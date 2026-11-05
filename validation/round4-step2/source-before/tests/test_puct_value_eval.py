from pathlib import Path

from deployment import evaluate_puct_value as evaluation


class FakeBattle:
    def __init__(self):
        self.calls = []

    def legal_actions(self):
        return [(1, 0, 0, 17), (1, 1, 0, 18)]

    def mcts_depth_priors(self, simulations, prior, depth, c, seed, greedy,
                          epsilon, resample, value_fn):
        self.calls.append((simulations, depth, seed, resample, value_fn))
        return [self.legal_actions()[0], self.legal_actions()[1]], simulations, False


def test_same_full_tree_and_independent_search_seed_in_both_arms(monkeypatch):
    monkeypatch.setattr(evaluation, "_activity_path", None)
    monkeypatch.setattr(evaluation, "_search_seed", 1234)
    battle = FakeBattle()
    for arm in evaluation.ARMS:
        monkeypatch.setattr(evaluation, "_arm", arm)
        monkeypatch.setattr(evaluation, "_decisions", 0)
        plan, done = evaluation._plan(battle, 987654321, "mcts-resampled", 512, 0.05, False)
        assert plan == [battle.legal_actions()[0]] and done == 512
    rollout, value = battle.calls
    assert rollout[:4] == value[:4] == (512, 500, 1234, True)
    assert rollout[4] is None and value[4] is evaluation._network_value


def test_only_completed_matched_seeds_in_paired_statistic():
    rows = [dict(arm="rollout", seed=1, floor=10, status="terminated", won=False),
            dict(arm="value", seed=1, floor=12, status="terminated", won=True),
            dict(arm="rollout", seed=2, floor=40, status="terminated", won=False),
            dict(arm="value", seed=2, floor=0, status="error", won=False)]
    stats = evaluation.paired_summary(rows)
    assert stats["paired_value_vs_rollout"]["complete_pairs"] == 1
    assert stats["paired_value_vs_rollout"]["mean_floor_difference"] == 2
    assert stats["arms"]["value"]["errors"] == 1


def test_progress_write_failure_does_not_stop_search(monkeypatch, tmp_path):
    monkeypatch.setattr(evaluation, "_activity_path", tmp_path / "worker.json")
    monkeypatch.setattr(Path, "write_text", lambda *a, **kw: (_ for _ in ()).throw(PermissionError()))
    evaluation._activity(force=True)
