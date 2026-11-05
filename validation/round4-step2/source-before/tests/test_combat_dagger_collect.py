import json

import numpy as np
import torch

from agent import combat_dagger_collect as collect
from agent.common import ACTION_FEAT_DIM, OUTCOME, PUBLIC_COMBAT_OBS_DIM, SCREEN


class FakeBattle:
    def __init__(self, teacher_action=(1, 0, 0, 0)):
        self.teacher_action = teacher_action
        self.outcome = OUTCOME.UNDECIDED
        self.player_hp = 25
        self.player_max_hp = 50
        self.calls = []

    def mcts(self, simulations, c, seed, resample, greedy, epsilon):
        self.calls.append((simulations, resample))
        return [self.teacher_action], simulations, True


class FakeRun:
    def __init__(self, second_truncated=False, teacher_action=(1, 0, 0, 0)):
        self.screen = SCREEN.COMBAT
        self.battle = FakeBattle(teacher_action)
        self.second_truncated = second_truncated
        self.finished = 0
        self.truncated = False
        self.won = False
        self.floor = 1
        self.hp = 25
        self.combat_is_boss = False
        self.battle_actions = []

    def state_hash(self):
        return self.finished + 1

    def step_combat(self, *action):
        self.battle_actions.append(tuple(action))
        self.finished += 1
        self.battle.outcome = (OUTCOME.TRUNCATED if self.finished == 2 else OUTCOME.PLAYER_VICTORY)
        self.screen = SCREEN.EVENT if self.finished == 1 else SCREEN.RUN_OVER
        self.truncated = self.finished == 2
        return True

    def step(self, *_):
        if self.second_truncated:
            self.screen = SCREEN.COMBAT
            self.battle = FakeBattle()
        else:
            self.screen = SCREEN.RUN_OVER
        return True


def install_fake(monkeypatch, rc):
    monkeypatch.setattr(collect, "new_run", lambda *_: rc)
    monkeypatch.setattr(collect, "build_candidates", lambda _: (
        np.zeros(2, dtype=np.float32), [(12, 0)], np.zeros((1, 2), dtype=np.float32)))
    actions = [(0, 0, 0, 0), (1, 0, 0, 0)]
    monkeypatch.setattr(collect, "combat_action_arrays", lambda _: (
        actions, np.zeros((2, ACTION_FEAT_DIM), dtype=np.float32)))
    monkeypatch.setattr(collect, "public_combat_observation", lambda _: np.zeros(PUBLIC_COMBAT_OBS_DIM, dtype=np.float32))
    return actions


def test_student_executes_student_action_and_labels_exact_teacher(tmp_path, monkeypatch):
    rc = FakeRun()
    actions = install_fake(monkeypatch, rc)
    policy = lambda _s, _a: torch.tensor([[3.0, 1.0]])
    result = collect.collect_episode(42, policy, object(), teacher_sims=7,
                                     resample_hidden=True, output_dir=tmp_path,
                                     metadata={"policy_sha256": "policy", "armg_sha256": "armg"})
    assert result["status"] == "terminated"
    assert rc.battle_actions == [actions[0]]
    assert rc.battle.calls == [(7, True)]
    assert result["teacher_simulations"] == 7 and result["battles"] == 1
    with np.load(result["shards"][0]["path"], allow_pickle=False) as data:
        assert data["labels"].tolist() == [1]
        assert data["action_ids"].tolist() == [list(a) for a in actions]
        assert data["offsets"].tolist() == [0, 2]
        assert data["wins"].tolist() == [1.0] and data["hp"].tolist() == [0.5]
        meta = json.loads(str(data["metadata_json"]))
        assert meta["policy_sha256"] == "policy" and meta["seed"] == 42
        assert meta["teacher_sims"] == 7 and meta["resample_hidden"]


def test_teacher_mismatch_skips_policy_label_but_keeps_value(tmp_path, monkeypatch):
    rc = FakeRun(teacher_action=(8, 0, 0, 0))
    install_fake(monkeypatch, rc)
    policy = lambda _s, _a: torch.tensor([[2.0, 1.0]])
    result = collect.collect_episode(43, policy, object(), teacher_sims=2, output_dir=tmp_path)
    assert result["status"] == "terminated" and result["teacher_unmatched"] == 1
    with np.load(result["shards"][0]["path"], allow_pickle=False) as data:
        assert data["labels"].tolist() == [-1] and data["hp"].tolist() == [0.5]


def test_later_battle_truncation_discards_entire_episode(tmp_path, monkeypatch):
    rc = FakeRun(second_truncated=True)
    install_fake(monkeypatch, rc)
    policy = lambda _s, _a: torch.tensor([[3.0, 1.0]])
    result = collect.collect_episode(44, policy, object(), teacher_sims=2, output_dir=tmp_path)
    assert result["status"] == "truncated" and result["shards"] == []
    assert list(tmp_path.iterdir()) == []


def test_pure_evaluation_requires_no_teacher_or_data_files(monkeypatch):
    rc = FakeRun()
    install_fake(monkeypatch, rc)
    policy = lambda _s, _a: torch.tensor([[3.0, 1.0]])
    result = collect.collect_episode(45, policy, object(), teacher_sims=2,
                                     collect_labels=False, output_dir=None)
    assert result["status"] == "terminated" and result["shards"] == []
    assert result["teacher_searches"] == 0 and rc.battle.calls == []
