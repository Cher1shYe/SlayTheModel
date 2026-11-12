"""Weights-only checkpoints bound to the simulator identity.

``best.pt`` (best validation win rate; equal win rates: higher mean floor) and
``last.pt`` (rewritten after every validation and at the end of training).
There is no optimizer or RNG state, so an interrupted run cannot be resumed
exactly. The separate critic, when configured, is stored under "critic".
"""
from __future__ import annotations

from pathlib import Path

import torch

from .config import RunConfig
from .sim import identity

FORMAT = "spire_rl/3"   # 3: stage-free inputs, 3-component critic, factorized policy


class IncompatibleCheckpoint(RuntimeError):
    pass


def save(path: Path, cfg: RunConfig, model, progress: dict, critic=None) -> None:
    payload = {
        "format": FORMAT,
        "config": cfg.to_dict(),
        "fingerprint": cfg.fingerprint(),
        "identity": identity(),
        "model": model.state_dict(),
        "progress": progress,
        "critic": critic.state_dict() if critic is not None else None,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    torch.save(payload, tmp)
    tmp.replace(path)


def load(path: Path) -> dict:
    """Always loads to CPU; callers copy the weights into a model on their device."""
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("format") != FORMAT:
        raise IncompatibleCheckpoint(f"{path}: unknown checkpoint format {payload.get('format')!r}")
    current = identity()
    if payload["identity"] != current:
        diff = {k: (payload["identity"].get(k), current.get(k)) for k in current
                if payload["identity"].get(k) != current.get(k)}
        raise IncompatibleCheckpoint(f"{path}: simulator identity differs (saved, current): {diff}")
    return payload
