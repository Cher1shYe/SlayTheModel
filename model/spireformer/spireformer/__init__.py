"""SpireFormer v0.1 public API."""

from .batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets
from .checkpoint import (
    CheckpointState,
    capture_rng_state,
    load_checkpoint,
    restore_rng_state,
    save_checkpoint,
)
from .data import (
    TensorDatasetManifest,
    TensorShardDataset,
    TensorShardInfo,
    TensorShardWriter,
    create_trajectory_dataloader,
    write_tensor_dataset,
)
from .decision_transformer import DecisionTransformerCore
from .losses import (
    SpireFormerCriterion,
    SpireFormerLoss,
    SpireFormerLossConfig,
    compute_spireformer_loss,
)
from .manifest import SpireFormerManifest
from .model import SpireFormer, SpireFormerConfig, SpireFormerOutput
from .precision import (
    PrecisionMode,
    autocast_context,
    cast_model_for_inference,
    ensure_precision_supported,
)
from .presets import (
    SPIREFORMER_PRESETS,
    SpireFormerPreset,
    available_presets,
    count_parameters,
    get_preset,
    get_spireformer_config,
)
from .set_transformer import ISAB, MAB, PMA, SAB, SetEncoder
from .trajectory import Trajectory, TrajectoryStep, collate_trajectories
from .training import (
    AggregatedMetrics,
    MetricAccumulator,
    OptimizerStepResult,
    SpireFormerTrainer,
    StepMetrics,
    TrainConfig,
    create_optimizer,
    create_warmup_cosine_scheduler,
)

__version__ = "0.1.0"

__all__ = [
    "DecisionDomain",
    "DecisionTransformerCore",
    "CheckpointState",
    "ISAB",
    "MAB",
    "PMA",
    "SAB",
    "SetEncoder",
    "AggregatedMetrics",
    "MetricAccumulator",
    "OptimizerStepResult",
    "PrecisionMode",
    "SPIREFORMER_PRESETS",
    "SpireFormer",
    "SpireFormerBatch",
    "SpireFormerConfig",
    "SpireFormerCriterion",
    "SpireFormerLoss",
    "SpireFormerLossConfig",
    "SpireFormerManifest",
    "SpireFormerOutput",
    "SpireFormerPreset",
    "SpireFormerTrainer",
    "SpireFormerTargets",
    "StepMetrics",
    "TensorDatasetManifest",
    "TensorShardDataset",
    "TensorShardInfo",
    "TensorShardWriter",
    "TrainConfig",
    "Trajectory",
    "TrajectoryStep",
    "autocast_context",
    "available_presets",
    "capture_rng_state",
    "cast_model_for_inference",
    "collate_trajectories",
    "count_parameters",
    "compute_spireformer_loss",
    "create_optimizer",
    "create_trajectory_dataloader",
    "create_warmup_cosine_scheduler",
    "ensure_precision_supported",
    "get_preset",
    "get_spireformer_config",
    "load_checkpoint",
    "restore_rng_state",
    "save_checkpoint",
    "write_tensor_dataset",
]
