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
    set_selection_weight: float = 1.0

    def validate(self) -> None:
        for name, value in (
            ("policy_weight", self.policy_weight),
            ("value_weight", self.value_weight),
            ("entropy_weight", self.entropy_weight),
            ("set_selection_weight", self.set_selection_weight),
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
    set_selection: Tensor


def _differentiable_zero(reference: Tensor) -> Tensor:
    # Policy logits contain -inf by contract for illegal actions. Summing the
    # raw tensor and multiplying by zero would produce NaN on an unlabeled
    # batch, so remove non-finite sentinels before creating a graph-connected
    # scalar zero.
    finite_reference = torch.where(
        torch.isfinite(reference), reference, torch.zeros_like(reference)
    )
    return finite_reference.float().sum() * 0.0


def _selected_set_nll(
    logits: Tensor, candidate_mask: Tensor, selected: Tensor
) -> Tensor:
    """Conditional Bernoulli set NLL in O(candidates * selected-count).

    The normalization is the k-th elementary symmetric polynomial of
    exp(candidate logits), computed in log space.  This assigns one
    permutation-invariant probability to an unordered k-card subset without
    enumerating any of its binomially many alternatives.
    """

    rows, candidate_count = logits.shape
    selected_counts = selected.sum(dim=-1).to(torch.long)
    max_k = int(selected_counts.max().item()) if rows else 0
    safe_logits = torch.where(candidate_mask, logits, torch.zeros_like(logits))
    negative_large = -1e9
    dp = [safe_logits.new_zeros(rows)] + [
        safe_logits.new_full((rows,), negative_large) for _ in range(max_k)
    ]
    for candidate_index in range(candidate_count):
        eligible = candidate_mask[:, candidate_index]
        score = safe_logits[:, candidate_index]
        for k in range(min(candidate_index + 1, max_k), 0, -1):
            include = torch.logaddexp(dp[k], dp[k - 1] + score)
            dp[k] = torch.where(eligible, include, dp[k])
    log_partition = (
        torch.stack(dp, dim=1).gather(1, selected_counts.unsqueeze(-1)).squeeze(-1)
    )
    chosen_score = (safe_logits * selected.to(safe_logits.dtype)).sum(dim=-1)
    return log_partition - chosen_score


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
    if batch.set_candidate_mask is not None:
        if output.set_candidate_logits is None or output.set_count_logits is None:
            raise ValueError("set-choice batch requires set candidate and count logits")
        if output.set_candidate_logits.shape != batch.set_candidate_mask.shape:
            raise ValueError("set_candidate_logits must match set_candidate_mask")
        if output.set_count_logits.shape != (
            *batch.step_mask.shape,
            batch.set_candidate_mask.shape[-1] + 1,
        ):
            raise ValueError("set_count_logits must have shape [B, T, C+1]")

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

    set_active = targets.set_target_mask
    if set_active is not None and set_active.any():
        assert targets.set_selected_mask is not None
        assert batch.set_candidate_mask is not None
        assert (
            output.set_candidate_logits is not None
            and output.set_count_logits is not None
        )
        selected = targets.set_selected_mask[set_active]
        set_logits = output.set_candidate_logits[set_active].float()
        candidate_mask = batch.set_candidate_mask[set_active]
        selected_counts = selected.sum(dim=-1).to(torch.long)
        subset_nll = _selected_set_nll(set_logits, candidate_mask, selected)
        count_nll = F.cross_entropy(
            output.set_count_logits[set_active].float(),
            selected_counts,
            reduction="none",
        )
        set_loss = (subset_nll + count_nll).mean()
    elif (
        output.set_candidate_logits is not None and output.set_count_logits is not None
    ):
        set_loss = _differentiable_zero(
            output.set_candidate_logits
        ) + _differentiable_zero(output.set_count_logits)
    else:
        set_loss = _differentiable_zero(output.policy_logits)

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
        + config.set_selection_weight * set_loss
        + config.value_weight * value_loss
        - config.entropy_weight * entropy
    )
    return SpireFormerLoss(
        total=total,
        policy=policy_loss,
        value=value_loss,
        entropy=entropy,
        set_selection=set_loss,
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
