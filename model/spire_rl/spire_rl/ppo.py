"""GAE and the PPO update (clipped policy, Huber value, entropy, auxiliary heads)."""
from __future__ import annotations

import contextlib
import copy
import math
import random
import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F

from .config import ForkConfig, PPOConfig
from .data import Episode, collate
from .env import Outcome, aux_labels
from .model import VALUE_SCALE, SpireNet


def _gae(rewards: np.ndarray, values: np.ndarray, bootstrap_value: float, truncated: bool,
         gamma: float, lam: float) -> np.ndarray:
    T = len(rewards)
    adv = np.zeros(T, np.float64)
    nxt_adv = 0.0
    for t in reversed(range(T)):
        if t == T - 1:
            if truncated:
                next_value, bootstrap, trace = bootstrap_value, 1.0, 0.0
            else:
                next_value, bootstrap, trace = 0.0, 0.0, 0.0
        else:
            next_value, bootstrap, trace = values[t + 1], 1.0, 1.0
        delta = rewards[t] + gamma * bootstrap * next_value - values[t]
        nxt_adv = delta + gamma * lam * trace * nxt_adv
        adv[t] = nxt_adv
    return adv


def compute_gae(ep: Episode, gamma: float, lam: float, weights: tuple[float, float, float] | None = None) -> None:
    """Fills ep.advantages / ep.returns (and ep.comp_returns with ``weights``).

    Real death or victory: no bootstrap. Trusted truncation: bootstrap from
    V(final state) without continuing the trace. Failures are never passed in.

    With ``weights`` (r_train per raw floor / act entry / win at this episode's
    alpha) GAE runs on each return component with the critic's component
    values; the policy advantage is their weighted sum, which equals GAE on
    r_train with V = sum(w_k V_k). Without weights: scalar GAE on r_train.
    """
    truncated = ep.outcome == Outcome.TRUNCATED
    if weights is None:
        rewards = np.asarray([r[0] for r in ep.reward], np.float64)
        values = np.asarray(ep.value, np.float64)
        adv = _gae(rewards, values, ep.bootstrap_value, truncated, gamma, lam)
        ep.advantages = adv.astype(np.float32)
        ep.returns = (adv + values).astype(np.float32)
        return
    scale = np.asarray(VALUE_SCALE, np.float64)
    comps = np.asarray(ep.value_comps, np.float64).reshape(len(ep), 3) * scale        # raw units
    boot = (np.asarray(ep.bootstrap_comps, np.float64) * scale if ep.bootstrap_comps is not None
            else np.zeros(3))
    events = np.asarray([r[1:4] for r in ep.reward], np.float64)                      # floors, acts, win
    adv_k = np.stack([_gae(events[:, k], comps[:, k], boot[k], truncated, gamma, lam) for k in range(3)], 1)
    ret_k = adv_k + comps
    w = np.asarray(weights, np.float64)
    ep.advantages = (adv_k @ w).astype(np.float32)
    ep.returns = (ret_k @ w).astype(np.float32)
    ep.comp_returns = (ret_k / scale).astype(np.float32)


def prepare(episodes: list[Episode], cfg: PPOConfig, fork_seeds: int = 0) -> list[tuple[Episode, int]]:
    """Labels, GAE and the flat target list of one rollout (failures excluded).

    Each episode carries ``info["value_weights"]`` from its collection alpha.
    Completed paired forks become ``ep.fork_targets[t] = (options, groups,
    group_level, advantages)``: option returns minus their mean, divided by the
    standard deviation of all such centred returns of the same screen in this
    rollout (campfire, map and card forks have different horizons and spreads).
    """
    from .rollout import fork_option_returns
    targets, centred, screens = [], {}, {}
    for ep in episodes:
        if ep.outcome == Outcome.FAILURE or len(ep) == 0:
            continue
        ep.aux = aux_labels(ep.info["log"], len(ep), ep.outcome)
        compute_gae(ep, cfg.gamma, cfg.gae_lambda, ep.info.get("value_weights"))
        targets.extend((ep, t) for t in range(len(ep)))
        ep.fork_targets = {}
        for fork in ep.info.get("forks", []):
            r = fork_option_returns(fork, fork_seeds) if fork_seeds else None
            if r is None or len(r) < 2:
                continue
            c = r - r.mean()
            ep.fork_targets[fork.t] = (fork.options, fork.groups, fork.group_level, c)
            centred.setdefault(fork.screen, []).append(c)
            screens[(ep.episode_id, fork.t)] = fork.screen
    scale = {screen: float(np.concatenate(cs).std()) + 1e-8 for screen, cs in centred.items()}
    for ep, t in targets:
        if t in ep.fork_targets:
            o, g, gl, c = ep.fork_targets[t]
            ep.fork_targets[t] = (o, g, gl, c / scale[screens[(ep.episode_id, t)]])
    return targets


def critic_quality(targets) -> dict:
    """On-policy explained variance of the critic used for this rollout's advantages.

    In run main-a0-s1 this stayed <= 0 (critic ~ constant) while value_loss looked small.
    """
    if not targets:
        return {}
    v = _gather(targets, "value")
    ret = _gather(targets, "returns")
    var = float(np.var(ret))
    out = {"value_ev": (1.0 - float(np.var(ret - v)) / var) if var > 0 else float("nan"),
           "value_pred_std": float(np.std(v)), "return_std": float(np.sqrt(var))}
    eps = [ep for ep, t in targets if ep.comp_returns is not None]
    if eps:
        comp_v = np.stack([np.asarray(ep.value_comps[t]) for ep, t in targets])
        comp_r = np.stack([ep.comp_returns[t] for ep, t in targets])
        for k, name in enumerate(("floors", "acts", "win")):
            vr = float(np.var(comp_r[:, k]))
            out[f"value_ev_{name}"] = (1.0 - float(np.var(comp_r[:, k] - comp_v[:, k])) / vr) if vr > 0 else float("nan")
    return out


def _autocast(device: torch.device, bf16: bool):
    if device.type == "cuda" and bf16:
        return torch.autocast("cuda", dtype=torch.bfloat16)
    return contextlib.nullcontext()


@dataclass
class UpdateStats:
    values: dict

    def __getitem__(self, key):
        return self.values[key]


def _gather(eps_t, field, index=None):
    out = []
    for ep, t in eps_t:
        v = getattr(ep, field)
        out.append(v[t] if index is None else v[t][index])
    return np.asarray(out, np.float32)


def recompute_check(model: SpireNet, targets, window: int, device, bf16: bool, limit: int = 64) -> float:
    """Max |logp_saved - logp_recomputed| with unchanged parameters."""
    model.eval()
    sample = targets[:limit]
    with torch.no_grad(), _autocast(device, bf16):
        out = model(collate(sample, window).to(device))
    logp = torch.log_softmax(out.logits, -1)
    actions = torch.tensor([ep.actions[t] for ep, t in sample], device=device)
    new = logp.gather(1, actions[:, None])[:, 0].cpu().numpy()
    old = _gather(sample, "logp")
    return float(np.abs(new - old).max()) if len(sample) else 0.0


def sampled_kl(model: SpireNet, sample, window: int, device, bf16: bool, microbatch: int) -> float:
    """Mean approx KL(old || current) over a fixed sample of the rollout (no grad)."""
    total, n = 0.0, 0
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            for m0 in range(0, len(sample), max(1, microbatch * 4)):
                micro = sample[m0:m0 + max(1, microbatch * 4)]
                with _autocast(device, bf16):
                    out = model(collate(micro, window).to(device))
                logp_all = torch.log_softmax(out.logits.float(), -1)
                actions = torch.tensor([ep.actions[t] for ep, t in micro], device=device)
                log_ratio = logp_all.gather(1, actions[:, None])[:, 0] - torch.tensor(_gather(micro, "logp"), device=device)
                total += float(((log_ratio.exp() - 1) - log_ratio).sum())
                n += len(micro)
    finally:
        model.train(was_training)
    return total / max(1, n)


def _value_loss(out_value, micro, cfg: PPOConfig, device):
    comp_ret = torch.tensor(np.stack([ep.comp_returns[t] for ep, t in micro]), device=device)
    return F.huber_loss(out_value, comp_ret, delta=cfg.value_huber_delta, reduction="none").sum(-1)


def critic_update(critic: SpireNet, optimizer: torch.optim.Optimizer, targets, cfg: PPOConfig, window: int,
                  device: torch.device, rng: random.Random) -> dict:
    """Value-only passes of the separate critic; independent of the policy's KL stop."""
    critic.train()
    losses, norms, steps = [], [], 0
    for _ in range(cfg.value_epochs):
        order = list(range(len(targets)))
        rng.shuffle(order)
        for start in range(0, len(order), cfg.batch_targets):
            batch = [targets[i] for i in order[start:start + cfg.batch_targets]]
            n = len(batch)
            optimizer.zero_grad(set_to_none=True)
            total = 0.0
            for m0 in range(0, n, cfg.microbatch):
                micro = batch[m0:m0 + cfg.microbatch]
                with _autocast(device, cfg.bf16):
                    out = critic(collate(micro, window).to(device))
                loss = _value_loss(out.value, micro, cfg, device)
                (loss.sum() / n).backward()
                total += float(loss.detach().sum())
            norms.append(float(torch.nn.utils.clip_grad_norm_(critic.parameters(), cfg.max_grad_norm)))
            optimizer.step()
            steps += 1
            losses.append(total / n)
    return {"value_loss": float(np.mean(losses)) if losses else math.nan,
            "value_loss_last_epoch": float(np.mean(losses[-max(1, len(losses) // max(1, cfg.value_epochs)):]))
            if losses else math.nan,
            "critic_grad_norm": float(np.mean(norms)) if norms else math.nan, "critic_steps": steps}


def fork_targets_of(targets) -> list[tuple[Episode, int]]:
    """The decisions of ``targets`` that carry a completed paired fork (see ``prepare``)."""
    return [(ep, t) for ep, t in targets if t in getattr(ep, "fork_targets", {})]


def _fork_option_logp(out, logp_all: torch.Tensor, i: int, ft) -> torch.Tensor:
    """Log-probabilities of the compared options of fork target ``ft`` (row ``i`` of a batch),
    renormalized over those options: whole action groups for campfire forks, single
    candidates for map and card forks."""
    opts, groups, group_level, _ = ft
    if group_level and out.group_logp is not None:
        lps = out.group_logp[i, torch.tensor(groups, device=logp_all.device)]
    else:
        lps = logp_all[i, torch.tensor(opts, device=logp_all.device)]
    return torch.log_softmax(lps.float(), -1)


def fork_target(ref_logp: torch.Tensor, advantages: torch.Tensor, fork: ForkConfig) -> torch.Tensor:
    """Target distribution over the compared options of one fork decision.

    ``ref_logp``: the policy over those options at the start of the update. Each option's
    log-odds move by ``target_scale`` per unit of (clipped) normalized advantage. An option
    below ``prob_floor`` is treated as being at the floor, so the target never follows the
    policy to zero: with equal advantages the target equals the policy wherever every
    option is above the floor and lifts the ones below it.
    """
    base = torch.log(ref_logp.exp().clamp(min=fork.prob_floor))
    return torch.softmax(base + fork.target_scale * advantages.clamp(-fork.adv_clip, fork.adv_clip), -1)


def fork_reference(model: SpireNet, pool, window: int, device, bf16: bool, fork: ForkConfig,
                   microbatch: int) -> tuple[list[torch.Tensor], list[float]]:
    """Targets of all fork decisions in ``pool`` from the current (pre-update) policy, and
    the lowest log-probability among each decision's compared options (how far the policy
    has pushed an option away; round 4 reached about -5000)."""
    was_training = model.training
    model.eval()
    targets, lowest = [], []
    with torch.no_grad():
        for m0 in range(0, len(pool), max(1, microbatch * 4)):
            micro = pool[m0:m0 + max(1, microbatch * 4)]
            with _autocast(device, bf16):
                out = model(collate(micro, window).to(device))
            logp_all = torch.log_softmax(out.logits.float(), -1)
            for i, (ep, t) in enumerate(micro):
                ft = ep.fork_targets[t]
                ref = _fork_option_logp(out, logp_all, i, ft)
                adv = torch.tensor(ft[3], device=device, dtype=ref.dtype)
                targets.append(fork_target(ref, adv, fork))
                lowest.append(float(ref.min()))
    model.train(was_training)
    return targets, lowest


def _snapshot(model: SpireNet, into: list[torch.Tensor] | None) -> list[torch.Tensor]:
    with torch.no_grad():
        if into is None:
            return [p.detach().clone() for p in model.parameters()]
        for buf, p in zip(into, model.parameters()):
            buf.copy_(p)
    return into


def _restore(model: SpireNet, saved: list[torch.Tensor]) -> None:
    with torch.no_grad():
        for p, buf in zip(model.parameters(), saved):
            p.copy_(buf)


def ppo_update(model: SpireNet, optimizer: torch.optim.Optimizer, targets, cfg: PPOConfig,
               entropy_coef: float, window: int, device: torch.device, rng: random.Random,
               critic: SpireNet | None = None, critic_optimizer: torch.optim.Optimizer | None = None,
               fork: ForkConfig | None = None, critic_targets=None, fork_pool=None) -> UpdateStats:
    """Clipped PPO on the policy. With a separate ``critic`` the policy loss has no value term
    and the critic gets its own value-only passes afterwards (``critic_update``).

    KL limit. Each minibatch's forward pass measures the policy before its own step; above
    ``kl_hard_mult`` * target_kl the update stops. Every ``kl_check_every`` steps (and after
    the last step) the KL is also measured on a fixed sample of ``kl_check_targets`` targets;
    above 1.5 * target_kl (or non-finite) the update stops. With ``kl_rollback`` a stop
    restores parameters AND optimizer state from the latest passing fixed-sample check.
    This may discard several steps: the immediately preceding step need not be safe.

    Fork loss (``fork`` enabled): every step also trains on a share of ``fork_pool`` (default:
    the fork decisions among ``targets``; the trainer adds those of earlier rollouts), so one
    pass over the targets is one pass over the pool. See ``ForkConfig`` for the loss.
    """
    started = time.perf_counter()
    stats = {k: [] for k in ("policy_loss", "value_loss", "entropy", "entropy_group", "approx_kl", "clip_frac",
                             "aux_survival_loss", "aux_hp_loss", "aux_act_loss", "grad_norm", "fork_loss")}
    adv_all = _gather(targets, "advantages")
    adv_mean, adv_std = float(adv_all.mean()), float(adv_all.std() + 1e-8)
    epochs_done, steps, stopped, stop_reason, processed = 0, 0, False, "", 0
    kl_sample = rng.sample(targets, min(len(targets), cfg.kl_check_targets)) if targets else []
    kl_checks: list[float] = []
    kl_limit = 1.5 * cfg.target_kl
    shared_value = critic is None
    use_forks = fork is not None and fork.enabled and fork.coef > 0
    pool = (list(fork_pool) if fork_pool is not None else fork_targets_of(targets)) if use_forks else []
    fork_q, fork_lowest = (fork_reference(model, pool, window, device, cfg.bf16, fork, cfg.microbatch)
                           if pool else ([], []))
    steps_per_epoch = max(1, math.ceil(len(targets) / cfg.batch_targets))
    fork_per_step = math.ceil(len(pool) / steps_per_epoch) if pool else 0
    fork_n = 0
    safe: list[torch.Tensor] | None = None
    safe_optimizer = None
    safe_steps = safe_processed = safe_fork_n = 0
    rolled_back, rollback_steps = False, 0

    def remember_safe() -> None:
        nonlocal safe, safe_optimizer, safe_steps, safe_processed, safe_fork_n
        if cfg.kl_rollback:
            safe = _snapshot(model, safe)
            safe_optimizer = copy.deepcopy(optimizer.state_dict())
            safe_steps, safe_processed, safe_fork_n = steps, processed, fork_n

    def roll_back() -> None:
        nonlocal steps, processed, fork_n, rolled_back, rollback_steps
        if cfg.kl_rollback and safe is not None and steps > safe_steps and not rolled_back:
            _restore(model, safe)
            optimizer.load_state_dict(safe_optimizer)
            rollback_steps = steps - safe_steps
            steps, processed, fork_n = safe_steps, safe_processed, safe_fork_n
            rolled_back = True
        if cfg.kl_rollback:
            optimizer.zero_grad(set_to_none=True)

    if cfg.kl_rollback and kl_sample:
        initial_kl = sampled_kl(model, kl_sample, window, device, cfg.bf16, cfg.microbatch)
        if not math.isfinite(initial_kl) or initial_kl > kl_limit:
            raise RuntimeError(f"initial sampled KL {initial_kl:.6g} exceeds limit {kl_limit:.6g} "
                               "or is non-finite; no verified state to roll back to")
        remember_safe()

    model.train()
    for epoch in range(cfg.epochs):
        order = list(range(len(targets)))
        rng.shuffle(order)
        fork_order = list(range(len(pool)))
        rng.shuffle(fork_order)
        for step_in_epoch, start in enumerate(range(0, len(order), cfg.batch_targets)):
            batch = [targets[i] for i in order[start:start + cfg.batch_targets]]
            n = len(batch)
            aux_all = np.stack([ep.aux[t] for ep, t in batch])
            aux_counts = np.maximum(aux_all[:, 3:].sum(0), 1.0)
            optimizer.zero_grad(set_to_none=True)
            kl_sum = clip_sum = ent_sum = gent_sum = pl_sum = vl_sum = 0.0
            aux_sums = np.zeros(3)
            for m0 in range(0, n, cfg.microbatch):
                micro = batch[m0:m0 + cfg.microbatch]
                b = collate(micro, window).to(device)
                with _autocast(device, cfg.bf16):
                    out = model(b)
                logp_all = torch.log_softmax(out.logits, -1)
                actions = torch.tensor([ep.actions[t] for ep, t in micro], device=device)
                logp = logp_all.gather(1, actions[:, None])[:, 0]
                old_logp = torch.tensor(_gather(micro, "logp"), device=device)
                adv = (torch.tensor(_gather(micro, "advantages"), device=device) - adv_mean) / adv_std
                ratio = torch.exp(logp - old_logp)
                pg = -torch.min(ratio * adv, ratio.clamp(1 - cfg.clip, 1 + cfg.clip) * adv)
                probs = logp_all.exp()
                entropy = -(probs * logp_all.masked_fill(~b.cand_mask, 0.0)).sum(-1)
                if out.group_logp is not None:
                    group_entropy = -(out.group_logp.exp() * out.group_logp).sum(-1)
                else:
                    group_entropy = torch.zeros_like(entropy)
                vloss = _value_loss(out.value, micro, cfg, device) if shared_value else torch.zeros_like(entropy)
                aux = torch.tensor(np.stack([ep.aux[t] for ep, t in micro]), device=device)
                surv = F.binary_cross_entropy_with_logits(out.aux[:, 0], aux[:, 0], reduction="none") * aux[:, 3]
                hp = F.huber_loss(torch.sigmoid(out.aux[:, 1]), aux[:, 1], delta=cfg.aux_hp_huber_delta,
                                  reduction="none") * aux[:, 4]
                act = F.binary_cross_entropy_with_logits(out.aux[:, 2], aux[:, 2], reduction="none") * aux[:, 5]
                loss = ((pg + cfg.value_coef * vloss - entropy_coef * entropy
                         - cfg.type_entropy_coef * group_entropy).sum() / n
                        + cfg.aux_survival_coef * surv.sum() / aux_counts[0]
                        + cfg.aux_hp_coef * hp.sum() / aux_counts[1]
                        + cfg.aux_act_coef * act.sum() / aux_counts[2])
                loss.backward()
                with torch.no_grad():
                    log_ratio = logp - old_logp
                    kl_sum += float(((ratio - 1) - log_ratio).sum())
                    clip_sum += float(((ratio - 1).abs() > cfg.clip).float().sum())
                    ent_sum += float(entropy.sum())
                    gent_sum += float(group_entropy.sum())
                    pl_sum += float(pg.sum())
                    vl_sum += float(vloss.sum())
                    aux_sums += [float(surv.sum()), float(hp.sum()), float(act.sum())]
            approx_kl = kl_sum / n          # of the policy before this batch's step, on this batch
            stats["policy_loss"].append(pl_sum / n)
            stats["value_loss"].append(vl_sum / n)
            stats["entropy"].append(ent_sum / n)
            stats["entropy_group"].append(gent_sum / n)
            stats["approx_kl"].append(approx_kl)
            stats["clip_frac"].append(clip_sum / n)
            stats["aux_survival_loss"].append(aux_sums[0] / aux_counts[0])
            stats["aux_hp_loss"].append(aux_sums[1] / aux_counts[1])
            stats["aux_act_loss"].append(aux_sums[2] / aux_counts[2])
            if not math.isfinite(approx_kl) or approx_kl > cfg.kl_hard_mult * cfg.target_kl:
                stopped, stop_reason = True, "minibatch_kl"
                roll_back()
                break
            fork_idx = fork_order[step_in_epoch * fork_per_step:(step_in_epoch + 1) * fork_per_step]
            fl_sum = 0.0
            for m0 in range(0, len(fork_idx), cfg.microbatch):
                idx = fork_idx[m0:m0 + cfg.microbatch]
                micro = [pool[i] for i in idx]
                with _autocast(device, cfg.bf16):
                    out = model(collate(micro, window).to(device))
                logp_all = torch.log_softmax(out.logits.float(), -1)
                terms = []
                for row, (i, (ep, t)) in enumerate(zip(idx, micro)):
                    lps = _fork_option_logp(out, logp_all, row, ep.fork_targets[t])
                    q = fork_q[i]
                    terms.append((torch.special.xlogy(q, q) - q * lps).sum())   # KL(target || policy)
                fork_loss = torch.stack(terms).sum()
                (fork.coef * fork_loss / n).backward()
                fl_sum += float(fork_loss.detach())
            if fork_idx:
                stats["fork_loss"].append(fl_sum / len(fork_idx))
                fork_n += len(fork_idx)
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.max_grad_norm)
            stats["grad_norm"].append(float(grad_norm))
            optimizer.step()
            steps += 1
            processed += n
            if steps % cfg.kl_check_every == 0:
                kl = sampled_kl(model, kl_sample, window, device, cfg.bf16, cfg.microbatch)
                kl_checks.append(kl)
                if not math.isfinite(kl) or kl > kl_limit:
                    stopped, stop_reason = True, "sampled_kl"
                    roll_back()
                    break
                remember_safe()
        epochs_done = epoch + 1
        if stopped:
            break
    # Check the policy actually kept, including after an early stop and when the update
    # ends between periodic checks. Never silently keep an unverified restored state.
    kl_final = math.nan
    if kl_sample:
        kl_final = sampled_kl(model, kl_sample, window, device, cfg.bf16, cfg.microbatch)
        if not math.isfinite(kl_final) or kl_final > kl_limit:
            kl_checks.append(kl_final)
            stopped, stop_reason = True, stop_reason or "sampled_kl"
            roll_back()
            if cfg.kl_rollback:
                kl_final = sampled_kl(model, kl_sample, window, device, cfg.bf16, cfg.microbatch)
                if not math.isfinite(kl_final) or kl_final > kl_limit:
                    raise RuntimeError(f"restored sampled KL {kl_final:.6g} exceeds limit {kl_limit:.6g} "
                                       "or is non-finite")
    summary = {k: (float(np.mean(v)) if v else math.nan) for k, v in stats.items()}
    if not shared_value:
        summary.pop("value_loss")
    # `epochs` counts epochs entered; `target_passes` is the work actually kept.
    summary.update(optimizer_steps=steps, epochs=epochs_done, kl_early_stop=stopped, kl_stop_reason=stop_reason,
                   kl_rollback=rolled_back, kl_rollback_steps=rollback_steps,
                   targets=len(targets), adv_mean=adv_mean, adv_std=adv_std,
                   approx_kl_max=float(max(stats["approx_kl"])) if stats["approx_kl"] else math.nan,
                   sampled_kl_last=kl_checks[-1] if kl_checks else math.nan, sampled_kl_final=kl_final,
                   target_passes=processed / max(1, len(targets)), fork_targets_seen=fork_n,
                   fork_pool=len(pool),
                   fork_option_logp_min=float(np.median(fork_lowest)) if fork_lowest else math.nan)
    if critic is not None and critic_optimizer is not None and targets:
        ct = critic_targets if critic_targets is not None else targets
        summary.update(critic_update(critic, critic_optimizer, ct, cfg, critic.cfg.window, device, rng))
        summary["critic_targets"] = len(ct)
    summary["update_seconds"] = time.perf_counter() - started
    return UpdateStats(summary)
