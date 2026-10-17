"""Generic public roster reconstruction across native act encounters."""
import numpy as np
import pytest

from sts2_env.az.information import PublicHistory
from sts2_env.az.monster_registry import ENCOUNTERS, audit
from sts2_env.az.roster import (EnemySlot, after_round, capture_slots, create_slots,
                                restore_slots, validate_slots)
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.search.clone import clone_state

SAMPLES = [
    'setup_nibbits_weak', 'setup_nibbits_normal', 'setup_slimes_weak',
    'setup_bowlbugs_normal', 'setup_inklets_normal', 'setup_cultists_normal',
    'setup_exoskeletons_normal', 'setup_toadpoles_normal', 'setup_axebots_normal',
    'setup_chompers_normal', 'setup_corpse_slugs_normal', 'setup_queen_boss',
    'setup_kaiser_crab_boss', 'setup_doormaker_boss', 'setup_waterfall_giant_boss',
]


def build(encounter, seed=5, deck_size=10):
    deck = create_ironclad_starter_deck()[:deck_size]
    world = CombatState(80, 80, deck, seed, relics=[], potions=[], character_id='Ironclad')
    ENCOUNTERS[encounter](world, Rng(seed))
    world.start_combat()
    world.rng = Rng(seed + 1)
    return world


def history_for(world, roster_moves=None):
    return PublicHistory(roster_moves=roster_moves or tuple(() for _ in world.enemies))


def capture(world, history):
    return capture_slots(world, history, tuple(e.max_hp for e in world.enemies))


def round_trip(encounter, seed=5, turns=3):
    world = build(encounter, seed)
    history = history_for(world)
    slots = capture(world, history)
    validate_slots(slots)
    assert all(slot.hp > 0 for slot in slots)
    scratch = CombatState(80, 80, create_ironclad_starter_deck(), seed,
                          relics=[], potions=[], character_id='Ironclad')
    create_slots(scratch, slots, Rng(seed + 7), encounter=encounter)
    scratch.start_combat()
    restore_slots(scratch, slots, Rng(seed + 8))
    assert capture(scratch, history) == slots
    for _ in range(turns):
        if world.is_over:
            break
        before = slots
        # Align the hidden chance stream only for the native parity oracle; a
        # real particle samples its own future, so future branch choices differ.
        scratch.rng = clone_state(world.rng)
        world.end_player_turn()
        scratch.end_player_turn()
        world_history = PublicHistory(roster_moves=after_round(before, world.is_over))
        scratch_history = PublicHistory(roster_moves=after_round(before, scratch.is_over))
        slots = capture(world, world_history)
        validate_slots(slots)
        assert capture(scratch, scratch_history) == slots
    return slots


@pytest.mark.parametrize('encounter', SAMPLES)
def test_roster_round_trip_and_public_parity(encounter):
    slots = round_trip(encounter)
    assert 1 <= len(slots) <= 5


def test_every_encounter_capture_is_publicly_derivable(report=None):
    report = report or audit()
    checked = 0
    for name, entry in sorted(report['encounters'].items()):
        if not entry['admitted']:
            continue
        world = build(name)
        slots = capture(world, history_for(world))
        validate_slots(slots)
        checked += 1
    assert checked >= 75


def test_unknown_move_history_is_refused():
    world = build('setup_nibbits_normal')
    slots = capture(world, history_for(world))
    bad = tuple(EnemySlot(s.slot, s.monster_id, s.initial_hp, s.hp, s.max_hp, s.block, s.powers,
                          s.intents, s.move, ('NOT_A_MOVE',), s.escaped) for s in slots)
    with pytest.raises(ValueError):
        validate_slots(bad)


def test_intent_must_match_the_public_move():
    world = build('setup_nibbits_normal')
    slots = capture(world, history_for(world))
    slot = slots[0]
    bad = (EnemySlot(slot.slot, slot.monster_id, slot.initial_hp, slot.hp, slot.max_hp, slot.block,
                     slot.powers, (('ATTACK', 999, 1),), slot.move, slot.moves, slot.escaped),) + slots[1:]
    with pytest.raises(ValueError):
        validate_slots(bad)


def test_test_subject_requires_the_boss_contract():
    world = CombatState(80, 80, create_ironclad_starter_deck(), 5, relics=[], potions=[],
                        character_id='Ironclad')
    from sts2_env.encounters.act3 import setup_test_subject_boss
    setup_test_subject_boss(world, Rng(5))
    world.start_combat()
    with pytest.raises(ValueError):
        slots = capture(world, history_for(world))
        validate_slots(slots)
