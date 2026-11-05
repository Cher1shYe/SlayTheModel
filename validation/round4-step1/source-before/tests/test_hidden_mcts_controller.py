import pytest

from agent.hidden_mcts_controller import HiddenMctsController


class Battle:
    def __init__(self, actions=None, done=None):
        self.actions = actions or [(0, 0, 0, 1), (1, 0, 0, 0)]
        self.done = done
        self.calls = []

    def legal_actions(self):
        return self.actions

    def mcts(self, simulations, c, seed, resample, greedy, epsilon):
        self.calls.append((simulations, c, seed, resample, greedy, epsilon))
        return [self.actions[1], self.actions[0]], self.done or simulations, True


def test_hidden_mcts_boss_budget_and_game_seed_independent():
    a, b = Battle(), Battle()
    first = HiddenMctsController(123)
    second = HiddenMctsController(123)
    assert first.plan(a, 111, "mcts-resampled", 2000, .05, False) == ([a.actions[1]], 2000)
    assert second.plan(b, 999999, "mcts-resampled", 2000, .05, False) == ([b.actions[1]], 2000)
    assert a.calls == b.calls
    assert a.calls[0][2:5] == (123, True, False)
    assert first.plan(a, 222, "mcts-resampled", 2000, .05, True) == ([a.actions[1]], 10000)
    assert a.calls[-1][2] == (123 + 7919)
    assert (first.normal_decisions, first.boss_decisions) == (1, 1)
    assert (first.normal_simulations, first.boss_simulations_completed) == (2000, 10000)


def test_forced_action_skips_search():
    b = Battle(actions=[(1, 0, 0, 0)])
    c = HiddenMctsController(123)
    assert c.plan(b, 1, "mcts-resampled", 2000, .05, True) == (b.actions, 0)
    assert not b.calls and c.decisions == 0


def test_incomplete_budget_rejected():
    with pytest.raises(RuntimeError, match="incomplete"):
        HiddenMctsController(123).plan(Battle(done=3), 1, "mcts-resampled", 2000, .05, False)

