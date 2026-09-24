"""Scale and safety tests for the named SpireFormer presets."""

from __future__ import annotations

from dataclasses import replace

import pytest

from spireformer.model import SpireFormerConfig
from spireformer.presets import (
    SPIREFORMER_PRESETS,
    available_presets,
    count_parameters,
    get_preset,
    get_spireformer_config,
)


EXPECTED_REFERENCE_COUNTS = {
    "tiny": 2_882_818,
    "small": 100_801_538,
    "medium": 707_891_714,
    "large": 2_033_487_362,
}


@pytest.mark.parametrize("name", available_presets())
def test_presets_are_valid_and_in_their_advertised_parameter_range(
    name: str,
) -> None:
    preset = get_preset(name)
    config = preset.create_config()

    config.validate()
    assert config.model_dim % config.set_num_heads == 0
    assert config.model_dim % config.temporal_num_heads == 0
    assert config.model_dim % config.action_num_heads == 0

    exact_count = count_parameters(config)
    assert exact_count == EXPECTED_REFERENCE_COUNTS[name]
    assert preset.parameter_range[0] <= exact_count <= preset.parameter_range[1]
    assert preset.reference_parameter_count() == exact_count


def test_presets_grow_monotonically_and_keep_training_practical_head_widths() -> None:
    counts = [EXPECTED_REFERENCE_COUNTS[name] for name in available_presets()]
    assert counts == sorted(counts)

    # Each attention head remains a conventional 32 or 64 channels rather
    # than growing into an inefficient, extremely wide head at larger scales.
    for preset in SPIREFORMER_PRESETS.values():
        for heads in (
            preset.set_num_heads,
            preset.temporal_num_heads,
            preset.action_num_heads,
        ):
            assert preset.model_dim // heads in {32, 64}


def test_tiny_matches_the_original_v01_default_architecture() -> None:
    assert get_spireformer_config("tiny") == SpireFormerConfig(
        entity_feature_dim=48,
        action_feature_dim=32,
    )


def test_data_contract_settings_can_change_without_redefining_scale() -> None:
    config = get_spireformer_config(
        " SMALL ",
        entity_feature_dim=80,
        action_feature_dim=56,
        dropout=0.2,
        max_timestep=8192,
    )

    assert config.entity_feature_dim == 80
    assert config.action_feature_dim == 56
    assert config.dropout == 0.2
    assert config.max_timestep == 8192
    assert config.model_dim == SPIREFORMER_PRESETS["small"].model_dim
    config.validate()


def test_invalid_config_values_are_rejected_by_the_preset_factory() -> None:
    with pytest.raises(ValueError, match="entity_feature_dim"):
        get_spireformer_config("tiny", entity_feature_dim=0)
    with pytest.raises(ValueError, match="dropout"):
        get_spireformer_config("tiny", dropout=1.0)

    invalid = replace(get_spireformer_config("tiny"), temporal_num_heads=3)
    with pytest.raises(ValueError, match="temporal_num_heads"):
        count_parameters(invalid)


def test_unknown_preset_reports_all_available_choices() -> None:
    with pytest.raises(ValueError) as error:
        get_spireformer_config("enormous")

    message = str(error.value)
    assert "unknown SpireFormer preset 'enormous'" in message
    for name in available_presets():
        assert name in message


def test_parameter_counter_rejects_non_configs() -> None:
    with pytest.raises(TypeError, match="SpireFormerConfig"):
        count_parameters({})  # type: ignore[arg-type]
