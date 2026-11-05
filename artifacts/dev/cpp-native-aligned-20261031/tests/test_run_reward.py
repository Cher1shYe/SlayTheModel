"""Terminal reward and permanent-deck Elo (spec: Part 2 of the 2026-11-05 goal)."""
from __future__ import annotations

import math

import pytest

from agent.common import sim
from agent.run_reward import (
    DEFAULT_ELO_SNAPSHOT, DeckElo, RunRewardTracker, terminal_reward,
)


def card(name: str) -> int:
    return next(i for i in range(1, sim.card_count()) if sim.card_name(i) == name)


def test_specified_example_sums_to_4_47():
    """L1=10, L2=5, E1=2, E2=1, 1 boss, 1 upgrade, 1 removal, mean Elo 1500."""
    tracker = RunRewardTracker()
    tracker.act_floor = {1: 10, 2: 5}
    tracker.elites = {1: 2, 2: 1}
    tracker.bosses = 1
    tracker.upgrades = 1
    tracker.removals = 1
    components = tracker.components()
    assert components["floor_reward"] == pytest.approx(10 * 1 / 20 + 5 * 2 / 20)
    assert components["elite_bonus"] == pytest.approx(0.1 * 2 + 0.2 * 1)
    assert components["boss_bonus"] == pytest.approx(0.5)
    assert components["upgrade_bonus"] == pytest.approx(0.05)
    assert components["removal_bonus"] == pytest.approx(0.02)
    total = terminal_reward(components, 1500 / 600.0)
    assert total == pytest.approx(4.47)


@pytest.mark.parametrize("bosses,expected", [
    (0, 0.0), (1, 0.5), (2, 1.5), (3, 3.0), (4, 5.0),
])
def test_boss_term_weights_by_order(bosses, expected):
    tracker = RunRewardTracker()
    tracker.bosses = bosses
    assert tracker.components()["boss_bonus"] == pytest.approx(expected)


def test_act_floor_keeps_highest_and_ignores_unentered_acts():
    class Run:
        def __init__(self, act, floor, screen=None):
            self.act, self.act_floor = act, floor
            self.screen = screen if screen is not None else sim.RunScreen.MAP

    tracker = RunRewardTracker()
    for act, floor in [(0, 3), (0, 9), (0, 4), (1, 2), (1, 6)]:
        tracker.observe(Run(act, floor))
    assert tracker.components()["max_floor_by_act"] == {1: 9, 2: 6}
    # Repeating the same floor cannot double count.
    assert tracker.components()["floor_reward"] == pytest.approx(9 / 20 + 12 / 20)
    # A run that never enters act 3 scores nothing for it.
    assert tracker.act_floor.get(3, 0) == 0


def test_elites_are_weighted_by_the_act_they_died_in():
    tracker = RunRewardTracker()
    tracker.elite_defeated(1)
    tracker.elite_defeated(1)
    tracker.elite_defeated(2)
    tracker.elite_defeated(3)
    assert tracker.components()["elite_bonus"] == pytest.approx(0.2 + 0.2 + 0.3)


def test_more_than_four_bosses_is_rejected():
    tracker = RunRewardTracker()
    tracker.bosses = 5
    with pytest.raises(ValueError, match="four bosses"):
        terminal_reward(tracker.components())
    with pytest.raises(ValueError, match="non-finite"):
        terminal_reward(RunRewardTracker().components(), float("nan"))


def test_cumulative_excludes_the_terminal_only_elo_term():
    tracker = RunRewardTracker()
    tracker.act_floor = {1: 4}
    tracker.upgrades = 2
    assert tracker.cumulative() == pytest.approx(0.2 + 0.1)
    components = tracker.components()
    assert terminal_reward(components, 0.5) == pytest.approx(tracker.cumulative() + 0.5)


# ------------------------------------------------------------------------ Elo
@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_elo_snapshot_identity_is_pinned():
    elo = DeckElo()
    identity = elo.identity()
    assert identity["cards_sha256"] == elo.manifest_declared_sha256
    assert identity["rows"] == elo.row_count > 300
    assert identity["flat_elo"] == 1150.0
    assert set(identity["excluded_names"]) == {"corruption", "break", "grapple"}
    assert identity["matching_rule"].startswith("title -> upper snake")
    # Ironclad is fully matched except the three flat-Elo starters, which the
    # spec assigns 1150 by rule rather than by data.
    missing = [sim.card_name(i) for i in range(1, sim.card_count())
               if elo.countable(i) and sim.card_pool_name(i) == "IRONCLAD"
               and i not in elo.name_to_row]
    assert sorted(missing) == ["Bash", "Defend", "Strike"]


PUNCTUATION_CASES = [("Fight Me!", "FIGHT_ME"), ("Pact's End", "PACTS_END"),
                     ("One-Two Punch", "ONE_TWO_PUNCH"), ("Bash", "BASH")]


@pytest.mark.parametrize("title,expected", PUNCTUATION_CASES)
def test_elo_names_normalise_like_the_snapshot(title, expected):
    from agent.run_reward import _snapshot_key
    assert _snapshot_key(title) == expected


@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_elo_starter_cards_are_flat_1150_including_upgrades():
    elo = DeckElo()
    for name in ("Strike", "Defend", "Bash"):
        assert elo.card_elo(card(name)) == (1150.0, False)
    # Upgraded copies use the base card's row, so they match the unupgraded one.
    pact = card("Pact's End")
    assert elo.card_elo(pact)[0] == pytest.approx(1618.7)


@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_elo_deck_mean_counts_duplicates_and_reports_exclusions():
    elo = DeckElo()
    strike, defend = card("Strike"), card("Defend")
    assert elo([(strike, False, 1, 1), (strike, True, 2, 1), (defend, False, 3, 1)]) == {
        "deck_mean_elo": 1150.0, "deck_elo_counted": 3, "deck_elo_excluded": 0,
        "deck_elo_missing": 0, "deck_elo_bonus": pytest.approx(1150 / 600)}
    # A duplicate of a rated card is counted per copy, not once.
    pact = card("Pact's End")
    two = elo([(pact, False, 1, 1), (pact, False, 2, 1)])
    assert two["deck_elo_counted"] == 2
    assert two["deck_mean_elo"] == pytest.approx(1618.7)


@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_elo_exclusions_cover_multiplayer_curses_statuses_tokens_events():
    elo = DeckElo()
    excluded = [i for i in range(1, sim.card_count())
                if sim.card_pool_name(i) in ("CURSE", "STATUS", "TOKEN", "EVENT")
                or sim.card_multiplayer_only(i)
                or sim.card_name(i).lower() in ("corruption", "break", "grapple")]
    assert excluded and not any(elo.countable(i) for i in excluded)
    only_excluded = [(i, False, n, 1) for n, i in enumerate(excluded)]
    stats = elo(only_excluded)
    assert stats["deck_mean_elo"] == 0.0 and stats["deck_elo_bonus"] == 0.0
    assert stats["deck_elo_counted"] == 0
    assert stats["deck_elo_excluded"] == len(excluded)


@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_elo_empty_deck_is_zero_not_a_division_error():
    stats = DeckElo()([])
    assert stats == {"deck_mean_elo": 0.0, "deck_elo_counted": 0, "deck_elo_excluded": 0,
                     "deck_elo_missing": 0, "deck_elo_bonus": 0.0}


@pytest.mark.skipif(not DEFAULT_ELO_SNAPSHOT.exists(), reason="frozen Elo snapshot absent")
def test_break_is_not_bash_and_missing_elo_is_flagged_not_zeroed(monkeypatch):
    """Missing data is not zero, and exclusion is not substitution."""
    elo = DeckElo()
    assert elo.card_elo(card("Bash")) == (1150.0, False)
    assert not elo.countable(card("Break"))
    assert not elo.countable(card("Corruption"))
    # A card absent from the snapshot uses 1150 *and* is reported as missing.
    monkeypatch.setattr(elo, "name_to_row", {})
    stats = elo([(card("Pact's End"), False, 1, 1)])
    assert stats["deck_mean_elo"] == 1150.0 and stats["deck_elo_missing"] == 1
