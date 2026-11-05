"""PyTorch heads used on top of the native simulator.

Small MLPs only: the C++ engine provides all state transitions and the search,
these nets provide card priors and combat priors/values.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from .engine_identity import current_engine_contract, validate_engine_contract

from .common import (
    ACTION_FEAT_DIM,
    ACTION_SCHEMA_VERSION,
    CARD_FEAT_DIM,
    PUBLIC_COMBAT_OBS_DIM,
    PUBLIC_OBS_DIM,
    PUBLIC_OBS_VERSION,
)


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
        self.net = _mlp([PUBLIC_OBS_DIM + CARD_FEAT_DIM, *hidden, 1])

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
        self.state_enc = _mlp([PUBLIC_COMBAT_OBS_DIM, hidden, hidden])
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


CHECKPOINT_FORMAT = 3


def checkpoint_config(model) -> dict:
    first = next(model.parameters())
    return {
        "format": CHECKPOINT_FORMAT,
        "obs_version": int(PUBLIC_OBS_VERSION),
        "action_schema_version": int(ACTION_SCHEMA_VERSION),
        "param_shapes": [list(p.shape) for p in model.parameters()],
        "in_features": int(first.shape[1]) if first.dim() == 2 else int(first.numel()),
        "engine_contract": current_engine_contract(),
    }


def save_checkpoint(path, model, extra=None):
    payload = {"state_dict": model.state_dict(), "config": checkpoint_config(model)}
    if extra:
        payload.update(extra)
    validate_engine_contract(payload["config"], path)
    torch.save(payload, path)


def read_checkpoint(path, map_location="cpu"):
    """Read tensors plus standard NumPy RNG state, never arbitrary pickle code."""
    import numpy as np
    from numpy.core.multiarray import _reconstruct

    with torch.serialization.safe_globals([
        (_reconstruct, "numpy.core.multiarray._reconstruct"),
        (_reconstruct, "numpy._core.multiarray._reconstruct"),
        np.dtype, np.ndarray, type(np.dtype(np.uint32)),
    ]):
        payload = torch.load(path, map_location=map_location, weights_only=True)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: checkpoint must be a dictionary")
    return payload


def load_checkpoint(path, model, map_location="cpu", *, expected_config=None):
    """Load only the current engine and observation/action schema.

    Old files are left untouched. Eligible ArmG weights require the separate,
    explicit migration entry point; incompatible layouts require retraining.
    """
    payload = read_checkpoint(path, map_location=map_location)
    cfg = payload.get("config")
    if not isinstance(cfg, dict):
        raise ValueError(
            f"{path}: legacy checkpoint without schema metadata; retrain for "
            f"public observation v{PUBLIC_OBS_VERSION} / action schema v{ACTION_SCHEMA_VERSION}")
    if cfg.get("obs_version") != PUBLIC_OBS_VERSION:
        raise ValueError(
            f"{path}: observation version {cfg.get('obs_version')} != {PUBLIC_OBS_VERSION}")
    if cfg.get("action_schema_version") != ACTION_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: action schema version {cfg.get('action_schema_version')} != {ACTION_SCHEMA_VERSION}")
    current = [list(p.shape) for p in model.parameters()]
    if cfg.get("param_shapes") != current:
        raise ValueError(f"{path}: parameter shapes do not match the current network")
    validate_engine_contract(cfg, path)
    if cfg.get("format") != CHECKPOINT_FORMAT:
        raise ValueError(f"{path}: incompatible checkpoint format")
    for key, value in (expected_config or {}).items():
        if cfg.get(key) != value:
            raise ValueError(f"{path}: incompatible {key}: {cfg.get(key)} != {value}")
    model.load_state_dict(payload["state_dict"])
    return payload
