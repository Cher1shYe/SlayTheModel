from __future__ import annotations

import numpy as np
import torch

from agent import armg_train
from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, ArmGScorer
from agent.common import SCREEN
from deployment.evaluate_armg_rules import paired_summary


def test_rules_batched_gradient_matches_exact_per_decision_transform():
    torch.set_num_threads(1)
    torch.manual_seed(13)
    rng = np.random.default_rng(20)
    model = ArmGScorer()
    def record(n, choice, overlay=False):
        state = rng.normal(size=ARMG_OBS_DIM).astype(np.float32)
        actions = rng.normal(size=(n, ARMG_ACTION_DIM)).astype(np.float32)
        if not overlay:
            return state, actions, choice
        bonus = rng.normal(size=n).astype(np.float32)
        allowed = np.ones(n, dtype=np.bool_)
        allowed[(choice + 1) % n] = False
        return state, actions, choice, bonus, allowed
    weighted = [([record(3, 0, True), record(2, 1)], .4),
                ([record(5, 3, True), record(4, 0, True)], -.2)]
    expected = sum(armg_train.game_loss(model, recs, adv) for recs, adv in weighted) / len(weighted)
    expected.backward()
    gradients = [p.grad.clone() for p in model.parameters()]
    model.zero_grad()
    actual = armg_train.backward_weighted(model, weighted, chunk_size=3)
    assert np.isclose(actual, expected.item(), rtol=1e-5, atol=1e-6)
    for expected_grad, parameter in zip(gradients, model.parameters()):
        assert torch.allclose(expected_grad, parameter.grad, rtol=1e-4, atol=1e-6)


def test_paired_summary_excludes_abnormal_and_attributes_rules():
    results = []
    for seed in (201, 202):
        for arm in ("baseline", "need", "relic", "both"):
            results.append({"seed": seed, "arm": arm,
                            "status": "error" if seed == 202 and arm == "both" else "terminated",
                            "floor": 12 + (2 if arm in ("need", "both") else 0),
                            "won": arm == "both", "hp": 0,
                            "need_decisions": int(arm in ("need", "both")),
                            "relic_decisions": int(arm in ("relic", "both"))})
    result = paired_summary(results)
    assert result["arms"]["both"]["errors"] == 1
    assert result["arms"]["both"]["need_decisions"] == 2
    assert result["paired_vs_baseline"]["need"]["mean_floor_difference"] == 2
    assert result["paired_vs_baseline"]["both"]["complete_pairs"] == 1
    assert result["paired_vs_baseline"]["both"]["only_overlay_wins"] == 1


def test_forced_relic_rule_does_not_enter_policy_gradient(monkeypatch):
    import agent.armg_relic as relic
    class Run:
        screen = SCREEN.EVENT
        truncated = False
        won = False
        floor = 1
        hp = 0
        def step(self, action, index):
            assert (action, index) == (2, 0)
            self.screen = SCREEN.RUN_OVER
            return True
    class Model:
        def __call__(self, obs, candidates):
            return torch.tensor([[1.0, 0.0]])
    monkeypatch.setattr(armg_train, "new_run", lambda *args: Run())
    monkeypatch.setattr(armg_train, "build_candidates", lambda rc: (
        np.zeros(2, dtype=np.float32), [(1, 0), (2, 0)], np.zeros((2, 2), dtype=np.float32)))
    monkeypatch.setattr(relic, "relic_action", lambda rc, actions, logits: (2, 0))
    episode = armg_train.collect_episode(1, Model(), relic_rules=True, max_steps=5)
    assert episode["status"] == "terminated"
    assert episode["relic_decisions"] == 1
    assert episode["records"] == []
