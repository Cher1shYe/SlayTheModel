"""Versioned, safe tensor shards for SpireFormer training.

The shards in this module are a derived training representation.  A future raw
JSONL capture stream remains the auditable source of truth; identifiers such as
``state_fingerprint`` and ``action_id`` intentionally never become model input
features here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
import random
import tempfile
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence, TypeGuard, cast
from uuid import uuid4

import torch
from torch import Tensor
from torch.utils.data import DataLoader, IterableDataset, get_worker_info

from .batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets
from .trajectory import Trajectory, TrajectoryStep, collate_trajectories


TENSOR_DATASET_SCHEMA_VERSION = 1
TENSOR_SHARD_SCHEMA_VERSION = 1
TENSOR_DATASET_MANIFEST = "manifest.json"
TENSOR_SHARD_FORMAT = "spireformer.tensor-shard"

_SHARD_KEYS = frozenset(
    {
        "format",
        "schema_version",
        "entity_feature_dim",
        "action_feature_dim",
        "feature_dtype",
        "trajectory_count",
        "step_count",
        "trajectory_step_offsets",
        "entity_offsets",
        "action_offsets",
        "entity_features",
        "legal_action_features",
        "selected_action_indices",
        "returns_to_go",
        "timesteps",
        "domain_ids",
        "value_targets",
        "value_target_mask",
        "teacher_policy",
        "teacher_policy_mask",
    }
)

_DTYPE_TO_NAME = {
    torch.float16: "float16",
    torch.bfloat16: "bfloat16",
    torch.float32: "float32",
    torch.float64: "float64",
}
_NAME_TO_DTYPE = {name: dtype for dtype, name in _DTYPE_TO_NAME.items()}


def _is_plain_int(value: object) -> TypeGuard[int]:
    return type(value) is int


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_torch_save(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        torch.save(dict(payload), temporary_path)
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


@dataclass(frozen=True, slots=True)
class TensorShardInfo:
    """One immutable shard entry in a :class:`TensorDatasetManifest`."""

    file: str
    trajectory_count: int
    step_count: int
    byte_count: int
    sha256: str

    def validate(self) -> None:
        _require_non_empty_string(self.file, "shard file")
        if Path(self.file).name != self.file or self.file in (".", ".."):
            raise ValueError("shard file must be a plain filename")
        if not self.file.endswith(".pt"):
            raise ValueError("shard file must use the .pt extension")
        for name in ("trajectory_count", "step_count", "byte_count"):
            value = getattr(self, name)
            if not _is_plain_int(value):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.step_count < self.trajectory_count:
            raise ValueError("each trajectory must contain at least one step")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise ValueError("shard sha256 must contain 64 hexadecimal characters")
        try:
            int(self.sha256, 16)
        except ValueError as error:
            raise ValueError("shard sha256 is not hexadecimal") from error

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "file": self.file,
            "trajectory_count": self.trajectory_count,
            "step_count": self.step_count,
            "byte_count": self.byte_count,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "TensorShardInfo":
        expected = {
            "file",
            "trajectory_count",
            "step_count",
            "byte_count",
            "sha256",
        }
        if set(values) != expected:
            raise ValueError(
                f"invalid shard metadata keys: expected {sorted(expected)}, "
                f"got {sorted(values)}"
            )
        shard = cls(
            file=values["file"],  # type: ignore[arg-type]
            trajectory_count=values["trajectory_count"],  # type: ignore[arg-type]
            step_count=values["step_count"],  # type: ignore[arg-type]
            byte_count=values["byte_count"],  # type: ignore[arg-type]
            sha256=values["sha256"],  # type: ignore[arg-type]
        )
        shard.validate()
        return shard


@dataclass(frozen=True, slots=True)
class TensorDatasetManifest:
    """Compatibility contract and immutable shard inventory for one dataset."""

    schema_version: int
    dataset_id: str
    created_at_utc: str
    tensorizer_version: str
    vocabulary_hash: str
    reward_version: str
    no_save_load_information: bool
    entity_feature_dim: int
    action_feature_dim: int
    feature_dtype: str
    shards: tuple[TensorShardInfo, ...]

    @property
    def trajectory_count(self) -> int:
        return sum(shard.trajectory_count for shard in self.shards)

    @property
    def step_count(self) -> int:
        return sum(shard.step_count for shard in self.shards)

    def validate(self) -> None:
        if not _is_plain_int(self.schema_version):
            raise TypeError("schema_version must be an integer")
        if self.schema_version != TENSOR_DATASET_SCHEMA_VERSION:
            raise ValueError(f"unsupported tensor dataset schema {self.schema_version}")
        for name in (
            "dataset_id",
            "created_at_utc",
            "tensorizer_version",
            "vocabulary_hash",
            "reward_version",
        ):
            _require_non_empty_string(getattr(self, name), name)
        if type(self.no_save_load_information) is not bool:
            raise TypeError("no_save_load_information must be a boolean")
        if not self.no_save_load_information:
            raise ValueError("SpireFormer tensor schema v1 only supports no-SL data")
        for name in ("entity_feature_dim", "action_feature_dim"):
            value = getattr(self, name)
            if not _is_plain_int(value):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.feature_dtype not in _NAME_TO_DTYPE:
            raise ValueError(f"unsupported feature dtype {self.feature_dtype!r}")
        if not isinstance(self.shards, tuple) or not self.shards:
            raise ValueError("a tensor dataset must contain at least one shard")
        filenames: set[str] = set()
        for shard in self.shards:
            if not isinstance(shard, TensorShardInfo):
                raise TypeError("shards must contain TensorShardInfo values")
            shard.validate()
            if shard.file in filenames:
                raise ValueError(f"duplicate shard filename {shard.file!r}")
            filenames.add(shard.file)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "created_at_utc": self.created_at_utc,
            "tensorizer_version": self.tensorizer_version,
            "vocabulary_hash": self.vocabulary_hash,
            "reward_version": self.reward_version,
            "no_save_load_information": self.no_save_load_information,
            "entity_feature_dim": self.entity_feature_dim,
            "action_feature_dim": self.action_feature_dim,
            "feature_dtype": self.feature_dtype,
            "trajectory_count": self.trajectory_count,
            "step_count": self.step_count,
            "shards": [shard.to_dict() for shard in self.shards],
        }

    def to_json(self) -> str:
        return (
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        )

    def save(self, root_or_manifest: str | os.PathLike[str]) -> Path:
        """Atomically publish the manifest after every shard is durable."""

        path = Path(root_or_manifest)
        if path.suffix.lower() != ".json":
            path = path / TENSOR_DATASET_MANIFEST
        _atomic_write_text(path, self.to_json())
        return path

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "TensorDatasetManifest":
        expected = {
            "schema_version",
            "dataset_id",
            "created_at_utc",
            "tensorizer_version",
            "vocabulary_hash",
            "reward_version",
            "no_save_load_information",
            "entity_feature_dim",
            "action_feature_dim",
            "feature_dtype",
            "trajectory_count",
            "step_count",
            "shards",
        }
        if set(values) != expected:
            raise ValueError(
                f"invalid manifest keys: expected {sorted(expected)}, "
                f"got {sorted(values)}"
            )
        for count_name in ("trajectory_count", "step_count"):
            count = values[count_name]
            if not _is_plain_int(count):
                raise TypeError(f"manifest {count_name} must be an integer")
            if count < 1:
                raise ValueError(f"manifest {count_name} must be positive")
        raw_shards = values["shards"]
        if not isinstance(raw_shards, list):
            raise TypeError("manifest shards must be a JSON array")
        shards = tuple(
            (
                TensorShardInfo.from_dict(shard)
                if isinstance(shard, Mapping)
                else _raise_type_error("each shard entry must be an object")
            )
            for shard in raw_shards
        )
        manifest = cls(
            schema_version=values["schema_version"],  # type: ignore[arg-type]
            dataset_id=values["dataset_id"],  # type: ignore[arg-type]
            created_at_utc=values["created_at_utc"],  # type: ignore[arg-type]
            tensorizer_version=values["tensorizer_version"],  # type: ignore[arg-type]
            vocabulary_hash=values["vocabulary_hash"],  # type: ignore[arg-type]
            reward_version=values["reward_version"],  # type: ignore[arg-type]
            no_save_load_information=values[  # type: ignore[arg-type]
                "no_save_load_information"
            ],
            entity_feature_dim=values["entity_feature_dim"],  # type: ignore[arg-type]
            action_feature_dim=values["action_feature_dim"],  # type: ignore[arg-type]
            feature_dtype=values["feature_dtype"],  # type: ignore[arg-type]
            shards=shards,
        )
        manifest.validate()
        if values["trajectory_count"] != manifest.trajectory_count:
            raise ValueError("manifest trajectory_count does not match its shards")
        if values["step_count"] != manifest.step_count:
            raise ValueError("manifest step_count does not match its shards")
        return manifest

    @classmethod
    def from_json(cls, payload: str) -> "TensorDatasetManifest":
        values = json.loads(payload)
        if not isinstance(values, dict):
            raise ValueError("manifest JSON root must be an object")
        return cls.from_dict(values)

    @classmethod
    def load(cls, root_or_manifest: str | os.PathLike[str]) -> "TensorDatasetManifest":
        path = Path(root_or_manifest)
        if path.is_dir() or path.suffix.lower() != ".json":
            path = path / TENSOR_DATASET_MANIFEST
        return cls.from_json(path.read_text(encoding="utf-8"))


def _raise_type_error(message: str) -> Any:
    raise TypeError(message)


def _validate_source_trajectory(
    trajectory: Trajectory,
    entity_feature_dim: int,
    action_feature_dim: int,
) -> None:
    if not isinstance(trajectory, Trajectory):
        raise TypeError("writer accepts Trajectory values only")
    if not trajectory.steps:
        raise ValueError("empty trajectories cannot be serialized")
    for step in trajectory.steps:
        if not isinstance(step, TrajectoryStep):
            raise TypeError("trajectory steps must be TrajectoryStep values")
        step.validate(entity_feature_dim, action_feature_dim)
        if not step.entity_features.is_floating_point():
            raise TypeError("entity features must use a floating-point dtype")
        if not step.legal_action_features.is_floating_point():
            raise TypeError("action features must use a floating-point dtype")
        if not torch.isfinite(step.entity_features).all():
            raise ValueError("entity features contain NaN or infinity")
        if not torch.isfinite(step.legal_action_features).all():
            raise ValueError("action features contain NaN or infinity")
        if not torch.isfinite(torch.tensor(step.return_to_go)):
            raise ValueError("return_to_go must be finite")
        if step.value_target is not None and not torch.isfinite(
            torch.tensor(step.value_target)
        ):
            raise ValueError("value_target must be finite when present")
        if step.teacher_policy is not None:
            if not step.teacher_policy.is_floating_point():
                raise TypeError("teacher_policy must use a floating-point dtype")
            if not torch.isfinite(step.teacher_policy).all():
                raise ValueError("teacher_policy contains NaN or infinity")


def _pack_trajectories(
    trajectories: Sequence[Trajectory],
    *,
    entity_feature_dim: int,
    action_feature_dim: int,
    dtype: torch.dtype,
) -> dict[str, object]:
    if not trajectories:
        raise ValueError("a shard must contain at least one trajectory")
    if dtype not in _DTYPE_TO_NAME:
        raise ValueError(f"unsupported feature dtype {dtype}")
    for trajectory in trajectories:
        _validate_source_trajectory(trajectory, entity_feature_dim, action_feature_dim)

    trajectory_step_offsets = [0]
    entity_offsets = [0]
    action_offsets = [0]
    entity_features: list[Tensor] = []
    action_features: list[Tensor] = []
    selected_action_indices: list[int] = []
    returns_to_go: list[float] = []
    timesteps: list[int] = []
    domain_ids: list[int] = []
    value_targets: list[float] = []
    value_target_mask: list[bool] = []
    teacher_policy: list[Tensor] = []
    teacher_policy_mask: list[bool] = []

    for trajectory in trajectories:
        for step in trajectory.steps:
            entities = (
                step.entity_features.detach().to(device="cpu", dtype=dtype).contiguous()
            )
            actions = (
                step.legal_action_features.detach()
                .to(device="cpu", dtype=dtype)
                .contiguous()
            )
            entity_features.append(entities)
            action_features.append(actions)
            entity_offsets.append(entity_offsets[-1] + entities.shape[0])
            action_offsets.append(action_offsets[-1] + actions.shape[0])
            selected_action_indices.append(step.selected_action_index)
            returns_to_go.append(step.return_to_go)
            timesteps.append(step.timestep)
            domain_ids.append(int(step.domain))
            value_targets.append(
                0.0 if step.value_target is None else step.value_target
            )
            value_target_mask.append(step.value_target is not None)
            if step.teacher_policy is None:
                teacher_policy.append(torch.zeros(actions.shape[0], dtype=dtype))
                teacher_policy_mask.append(False)
            else:
                teacher_policy.append(
                    step.teacher_policy.detach()
                    .to(device="cpu", dtype=dtype)
                    .contiguous()
                )
                teacher_policy_mask.append(True)
        trajectory_step_offsets.append(
            trajectory_step_offsets[-1] + len(trajectory.steps)
        )

    step_count = trajectory_step_offsets[-1]
    return {
        "format": TENSOR_SHARD_FORMAT,
        "schema_version": TENSOR_SHARD_SCHEMA_VERSION,
        "entity_feature_dim": entity_feature_dim,
        "action_feature_dim": action_feature_dim,
        "feature_dtype": _DTYPE_TO_NAME[dtype],
        "trajectory_count": len(trajectories),
        "step_count": step_count,
        "trajectory_step_offsets": torch.tensor(
            trajectory_step_offsets, dtype=torch.int64
        ),
        "entity_offsets": torch.tensor(entity_offsets, dtype=torch.int64),
        "action_offsets": torch.tensor(action_offsets, dtype=torch.int64),
        "entity_features": torch.cat(entity_features, dim=0),
        "legal_action_features": torch.cat(action_features, dim=0),
        "selected_action_indices": torch.tensor(
            selected_action_indices, dtype=torch.int64
        ),
        "returns_to_go": torch.tensor(returns_to_go, dtype=dtype),
        "timesteps": torch.tensor(timesteps, dtype=torch.int64),
        "domain_ids": torch.tensor(domain_ids, dtype=torch.int64),
        "value_targets": torch.tensor(value_targets, dtype=dtype),
        "value_target_mask": torch.tensor(value_target_mask, dtype=torch.bool),
        "teacher_policy": torch.cat(teacher_policy, dim=0),
        "teacher_policy_mask": torch.tensor(teacher_policy_mask, dtype=torch.bool),
    }


def _require_tensor(
    payload: Mapping[str, object], name: str, *, dtype: torch.dtype, ndim: int
) -> Tensor:
    value = payload[name]
    if not isinstance(value, Tensor):
        raise TypeError(f"shard field {name!r} must be a tensor")
    if value.dtype != dtype:
        raise TypeError(f"shard field {name!r} must use {dtype}, got {value.dtype}")
    if value.ndim != ndim:
        raise ValueError(f"shard field {name!r} must have rank {ndim}")
    return value


def _validate_offsets(
    offsets: Tensor, *, expected_length: int, expected_end: int, name: str
) -> None:
    if offsets.shape != (expected_length,):
        raise ValueError(f"{name} must have shape [{expected_length}]")
    if offsets[0].item() != 0 or offsets[-1].item() != expected_end:
        raise ValueError(f"{name} endpoints do not match packed data")
    if offsets.numel() > 1 and torch.any(offsets[1:] <= offsets[:-1]):
        raise ValueError(f"{name} must be strictly increasing")


def _validate_shard_payload(
    payload: object,
    *,
    entity_feature_dim: int,
    action_feature_dim: int,
    feature_dtype: str,
    trajectory_count: int,
    step_count: int,
) -> Mapping[str, object]:
    if type(payload) is not dict:
        raise TypeError("tensor shard root must be a plain dictionary")
    if set(payload) != _SHARD_KEYS:
        raise ValueError(
            f"invalid tensor shard keys: expected {sorted(_SHARD_KEYS)}, "
            f"got {sorted(payload)}"
        )
    if not isinstance(payload["format"], str):
        raise TypeError("tensor shard format must be a string")
    if payload["format"] != TENSOR_SHARD_FORMAT:
        raise ValueError("not a SpireFormer tensor shard")
    if not _is_plain_int(payload["schema_version"]):
        raise TypeError("tensor shard schema_version must be an integer")
    if payload["schema_version"] != TENSOR_SHARD_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported tensor shard schema {payload['schema_version']!r}"
        )
    scalar_expectations = {
        "entity_feature_dim": entity_feature_dim,
        "action_feature_dim": action_feature_dim,
        "feature_dtype": feature_dtype,
        "trajectory_count": trajectory_count,
        "step_count": step_count,
    }
    for name, expected in scalar_expectations.items():
        if isinstance(expected, int) and not _is_plain_int(payload[name]):
            raise TypeError(f"shard {name} must be an integer")
        if isinstance(expected, str) and not isinstance(payload[name], str):
            raise TypeError(f"shard {name} must be a string")
        if payload[name] != expected:
            raise ValueError(
                f"shard {name} mismatch: expected {expected!r}, "
                f"got {payload[name]!r}"
            )

    dtype = _NAME_TO_DTYPE[feature_dtype]
    trajectory_offsets = _require_tensor(
        payload, "trajectory_step_offsets", dtype=torch.int64, ndim=1
    )
    entity_offsets = _require_tensor(
        payload, "entity_offsets", dtype=torch.int64, ndim=1
    )
    action_offsets = _require_tensor(
        payload, "action_offsets", dtype=torch.int64, ndim=1
    )
    entity_features = _require_tensor(payload, "entity_features", dtype=dtype, ndim=2)
    action_features = _require_tensor(
        payload, "legal_action_features", dtype=dtype, ndim=2
    )
    selected = _require_tensor(
        payload, "selected_action_indices", dtype=torch.int64, ndim=1
    )
    returns = _require_tensor(payload, "returns_to_go", dtype=dtype, ndim=1)
    timesteps = _require_tensor(payload, "timesteps", dtype=torch.int64, ndim=1)
    domains = _require_tensor(payload, "domain_ids", dtype=torch.int64, ndim=1)
    values = _require_tensor(payload, "value_targets", dtype=dtype, ndim=1)
    value_mask = _require_tensor(payload, "value_target_mask", dtype=torch.bool, ndim=1)
    teacher = _require_tensor(payload, "teacher_policy", dtype=dtype, ndim=1)
    teacher_mask = _require_tensor(
        payload, "teacher_policy_mask", dtype=torch.bool, ndim=1
    )

    if entity_features.shape[1] != entity_feature_dim:
        raise ValueError("packed entity feature width does not match manifest")
    if action_features.shape[1] != action_feature_dim:
        raise ValueError("packed action feature width does not match manifest")
    _validate_offsets(
        trajectory_offsets,
        expected_length=trajectory_count + 1,
        expected_end=step_count,
        name="trajectory_step_offsets",
    )
    _validate_offsets(
        entity_offsets,
        expected_length=step_count + 1,
        expected_end=entity_features.shape[0],
        name="entity_offsets",
    )
    _validate_offsets(
        action_offsets,
        expected_length=step_count + 1,
        expected_end=action_features.shape[0],
        name="action_offsets",
    )
    for name, tensor in (
        ("selected_action_indices", selected),
        ("returns_to_go", returns),
        ("timesteps", timesteps),
        ("domain_ids", domains),
        ("value_targets", values),
        ("value_target_mask", value_mask),
        ("teacher_policy_mask", teacher_mask),
    ):
        if tensor.shape != (step_count,):
            raise ValueError(f"{name} must have shape [{step_count}]")
    if teacher.shape != (action_features.shape[0],):
        raise ValueError("teacher_policy must have one value per packed action")

    if torch.any(timesteps < 0):
        raise ValueError("timesteps must be non-negative")
    if torch.any(
        (domains < int(DecisionDomain.COMBAT))
        | (domains > int(DecisionDomain.OUTSIDE_COMBAT))
    ):
        raise ValueError("domain_ids contain an unsupported decision domain")
    action_counts = action_offsets[1:] - action_offsets[:-1]
    if torch.any((selected < 0) | (selected >= action_counts)):
        raise ValueError("a selected action index is outside its local action set")
    for name, tensor in (
        ("entity_features", entity_features),
        ("legal_action_features", action_features),
        ("returns_to_go", returns),
        ("value_targets", values),
        ("teacher_policy", teacher),
    ):
        if not torch.isfinite(tensor).all():
            raise ValueError(f"{name} contains NaN or infinity")
    if torch.any(teacher < 0):
        raise ValueError("teacher_policy contains negative probability mass")
    teacher_for_sum = teacher.to(torch.float64)
    teacher_prefix_sum = torch.cat(
        (teacher_for_sum.new_zeros(1), teacher_for_sum.cumsum(dim=0))
    )
    teacher_row_sums = (
        teacher_prefix_sum[action_offsets[1:]] - teacher_prefix_sum[action_offsets[:-1]]
    )
    enabled_teacher_sums = teacher_row_sums[teacher_mask]
    probability_tolerance = max(1e-5, float(torch.finfo(dtype).eps) * 4.0)
    if enabled_teacher_sums.numel() and not torch.allclose(
        enabled_teacher_sums,
        torch.ones_like(enabled_teacher_sums),
        atol=probability_tolerance,
        rtol=probability_tolerance,
    ):
        raise ValueError("an enabled teacher policy does not sum to one")
    if torch.any(teacher_row_sums[~teacher_mask] != 0):
        raise ValueError("a disabled teacher policy row must contain only zero")
    if torch.any(~value_mask & (values != 0)):
        raise ValueError("disabled value targets must be serialized as zero")
    return payload


def _unpack_trajectories(payload: Mapping[str, object]) -> Iterator[Trajectory]:
    # The payload has already passed _validate_shard_payload.  Casts keep this
    # hot reconstruction loop readable without weakening the on-disk checks.
    trajectory_offsets = cast(Tensor, payload["trajectory_step_offsets"])
    entity_offsets = cast(Tensor, payload["entity_offsets"])
    action_offsets = cast(Tensor, payload["action_offsets"])
    entity_features = cast(Tensor, payload["entity_features"])
    action_features = cast(Tensor, payload["legal_action_features"])
    selected = cast(Tensor, payload["selected_action_indices"])
    returns = cast(Tensor, payload["returns_to_go"])
    timesteps = cast(Tensor, payload["timesteps"])
    domains = cast(Tensor, payload["domain_ids"])
    values = cast(Tensor, payload["value_targets"])
    value_mask = cast(Tensor, payload["value_target_mask"])
    teacher = cast(Tensor, payload["teacher_policy"])
    teacher_mask = cast(Tensor, payload["teacher_policy_mask"])
    trajectory_count = cast(int, payload["trajectory_count"])

    for trajectory_index in range(trajectory_count):
        first_step = int(trajectory_offsets[trajectory_index].item())
        last_step = int(trajectory_offsets[trajectory_index + 1].item())
        steps: list[TrajectoryStep] = []
        for step_index in range(first_step, last_step):
            entity_start = int(entity_offsets[step_index].item())
            entity_end = int(entity_offsets[step_index + 1].item())
            action_start = int(action_offsets[step_index].item())
            action_end = int(action_offsets[step_index + 1].item())
            steps.append(
                TrajectoryStep(
                    entity_features=entity_features[entity_start:entity_end],
                    legal_action_features=action_features[action_start:action_end],
                    selected_action_index=int(selected[step_index].item()),
                    return_to_go=float(returns[step_index].item()),
                    timestep=int(timesteps[step_index].item()),
                    domain=DecisionDomain(int(domains[step_index].item())),
                    value_target=(
                        float(values[step_index].item())
                        if bool(value_mask[step_index].item())
                        else None
                    ),
                    teacher_policy=(
                        teacher[action_start:action_end]
                        if bool(teacher_mask[step_index].item())
                        else None
                    ),
                )
            )
        yield Trajectory(tuple(steps))


class TensorShardWriter:
    """Stream trajectories into immutable, atomically-published tensor shards."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        entity_feature_dim: int,
        action_feature_dim: int,
        tensorizer_version: str,
        vocabulary_hash: str,
        reward_version: str,
        dataset_id: str | None = None,
        trajectories_per_shard: int = 1024,
        dtype: torch.dtype = torch.float32,
        overwrite: bool = False,
    ) -> None:
        self.root = Path(root)
        if not _is_plain_int(entity_feature_dim) or entity_feature_dim < 1:
            raise ValueError("entity_feature_dim must be a positive integer")
        if not _is_plain_int(action_feature_dim) or action_feature_dim < 1:
            raise ValueError("action_feature_dim must be a positive integer")
        if not _is_plain_int(trajectories_per_shard) or trajectories_per_shard < 1:
            raise ValueError("trajectories_per_shard must be a positive integer")
        if dtype not in _DTYPE_TO_NAME:
            raise ValueError(f"unsupported feature dtype {dtype}")
        self.entity_feature_dim = entity_feature_dim
        self.action_feature_dim = action_feature_dim
        self.tensorizer_version = _require_non_empty_string(
            tensorizer_version, "tensorizer_version"
        )
        self.vocabulary_hash = _require_non_empty_string(
            vocabulary_hash, "vocabulary_hash"
        )
        self.reward_version = _require_non_empty_string(
            reward_version, "reward_version"
        )
        self.dataset_id = _require_non_empty_string(
            dataset_id or uuid4().hex, "dataset_id"
        )
        self.trajectories_per_shard = trajectories_per_shard
        self.dtype = dtype
        self.overwrite = overwrite
        self._buffer: list[Trajectory] = []
        self._shards: list[TensorShardInfo] = []
        self._closed = False
        self._aborted = False
        # Unique names let overwrite=True build a complete replacement beside
        # the currently published dataset.  The old manifest remains valid
        # until the final atomic manifest swap.
        self._publication_id = uuid4().hex[:12]

        if type(overwrite) is not bool:
            raise TypeError("overwrite must be a boolean")
        manifest_path = self.root / TENSOR_DATASET_MANIFEST
        if manifest_path.exists() and not overwrite:
            raise FileExistsError(f"dataset already exists at {manifest_path}")
        self.root.mkdir(parents=True, exist_ok=True)

    def add(self, trajectory: Trajectory) -> None:
        if self._closed or self._aborted:
            raise RuntimeError("cannot add to a closed tensor shard writer")
        _validate_source_trajectory(
            trajectory, self.entity_feature_dim, self.action_feature_dim
        )
        self._buffer.append(trajectory)
        if len(self._buffer) >= self.trajectories_per_shard:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        filename = f"shard-{self._publication_id}-{len(self._shards):06d}.pt"
        path = self.root / filename
        if path.exists() and not self.overwrite:
            raise FileExistsError(f"refusing to overwrite existing shard {path}")
        payload = _pack_trajectories(
            self._buffer,
            entity_feature_dim=self.entity_feature_dim,
            action_feature_dim=self.action_feature_dim,
            dtype=self.dtype,
        )
        # Validate the canonical, cast representation too.  This catches, for
        # example, a finite float64 value that overflows while being converted
        # to a requested float16 storage dtype before any file is published.
        _validate_shard_payload(
            payload,
            entity_feature_dim=self.entity_feature_dim,
            action_feature_dim=self.action_feature_dim,
            feature_dtype=_DTYPE_TO_NAME[self.dtype],
            trajectory_count=len(self._buffer),
            step_count=sum(len(trajectory.steps) for trajectory in self._buffer),
        )
        _atomic_torch_save(path, payload)
        shard = TensorShardInfo(
            file=filename,
            trajectory_count=len(self._buffer),
            step_count=sum(len(trajectory.steps) for trajectory in self._buffer),
            byte_count=path.stat().st_size,
            sha256=_sha256_file(path),
        )
        shard.validate()
        self._shards.append(shard)
        self._buffer.clear()

    def close(self) -> TensorDatasetManifest:
        if self._aborted:
            raise RuntimeError("cannot close an aborted tensor shard writer")
        if self._closed:
            raise RuntimeError("tensor shard writer is already closed")
        self._flush()
        if not self._shards:
            raise ValueError("cannot publish an empty tensor dataset")
        manifest = TensorDatasetManifest(
            schema_version=TENSOR_DATASET_SCHEMA_VERSION,
            dataset_id=self.dataset_id,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            tensorizer_version=self.tensorizer_version,
            vocabulary_hash=self.vocabulary_hash,
            reward_version=self.reward_version,
            no_save_load_information=True,
            entity_feature_dim=self.entity_feature_dim,
            action_feature_dim=self.action_feature_dim,
            feature_dtype=_DTYPE_TO_NAME[self.dtype],
            shards=tuple(self._shards),
        )
        manifest.save(self.root)
        self._closed = True
        return manifest

    def __enter__(self) -> "TensorShardWriter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.close()
        else:
            # Already-published shard files may remain after a failed producer,
            # but no manifest is written, so readers cannot observe a partial
            # dataset as complete.
            self._aborted = True
            self._buffer.clear()


def write_tensor_dataset(
    root: str | os.PathLike[str],
    trajectories: Iterable[Trajectory],
    *,
    entity_feature_dim: int,
    action_feature_dim: int,
    tensorizer_version: str,
    vocabulary_hash: str,
    reward_version: str,
    dataset_id: str | None = None,
    trajectories_per_shard: int = 1024,
    dtype: torch.dtype = torch.float32,
    overwrite: bool = False,
) -> TensorDatasetManifest:
    """Convenience wrapper for a finite trajectory iterable."""

    writer = TensorShardWriter(
        root,
        entity_feature_dim=entity_feature_dim,
        action_feature_dim=action_feature_dim,
        tensorizer_version=tensorizer_version,
        vocabulary_hash=vocabulary_hash,
        reward_version=reward_version,
        dataset_id=dataset_id,
        trajectories_per_shard=trajectories_per_shard,
        dtype=dtype,
        overwrite=overwrite,
    )
    try:
        for trajectory in trajectories:
            writer.add(trajectory)
        return writer.close()
    except BaseException:
        writer._aborted = True
        writer._buffer.clear()
        raise


class TensorShardDataset(IterableDataset[Trajectory]):
    """Stream tensor shards once per distributed rank/DataLoader worker."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        shuffle_shards: bool = False,
        shuffle_seed: int = 0,
        rank: int | None = None,
        world_size: int | None = None,
        verify_hashes: bool = False,
        expected_tensorizer_version: str | None = None,
        expected_vocabulary_hash: str | None = None,
        expected_reward_version: str | None = None,
    ) -> None:
        super().__init__()
        self.root = Path(root)
        self.manifest = TensorDatasetManifest.load(self.root)
        self.shuffle_shards = shuffle_shards
        self.shuffle_seed = shuffle_seed
        self.verify_hashes = verify_hashes
        # A shared-memory scalar lets persistent DataLoader worker processes
        # observe set_epoch() without rebuilding the loader. This also keeps
        # live training and torchrun shard ordering deterministic.
        self._shared_epoch = torch.zeros((), dtype=torch.int64)
        try:
            self._shared_epoch.share_memory_()
            self._epoch_is_shared = True
        except RuntimeError:
            # Sandboxed systems can forbid torch_shm_manager. Single-process
            # loading remains correct; persistent workers are rejected below
            # because they could not observe epoch changes.
            self._epoch_is_shared = False
        if type(shuffle_shards) is not bool:
            raise TypeError("shuffle_shards must be a boolean")
        if not _is_plain_int(shuffle_seed):
            raise TypeError("shuffle_seed must be an integer")
        if type(verify_hashes) is not bool:
            raise TypeError("verify_hashes must be a boolean")
        compatibility_checks = (
            (
                "tensorizer_version",
                expected_tensorizer_version,
                self.manifest.tensorizer_version,
            ),
            (
                "vocabulary_hash",
                expected_vocabulary_hash,
                self.manifest.vocabulary_hash,
            ),
            ("reward_version", expected_reward_version, self.manifest.reward_version),
        )
        for name, expected, actual in compatibility_checks:
            if expected is not None and expected != actual:
                raise ValueError(
                    f"dataset {name} mismatch: expected {expected!r}, got {actual!r}"
                )

        if (rank is None) != (world_size is None):
            raise ValueError("rank and world_size must be specified together")
        if rank is None:
            if torch.distributed.is_available() and torch.distributed.is_initialized():
                rank = torch.distributed.get_rank()
                world_size = torch.distributed.get_world_size()
            else:
                rank, world_size = 0, 1
        assert world_size is not None
        if not _is_plain_int(world_size) or world_size < 1:
            raise ValueError("world_size must be a positive integer")
        if not _is_plain_int(rank) or not 0 <= rank < world_size:
            raise ValueError("rank must satisfy 0 <= rank < world_size")
        self.rank = rank
        self.world_size = world_size

    @property
    def epoch(self) -> int:
        return int(self._shared_epoch.item())

    @property
    def epoch_updates_are_shared(self) -> bool:
        return self._epoch_is_shared

    def set_epoch(self, epoch: int) -> None:
        if not _is_plain_int(epoch) or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        self._shared_epoch.fill_(epoch)

    def assigned_shards(
        self, *, worker_id: int = 0, num_workers: int = 1
    ) -> tuple[TensorShardInfo, ...]:
        """Return this rank/worker's disjoint deterministic shard assignment."""

        if not _is_plain_int(num_workers) or num_workers < 1:
            raise ValueError("num_workers must be a positive integer")
        if not _is_plain_int(worker_id) or not 0 <= worker_id < num_workers:
            raise ValueError("worker_id must satisfy 0 <= worker_id < num_workers")
        # Keep rank ownership stable across epochs.  If the global shard list
        # were shuffled before rank partitioning, rank 0 could begin epoch N+1
        # on a shard that a slower rank 1 is still consuming from epoch N.
        # Fixed rank partitions prevent that cross-epoch duplication; only the
        # order inside one rank changes between epochs.
        shards = list(self.manifest.shards[self.rank :: self.world_size])
        if self.shuffle_shards:
            random.Random(self.shuffle_seed + self.epoch).shuffle(shards)
        return tuple(shards[worker_id::num_workers])

    def _load_shard(self, shard: TensorShardInfo) -> Mapping[str, object]:
        path = self.root / shard.file
        if self.verify_hashes:
            if path.stat().st_size != shard.byte_count:
                raise ValueError(f"shard size mismatch for {shard.file}")
            if _sha256_file(path) != shard.sha256:
                raise ValueError(f"shard sha256 mismatch for {shard.file}")
        # weights_only=True is deliberate: tensor shards are data, never trusted
        # Python pickle programs.
        payload = torch.load(path, map_location="cpu", weights_only=True)
        return _validate_shard_payload(
            payload,
            entity_feature_dim=self.manifest.entity_feature_dim,
            action_feature_dim=self.manifest.action_feature_dim,
            feature_dtype=self.manifest.feature_dtype,
            trajectory_count=shard.trajectory_count,
            step_count=shard.step_count,
        )

    def __iter__(self) -> Iterator[Trajectory]:
        worker = get_worker_info()
        worker_id = 0 if worker is None else worker.id
        num_workers = 1 if worker is None else worker.num_workers
        for shard in self.assigned_shards(worker_id=worker_id, num_workers=num_workers):
            yield from _unpack_trajectories(self._load_shard(shard))

    def __len__(self) -> int:
        # DataLoader workers split this rank's shards again at iteration time.
        return sum(shard.trajectory_count for shard in self.assigned_shards())


def make_trajectory_collate_fn(
    entity_feature_dim: int, action_feature_dim: int
) -> Callable[[Sequence[Trajectory]], tuple[SpireFormerBatch, SpireFormerTargets]]:
    """Return a picklable collator suitable for single- or multi-worker loading."""

    if entity_feature_dim < 1 or action_feature_dim < 1:
        raise ValueError("feature dimensions must be positive")
    return partial(
        collate_trajectories,
        entity_feature_dim=entity_feature_dim,
        action_feature_dim=action_feature_dim,
    )


def create_trajectory_dataloader(
    dataset: TensorShardDataset,
    *,
    batch_size: int,
    num_workers: int = 0,
    pin_memory: bool = False,
    drop_last: bool = False,
    persistent_workers: bool = False,
) -> DataLoader[Any]:
    """Construct a DataLoader using the dataset manifest's feature widths."""

    if not isinstance(dataset, TensorShardDataset):
        raise TypeError("dataset must be a TensorShardDataset")
    if not _is_plain_int(batch_size) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if not _is_plain_int(num_workers) or num_workers < 0:
        raise ValueError("num_workers must be a non-negative integer")
    if persistent_workers and num_workers == 0:
        raise ValueError("persistent_workers requires num_workers > 0")
    if persistent_workers and not dataset.epoch_updates_are_shared:
        raise RuntimeError(
            "persistent workers require shared-memory epoch state, but this "
            "environment does not permit torch shared memory"
        )
    return DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=num_workers,
        collate_fn=make_trajectory_collate_fn(
            dataset.manifest.entity_feature_dim,
            dataset.manifest.action_feature_dim,
        ),
        pin_memory=pin_memory,
        drop_last=drop_last,
        persistent_workers=persistent_workers,
    )


__all__ = [
    "TENSOR_DATASET_MANIFEST",
    "TENSOR_DATASET_SCHEMA_VERSION",
    "TENSOR_SHARD_FORMAT",
    "TENSOR_SHARD_SCHEMA_VERSION",
    "TensorDatasetManifest",
    "TensorShardDataset",
    "TensorShardInfo",
    "TensorShardWriter",
    "create_trajectory_dataloader",
    "make_trajectory_collate_fn",
    "write_tensor_dataset",
]
