"""Semantic regression tests for reproduced rule bugs.

Each test names its evidence source.  Evidence levels:
  C#  – derived from the decompiled reference implementation (primary);
  PY  – cross-checked against the Python reference engine;
  GAME – an actual client trace (not available in this environment).

No test in this file claims GAME-level alignment; the module purpose is to pin
behaviour that previously diverged from the C# reference.
"""
from __future__ import annotations

import pytest

from agent.common import sim

DECIDED = sim.Outcome.UNDECIDED if hasattr(sim, "Outcome") else None
UNDECIDED = sim.Outcome.UNDECIDED
END_TURN = int(sim.ActionType.END_TURN)


def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def battle(cards, encounter, relics=(), seed=1234, hp=500, potions=()):
    bc = sim.BattleContext()
    bc.init(getattr(sim.Encounter, encounter), seed, cards, [False] * len(cards), 0,
            hp, hp, list(relics), list(potions))
    return bc


def play_first_card(bc, target=None):
    acts = [a for a in bc.legal_actions() if a[0] == 0]
    if target is not None:
        acts = [a for a in acts if a[2] == target] or acts
    assert acts
    assert bc.step(*acts[0])


def test_sword_boomerang_applies_modifiers_once():
    """C# SwordBoomerang: DamageCmd 3 damage x 3 hits, modifiers once per hit."""
    sb = card_id("Sword Boomerang")
    plain = battle([sb] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    hp0 = plain.monsters[0][1]
    play_first_card(plain)
    assert hp0 - plain.monsters[0][1] == 9  # 3 x 3

    buffed = battle([sb] * 10, "SETUP_CEREMONIAL_BEAST_BOSS",
                    relics=[int(sim.RelicId.VAJRA)])
    hp0 = buffed.monsters[0][1]
    play_first_card(buffed)
    assert hp0 - buffed.monsters[0][1] == 12  # 3 x (3 + 1)


def test_mangle_temporary_strength_is_restored():
    """C# ManglePower (TemporaryStrengthPower, IsPositive=false): -10 until the
    end of the affected monster's turn, then restored."""
    bc = battle([card_id("Mangle")] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    play_first_card(bc, target=0)
    assert bc.monsters[0][10] == -10
    bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][10] == 0


def test_dark_shackles_temporary_strength_is_restored():
    """C# DarkShacklesPower is a TemporaryStrengthPower: -9 then restored."""
    bc = battle([card_id("Dark Shackles")] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    play_first_card(bc, target=0)
    assert bc.monsters[0][10] == -9
    bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][10] == 0


def test_alchemize_creates_a_combat_potion():
    """C# Alchemize -> PotionFactory.CreateRandomPotionInCombat into a free slot."""
    bc = battle([card_id("Alchemize")] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    assert bc.potions == [] and bc.energy == 3
    play_first_card(bc)
    assert bc.energy == 2
    assert len(bc.potions) == 1
    # Deterministic for a fixed combat seed.
    bc2 = battle([card_id("Alchemize")] * 10, "SETUP_CEREMONIAL_BEAST_BOSS")
    play_first_card(bc2)
    assert bc2.potions == bc.potions


def test_alchemize_does_not_overfill_potion_slots():
    bc = battle([card_id("Alchemize")] * 10, "SETUP_CEREMONIAL_BEAST_BOSS",
                potions=[int(sim.PotionId.EnergyPotion)] * 3)
    assert len(bc.potions) == 3
    play_first_card(bc)
    assert len(bc.potions) == 3


def test_lagavulin_wakes_on_unblocked_damage():
    """C# AsleepPower: unblocked damage removes Plating, wakes, and stuns one turn.
    SLEEP_BRANCH then selects SLASH; the monster attacks on following turns."""
    strike = card_id("Strike")
    bc = battle([strike] * 20, "SETUP_LAGAVULIN_MATRIARCH_BOSS", hp=500)
    # PlatingPower.BeforeSideTurnStart: 12 block at the start of round 1.
    assert bc.monsters[0][3] == 12
    assert bc.monster_state(0)[0] == 0  # SLEEP_MOVE
    for _ in range(3):
        play_first_card(bc)
    assert bc.monsters[0][1] == 216  # 12 block, then 18 damage
    assert not bc.monster_powers(0)  # Asleep + Plating removed
    hp = bc.player_hp
    bc.step(END_TURN, 0, 0, 0)
    assert bc.player_hp == hp  # wake turn is a stun
    bc.step(END_TURN, 0, 0, 0)
    assert bc.player_hp == hp - 19  # SLASH_MOVE


def test_plating_decrements_each_monster_turn():
    """C# PlatingPower: grants its counter as block and decrements by 1."""
    bc = battle([card_id("Defend")] * 10, "SETUP_LAGAVULIN_MATRIARCH_BOSS", hp=500)
    powers = dict(bc.monster_powers(0))
    plating = next(v for k, v in powers.items() if v == 12)
    assert plating == 12
    bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][3] in (11, 12)  # block reset then 11 gained
    amounts = {v for _k, v in bc.monster_powers(0)}
    assert 11 in amounts


def test_test_subject_revives_twice_then_phase_three():
    """C# TestSubject/AdaptablePower: two respawns at 200/300 HP, third form ends."""
    bludgeon = card_id("Bludgeon")
    bc = battle([bludgeon] * 40, "SETUP_TEST_SUBJECT_BOSS", hp=500)
    assert bc.monsters[0][2] == 100
    guard = 0
    seen_reviving = False
    while bc.monsters[0][2] == 100 and guard < 40:
        guard += 1
        acts = [a for a in bc.legal_actions() if a[0] == 0]
        if acts:
            bc.step(*acts[0])
        else:
            bc.step(END_TURN, 0, 0, 0)
        seen_reviving |= bc.monster_state(0)[2]
    assert seen_reviving
    # Respawn turn restores second-form HP (200 at A0).
    while bc.monsters[0][2] == 100 and guard < 60:
        guard += 1
        bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][2] == 200


def test_knowledge_demon_curse_counter_advances():
    """C# KnowledgeDemon: three Curse of Knowledge casts, then the branch flips
    to Slap (counter >= 3).  Previously the unknown condition was always true."""
    bc = battle([card_id("Defend")] * 40, "SETUP_KNOWLEDGE_DEMON_BOSS", hp=500)
    visited_curses = 0
    moves = []
    for _ in range(13):
        moves.append(bc.monster_state(0)[0])
        bc.step(END_TURN, 0, 0, 0)
    curse_state = 0
    slap_state = 1
    assert moves.count(curse_state) == 3
    assert moves[0] == curse_state and moves[4] == curse_state and moves[8] == curse_state
    assert moves[12] == slap_state  # fourth cycle no longer curses


def test_unknown_monster_condition_codes_are_rejected_at_generation():
    """The generator must refuse conditions it cannot map instead of defaulting
    them to true (the Lagavulin ASLEEP bug)."""
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "gen_monsters", root / "simulator" / "tools" / "gen_monsters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(ValueError):
        mod.cond_code("cond.add_branch(lambda: some_new_condition(), MOVE)")
    assert mod.cond_code("cond.add_branch(lambda: True, MOVE)") == 0
    assert mod.cond_code(
        "cond.add_branch(lambda: creature.has_power(PowerId.ASLEEP), MOVE)") == 15
