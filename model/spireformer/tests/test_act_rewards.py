"""Whole-run act reward arithmetic and boundary/state-machine contracts."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

from spireformer.act_rewards import (
    ACT_RTG_SCHEME,
    BattleEnd,
    BattleStart,
    EpisodeRewardAccumulator,
    act_reward_parameters,
    undiscounted_returns,
)


def _boss(act: int, **changes) -> BattleStart:
    return replace(BattleStart(f"boss-{act}", act, True, 40, 80, 2, 2), **changes)


def _end(start: BattleStart, **changes) -> BattleEnd:
    return replace(BattleEnd(start.combat_id, start.act, 30, 80, True), **changes)


def _complete(accumulator: EpisodeRewardAccumulator, act: int, **changes):
    start = _boss(act, **changes)
    preparation = accumulator.begin_battle(start)
    milestone = accumulator.end_battle(_end(start, act_completed=True))
    return preparation, milestone


@pytest.mark.parametrize("before,after,post_max,expected", [
    (80, 60, 80, -0.25), (40, 60, 80, 0.25), (40, 40, 80, 0.0),
    (80, 60, 100, -0.2), (80, 0, 20, -4.0),
])
def test_nonboss_hp_uses_post_max_hp_and_is_unclipped(
    before: float, after: float, post_max: float, expected: float,
) -> None:
    accumulator = EpisodeRewardAccumulator()
    start = BattleStart("normal-or-elite", 1, False, before, 80)
    assert accumulator.begin_battle(start) == {}
    result = accumulator.end_battle(_end(
        start, hp=after, max_hp=post_max, won=after > 0,
    ))
    assert result == {"combat_hp": expected}
    assert accumulator.total_reward == expected


@pytest.mark.parametrize("post_hp,won", [(80, True), (1, True), (0, False)])
def test_boss_hp_change_never_generates_hp_reward(post_hp: float, won: bool) -> None:
    accumulator = EpisodeRewardAccumulator()
    start = _boss(1)
    assert accumulator.begin_battle(start) == {"upgraded_cards": 0.1, "relics": 0.2}
    assert accumulator.end_battle(_end(start, hp=post_hp, won=won)) == {}


def test_full_counts_recur_each_act_and_third_act_adds_entry_hp() -> None:
    accumulator = EpisodeRewardAccumulator()
    first, first_end = _complete(accumulator, 1)
    second, second_end = _complete(accumulator, 2)
    third, third_end = _complete(accumulator, 3)
    assert first == second == {"upgraded_cards": 0.1, "relics": 0.2}
    assert third == {"upgraded_cards": 0.1, "relics": 0.2, "act3_entry_hp": 0.5}
    assert [first_end, second_end, third_end] == [
        {"act_completion": 1.0}, {"act_completion": 2.0}, {"act_completion": 3.0},
    ]
    assert accumulator.finish("win") == {}
    assert accumulator.total_reward == pytest.approx(7.4)
    assert accumulator.completed_acts == frozenset({1, 2, 3})
    assert accumulator.outcome == "win"


def test_preparation_uses_current_counts_without_caps_or_incremental_deltas() -> None:
    accumulator = EpisodeRewardAccumulator()
    preparation, _ = _complete(accumulator, 1, upgraded_cards=1000, relics=1000)
    assert preparation == {"upgraded_cards": 50.0, "relics": 100.0}
    next_preparation, _ = _complete(accumulator, 2, upgraded_cards=1, relics=1)
    assert next_preparation == {"upgraded_cards": 0.05, "relics": 0.1}
    assert accumulator.total_reward > 100


def test_third_act_hp_fraction_uses_pre_boss_max_hp() -> None:
    accumulator = EpisodeRewardAccumulator()
    _complete(accumulator, 1)
    _complete(accumulator, 2)
    preparation, _ = _complete(accumulator, 3, hp=40, max_hp=160)
    # _complete ends at 30/80 HP; neither end value belongs in this bonus.
    assert preparation["act3_entry_hp"] == 0.25


def test_double_boss_has_one_preparation_and_one_explicit_act_milestone() -> None:
    accumulator = EpisodeRewardAccumulator()
    _complete(accumulator, 1)
    _complete(accumulator, 2)
    first = _boss(3)
    assert accumulator.begin_battle(first)["act3_entry_hp"] == 0.5
    assert accumulator.end_battle(_end(first)) == {}
    assert accumulator.completed_acts == frozenset({1, 2})
    second = replace(first, combat_id="second-boss", hp=20, upgraded_cards=99, relics=99)
    assert accumulator.begin_battle(second) == {}
    assert accumulator.end_battle(_end(second, act_completed=True)) == {"act_completion": 3.0}
    assert accumulator.finish("win") == {}
    assert accumulator.total_reward == pytest.approx(7.4)


def test_winning_boss_does_not_imply_act_completion() -> None:
    accumulator = EpisodeRewardAccumulator()
    start = _boss(1)
    accumulator.begin_battle(start)
    accumulator.end_battle(_end(start))
    with pytest.raises(ValueError, match="milestones"):
        accumulator.begin_battle(_boss(2))
    with pytest.raises(ValueError, match="all three"):
        accumulator.finish("win")


@pytest.mark.parametrize("is_boss,expected_hp", [(False, -0.5), (True, 0.0)])
def test_combat_defeat_adds_one_terminal_penalty(is_boss: bool, expected_hp: float) -> None:
    accumulator = EpisodeRewardAccumulator()
    start = BattleStart("fatal", 1, is_boss, 40, 80, 0, 0)
    accumulator.begin_battle(start)
    end_components = accumulator.end_battle(_end(start, hp=0, won=False))
    assert sum(end_components.values()) == expected_hp
    with pytest.raises(ValueError, match="after defeat"):
        accumulator.begin_battle(replace(start, combat_id="too-late"))
    assert accumulator.finish("defeat") == {"defeat": -10.0}
    assert accumulator.total_reward == -10 + expected_hp
    with pytest.raises(ValueError, match="already finished"):
        accumulator.finish("defeat")


def test_outside_combat_defeat_preserves_prior_rewards() -> None:
    accumulator = EpisodeRewardAccumulator()
    _complete(accumulator, 1)
    assert accumulator.finish("defeat") == {"defeat": -10.0}
    assert accumulator.total_reward == pytest.approx(-8.7)
    assert EpisodeRewardAccumulator().finish("defeat") == {"defeat": -10.0}


@pytest.mark.parametrize("outcome", [None, "", "unknown", "abandoned", "truncated", "ongoing"])
def test_incomplete_outcomes_are_rejected_without_poisoning_state(outcome) -> None:
    accumulator = EpisodeRewardAccumulator()
    with pytest.raises(ValueError, match="verified terminal"):
        accumulator.finish(outcome)
    assert accumulator.outcome is None
    assert accumulator.finish("defeat") == {"defeat": -10.0}


def test_unmatched_and_duplicate_battles_reject_without_rewards() -> None:
    accumulator = EpisodeRewardAccumulator()
    first = _boss(1)
    with pytest.raises(ValueError, match="no matching"):
        accumulator.end_battle(_end(first))
    accumulator.begin_battle(first)
    total = accumulator.total_reward
    with pytest.raises(ValueError, match="already active"):
        accumulator.begin_battle(replace(first, combat_id="other"))
    for unmatched in (_end(first, combat_id="other"), _end(first, act=2)):
        with pytest.raises(ValueError, match="does not match"):
            accumulator.end_battle(unmatched)
    with pytest.raises(ValueError, match="unclosed"):
        accumulator.finish("defeat")
    assert accumulator.total_reward == total
    accumulator.end_battle(_end(first))
    with pytest.raises(ValueError, match="duplicate"):
        accumulator.begin_battle(first)
    with pytest.raises(ValueError, match="no matching"):
        accumulator.end_battle(_end(first))
    assert accumulator.total_reward == total


def test_completed_act_cannot_be_awarded_again_or_entered_again() -> None:
    accumulator = EpisodeRewardAccumulator()
    _complete(accumulator, 1)
    total = accumulator.total_reward
    with pytest.raises(ValueError, match="milestones"):
        accumulator.begin_battle(_boss(1, combat_id="repeated-act"))
    with pytest.raises(ValueError, match="no matching"):
        accumulator.end_battle(_end(_boss(1), act_completed=True))
    assert accumulator.total_reward == total


@pytest.mark.parametrize("is_boss,won", [(False, True), (False, False), (True, False)])
def test_act_completion_requires_a_won_boss(is_boss: bool, won: bool) -> None:
    accumulator = EpisodeRewardAccumulator()
    start = BattleStart("battle", 1, is_boss, 40, 80, 0, 0)
    accumulator.begin_battle(start)
    with pytest.raises(ValueError, match="won boss"):
        accumulator.end_battle(_end(start, won=won, act_completed=True))
    assert accumulator.completed_acts == frozenset()
    assert accumulator.total_reward == 0


def test_no_battle_or_end_after_finish() -> None:
    accumulator = EpisodeRewardAccumulator()
    accumulator.finish("defeat")
    with pytest.raises(ValueError, match="already finished"):
        accumulator.begin_battle(_boss(1))
    with pytest.raises(ValueError, match="already finished"):
        accumulator.end_battle(_end(_boss(1)))


@pytest.mark.parametrize("changes", [
    {"combat_id": ""}, {"combat_id": "  "}, {"combat_id": None},
    {"act": 0}, {"act": 4}, {"act": True}, {"act": 1.0},
    {"hp": -1}, {"hp": 81}, {"hp": math.nan}, {"hp": math.inf}, {"hp": True},
    {"max_hp": 0}, {"max_hp": -1}, {"max_hp": math.inf}, {"max_hp": "80"},
])
def test_boundary_validation(changes) -> None:
    with pytest.raises(ValueError):
        replace(_boss(1), **changes)
    with pytest.raises(ValueError):
        replace(_end(_boss(1)), **changes)


@pytest.mark.parametrize("changes", [
    {"is_boss": 1}, {"upgraded_cards": None}, {"upgraded_cards": -1},
    {"upgraded_cards": 1.5}, {"upgraded_cards": True}, {"upgraded_cards": math.inf},
    {"relics": None}, {"relics": -1}, {"relics": 1.5}, {"relics": True},
])
def test_boss_count_validation(changes) -> None:
    with pytest.raises(ValueError):
        replace(_boss(1), **changes)


@pytest.mark.parametrize("changes", [{"won": 1}, {"act_completed": 1}])
def test_end_flags_require_booleans(changes) -> None:
    with pytest.raises(ValueError):
        replace(_end(_boss(1)), **changes)


def test_returns_are_undiscounted_and_unclipped() -> None:
    assert undiscounted_returns([0.25, 1.0, 20, -10.0]) == (11.25, 11.0, 10.0, -10.0)
    assert undiscounted_returns([]) == ()
    for invalid in ([math.nan], [math.inf], [True], ["1"], [1e308, 1e308]):
        with pytest.raises(ValueError):
            undiscounted_returns(invalid)


def test_scheme_parameters_state_actual_unclipped_reward_semantics() -> None:
    parameters = act_reward_parameters()
    assert ACT_RTG_SCHEME == "whole-run-act-v1"
    assert parameters["discount"] == 1.0
    assert parameters["clipping"] is None
    assert parameters["terminal_win"] == 0
    assert parameters["terminal_defeat"] == -10
    assert parameters["nonboss_combat_hp"] == "(post_hp - pre_hp) / post_max_hp"
    assert parameters["preparation_counting"] == "full_current_counts_once_per_act"
    assert parameters["upgraded_card_counting"] == "each_upgraded_permanent_deck_card_once"
    assert parameters["relic_counting"] == "all_currently_held_including_starting_relic"
