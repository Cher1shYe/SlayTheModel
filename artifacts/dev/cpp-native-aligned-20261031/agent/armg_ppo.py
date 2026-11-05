"""On-policy PPO for public non-combat decisions; combat stays a fixed controller.

Adapted from ``sts2/agent/armg_ppo.py`` to this engine's public run observation
and legal-action features. Complete episodes only; the critic is independent of
the actor; forced decisions stay in the value trajectory but never train the
actor. The battle controller is external (MCTS or greedy) and is never trained
here: only the out-of-combat policy is PPO.

Information boundary: observations are ``public_observation`` (no draw order,
future RNG, or hidden pile content). The actor therefore only sees what a player
can see. The combat controller's own information access is documented separately
in the training configuration; do not describe this policy as a PPO-trained
battle agent. ``oracle`` combat (mcts-oracle) uses the simulator's full battle
state and future RNG and is recorded as such, never as a player-visible policy.
"""
from __future__ import annotations

import math

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, ArmGScorer


class ArmGActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.actor = ArmGScorer()
        self.critic = nn.Sequential(nn.Linear(ARMG_OBS_DIM, 128), nn.ReLU(),
                                    nn.Linear(128, 128), nn.ReLU(), nn.Linear(128, 1))

    def forward(self, obs, candidates):
        return self.actor(obs, candidates)

    def value(self, obs):
        return self.critic(obs).squeeze(-1)


class TrajectoryRecorder:
    """Records one row per non-combat decision while a run is played."""

    def __init__(self, model):
        self.model = model
        self.rows = []
        self.last_cumulative = 0.0

    @torch.no_grad()
    def record(self, obs, features, choice, forced, cumulative, *, bonus=None, allowed=None):
        if self.rows:
            self.rows[-1]["reward"] += float(cumulative - self.last_cumulative)
        tensor = torch.from_numpy(obs)[None]
        logits = self.model(tensor, torch.from_numpy(features)[None])[0]
        if bonus is not None:
            from .armg_need import apply_need_to_logits
            logits = apply_need_to_logits(logits, bonus, allowed, True)
        logp = F.log_softmax(logits.masked_fill(torch.isneginf(logits), -1e9), dim=0)
        value = float(self.model.value(tensor)[0])
        if not torch.isfinite(logp).all() or not math.isfinite(value):
            raise RuntimeError("nonfinite rollout prediction")
        self.rows.append({"obs": obs.copy(), "features": features.copy(),
                          "choice": int(choice), "old_logp": float(logp[choice]),
                          "need_bonus": None if bonus is None else np.array(bonus, copy=True),
                          "need_allowed": None if allowed is None else np.array(allowed, copy=True),
                          "old_logps": logp.numpy().copy(), "old_value": value,
                          "actor_valid": not forced and len(features) > 1,
                          "reward": float(cumulative) if not self.rows else 0.0})
        self.last_cumulative = float(cumulative)

    def finish(self, total):
        """Close the trajectory and check that increments sum to ``total``."""
        if self.rows:
            self.rows[-1]["reward"] += float(total - self.last_cumulative)
            total_gap = sum(r["reward"] for r in self.rows) - float(total)
            if not math.isclose(total_gap, 0.0, abs_tol=1e-6):
                raise RuntimeError(
                    f"transition rewards do not equal episode reward ({total_gap:+.9f})")
        rows, self.rows = self.rows, []
        return rows


def gae(rewards, values, gamma=1.0, lam=0.95):
    """Complete episode: true terminal bootstrap is zero, never a truncation."""
    if len(rewards) != len(values) or not 0 <= gamma <= 1 or not 0 <= lam <= 1:
        raise ValueError("invalid GAE inputs")
    rewards = np.asarray(rewards, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(rewards).all() or not np.isfinite(values).all():
        raise ValueError("nonfinite GAE inputs")
    advantages = np.zeros(len(rewards), dtype=np.float64)
    carry, following = 0.0, 0.0
    for i in range(len(rewards) - 1, -1, -1):
        delta = rewards[i] + gamma * following - values[i]
        carry = delta + gamma * lam * carry
        advantages[i] = carry
        following = values[i]
    return advantages.astype(np.float32), (advantages + values).astype(np.float32)


def prepare(episodes, gamma=1.0, lam=0.95):
    rows = []
    for ep in episodes:
        if ep["status"] != "terminated":
            raise ValueError("PPO only accepts complete episodes")
        trajectory = ep["ppo_records"]
        advantages, returns = gae([r["reward"] for r in trajectory],
                                  [r["old_value"] for r in trajectory], gamma, lam)
        for r, advantage, target in zip(trajectory, advantages, returns):
            rows.append(dict(r, advantage=float(advantage), target=float(target)))
    valid = [r["advantage"] for r in rows if r["actor_valid"]]
    if valid:
        mean, std = float(np.mean(valid)), float(np.std(valid))
        for r in rows:
            r["advantage"] = ((r["advantage"] - mean) / max(std, 1e-8)
                              if r["actor_valid"] else 0.0)
    return rows


def batch_tensors(rows):
    count = max(len(r["features"]) for r in rows)
    candidates = np.zeros((len(rows), count, ARMG_ACTION_DIM), dtype=np.float32)
    mask = np.zeros((len(rows), count), dtype=bool)
    old_logps = np.zeros((len(rows), count), dtype=np.float32)
    for i, r in enumerate(rows):
        n = len(r["features"])
        candidates[i, :n] = r["features"]
        mask[i, :n] = True
        old_logps[i, :n] = r["old_logps"]
    return (torch.from_numpy(np.stack([r["obs"] for r in rows])),
            torch.from_numpy(candidates), torch.from_numpy(mask), torch.from_numpy(old_logps))


def clipped_loss(log_ratio, advantages, clip_ratio):
    ratio = log_ratio.exp()
    return -torch.minimum(ratio * advantages,
                          ratio.clamp(1 - clip_ratio, 1 + clip_ratio) * advantages)


def policy_logps(model, obs, candidates, rows):
    """Replay the exact sampling transform, before padding variable action sets."""
    from .armg_need import apply_need_to_logits
    logits = model(obs, candidates)
    transformed = []
    for i, row in enumerate(rows):
        scores = logits[i, :len(row["features"])]
        if row.get("need_bonus") is not None:
            scores = apply_need_to_logits(scores, row["need_bonus"], row["need_allowed"], True)
        scores = scores.masked_fill(torch.isneginf(scores), -1e9)
        transformed.append(F.pad(scores, (0, candidates.shape[1] - len(scores)), value=-1e9))
    return F.log_softmax(torch.stack(transformed), dim=-1)


@torch.no_grad()
def diagnostics(model, rows, minibatch_size):
    kl_sum = entropy_sum = 0.0
    valid_count = 0.0
    predictions, targets = [], []
    for start in range(0, len(rows), minibatch_size):
        part = rows[start:start + minibatch_size]
        obs, candidates, mask, old_logps = batch_tensors(part)
        logps = policy_logps(model, obs, candidates, part)
        old_probs = old_logps.exp() * mask
        valid = torch.tensor([r["actor_valid"] for r in part], dtype=torch.bool)
        kl = (old_probs * (old_logps - logps)).sum(-1)
        entropy = -(logps.exp() * logps).sum(-1)
        kl_sum += float(kl[valid].sum())
        entropy_sum += float(entropy[valid].sum())
        valid_count += int(valid.sum())
        predictions.extend(model.value(obs).tolist())
        targets.extend(r["target"] for r in part)
    variance = float(np.var(targets)) if targets else 0.0
    return {"exact_kl": max(0.0, kl_sum / max(valid_count, 1)),
            "entropy": entropy_sum / max(valid_count, 1),
            "explained_variance": (1.0 - float(np.var(np.asarray(targets) - predictions)) / variance
                                   if variance > 1e-12 else None)}


def update(model, optimizer, episodes, *, epochs=4, minibatch_size=128, clip_ratio=0.2,
           target_kl=0.02, gamma=1.0, gae_lambda=0.95, value_coef=0.5, entropy_coef=0.01,
           max_grad_norm=0.5):
    if (epochs < 1 or minibatch_size < 1 or not 0 < clip_ratio < 1 or target_kl <= 0
            or max_grad_norm <= 0 or min(value_coef, entropy_coef) < 0):
        raise ValueError("invalid PPO hyperparameters")
    rows = prepare(episodes, gamma, gae_lambda)
    if not rows:
        raise ValueError("empty PPO rollout")
    valid_count = sum(r["actor_valid"] for r in rows)
    # Verify the frozen behaviour policy really matches the model before updates.
    initial = diagnostics(model, rows, minibatch_size)
    if initial["exact_kl"] > 1e-5:
        raise RuntimeError("stale/off-policy rollout: actor differs from sampling policy")
    model.train()
    updates = epochs_done = 0
    stopped = False
    sums = {key: 0.0 for key in ("policy_loss", "value_loss", "clip_fraction", "grad_norm")}
    metrics = initial
    for epoch in range(epochs):
        order = torch.randperm(len(rows)).tolist()
        for start in range(0, len(rows), minibatch_size):
            part = [rows[i] for i in order[start:start + minibatch_size]]
            obs, candidates, mask, old_logps = batch_tensors(part)
            logps = policy_logps(model, obs, candidates, part)
            indices = torch.tensor([r["choice"] for r in part])
            chosen = logps[torch.arange(len(part)), indices]
            old = torch.tensor([r["old_logp"] for r in part])
            valid = torch.tensor([r["actor_valid"] for r in part], dtype=torch.bool)
            log_ratio = chosen - old
            exact_kl = ((old_logps.exp() * mask) * (old_logps - logps)).sum(-1)
            if valid.any() and float(exact_kl[valid].mean().detach()) > 1.5 * target_kl:
                stopped = True
                break
            advantages = torch.tensor([r["advantage"] for r in part])
            scale = len(rows) / max(valid_count, 1)
            policy_loss = (clipped_loss(log_ratio, advantages, clip_ratio) * valid).mean() * scale
            entropy = (-(logps.exp() * logps).sum(-1) * valid).mean() * scale
            value_loss = 0.5 * (model.value(obs) - torch.tensor([r["target"] for r in part])).square().mean()
            loss = policy_loss + value_coef * value_loss - entropy_coef * entropy
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite PPO loss")
            optimizer.zero_grad()
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm,
                                                  error_if_nonfinite=True)
            optimizer.step()
            updates += 1
            for key, value in [("policy_loss", policy_loss), ("value_loss", value_loss),
                               ("grad_norm", norm)]:
                sums[key] += float(value.detach())
            sums["clip_fraction"] += (float(((log_ratio.exp() - 1).abs() > clip_ratio)[valid]
                                            .float().mean())
                                      if valid.any() else 0.0)
        epochs_done = epoch + 1
        metrics = diagnostics(model, rows, minibatch_size)
        if stopped or metrics["exact_kl"] > 1.5 * target_kl:
            stopped = True
            break
    return {**{key: value / max(updates, 1) for key, value in sums.items()}, **metrics,
            "updates": updates, "epochs": epochs_done, "kl_early_stop": stopped,
            "decisions": len(rows), "actor_decisions": valid_count}
