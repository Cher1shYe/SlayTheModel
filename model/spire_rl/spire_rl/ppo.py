"""GAE and the PPO update (clipped policy, Huber value, entropy, auxiliary heads)."""
from __future__ import annotations

import contextlib
import math
import random
import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F

from .config import PPOConfig
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


def prepare(episodes: list[Episode], cfg: PPOConfig) -> list[tuple[Episode, int]]:
    """Labels, GAE and the flat target list of one rollout (failures excluded).

    Each episode carries ``info["value_weights"]`` from its collection alpha.
    """
    targets = []
    for ep in episodes:
        if ep.outcome == Outcome.FAILURE or len(ep) == 0:
            continue
        ep.aux = aux_labels(ep.info["log"], len(ep), ep.outcome)
        compute_gae(ep, cfg.gamma, cfg.gae_lambda, ep.info.get("value_weights"))
        targets.extend((ep, t) for t in range(len(ep)))
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


def ppo_update(model: SpireNet, optimizer: torch.optim.Optimizer, targets, cfg: PPOConfig,
               entropy_coef: float, window: int, device: torch.device, rng: random.Random,
               critic: SpireNet | None = None, critic_optimizer: torch.optim.Optimizer | None = None) -> UpdateStats:
    """Clipped PPO on the policy. With a separate ``critic`` the policy loss has no value term
    and the critic gets its own value-only passes afterwards (``critic_update``).

    Early stop: every ``kl_check_every`` steps the KL is measured on a fixed sample of
    ``kl_check_targets`` targets and the update stops above 1.5 * target_kl; a single
    minibatch above ``kl_hard_mult`` * target_kl also stops it.
    """
    started = time.perf_counter()
    stats = {k: [] for k in ("policy_loss", "value_loss", "entropy", "entropy_group", "approx_kl", "clip_frac",
                             "aux_survival_loss", "aux_hp_loss", "aux_act_loss", "grad_norm")}
    adv_all = _gather(targets, "advantages")
    adv_mean, adv_std = float(adv_all.mean()), float(adv_all.std() + 1e-8)
    epochs_done, steps, stopped, stop_reason, processed = 0, 0, False, "", 0
    kl_sample = rng.sample(targets, min(len(targets), cfg.kl_check_targets)) if targets else []
    kl_checks: list[float] = []
    shared_value = critic is None
    model.train()
    for epoch in range(cfg.epochs):
        order = list(range(len(targets)))
        rng.shuffle(order)
        for start in range(0, len(order), cfg.batch_targets):
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
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.max_grad_norm)
            optimizer.step()
            steps += 1
            processed += n
            approx_kl = kl_sum / n
            stats["policy_loss"].append(pl_sum / n)
            stats["value_loss"].append(vl_sum / n)
            stats["entropy"].append(ent_sum / n)
            stats["entropy_group"].append(gent_sum / n)
            stats["approx_kl"].append(approx_kl)
            stats["clip_frac"].append(clip_sum / n)
            stats["aux_survival_loss"].append(aux_sums[0] / aux_counts[0])
            stats["aux_hp_loss"].append(aux_sums[1] / aux_counts[1])
            stats["aux_act_loss"].append(aux_sums[2] / aux_counts[2])
            stats["grad_norm"].append(float(grad_norm))
            if approx_kl > cfg.kl_hard_mult * cfg.target_kl:
                stopped, stop_reason = True, "minibatch_kl"
                break
            if steps % cfg.kl_check_every == 0:
                kl = sampled_kl(model, kl_sample, window, device, cfg.bf16, cfg.microbatch)
                kl_checks.append(kl)
                if kl > 1.5 * cfg.target_kl:
                    stopped, stop_reason = True, "sampled_kl"
                    break
        epochs_done = epoch + 1
        if stopped:
            break
    summary = {k: (float(np.mean(v)) if v else math.nan) for k, v in stats.items()}
    if not shared_value:
        summary.pop("value_loss")
    # `epochs` counts epochs entered; `target_passes` is the work actually done.
    summary.update(optimizer_steps=steps, epochs=epochs_done, kl_early_stop=stopped, kl_stop_reason=stop_reason,
                   targets=len(targets), adv_mean=adv_mean, adv_std=adv_std,
                   approx_kl_max=float(max(stats["approx_kl"])) if stats["approx_kl"] else math.nan,
                   sampled_kl_last=kl_checks[-1] if kl_checks else math.nan,
                   target_passes=processed / max(1, len(targets)))
    if critic is not None and critic_optimizer is not None and targets:
        summary.update(critic_update(critic, critic_optimizer, targets, cfg, critic.cfg.window, device, rng))
    summary["update_seconds"] = time.perf_counter() - started
    return UpdateStats(summary)
