from __future__ import annotations

import pytest

from deployment.evaluate_combat_dagger import paired_summary, summarize


def _episode(arm, seed, floor, won=False, status="terminated", **kwargs):
    return {"arm": arm, "seed": seed, "floor": floor, "won": won,
            "status": status, "elapsed_seconds": 1.0, **kwargs}


def test_paired_floor_and_win_rates_exclude_incomplete_pairs():
    rows = [_episode("student", 1, 20, True, battles=3, battle_wins=2),
            _episode("student", 2, 12),
            _episode("student", 3, 40, status="truncated"),
            _episode("greedy", 1, 14), _episode("greedy", 2, 16, True),
            _episode("greedy", 3, 8),
            _episode("mcts-oracle", 1, 30), _episode("mcts-oracle", 2, 40, True),
            _episode("mcts-oracle", 3, 0, status="error")]
    result = paired_summary(rows, ("student", "greedy", "mcts-oracle"))
    student = result["arms"]["student"]
    assert (student["completed"], student["truncated"], student["win_rate_completed"]) == (2, 1, 0.5)
    assert student["mean_floor_completed"] == 16
    assert student["battle_win_rate"] == 2 / 3
    greedy = result["paired_student_vs"]["greedy"]
    assert greedy["complete_pairs"] == 2
    assert greedy["student_minus_baseline_floor"] == 1
    assert greedy["student_only_wins"] == greedy["baseline_only_wins"] == 1
    assert result["arms"]["mcts-oracle"]["errors"] == 1


def test_no_complete_results_and_duplicate_seed_are_reported():
    assert summarize([_episode("student", 1, 0, status="error")])["mean_floor_completed"] is None
    rows = [_episode("student", 1, 1), _episode("student", 1, 2)]
    with pytest.raises(ValueError, match="duplicate"):
        paired_summary(rows, ("student",))
