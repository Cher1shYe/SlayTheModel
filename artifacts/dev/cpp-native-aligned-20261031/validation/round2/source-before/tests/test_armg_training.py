from __future__ import annotations

import numpy as np
from pathlib import Path
import subprocess
import sys
import torch
import pytest

from agent import armg_train
from agent.armg import ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM, ArmGScorer


def test_single_combat_action_needs_no_search_simulation():
    class Battle:
        def search(self, *args):
            return [(1, 0, 0, 0)], [0], [0.0], 0

    assert armg_train._combat_action(Battle(), 10, "search", 8, 0.05) == (1, 0, 0, 0)


def test_mcts_plan_boss_budget_and_hidden_information():
    class Battle:
        def __init__(self):
            self.args = None

        def legal_actions(self):
            return [(1, 0, 0, 0), (2, 0, 0, 0)]

        def mcts(self, *args):
            self.args = args
            return [(1, 0, 0, 0)] * 20, args[0], True

    battle = Battle()
    plan, done = armg_train._mcts_plan(battle, 123, "mcts-oracle", 100, 0.05, True)
    assert len(plan) == 15 and done == 300
    assert battle.args[0] == 300 and battle.args[3:5] == (False, False)
    plan, done = armg_train._mcts_plan(battle, 123, "mcts-resampled", 100, 0.05, False)
    assert len(plan) == 1 and done == 100
    assert battle.args[3:5] == (True, False)


def test_warm_start_resets_training_state_and_tracks_source(tmp_path, monkeypatch):
    def episode(seed, model, *, deterministic=False, **kwargs):
        return {"seed": seed, "status": "terminated", "won": False,
                "floor": 8, "hp": 0, "steps": 1, "records": [], "error": None}

    monkeypatch.setattr(armg_train, "collect_episode", episode)
    src = tmp_path / "source"
    dst = tmp_path / "mcts"
    armg_train.train(games=1, out_dir=str(src), combat="greedy", eval_runs=1)
    armg_train.train(games=1, out_dir=str(dst), combat="mcts-oracle", eval_runs=1,
                     init_checkpoint=str(src / "latest.pt"), train_seed_offset=100000)
    old = torch.load(src / "latest.pt", map_location="cpu", weights_only=False)
    new = torch.load(dst / "latest.pt", map_location="cpu", weights_only=False)
    assert all(torch.equal(old["state_dict"][key], new["state_dict"][key])
               for key in old["state_dict"])
    assert new["progress"]["games"] == 1
    assert new["progress"]["initialization"]["source_settings"]["combat"] == "greedy"
    assert len(new["progress"]["initialization"]["sha256"]) == 64
    assert new["settings"]["combat"] == "mcts-oracle"
    assert new["settings"]["train_seed_offset"] == 100000
    assert new["optimizer_state_dict"]["state"] == {}
    with pytest.raises(ValueError, match="settings differ"):
        armg_train.train(games=2, out_dir=str(dst), combat="mcts-oracle", eval_runs=1,
                         resume=str(src / "latest.pt"))


def test_batched_gradient_matches_per_run_loss_with_variable_actions():
    torch.set_num_threads(1)
    torch.manual_seed(13)
    rng = np.random.default_rng(18)
    model = ArmGScorer()
    weighted = []
    for counts, advantage in (([2, 7], 0.24), ([3], -0.47), ([6, 2], 0.1)):
        records = [(rng.normal(size=ARMG_OBS_DIM).astype(np.float32),
                    rng.normal(size=(n, ARMG_ACTION_DIM)).astype(np.float32), n - 1)
                   for n in counts]
        weighted.append((records, advantage))
    original_loss = sum(armg_train.game_loss(model, records, advantage)
                        for records, advantage in weighted) / len(weighted)
    original_loss.backward()
    gradients = [parameter.grad.clone() for parameter in model.parameters()]
    model.zero_grad()
    chunk_loss = armg_train.backward_weighted(model, weighted, chunk_size=2)
    assert np.isclose(chunk_loss, original_loss.item(), rtol=1e-5, atol=1e-6)
    for expected, parameter in zip(gradients, model.parameters()):
        assert torch.allclose(expected, parameter.grad, rtol=1e-4, atol=1e-6)


def test_resume_restores_optimizer_baseline_and_rng(tmp_path, monkeypatch):
    def episode(seed, model, *, deterministic=False, **kwargs):
        obs = np.zeros(ARMG_OBS_DIM, dtype=np.float32)
        candidates = np.zeros((2, ARMG_ACTION_DIM), dtype=np.float32)
        candidates[0, 0], candidates[1, 0] = 1.0, -1.0
        choice = int(torch.randint(0, 2, (1,))) if not deterministic else 0
        return {"seed": seed, "status": "terminated", "won": False,
                "floor": 5 + seed % 7, "hp": 0, "steps": 1,
                "records": [] if deterministic else [(obs, candidates, choice)], "error": None}

    monkeypatch.setattr(armg_train, "collect_episode", episode)
    opts = dict(batch_size=2, eval_every=2, eval_runs=2, combat="greedy", seed=7)
    straight = tmp_path / "straight"
    resumed = tmp_path / "resumed"
    armg_train.train(games=4, out_dir=str(straight), **opts)
    armg_train.train(games=2, out_dir=str(resumed), **opts)
    armg_train.train(games=4, out_dir=str(resumed), resume=str(resumed / "latest.pt"), **opts)
    full = torch.load(straight / "latest.pt", map_location="cpu", weights_only=False)
    restored = torch.load(resumed / "latest.pt", map_location="cpu", weights_only=False)
    assert restored["config"]["armg_feature_version"] == ARMG_FEATURE_VERSION
    assert full["progress"] == restored["progress"]
    assert all(torch.equal(full["state_dict"][k], restored["state_dict"][k])
               for k in full["state_dict"])


def test_summary_excludes_incomplete_from_win_rate():
    episodes = [{"status": "terminated", "floor": 20, "won": True},
                {"status": "truncated", "floor": 40, "won": False},
                {"status": "error", "floor": 2, "won": False}]
    result = armg_train.summarize(episodes)
    assert result == {"runs": 3, "completed": 1, "truncated": 1, "errors": 1,
                      "cycle_recoveries": 0, "runs_with_recovery": 0,
                      "mcts_searches": 0, "mcts_simulations": 0,
                      "mean_floor": 20.0, "win_rate": 1.0}


def test_policy_cycle_recovers_with_a_legal_action_and_reports_it(monkeypatch):
    from agent.common import SCREEN

    class Run:
        screen = SCREEN.EVENT
        truncated = False
        won = False
        floor = 1
        hp = 0

        def step(self, action, _index):
            if action == 2:
                self.screen = SCREEN.RUN_OVER
            return True

    class Model:
        def __call__(self, obs, candidates):
            return torch.tensor([[1.0, -1.0]])

    monkeypatch.setattr(armg_train, "new_run", lambda *args: Run())
    monkeypatch.setattr(armg_train, "build_candidates", lambda rc: (
        np.zeros(2, dtype=np.float32), [(1, 0), (2, 0)], np.zeros((2, 2), dtype=np.float32)))
    ep = armg_train.collect_episode(42, Model(), deterministic=True, max_steps=10)
    assert ep["status"] == "terminated"
    assert ep["steps"] == 4
    assert ep["cycle_recoveries"] == 1


def test_spawn_rollouts_are_stable_across_worker_counts(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    payloads = []
    for workers in (2, 3):
        out = tmp_path / f"workers-{workers}"
        subprocess.run([sys.executable, "-m", "agent.armg_train", "--games", "4",
                        "--batch-size", "4", "--eval-every", "4", "--eval-runs", "1",
                        "--combat", "greedy", "--max-steps", "500", "--workers", str(workers),
                        "--out-dir", str(out)], cwd=repo, check=True, capture_output=True, timeout=90)
        payloads.append(torch.load(out / "latest.pt", map_location="cpu", weights_only=False))
    left, right = payloads
    assert left["progress"] == right["progress"]
    assert torch.equal(left["torch_rng_state"], right["torch_rng_state"])
    assert all(torch.equal(left["state_dict"][key], right["state_dict"][key])
               for key in left["state_dict"])
