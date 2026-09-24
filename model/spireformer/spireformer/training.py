"""Dependency-light training utilities for SpireFormer.

This module is intentionally independent of a particular ``Dataset`` or
distributed launcher.  A local DataLoader, a future headless collector, and a
multi-node trainer can all feed the same tensor contracts into
``train_microbatch``.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from math import cos, isfinite, pi
from numbers import Real
from typing import Any, ContextManager, Mapping

import torch
from torch import nn
from torch.nn.utils import clip_grad_norm_
from torch.optim import AdamW, Optimizer
from torch.optim.lr_scheduler import LambdaLR, LRScheduler

from .batch import SpireFormerBatch, SpireFormerTargets
from .losses import SpireFormerCriterion, SpireFormerLoss
from .model import SpireFormerOutput
from .precision import PrecisionMode, autocast_context, ensure_precision_supported


@dataclass(frozen=True, slots=True)
class TrainConfig:
    """Optimizer, schedule, precision, and accumulation settings."""

    precision: PrecisionMode | str = PrecisionMode.BF16
    learning_rate: float = 3.0e-4
    weight_decay: float = 0.1
    betas: tuple[float, float] = (0.9, 0.95)
    eps: float = 1.0e-8
    warmup_steps: int = 1_000
    total_steps: int = 100_000
    min_lr_ratio: float = 0.1
    gradient_accumulation_steps: int = 1
    max_grad_norm: float | None = 1.0
    non_blocking_transfer: bool = True

    @property
    def precision_mode(self) -> PrecisionMode:
        return PrecisionMode.parse(self.precision)

    def validate(self) -> None:
        PrecisionMode.parse(self.precision)
        for name, value in (
            ("learning_rate", self.learning_rate),
            ("weight_decay", self.weight_decay),
            ("eps", self.eps),
            ("min_lr_ratio", self.min_lr_ratio),
        ):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TypeError(f"{name} must be a finite number")
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if self.weight_decay < 0:
            raise ValueError("weight_decay cannot be negative")
        if self.eps <= 0:
            raise ValueError("eps must be positive")
        if not 0.0 <= self.min_lr_ratio <= 1.0:
            raise ValueError("min_lr_ratio must be in [0, 1]")
        if len(self.betas) != 2:
            raise ValueError("betas must contain exactly two values")
        for beta in self.betas:
            if isinstance(beta, bool) or not isinstance(beta, Real):
                raise TypeError("betas must be finite numbers")
            if not isfinite(float(beta)) or not 0.0 <= beta < 1.0:
                raise ValueError("each beta must be in [0, 1)")
        for name, value in (
            ("warmup_steps", self.warmup_steps),
            ("total_steps", self.total_steps),
            ("gradient_accumulation_steps", self.gradient_accumulation_steps),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.warmup_steps < 0:
            raise ValueError("warmup_steps cannot be negative")
        if self.total_steps <= 0:
            raise ValueError("total_steps must be positive")
        if self.warmup_steps > self.total_steps:
            raise ValueError("warmup_steps cannot exceed total_steps")
        if self.gradient_accumulation_steps <= 0:
            raise ValueError("gradient_accumulation_steps must be positive")
        if self.max_grad_norm is not None:
            if isinstance(self.max_grad_norm, bool) or not isinstance(
                self.max_grad_norm, Real
            ):
                raise TypeError("max_grad_norm must be a finite number or None")
            if not isfinite(float(self.max_grad_norm)) or self.max_grad_norm <= 0:
                raise ValueError("max_grad_norm must be positive and finite")
        if type(self.non_blocking_transfer) is not bool:
            raise TypeError("non_blocking_transfer must be a boolean")


@dataclass(frozen=True, slots=True)
class StepMetrics:
    """Detached metrics from one train or evaluation microbatch."""

    total_loss: float
    policy_loss: float
    value_loss: float
    entropy: float
    policy_targets: int
    value_targets: int
    active_steps: int
    micro_step: int
    global_step: int
    learning_rate: float
    did_optimizer_step: bool
    grad_norm: float | None = None


@dataclass(frozen=True, slots=True)
class OptimizerStepResult:
    """Result of explicitly flushing a partial accumulation window."""

    global_step: int
    learning_rate: float
    grad_norm: float | None


@dataclass(frozen=True, slots=True)
class AggregatedMetrics:
    """Weighted averages accumulated over an arbitrary number of batches."""

    total_loss: float
    policy_loss: float
    value_loss: float
    entropy: float
    microbatches: int
    optimizer_steps: int
    active_steps: int
    policy_targets: int
    value_targets: int
    global_step: int
    learning_rate: float


class MetricAccumulator:
    """Aggregate metrics without retaining tensors or autograd graphs."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._total_loss_sum = 0.0
        self._policy_loss_sum = 0.0
        self._value_loss_sum = 0.0
        self._entropy_sum = 0.0
        self._microbatches = 0
        self._optimizer_steps = 0
        self._active_weight = 0
        self._policy_weight = 0
        self._value_weight = 0
        self._active_steps = 0
        self._policy_targets = 0
        self._value_targets = 0
        self._global_step = 0
        self._learning_rate = 0.0

    def update(self, metrics: StepMetrics) -> None:
        active_weight = metrics.active_steps
        policy_weight = metrics.policy_targets
        value_weight = metrics.value_targets
        self._total_loss_sum += metrics.total_loss * active_weight
        self._policy_loss_sum += metrics.policy_loss * policy_weight
        self._value_loss_sum += metrics.value_loss * value_weight
        self._entropy_sum += metrics.entropy * policy_weight
        self._microbatches += 1
        self._optimizer_steps += int(metrics.did_optimizer_step)
        self._active_weight += active_weight
        self._policy_weight += policy_weight
        self._value_weight += value_weight
        self._active_steps += metrics.active_steps
        self._policy_targets += metrics.policy_targets
        self._value_targets += metrics.value_targets
        self._global_step = metrics.global_step
        self._learning_rate = metrics.learning_rate

    def record_optimizer_step(self, result: OptimizerStepResult) -> None:
        """Record a step produced by ``flush_accumulation``."""

        self._optimizer_steps += 1
        self._global_step = result.global_step
        self._learning_rate = result.learning_rate

    def compute(self, *, reset: bool = False) -> AggregatedMetrics:
        if not self._microbatches:
            result = AggregatedMetrics(
                total_loss=0.0,
                policy_loss=0.0,
                value_loss=0.0,
                entropy=0.0,
                microbatches=0,
                optimizer_steps=0,
                active_steps=0,
                policy_targets=0,
                value_targets=0,
                global_step=self._global_step,
                learning_rate=self._learning_rate,
            )
        else:
            result = AggregatedMetrics(
                total_loss=(
                    self._total_loss_sum / self._active_weight
                    if self._active_weight
                    else 0.0
                ),
                policy_loss=(
                    self._policy_loss_sum / self._policy_weight
                    if self._policy_weight
                    else 0.0
                ),
                value_loss=(
                    self._value_loss_sum / self._value_weight
                    if self._value_weight
                    else 0.0
                ),
                entropy=(
                    self._entropy_sum / self._policy_weight
                    if self._policy_weight
                    else 0.0
                ),
                microbatches=self._microbatches,
                optimizer_steps=self._optimizer_steps,
                active_steps=self._active_steps,
                policy_targets=self._policy_targets,
                value_targets=self._value_targets,
                global_step=self._global_step,
                learning_rate=self._learning_rate,
            )
        if reset:
            self.reset()
        return result


def create_optimizer(model: nn.Module, config: TrainConfig) -> AdamW:
    """Build AdamW with decay only on matrix-shaped parameters."""

    config.validate()
    decay: list[nn.Parameter] = []
    no_decay: list[nn.Parameter] = []
    for parameter in model.parameters():
        if not parameter.requires_grad:
            continue
        (decay if parameter.ndim >= 2 else no_decay).append(parameter)
    if not decay and not no_decay:
        raise ValueError("model has no trainable parameters")
    return AdamW(
        [
            {"params": decay, "weight_decay": config.weight_decay},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=config.learning_rate,
        betas=config.betas,
        eps=config.eps,
    )


def _lr_multiplier(step: int, config: TrainConfig) -> float:
    if config.warmup_steps and step < config.warmup_steps:
        return float(step + 1) / float(config.warmup_steps)
    decay_steps = config.total_steps - config.warmup_steps
    if decay_steps <= 0:
        return 1.0
    progress = min(max(step - config.warmup_steps, 0) / decay_steps, 1.0)
    cosine = 0.5 * (1.0 + cos(pi * progress))
    return config.min_lr_ratio + (1.0 - config.min_lr_ratio) * cosine


def create_warmup_cosine_scheduler(
    optimizer: Optimizer,
    config: TrainConfig,
) -> LambdaLR:
    """Create a per-optimizer-step warmup and cosine learning-rate schedule."""

    config.validate()
    return LambdaLR(optimizer, lr_lambda=lambda step: _lr_multiplier(step, config))


def _target_counts(
    batch: SpireFormerBatch,
    targets: SpireFormerTargets,
) -> tuple[int, int, int]:
    policy_mask = batch.step_mask
    if targets.policy_target_mask is not None:
        policy_mask = policy_mask & targets.policy_target_mask
    value_mask = batch.step_mask
    if targets.value_target_mask is not None:
        value_mask = value_mask & targets.value_target_mask
    return (
        int(batch.step_mask.sum().item()),
        int(policy_mask.sum().item()),
        int(value_mask.sum().item()),
    )


class SpireFormerTrainer:
    """Small training engine that can sit behind any batch-producing frontend."""

    def __init__(
        self,
        model: nn.Module,
        optimizer: Optimizer,
        scheduler: LRScheduler | None,
        config: TrainConfig,
        device: torch.device | str,
        criterion: SpireFormerCriterion | None = None,
    ) -> None:
        config.validate()
        self.device = torch.device(device)
        ensure_precision_supported(config.precision_mode, self.device)
        self.model = model.to(self.device)
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.config = config
        self.criterion = (criterion or SpireFormerCriterion()).to(self.device)
        self.global_step = 0
        self.micro_step = 0
        self._accumulation_count = 0
        self.train_metrics = MetricAccumulator()
        self.eval_metrics = MetricAccumulator()
        self.optimizer.zero_grad(set_to_none=True)

    @property
    def accumulation_count(self) -> int:
        return self._accumulation_count

    @property
    def learning_rate(self) -> float:
        return float(self.optimizer.param_groups[0]["lr"])

    def _move_inputs(
        self,
        batch: SpireFormerBatch,
        targets: SpireFormerTargets,
    ) -> tuple[SpireFormerBatch, SpireFormerTargets]:
        # Training keeps the master inputs and parameters in FP32.  Autocast
        # chooses BF16 only for operations where it is numerically appropriate.
        return (
            batch.to(
                self.device,
                dtype=torch.float32,
                non_blocking=self.config.non_blocking_transfer,
            ),
            targets.to(
                self.device,
                dtype=torch.float32,
                non_blocking=self.config.non_blocking_transfer,
            ),
        )

    def _optimizer_step(self, *, partial: bool = False) -> OptimizerStepResult:
        if self._accumulation_count <= 0:
            raise RuntimeError("there are no accumulated gradients to apply")
        if (
            partial
            and self._accumulation_count < self.config.gradient_accumulation_steps
        ):
            correction = (
                self.config.gradient_accumulation_steps / self._accumulation_count
            )
            for parameter in self.model.parameters():
                if parameter.grad is not None:
                    parameter.grad.mul_(correction)

        grad_norm: float | None = None
        if self.config.max_grad_norm is not None:
            norm = clip_grad_norm_(
                self.model.parameters(),
                self.config.max_grad_norm,
                error_if_nonfinite=True,
            )
            grad_norm = float(norm.detach().float().item())
        self.optimizer.step()
        if self.scheduler is not None:
            self.scheduler.step()
        self.optimizer.zero_grad(set_to_none=True)
        self.global_step += 1
        self._accumulation_count = 0
        return OptimizerStepResult(
            global_step=self.global_step,
            learning_rate=self.learning_rate,
            grad_norm=grad_norm,
        )

    def _gradient_sync_context(self, *, synchronize: bool) -> ContextManager[Any]:
        """Suppress DDP all-reduce until the accumulation boundary.

        ``DistributedDataParallel.no_sync`` must cover the forward pass as
        well as backward.  Looking it up dynamically keeps this trainer usable
        with an ordinary ``SpireFormer`` and with lightweight test wrappers.
        """

        no_sync = getattr(self.model, "no_sync", None)
        if synchronize or not callable(no_sync):
            return nullcontext()
        context = no_sync()
        if not hasattr(context, "__enter__") or not hasattr(context, "__exit__"):
            raise TypeError("model.no_sync() must return a context manager")
        return context

    def train_microbatch(
        self,
        batch: SpireFormerBatch,
        targets: SpireFormerTargets,
        *,
        force_optimizer_step: bool = False,
    ) -> StepMetrics:
        """Backpropagate one microbatch and step at the accumulation boundary.

        Set ``force_optimizer_step`` on the final microbatch of a short DDP
        accumulation window.  That backward pass then performs the required
        gradient synchronization before the partial window is rescaled and
        applied.  For non-distributed models, ``flush_accumulation`` remains an
        equivalent convenience.
        """

        if type(force_optimizer_step) is not bool:
            raise TypeError("force_optimizer_step must be a boolean")

        self.model.train()
        batch, targets = self._move_inputs(batch, targets)
        reaches_boundary = (
            self._accumulation_count + 1 == self.config.gradient_accumulation_steps
        )
        synchronize = reaches_boundary or force_optimizer_step
        with self._gradient_sync_context(synchronize=synchronize):
            with autocast_context(self.config.precision_mode, self.device):
                output: SpireFormerOutput = self.model(batch)
                loss: SpireFormerLoss = self.criterion(output, batch, targets)
            if not torch.isfinite(loss.total.detach()):
                self.optimizer.zero_grad(set_to_none=True)
                self._accumulation_count = 0
                raise FloatingPointError("non-finite SpireFormer loss")

            (loss.total / self.config.gradient_accumulation_steps).backward()
        self.micro_step += 1
        self._accumulation_count += 1
        did_step = reaches_boundary or force_optimizer_step
        optimizer_result = (
            self._optimizer_step(partial=force_optimizer_step and not reaches_boundary)
            if did_step
            else None
        )
        active_steps, policy_targets, value_targets = _target_counts(batch, targets)
        metrics = StepMetrics(
            total_loss=float(loss.total.detach().float().item()),
            policy_loss=float(loss.policy.detach().float().item()),
            value_loss=float(loss.value.detach().float().item()),
            entropy=float(loss.entropy.detach().float().item()),
            policy_targets=policy_targets,
            value_targets=value_targets,
            active_steps=active_steps,
            micro_step=self.micro_step,
            global_step=self.global_step,
            learning_rate=self.learning_rate,
            did_optimizer_step=did_step,
            grad_norm=(
                None if optimizer_result is None else optimizer_result.grad_norm
            ),
        )
        self.train_metrics.update(metrics)
        return metrics

    def flush_accumulation(self) -> OptimizerStepResult | None:
        """Apply a short final accumulation window, preserving loss scale."""

        if not self._accumulation_count:
            return None
        if callable(getattr(self.model, "no_sync", None)):
            raise RuntimeError(
                "cannot flush gradients accumulated under model.no_sync(); "
                "pass force_optimizer_step=True on the final microbatch"
            )
        result = self._optimizer_step(partial=True)
        self.train_metrics.record_optimizer_step(result)
        return result

    def evaluate_batch(
        self,
        batch: SpireFormerBatch,
        targets: SpireFormerTargets,
    ) -> StepMetrics:
        """Evaluate one batch without changing gradients or trainer counters."""

        was_training = self.model.training
        self.model.eval()
        try:
            batch, targets = self._move_inputs(batch, targets)
            with torch.inference_mode(), autocast_context(
                self.config.precision_mode, self.device
            ):
                output: SpireFormerOutput = self.model(batch)
                loss: SpireFormerLoss = self.criterion(output, batch, targets)
        finally:
            self.model.train(was_training)
        active_steps, policy_targets, value_targets = _target_counts(batch, targets)
        metrics = StepMetrics(
            total_loss=float(loss.total.detach().float().item()),
            policy_loss=float(loss.policy.detach().float().item()),
            value_loss=float(loss.value.detach().float().item()),
            entropy=float(loss.entropy.detach().float().item()),
            policy_targets=policy_targets,
            value_targets=value_targets,
            active_steps=active_steps,
            micro_step=self.micro_step,
            global_step=self.global_step,
            learning_rate=self.learning_rate,
            did_optimizer_step=False,
            grad_norm=None,
        )
        self.eval_metrics.update(metrics)
        return metrics

    def state_dict(self) -> dict[str, int]:
        """Return counters safe to store at an optimizer boundary."""

        if self._accumulation_count:
            raise RuntimeError(
                "cannot checkpoint in the middle of gradient accumulation; "
                "call flush_accumulation first"
            )
        return {
            "global_step": self.global_step,
            "micro_step": self.micro_step,
            "accumulation_count": 0,
        }

    def load_state_dict(self, state: Mapping[str, Any]) -> None:
        """Restore counters after model/optimizer/scheduler state is loaded."""

        def counter(name: str, default: int | None = None) -> int:
            value = state.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"trainer {name} must be a non-negative integer")
            return value

        global_step = counter("global_step")
        micro_step = counter("micro_step")
        accumulation_count = counter("accumulation_count", 0)
        if accumulation_count:
            raise ValueError("checkpoint cannot resume unsaved accumulated gradients")
        self.global_step = global_step
        self.micro_step = micro_step
        self._accumulation_count = 0


__all__ = [
    "AggregatedMetrics",
    "MetricAccumulator",
    "OptimizerStepResult",
    "SpireFormerTrainer",
    "StepMetrics",
    "TrainConfig",
    "create_optimizer",
    "create_warmup_cosine_scheduler",
]
