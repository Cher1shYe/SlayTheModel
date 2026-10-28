"""Ancients, curses and event-card semantics.

Evidence: decompiled C# v0.111.0 (`MegaCrit.Sts2.Core.Models.Events.*`,
`Models.Cards.*`, `Models.Relics.*`). No client trace is available, so these
are semantic pins against the reference code, not differential proof.
"""
from __future__ import annotations

import numpy as np
import pytest

from agent.common import SCREEN, new_run, sim

UNDECIDED = sim.Outcome.UNDECIDED
END_TURN = int(sim.ActionType.END_TURN)
PLAY_CARD = int(sim.ActionType.PLAY_CARD)
EVENT_CHOICE = int(sim.RunActionType.EVENT_CHOICE)


def card_id(name: str) -> int:
    for i in range(1, sim.card_count()):
        if sim.card_name(i) == name:
            return i
    raise KeyError(name)


def relic_id(name: str) -> int:
    for member in sim.RelicId.__members__:
        rid = int(getattr(sim.RelicId, member))
        if sim.relic_info(rid)[0] == name:
            return rid
    raise KeyError(name)


def event_id(name: str) -> int:
    for i in range(sim.event_count()):
        if sim.event_info(i)[0] == name:
            return i
    raise KeyError(name)


def battle(cards, encounter="SETUP_LAGAVULIN_MATRIARCH_BOSS", seed=7, hp=500,
           potions=(), gold=0, relics=()):
    bc = sim.BattleContext()
    bc.init(getattr(sim.Encounter, encounter), seed, cards,
            [False] * len(cards), 0, hp, hp, list(relics), list(potions))
    bc.gold = gold
    return bc


def play_by_id(bc, name: str):
    ids = [i for i, c in enumerate(bc.hand) if c[0] == card_id(name)]
    actions = [a for a in bc.legal_actions()
               if a[0] == PLAY_CARD and a[1] == ids[0]] if ids else []
    assert actions
    assert bc.step(*actions[0])


def deck_names(rc):
    return [sim.card_name(c[0]) for c in rc.deck]


# --------------------------------------------------------------------- ancients
def test_act_ancients_are_reachable_from_the_correct_pools():
    seen = {0: set(), 1: set(), 2: set()}
    darv_acts = {}
    for seed in range(1, 121):
        rc = new_run(seed)
        seen[0].add(rc.event_name)
        for act in (1, 2):
            assert rc.start_act(act)
            seen[act].add(rc.event_name)
            if rc.event_name == "DARV":
                darv_acts.setdefault(seed, set()).add(act)
    assert seen[0] == {"NEOW"}
    assert seen[1] <= {"OROBAS", "PAEL", "TEZCATARA", "DARV"}
    assert seen[2] <= {"NONUPEIPE", "TANX", "VAKUU", "DARV"}
    assert {"OROBAS", "PAEL", "TEZCATARA"} <= seen[1]
    assert {"NONUPEIPE", "TANX", "VAKUU"} <= seen[2]
    assert darv_acts, "Darv must be reachable from the shared ancient pool"
    # Shared without replacement: Darv cannot appear in both acts 2 and 3.
    assert all(len(acts) == 1 for acts in darv_acts.values())


def test_ancient_choice_grants_the_offered_relic():
    for seed in range(1, 40):
        rc = new_run(seed)
        for act in range(3):
            if act:
                assert rc.start_act(act)
            assert rc.screen == SCREEN.EVENT
            options = list(rc.event_relics)
            assert len(options) == 3 and all(r > 0 for r in options)
            assert len(set(options)) == 3
            before = set(rc.relics)
            assert rc.step(EVENT_CHOICE, 2)
            gained = set(rc.relics) - before
            assert options[2] in gained
            # Touch of Orobas is kept and also replaces Burning Blood.
            if options[2] == relic_id("TOUCH_OF_OROBAS"):
                assert relic_id("BLACK_BLOOD") in rc.relics
                assert relic_id("BURNING_BLOOD") not in rc.relics
            # Relics such as Calling Bell / Toy Box grant further relics.


def test_neow_offers_follow_the_relic_mirror_rules():
    curses = {relic_id(n) for n in
              ("CURSED_PEARL", "LARGE_CAPSULE", "LEAFY_POULTICE",
               "PRECARIOUS_SHEARS", "SCROLL_BOXES", "SILVER_CRUCIBLE")}
    seen_curses = set()
    for seed in range(1, 161):
        rc = new_run(seed)
        offers = list(rc.event_relics)
        curse = offers[2]
        assert curse in curses
        seen_curses.add(curse)
        if curse == relic_id("CURSED_PEARL"):
            assert relic_id("GOLDEN_PEARL") not in offers[:2]
        if curse == relic_id("PRECARIOUS_SHEARS"):
            assert relic_id("PRECISE_SCISSORS") not in offers[:2]
        if curse == relic_id("LEAFY_POULTICE"):
            assert relic_id("NEW_LEAF") not in offers[:2]
    assert {relic_id("CURSED_PEARL"), relic_id("LARGE_CAPSULE")} <= seen_curses


def test_event_option_observation_encodes_relic_identity():
    a = new_run(2)
    b = new_run(3)
    # Different Neow offers must produce different public observations.
    assert list(a.event_relics) != list(b.event_relics)
    oa = np.asarray(a.observe_public(), dtype=np.float32)
    ob = np.asarray(b.observe_public(), dtype=np.float32)
    assert oa.shape == (sim.PUBLIC_OBS_DIM,)
    assert not np.array_equal(oa, ob)


def test_archaic_tooth_transforms_bash_into_break():
    rc = new_run(7)
    assert rc.add_relic(relic_id("ARCHAIC_TOOTH"))
    names = deck_names(rc)
    assert "Break" in names and "Bash" not in names
    assert rc.deck_count == 10


def test_alchemical_coffer_adds_four_slots_and_four_potions():
    rc = new_run(7)
    slots, potions = rc.potion_slots, len(rc.potions)
    assert rc.add_relic(relic_id("ALCHEMICAL_COFFER"))
    assert rc.potion_slots == slots + 4
    assert len(rc.potions) == potions + 4


def test_sand_castle_upgrades_six_cards():
    rc = new_run(7)
    assert rc.add_relic(relic_id("SAND_CASTLE"))
    upgraded = sum(1 for c in rc.deck if c[1])
    assert upgraded == 6


def test_paels_flesh_grants_energy_from_round_three():
    flesh = relic_id("PAELS_FLESH")
    strikec = card_id("Strike")
    bc = battle([strikec] * 10, relics=[flesh])
    assert bc.turn == 1 and bc.energy == 3
    bc.step(END_TURN, 0, 0, 0)
    assert bc.energy == 3
    bc.step(END_TURN, 0, 0, 0)
    assert bc.turn == 3 and bc.energy == 4


def test_paels_blood_draws_an_extra_card():
    blood = relic_id("PAELS_BLOOD")
    plain = battle([card_id("Strike")] * 10)
    buffed = battle([card_id("Strike")] * 10, relics=[blood])
    assert len(buffed.hand) == len(plain.hand) + 1


# ------------------------------------------------------------------------ curses
def test_clumsy_is_unplayable_and_ethereal():
    bc = battle([card_id("Clumsy")] * 8)
    assert not [a for a in bc.legal_actions() if a[0] == PLAY_CARD]
    bc.step(END_TURN, 0, 0, 0)
    assert bc.exhaust_count == 5


def test_decay_deals_two_damage_at_turn_end():
    bc = battle([card_id("Decay")] * 10)
    hp0 = bc.player_hp
    bc.step(END_TURN, 0, 0, 0)
    # Five copies in the opening hand, 2 unpowered damage each.
    assert hp0 - bc.player_hp == 10


def test_bad_luck_deals_thirteen_unblockable():
    bc = battle([card_id("Bad Luck")] * 10)
    hp0 = bc.player_hp
    bc.step(END_TURN, 0, 0, 0)
    assert hp0 - bc.player_hp == 13 * 5


def test_regret_hits_for_cards_in_hand():
    bc = battle([card_id("Regret")] * 10)
    hp0 = bc.player_hp
    bc.step(END_TURN, 0, 0, 0)
    # Each of the five Regrets in hand hits for the 5-card hand size.
    assert hp0 - bc.player_hp == 25


def test_doubt_and_shame_apply_status_that_does_not_tick_immediately():
    bc = battle([card_id("Doubt"), card_id("Shame"), card_id("Defend"),
                 card_id("Defend"), card_id("Defend")])
    assert bc.player_weak == 0 and bc.player_frail == 0
    bc.step(END_TURN, 0, 0, 0)
    # One copy of each in hand; both are applied and survive this turn's tick.
    assert bc.player_weak == 1
    assert bc.player_frail == 1


def test_debt_drains_at_most_the_gold_you_have():
    bc = battle([card_id("Debt")] * 5, gold=7)
    bc.step(END_TURN, 0, 0, 0)
    assert bc.gold == 0


def test_normality_blocks_a_fourth_card():
    anger = card_id("Anger")
    deck = [card_id("Normality")] + [anger] * 4
    bc = battle(deck, encounter="SETUP_CEREMONIAL_BEAST_BOSS")
    assert len(bc.hand) == 5
    for _ in range(3):
        play_by_id(bc, "Anger")
    assert not [a for a in bc.legal_actions() if a[0] == PLAY_CARD]


# ------------------------------------------------------------------ event cards
def test_relax_gains_block_and_delays_energy_and_draw():
    bc = battle([card_id("Relax")] * 10)
    play_by_id(bc, "Relax")
    assert bc.player_block >= 15
    bc.step(END_TURN, 0, 0, 0)
    assert bc.turn == 2
    assert bc.energy == 5          # 3 base + 2 next turn
    assert len(bc.hand) == 7       # 5 base + 2 next turn


def test_brightest_flame_trades_max_hp_for_energy_and_cards():
    bc = battle([card_id("Brightest Flame")] * 10)
    hp0, max0 = bc.player_hp, bc.player_max_hp
    play_by_id(bc, "Brightest Flame")
    assert bc.energy == 5
    assert bc.player_max_hp == max0 - 1
    assert bc.player_hp == hp0 - 1


# --------------------------------------------------------------- event curses
def test_this_or_that_adds_clumsy():
    rc = new_run(5)
    assert rc.begin_event(event_id("THIS_OR_THAT"))
    assert rc.step(EVENT_CHOICE, 1)
    assert "Clumsy" in deck_names(rc)


def test_lost_wisp_adds_decay():
    rc = new_run(5)
    assert rc.begin_event(event_id("LOST_WISP"))
    assert rc.step(EVENT_CHOICE, 0)
    assert "Decay" in deck_names(rc)


def test_unrest_site_rest_adds_poor_sleep():
    rc = new_run(5)
    assert rc.begin_event(event_id("UNREST_SITE"))
    assert rc.step(EVENT_CHOICE, 0)
    assert "Poor Sleep" in deck_names(rc)


def test_wellspring_removal_adds_guilty():
    rc = new_run(5)
    assert rc.begin_event(event_id("WELLSPRING"))
    deck0 = rc.deck_count
    assert rc.step(EVENT_CHOICE, 1)
    assert rc.deck_count == deck0  # one removed, Guilty added
    assert "Guilty" in deck_names(rc)


def test_reflections_shatter_adds_bad_luck():
    rc = new_run(5)
    assert rc.begin_event(event_id("REFLECTIONS"))
    deck0 = rc.deck_count
    assert rc.step(EVENT_CHOICE, 1)
    assert rc.deck_count == 2 * deck0 + 1
    assert "Bad Luck" in deck_names(rc)


def test_cursed_pearl_adds_greed():
    rc = new_run(5)
    gold0 = rc.gold
    assert rc.add_relic(relic_id("CURSED_PEARL"))
    assert rc.gold == gold0 + 333
    assert "Greed" in deck_names(rc)
