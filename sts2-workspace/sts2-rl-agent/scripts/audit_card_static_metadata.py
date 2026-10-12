#!/usr/bin/env python3
"""Audit card static metadata against decompiled card models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.cards.factory import card_metadata, create_card
from sts2_env.cards.reference_static_metadata import (
    ReferenceCardStaticMetadata,
    reference_metadata_by_card_id,
    upgraded_reference_metadata_by_card_id,
)
from sts2_env.core.enums import CardId


RUNTIME_ONLY_CARD_IDS = frozenset({CardId.GENERIC})


def collect_static_metadata_mismatches() -> list[str]:
    mismatches: list[str] = []
    references_by_upgrade_state = {
        False: reference_metadata_by_card_id(),
        True: upgraded_reference_metadata_by_card_id(),
    }
    for upgraded, references in references_by_upgrade_state.items():
        mismatches.extend(_collect_mismatches_for_upgrade_state(upgraded, references))
    return mismatches


def _collect_mismatches_for_upgrade_state(
    upgraded: bool,
    references: dict[CardId, ReferenceCardStaticMetadata],
) -> list[str]:
    mismatches: list[str] = []
    for reference in references.values():
        if reference.card_id in RUNTIME_ONLY_CARD_IDS:
            continue
        card = create_card(reference.card_id, upgraded=upgraded)
        expected = {
            "upgraded": upgraded and reference.max_upgrade_level > 0,
            "cost": reference.cost,
            "card_type": reference.card_type,
            "target_type": reference.target_type,
            "rarity": reference.rarity,
            "keywords": reference.keywords,
            "tags": reference.tags,
            "has_energy_cost_x": reference.has_energy_cost_x,
            "star_cost": reference.star_cost,
            "has_star_cost_x": reference.has_star_cost_x,
            "can_be_generated_in_combat": reference.can_be_generated_in_combat,
            "can_be_generated_by_modifiers": reference.can_be_generated_by_modifiers,
            "has_turn_end_in_hand_effect": reference.has_turn_end_in_hand_effect,
            "gains_block": reference.gains_block,
            "orb_evoke_type": reference.orb_evoke_type,
            "should_show_in_card_library": reference.should_show_in_card_library,
            "has_custom_playability": reference.has_custom_playability,
            "has_custom_should_play": reference.has_custom_should_play,
            "has_custom_card_type": reference.has_custom_card_type,
            "has_custom_target_type": reference.has_custom_target_type,
            "multiplayer_constraint": reference.multiplayer_constraint,
        }
        if reference.visual_card_pool is not None:
            expected["visual_card_pool"] = reference.visual_card_pool
        actual = {
            "upgraded": card.upgraded,
            "cost": card.cost,
            "card_type": card.card_type,
            "target_type": card.target_type,
            "rarity": card.rarity,
            "keywords": card.keywords,
            "tags": card.tags,
            "has_energy_cost_x": card.has_energy_cost_x,
            "star_cost": card.star_cost,
            "has_star_cost_x": card.has_star_cost_x,
            "can_be_generated_in_combat": card.can_be_generated_in_combat,
            "can_be_generated_by_modifiers": card.can_be_generated_by_modifiers,
            "has_turn_end_in_hand_effect": card.has_turn_end_in_hand_effect,
            "gains_block": card.gains_block,
            "orb_evoke_type": card.orb_evoke_type,
            "visual_card_pool": card.visual_card_pool,
            "should_show_in_card_library": card.should_show_in_card_library,
            "has_custom_playability": card.has_custom_playability,
            "has_custom_should_play": card.has_custom_should_play,
            "has_custom_card_type": card.has_custom_card_type,
            "has_custom_target_type": card.has_custom_target_type,
            "multiplayer_constraint": card_metadata(reference.card_id).multiplayer_constraint,
        }
        for field_name, expected_value in expected.items():
            actual_value = actual[field_name]
            if actual_value != expected_value:
                mismatches.append(
                    f"{reference.card_id.name}.upgraded={upgraded}.{field_name}: "
                    f"{actual_value!r} != {expected_value!r}"
                )
    return mismatches


def main() -> int:
    mismatches = collect_static_metadata_mismatches()
    for mismatch in mismatches:
        print(mismatch)
    if mismatches:
        print(f"{len(mismatches)} card static metadata mismatch(es) found")
        return 1
    print("card static metadata audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
