"""Tests for held-out evaluation and its data-leakage guardrails."""

from __future__ import annotations

import json
from math import exp, log
from pathlib import Path

import pytest
import torch
from torch import Tensor, nn

from spireformer import DecisionDomain, Trajectory, TrajectoryStep
from spireformer.checkpoint import save_checkpoint
from spireformer.data import TensorShardDataset, write_tensor_dataset
from spireformer.evaluate import evaluate_checkpoint, evaluate_model
from spireformer.manifest import SpireFormerManifest
from spireformer.model import SpireFormer, SpireFormerConfig, SpireFormerOutput


def _step(
    scores: list[float],
    selected: int,
    *,
    domain: DecisionDomain,
    timestep: int,
    return_to_go: float = 42.0,
    set_scores: list[float] | None = None,
    set_selected: list[bool] | None = None,
) -> TrajectoryStep:
    return TrajectoryStep(
        entity_features=torch.tensor([[float(timestep), 1.0]]),
        legal_action_features=torch.tensor([[score, 1.0] for score in scores]),
        selected_action_index=selected,
        return_to_go=return_to_go,
        timestep=timestep,
        domain=domain,
        value_target=0.5,
        set_candidate_features=(
            torch.tensor([[score, 1.0] for score in set_scores])
            if set_scores is not None
            else None
        ),
        set_selected_mask=(
            torch.tensor(set_selected, dtype=torch.bool)
            if set_selected is not None
            else None
        ),
        set_min_select=1 if set_scores is not None else None,
        set_max_select=1 if set_scores is not None else None,
        executed_action_features=(
            torch.tensor([scores[selected], 1.0])
            if set_selected is not None
            else None
        ),
    )


def _dataset(
    path: Path,
    trajectory: Trajectory,
    *,
    dataset_id: str,
    vocabulary_hash: str = "vocab-v1",
    dtype: torch.dtype = torch.float32,
) -> TensorShardDataset:
    write_tensor_dataset(
        path,
        [trajectory],
        entity_feature_dim=2,
        action_feature_dim=2,
        tensorizer_version="tensorizer-v1",
        vocabulary_hash=vocabulary_hash,
        reward_version="whole-run-v2",
        dataset_id=dataset_id,
        dtype=dtype,
    )
    return TensorShardDataset(path, verify_hashes=True)


def _checkpoint(path: Path, train: TensorShardDataset) -> Path:
    config = SpireFormerConfig(
        entity_feature_dim=2,
        action_feature_dim=2,
        model_dim=16,
        set_num_heads=4,
        set_num_layers=1,
        set_num_inducing_points=4,
        temporal_num_heads=4,
        temporal_num_layers=1,
        action_num_heads=4,
        dropout=0.0,
        max_timestep=8,
    )
    manifest = SpireFormerManifest(
        schema_version=1,
        model_version="unit-test",
        tensorizer_version="tensorizer-v1",
        vocabulary_hash="vocab-v1",
        reward_version="whole-run-v2",
        no_save_load_information=True,
        config=config,
    )
    save_checkpoint(
        path,
        model=SpireFormer(config),
        manifest=manifest,
        step=7,
        extra={"resume_contract": {"dataset_manifest": train.manifest.to_dict()}},
    )
    return path


class _FeatureScoreModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.seen_return_to_go: list[float] = []
        self.seen_feature_dtypes: list[torch.dtype] = []

    def forward(self, batch) -> SpireFormerOutput:
        self.seen_return_to_go.append(float(batch.returns_to_go.abs().max().item()))
        self.seen_feature_dtypes.append(batch.entity_features.dtype)
        logits = batch.legal_action_features[..., 0].masked_fill(
            ~batch.legal_action_mask, -torch.inf
        )
        set_logits: Tensor | None = None
        count_logits: Tensor | None = None
        if batch.set_candidate_features is not None:
            assert batch.set_candidate_mask is not None
            set_logits = batch.set_candidate_features[..., 0].masked_fill(
                ~batch.set_candidate_mask, -torch.inf
            )
            counts = batch.set_candidate_features.shape[2] + 1
            count_logits = torch.full(
                (*batch.step_mask.shape, counts),
                -torch.inf,
                device=logits.device,
            )
            count_logits[..., 1] = 1.0
        return SpireFormerOutput(
            policy_logits=logits,
            state_value=torch.zeros_like(batch.returns_to_go[..., 0]),
            state_context=torch.zeros(
                *batch.step_mask.shape, 1, device=logits.device
            ),
            set_candidate_logits=set_logits,
            set_count_logits=count_logits,
        )


def test_policy_metrics_use_hard_labels_masks_and_nontrivial_baselines(
    tmp_path: Path,
) -> None:
    trajectory = Trajectory(
        (
            _step([0.0, 2.0], 1, domain=DecisionDomain.COMBAT, timestep=0),
            _step([3.0], 0, domain=DecisionDomain.OUTSIDE_COMBAT, timestep=1),
            _step([4.0, 3.0, 0.0], 2, domain=DecisionDomain.COMBAT, timestep=2),
        )
    )
    dataset = _dataset(tmp_path / "holdout", trajectory, dataset_id="holdout")
    model = _FeatureScoreModel()
    result = evaluate_model(model, dataset, batch_size=1)

    assert model.seen_return_to_go == [0.0]
    assert result["recorded_future_return_input"] is False
    overall = result["policy"]["overall"]
    assert overall["count"] == 3
    assert overall["top1_accuracy"] == pytest.approx(2 / 3)
    assert overall["first_legal_accuracy"] == pytest.approx(1 / 3)
    assert overall["uniform_expected_top1"] == pytest.approx((0.5 + 1 + 1 / 3) / 3)
    assert overall["uniform_nll"] == pytest.approx((log(2) + log(3)) / 3)
    assert overall["nll"] == pytest.approx(
        (log(1 + exp(-2)) + log(exp(4) + exp(3) + 1)) / 3
    )
    nontrivial = result["policy"]["nontrivial"]
    assert nontrivial["count"] == 2
    assert nontrivial["top1_accuracy"] == pytest.approx(0.5)
    assert nontrivial["first_legal_accuracy"] == pytest.approx(0.0)
    assert result["policy"]["by_domain"]["combat"]["overall"]["count"] == 2
    assert result["policy"]["by_domain"]["outside_combat"]["overall"]["count"] == 1
    assert result["set_selection"]["count"] == 0
    assert result["value"]["count"] == 3
    assert result["value"]["mae"] == pytest.approx(0.5)

    diagnostic = evaluate_model(model, dataset, conditioning="recorded")
    assert diagnostic["recorded_future_return_input"] is True
    assert model.seen_return_to_go[-1] == pytest.approx(42.0)


def test_set_metrics_do_not_confuse_template_action_with_selected_cards(
    tmp_path: Path,
) -> None:
    trajectory = Trajectory(
        (
            _step(
                [0.0, 2.0],
                0,
                domain=DecisionDomain.COMBAT,
                timestep=0,
                set_scores=[0.1, 0.8, 0.6],
                set_selected=[False, True, False],
            ),
        )
    )
    dataset = _dataset(tmp_path / "holdout", trajectory, dataset_id="holdout")
    result = evaluate_model(_FeatureScoreModel(), dataset)

    assert result["policy"]["overall"]["top1_accuracy"] == 0.0
    assert result["set_selection"] == {
        "count": 1,
        "exact_set_accuracy": 1.0,
        "count_accuracy": 1.0,
        "joint_action_and_set_accuracy": 0.0,
    }


def test_fp16_shard_features_are_promoted_before_evaluation(tmp_path: Path) -> None:
    trajectory = Trajectory(
        (_step([0.0, 1.0], 1, domain=DecisionDomain.COMBAT, timestep=0),)
    )
    dataset = _dataset(
        tmp_path / "fp16-holdout",
        trajectory,
        dataset_id="fp16-holdout",
        dtype=torch.float16,
    )
    model = _FeatureScoreModel()

    result = evaluate_model(model, dataset, device="cpu", precision="fp32")

    assert result["policy"]["overall"]["count"] == 1
    assert model.seen_feature_dtypes == [torch.float32]


def test_checkpoint_evaluation_validates_manifest_and_training_overlap(
    tmp_path: Path,
) -> None:
    train = _dataset(
        tmp_path / "train",
        Trajectory((_step([0.0, 1.0], 1, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="train",
    )
    holdout = _dataset(
        tmp_path / "holdout",
        Trajectory((_step([2.0, 0.0], 0, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="holdout",
    )
    wrong_vocab = _dataset(
        tmp_path / "wrong-vocab",
        Trajectory((_step([5.0, 0.0], 0, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="wrong-vocab",
        vocabulary_hash="different",
    )
    checkpoint = _checkpoint(tmp_path / "checkpoint.pt", train)

    result = evaluate_checkpoint(
        checkpoint, holdout.root, device="cpu", precision="fp32"
    )
    assert result["checkpoint_step"] == 7
    assert result["overlap_check"] == "dataset_id_and_shards_disjoint"
    assert result["episode_split_verified"] is False
    assert result["policy"]["overall"]["count"] == 1
    with pytest.raises(ValueError, match="training dataset"):
        evaluate_checkpoint(checkpoint, train.root, device="cpu")
    with pytest.raises(ValueError, match="vocabulary_hash"):
        evaluate_checkpoint(checkpoint, wrong_vocab.root, device="cpu")


def test_assembly_report_verifies_episode_split_and_detects_stale_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "assembled"
    train = _dataset(
        root / "train",
        Trajectory((_step([0.0, 1.0], 1, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="train-dataset",
    )
    heldout = _dataset(
        root / "val",
        Trajectory((_step([2.0, 0.0], 0, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="val-dataset",
    )
    checkpoint = _checkpoint(tmp_path / "checkpoint.pt", train)
    report_path = root / "assembly-report.json"
    report = {
        "schema_version": 1,
        "tensorizer_version": "tensorizer-v1",
        "vocabulary_hash": "vocab-v1",
        "reward_version": "whole-run-v2",
        "entity_feature_dim": 2,
        "action_feature_dim": 2,
        "splits": {
            "train": {
                "episode_count": 1,
                "bc_steps": 1,
                "trajectories": 1,
                "episodes": [
                    {"episode_id": "episode-train", "source_sha256": "a" * 64}
                ],
            },
            "val": {
                "episode_count": 1,
                "bc_steps": 1,
                "trajectories": 1,
                "episodes": [
                    {"episode_id": "episode-val", "source_sha256": "b" * 64}
                ],
            },
        },
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = evaluate_checkpoint(checkpoint, heldout.root, device="cpu")
    assert result["episode_split_verified"] is True

    report["splits"]["val"]["episodes"][0]["episode_id"] = "episode-train"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="episodes overlap"):
        evaluate_checkpoint(checkpoint, heldout.root, device="cpu")

    report["splits"]["val"]["episodes"][0]["episode_id"] = "episode-val"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    train_manifest_path = root / "train" / "manifest.json"
    train_manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
    train_manifest["dataset_id"] = "unrelated-train-dataset"
    train_manifest_path.write_text(json.dumps(train_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match assembly root/train"):
        evaluate_checkpoint(checkpoint, heldout.root, device="cpu")


def test_separate_holdout_assembly_checks_training_root_and_source_identity(
    tmp_path: Path,
) -> None:
    training_root = tmp_path / "original-assembly"
    train = _dataset(
        training_root / "train",
        Trajectory((_step([0.0, 1.0], 1, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="original-train",
    )
    holdout_root = tmp_path / "future-assembly"
    holdout = _dataset(
        holdout_root / "holdout",
        Trajectory((_step([2.0, 0.0], 0, domain=DecisionDomain.COMBAT, timestep=0),)),
        dataset_id="future-holdout",
    )
    checkpoint = _checkpoint(tmp_path / "checkpoint.pt", train)
    common = {
        "schema_version": 1,
        "tensorizer_version": "tensorizer-v1",
        "vocabulary_hash": "vocab-v1",
        "reward_version": "whole-run-v2",
        "entity_feature_dim": 2,
        "action_feature_dim": 2,
    }
    train_report = {
        **common,
        "splits": {
            "train": {
                "episode_count": 1,
                "bc_steps": 1,
                "trajectories": 1,
                "episodes": [
                    {"episode_id": "episode-train", "source_sha256": "a" * 64}
                ],
            }
        },
    }
    holdout_report = {
        **common,
        "splits": {
            "holdout": {
                "episode_count": 1,
                "bc_steps": 1,
                "trajectories": 1,
                "episodes": [
                    {"episode_id": "episode-future", "source_sha256": "b" * 64}
                ],
            }
        },
    }
    (training_root / "assembly-report.json").write_text(
        json.dumps(train_report), encoding="utf-8"
    )
    holdout_report_path = holdout_root / "assembly-report.json"
    holdout_report_path.write_text(json.dumps(holdout_report), encoding="utf-8")

    without_provenance = evaluate_checkpoint(checkpoint, holdout.root, device="cpu")
    assert without_provenance["episode_split_verified"] is False
    verified = evaluate_checkpoint(
        checkpoint,
        holdout.root,
        device="cpu",
        training_assembly_root=training_root,
    )
    assert verified["episode_split_verified"] is True

    holdout_report["splits"]["holdout"]["episodes"][0]["source_sha256"] = "a" * 64
    holdout_report_path.write_text(json.dumps(holdout_report), encoding="utf-8")
    with pytest.raises(ValueError, match="episodes overlap"):
        evaluate_checkpoint(
            checkpoint,
            holdout.root,
            device="cpu",
            training_assembly_root=training_root,
        )

    holdout_report["splits"]["holdout"]["episodes"][0]["source_sha256"] = "b" * 64
    holdout_report_path.write_text(json.dumps(holdout_report), encoding="utf-8")
    train_manifest_path = training_root / "train" / "manifest.json"
    train_manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
    train_manifest["dataset_id"] = "different-training-dataset"
    train_manifest_path.write_text(json.dumps(train_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match assembly root/train"):
        evaluate_checkpoint(
            checkpoint,
            holdout.root,
            device="cpu",
            training_assembly_root=training_root,
        )
