"""Runtime precision policy shared by training and inference."""

from __future__ import annotations

from contextlib import nullcontext
from enum import Enum
from typing import ContextManager

import torch
from torch import nn


class PrecisionMode(str, Enum):
    """Supported numerical modes.

    BF16 training uses autocast while keeping the optimizer's parameter copy
    in FP32.  Full BF16 parameter storage is exposed separately for inference.
    """

    FP32 = "fp32"
    BF16 = "bf16"

    @classmethod
    def parse(cls, value: "PrecisionMode | str") -> "PrecisionMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(value.strip().lower())
        except (AttributeError, ValueError) as error:
            choices = ", ".join(mode.value for mode in cls)
            raise ValueError(
                f"unknown precision {value!r}; expected {choices}"
            ) from error


def autocast_context(
    mode: PrecisionMode | str,
    device: torch.device | str,
) -> ContextManager[None]:
    """Return the appropriate autocast context for one forward/loss pass."""

    precision = PrecisionMode.parse(mode)
    resolved_device = torch.device(device)
    if precision is PrecisionMode.FP32:
        return nullcontext()
    return torch.autocast(device_type=resolved_device.type, dtype=torch.bfloat16)


def ensure_precision_supported(
    mode: PrecisionMode | str,
    device: torch.device | str,
) -> None:
    """Fail early when CUDA hardware cannot execute BF16 instructions."""

    precision = PrecisionMode.parse(mode)
    resolved_device = torch.device(device)
    if (
        precision is PrecisionMode.BF16
        and resolved_device.type == "cuda"
        and not torch.cuda.is_bf16_supported()
    ):
        raise RuntimeError("the selected CUDA device does not support BF16")


def cast_model_for_inference(
    model: nn.Module,
    *,
    mode: PrecisionMode | str,
    device: torch.device | str,
) -> nn.Module:
    """Move inference parameters to FP32 or BF16 storage.

    Training should normally leave parameters in FP32 and use
    :func:`autocast_context` instead.
    """

    precision = PrecisionMode.parse(mode)
    ensure_precision_supported(precision, device)
    dtype = torch.bfloat16 if precision is PrecisionMode.BF16 else torch.float32
    return model.to(device=device, dtype=dtype)


__all__ = [
    "PrecisionMode",
    "autocast_context",
    "cast_model_for_inference",
    "ensure_precision_supported",
]
