"""CPU tests for optimization, BF16 autocast, metrics, and checkpoints."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import random
from typing import Iterator

import pytest
import torch

from spireformer.batch import SpireFormerBatch, SpireFormerTargets
from spireformer.checkpoint import load_checkpoint, save_checkpoint
from spireformer.manifest import SpireFormerManifest
from spireformer.model import SpireFormer, SpireFormerConfig, SpireFormerOutput
from spireformer.training import (
    MetricAccumulator,
    SpireFormerTrainer,
    StepMetrics,
    TrainConfig,
    create_optimizer,
    create_warmup_cosine_scheduler,
)


class _NoSyncSpy(torch.nn.Module):
    """DDP-shaped wrapper that records whether forward/backward were suppressed."""

    def __init__(self, module: SpireFormer) -> None:
        super().__init__()
        self.module = module
        self.no_sync_entries = 0
        self.inside_no_sync = False
        self.forward_no_sync: list[bool] = []
        self.backward_no_sync: list[bool] = []

    @contextmanager
    def no_sync(self) -> Iterator[None]:
        self.no_sync_entries += 1
        self.inside_no_sync = True
        try:
            yield
        finally:
            self.inside_no_sync = False

    def forward(self, batch: SpireFormerBatch) -> SpireFormerOutput:
        self.forward_no_sync.append(self.inside_no_sync)
        output = self.module(batch)
        output.state_value.register_hook(
            lambda gradient: self.backward_no_sync.append(self.inside_no_sync)
        )
        return output


def _model_config() -> SpireFormerConfig:
    return SpireFormerConfig(
        entity_feature_dim=3,
        action_feature_dim=2,
        model_dim=8,
        set_num_heads=2,
        set_num_layers=1,
        set_num_inducing_points=2,
        temporal_num_heads=2,
        temporal_num_layers=1,
        temporal_ff_multiplier=2,
        action_num_heads=2,
        dropout=0.0,
        max_timestep=32,
    )


def _manifest(model_version: str = "spireformer-test") -> SpireFormerManifest:
    return SpireFormerManifest(
        schema_version=1,
        model_version=model_version,
        tensorizer_version="test-v1",
        vocabulary_hash="test-vocabulary",
        reward_version="test-reward-v1",
        no_save_load_information=True,
        config=_model_config(),
    )


def _batch_and_targets() -> tuple[SpireFormerBatch, SpireFormerTargets]:
    torch.manual_seed(7)
    batch = SpireFormerBatch(
        entity_features=torch.randn(1, 2, 2, 3),
        entity_mask=torch.tensor([[[True, True], [True, False]]]),
        legal_action_features=torch.randn(1, 2, 3, 2),
        legal_action_mask=torch.tensor([[[True, True, False], [True, False, True]]]),
        previous_action_features=torch.zeros(1, 2, 2),
        returns_to_go=torch.tensor([[[1.0], [0.5]]]),
        timesteps=torch.tensor([[0, 1]]),
        domain_ids=torch.tensor([[0, 1]]),
        step_mask=torch.ones(1, 2, dtype=torch.bool),
    )
    targets = SpireFormerTargets(
        action_indices=torch.tensor([[1, 2]]),
        value_targets=torch.tensor([[0.4, -0.2]]),
    )
    return batch, targets


def _trainer(
    model: torch.nn.Module,
    *,
    precision: str = "fp32",
    accumulation: int = 1,
    max_grad_norm: float | None = 1.0,
) -> SpireFormerTrainer:
    config = TrainConfig(
        precision=precision,
        learning_rate=1.0e-3,
        weight_decay=0.01,
        warmup_steps=0,
        total_steps=10,
        min_lr_ratio=0.1,
        gradient_accumulation_steps=accumulation,
        max_grad_norm=max_grad_norm,
        non_blocking_transfer=False,
    )
    optimizer = create_optimizer(model, config)
    scheduler = create_warmup_cosine_scheduler(optimizer, config)
    return SpireFormerTrainer(
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        config=config,
        device="cpu",
    )


def test_ddp_no_sync_covers_only_non_boundary_forward_and_backward() -> None:
    wrapped = _NoSyncSpy(SpireFormer(_model_config()))
    trainer = _trainer(wrapped, accumulation=2)
    batch, targets = _batch_and_targets()

    first = trainer.train_microbatch(batch, targets)
    second = trainer.train_microbatch(batch, targets)

    assert not first.did_optimizer_step
    assert second.did_optimizer_step
    assert wrapped.no_sync_entries == 1
    assert wrapped.forward_no_sync == [True, False]
    assert wrapped.backward_no_sync == [True, False]


def test_ddp_short_window_must_sync_its_final_microbatch() -> None:
    wrapped = _NoSyncSpy(SpireFormer(_model_config()))
    trainer = _trainer(wrapped, accumulation=3)
    batch, targets = _batch_and_targets()

    trainer.train_microbatch(batch, targets)
    with pytest.raises(RuntimeError, match="force_optimizer_step"):
        trainer.flush_accumulation()

    final = trainer.train_microbatch(
        batch,
        targets,
        force_optimizer_step=True,
    )

    assert final.did_optimizer_step
    assert final.global_step == 1
    assert trainer.accumulation_count == 0
    assert wrapped.no_sync_entries == 1
    assert wrapped.forward_no_sync == [True, False]
    assert wrapped.backward_no_sync == [True, False]


def test_train_microbatch_accumulates_then_updates_and_evaluates() -> None:
    torch.manual_seed(3)
    model = SpireFormer(_model_config())
    trainer = _trainer(model, accumulation=2)
    batch, targets = _batch_and_targets()
    before = {name: value.detach().clone() for name, value in model.named_parameters()}

    first = trainer.train_microbatch(batch, targets)
    assert not first.did_optimizer_step
    assert trainer.global_step == 0
    assert trainer.accumulation_count == 1

    second = trainer.train_microbatch(batch, targets)
    assert second.did_optimizer_step
    assert second.global_step == 1
    assert second.grad_norm is not None and second.grad_norm >= 0.0
    assert trainer.accumulation_count == 0
    assert any(
        not torch.equal(before[name], parameter)
        for name, parameter in model.named_parameters()
    )

    previous_mode = model.training
    evaluated = trainer.evaluate_batch(batch, targets)
    assert torch.isfinite(torch.tensor(evaluated.total_loss))
    assert evaluated.global_step == 1
    assert not evaluated.did_optimizer_step
    assert model.training is previous_mode
    assert trainer.global_step == 1
    assert all(parameter.grad is None for parameter in model.parameters())


def test_partial_accumulation_flush_matches_a_full_single_batch_step() -> None:
    torch.manual_seed(11)
    partial_model = SpireFormer(_model_config())
    direct_model = SpireFormer(_model_config())
    direct_model.load_state_dict(partial_model.state_dict())
    partial = _trainer(
        partial_model,
        accumulation=2,
        max_grad_norm=None,
    )
    direct = _trainer(
        direct_model,
        accumulation=1,
        max_grad_norm=None,
    )
    batch, targets = _batch_and_targets()

    result = partial.train_microbatch(batch, targets)
    assert not result.did_optimizer_step
    flushed = partial.flush_accumulation()
    assert flushed is not None and flushed.global_step == 1
    direct.train_microbatch(batch, targets)

    for partial_parameter, direct_parameter in zip(
        partial_model.parameters(), direct_model.parameters(), strict=True
    ):
        torch.testing.assert_close(partial_parameter, direct_parameter)


def test_bf16_autocast_keeps_master_parameters_fp32_on_cpu() -> None:
    model = SpireFormer(_model_config())
    trainer = _trainer(model, precision="bf16")
    batch, targets = _batch_and_targets()

    result = trainer.train_microbatch(batch, targets)

    assert result.did_optimizer_step
    assert torch.isfinite(torch.tensor(result.total_loss))
    assert {parameter.dtype for parameter in model.parameters()} == {torch.float32}


def test_warmup_cosine_scheduler_reaches_floor() -> None:
    model = torch.nn.Linear(2, 1)
    config = TrainConfig(
        precision="fp32",
        learning_rate=1.0,
        warmup_steps=2,
        total_steps=6,
        min_lr_ratio=0.2,
    )
    optimizer = create_optimizer(model, config)
    scheduler = create_warmup_cosine_scheduler(optimizer, config)

    rates = [optimizer.param_groups[0]["lr"]]
    for _ in range(7):
        optimizer.zero_grad(set_to_none=True)
        model(torch.ones(1, 2)).sum().backward()
        optimizer.step()
        scheduler.step()
        rates.append(optimizer.param_groups[0]["lr"])

    assert rates[0] == pytest.approx(0.5)
    assert max(rates) == pytest.approx(1.0)
    assert rates[-1] == pytest.approx(0.2)
    assert all(rate >= 0.2 for rate in rates)


def test_metric_accumulator_reports_real_counts_and_weighted_averages() -> None:
    accumulator = MetricAccumulator()
    accumulator.update(
        StepMetrics(
            total_loss=2.0,
            policy_loss=4.0,
            value_loss=8.0,
            entropy=1.0,
            policy_targets=2,
            value_targets=1,
            active_steps=2,
            micro_step=1,
            global_step=0,
            learning_rate=0.01,
            did_optimizer_step=False,
        )
    )
    accumulator.update(
        StepMetrics(
            total_loss=4.0,
            policy_loss=10.0,
            value_loss=14.0,
            entropy=3.0,
            policy_targets=1,
            value_targets=3,
            active_steps=1,
            micro_step=2,
            global_step=1,
            learning_rate=0.005,
            did_optimizer_step=True,
        )
    )

    metrics = accumulator.compute()
    assert metrics.total_loss == pytest.approx(8.0 / 3.0)
    assert metrics.policy_loss == pytest.approx(6.0)
    assert metrics.value_loss == pytest.approx(12.5)
    assert metrics.entropy == pytest.approx(5.0 / 3.0)
    assert metrics.active_steps == 3
    assert metrics.policy_targets == 3
    assert metrics.value_targets == 4
    assert metrics.optimizer_steps == 1


def test_checkpoint_restores_training_state_manifest_and_rng(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "run" / "checkpoint.pt"
    model = SpireFormer(_model_config())
    trainer = _trainer(model)
    batch, targets = _batch_and_targets()
    trainer.train_microbatch(batch, targets)
    saved_parameters = {
        name: parameter.detach().clone() for name, parameter in model.named_parameters()
    }

    random.seed(1234)
    torch.manual_seed(5678)
    save_checkpoint(
        checkpoint_path,
        model=model,
        optimizer=trainer.optimizer,
        scheduler=trainer.scheduler,
        step=trainer.global_step,
        manifest=_manifest(),
        trainer_state=trainer.state_dict(),
        extra={"dataset_shard": 7},
    )
    expected_python_random = random.random()
    expected_torch_random = torch.rand(4)

    with torch.no_grad():
        for parameter in model.parameters():
            parameter.add_(100.0)
    random.seed(1)
    torch.manual_seed(2)
    trainer.global_step = 999

    loaded = load_checkpoint(
        checkpoint_path,
        model=model,
        optimizer=trainer.optimizer,
        scheduler=trainer.scheduler,
        expected_manifest=_manifest(),
        restore_rng=True,
    )
    trainer.load_state_dict(loaded.trainer_state)

    assert loaded.step == 1
    assert loaded.extra == {"dataset_shard": 7}
    assert loaded.manifest == _manifest()
    assert trainer.global_step == 1
    for name, parameter in model.named_parameters():
        torch.testing.assert_close(parameter, saved_parameters[name])
    assert random.random() == expected_python_random
    torch.testing.assert_close(torch.rand(4), expected_torch_random)
    assert not list(checkpoint_path.parent.glob(".*.tmp"))


def test_checkpoint_rejects_manifest_mismatch_before_mutating_model(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.pt"
    source = SpireFormer(_model_config())
    save_checkpoint(
        checkpoint_path,
        model=source,
        step=0,
        manifest=_manifest("source"),
    )
    destination = SpireFormer(_model_config())
    before = {
        name: parameter.detach().clone()
        for name, parameter in destination.named_parameters()
    }

    with pytest.raises(ValueError, match="incompatible"):
        load_checkpoint(
            checkpoint_path,
            model=destination,
            expected_manifest=_manifest("different"),
        )

    for name, parameter in destination.named_parameters():
        torch.testing.assert_close(parameter, before[name])


def test_checkpoint_rejects_resume_contract_before_mutating_model(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "checkpoint.pt"
    source = SpireFormer(_model_config())
    save_checkpoint(
        checkpoint_path,
        model=source,
        step=0,
        manifest=_manifest(),
        extra={"resume_contract": {"batch_size": 4}},
    )
    destination = SpireFormer(_model_config())
    before = {
        name: parameter.detach().clone()
        for name, parameter in destination.named_parameters()
    }

    with pytest.raises(ValueError, match="resume_contract"):
        load_checkpoint(
            checkpoint_path,
            model=destination,
            expected_manifest=_manifest(),
            expected_extra={"resume_contract": {"batch_size": 8}},
        )

    for name, parameter in destination.named_parameters():
        torch.testing.assert_close(parameter, before[name])


def test_trainer_refuses_to_serialize_unsaved_accumulated_gradients() -> None:
    trainer = _trainer(SpireFormer(_model_config()), accumulation=2)
    batch, targets = _batch_and_targets()
    trainer.train_microbatch(batch, targets)

    with pytest.raises(RuntimeError, match="gradient accumulation"):
        trainer.state_dict()


@pytest.mark.parametrize(
    "config, message",
    [
        (TrainConfig(total_steps=0), "total_steps"),
        (TrainConfig(warmup_steps=2, total_steps=1), "warmup_steps"),
        (TrainConfig(gradient_accumulation_steps=0), "gradient_accumulation_steps"),
        (TrainConfig(precision="fp16"), "precision"),
    ],
)
def test_train_config_validation(config: TrainConfig, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        config.validate()
