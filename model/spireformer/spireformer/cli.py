"""Command-line entry point for reproducible SpireFormer training."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
import random
import sys
import tempfile
from time import perf_counter
from typing import Any, Sequence, cast

import torch
from torch import distributed as dist
from torch.nn.parallel import DistributedDataParallel

from .batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets
from .checkpoint import (
    capture_rng_state,
    load_checkpoint,
    restore_rng_state,
    save_checkpoint,
)
from .data import (
    TensorShardDataset,
    create_trajectory_dataloader,
)
from .losses import SpireFormerCriterion, SpireFormerLossConfig
from .manifest import SpireFormerManifest
from .model import SpireFormer
from .precision import (
    PrecisionMode,
    autocast_context,
    cast_model_for_inference,
    ensure_precision_supported,
)
from .presets import (
    DEFAULT_MAX_TIMESTEP,
    available_presets,
    count_parameters,
    get_preset,
    get_spireformer_config,
)
from .training import (
    AggregatedMetrics,
    SpireFormerTrainer,
    TrainConfig,
    create_optimizer,
    create_warmup_cosine_scheduler,
)


@dataclass(frozen=True, slots=True)
class _DistributedContext:
    rank: int
    local_rank: int
    world_size: int
    device: torch.device
    initialized_here: bool

    @property
    def is_primary(self) -> bool:
        return self.rank == 0


def _resolve_device(requested: str, local_rank: int, world_size: int) -> torch.device:
    if requested == "auto":
        if torch.cuda.is_available():
            requested = "cuda"
        elif torch.backends.mps.is_available():
            requested = "mps"
        else:
            requested = "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")
        device_index = local_rank if world_size > 1 else 0
        torch.cuda.set_device(device_index)
        return torch.device("cuda", device_index)
    if requested == "mps":
        if world_size > 1:
            raise RuntimeError("torchrun is supported only with CUDA or CPU")
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is not available")
        return torch.device("mps")
    if requested != "cpu":
        raise ValueError(f"unsupported device {requested!r}")
    return torch.device("cpu")


def _initialize_distributed(requested_device: str) -> _DistributedContext:
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    if world_size < 1 or not 0 <= rank < world_size:
        raise ValueError("invalid WORLD_SIZE/RANK environment")
    device = _resolve_device(requested_device, local_rank, world_size)
    initialized_here = False
    if world_size > 1 and not dist.is_initialized():
        backend = "nccl" if device.type == "cuda" else "gloo"
        dist.init_process_group(backend=backend, init_method="env://")
        initialized_here = True
    return _DistributedContext(
        rank=rank,
        local_rank=local_rank,
        world_size=world_size,
        device=device,
        initialized_here=initialized_here,
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _append_json_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")
        handle.flush()


def _preset_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in available_presets():
        preset = get_preset(name)
        rows.append(
            {
                "name": name,
                "parameters": preset.reference_parameter_count(),
                "model_dim": preset.model_dim,
                "temporal_layers": preset.temporal_num_layers,
                "attention_heads": preset.temporal_num_heads,
                "set_layers": preset.set_num_layers,
                "description": preset.description,
            }
        )
    return rows


def _run_presets(args: argparse.Namespace) -> int:
    rows = _preset_rows()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print("name    parameters      dim  temporal  heads  set")
    for row in rows:
        print(
            f"{row['name']:<7} {row['parameters']:>13,} "
            f"{row['model_dim']:>6} {row['temporal_layers']:>9} "
            f"{row['attention_heads']:>6} {row['set_layers']:>4}"
        )
    return 0


def _synchronize_device(device: torch.device) -> None:
    """Make accelerator timings describe completed work, not queued work."""

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def _synthetic_batch(
    *,
    batch_size: int,
    steps: int,
    entities: int,
    actions: int,
    entity_feature_dim: int,
    action_feature_dim: int,
    device: torch.device,
    dtype: torch.dtype,
    seed: int,
) -> tuple[SpireFormerBatch, SpireFormerTargets]:
    """Build a deterministic, fully valid mixed-domain policy batch."""

    generator = torch.Generator(device="cpu").manual_seed(seed)
    entity_features = torch.randn(
        batch_size,
        steps,
        entities,
        entity_feature_dim,
        generator=generator,
    )
    action_features = torch.randn(
        batch_size,
        steps,
        actions,
        action_feature_dim,
        generator=generator,
    )
    previous_actions = torch.randn(
        batch_size,
        steps,
        action_feature_dim,
        generator=generator,
    )
    previous_actions[:, 0].zero_()
    returns_to_go = torch.rand(
        batch_size,
        steps,
        1,
        generator=generator,
    )
    entity_mask = torch.ones(batch_size, steps, entities, dtype=torch.bool)
    legal_action_mask = torch.ones(batch_size, steps, actions, dtype=torch.bool)
    # Exercise the dynamic illegal-action sentinel without ever creating an
    # all-masked decision row.
    if actions > 1:
        legal_action_mask[..., -1] = False
    timesteps = torch.arange(steps, dtype=torch.int64).expand(batch_size, -1)
    domains = (
        torch.arange(steps, dtype=torch.int64)
        .remainder(len(DecisionDomain))
        .expand(batch_size, -1)
    )
    step_mask = torch.ones(batch_size, steps, dtype=torch.bool)
    batch = SpireFormerBatch(
        entity_features=entity_features,
        entity_mask=entity_mask,
        legal_action_features=action_features,
        legal_action_mask=legal_action_mask,
        previous_action_features=previous_actions,
        returns_to_go=returns_to_go,
        timesteps=timesteps,
        domain_ids=domains,
        step_mask=step_mask,
    ).to(device, dtype=dtype)
    targets = SpireFormerTargets(
        action_indices=torch.zeros(batch_size, steps, dtype=torch.int64),
        value_targets=(
            torch.rand(batch_size, steps, generator=generator).mul_(2.0).sub_(1.0)
        ),
    ).to(device, dtype=dtype)
    return batch, targets


def _finite_smoke_result(
    output: Any,
    batch: SpireFormerBatch,
) -> tuple[bool, bool]:
    legal_logits = output.policy_logits.masked_select(batch.legal_action_mask)
    illegal_logits = output.policy_logits.masked_select(~batch.legal_action_mask)
    finite = bool(
        torch.isfinite(legal_logits).all().item()
        and torch.isfinite(output.state_value).all().item()
        and torch.isfinite(output.state_context).all().item()
    )
    illegal_actions_masked = bool(
        not illegal_logits.numel() or torch.isneginf(illegal_logits).all().item()
    )
    return finite, illegal_actions_masked


def _run_smoke(args: argparse.Namespace) -> int:
    """Run a synthetic inference or backward pass on the requested hardware."""

    device = _resolve_device(args.device, local_rank=0, world_size=1)
    precision = PrecisionMode.parse(args.precision)
    ensure_precision_supported(precision, device)
    torch.manual_seed(args.seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(args.seed)
    torch.set_float32_matmul_precision("high")

    model_config = get_spireformer_config(
        args.preset,
        dropout=0.0,
        max_timestep=max(DEFAULT_MAX_TIMESTEP, args.steps),
    )
    parameter_count = count_parameters(model_config)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    setup_started = perf_counter()
    model = SpireFormer(model_config)
    if args.mode == "inference":
        # Deployment smoke uses actual BF16 parameter storage, not merely
        # autocast, so it also verifies the expected checkpoint-serving dtype.
        model = cast(
            SpireFormer,
            cast_model_for_inference(
                model,
                mode=precision,
                device=device,
            ),
        )
        input_dtype = (
            torch.bfloat16 if precision is PrecisionMode.BF16 else torch.float32
        )
    else:
        # Training deliberately retains FP32 master parameters.  BF16 applies
        # only through autocast, and no Adam state is allocated by this smoke.
        model = model.to(device=device, dtype=torch.float32)
        input_dtype = torch.float32
    batch, targets = _synthetic_batch(
        batch_size=args.batch_size,
        steps=args.steps,
        entities=args.entities,
        actions=args.actions,
        entity_feature_dim=model_config.entity_feature_dim,
        action_feature_dim=model_config.action_feature_dim,
        device=device,
        dtype=input_dtype,
        seed=args.seed,
    )
    criterion = SpireFormerCriterion().to(device)
    setup_seconds = perf_counter() - setup_started

    _synchronize_device(device)
    run_started = perf_counter()
    loss = None
    gradients_finite = None
    if args.mode == "inference":
        model.eval()
        with torch.inference_mode():
            output = model(batch)
    else:
        model.train()
        with autocast_context(precision, device):
            output = model(batch)
            loss = criterion(output, batch, targets)
        loss.total.backward()
        gradients_finite = all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all().item())
            for parameter in model.parameters()
        )
    _synchronize_device(device)
    elapsed_seconds = perf_counter() - run_started

    outputs_finite, illegal_actions_masked = _finite_smoke_result(output, batch)
    loss_finite = None if loss is None else bool(torch.isfinite(loss.total).item())
    finite = outputs_finite and illegal_actions_masked
    if loss_finite is not None:
        finite = finite and loss_finite and bool(gradients_finite)
    first_parameter = next(model.parameters())
    if device.type == "cuda":
        device_name = torch.cuda.get_device_name(device)
        cuda_capability: list[int] | None = list(
            torch.cuda.get_device_capability(device)
        )
    elif device.type == "mps":
        device_name = f"Apple MPS ({platform.machine()})"
        cuda_capability = None
    else:
        device_name = platform.processor() or platform.machine() or "CPU"
        cuda_capability = None
    result = {
        "kind": "smoke",
        "preset": args.preset,
        "mode": args.mode,
        "device": str(device),
        "device_name": device_name,
        "cuda_capability": cuda_capability,
        "torch_version": str(torch.__version__),
        "cuda_version": torch.version.cuda,
        "precision": precision.value,
        "parameter_dtype": str(first_parameter.dtype).removeprefix("torch."),
        "parameter_count": parameter_count,
        "finite": finite,
        "outputs_finite": outputs_finite,
        "gradients_finite": gradients_finite,
        "illegal_actions_masked": illegal_actions_masked,
        "loss": None if loss is None else float(loss.total.detach().float().item()),
        "output_shapes": {
            "policy_logits": list(output.policy_logits.shape),
            "state_value": list(output.state_value.shape),
            "state_context": list(output.state_context.shape),
        },
        "input_shape": {
            "batch": args.batch_size,
            "steps": args.steps,
            "entities": args.entities,
            "actions": args.actions,
        },
        "setup_seconds": setup_seconds,
        "elapsed_seconds": elapsed_seconds,
        "cuda_peak_memory_bytes": (
            torch.cuda.max_memory_allocated(device) if device.type == "cuda" else None
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if finite else 2


def _learning_rate(args: argparse.Namespace) -> float:
    if args.learning_rate is not None:
        return args.learning_rate
    return {
        "tiny": 3.0e-4,
        "small": 1.0e-4,
        "medium": 6.0e-5,
        "large": 3.0e-5,
    }[args.preset]


class _BatchCursor:
    """Endlessly cycle an IterableDataset while advancing its shuffle epoch."""

    def __init__(self, loader: Any, dataset: TensorShardDataset) -> None:
        self.loader = loader
        self.dataset = dataset
        self.epoch = 0
        self.dataset.set_epoch(0)
        self.iterator = iter(loader)
        self.batches_in_epoch = 0

    def next(self) -> tuple[Any, Any]:
        try:
            value = next(self.iterator)
            self.batches_in_epoch += 1
            return value
        except StopIteration:
            self.epoch += 1
            self.batches_in_epoch = 0
            self.dataset.set_epoch(self.epoch)
            self.iterator = iter(self.loader)
            try:
                value = next(self.iterator)
                self.batches_in_epoch += 1
                return value
            except StopIteration as error:
                raise RuntimeError(
                    "this rank has no tensor shards; reduce world size/workers or add data"
                ) from error

    def state_dict(self) -> dict[str, int]:
        return {
            "epoch": self.epoch,
            "batches_in_epoch": self.batches_in_epoch,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Rebuild the deterministic iterator at an exact batch boundary."""

        if set(state) != {"epoch", "batches_in_epoch"}:
            raise ValueError("checkpoint data cursor has unexpected fields")
        epoch = state.get("epoch")
        batches_in_epoch = state.get("batches_in_epoch")
        for name, value in (
            ("epoch", epoch),
            ("batches_in_epoch", batches_in_epoch),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"cursor {name} must be a non-negative integer")
        assert isinstance(epoch, int) and isinstance(batches_in_epoch, int)
        self.epoch = epoch
        self.batches_in_epoch = 0
        self.dataset.set_epoch(epoch)
        self.iterator = iter(self.loader)
        for _ in range(batches_in_epoch):
            try:
                next(self.iterator)
            except StopIteration as error:
                raise ValueError(
                    "checkpoint data cursor is incompatible with this dataset/loader"
                ) from error
            self.batches_in_epoch += 1


def _gather_rank_objects(value: Any, context: _DistributedContext) -> list[Any]:
    if context.world_size == 1:
        return [value]
    gathered: list[Any] = [None] * context.world_size
    dist.all_gather_object(gathered, value)
    return gathered


def _aggregate_metrics(
    metrics: AggregatedMetrics,
    context: _DistributedContext,
) -> AggregatedMetrics:
    """Turn per-rank weighted metrics into one global DDP measurement."""

    if context.world_size == 1:
        return metrics
    values = torch.tensor(
        [
            metrics.total_loss * metrics.active_steps,
            metrics.policy_loss * metrics.policy_targets,
            metrics.value_loss * metrics.value_targets,
            metrics.entropy * metrics.policy_targets,
            metrics.microbatches,
            metrics.active_steps,
            metrics.policy_targets,
            metrics.value_targets,
        ],
        dtype=torch.float64,
        device=context.device,
    )
    dist.all_reduce(values, op=dist.ReduceOp.SUM)
    (
        total_sum,
        policy_sum,
        value_sum,
        entropy_sum,
        microbatches,
        active_steps,
        policy_targets,
        value_targets,
    ) = values.tolist()
    return AggregatedMetrics(
        total_loss=total_sum / active_steps if active_steps else 0.0,
        policy_loss=policy_sum / policy_targets if policy_targets else 0.0,
        value_loss=value_sum / value_targets if value_targets else 0.0,
        entropy=entropy_sum / policy_targets if policy_targets else 0.0,
        microbatches=int(microbatches),
        # Optimizer steps are synchronous logical steps, not work to sum.
        optimizer_steps=metrics.optimizer_steps,
        active_steps=int(active_steps),
        policy_targets=int(policy_targets),
        value_targets=int(value_targets),
        global_step=metrics.global_step,
        learning_rate=metrics.learning_rate,
    )


def _save_training_checkpoint(
    path: Path,
    *,
    raw_model: SpireFormer,
    manifest: SpireFormerManifest,
    trainer: SpireFormerTrainer,
    optimizer: torch.optim.Optimizer,
    scheduler: Any,
    context: _DistributedContext,
    preset: str,
    cursor: _BatchCursor,
    resume_contract: dict[str, Any],
) -> None:
    cursor_states = _gather_rank_objects(cursor.state_dict(), context)
    rng_states = _gather_rank_objects(capture_rng_state(), context)
    if context.is_primary:
        save_checkpoint(
            path,
            model=raw_model,
            manifest=manifest,
            step=trainer.global_step,
            optimizer=optimizer,
            scheduler=scheduler,
            trainer_state=trainer.state_dict(),
            extra={
                "preset": preset,
                "world_size": context.world_size,
                "resume_contract": resume_contract,
                "cursor_states": cursor_states,
                "rng_states": rng_states,
            },
            rng_state=rng_states[0],
        )
    if context.world_size > 1:
        dist.barrier()


def _run_train(args: argparse.Namespace) -> int:
    context = _initialize_distributed(args.device)
    try:
        seed = args.seed + context.rank
        random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.set_float32_matmul_precision("high")
        ensure_precision_supported(args.precision, context.device)

        dataset = TensorShardDataset(
            args.dataset,
            shuffle_shards=True,
            shuffle_seed=args.seed,
            rank=context.rank,
            world_size=context.world_size,
            verify_hashes=args.verify_data,
        )
        data_manifest = dataset.manifest
        if len(data_manifest.shards) < context.world_size:
            raise RuntimeError(
                f"dataset has {len(data_manifest.shards)} shards for "
                f"{context.world_size} ranks; every rank needs at least one shard"
            )
        model_config = get_spireformer_config(
            args.preset,
            entity_feature_dim=data_manifest.entity_feature_dim,
            action_feature_dim=data_manifest.action_feature_dim,
            dropout=args.dropout,
            max_timestep=args.max_timestep,
        )
        parameter_count = count_parameters(model_config)
        activation_checkpointing = args.activation_checkpointing
        if activation_checkpointing is None:
            activation_checkpointing = args.preset in {"medium", "large"}

        train_config = TrainConfig(
            precision=PrecisionMode.parse(args.precision),
            learning_rate=_learning_rate(args),
            weight_decay=args.weight_decay,
            warmup_steps=args.warmup_steps,
            total_steps=args.total_steps,
            min_lr_ratio=args.min_lr_ratio,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            max_grad_norm=args.max_grad_norm,
        )
        train_config.validate()
        manifest = SpireFormerManifest(
            schema_version=1,
            model_version=args.model_version or f"spireformer-{args.preset}-v1",
            tensorizer_version=data_manifest.tensorizer_version,
            vocabulary_hash=data_manifest.vocabulary_hash,
            reward_version=data_manifest.reward_version,
            no_save_load_information=True,
            config=model_config,
        )
        manifest.validate()

        loss_config = {
            "policy_weight": args.policy_weight,
            "value_weight": args.value_weight,
            "entropy_weight": args.entropy_weight,
        }
        resume_contract = {
            "schema_version": 1,
            "preset": args.preset,
            "model_manifest_digest": manifest.digest(),
            "dataset_manifest": data_manifest.to_dict(),
            "train_config": {
                **asdict(train_config),
                "precision": train_config.precision_mode.value,
            },
            "loss_config": loss_config,
            "batch_size": args.batch_size,
            "num_workers": args.num_workers,
            "activation_checkpointing": activation_checkpointing,
            "world_size": context.world_size,
            "device_type": context.device.type,
            "seed": args.seed,
            "torch_version": str(torch.__version__),
        }

        run_summary = {
            "schema_version": 1,
            "preset": args.preset,
            "parameter_count": parameter_count,
            "model_config": model_config.to_dict(),
            "train_config": {
                **asdict(train_config),
                "precision": train_config.precision_mode.value,
            },
            "model_manifest": manifest.to_dict(),
            "model_manifest_digest": manifest.digest(),
            "dataset_manifest": data_manifest.to_dict(),
            "loss_config": loss_config,
            "resume_contract": resume_contract,
            "activation_checkpointing": activation_checkpointing,
            "device": str(context.device),
            "world_size": context.world_size,
            "seed": args.seed,
            "torch_version": str(torch.__version__),
        }
        if args.dry_run:
            if context.is_primary:
                print(json.dumps(run_summary, ensure_ascii=False, indent=2))
            return 0

        output_dir = Path(args.output)
        checkpoint_path = output_dir / "checkpoint-latest.pt"
        if args.resume is None and checkpoint_path.exists():
            raise FileExistsError(
                f"checkpoint already exists at {checkpoint_path}; pass --resume "
                "or choose a new output directory"
            )
        if context.is_primary:
            output_dir.mkdir(parents=True, exist_ok=True)
        if context.world_size > 1:
            dist.barrier()

        loader = create_trajectory_dataloader(
            dataset,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            pin_memory=context.device.type == "cuda",
            drop_last=False,
            # Workers are recreated when the iterable dataset advances epoch,
            # so they observe the updated deterministic shard shuffle seed.
            persistent_workers=False,
        )
        if not dataset.assigned_shards():
            raise RuntimeError(
                f"rank {context.rank} received no shard; dataset has "
                f"{len(data_manifest.shards)} shards for {context.world_size} ranks"
            )

        raw_model = SpireFormer(model_config).to(context.device)
        raw_model.set_gradient_checkpointing(activation_checkpointing)
        optimizer = create_optimizer(raw_model, train_config)
        scheduler = create_warmup_cosine_scheduler(optimizer, train_config)
        criterion = SpireFormerCriterion(SpireFormerLossConfig(**loss_config))

        restored = None
        if args.resume is not None:
            restored = load_checkpoint(
                args.resume,
                model=raw_model,
                optimizer=optimizer,
                scheduler=scheduler,
                expected_manifest=manifest,
                # Load through CPU to avoid a second full checkpoint-sized
                # allocation on the accelerator during resume.
                map_location="cpu",
                restore_rng=False,
                expected_extra={"resume_contract": resume_contract},
            )

        training_model: Any = raw_model
        if context.world_size > 1:
            training_model = DistributedDataParallel(
                raw_model,
                device_ids=(
                    [context.device.index] if context.device.type == "cuda" else None
                ),
                output_device=(
                    context.device.index if context.device.type == "cuda" else None
                ),
            )
        trainer = SpireFormerTrainer(
            cast(SpireFormer, training_model),
            optimizer,
            scheduler,
            train_config,
            context.device,
            criterion,
        )
        if restored is not None:
            trainer.load_state_dict(restored.trainer_state)
            if restored.step != trainer.global_step:
                raise ValueError("checkpoint step and trainer global_step disagree")
        if trainer.global_step > train_config.total_steps:
            raise ValueError("checkpoint is beyond the requested total_steps")

        cursor = _BatchCursor(loader, dataset)
        if restored is not None:
            cursor_states = restored.extra.get("cursor_states")
            rng_states = restored.extra.get("rng_states")
            if (
                not isinstance(cursor_states, list)
                or len(cursor_states) != context.world_size
            ):
                raise ValueError("checkpoint cursor state does not match world size")
            if (
                not isinstance(rng_states, list)
                or len(rng_states) != context.world_size
            ):
                raise ValueError("checkpoint RNG state does not match world size")
            rank_cursor = cursor_states[context.rank]
            rank_rng = rng_states[context.rank]
            if not isinstance(rank_cursor, dict) or not isinstance(rank_rng, dict):
                raise ValueError("checkpoint rank state is malformed")
            cursor.load_state_dict(rank_cursor)
            # Iterator reconstruction may consume process RNG, so restore the
            # saved state only after the exact data position has been rebuilt.
            restore_rng_state(rank_rng)

        if context.is_primary:
            _atomic_write_json(output_dir / "run-config.json", run_summary)
        if context.world_size > 1:
            dist.barrier()

        metrics_path = output_dir / "metrics.jsonl"
        last_saved_step = -1
        while trainer.global_step < train_config.total_steps:
            batch, targets = cursor.next()
            metrics = trainer.train_microbatch(batch, targets)
            if not metrics.did_optimizer_step:
                continue
            if trainer.global_step % args.log_every == 0:
                aggregate = _aggregate_metrics(
                    trainer.train_metrics.compute(reset=True), context
                )
                record = {
                    "kind": "train",
                    "epoch": cursor.epoch,
                    **asdict(aggregate),
                }
                if context.is_primary:
                    print(json.dumps(record, sort_keys=True), flush=True)
                    _append_json_line(metrics_path, record)
            if trainer.global_step % args.checkpoint_every == 0:
                _save_training_checkpoint(
                    checkpoint_path,
                    raw_model=raw_model,
                    manifest=manifest,
                    trainer=trainer,
                    optimizer=optimizer,
                    scheduler=scheduler,
                    context=context,
                    preset=args.preset,
                    cursor=cursor,
                    resume_contract=resume_contract,
                )
                last_saved_step = trainer.global_step

        if trainer.global_step != last_saved_step:
            _save_training_checkpoint(
                checkpoint_path,
                raw_model=raw_model,
                manifest=manifest,
                trainer=trainer,
                optimizer=optimizer,
                scheduler=scheduler,
                context=context,
                preset=args.preset,
                cursor=cursor,
                resume_contract=resume_contract,
            )
        if context.is_primary:
            print(
                json.dumps(
                    {
                        "kind": "complete",
                        "global_step": trainer.global_step,
                        "checkpoint": str(checkpoint_path),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        return 0
    finally:
        if "context" in locals() and context.initialized_here:
            dist.destroy_process_group()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spireformer",
        description="Train and inspect the SlayTheModel SpireFormer policy.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    presets_parser = subparsers.add_parser(
        "presets", help="show exact parameter counts without allocating weights"
    )
    presets_parser.add_argument("--json", action="store_true")
    presets_parser.set_defaults(handler=_run_presets)

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="run a synthetic forward or backward pass without a dataset",
    )
    smoke_parser.add_argument("--preset", choices=available_presets(), default="tiny")
    smoke_parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    smoke_parser.add_argument(
        "--precision",
        choices=tuple(mode.value for mode in PrecisionMode),
        default=PrecisionMode.BF16.value,
    )
    smoke_parser.add_argument(
        "--mode", choices=("inference", "train"), default="inference"
    )
    smoke_parser.add_argument("--batch-size", type=int, default=1)
    smoke_parser.add_argument("--steps", type=int, default=2)
    smoke_parser.add_argument("--entities", type=int, default=16)
    smoke_parser.add_argument("--actions", type=int, default=16)
    smoke_parser.add_argument("--seed", type=int, default=20260924)
    smoke_parser.set_defaults(handler=_run_smoke)

    train_parser = subparsers.add_parser(
        "train", help="train from a versioned tensor-shard dataset"
    )
    train_parser.add_argument("--dataset", required=True)
    train_parser.add_argument("--output", required=True)
    train_parser.add_argument("--preset", choices=available_presets(), default="tiny")
    train_parser.add_argument(
        "--precision",
        choices=tuple(mode.value for mode in PrecisionMode),
        default=PrecisionMode.BF16.value,
    )
    train_parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda", "mps"), default="auto"
    )
    train_parser.add_argument("--model-version")
    train_parser.add_argument("--batch-size", type=int, default=1)
    train_parser.add_argument("--num-workers", type=int, default=0)
    train_parser.add_argument("--total-steps", type=int, default=100_000)
    train_parser.add_argument("--warmup-steps", type=int, default=1_000)
    train_parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    train_parser.add_argument("--learning-rate", type=float)
    train_parser.add_argument("--weight-decay", type=float, default=0.1)
    train_parser.add_argument("--min-lr-ratio", type=float, default=0.1)
    train_parser.add_argument("--max-grad-norm", type=float, default=1.0)
    train_parser.add_argument("--dropout", type=float, default=0.1)
    train_parser.add_argument("--max-timestep", type=int, default=4096)
    train_parser.add_argument("--policy-weight", type=float, default=1.0)
    train_parser.add_argument("--value-weight", type=float, default=0.25)
    train_parser.add_argument("--entropy-weight", type=float, default=0.01)
    train_parser.add_argument("--seed", type=int, default=20260924)
    train_parser.add_argument("--log-every", type=int, default=10)
    train_parser.add_argument("--checkpoint-every", type=int, default=1_000)
    train_parser.add_argument("--resume")
    train_parser.add_argument("--verify-data", action="store_true")
    train_parser.add_argument("--dry-run", action="store_true")
    train_parser.add_argument(
        "--activation-checkpointing",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="default: enabled for medium/large, disabled for tiny/small",
    )
    train_parser.set_defaults(handler=_run_train)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in (
        "batch_size",
        "total_steps",
        "gradient_accumulation_steps",
        "log_every",
        "checkpoint_every",
        "steps",
        "entities",
        "actions",
        "seed",
    ):
        if hasattr(args, name) and getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
