"""Command-line smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from spireformer import DecisionDomain, Trajectory, TrajectoryStep
from spireformer.cli import _DistributedContext, _aggregate_metrics, main
from spireformer.data import write_tensor_dataset
from spireformer.training import AggregatedMetrics


def _dataset(path: Path) -> None:
    generator = torch.Generator().manual_seed(101)
    trajectory = Trajectory(
        (
            TrajectoryStep(
                entity_features=torch.randn(3, 6, generator=generator),
                legal_action_features=torch.randn(2, 5, generator=generator),
                selected_action_index=1,
                return_to_go=0.75,
                timestep=0,
                domain=DecisionDomain.COMBAT,
                value_target=0.5,
            ),
        )
    )
    write_tensor_dataset(
        path,
        [trajectory],
        entity_feature_dim=6,
        action_feature_dim=5,
        tensorizer_version="test-tensorizer-v1",
        vocabulary_hash="test-vocabulary",
        reward_version="test-reward-v1",
    )


def test_presets_command_reports_all_exact_sizes(capsys) -> None:
    assert main(["presets", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in rows] == ["tiny", "small", "medium", "large"]
    assert rows[0]["parameters"] == 2_882_818
    assert rows[-1]["parameters"] == 2_033_487_362


def test_smoke_bf16_inference_uses_deployment_weights_and_reports_shapes(
    capsys,
) -> None:
    assert (
        main(
            [
                "smoke",
                "--preset",
                "tiny",
                "--device",
                "cpu",
                "--precision",
                "bf16",
                "--mode",
                "inference",
                "--batch-size",
                "2",
                "--steps",
                "3",
                "--entities",
                "4",
                "--actions",
                "5",
                "--seed",
                "17",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["kind"] == "smoke"
    assert result["preset"] == "tiny"
    assert result["mode"] == "inference"
    assert result["device"] == "cpu"
    assert result["precision"] == "bf16"
    assert result["parameter_dtype"] == "bfloat16"
    assert result["parameter_count"] == 2_882_818
    assert result["finite"] is True
    assert result["outputs_finite"] is True
    assert result["gradients_finite"] is None
    assert result["illegal_actions_masked"] is True
    assert result["loss"] is None
    assert result["output_shapes"] == {
        "policy_logits": [2, 3, 5],
        "state_context": [2, 3, 128],
        "state_value": [2, 3],
    }
    assert result["cuda_peak_memory_bytes"] is None
    assert result["setup_seconds"] >= 0.0
    assert result["elapsed_seconds"] >= 0.0


def test_smoke_bf16_training_keeps_fp32_master_and_runs_backward(capsys) -> None:
    assert (
        main(
            [
                "smoke",
                "--preset",
                "tiny",
                "--device",
                "cpu",
                "--precision",
                "bf16",
                "--mode",
                "train",
                "--batch-size",
                "1",
                "--steps",
                "2",
                "--entities",
                "3",
                "--actions",
                "4",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)

    assert result["mode"] == "train"
    assert result["precision"] == "bf16"
    assert result["parameter_dtype"] == "float32"
    assert result["parameter_count"] == 2_882_818
    assert result["finite"] is True
    assert result["outputs_finite"] is True
    assert result["gradients_finite"] is True
    assert result["illegal_actions_masked"] is True
    assert isinstance(result["loss"], float)
    assert result["output_shapes"]["policy_logits"] == [1, 2, 4]
    assert result["output_shapes"]["state_value"] == [1, 2]
    assert result["cuda_peak_memory_bytes"] is None


@pytest.mark.parametrize("option", ["--steps", "--entities", "--actions", "--seed"])
def test_smoke_rejects_non_positive_dimensions_and_seed(option: str) -> None:
    with pytest.raises(SystemExit):
        main(["smoke", "--device", "cpu", option, "0"])


def test_smoke_prints_diagnostics_and_returns_nonzero_for_nonfinite_result(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(
        "spireformer.cli._finite_smoke_result",
        lambda output, batch: (False, True),
    )

    exit_code = main(
        [
            "smoke",
            "--device",
            "cpu",
            "--precision",
            "fp32",
            "--mode",
            "inference",
            "--steps",
            "1",
            "--entities",
            "1",
            "--actions",
            "1",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code != 0
    assert result["finite"] is False
    assert result["device_name"]
    assert result["torch_version"] == str(torch.__version__)
    assert "cuda_version" in result
    assert result["cuda_capability"] is None


def test_ddp_metric_aggregation_uses_global_weighted_counts(monkeypatch) -> None:
    local = AggregatedMetrics(
        total_loss=2.0,
        policy_loss=4.0,
        value_loss=3.0,
        entropy=0.5,
        microbatches=1,
        optimizer_steps=1,
        active_steps=2,
        policy_targets=1,
        value_targets=2,
        global_step=7,
        learning_rate=1.0e-4,
    )
    remote_contribution = torch.tensor(
        [6.0, 6.0, 10.0, 3.0, 1.0, 1.0, 3.0, 1.0],
        dtype=torch.float64,
    )

    def fake_all_reduce(values, *, op) -> None:
        assert op is torch.distributed.ReduceOp.SUM
        values.add_(remote_contribution)

    monkeypatch.setattr(torch.distributed, "all_reduce", fake_all_reduce)
    context = _DistributedContext(
        rank=0,
        local_rank=0,
        world_size=2,
        device=torch.device("cpu"),
        initialized_here=False,
    )

    result = _aggregate_metrics(local, context)

    assert result.total_loss == pytest.approx(10.0 / 3.0)
    assert result.policy_loss == pytest.approx(2.5)
    assert result.value_loss == pytest.approx(16.0 / 3.0)
    assert result.entropy == pytest.approx(0.875)
    assert result.microbatches == 2
    assert result.active_steps == 3
    assert result.policy_targets == 4
    assert result.value_targets == 3
    assert result.optimizer_steps == 1


def test_train_dry_run_uses_dataset_contract_without_allocating_model(
    tmp_path: Path, capsys
) -> None:
    dataset = tmp_path / "dataset"
    _dataset(dataset)

    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--output",
                str(tmp_path / "run"),
                "--preset",
                "large",
                "--device",
                "cpu",
                "--dry-run",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["parameter_count"] > 2_000_000_000
    assert summary["model_config"]["entity_feature_dim"] == 6
    assert summary["model_config"]["action_feature_dim"] == 5
    assert summary["activation_checkpointing"] is True
    assert not (tmp_path / "run").exists()


def test_one_step_cpu_training_writes_resumable_checkpoint(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    output = tmp_path / "run"
    _dataset(dataset)

    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--output",
                str(output),
                "--preset",
                "tiny",
                "--device",
                "cpu",
                "--precision",
                "fp32",
                "--total-steps",
                "1",
                "--warmup-steps",
                "0",
                "--batch-size",
                "1",
                "--log-every",
                "1",
                "--checkpoint-every",
                "1",
                "--no-activation-checkpointing",
            ]
        )
        == 0
    )
    assert (output / "run-config.json").is_file()
    assert (output / "metrics.jsonl").is_file()
    checkpoint = output / "checkpoint-latest.pt"
    assert checkpoint.is_file()
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    assert payload["step"] == 1
    assert payload["extra"]["resume_contract"]["batch_size"] == 1
    assert payload["extra"]["cursor_states"] == [{"epoch": 0, "batches_in_epoch": 1}]
    assert len(payload["extra"]["rng_states"]) == 1

    # An exact no-op resume validates and restores model/optimizer/scheduler,
    # the rank-local data cursor, and process RNG before returning complete.
    assert (
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--output",
                str(output),
                "--preset",
                "tiny",
                "--device",
                "cpu",
                "--precision",
                "fp32",
                "--total-steps",
                "1",
                "--warmup-steps",
                "0",
                "--batch-size",
                "1",
                "--log-every",
                "1",
                "--checkpoint-every",
                "1",
                "--no-activation-checkpointing",
                "--resume",
                str(checkpoint),
            ]
        )
        == 0
    )

    with pytest.raises(ValueError, match="resume_contract"):
        main(
            [
                "train",
                "--dataset",
                str(dataset),
                "--output",
                str(output),
                "--preset",
                "tiny",
                "--device",
                "cpu",
                "--precision",
                "fp32",
                "--total-steps",
                "1",
                "--warmup-steps",
                "0",
                "--batch-size",
                "2",
                "--no-activation-checkpointing",
                "--resume",
                str(checkpoint),
            ]
        )
