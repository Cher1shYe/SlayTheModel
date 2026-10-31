"""Budget and information-mode contracts for the prepared oracle controller."""

import hashlib
import json
import math

import pytest

from agent.hidden_mcts_controller import HiddenMctsController


class FakeBattle:
    def __init__(self, actions=None, completed=None, returned=None):
        self.actions = actions if actions is not None else [(0, 0, 0, 1), (1, 0, 0, 0)]
        self.completed = completed
        self.returned = returned
        self.calls = []

    def legal_actions(self):
        return self.actions

    def mcts(self, budget, c, seed, resample_hidden, greedy_rollout, epsilon):
        self.calls.append((budget, c, seed, resample_hidden, greedy_rollout, epsilon))
        path = self.returned if self.returned is not None else [self.actions[1], self.actions[0]]
        return path, budget if self.completed is None else self.completed, True


def test_oracle_budget_information_and_no_cached_path():
    battle = FakeBattle()
    controller = HiddenMctsController(123, mode="oracle")

    assert controller.plan(battle, 999, "mcts-oracle", 2000, .05, False) == ([battle.actions[1]], 2000)
    # Even though the previous search returned a second valid action, search again.
    assert controller.plan(battle, 555, "mcts-oracle", 2000, .05, True) == ([battle.actions[1]], 10000)
    assert [x[0] for x in battle.calls] == [2000, 10000]
    assert [x[2] for x in battle.calls] == [123, 123 + 7919]
    assert all(x[3:5] == (False, False) for x in battle.calls)
    assert all(x[1] == pytest.approx(3 * math.sqrt(2)) for x in battle.calls)
    assert (controller.normal_decisions, controller.boss_decisions) == (1, 1)
    assert (controller.normal_simulations, controller.boss_simulations_completed) == (2000, 10000)


def test_oracle_rng_independent_of_game_seed():
    a, b = FakeBattle(), FakeBattle()
    first, second = HiddenMctsController(17, mode="oracle"), HiddenMctsController(17, mode="oracle")
    assert first.plan(a, 111, "mcts-oracle", 20, .05, False) == second.plan(b, 999999, "mcts-oracle", 20, .05, False)
    assert a.calls == b.calls


def test_oracle_forced_action_and_invalid_results():
    forced = FakeBattle(actions=[(1, 0, 0, 0)])
    controller = HiddenMctsController(1, mode="oracle")
    assert controller.plan(forced, 11, "mcts-oracle", 2000, .05, True) == (forced.actions, 0)
    assert forced.calls == []
    with pytest.raises(RuntimeError, match="incomplete"):
        HiddenMctsController(1, mode="oracle").plan(FakeBattle(completed=19), 11, "mcts-oracle", 20, .05, False)
    with pytest.raises(RuntimeError):
        HiddenMctsController(1, mode="oracle").plan(FakeBattle(returned=[(9, 0, 0, 0)]), 11, "mcts-oracle", 20, .05, False)


@pytest.mark.parametrize("mode", ["oracle", "hidden"])
def test_pipeline_passes_mode_to_both_stages(tmp_path, monkeypatch, mode):
    """Mock both child processes so no sampling, training, or extension loads occur."""
    import torch
    from deployment import run_armg_prior_pipeline as pipeline

    data = tmp_path / "data"
    data.mkdir()
    (data / "manifest.json").write_text("{}", encoding="utf-8")
    extension = tmp_path / "sim.pyd"
    extension.write_bytes(b"test")
    monkeypatch.setenv("STS2_PRIOR_PYD", str(extension))
    monkeypatch.setattr(torch, "load", lambda *a, **kw: {
        "progress": {"initialization": "random"},
        "settings": {"information": mode, "simulations_per_decision": 4,
                     "boss_simulations_per_decision": 7, "path_cache": "none"},
    })
    commands = []

    class CompletedProcess:
        pid = 123

        def __init__(self, cmd, **kwargs):
            from pathlib import Path
            commands.append(cmd)
            stage_out = Path(cmd[cmd.index("--out-dir") + 1])
            stage_out.mkdir()
            if "agent.armg_prior_train" in cmd:
                (stage_out / "prior.pt").write_bytes(b"stub")
                result = {"state": "completed", "stage": "completed", "games_completed": 6,
                          "terminated": 6, "errors": 0, "truncated": 0}
            else:
                (stage_out / "latest.pt").write_bytes(b"stub")
                result = {"state": "completed", "games": 2}
            (stage_out / "progress.json").write_text(json.dumps(result), encoding="utf-8")

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(pipeline.subprocess, "Popen", CompletedProcess)
    kwargs = {} if mode == "oracle" else {"combat_mode": "hidden"}
    out = tmp_path / "run"
    assert pipeline.run(out, data, workers=2, simulations=4, boss_simulations=7,
                        prior_games=6, rl_games=2, eval_runs=2, **kwargs) == 0
    assert len(commands) == 2
    assert all(command[command.index("--combat-mode") + 1] == mode for command in commands)
    progress = json.loads((out / "pipeline_progress.json").read_text(encoding="utf-8"))
    assert progress["state"] == "completed"
    assert progress["combat_mode"] == mode
    assert progress["path_cache"] == "none"


@pytest.mark.parametrize("field,wrong", [
    ("information", "hidden"),
    ("simulations_per_decision", 1999),
    ("boss_simulations_per_decision", 9999),
    ("path_cache", "legacy"),
    ("simulator_sha256", "wrong"),
])
def test_rl_rejects_incompatible_prior_before_training(tmp_path, monkeypatch, field, wrong):
    import torch
    from deployment import train_armg_hidden_mcts as trainer

    extension = tmp_path / "sim.pyd"
    extension.write_bytes(b"test extension")
    checkpoint = tmp_path / "prior.pt"
    checkpoint.write_bytes(b"test checkpoint")
    monkeypatch.setattr(trainer.extension_loader, "_extension", str(extension))
    prior = {
        "progress": {"stage": "prior_complete", "initialization": "random"},
        "settings": {"information": "oracle", "simulations_per_decision": 2000,
                     "boss_simulations_per_decision": 10000, "path_cache": "none",
                     "simulator_sha256": hashlib.sha256(extension.read_bytes()).hexdigest()},
    }
    prior["settings"][field] = wrong
    monkeypatch.setattr(torch, "load", lambda *a, **kw: prior)
    out = tmp_path / "must_not_exist"
    with pytest.raises(ValueError, match="prior checkpoint does not match"):
        trainer.train(init_checkpoint=checkpoint, out_dir=out, combat_mode="oracle")
    assert not out.exists()
