import pytest

from deployment.evaluate_armg_checkpoints import paired_summary


def test_summary_pairs_by_seed_and_ignores_incomplete():
    rows = [
        {"arm": "baseline", "seed": 2, "status": "terminated", "floor": 20, "won": False},
        {"arm": "candidate", "seed": 1, "status": "terminated", "floor": 9, "won": True},
        {"arm": "baseline", "seed": 1, "status": "terminated", "floor": 7, "won": False},
        {"arm": "candidate", "seed": 2, "status": "terminated", "floor": 21, "won": False},
        {"arm": "baseline", "seed": 3, "status": "error", "floor": 0, "won": False},
        {"arm": "candidate", "seed": 3, "status": "terminated", "floor": 30, "won": False},
    ]
    result = paired_summary(rows, bootstrap=True)
    assert result["complete_pairs"] == 2
    assert result["mean_floor_difference"] == 1.5
    assert result["floor_difference_se"] == pytest.approx(0.5)
    assert result["candidate_only_wins"] == 1
    assert result["baseline_only_wins"] == 0
    assert result["bootstrap_95_ci"] == [1.0, 2.0]


def test_summary_rejects_duplicate_seed_within_arm():
    row = {"arm": "baseline", "seed": 1, "status": "terminated", "floor": 7}
    with pytest.raises(ValueError, match="duplicated"):
        paired_summary([row, row])
