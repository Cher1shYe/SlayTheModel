from pathlib import Path

from deployment import evaluate_hidden_puct as hidden


class FakeBattle:
    def __init__(self):
        self.seeds = []

    def legal_actions(self):
        return [(1, 0, 0, 17), (1, 1, 0, 18)]

    def mcts_depth_priors(self, simulations, callback, depth, c, seed, greedy, epsilon, resample):
        assert depth == 4
        assert resample is True
        self.seeds.append(seed)
        # Simulated future actions must never be cached by the controller.
        return [self.legal_actions()[0], self.legal_actions()[1]], simulations, True


def test_search_seed_does_not_use_game_seed_and_returns_only_root(monkeypatch):
    monkeypatch.setattr(hidden, "_activity_path", None)
    monkeypatch.setattr(hidden, "_search_seed", 1234)
    monkeypatch.setattr(hidden, "_depth", 4)
    monkeypatch.setattr(hidden, "_decisions", 0)
    battle = FakeBattle()
    plan, done = hidden._plan(battle, 10001, "mcts-resampled", 10, 0.05, False)
    assert plan == [battle.legal_actions()[0]] and done == 10
    hidden._plan(battle, 10001, "mcts-resampled", 10, 0.05, False)
    assert battle.seeds == [1234, 1234 + 7919]
    monkeypatch.setattr(hidden, "_decisions", 0)
    hidden._plan(battle, 99999, "mcts-resampled", 10, 0.05, False)
    assert battle.seeds[-1] == 1234


def test_activity_write_failure_does_not_fail_a_game(monkeypatch, tmp_path):
    monkeypatch.setattr(hidden, "_activity_path", tmp_path / "worker.json")
    monkeypatch.setattr(hidden, "_activity_seed", 1)
    monkeypatch.setattr(hidden, "_started", 0.0)
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError()))
    hidden._activity(force=True)
