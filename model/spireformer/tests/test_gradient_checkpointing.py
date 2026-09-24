"""Activation-checkpointing regression tests."""

from __future__ import annotations

import torch

from spireformer import (
    DecisionDomain,
    SpireFormer,
    SpireFormerConfig,
    Trajectory,
    TrajectoryStep,
    collate_trajectories,
    compute_spireformer_loss,
)


def _training_example():
    generator = torch.Generator().manual_seed(29)
    steps = tuple(
        TrajectoryStep(
            entity_features=torch.randn(4, 6, generator=generator),
            legal_action_features=torch.randn(3, 5, generator=generator),
            selected_action_index=step % 3,
            return_to_go=1.0 - step * 0.1,
            value_target=0.5 - step * 0.1,
            timestep=step,
            domain=(
                DecisionDomain.COMBAT
                if step % 2 == 0
                else DecisionDomain.OUTSIDE_COMBAT
            ),
        )
        for step in range(3)
    )
    return collate_trajectories(
        [Trajectory(steps)], entity_feature_dim=6, action_feature_dim=5
    )


def test_gradient_checkpointing_preserves_forward_and_backward() -> None:
    torch.manual_seed(31)
    config = SpireFormerConfig(
        entity_feature_dim=6,
        action_feature_dim=5,
        model_dim=16,
        set_num_heads=4,
        set_num_layers=2,
        set_num_inducing_points=3,
        temporal_num_heads=4,
        temporal_num_layers=2,
        action_num_heads=4,
        dropout=0.0,
    )
    baseline = SpireFormer(config).train()
    checkpointed = SpireFormer(config).train()
    checkpointed.load_state_dict(baseline.state_dict())
    checkpointed.set_gradient_checkpointing(True)
    batch, targets = _training_example()

    baseline_output = baseline(batch)
    checkpointed_output = checkpointed(batch)
    torch.testing.assert_close(
        checkpointed_output.policy_logits, baseline_output.policy_logits
    )
    torch.testing.assert_close(
        checkpointed_output.state_value, baseline_output.state_value
    )

    baseline_loss = compute_spireformer_loss(baseline_output, batch, targets).total
    checkpointed_loss = compute_spireformer_loss(
        checkpointed_output, batch, targets
    ).total
    baseline_loss.backward()
    checkpointed_loss.backward()

    for (baseline_name, baseline_parameter), (
        checkpointed_name,
        checkpointed_parameter,
    ) in zip(baseline.named_parameters(), checkpointed.named_parameters(), strict=True):
        assert baseline_name == checkpointed_name
        assert baseline_parameter.grad is not None
        assert checkpointed_parameter.grad is not None
        torch.testing.assert_close(
            checkpointed_parameter.grad,
            baseline_parameter.grad,
            rtol=1e-4,
            atol=1e-6,
        )
