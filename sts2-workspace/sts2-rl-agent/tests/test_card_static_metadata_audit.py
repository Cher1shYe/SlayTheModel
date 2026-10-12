"""Card static metadata parity audit."""

from scripts.audit_card_dynamic_vars import collect_card_dynamic_var_mismatches
from scripts.audit_card_static_metadata import collect_static_metadata_mismatches
from sts2_env.cards.base import CardInstance
from sts2_env.cards.factory import create_card
from sts2_env.cards.reference_static_metadata import reference_metadata_by_card_id
from sts2_env.core.card_pools import CardPoolId
from sts2_env.core.enums import CardId, CardTag, CardType, OrbEvokeType, TargetType


def test_card_static_metadata_matches_decompiled_models() -> None:
    assert collect_static_metadata_mismatches() == []


def test_selected_card_dynamic_vars_match_decompiled_models() -> None:
    assert collect_card_dynamic_var_mismatches() == []


def test_orb_evoke_type_matches_decompiled_card_properties() -> None:
    assert create_card(CardId.DUALCAST).orb_evoke_type is OrbEvokeType.FRONT
    assert create_card(CardId.QUADCAST).orb_evoke_type is OrbEvokeType.FRONT
    assert create_card(CardId.MULTI_CAST).orb_evoke_type is OrbEvokeType.ALL
    assert create_card(CardId.SHATTER).orb_evoke_type is OrbEvokeType.ALL
    assert create_card(CardId.ZAP).orb_evoke_type is OrbEvokeType.NONE


def test_visual_card_pool_matches_decompiled_card_properties() -> None:
    assert create_card(CardId.ENTRENCH).visual_card_pool is CardPoolId.IRONCLAD
    assert create_card(CardId.CALTROPS).visual_card_pool is CardPoolId.SILENT
    assert create_card(CardId.STACK).visual_card_pool is CardPoolId.DEFECT
    assert create_card(CardId.VOLLEY).visual_card_pool is CardPoolId.COLORLESS
    assert create_card(CardId.ENTRENCH).visual_card_pool_is_colorless is False
    assert create_card(CardId.VOLLEY).visual_card_pool_is_colorless is True


def test_card_library_visibility_matches_decompiled_constructor_flags() -> None:
    assert create_card(CardId.DEPRECATED_CARD).should_show_in_card_library is False
    assert create_card(CardId.MAD_SCIENCE).should_show_in_card_library is False
    assert create_card(CardId.STRIKE_IRONCLAD).should_show_in_card_library is True


def test_custom_playability_matches_decompiled_card_properties() -> None:
    references = reference_metadata_by_card_id()
    expected_card_ids = {card_id for card_id, reference in references.items() if reference.has_custom_playability}
    actual_card_ids = {card_id for card_id in references if create_card(card_id).has_custom_playability}
    assert actual_card_ids == expected_card_ids


def test_custom_should_play_matches_decompiled_card_properties() -> None:
    references = reference_metadata_by_card_id()
    expected_card_ids = {card_id for card_id, reference in references.items() if reference.has_custom_should_play}
    actual_card_ids = {card_id for card_id in references if create_card(card_id).has_custom_should_play}
    assert actual_card_ids == expected_card_ids


def test_custom_card_type_matches_decompiled_card_properties() -> None:
    references = reference_metadata_by_card_id()
    expected_card_ids = {card_id for card_id, reference in references.items() if reference.has_custom_card_type}
    actual_card_ids = {card_id for card_id in references if create_card(card_id).has_custom_card_type}
    assert actual_card_ids == expected_card_ids


def test_custom_target_type_matches_decompiled_card_properties() -> None:
    references = reference_metadata_by_card_id()
    expected_card_ids = {card_id for card_id, reference in references.items() if reference.has_custom_target_type}
    actual_card_ids = {card_id for card_id in references if create_card(card_id).has_custom_target_type}
    assert actual_card_ids == expected_card_ids


def test_card_instances_inherit_decompiled_canonical_tags() -> None:
    fetch = CardInstance(CardId.FETCH, 1, CardType.ATTACK, TargetType.ANY_ENEMY)
    sic_em = CardInstance(CardId.SIC_EM, 1, CardType.SKILL, TargetType.ANY_ENEMY)
    assert CardTag.OSTY_ATTACK in fetch.tags
    assert CardTag.OSTY_ATTACK in sic_em.tags
