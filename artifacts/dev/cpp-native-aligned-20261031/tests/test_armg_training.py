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
    assert len(plan) == 15 and done == 100
    assert battle.args[0] == 100 and battle.args[3:5] == (False, False)
    plan, done = armg_train._mcts_plan(battle, 123, "mcts-resampled", 100, 0.05, False)
    assert len(plan) == 1 and done == 100
    assert battle.args[3:5] == (True, False)


def _fake_episode(model, seed, deterministic, records=()):
    """Complete-episode double: PPO needs a scored trajectory, not ``records``."""
    from agent.armg_ppo import TrajectoryRecorder
    from agent.run_reward import RunRewardTracker, terminal_reward
    tracker = RunRewardTracker()
    tracker.act_floor = {1: 5}
    components = tracker.components()
    total = terminal_reward(components)
    recorder = TrajectoryRecorder(model)
    rng = np.random.default_rng(seed)
    for obs, candidates, choice in records:
        recorder.record(obs, candidates, choice, False, total if len(recorder.rows) else 0.0)
    return {"seed": seed, "status": "terminated", "won": False,
            "floor": 8, "hp": 0, "steps": 1, "records": [],
            "ppo_records": recorder.finish(total), "reward": components,
            "total_reward": total, "error": None,
            "deck_mean_elo": 1200.0, "deck_elo_counted": 10, "deck_elo_excluded": 0,
            "deck_elo_missing": 0, "deck_elo_bonus": 2.0}


def test_warm_start_resets_training_state_and_tracks_source(tmp_path, monkeypatch):
    def episode(seed, model, *, deterministic=False, **kwargs):
        return _fake_episode(model, seed, deterministic)

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
        rows = [(obs, candidates, 0 if deterministic else choice)]
        ep = _fake_episode(model, seed, deterministic, rows)
        ep["floor"] = 5 + seed % 7
        return ep

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
                      "mean_floor": 20.0, "mean_reward": None, "win_rate": 1.0}


def test_policy_cycle_recovers_with_a_legal_action_and_reports_it(monkeypatch):
    from agent.common import SCREEN

    class Run:
        screen = SCREEN.EVENT
        truncated = False
        won = False
        floor = 1
        hp = 0
        act = act_floor = card_shop_removals_used = 0
        deck = []

        def step(self, action, _index):
            if action == 2:
                self.screen = SCREEN.RUN_OVER
            return True

    class Model:
        def __call__(self, obs, candidates):
            return torch.tensor([[1.0, -1.0]])

    monkeypatch.setattr(armg_train, "new_run", lambda *args, **kwargs: Run())
    monkeypatch.setattr(armg_train, "build_candidates", lambda rc: (
        np.zeros(2, dtype=np.float32), [(1, 0), (2, 0)], np.zeros((2, 2), dtype=np.float32)))
    ep = armg_train.collect_episode(42, Model(), deterministic=True, max_steps=10)
    assert ep["status"] == "terminated"
    assert ep["steps"] == 4
    assert ep["cycle_recoveries"] == 1


def test_spawn_rollouts_are_stable_across_worker_counts(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    payloads = []
    for workers in (1, 2, 3):
        out = tmp_path / f"workers-{workers}"
        subprocess.run([sys.executable, "-m", "agent.armg_train", "--games", "4",
                        "--batch-size", "4", "--eval-every", "4", "--eval-runs", "1",
                        "--combat", "greedy", "--max-steps", "500", "--workers", str(workers),
                        "--out-dir", str(out)], cwd=repo, check=True, capture_output=True, timeout=90)
        payloads.append(torch.load(out / "latest.pt", map_location="cpu", weights_only=False))
    for payload in payloads:
        payload["progress"].pop("workers")
    left, right = payloads[:2]
    assert right["progress"] == payloads[2]["progress"]
    assert all(torch.equal(right["state_dict"][key], payloads[2]["state_dict"][key])
               for key in right["state_dict"])
    assert left["progress"] == right["progress"]
    assert torch.equal(left["torch_rng_state"], right["torch_rng_state"])
    assert all(torch.equal(left["state_dict"][key], right["state_dict"][key])
               for key in left["state_dict"])


def test_upgrade_and_removal_credit_only_the_scored_action(monkeypatch):
    """U/D are campfire upgrades and shop removals, not any deck change.

    An event or relic that upgrades or removes a card must not score: the
    specified reward credits the action the player chose, and a free event
    upgrade is not a campfire upgrade.
    """
    from agent.common import RACT, SCREEN

    class Run:
        truncated = False
        won = False
        floor = 3
        hp = 10
        act = 0
        act_floor = 3

        def __init__(self):
            self.screen = SCREEN.EVENT
            self.deck = [(1, False, 1, 1), (2, False, 2, 1), (3, False, 3, 1)]
            self.card_shop_removals_used = 0
            self.steps = 0

        def step(self, action, index):
            self.steps += 1
            if self.steps == 1:
                # Event effect: upgrades a card the player never chose to upgrade.
                self.deck[0] = (1, True, 1, 1)
                self.screen = SCREEN.REST
            elif self.steps == 2:
                assert action == int(RACT.REST_UPGRADE)
                self.deck[1] = (2, True, 2, 1)
                self.screen = SCREEN.SHOP
            else:
                assert action == int(RACT.REMOVE_CARD)
                self.card_shop_removals_used += 1
                self.screen = SCREEN.RUN_OVER
            return True

    run = Run()
    monkeypatch.setattr(armg_train, "new_run", lambda *a, **k: run)
    monkeypatch.setattr(armg_train, "build_candidates", lambda rc: (
        np.zeros(ARMG_OBS_DIM, dtype=np.float32),
        [(int(RACT.REST_UPGRADE), 0)] if rc.screen == SCREEN.REST
        else [(int(RACT.REMOVE_CARD), 0)],
        np.zeros((1, ARMG_ACTION_DIM), dtype=np.float32)))
    from agent.armg_ppo import TrajectoryRecorder
    model = armg_train.ArmGActorCritic()
    episode = armg_train.collect_episode(5, model, trajectory=TrajectoryRecorder(model), max_steps=10)
    assert episode["status"] == "terminated", episode["error"]
    components = episode["reward"]
    assert components["campfire_upgrades"] == 1
    assert components["shop_removals"] == 1
    assert components["upgrade_bonus"] == pytest.approx(0.05)
    assert components["removal_bonus"] == pytest.approx(0.02)


def test_truncated_and_error_runs_never_become_training_episodes():
    """A step-limit stop or an exception is not a game over and scores nothing."""
    from agent.armg_ppo import ArmGActorCritic, TrajectoryRecorder, prepare

    model = ArmGActorCritic()
    truncated = armg_train.collect_episode(1, model, combat="greedy", max_steps=20,
                                           trajectory=TrajectoryRecorder(model))
    assert truncated["status"] == "truncated"
    assert truncated["total_reward"] is None
    assert truncated["ppo_records"] == []
    assert truncated["reward"]["floor_reward"] > 0, "components are still reported"
    with pytest.raises(ValueError, match="complete"):
        prepare([truncated])


def test_step_limit_is_reported_as_truncation_not_a_loss():
    from agent.policy import split_seeds
    episode = armg_train.collect_episode(split_seeds("train", 1)[0], None,
                                         combat="greedy", max_steps=3)
    assert episode["status"] == "truncated"
    assert episode["won"] is False
    assert armg_train.summarize([episode])["win_rate"] is None
    assert armg_train.summarize([episode])["truncated"] == 1


def test_reward_components_are_reported_separately_without_double_counting():
    """The Elo term lives at the episode top level, not inside ``reward``."""
    episodes = [{
        "reward": {"floor_reward": 1.0, "elite_bonus": 0.2, "boss_bonus": 0.5,
                   "upgrade_bonus": 0.05, "removal_bonus": 0.02,
                   "campfire_upgrades": 1, "shop_removals": 1, "bosses": 1},
        "deck_elo_bonus": 2.0, "total_reward": 3.77,
        "deck_mean_elo": 1200.0, "deck_elo_missing": 2, "deck_elo_excluded": 3,
    }]
    summary = armg_train._mean_components(episodes)
    assert summary["floor_reward"] == pytest.approx(1.0)
    assert summary["deck_elo_bonus"] == pytest.approx(2.0)
    assert summary["total_reward"] == pytest.approx(3.77)
    # Components and total are independent; the total is not recomputed from
    # the (rounded) per-component means.
    assert (summary["floor_reward"] + summary["elite_bonus"] + summary["boss_bonus"]
            + summary["upgrade_bonus"] + summary["removal_bonus"]
            + summary["deck_elo_bonus"]) == pytest.approx(3.77)
    assert summary["deck_elo_missing"] == 2
    assert summary["deck_elo_excluded"] == 3
    assert summary["campfire_upgrades"] == 1
    assert summary["shop_removals"] == 1
    assert summary["bosses"] == 1
    assert armg_train._mean_components([]) == {}

def test_error_episode_is_logged_and_not_trained(tmp_path, monkeypatch):
    import json
    def episode(seed, model, *, deterministic=False, **kwargs):
        ep = _fake_episode(model, seed, deterministic)
        if not deterministic:
            ep.update(status='error', error='injected failure', total_reward=None, ppo_records=[])
        else:
            assert kwargs['deck_elo'] is not None
        return ep
    monkeypatch.setattr(armg_train, 'collect_episode', episode)
    monkeypatch.setattr(armg_train, 'ppo_update', lambda *a, **kw: pytest.fail('error batch trained'))
    armg_train.train(games=1, batch_size=1, eval_runs=1, out_dir=str(tmp_path), combat='greedy')
    payload = torch.load(tmp_path/'latest.pt', weights_only=False)
    assert payload['progress']['errors'] == 1
    assert payload['progress']['games'] == 1
    record = json.loads((tmp_path/'metrics.jsonl').read_text().splitlines()[-1])
    assert record['errors'] == ['injected failure']
    assert record['validation']['mean_reward'] is not None


@pytest.mark.parametrize('persistent', [False, True])
def test_broken_pool_retries_same_batch_or_saves_before_batch(tmp_path, monkeypatch, persistent):
    import json
    calls = []
    class Pool:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def shutdown(self, **kwargs): pass
        def map(self, fn, tasks, **kwargs):
            calls.append(list(tasks))
            if persistent or len(calls) == 1:
                raise armg_train.BrokenProcessPool('injected worker crash')
            model = armg_train.ArmGActorCritic()
            return [_fake_episode(model, task[0], False) for task in tasks]
    monkeypatch.setattr(armg_train, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(armg_train, 'collect_episode',
                        lambda seed, model, **kw: _fake_episode(model, seed, True))
    kwargs = dict(games=2, batch_size=2, eval_runs=1, out_dir=str(tmp_path), workers=2, combat='greedy')
    if persistent:
        with pytest.raises(armg_train.BrokenProcessPool): armg_train.train(**kwargs)
    else:
        armg_train.train(**kwargs)
    assert len(calls) == 2 and calls[0] == calls[1]
    saved = torch.load(tmp_path/'latest.pt', weights_only=False)
    assert saved['progress']['games'] == (0 if persistent else 2)
    if persistent:
        torch.set_rng_state(saved['torch_rng_state'])
        assert torch.randint(0, 2**31-1, (2,)).tolist() == [t[1] for t in calls[0]]
    records = [json.loads(line) for line in (tmp_path/'worker-events.jsonl').read_text().splitlines()]
    assert records[0]['event'] == 'worker_pool_failure'


def test_cycle_longer_than_old_window_exits(monkeypatch):
    from agent.common import SCREEN
    class Run:
        screen = SCREEN.EVENT
        truncated = won = False
        floor = hp = 1
        act = act_floor = card_shop_removals_used = 0
        deck = []
        phase = 0
        def step(self, action, _index):
            if action == 2:
                self.screen = SCREEN.RUN_OVER
            else:
                self.phase = (self.phase + 1) % 70
            return True
    class Model:
        def __call__(self, obs, candidates): return torch.tensor([[1., -1.]])
    monkeypatch.setattr(armg_train, 'new_run', lambda *a, **kw: Run())
    monkeypatch.setattr(armg_train, 'build_candidates', lambda rc: (
        np.array([rc.phase], dtype=np.float32), [(1, 0), (2, 0)], np.zeros((2, 2), dtype=np.float32)))
    ep = armg_train.collect_episode(42, Model(), deterministic=True, max_steps=300)
    assert ep['status'] == 'terminated' and ep['steps'] == 211
    assert ep['cycle_recoveries'] == 1

def test_best_checkpoint_selects_elo_inclusive_reward_not_floor(tmp_path, monkeypatch):
    validations = 0
    def episode(seed, model, *, deterministic=False, **kwargs):
        nonlocal validations
        ep = _fake_episode(model, seed, deterministic)
        if deterministic:
            assert kwargs['deck_elo'] is not None
            validations += 1
            ep['total_reward'] = 5.0 if validations == 1 else 4.0
            ep['floor'] = 10 if validations == 1 else 20
        return ep
    monkeypatch.setattr(armg_train, 'collect_episode', episode)
    armg_train.train(games=2, batch_size=1, eval_every=1, eval_runs=1,
                     out_dir=str(tmp_path), combat='greedy')
    best = torch.load(tmp_path/'best.pt', weights_only=False)
    assert best['progress']['games'] == 1
    assert best['progress']['best_reward'] == 5.0
    assert best['settings']['best_metric'] == 'mean_reward'
