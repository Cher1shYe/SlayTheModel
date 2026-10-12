"""Defect common card upgrade parity tests backed by decompiled card models."""

import sts2_env.powers  # noqa: F401

from sts2_env.cards.defect import (
    create_defect_starter_deck,
    make_charge_battery,
    make_claw,
)
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import PowerId
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle


CHARGE_BATTERY_UPGRADED_BLOCK = 10
CHARGE_BATTERY_ENERGY_NEXT_TURN = 1
CLAW_BASE_DAMAGE = 3
CLAW_UPGRADED_DAMAGE = 4
CLAW_UPGRADED_INCREASE = 3
TEST_PLAYER_HP = 75
TEST_RNG_SEED = 42
DEFECT_CHARACTER_ID = "Defect"
PLAY_CARD_ENERGY = 1
HAND_CARD_INDEX = 0
FIRST_ENEMY_INDEX = 0


def _make_combat() -> CombatState:
    combat = CombatState(
        player_hp=TEST_PLAYER_HP,
        player_max_hp=TEST_PLAYER_HP,
        deck=create_defect_starter_deck(),
        rng_seed=TEST_RNG_SEED,
        character_id=DEFECT_CHARACTER_ID,
    )
    creature, ai = create_shrinker_beetle(Rng(TEST_RNG_SEED))
    combat.add_enemy(creature, ai)
    combat.start_combat()
    return combat


def test_charge_battery_upgrade_only_increases_block_and_keeps_energy_next_turn():
    combat = _make_combat()
    combat.hand = [make_charge_battery(upgraded=True)]
    combat.energy = PLAY_CARD_ENERGY

    assert combat.play_card(HAND_CARD_INDEX)

    assert combat.player.block == CHARGE_BATTERY_UPGRADED_BLOCK
    assert combat.player.get_power_amount(PowerId.ENERGY_NEXT_TURN) == CHARGE_BATTERY_ENERGY_NEXT_TURN


def test_claw_upgrade_uses_upgraded_damage_and_shared_growth_amount():
    combat = _make_combat()
    played = make_claw(upgraded=True)
    in_draw = make_claw()
    in_discard = make_claw()
    enemy = combat.enemies[FIRST_ENEMY_INDEX]
    starting_hp = enemy.current_hp
    combat.hand = [played]
    combat.draw_pile = [in_draw]
    combat.discard_pile = [in_discard]

    assert combat.play_card(HAND_CARD_INDEX, FIRST_ENEMY_INDEX)

    assert enemy.current_hp == starting_hp - CLAW_UPGRADED_DAMAGE
    assert played.base_damage == CLAW_UPGRADED_DAMAGE + CLAW_UPGRADED_INCREASE
    assert in_draw.base_damage == CLAW_BASE_DAMAGE + CLAW_UPGRADED_INCREASE
    assert in_discard.base_damage == CLAW_BASE_DAMAGE + CLAW_UPGRADED_INCREASE
