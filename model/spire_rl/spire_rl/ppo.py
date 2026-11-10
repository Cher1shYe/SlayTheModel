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
from .model import SpireNet


def compute_gae(ep: Episode, gamma: float, lam: float) -> None:
    """Fills ep.advantages / ep.returns.

    Real death or victory: no bootstrap. Trusted truncation: bootstrap from
    V(final state) without continuing the trace. Failures are never passed in.
    """
    T = len(ep)
    values = np.asarray(ep.value, np.float64)
    rewards = np.asarray([r[0] for r in ep.reward], np.float64)
    adv = np.zeros(T, np.float64)
    nxt_adv = 0.0
    for t in reversed(range(T)):
        if t == T - 1:
            if ep.outcome == Outcome.TRUNCATED:
                next_value, bootstrap, trace = ep.bootstrap_value, 1.0, 0.0
            else:
                next_value, bootstrap, trace = 0.0, 0.0, 0.0
        else:
            next_value, bootstrap, trace = values[t + 1], 1.0, 1.0
        delta = rewards[t] + gamma * bootstrap * next_value - values[t]
        nxt_adv = delta + gamma * lam * trace * nxt_adv
        adv[t] = nxt_adv
    ep.advantages = adv.astype(np.float32)
    ep.returns = (adv + values).astype(np.float32)


def prepare(episodes: list[Episode], cfg: PPOConfig) -> list[tuple[Episode, int]]:
    """Labels, GAE and the flat target list of one rollout (failures excluded)."""
    targets = []
    for ep in episodes:
        if ep.outcome == Outcome.FAILURE or len(ep) == 0:
            continue
        ep.aux = aux_labels(ep.info["log"], len(ep), ep.outcome)
        compute_gae(ep, cfg.gamma, cfg.gae_lambda)
        targets.extend((ep, t) for t in range(len(ep)))
    return targets


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


def ppo_update(model: SpireNet, optimizer: torch.optim.Optimizer, targets, cfg: PPOConfig,
               entropy_coef: float, window: int, device: torch.device, rng: random.Random) -> UpdateStats:
    started = time.perf_counter()
    stats = {k: [] for k in ("policy_loss", "value_loss", "entropy", "approx_kl", "clip_frac",
                             "aux_survival_loss", "aux_hp_loss", "aux_act_loss", "grad_norm")}
    adv_all = _gather(targets, "advantages")
    adv_mean, adv_std = float(adv_all.mean()), float(adv_all.std() + 1e-8)
    epochs_done, steps, stopped = 0, 0, False
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
            kl_sum = clip_sum = ent_sum = pl_sum = vl_sum = 0.0
            aux_sums = np.zeros(3)
            for m0 in range(0, n, cfg.microbatch):
                micro = batch[m0:m0 + cfg.microbatch]
                b = collate(micro, window).to(device)
                with _autocast(device, cfg.bf16):
                    out = model(b)
                logits = out.logits
                logp_all = torch.log_softmax(logits, -1)
                actions = torch.tensor([ep.actions[t] for ep, t in micro], device=device)
                logp = logp_all.gather(1, actions[:, None])[:, 0]
                old_logp = torch.tensor(_gather(micro, "logp"), device=device)
                adv = (torch.tensor(_gather(micro, "advantages"), device=device) - adv_mean) / adv_std
                ret = torch.tensor(_gather(micro, "returns"), device=device)
                ratio = torch.exp(logp - old_logp)
                pg = -torch.min(ratio * adv, ratio.clamp(1 - cfg.clip, 1 + cfg.clip) * adv)
                probs = logp_all.exp()
                entropy = -(probs * logp_all.masked_fill(~b.cand_mask, 0.0)).sum(-1)
                vloss = F.huber_loss(out.value, ret, delta=cfg.value_huber_delta, reduction="none")
                aux = torch.tensor(np.stack([ep.aux[t] for ep, t in micro]), device=device)
                surv = F.binary_cross_entropy_with_logits(out.aux[:, 0], aux[:, 0], reduction="none") * aux[:, 3]
                hp = F.huber_loss(torch.sigmoid(out.aux[:, 1]), aux[:, 1], delta=cfg.aux_hp_huber_delta,
                                  reduction="none") * aux[:, 4]
                act = F.binary_cross_entropy_with_logits(out.aux[:, 2], aux[:, 2], reduction="none") * aux[:, 5]
                loss = ((pg + cfg.value_coef * vloss - entropy_coef * entropy).sum() / n
                        + cfg.aux_survival_coef * surv.sum() / aux_counts[0]
                        + cfg.aux_hp_coef * hp.sum() / aux_counts[1]
                        + cfg.aux_act_coef * act.sum() / aux_counts[2])
                loss.backward()
                with torch.no_grad():
                    log_ratio = logp - old_logp
                    kl_sum += float(((ratio - 1) - log_ratio).sum())
                    clip_sum += float(((ratio - 1).abs() > cfg.clip).float().sum())
                    ent_sum += float(entropy.sum())
                    pl_sum += float(pg.sum())
                    vl_sum += float(vloss.sum())
                    aux_sums += [float(surv.sum()), float(hp.sum()), float(act.sum())]
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.max_grad_norm)
            optimizer.step()
            steps += 1
            approx_kl = kl_sum / n
            stats["policy_loss"].append(pl_sum / n)
            stats["value_loss"].append(vl_sum / n)
            stats["entropy"].append(ent_sum / n)
            stats["approx_kl"].append(approx_kl)
            stats["clip_frac"].append(clip_sum / n)
            stats["aux_survival_loss"].append(aux_sums[0] / aux_counts[0])
            stats["aux_hp_loss"].append(aux_sums[1] / aux_counts[1])
            stats["aux_act_loss"].append(aux_sums[2] / aux_counts[2])
            stats["grad_norm"].append(float(grad_norm))
            if approx_kl > 1.5 * cfg.target_kl:
                stopped = True
                break
        epochs_done = epoch + 1
        if stopped:
            break
    summary = {k: (float(np.mean(v)) if v else math.nan) for k, v in stats.items()}
    summary.update(optimizer_steps=steps, epochs=epochs_done, kl_early_stop=stopped,
                   targets=len(targets), update_seconds=time.perf_counter() - started,
                   adv_mean=adv_mean, adv_std=adv_std)
    return UpdateStats(summary)
