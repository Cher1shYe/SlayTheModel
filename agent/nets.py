"""PyTorch heads used on top of the native simulator.

Small MLPs only: the C++ engine provides all state transitions and the search,
these nets provide card priors and combat priors/values.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from .common import ACTION_FEAT_DIM, CARD_FEAT_DIM, COMBAT_OBS_DIM, RUN_OBS_DIM


def _mlp(sizes, act=nn.ReLU):
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(act())
    return nn.Sequential(*layers)


class CardScorer(nn.Module):
    """Scores (run state, candidate card) jointly; softmax over candidates."""

    def __init__(self, hidden=(128, 128)):
        super().__init__()
        self.net = _mlp([RUN_OBS_DIM + CARD_FEAT_DIM, *hidden, 1])

    def forward(self, run_obs: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
        # run_obs [B, R]; candidates [B, K, C] -> [B, K]
        b, k, _ = candidates.shape
        obs = run_obs.unsqueeze(1).expand(b, k, run_obs.shape[-1])
        return self.net(torch.cat([obs, candidates], dim=-1)).squeeze(-1)

    @torch.no_grad()
    def scores(self, run_obs, candidates) -> torch.Tensor:
        was_training = self.training
        self.eval()
        out = self.forward(run_obs, candidates)
        self.train(was_training)
        return out


class CombatNet(nn.Module):
    """Action scorer with a state value head.

    Policy = softmax over the actions of one state, so the same weights work for
    any number of legal actions (sts_lightspeed style action scorer).
    """

    def __init__(self, hidden: int = 128):
        super().__init__()
        self.state_enc = _mlp([COMBAT_OBS_DIM, hidden, hidden])
        self.action_enc = _mlp([ACTION_FEAT_DIM, hidden, hidden])
        self.score = _mlp([hidden * 2, hidden, 1])
        self.value = _mlp([hidden, hidden // 2, 1])

    def forward(self, state: torch.Tensor, actions: torch.Tensor, mask: torch.Tensor | None = None):
        # state [B, S]; actions [B, K, A]; mask [B, K]
        b, k, _ = actions.shape
        s = self.state_enc(state)
        a = self.action_enc(actions.reshape(b * k, -1)).reshape(b, k, -1)
        logits = self.score(torch.cat([s.unsqueeze(1).expand(b, k, -1), a], dim=-1)).squeeze(-1)
        if mask is not None:
            logits = logits.masked_fill(mask <= 0, -1e9)
        value = self.value(s).squeeze(-1)
        return logits, value

    @torch.no_grad()
    def policy_value(self, state, actions):
        was_training = self.training
        self.eval()
        logits, value = self.forward(state, actions)
        self.train(was_training)
        return logits, value


def save_checkpoint(path, model, extra=None):
    payload = {"state_dict": model.state_dict()}
    if extra:
        payload.update(extra)
    torch.save(payload, path)


def load_checkpoint(path, model, map_location="cpu"):
    payload = torch.load(path, map_location=map_location, weights_only=False)
    model.load_state_dict(payload["state_dict"])
    return payload
