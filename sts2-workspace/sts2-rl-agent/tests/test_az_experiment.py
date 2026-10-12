import json
import pytest
from scripts.run_alphazero_experiment import paired_report, run


def outcomes(reward):
    return [dict(scenario_id=str(i), family_id="starter", reward=reward,
                 termination_reason="win" if reward == 1 else "death", final_hp=10 if reward == 1 else 0,
                 turns=5, errors=0, illegal_actions=0, decision_seconds=[0.1]) for i in range(150)]


def test_final_paired_report_keeps_failure_and_ci():
    report = paired_report(outcomes(-1), outcomes(-1))
    assert not report["gain_passed"] and report["utility_difference_ci95"] == [0., 0.]
    gain = paired_report(outcomes(-1), outcomes(1))
    assert gain["gain_passed"] and gain["win_rate_difference_ci95"] == [1., 1.]


def test_current_150_count_is_default_and_mismatched_count_rejected():
    initial, final = outcomes(-1), outcomes(1)
    assert paired_report(initial, final, test_count=150)["gain_passed"]
    assert paired_report(initial, final)["gain_passed"]
    assert not paired_report(initial, final, test_count=500)["gain_passed"]


def test_failed_training_cannot_touch_final_test(tmp_path, monkeypatch):
    import scripts.run_alphazero_experiment as module
    class FailedCoordinator:
        def __init__(self, *args): pass
        def run(self): raise RuntimeError("training failed")
    monkeypatch.setattr(module, "Coordinator", FailedCoordinator)
    monkeypatch.setattr(module, "evaluate_parallel", lambda *args, **kwargs: pytest.fail("Test data touched early"))
    with pytest.raises(RuntimeError, match="training failed"):
        run(tmp_path / "run", "data/az/m0_manifest.json")
    root = tmp_path / "run"
    assert not (root / "frozen_final_models.json").exists()
    assert json.loads((root / "progress.json").read_text())["stage"] == "failed"
