"""Weights-only checkpoints bound to the simulator identity.

Only the best validation model is kept (``best.pt``). There is no optimizer
or RNG state, so an interrupted run cannot be resumed; start it again.
"""
from __future__ import annotations

from pathlib import Path

import torch

from .config import RunConfig
from .sim import identity

FORMAT = "spire_rl/2"


class IncompatibleCheckpoint(RuntimeError):
    pass


def save(path: Path, cfg: RunConfig, model, progress: dict) -> None:
    payload = {
        "format": FORMAT,
        "config": cfg.to_dict(),
        "fingerprint": cfg.fingerprint(),
        "identity": identity(),
        "model": model.state_dict(),
        "progress": progress,
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
