"""BF16 runtime policy tests."""

from __future__ import annotations

import pytest
import torch

from spireformer import SpireFormer, SpireFormerConfig, compute_spireformer_loss
from spireformer.batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets
from spireformer.precision import PrecisionMode, autocast_context


def _batch_and_targets() -> tuple[SpireFormerBatch, SpireFormerTargets]:
    batch = SpireFormerBatch(
        entity_features=torch.randn(1, 1, 2, 3),
        entity_mask=torch.tensor([[[True, False]]]),
        legal_action_features=torch.randn(1, 1, 2, 4),
        legal_action_mask=torch.tensor([[[True, False]]]),
        previous_action_features=torch.zeros(1, 1, 4),
        returns_to_go=torch.ones(1, 1, 1),
        timesteps=torch.tensor([[0]]),
        domain_ids=torch.tensor([[int(DecisionDomain.COMBAT)]]),
        step_mask=torch.tensor([[True]]),
    )
    targets = SpireFormerTargets(
        action_indices=torch.tensor([[0]]),
        value_targets=torch.tensor([[0.5]]),
        teacher_policy=torch.tensor([[[1.0, 0.0]]]),
        policy_target_mask=torch.tensor([[True]]),
        value_target_mask=torch.tensor([[True]]),
    )
    return batch, targets


def test_bf16_transfer_only_casts_floating_point_tensors() -> None:
    batch, targets = _batch_and_targets()

    moved_batch = batch.to("cpu", dtype=torch.bfloat16)
    moved_targets = targets.to("cpu", dtype=torch.bfloat16)

    assert moved_batch.entity_features.dtype is torch.bfloat16
    assert moved_batch.legal_action_features.dtype is torch.bfloat16
    assert moved_batch.previous_action_features.dtype is torch.bfloat16
    assert moved_batch.returns_to_go.dtype is torch.bfloat16
    assert moved_batch.entity_mask.dtype is torch.bool
    assert moved_batch.timesteps.dtype is torch.int64
    assert moved_batch.domain_ids.dtype is torch.int64
    assert moved_targets.value_targets.dtype is torch.bfloat16
    assert moved_targets.teacher_policy is not None
    assert moved_targets.teacher_policy.dtype is torch.bfloat16
    assert moved_targets.action_indices.dtype is torch.int64
    assert moved_targets.policy_target_mask is not None
    assert moved_targets.policy_target_mask.dtype is torch.bool


def test_precision_mode_parsing_and_errors() -> None:
    assert PrecisionMode.parse("BF16") is PrecisionMode.BF16
    assert PrecisionMode.parse(PrecisionMode.FP32) is PrecisionMode.FP32
    with pytest.raises(ValueError, match="unknown precision"):
        PrecisionMode.parse("fp16")
    batch, _ = _batch_and_targets()
    with pytest.raises(TypeError, match="floating-point"):
        batch.to("cpu", dtype=torch.int32)


def test_cpu_autocast_runs_bf16_matrix_multiplication() -> None:
    left = torch.randn(8, 8)
    right = torch.randn(8, 8)
    with autocast_context("bf16", "cpu"):
        result = left @ right
    assert result.dtype is torch.bfloat16


def test_complete_model_trains_with_bf16_autocast() -> None:
    batch, targets = _batch_and_targets()
    model = SpireFormer(
        SpireFormerConfig(
            entity_feature_dim=3,
            action_feature_dim=4,
            model_dim=16,
            set_num_heads=4,
            set_num_layers=1,
            set_num_inducing_points=2,
            temporal_num_heads=4,
            temporal_num_layers=1,
            action_num_heads=4,
            dropout=0.0,
        )
    ).train()

    with autocast_context("bf16", "cpu"):
        output = model(batch)
        loss = compute_spireformer_loss(output, batch, targets).total

    assert output.policy_logits.dtype is torch.bfloat16
    assert output.state_value.dtype is torch.bfloat16
    assert loss.dtype is torch.float32
    loss.backward()
    assert all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in model.parameters()
    )
