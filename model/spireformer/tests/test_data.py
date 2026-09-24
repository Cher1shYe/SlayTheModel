"""Tests for the versioned tensor-shard training data layer."""

from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any

import pytest
import torch

from spireformer import DecisionDomain, Trajectory, TrajectoryStep
from spireformer.data import (
    TENSOR_DATASET_MANIFEST,
    TensorDatasetManifest,
    TensorShardDataset,
    create_trajectory_dataloader,
    write_tensor_dataset,
)


def _trajectory(index: int, *, two_steps: bool = True) -> Trajectory:
    first_actions = torch.tensor(
        [[index + 0.1, 1.0, 2.0], [index + 0.2, 3.0, 4.0]],
        dtype=torch.float32,
    )
    steps = [
        TrajectoryStep(
            entity_features=torch.tensor(
                [[float(index), 1.0], [float(index), 2.0]], dtype=torch.float32
            ),
            legal_action_features=first_actions,
            selected_action_index=1,
            return_to_go=10.0 - index,
            timestep=index * 2,
            domain=DecisionDomain.COMBAT,
            value_target=float(index) / 10.0,
            teacher_policy=torch.tensor([0.25, 0.75]),
        )
    ]
    if two_steps:
        steps.append(
            TrajectoryStep(
                entity_features=torch.tensor(
                    [[float(index), 9.0]], dtype=torch.float32
                ),
                legal_action_features=torch.tensor(
                    [[index + 0.3, 5.0, 6.0]], dtype=torch.float32
                ),
                selected_action_index=0,
                return_to_go=9.0 - index,
                timestep=index * 2 + 1,
                domain=DecisionDomain.OUTSIDE_COMBAT,
            )
        )
    return Trajectory(tuple(steps))


def _write_dataset(
    root: Path,
    count: int,
    *,
    trajectories_per_shard: int = 2,
) -> TensorDatasetManifest:
    return write_tensor_dataset(
        root,
        (_trajectory(index) for index in range(count)),
        entity_feature_dim=2,
        action_feature_dim=3,
        tensorizer_version="tensorizer-test-v1",
        vocabulary_hash="abc123",
        reward_version="reward-test-v1",
        dataset_id="unit-test-dataset",
        trajectories_per_shard=trajectories_per_shard,
    )


def test_tensor_shard_round_trip_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = _write_dataset(root, 3, trajectories_per_shard=2)

    assert manifest.trajectory_count == 3
    assert manifest.step_count == 6
    assert len(manifest.shards) == 2
    assert TensorDatasetManifest.load(root) == manifest
    assert not list(root.glob(".*.tmp"))

    loaded = list(TensorShardDataset(root, verify_hashes=True))
    assert len(loaded) == 3
    for expected, actual in zip(
        (_trajectory(index) for index in range(3)), loaded, strict=True
    ):
        assert len(actual.steps) == len(expected.steps)
        for expected_step, actual_step in zip(
            expected.steps, actual.steps, strict=True
        ):
            torch.testing.assert_close(
                actual_step.entity_features, expected_step.entity_features
            )
            torch.testing.assert_close(
                actual_step.legal_action_features,
                expected_step.legal_action_features,
            )
            assert (
                actual_step.selected_action_index == expected_step.selected_action_index
            )
            assert actual_step.domain == expected_step.domain
            assert actual_step.timestep == expected_step.timestep
            assert actual_step.return_to_go == pytest.approx(expected_step.return_to_go)
            if expected_step.value_target is None:
                assert actual_step.value_target is None
            else:
                assert actual_step.value_target == pytest.approx(
                    expected_step.value_target
                )
            if expected_step.teacher_policy is None:
                assert actual_step.teacher_policy is None
            else:
                assert actual_step.teacher_policy is not None
                torch.testing.assert_close(
                    actual_step.teacher_policy, expected_step.teacher_policy
                )

    # Tensor shards are intentionally model-ready data, not replay/audit logs.
    first_payload = torch.load(
        root / manifest.shards[0].file,
        map_location="cpu",
        weights_only=True,
    )
    assert "state_fingerprint" not in first_payload
    assert "action_id" not in first_payload


def test_reader_rejects_bad_shard_schema(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    manifest = _write_dataset(root, 1)
    shard_path = root / manifest.shards[0].file
    payload = torch.load(shard_path, map_location="cpu", weights_only=True)
    payload["schema_version"] = 999
    torch.save(payload, shard_path)

    with pytest.raises(ValueError, match="unsupported tensor shard schema"):
        list(TensorShardDataset(root))


def test_reader_always_uses_weights_only_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "dataset"
    _write_dataset(root, 1)
    original_load = torch.load
    calls: list[dict[str, Any]] = []

    def recording_load(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return original_load(*args, **kwargs)

    monkeypatch.setattr(torch, "load", recording_load)
    assert len(list(TensorShardDataset(root))) == 1
    assert calls
    assert all(call.get("weights_only") is True for call in calls)


def test_manifest_rejects_inconsistent_counts(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _write_dataset(root, 1)
    manifest_path = root / TENSOR_DATASET_MANIFEST
    values = json.loads(manifest_path.read_text(encoding="utf-8"))
    values["trajectory_count"] += 1
    manifest_path.write_text(json.dumps(values), encoding="utf-8")

    with pytest.raises(ValueError, match="trajectory_count"):
        TensorDatasetManifest.load(root)


def test_rank_ownership_is_fixed_across_epochs_and_workers_do_not_overlap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dataset"
    manifest = _write_dataset(root, 12, trajectories_per_shard=1)
    rank_assignments: list[set[str]] = []
    for rank in range(2):
        dataset = TensorShardDataset(
            root,
            rank=rank,
            world_size=2,
            shuffle_shards=True,
            shuffle_seed=17,
        )
        expected_rank_files = {shard.file for shard in manifest.shards[rank::2]}
        for epoch in (0, 1, 7):
            dataset.set_epoch(epoch)
            worker_assignments = [
                {
                    shard.file
                    for shard in dataset.assigned_shards(
                        worker_id=worker_id, num_workers=2
                    )
                }
                for worker_id in range(2)
            ]
            assert worker_assignments[0].isdisjoint(worker_assignments[1])
            assert set().union(*worker_assignments) == expected_rank_files
        rank_assignments.append(expected_rank_files)

    assert rank_assignments[0].isdisjoint(rank_assignments[1])
    assert set().union(*rank_assignments) == {shard.file for shard in manifest.shards}


def test_single_rank_shuffle_and_worker_stride_behavior_is_preserved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dataset"
    manifest = _write_dataset(root, 8, trajectories_per_shard=1)
    dataset = TensorShardDataset(
        root,
        rank=0,
        world_size=1,
        shuffle_shards=True,
        shuffle_seed=31,
    )
    dataset.set_epoch(4)

    expected = list(manifest.shards)
    random.Random(31 + 4).shuffle(expected)

    assert dataset.assigned_shards(worker_id=0, num_workers=2) == tuple(expected[0::2])
    assert dataset.assigned_shards(worker_id=1, num_workers=2) == tuple(expected[1::2])


def test_dataloader_restores_trajectories_and_collates(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _write_dataset(root, 3, trajectories_per_shard=1)
    dataset = TensorShardDataset(root)
    dataloader = create_trajectory_dataloader(dataset, batch_size=2)

    batch, targets = next(iter(dataloader))

    assert batch.entity_features.shape == (2, 2, 2, 2)
    assert batch.legal_action_features.shape == (2, 2, 2, 3)
    assert batch.step_mask.all()
    assert targets.action_indices.tolist() == [[1, 0], [1, 0]]
    assert targets.teacher_policy is not None
    torch.testing.assert_close(
        batch.previous_action_features[0, 1],
        torch.tensor([0.2, 3.0, 4.0]),
    )


def test_writer_rejects_non_finite_features_before_publication(
    tmp_path: Path,
) -> None:
    broken = _trajectory(0)
    broken.steps[0].entity_features[0, 0] = float("nan")

    with pytest.raises(ValueError, match="NaN or infinity"):
        write_tensor_dataset(
            tmp_path / "dataset",
            [broken],
            entity_feature_dim=2,
            action_feature_dim=3,
            tensorizer_version="v1",
            vocabulary_hash="vocab",
            reward_version="reward",
        )
    assert not (tmp_path / "dataset" / TENSOR_DATASET_MANIFEST).exists()
