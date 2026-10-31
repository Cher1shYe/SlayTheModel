"""A simulator safety cutoff must not be labeled as a game loss."""

import numpy as np
import torch

from agent.common import OUTCOME, SCREEN, sim
from agent.policy import summarize


def test_win_rate_excludes_truncated_and_errors():
    rows = [
        {"status": status, "won": won, "act": 1, "floor": 3, "hp_loss": 5}
        for status, won in [("terminated", True), ("terminated", False),
                            ("truncated", False), ("error", False)]
    ]
    result = summarize(rows)
    assert result["completed_runs"] == 2
    assert result["win_rate"] == 0.5
    assert result["truncated"] == 1 and result["errors"] == 1
    unknown = summarize(rows[2:])
    assert unknown["completed_runs"] == 0
    assert unknown["win_rate"] is None and unknown["win_ci95"] is None


class _TruncatedBattle:
    def __init__(self):
        self.outcome = OUTCOME.UNDECIDED
        self.player_hp = 40
        self.player_max_hp = 80

    def greedy_action(self, *_):
        return (int(sim.ActionType.END_TURN), 0, 0, 0)

    def search_priors(self, *_, **kwargs):
        actions = [(0, 0, 0, 0), (1, 0, 0, 0)]
        return actions, [1, 1], [0.5, 0.5], 2


class _TruncatedRun:
    def __init__(self):
        self.screen = SCREEN.COMBAT
        self.battle = _TruncatedBattle()
        self.truncated = False
        self.won = False
        self.floor = 5
        self.hp = 40
        self.max_hp = 80

    def step_combat(self, *_):
        self.battle.outcome = OUTCOME.TRUNCATED
        self.truncated = True
        self.screen = SCREEN.RUN_OVER
        return True


def test_selfplay_drops_truncated_combat_records(monkeypatch):
    import agent.selfplay as selfplay

    class Model:
        def policy_value(self, *_):
            return torch.zeros((1, 2)), torch.zeros((1, 1))

    monkeypatch.setattr(selfplay, "new_run", lambda *_: _TruncatedRun())
    monkeypatch.setattr(selfplay, "combat_action_arrays",
                        lambda _: ([(0, 0, 0, 0), (1, 0, 0, 0)],
                                   np.zeros((2, sim.ACTION_FEAT_DIM), dtype=np.float32)))
    monkeypatch.setattr(selfplay, "public_combat_observation",
                        lambda _: np.zeros(sim.PUBLIC_COMBAT_OBS_DIM, dtype=np.float32))
    result = selfplay.play_episode(1, Model(), simulations=2, sample=False)
    assert result["status"] == "truncated"
    assert result["records"] == [] and not result["won"]


def test_card_training_drops_truncated_run(monkeypatch):
    import agent.card_train as card_train

    monkeypatch.setattr(card_train, "new_run", lambda *_: _TruncatedRun())
    result = card_train.collect_episode(1, None)
    assert result["status"] == "truncated"
    assert result["records"] == [] and result["return"] == 0.0
