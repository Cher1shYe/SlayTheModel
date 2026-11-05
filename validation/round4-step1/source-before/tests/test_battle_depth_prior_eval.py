from __future__ import annotations

import numpy as np
import pytest
import torch

from deployment import evaluate_battle_depth_prior as evaluation


def test_paired_summary_excludes_incomplete_and_calculates_difference():
    rows = [
        {"arm": "puct", "seed": 1, "status": "terminated", "floor": 10, "won": False},
        {"arm": "puct_depth2", "seed": 1, "status": "terminated", "floor": 14, "won": True},
        {"arm": "puct", "seed": 2, "status": "terminated", "floor": 20, "won": False},
        {"arm": "puct_depth2", "seed": 2, "status": "truncated", "floor": 99, "won": False},
    ]
    data = evaluation.paired_summary(rows)
    paired = data["paired"]["puct_depth2_vs_puct"]
    assert paired["complete_pairs"] == 1
    assert paired["mean_floor_difference"] == 4
    assert paired["treatment_only_wins"] == 1
    assert data["arms"]["puct_depth2"]["truncated"] == 1


def test_network_prior_and_fixed_plan(monkeypatch):
    actions = [(1, 0, 0, 10), (1, 1, 0, 11)]

    class FakeBattle:
        def legal_actions(self):
            return actions

        def mcts_depth_priors(self, sims, callback, depth, c, seed, greedy, epsilon):
            assert sims == 100 and depth == 4 and c == 3.0 and not greedy
            priors = callback(self)
            assert priors[1] > priors[0] and sum(priors) == pytest.approx(1)
            return [actions[1], actions[0]], 100, True

    class Policy:
        def __call__(self, state, feats):
            return torch.tensor([[0.0, 1.0]])

    monkeypatch.setattr(evaluation.root, "_policy", Policy())
    monkeypatch.setattr(evaluation.root, "public_combat_observation", lambda _: np.zeros(4, dtype=np.float32))
    monkeypatch.setattr(evaluation.root, "combat_action_arrays", lambda _: (actions, np.zeros((2, 3), dtype=np.float32)))
    monkeypatch.setattr(evaluation, "_depth", 4)
    assert evaluation._fixed_plan(FakeBattle(), 4, "mcts-oracle", 100, .05, True) == ([actions[1]], 100)


def test_action_misalignment_fails(monkeypatch):
    class FakeBattle:
        def legal_actions(self):
            return [(1, 0, 0, 10), (1, 1, 0, 11)]

    monkeypatch.setattr(evaluation.root, "combat_action_arrays", lambda _: ([(1, 1, 0, 11)], np.zeros((1, 3))))
    with pytest.raises(RuntimeError, match="order"):
        evaluation._network_prior(FakeBattle())


def test_native_array_path_matches_legacy_callback(monkeypatch):
    observations = np.array([0.25, 0.5], dtype=np.float32)
    features = np.array([[0.1, 0.3], [0.4, 0.6]], dtype=np.float32)
    actions = [(1, 0, 0, 10), (1, 1, 0, 11)]

    class Battle:
        def legal_actions(self):
            return actions

    class FastBattle(Battle):
        def legal_action_features_array(self):
            return features.copy()

        def observation_public_array(self):
            return observations.copy()

    class Policy:
        def __call__(self, state, feats):
            assert torch.equal(state[0], torch.from_numpy(observations))
            assert torch.equal(feats[0], torch.from_numpy(features))
            return feats.sum(dim=2)

    monkeypatch.setattr(evaluation.root, "_policy", Policy())
    monkeypatch.setattr(evaluation.root, "public_combat_observation", lambda _: observations.copy())
    monkeypatch.setattr(evaluation.root, "combat_action_arrays", lambda _: (actions, features.copy()))
    assert evaluation._network_prior(Battle()) == evaluation._network_prior(FastBattle())


def test_running_episode_progress_file(tmp_path, monkeypatch):
    import json
    import time
    path = tmp_path / "worker.json"
    monkeypatch.setattr(evaluation, "_activity_path", path)
    monkeypatch.setattr(evaluation, "_activity_seed", 31010000)
    monkeypatch.setattr(evaluation, "_activity_started", time.perf_counter())
    monkeypatch.setattr(evaluation, "_depth", 8)
    monkeypatch.setattr(evaluation, "_decisions", 12)
    monkeypatch.setattr(evaluation, "_prior_calls", 43)
    evaluation._save_activity(force=True)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["seed"] == 31010000 and state["depth"] == 8
    assert state["combat_decisions_started"] == 12 and state["prior_calls"] == 43
