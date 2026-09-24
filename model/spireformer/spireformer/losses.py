"""Masked policy, value, and distillation losses for SpireFormer."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .batch import SpireFormerBatch, SpireFormerTargets
from .model import SpireFormerOutput


@dataclass(frozen=True, slots=True)
class SpireFormerLossConfig:
    policy_weight: float = 1.0
    value_weight: float = 0.25
    entropy_weight: float = 0.01

    def validate(self) -> None:
        for name, value in (
            ("policy_weight", self.policy_weight),
            ("value_weight", self.value_weight),
            ("entropy_weight", self.entropy_weight),
        ):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be a finite number")
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True, slots=True)
class SpireFormerLoss:
    total: Tensor
    policy: Tensor
    value: Tensor
    entropy: Tensor


def _differentiable_zero(reference: Tensor) -> Tensor:
    # Policy logits contain -inf by contract for illegal actions. Summing the
    # raw tensor and multiplying by zero would produce NaN on an unlabeled
    # batch, so remove non-finite sentinels before creating a graph-connected
    # scalar zero.
    finite_reference = torch.where(
        torch.isfinite(reference), reference, torch.zeros_like(reference)
    )
    return finite_reference.float().sum() * 0.0


def compute_spireformer_loss(
    output: SpireFormerOutput,
    batch: SpireFormerBatch,
    targets: SpireFormerTargets,
    config: SpireFormerLossConfig | None = None,
) -> SpireFormerLoss:
    """Compute loss without ever normalizing an all-padding action row."""

    config = config or SpireFormerLossConfig()
    config.validate()
    targets.validate(batch)
    if output.policy_logits.shape != batch.legal_action_mask.shape:
        raise ValueError("policy_logits must match legal_action_mask [B, T, A]")
    if output.state_value.shape != batch.step_mask.shape:
        raise ValueError("state_value must match step_mask [B, T]")

    policy_target_mask = (
        batch.step_mask
        if targets.policy_target_mask is None
        else batch.step_mask & targets.policy_target_mask
    )
    value_target_mask = (
        batch.step_mask
        if targets.value_target_mask is None
        else batch.step_mask & targets.value_target_mask
    )

    # Reductions and probability normalization stay in FP32 even when the
    # model forward is BF16. This costs little compared with the Transformer
    # and avoids quantizing small policy/value differences in the loss.
    active_logits = output.policy_logits[policy_target_mask].float()
    if active_logits.numel():
        log_probabilities = F.log_softmax(active_logits, dim=-1)
        active_legal_mask = batch.legal_action_mask[policy_target_mask]
        # Invalid actions intentionally have log probability -inf.  Replace
        # those entries before products such as 0 * -inf; torch.where around
        # the product is not enough because its backward pass can still emit
        # NaN gradients.
        finite_log_probabilities = torch.where(
            active_legal_mask,
            log_probabilities,
            torch.zeros_like(log_probabilities),
        )
        probabilities = log_probabilities.exp()
        if targets.teacher_policy is None:
            policy_loss = F.nll_loss(
                log_probabilities,
                targets.action_indices[policy_target_mask].to(torch.long),
            )
        else:
            teacher = targets.teacher_policy[policy_target_mask].float()
            policy_loss = -(teacher * finite_log_probabilities).sum(dim=-1).mean()
        entropy = -(probabilities * finite_log_probabilities).sum(dim=-1).mean()
    else:
        policy_loss = _differentiable_zero(output.policy_logits)
        entropy = _differentiable_zero(output.policy_logits)

    if value_target_mask.any():
        value_targets = targets.value_targets
        if value_targets.ndim == 3:
            value_targets = value_targets.squeeze(-1)
        value_loss = F.smooth_l1_loss(
            output.state_value[value_target_mask].float(),
            value_targets[value_target_mask].float(),
        )
    else:
        value_loss = _differentiable_zero(output.state_value)

    total = (
        config.policy_weight * policy_loss
        + config.value_weight * value_loss
        - config.entropy_weight * entropy
    )
    return SpireFormerLoss(
        total=total,
        policy=policy_loss,
        value=value_loss,
        entropy=entropy,
    )


class SpireFormerCriterion(nn.Module):
    """``nn.Module`` wrapper convenient for training loops and compilation."""

    def __init__(self, config: SpireFormerLossConfig | None = None) -> None:
        super().__init__()
        self.config = config or SpireFormerLossConfig()
        self.config.validate()

    def forward(
        self,
        output: SpireFormerOutput,
        batch: SpireFormerBatch,
        targets: SpireFormerTargets,
    ) -> SpireFormerLoss:
        return compute_spireformer_loss(output, batch, targets, self.config)


__all__ = [
    "SpireFormerCriterion",
    "SpireFormerLoss",
    "SpireFormerLossConfig",
    "compute_spireformer_loss",
]
