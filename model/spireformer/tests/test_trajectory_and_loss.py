"""Tests for trajectory collation, target masks, losses, and manifests."""

from __future__ import annotations

import json

import pytest
import torch
from torch.nn import functional as F

from spireformer import (
    DecisionDomain,
    SpireFormerBatch,
    SpireFormerConfig,
    SpireFormerLossConfig,
    SpireFormerManifest,
    SpireFormerOutput,
    SpireFormerTargets,
    Trajectory,
    TrajectoryStep,
    collate_trajectories,
    compute_spireformer_loss,
)


def _step(
    entities: list[list[float]],
    actions: list[list[float]],
    selected: int,
    timestep: int,
    domain: DecisionDomain,
    *,
    value_target: float | None = None,
    teacher_policy: list[float] | None = None,
) -> TrajectoryStep:
    return TrajectoryStep(
        entity_features=torch.tensor(entities, dtype=torch.float32),
        legal_action_features=torch.tensor(actions, dtype=torch.float32),
        selected_action_index=selected,
        return_to_go=float(10 - timestep),
        timestep=timestep,
        domain=domain,
        value_target=value_target,
        teacher_policy=(
            None
            if teacher_policy is None
            else torch.tensor(teacher_policy, dtype=torch.float32)
        ),
    )


def test_collator_shifts_selected_actions_and_pads_variable_trajectories() -> None:
    first_actions = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    second_actions = [[7.0, 8.0, 9.0]]
    third_actions = [[10.0, 11.0, 12.0], [13.0, 14.0, 15.0]]
    long_trajectory = Trajectory.from_sequence(
        [
            _step(
                [[1.0, 0.0], [0.0, 1.0]],
                first_actions,
                1,
                4,
                DecisionDomain.COMBAT,
                value_target=0.5,
            ),
            _step(
                [[2.0, 2.0]],
                second_actions,
                0,
                5,
                DecisionDomain.OUTSIDE_COMBAT,
                teacher_policy=[1.0],
            ),
            _step(
                [[3.0, 3.0], [4.0, 4.0], [5.0, 5.0]],
                third_actions,
                0,
                6,
                DecisionDomain.COMBAT,
                value_target=-0.25,
                teacher_policy=[0.25, 0.75],
            ),
        ]
    )
    short_trajectory = Trajectory.from_sequence(
        [
            _step(
                [[9.0, 9.0]],
                [[20.0, 21.0, 22.0]],
                0,
                17,
                DecisionDomain.OUTSIDE_COMBAT,
            )
        ]
    )

    batch, targets = collate_trajectories(
        [long_trajectory, short_trajectory],
        entity_feature_dim=2,
        action_feature_dim=3,
    )

    assert batch.entity_features.shape == (2, 3, 3, 2)
    assert batch.legal_action_features.shape == (2, 3, 2, 3)
    assert batch.step_mask.tolist() == [[True, True, True], [True, False, False]]
    assert batch.domain_ids.tolist() == [
        [
            int(DecisionDomain.COMBAT),
            int(DecisionDomain.OUTSIDE_COMBAT),
            int(DecisionDomain.COMBAT),
        ],
        [int(DecisionDomain.OUTSIDE_COMBAT), 0, 0],
    ]
    torch.testing.assert_close(batch.previous_action_features[0, 0], torch.zeros(3))
    torch.testing.assert_close(
        batch.previous_action_features[0, 1], torch.tensor(first_actions[1])
    )
    torch.testing.assert_close(
        batch.previous_action_features[0, 2], torch.tensor(second_actions[0])
    )
    torch.testing.assert_close(batch.previous_action_features[1, 0], torch.zeros(3))
    assert torch.count_nonzero(batch.previous_action_features[1, 1:]) == 0

    assert targets.policy_target_mask is not None
    assert torch.equal(targets.policy_target_mask, batch.step_mask)
    assert targets.value_target_mask is not None
    assert targets.value_target_mask.tolist() == [
        [True, False, True],
        [False, False, False],
    ]
    assert targets.teacher_policy is not None
    # Once a trajectory batch contains any soft teacher, a missing teacher is
    # represented by the selected action's one-hot target.
    torch.testing.assert_close(targets.teacher_policy[0, 0], torch.tensor([0.0, 1.0]))
    torch.testing.assert_close(targets.teacher_policy[0, 2], torch.tensor([0.25, 0.75]))
    torch.testing.assert_close(targets.teacher_policy[1, 0], torch.tensor([1.0, 0.0]))
    assert torch.count_nonzero(targets.teacher_policy[1, 1:]) == 0


def _loss_batch() -> SpireFormerBatch:
    return SpireFormerBatch(
        entity_features=torch.ones(1, 3, 1, 2),
        entity_mask=torch.ones(1, 3, 1, dtype=torch.bool),
        legal_action_features=torch.ones(1, 3, 3, 2),
        legal_action_mask=torch.tensor(
            [[[True, True, False], [True, True, True], [True, False, True]]]
        ),
        previous_action_features=torch.zeros(1, 3, 2),
        returns_to_go=torch.zeros(1, 3, 1),
        timesteps=torch.tensor([[0, 1, 2]]),
        domain_ids=torch.tensor([[0, 1, 0]]),
        step_mask=torch.ones(1, 3, dtype=torch.bool),
    )


def test_soft_policy_and_value_losses_honor_independent_target_masks() -> None:
    batch = _loss_batch()
    logits = torch.tensor(
        [[[1.0, 2.0, -torch.inf], [50.0, -50.0, 25.0], [0.0, -torch.inf, 2.0]]],
        requires_grad=True,
    )
    state_value = torch.tensor([[99.0, 0.25, -99.0]], requires_grad=True)
    output = SpireFormerOutput(
        policy_logits=logits,
        state_value=state_value,
        state_context=torch.zeros(1, 3, 4),
    )
    teacher = torch.tensor([[[0.25, 0.75, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]])
    targets = SpireFormerTargets(
        # The masked middle policy index is deliberately arbitrary.
        action_indices=torch.tensor([[1, 2, 2]]),
        value_targets=torch.tensor([[-1_000.0, -0.5, 1_000.0]]),
        teacher_policy=teacher,
        policy_target_mask=torch.tensor([[True, False, True]]),
        value_target_mask=torch.tensor([[False, True, False]]),
    )
    weights = SpireFormerLossConfig(
        policy_weight=1.5,
        value_weight=0.4,
        entropy_weight=0.0,
    )

    loss = compute_spireformer_loss(output, batch, targets, weights)

    first_log_prob = F.log_softmax(logits[0, 0, :2], dim=-1)
    third_log_prob = F.log_softmax(logits[0, 2, [0, 2]], dim=-1)
    expected_policy = (
        -(0.25 * first_log_prob[0] + 0.75 * first_log_prob[1]) - third_log_prob[1]
    ) / 2.0
    expected_value = F.smooth_l1_loss(state_value[0, 1], torch.tensor(-0.5))
    torch.testing.assert_close(loss.policy, expected_policy)
    torch.testing.assert_close(loss.value, expected_value)
    torch.testing.assert_close(loss.total, 1.5 * expected_policy + 0.4 * expected_value)
    loss.total.backward()
    assert torch.isfinite(logits.grad).all()
    assert torch.isfinite(state_value.grad).all()
    assert logits.grad[0, 1].eq(0).all()
    assert state_value.grad[0, [0, 2]].eq(0).all()


def test_hard_targets_validate_only_rows_enabled_by_policy_mask() -> None:
    batch = _loss_batch()
    targets = SpireFormerTargets(
        # Index 99 is safe while its policy target is deliberately disabled.
        action_indices=torch.tensor([[0, 99, 2]]),
        value_targets=torch.zeros(1, 3),
        policy_target_mask=torch.tensor([[True, False, True]]),
        value_target_mask=torch.zeros(1, 3, dtype=torch.bool),
    )
    targets.validate(batch)

    enabled = SpireFormerTargets(
        action_indices=targets.action_indices,
        value_targets=targets.value_targets,
        policy_target_mask=torch.ones(1, 3, dtype=torch.bool),
        value_target_mask=targets.value_target_mask,
    )
    with pytest.raises(ValueError, match="outside the padded action range"):
        enabled.validate(batch)


def test_empty_policy_and_value_target_masks_produce_a_finite_graph_zero() -> None:
    batch = _loss_batch()
    logits = torch.tensor(
        [[[1.0, 2.0, -torch.inf], [3.0, 4.0, 5.0], [6.0, -torch.inf, 7.0]]],
        requires_grad=True,
    )
    state_value = torch.randn(1, 3, requires_grad=True)
    output = SpireFormerOutput(
        policy_logits=logits,
        state_value=state_value,
        state_context=torch.zeros(1, 3, 4),
    )
    targets = SpireFormerTargets(
        # No target is active, so placeholder values and indices are ignored.
        action_indices=torch.tensor([[99, 99, 99]]),
        value_targets=torch.full((1, 3), float("nan")),
        policy_target_mask=torch.zeros(1, 3, dtype=torch.bool),
        value_target_mask=torch.zeros(1, 3, dtype=torch.bool),
    )

    loss = compute_spireformer_loss(output, batch, targets)

    assert loss.total.item() == 0.0
    assert loss.policy.item() == 0.0
    assert loss.value.item() == 0.0
    assert loss.entropy.item() == 0.0
    loss.total.backward()
    assert logits.grad is not None and torch.isfinite(logits.grad).all()
    assert state_value.grad is not None and torch.isfinite(state_value.grad).all()
    assert torch.count_nonzero(logits.grad) == 0
    assert torch.count_nonzero(state_value.grad) == 0


@pytest.mark.parametrize("weight", [float("nan"), float("inf")])
def test_loss_config_rejects_non_finite_weights(weight: float) -> None:
    with pytest.raises(ValueError):
        SpireFormerLossConfig(policy_weight=weight).validate()


def test_active_non_finite_value_target_is_rejected() -> None:
    batch = _loss_batch()
    targets = SpireFormerTargets(
        action_indices=torch.tensor([[0, 0, 0]]),
        value_targets=torch.tensor([[0.0, float("nan"), 0.0]]),
        policy_target_mask=torch.zeros(1, 3, dtype=torch.bool),
        value_target_mask=torch.tensor([[False, True, False]]),
    )

    with pytest.raises(ValueError, match="value target"):
        targets.validate(batch)


def test_manifest_json_round_trip_and_digest_are_stable() -> None:
    config = SpireFormerConfig(
        entity_feature_dim=23,
        action_feature_dim=17,
        model_dim=32,
        set_num_heads=4,
        set_num_layers=3,
        set_num_inducing_points=None,
        temporal_num_heads=4,
        temporal_num_layers=2,
        temporal_ff_multiplier=3,
        action_num_heads=4,
        dropout=0.0,
        max_timestep=8192,
    )
    manifest = SpireFormerManifest(
        schema_version=1,
        model_version="SpireFormer-v0.1-测试",
        tensorizer_version="sts2-protocol-v1",
        vocabulary_hash="abc123",
        reward_version="whole-run-v0",
        no_save_load_information=True,
        config=config,
    )

    payload = manifest.to_json()
    restored = SpireFormerManifest.from_json(payload)

    assert "测试" in payload
    assert restored == manifest
    assert restored.to_dict() == manifest.to_dict()
    assert restored.digest() == manifest.digest()
    assert json.loads(payload)["config"]["set_num_inducing_points"] is None


def test_manifest_rejects_save_load_information() -> None:
    manifest = SpireFormerManifest(
        schema_version=1,
        model_version="v0.1",
        tensorizer_version="v1",
        vocabulary_hash="abc",
        reward_version="v1",
        no_save_load_information=False,
        config=SpireFormerConfig(entity_feature_dim=2, action_feature_dim=2),
    )

    with pytest.raises(ValueError, match="no-SL"):
        manifest.to_json()
