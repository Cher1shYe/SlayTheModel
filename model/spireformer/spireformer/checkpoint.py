"""Atomic, versioned checkpoints for reproducible SpireFormer training.

The checkpoint deliberately stores the manifest next to the weights.  A model
with the right tensor shapes but a different vocabulary or reward definition is
not a compatible model, and should fail before any state is restored.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import random
import tempfile
from typing import Any, Mapping

import torch
from torch import nn
from torch.optim import Optimizer

from .manifest import SpireFormerManifest


CHECKPOINT_FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class CheckpointState:
    """Non-module state returned after loading a checkpoint."""

    step: int
    manifest: SpireFormerManifest
    trainer_state: dict[str, Any]
    extra: dict[str, Any]


def capture_rng_state() -> dict[str, Any]:
    """Capture process-local Python and Torch RNG state.

    Distributed launchers should gather one value per rank and store those
    alongside the shared checkpoint.  A single rank can rely on the default
    state saved by :func:`save_checkpoint`.
    """

    state: dict[str, Any] = {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
    }
    if torch.cuda.is_available():
        state["torch_cuda"] = torch.cuda.get_rng_state_all()
    if torch.backends.mps.is_available():
        state["torch_mps"] = torch.mps.get_rng_state()
    return state


def restore_rng_state(state: Mapping[str, Any]) -> None:
    """Restore a state returned by :func:`capture_rng_state`."""

    python_state = state.get("python")
    torch_cpu_state = state.get("torch_cpu")
    if python_state is None or torch_cpu_state is None:
        raise ValueError("checkpoint RNG state is incomplete")
    random.setstate(python_state)
    torch.set_rng_state(torch_cpu_state)

    cuda_state = state.get("torch_cuda")
    if cuda_state is not None and torch.cuda.is_available():
        if len(cuda_state) != torch.cuda.device_count():
            raise ValueError(
                "checkpoint CUDA RNG device count does not match this machine"
            )
        torch.cuda.set_rng_state_all(cuda_state)

    mps_state = state.get("torch_mps")
    if mps_state is not None and torch.backends.mps.is_available():
        torch.mps.set_rng_state(mps_state)


def _plain_dict(
    value: Mapping[str, Any] | None,
    *,
    field_name: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return dict(value)


def save_checkpoint(
    path: str | os.PathLike[str],
    *,
    model: nn.Module,
    manifest: SpireFormerManifest,
    step: int,
    optimizer: Optimizer | None = None,
    scheduler: Any | None = None,
    trainer_state: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    rng_state: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically save training state and return the final path.

    The temporary file is created in the destination directory, so
    :func:`os.replace` remains an atomic rename on the same filesystem.  The
    caller should save only on an optimizer boundary; accumulated gradients are
    intentionally not part of the checkpoint format.
    """

    if isinstance(step, bool) or not isinstance(step, int):
        raise TypeError("step must be an integer")
    if step < 0:
        raise ValueError("step cannot be negative")
    manifest.validate()
    destination = Path(path)
    if destination.exists() and destination.is_dir():
        raise IsADirectoryError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "format_version": CHECKPOINT_FORMAT_VERSION,
        "step": step,
        "manifest": manifest.to_dict(),
        "manifest_digest": manifest.digest(),
        "model": model.state_dict(),
        "optimizer": None if optimizer is None else optimizer.state_dict(),
        "scheduler": None if scheduler is None else scheduler.state_dict(),
        "trainer_state": _plain_dict(trainer_state, field_name="trainer_state"),
        "rng": (
            capture_rng_state()
            if rng_state is None
            else _plain_dict(rng_state, field_name="rng_state")
        ),
        "extra": _plain_dict(extra, field_name="extra"),
    }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            torch.save(payload, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return destination


def load_checkpoint(
    path: str | os.PathLike[str],
    *,
    model: nn.Module,
    optimizer: Optimizer | None = None,
    scheduler: Any | None = None,
    expected_manifest: SpireFormerManifest | None = None,
    map_location: str | torch.device | dict[str, str] | None = "cpu",
    restore_rng: bool = True,
    strict: bool = True,
    expected_extra: Mapping[str, Any] | None = None,
) -> CheckpointState:
    """Load a trusted SpireFormer checkpoint and validate its data contract."""

    source = Path(path)
    # ``weights_only`` limits deserialization to tensors and primitive
    # containers.  SpireFormer checkpoints intentionally contain no pickled
    # user classes.
    payload = torch.load(source, map_location=map_location, weights_only=True)
    if not isinstance(payload, dict):
        raise ValueError("checkpoint root must be a mapping")
    if payload.get("format_version") != CHECKPOINT_FORMAT_VERSION:
        raise ValueError(
            f"unsupported checkpoint format {payload.get('format_version')!r}"
        )

    raw_manifest = payload.get("manifest")
    if not isinstance(raw_manifest, Mapping):
        raise ValueError("checkpoint manifest is missing or malformed")
    manifest = SpireFormerManifest.from_dict(raw_manifest)
    recorded_digest = payload.get("manifest_digest")
    if recorded_digest != manifest.digest():
        raise ValueError("checkpoint manifest digest is invalid")
    if expected_manifest is not None:
        expected_manifest.validate()
        if manifest.digest() != expected_manifest.digest():
            raise ValueError("checkpoint manifest is incompatible with this run")

    step = payload.get("step")
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("checkpoint step is invalid")
    model_state = payload.get("model")
    if not isinstance(model_state, Mapping):
        raise ValueError("checkpoint model state is missing")

    optimizer_state = payload.get("optimizer")
    scheduler_state = payload.get("scheduler")
    if optimizer is not None and not isinstance(optimizer_state, dict):
        raise ValueError("checkpoint does not contain valid optimizer state")
    if scheduler is not None and scheduler_state is None:
        raise ValueError("checkpoint does not contain scheduler state")

    trainer_state = payload.get("trainer_state", {})
    extra = payload.get("extra", {})
    if not isinstance(trainer_state, Mapping):
        raise ValueError("checkpoint trainer_state must be a mapping")
    if not isinstance(extra, Mapping):
        raise ValueError("checkpoint extra must be a mapping")
    if expected_extra is not None:
        for key, expected_value in expected_extra.items():
            if key not in extra or extra[key] != expected_value:
                raise ValueError(
                    f"checkpoint extra field {key!r} is incompatible with this run"
                )

    # Compatibility is checked before mutating the supplied model or optimizer.
    model.load_state_dict(model_state, strict=strict)
    if optimizer is not None:
        assert isinstance(optimizer_state, dict)
        optimizer.load_state_dict(optimizer_state)
    if scheduler is not None:
        scheduler.load_state_dict(scheduler_state)
    if restore_rng:
        raw_rng = payload.get("rng")
        if not isinstance(raw_rng, Mapping):
            raise ValueError("checkpoint RNG state is missing or malformed")
        restore_rng_state(raw_rng)
    return CheckpointState(
        step=step,
        manifest=manifest,
        trainer_state=dict(trainer_state),
        extra=dict(extra),
    )


__all__ = [
    "CHECKPOINT_FORMAT_VERSION",
    "CheckpointState",
    "capture_rng_state",
    "load_checkpoint",
    "restore_rng_state",
    "save_checkpoint",
]
