"""Named, training-oriented size presets for :mod:`spireformer`.

The feature widths are deliberately arguments to the preset factory: they are
part of the data contract, not the model scale.  The defaults match the first
SpireFormer tensor layout (48 entity features and 32 action features), which
is also the reference used for the advertised parameter counts.

Large presets must never be instantiated merely to discover their size.
``count_parameters`` constructs the model on PyTorch's ``meta`` device, so it
counts the exact current architecture without allocating parameter storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

import torch

from .model import SpireFormer, SpireFormerConfig


DEFAULT_ENTITY_FEATURE_DIM: Final[int] = 48
DEFAULT_ACTION_FEATURE_DIM: Final[int] = 32
DEFAULT_MAX_TIMESTEP: Final[int] = 4096


@dataclass(frozen=True, slots=True)
class SpireFormerPreset:
    """Architecture-only settings for one named SpireFormer scale.

    ``parameter_range`` describes the intended scale when the reference
    feature dimensions and timestep limit are used.  It is a guardrail rather
    than an exact count because input widths and ``max_timestep`` legitimately
    change the embedding/projection parameter total.
    """

    name: str
    description: str
    parameter_range: tuple[int, int]
    model_dim: int
    set_num_heads: int
    set_num_layers: int
    set_num_inducing_points: int | None
    temporal_num_heads: int
    temporal_num_layers: int
    temporal_ff_multiplier: int
    action_num_heads: int

    def create_config(
        self,
        entity_feature_dim: int = DEFAULT_ENTITY_FEATURE_DIM,
        action_feature_dim: int = DEFAULT_ACTION_FEATURE_DIM,
        *,
        dropout: float = 0.1,
        max_timestep: int = DEFAULT_MAX_TIMESTEP,
    ) -> SpireFormerConfig:
        """Create and validate a complete config for this scale."""

        config = SpireFormerConfig(
            entity_feature_dim=entity_feature_dim,
            action_feature_dim=action_feature_dim,
            model_dim=self.model_dim,
            set_num_heads=self.set_num_heads,
            set_num_layers=self.set_num_layers,
            set_num_inducing_points=self.set_num_inducing_points,
            temporal_num_heads=self.temporal_num_heads,
            temporal_num_layers=self.temporal_num_layers,
            temporal_ff_multiplier=self.temporal_ff_multiplier,
            action_num_heads=self.action_num_heads,
            dropout=dropout,
            max_timestep=max_timestep,
        )
        config.validate()
        return config

    def reference_parameter_count(self) -> int:
        """Return the exact count for the documented reference input widths."""

        return count_parameters(self.create_config())


_PRESETS = {
    "tiny": SpireFormerPreset(
        name="tiny",
        description=(
            "Tiny (~2.9M): fast architecture and data-pipeline validation; "
            "matches the original SpireFormer v0.1 capacity."
        ),
        parameter_range=(2_500_000, 3_500_000),
        model_dim=128,
        set_num_heads=4,
        set_num_layers=2,
        set_num_inducing_points=16,
        temporal_num_heads=4,
        temporal_num_layers=4,
        temporal_ff_multiplier=4,
        action_num_heads=4,
    ),
    "small": SpireFormerPreset(
        name="small",
        description=(
            "Small (~100M): the first production training scale, sized for "
            "single-accelerator iteration."
        ),
        parameter_range=(90_000_000, 110_000_000),
        model_dim=768,
        set_num_heads=12,
        set_num_layers=2,
        set_num_inducing_points=32,
        temporal_num_heads=12,
        temporal_num_layers=6,
        temporal_ff_multiplier=4,
        action_num_heads=12,
    ),
    "medium": SpireFormerPreset(
        name="medium",
        description=(
            "Medium (~0.7B): substantially deeper trajectory reasoning for "
            "large offline-training runs."
        ),
        parameter_range=(650_000_000, 750_000_000),
        model_dim=1536,
        set_num_heads=24,
        set_num_layers=2,
        set_num_inducing_points=32,
        temporal_num_heads=24,
        temporal_num_layers=17,
        temporal_ff_multiplier=4,
        action_num_heads=24,
    ),
    "large": SpireFormerPreset(
        name="large",
        description=(
            "Large (~2B): maximum-capacity distributed-training preset for "
            "high-volume, high-quality trajectory corpora."
        ),
        parameter_range=(1_900_000_000, 2_100_000_000),
        model_dim=2304,
        set_num_heads=36,
        set_num_layers=2,
        set_num_inducing_points=32,
        temporal_num_heads=36,
        temporal_num_layers=24,
        temporal_ff_multiplier=4,
        action_num_heads=36,
    ),
}

SPIREFORMER_PRESETS: Final[Mapping[str, SpireFormerPreset]] = MappingProxyType(_PRESETS)
"""Read-only mapping of canonical lowercase preset names to definitions."""


def available_presets() -> tuple[str, ...]:
    """Return canonical preset names from smallest to largest."""

    return tuple(SPIREFORMER_PRESETS)


def get_preset(name: str) -> SpireFormerPreset:
    """Look up a preset by a case-insensitive, whitespace-tolerant name."""

    if not isinstance(name, str):
        raise TypeError("preset name must be a string")
    normalized = name.strip().lower()
    try:
        return SPIREFORMER_PRESETS[normalized]
    except KeyError as error:
        choices = ", ".join(available_presets())
        raise ValueError(
            f"unknown SpireFormer preset {name!r}; choose one of: {choices}"
        ) from error


def get_spireformer_config(
    name: str,
    entity_feature_dim: int = DEFAULT_ENTITY_FEATURE_DIM,
    action_feature_dim: int = DEFAULT_ACTION_FEATURE_DIM,
    *,
    dropout: float = 0.1,
    max_timestep: int = DEFAULT_MAX_TIMESTEP,
) -> SpireFormerConfig:
    """Create a validated :class:`SpireFormerConfig` for ``name``."""

    return get_preset(name).create_config(
        entity_feature_dim,
        action_feature_dim,
        dropout=dropout,
        max_timestep=max_timestep,
    )


def count_parameters(config: SpireFormerConfig, *, trainable_only: bool = False) -> int:
    """Count model parameters exactly without allocating their storage.

    The model is built under a ``meta`` device context.  This remains exact if
    the implementation gains or loses parameters, unlike a duplicated manual
    formula, while even the Large preset consumes only Python module metadata.
    """

    if not isinstance(config, SpireFormerConfig):
        raise TypeError("config must be a SpireFormerConfig")
    config.validate()
    with torch.device("meta"):
        model = SpireFormer(config)
    parameters = model.parameters()
    if trainable_only:
        parameters = (parameter for parameter in parameters if parameter.requires_grad)
    return sum(parameter.numel() for parameter in parameters)


__all__ = [
    "DEFAULT_ACTION_FEATURE_DIM",
    "DEFAULT_ENTITY_FEATURE_DIM",
    "DEFAULT_MAX_TIMESTEP",
    "SPIREFORMER_PRESETS",
    "SpireFormerPreset",
    "available_presets",
    "count_parameters",
    "get_preset",
    "get_spireformer_config",
]
