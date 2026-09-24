"""Versioned metadata stored next to model weights and tensor shards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from .model import SpireFormerConfig


@dataclass(frozen=True, slots=True)
class SpireFormerManifest:
    """Makes data/checkpoint compatibility explicit instead of accidental."""

    schema_version: int
    model_version: str
    tensorizer_version: str
    vocabulary_hash: str
    reward_version: str
    no_save_load_information: bool
    config: SpireFormerConfig

    def validate(self) -> None:
        if type(self.schema_version) is not int:
            raise TypeError("schema_version must be an integer")
        if self.schema_version != 1:
            raise ValueError(f"unsupported manifest schema {self.schema_version}")
        for field_name in (
            "model_version",
            "tensorizer_version",
            "vocabulary_hash",
            "reward_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if type(self.no_save_load_information) is not bool:
            raise TypeError("no_save_load_information must be a boolean")
        if not self.no_save_load_information:
            raise ValueError("SpireFormer v0.1 is defined for no-SL observations")
        if not isinstance(self.config, SpireFormerConfig):
            raise TypeError("config must be a SpireFormerConfig")
        self.config.validate()

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["config"] = self.config.to_dict()
        return values

    def to_json(self) -> str:
        self.validate()
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def digest(self) -> str:
        return sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SpireFormerManifest":
        data = dict(values)
        data["config"] = SpireFormerConfig.from_dict(data["config"])
        manifest = cls(**data)
        manifest.validate()
        return manifest

    @classmethod
    def from_json(cls, payload: str) -> "SpireFormerManifest":
        values = json.loads(payload)
        if not isinstance(values, dict):
            raise ValueError("manifest JSON root must be an object")
        return cls.from_dict(values)


__all__ = ["SpireFormerManifest"]
