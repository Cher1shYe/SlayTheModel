"""Status / curse / token / event-card upgrade parity tests backed by reference models."""

import pytest

import sts2_env.powers  # noqa: F401

from sts2_env.cards.factory import create_card, create_reference_card
from sts2_env.core.enums import CardId


STATUS_FACTORY_UPGRADE_CARD_IDS = (
    CardId.APOTHEOSIS,
    CardId.APPARITION,
    CardId.ASCENDERS_BANE,
    CardId.BAD_LUCK,
    CardId.BECKON,
    CardId.BRIGHTEST_FLAME,
    CardId.BYRDONIS_EGG,
    CardId.BYRD_SWOOP,
    CardId.CALTROPS,
    CardId.CLUMSY,
    CardId.CURSE_OF_THE_BELL,
    CardId.DAZED,
    CardId.DEBRIS,
    CardId.DECAY,
    CardId.DISINTEGRATION,
    CardId.DISTRACTION,
    CardId.DOUBT,
    CardId.DUAL_WIELD,
    CardId.ENLIGHTENMENT,
    CardId.ENTRENCH,
    CardId.EXTERMINATE,
    CardId.FEEDING_FRENZY_CARD,
    CardId.FOLLY,
    CardId.FUEL,
    CardId.GIANT_ROCK,
    CardId.GREED,
    CardId.GUILTY,
    CardId.HELLO_WORLD_CARD,
    CardId.INFECTION,
    CardId.INJURY,
    CardId.LANTERN_KEY,
    CardId.LUMINESCE,
    CardId.MAD_SCIENCE,
    CardId.MAUL,
    CardId.METAMORPHOSIS,
    CardId.MIND_ROT,
    CardId.MINION_DIVE_BOMB,
    CardId.MINION_SACRIFICE,
    CardId.MINION_STRIKE,
    CardId.NEOWS_FURY,
    CardId.OUTMANEUVER,
    CardId.PECK,
    CardId.POOR_SLEEP,
    CardId.REBOUND,
    CardId.RELAX,
    CardId.RIP_AND_TEAR,
    CardId.SHAME,
    CardId.SHIV,
    CardId.SLIMED,
    CardId.SLOTH_STATUS,
    CardId.SOOT,
    CardId.SOUL,
    CardId.SOVEREIGN_BLADE,
    CardId.SPOILS_MAP,
    CardId.SPORE_MIND,
    CardId.SQUASH,
    CardId.STACK,
    CardId.SWEEPING_GAZE,
    CardId.TORIC_TOUGHNESS,
    CardId.TOXIC,
    CardId.WASTE_AWAY,
    CardId.WHISTLE,
    CardId.WOUND,
    CardId.WRITHE,
)


def _status_card_id(card_id: CardId) -> str:
    return card_id.name


@pytest.mark.parametrize("card_id", STATUS_FACTORY_UPGRADE_CARD_IDS, ids=_status_card_id)
def test_status_factory_upgrade_core_metadata_matches_reference(card_id: CardId):
    actual = create_card(card_id, upgraded=True)
    expected = create_reference_card(card_id, upgraded=True, allow_generation=True)

    assert actual.upgraded is expected.upgraded
    assert actual.cost == expected.cost
    assert actual.has_energy_cost_x == expected.has_energy_cost_x
    assert actual.card_type == expected.card_type
    assert actual.target_type == expected.target_type
    assert actual.rarity == expected.rarity
    assert actual.star_cost == expected.star_cost
    assert actual.keywords == expected.keywords
    assert actual.tags == expected.tags


@pytest.mark.parametrize("card_id", STATUS_FACTORY_UPGRADE_CARD_IDS, ids=_status_card_id)
def test_status_factory_upgrade_dynamic_values_match_reference(card_id: CardId):
    actual = create_card(card_id, upgraded=True)
    expected = create_reference_card(card_id, upgraded=True, allow_generation=True)

    for key, expected_value in expected.effect_vars.items():
        actual_value = actual.effect_vars.get(key)
        if key in {"damage", "calc_base"} and actual_value is None:
            assert actual.base_damage == expected_value
            continue
        if key == "block" and actual_value is None:
            assert actual.base_block == expected_value
            continue
        assert actual_value == expected_value
