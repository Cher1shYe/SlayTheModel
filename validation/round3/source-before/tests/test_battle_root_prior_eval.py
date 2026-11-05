from __future__ import annotations

import numpy as np
import pytest
import torch

from deployment import evaluate_battle_root_prior as evaluation


def test_compare_complete_pairs_and_exclude_abnormal():
    results = [
        {"arm": "mcts", "seed": 1, "status": "terminated", "floor": 10, "won": False},
        {"arm": "puct", "seed": 1, "status": "terminated", "floor": 15, "won": True},
        {"arm": "puct_uniform", "seed": 1, "status": "terminated", "floor": 13, "won": False},
        {"arm": "mcts", "seed": 2, "status": "terminated", "floor": 12, "won": False},
        {"arm": "puct", "seed": 2, "status": "truncated", "floor": 99, "won": False},
    ]
    data = evaluation.paired_summary(results)
    assert data["paired"]["puct_vs_mcts"]["complete_pairs"] == 1
    assert data["paired"]["puct_vs_mcts"]["mean_floor_difference"] == 5
    assert data["paired"]["puct_vs_mcts"]["treatment_only_wins"] == 1
    assert data["paired"]["puct_vs_puct_uniform"]["mean_floor_difference"] == 2
    assert data["arms"]["puct"]["truncated"] == 1


def test_fixed_budget_and_root_action_alignment(monkeypatch):
    actions = [(1, 0, 0, 10), (1, 1, 0, 11)]

    class FakeBattle:
        def legal_actions(self):
            return actions

        def mcts_priors(self, sims, got_actions, priors, c, seed, resample, greedy, epsilon):
            assert sims == 100 and got_actions == actions and sum(priors) == pytest.approx(1)
            if evaluation._current_arm == "puct_uniform":
                assert priors == pytest.approx([0.5, 0.5])
            else:
                assert priors[1] > priors[0]
            assert c == 3.0 and not resample and not greedy
            return [actions[1], actions[0]], 100, True

        def mcts(self, sims, c, seed, resample, greedy, epsilon):
            assert sims == 100 and not resample and not greedy
            return [actions[0], actions[1]], 100, True

    class Policy:
        def __call__(self, state, feats):
            return torch.tensor([[0.0, 1.0]])

    monkeypatch.setattr(evaluation, "_policy", Policy())
    monkeypatch.setattr(evaluation, "public_combat_observation", lambda _: np.zeros(4, dtype=np.float32))
    monkeypatch.setattr(evaluation, "combat_action_arrays", lambda _: (actions, np.zeros((2, 3), dtype=np.float32)))
    monkeypatch.setattr(evaluation, "_current_arm", "puct")
    assert evaluation._fixed_plan(FakeBattle(), 4, "mcts-oracle", 100, .05, True) == ([actions[1]], 100)
    monkeypatch.setattr(evaluation, "_current_arm", "puct_uniform")
    assert evaluation._fixed_plan(FakeBattle(), 4, "mcts-oracle", 100, .05, True) == ([actions[1]], 100)
    monkeypatch.setattr(evaluation, "_current_arm", "mcts")
    assert evaluation._fixed_plan(FakeBattle(), 4, "mcts-oracle", 100, .05, True) == ([actions[0]], 100)
