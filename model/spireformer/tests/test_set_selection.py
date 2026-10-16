"""Set-valued card decisions use candidate tokens, never subset enumeration."""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest
import torch

from spireformer import (
    DecisionDomain,
    SpireFormer,
    SpireFormerConfig,
    SpireFormerLossConfig,
    SpireFormerOutput,
    TensorShardDataset,
    TensorShardWriter,
    Trajectory,
    TrajectoryStep,
    collate_trajectories,
    compute_spireformer_loss,
)
from spireformer.data import (
    _pack_trajectories,
    _unpack_trajectories,
    _validate_shard_payload,
)


def _step(
    candidate_count: int, selected: tuple[int, ...], minimum: int, maximum: int
) -> TrajectoryStep:
    cards = (
        torch.arange(candidate_count * 3, dtype=torch.float32).reshape(
            candidate_count, 3
        )
        / 10
    )
    selected_mask = torch.zeros(candidate_count, dtype=torch.bool)
    selected_mask[list(selected)] = True
    return TrajectoryStep(
        entity_features=torch.tensor([[1.0, 0.0, 0.0]]),
        legal_action_features=torch.tensor([[0.0, 1.0]]),
        selected_action_index=0,
        return_to_go=0.0,
        timestep=0,
        domain=DecisionDomain.OUTSIDE_COMBAT,
        set_candidate_features=cards,
        set_selected_mask=selected_mask,
        set_min_select=minimum,
        set_max_select=maximum,
        executed_action_features=torch.tensor([float(len(selected)), 1.0]),
    )


def _model() -> SpireFormer:
    return SpireFormer(
        SpireFormerConfig(
            entity_feature_dim=3,
            action_feature_dim=2,
            model_dim=16,
            set_num_heads=4,
            set_num_layers=1,
            set_num_inducing_points=2,
            temporal_num_heads=4,
            temporal_num_layers=1,
            action_num_heads=4,
            dropout=0.0,
        )
    )


def test_nineteen_choose_four_is_one_template_and_nineteen_candidates() -> None:
    first = _step(19, (1, 4, 8, 18), 4, 4)
    second = replace(
        _step(3, (), 0, 3),
        timestep=1,
    )
    batch, targets = collate_trajectories(
        [Trajectory((first, second))], entity_feature_dim=3, action_feature_dim=2
    )
    assert batch.legal_action_features.shape == (1, 2, 1, 2)
    assert batch.set_candidate_features is not None
    assert batch.set_candidate_features.shape == (1, 2, 19, 3)
    assert batch.set_min_select is not None and batch.set_max_select is not None
    assert batch.set_min_select.tolist() == [[4, 0]]
    assert batch.set_max_select.tolist() == [[4, 3]]
    assert targets.set_selected_mask is not None
    assert targets.set_selected_mask[0, 0].sum().item() == 4
    torch.testing.assert_close(
        batch.previous_action_features[0, 1], torch.tensor([4.0, 1.0])
    )

    model = _model().train()
    output = model(batch)
    assert (
        output.set_candidate_logits is not None and output.set_count_logits is not None
    )
    assert output.set_candidate_logits.shape == (1, 2, 19)
    assert output.set_count_logits.shape == (1, 2, 20)
    assert torch.isfinite(output.set_count_logits[0, 0, 4])
    assert torch.isneginf(output.set_count_logits[0, 0, 3])
    selected = model.select_sets(output, batch)
    assert selected[0, 0].sum().item() == 4
    assert 0 <= selected[0, 1].sum().item() <= 3
    loss = compute_spireformer_loss(output, batch, targets)
    assert torch.isfinite(loss.total)
    loss.total.backward()
    assert any(
        p.grad is not None and torch.count_nonzero(p.grad)
        for p in model.set_count_head.parameters()
    )


def test_subset_loss_matches_exact_three_choose_two_probability() -> None:
    batch, targets = collate_trajectories(
        [Trajectory((_step(3, (0, 2), 2, 2),))],
        entity_feature_dim=3,
        action_feature_dim=2,
    )
    logits = torch.tensor([[[0.7, -0.2, 1.4]]], requires_grad=True)
    output = SpireFormerOutput(
        policy_logits=torch.zeros(1, 1, 1, requires_grad=True),
        state_value=torch.zeros(1, 1, requires_grad=True),
        state_context=torch.zeros(1, 1, 16),
        set_candidate_logits=logits,
        set_count_logits=torch.tensor([[[-torch.inf, -torch.inf, 0.0, -torch.inf]]]),
    )
    loss = compute_spireformer_loss(
        output,
        batch,
        targets,
        SpireFormerLossConfig(entropy_weight=0.0, value_weight=0.0),
    )
    pair_scores = torch.stack(
        [logits[0, 0, list(pair)].sum() for pair in combinations(range(3), 2)]
    )
    expected = torch.logsumexp(pair_scores, dim=0) - logits[0, 0, [0, 2]].sum()
    torch.testing.assert_close(loss.set_selection, expected)
    loss.total.backward()
    assert logits.grad is not None and torch.isfinite(logits.grad).all()


def test_zero_selected_set_trains_cardinality_and_candidate_order_is_equivariant() -> (
    None
):
    batch, targets = collate_trajectories(
        [Trajectory((_step(4, (), 0, 4),))],
        entity_feature_dim=3,
        action_feature_dim=2,
    )
    model = _model().eval()
    perm = torch.tensor([2, 0, 3, 1])
    assert (
        batch.set_candidate_features is not None
        and batch.set_candidate_mask is not None
    )
    permuted = replace(
        batch,
        set_candidate_features=batch.set_candidate_features[:, :, perm],
        set_candidate_mask=batch.set_candidate_mask[:, :, perm],
    )
    with torch.inference_mode():
        original = model(batch)
        changed = model(permuted)
    assert (
        original.set_candidate_logits is not None
        and changed.set_candidate_logits is not None
    )
    assert (
        original.set_count_logits is not None and changed.set_count_logits is not None
    )
    torch.testing.assert_close(
        changed.set_candidate_logits,
        original.set_candidate_logits[:, :, perm],
        atol=1e-5,
        rtol=1e-5,
    )
    torch.testing.assert_close(
        changed.set_count_logits, original.set_count_logits, atol=1e-5, rtol=1e-5
    )
    assert targets.set_selected_mask is not None and not targets.set_selected_mask.any()
    assert torch.isfinite(
        compute_spireformer_loss(original, batch, targets).set_selection
    )


def test_other_rows_padding_cannot_change_a_choices_scores() -> None:
    short = Trajectory((_step(3, (0,), 1, 2),))
    long = Trajectory((_step(19, (1, 4, 8, 18), 4, 4),))
    alone, _ = collate_trajectories([short], entity_feature_dim=3, action_feature_dim=2)
    together, _ = collate_trajectories(
        [short, long], entity_feature_dim=3, action_feature_dim=2
    )
    model = _model().eval()
    with torch.inference_mode():
        single_output = model(alone)
        paired_output = model(together)
    assert single_output.set_candidate_logits is not None
    assert paired_output.set_candidate_logits is not None
    assert single_output.set_count_logits is not None
    assert paired_output.set_count_logits is not None
    torch.testing.assert_close(
        paired_output.set_candidate_logits[0, 0, :3],
        single_output.set_candidate_logits[0, 0],
        rtol=1e-5,
        atol=1e-5,
    )
    torch.testing.assert_close(
        paired_output.set_count_logits[0, 0, :4],
        single_output.set_count_logits[0, 0],
        rtol=1e-5,
        atol=1e-5,
    )


def test_zero_candidate_zero_select_row_is_finite() -> None:
    batch, targets = collate_trajectories(
        [Trajectory((_step(0, (), 0, 0),))],
        entity_feature_dim=3,
        action_feature_dim=2,
    )
    model = _model().train()
    output = model(batch)
    assert output.set_count_logits is not None
    assert torch.isfinite(output.set_count_logits[0, 0, 0])
    assert output.set_candidate_logits is not None
    assert torch.isneginf(output.set_candidate_logits).all()
    loss = compute_spireformer_loss(output, batch, targets)
    assert torch.isfinite(loss.total)
    loss.total.backward()


def test_invalid_set_target_is_rejected() -> None:
    batch, targets = collate_trajectories(
        [Trajectory((_step(3, (0,), 1, 2),))],
        entity_feature_dim=3,
        action_feature_dim=2,
    )
    assert targets.set_selected_mask is not None
    invalid = targets.set_selected_mask.clone()
    invalid[0, 0] = True
    with pytest.raises(ValueError, match="cardinality"):
        replace(targets, set_selected_mask=invalid).validate(batch)


def test_v2_shard_round_trip_preserves_set_and_concrete_previous_action(
    tmp_path: Path,
) -> None:
    original = Trajectory((_step(19, (1, 4, 8, 18), 4, 4),))
    with TensorShardWriter(
        tmp_path,
        entity_feature_dim=3,
        action_feature_dim=2,
        tensorizer_version="test",
        vocabulary_hash="hash",
        reward_version="test",
    ) as writer:
        writer.add(original)
    loaded = list(TensorShardDataset(tmp_path, verify_hashes=True))
    assert len(loaded) == 1
    actual = loaded[0].steps[0]
    assert (
        actual.set_candidate_features is not None
        and actual.set_selected_mask is not None
    )
    assert actual.set_candidate_features.shape == (19, 3)
    assert actual.set_selected_mask.nonzero().flatten().tolist() == [1, 4, 8, 18]
    torch.testing.assert_close(
        actual.executed_action_features, torch.tensor([4.0, 1.0])
    )


def test_cancel_action_keeps_candidates_without_a_false_set_target(
    tmp_path: Path,
) -> None:
    choosing = _step(5, (0, 2), 2, 2)
    cancelled = replace(
        choosing,
        legal_action_features=torch.tensor([[0.0, 1.0], [1.0, 0.0]]),
        selected_action_index=1,
        set_selected_mask=None,
        executed_action_features=None,
    )
    batch, targets = collate_trajectories(
        [Trajectory((cancelled,))], entity_feature_dim=3, action_feature_dim=2
    )
    assert batch.set_step_mask is not None and batch.set_step_mask[0, 0]
    assert targets.set_target_mask is not None and not targets.set_target_mask[0, 0]
    assert targets.set_selected_mask is not None and not targets.set_selected_mask.any()

    with TensorShardWriter(
        tmp_path,
        entity_feature_dim=3,
        action_feature_dim=2,
        tensorizer_version="test",
        vocabulary_hash="hash",
        reward_version="test",
    ) as writer:
        writer.add(Trajectory((cancelled,)))
    loaded = list(TensorShardDataset(tmp_path))
    assert loaded[0].steps[0].set_candidate_features is not None
    assert loaded[0].steps[0].set_selected_mask is None


def test_v1_shard_is_still_readable() -> None:
    ordinary = replace(
        _step(1, (0,), 1, 1),
        set_candidate_features=None,
        set_selected_mask=None,
        set_min_select=None,
        set_max_select=None,
        executed_action_features=None,
    )
    packed = _pack_trajectories(
        [Trajectory((ordinary,))],
        entity_feature_dim=3,
        action_feature_dim=2,
        dtype=torch.float32,
    )
    v2_only = {
        "set_candidate_offsets",
        "set_candidate_features",
        "set_selected_mask",
        "set_min_select",
        "set_max_select",
        "set_step_mask",
        "set_target_mask",
        "executed_action_features",
    }
    old_payload = {key: value for key, value in packed.items() if key not in v2_only}
    old_payload["schema_version"] = 1
    _validate_shard_payload(
        old_payload,
        entity_feature_dim=3,
        action_feature_dim=2,
        feature_dtype="float32",
        trajectory_count=1,
        step_count=1,
    )
    loaded = list(_unpack_trajectories(old_payload))
    assert loaded[0].steps[0].set_candidate_features is None
    assert loaded[0].steps[0].selected_action_index == 0
