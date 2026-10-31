"""On-policy PPO for public non-combat decisions; combat remains external.

Complete episodes only, undiscounted reward by default, independent critic.
Forced decisions stay in the value trajectory but never train the actor.
"""
from __future__ import annotations

import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .armg import ArmGScorer, ARMG_OBS_DIM, ARMG_ACTION_DIM


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
    def __init__(self, model):
        self.model = model
        self.rows = []
        self.last_cumulative = 0.0

    @torch.no_grad()
    def record(self, obs, features, choice, forced, cumulative):
        if self.rows:
            self.rows[-1]['reward'] += float(cumulative - self.last_cumulative)
        tensor = torch.from_numpy(obs)[None]
        logits = self.model(tensor, torch.from_numpy(features)[None])[0]
        logp = F.log_softmax(logits, dim=0)
        value = float(self.model.value(tensor)[0])
        if not torch.isfinite(logp).all() or not math.isfinite(value):
            raise RuntimeError('nonfinite rollout prediction')
        self.rows.append({'obs': obs.copy(), 'features': features.copy(), 'choice': int(choice),
                          'old_logp': float(logp[choice]), 'old_logps': logp.numpy().copy(),
                          'old_value': value, 'actor_valid': not forced and len(features) > 1,
                          'reward': float(cumulative) if not self.rows else 0.0})
        self.last_cumulative = float(cumulative)

    def finish(self, total):
        if self.rows:
            self.rows[-1]['reward'] += float(total - self.last_cumulative)
            if not math.isclose(sum(r['reward'] for r in self.rows), total, abs_tol=1e-6):
                raise RuntimeError('transition rewards do not equal episode reward')
        rows, self.rows = self.rows, []
        return rows


def gae(rewards, values, gamma=1.0, lam=.95):
    """Complete episode: true terminal bootstrap is zero, never a truncation."""
    if len(rewards) != len(values) or not 0 <= gamma <= 1 or not 0 <= lam <= 1:
        raise ValueError('invalid GAE inputs')
    rewards, values = np.asarray(rewards, dtype=np.float64), np.asarray(values, dtype=np.float64)
    if not np.isfinite(rewards).all() or not np.isfinite(values).all():
        raise ValueError('nonfinite GAE inputs')
    advantages = np.zeros(len(rewards), dtype=np.float64)
    carry, following = 0.0, 0.0
    for i in range(len(rewards) - 1, -1, -1):
        delta = rewards[i] + gamma * following - values[i]
        carry = delta + gamma * lam * carry
        advantages[i] = carry
        following = values[i]
    return advantages.astype(np.float32), (advantages + values).astype(np.float32)


def prepare(episodes, gamma=1.0, lam=.95):
    rows = []
    for ep in episodes:
        if ep['status'] != 'terminated':
            raise ValueError('PPO only accepts complete episodes')
        trajectory = ep['ppo_records']
        advantages, returns = gae([r['reward'] for r in trajectory],
                                 [r['old_value'] for r in trajectory], gamma, lam)
        for r, advantage, target in zip(trajectory, advantages, returns):
            rows.append(dict(r, advantage=float(advantage), target=float(target)))
    valid = [r['advantage'] for r in rows if r['actor_valid']]
    if valid:
        mean, std = float(np.mean(valid)), float(np.std(valid))
        for r in rows:
            r['advantage'] = ((r['advantage'] - mean) / max(std, 1e-8)
                              if r['actor_valid'] else 0.0)
    return rows


def batch_tensors(rows):
    count = max(len(r['features']) for r in rows)
    candidates = np.zeros((len(rows), count, ARMG_ACTION_DIM), dtype=np.float32)
    mask = np.zeros((len(rows), count), dtype=bool)
    old_logps = np.zeros((len(rows), count), dtype=np.float32)
    for i, r in enumerate(rows):
        n = len(r['features'])
        candidates[i, :n] = r['features']
        mask[i, :n] = True
        old_logps[i, :n] = r['old_logps']
    return (torch.from_numpy(np.stack([r['obs'] for r in rows])),
            torch.from_numpy(candidates), torch.from_numpy(mask), torch.from_numpy(old_logps))


def clipped_loss(log_ratio, advantages, clip_ratio):
    ratio = log_ratio.exp()
    return -torch.minimum(ratio * advantages,
                          ratio.clamp(1 - clip_ratio, 1 + clip_ratio) * advantages)


@torch.no_grad()
def diagnostics(model, rows, minibatch_size):
    kl_sum = entropy_sum = clip_sum = valid_count = 0.0
    predictions, targets = [], []
    for start in range(0, len(rows), minibatch_size):
        part = rows[start:start + minibatch_size]
        obs, candidates, mask, old_logps = batch_tensors(part)
        logps = F.log_softmax(model(obs, candidates).masked_fill(~mask, -1e9), dim=-1)
        old_probs = old_logps.exp() * mask
        valid = torch.tensor([r['actor_valid'] for r in part], dtype=torch.bool)
        kl = (old_probs * (old_logps - logps)).sum(-1)
        entropy = -(logps.exp() * logps).sum(-1)
        kl_sum += float(kl[valid].sum())
        entropy_sum += float(entropy[valid].sum())
        valid_count += int(valid.sum())
        predictions.extend(model.value(obs).tolist())
        targets.extend(r['target'] for r in part)
    variance = float(np.var(targets)) if targets else 0.0
    return {'exact_kl': max(0.0, kl_sum / max(valid_count, 1)),
            'entropy': entropy_sum / max(valid_count, 1),
            'explained_variance': (1.0 - float(np.var(np.asarray(targets) - predictions)) / variance
                                   if variance > 1e-12 else None)}


def update(model, optimizer, episodes, prior, strength, *, epochs=4, minibatch_size=128,
           clip_ratio=.2, target_kl=.02, gamma=1.0, gae_lambda=.95,
           value_coef=.5, entropy_coef=.01, max_grad_norm=.5):
    if (epochs < 1 or minibatch_size < 1 or not 0 < clip_ratio < 1 or target_kl <= 0
            or max_grad_norm <= 0 or min(strength, value_coef, entropy_coef) < 0):
        raise ValueError('invalid PPO hyperparameters')
    rows = prepare(episodes, gamma, gae_lambda)
    if not rows:
        raise ValueError('empty PPO rollout')
    valid_count = sum(r['actor_valid'] for r in rows)
    eligible = 0
    for r in rows:
        target = prior.target((r['obs'], r['features'], r['choice'])) if r['actor_valid'] else None
        r['prior_target'] = target if target and target.get('eligible') else None
        eligible += r['prior_target'] is not None
    # Verify the frozen behavior policy really matches the model before updates.
    initial = diagnostics(model, rows, minibatch_size)
    if initial['exact_kl'] > 1e-5:
        raise RuntimeError('stale/off-policy rollout: actor differs from sampling policy')
    model.train()
    updates = epochs_done = 0
    stopped = False
    sums = {key: 0.0 for key in ('policy_loss', 'value_loss', 'prior_kl', 'clip_fraction', 'grad_norm')}
    for epoch in range(epochs):
        order = torch.randperm(len(rows)).tolist()
        for start in range(0, len(rows), minibatch_size):
            part = [rows[i] for i in order[start:start + minibatch_size]]
            obs, candidates, mask, old_logps = batch_tensors(part)
            logits = model(obs, candidates).masked_fill(~mask, -1e9)
            logps = F.log_softmax(logits, dim=-1)
            indices = torch.tensor([r['choice'] for r in part])
            chosen = logps[torch.arange(len(part)), indices]
            old = torch.tensor([r['old_logp'] for r in part])
            valid = torch.tensor([r['actor_valid'] for r in part], dtype=torch.bool)
            log_ratio = chosen - old
            exact_kl = ((old_logps.exp() * mask) * (old_logps - logps)).sum(-1)
            if valid.any() and float(exact_kl[valid].mean().detach()) > 1.5 * target_kl:
                stopped = True
                break
            advantages = torch.tensor([r['advantage'] for r in part])
            scale = len(rows) / max(valid_count, 1)
            policy_loss = (clipped_loss(log_ratio, advantages, clip_ratio) * valid).mean() * scale
            entropy = (-(logps.exp() * logps).sum(-1) * valid).mean() * scale
            value_loss = .5 * (model.value(obs) - torch.tensor([r['target'] for r in part])).square().mean()
            prior_kl = logits.sum() * 0.0
            for i, r in enumerate(part):
                target = r['prior_target']
                if target is not None:
                    q = torch.from_numpy(target['target'])
                    lp = F.log_softmax(logits[i, target['indices']], dim=0)
                    prior_kl = prior_kl + (q * (q.log() - lp)).sum()
            # Across minibatches this estimates the mean over prior-eligible
            # states, not a sum depending on the number of card rewards.
            prior_kl = prior_kl / len(part) * len(rows) / max(eligible, 1)
            loss = policy_loss + value_coef * value_loss - entropy_coef * entropy + strength * prior_kl
            if not torch.isfinite(loss):
                raise RuntimeError('nonfinite PPO loss')
            optimizer.zero_grad()
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm, error_if_nonfinite=True)
            optimizer.step()
            updates += 1
            for key, value in [('policy_loss', policy_loss), ('value_loss', value_loss),
                               ('prior_kl', prior_kl), ('grad_norm', norm)]:
                sums[key] += float(value.detach())
            sums['clip_fraction'] += float(((log_ratio.exp() - 1).abs() > clip_ratio)[valid].float().mean()) if valid.any() else 0.0
        epochs_done = epoch + 1
        metrics = diagnostics(model, rows, minibatch_size)
        if stopped or metrics['exact_kl'] > 1.5 * target_kl:
            stopped = True
            break
    return {**{key: value / max(updates, 1) for key, value in sums.items()}, **metrics,
            'updates': updates, 'epochs': epochs_done, 'kl_early_stop': stopped,
            'decisions': len(rows), 'actor_decisions': valid_count,
            'prior_eligible_decisions': eligible, 'prior_strength': strength}
