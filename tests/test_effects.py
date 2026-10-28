"""Effect tests for damage/block, status timing, piles, shuffle, death, summon,
upgrades and relic combinations.

Evidence: C# reference semantics (`MegaCrit.Sts2.Core.Commands`/`Models`); no
client trace is available, so these are semantic pins, not differential proof.
"""
from __future__ import annotations

import pytest

from agent.common import sim

UNDECIDED = sim.Outcome.UNDECIDED
END_TURN = int(sim.ActionType.END_TURN)


def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def battle(cards, encounter="SETUP_CEREMONIAL_BEAST_BOSS", relics=(), seed=99,
           hp=500, upgraded=None):
    bc = sim.BattleContext()
    up = upgraded or [False] * len(cards)
    bc.init(getattr(sim.Encounter, encounter), seed, cards, up, 0, hp, hp,
            list(relics), [])
    return bc


def play_by_id(bc, name: str, target=0):
    ids = [i for i, c in enumerate(bc.hand) if c[0] == card_id(name)]
    if not ids:
        return False
    actions = [a for a in bc.legal_actions()
               if a[0] == int(sim.ActionType.PLAY_CARD) and a[1] == ids[0]]
    if not actions:
        return False
    if target is not None:
        with_target = [a for a in actions if a[2] == target]
        actions = with_target or actions
    assert bc.step(*actions[0])
    return True


def total_cards(bc) -> int:
    return bc.hand_count if hasattr(bc, "hand_count") else len(bc.hand) + bc.draw_count + \
        bc.discard_count + bc.exhaust_count


def test_strength_and_vulnerable_modify_damage():
    strike = card_id("Strike")
    bc = battle([strike] * 10)
    hp0 = bc.monsters[0][1]
    assert play_by_id(bc, "Strike")
    assert hp0 - bc.monsters[0][1] == 6

    bash = card_id("Bash")
    bc = battle([bash, strike] * 5)
    assert play_by_id(bc, "Bash")
    assert bc.monsters[0][8] == 2  # vulnerable
    hp0 = bc.monsters[0][1]
    assert play_by_id(bc, "Strike")
    assert hp0 - bc.monsters[0][1] == 9  # floor(6 * 1.5)


def test_block_and_dexterity():
    defend = card_id("Defend")
    bc = battle([defend] * 10)
    assert play_by_id(bc, "Defend")
    assert bc.player_block == 5

    buffed = battle([defend] * 10, relics=[int(sim.RelicId.ODDLY_SMOOTH_STONE)])
    assert play_by_id(buffed, "Defend")
    assert buffed.player_block == 6  # dexterity +1


def test_vulnerable_ticks_down_after_monster_turn():
    bash = card_id("Bash")
    bc = battle([bash] * 10)
    assert play_by_id(bc, "Bash")
    assert bc.monsters[0][8] == 2
    bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][8] == 1
    bc.step(END_TURN, 0, 0, 0)
    assert bc.monsters[0][8] == 0


def test_draw_discard_and_exhaust_piles():
    pommel = card_id("Pommel Strike")
    bc = battle([pommel] * 10)
    draw0 = bc.draw_count
    hand0 = len(bc.hand)
    assert play_by_id(bc, "Pommel Strike")
    assert bc.draw_count == draw0 - 1  # draws one
    assert len(bc.hand) == hand0  # played one, drew one
    assert bc.discard_count >= 1

    grit = card_id("True Grit")
    bc = battle([grit] * 10)
    assert play_by_id(bc, "True Grit")
    assert bc.exhaust_count == 1  # unupgraded exhausts a random card


def test_shuffle_preserves_card_count():
    deck = [card_id("Strike"), card_id("Defend")] * 5
    bc = battle(deck, encounter="SETUP_SHRINKER_BEETLE_WEAK", hp=500)
    for _ in range(4):
        bc.step(END_TURN, 0, 0, 0)
        assert total_cards(bc) == len(deck)


def test_monster_death_and_victory():
    bludgeon = card_id("Bludgeon")
    bc = battle([bludgeon] * 10, encounter="SETUP_SHRINKER_BEETLE_WEAK", hp=500)
    guard = 0
    while bc.outcome == UNDECIDED and guard < 20:
        guard += 1
        if not play_by_id(bc, "Bludgeon"):
            bc.step(END_TURN, 0, 0, 0)
    assert bc.outcome == sim.Outcome.PLAYER_VICTORY
    assert not bc.monsters[0][7]


def test_player_death_is_a_loss():
    defend = card_id("Defend")
    bc = battle([defend] * 10, encounter="SETUP_RUBY_RAIDERS_NORMAL", hp=1, seed=3)
    guard = 0
    while bc.outcome == UNDECIDED and guard < 6:
        guard += 1
        bc.step(END_TURN, 0, 0, 0)
    assert bc.outcome == sim.Outcome.PLAYER_LOSS


def test_monster_summon_increases_roster():
    defend = card_id("Defend")
    bc = battle([defend] * 20, encounter="SETUP_OVICOPTER_NORMAL", hp=500, seed=1)
    start = len(bc.monsters)
    guard = 0
    while len(bc.monsters) == start and guard < 8:
        guard += 1
        bc.step(END_TURN, 0, 0, 0)
    assert len(bc.monsters) > start


def test_upgraded_card_damage():
    bash = card_id("Bash")
    bc = battle([bash] * 10, upgraded=[True] * 10)
    hp0 = bc.monsters[0][1]
    assert play_by_id(bc, "Bash")
    assert hp0 - bc.monsters[0][1] == 10  # 8 -> 10


def test_relic_damage_combination():
    strike = card_id("Strike")
    plain = battle([strike] * 10)
    hp0 = plain.monsters[0][1]
    assert play_by_id(plain, "Strike")
    assert hp0 - plain.monsters[0][1] == 6

    dummy = battle([strike] * 10, relics=[int(sim.RelicId.STRIKE_DUMMY)])
    hp0 = dummy.monsters[0][1]
    assert play_by_id(dummy, "Strike")
    assert hp0 - dummy.monsters[0][1] == 9

    both = battle([strike] * 10, relics=[int(sim.RelicId.STRIKE_DUMMY),
                                         int(sim.RelicId.VAJRA)])
    hp0 = both.monsters[0][1]
    assert play_by_id(both, "Strike")
    assert hp0 - both.monsters[0][1] == 10  # (6 + 1 strength) + 3
