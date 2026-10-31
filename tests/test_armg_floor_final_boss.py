"""Final-boss potion handling is per-search and never leaks between fights."""
from types import SimpleNamespace

import pytest

from agent.armg_floor_schedule import FloorMctsController, is_final_boss


@pytest.mark.parametrize('act,boss,row,length,second,expected', [
    (0, False, 3, 16, -1, False),
    (0, True, 16, 16, -1, False),
    (1, True, 15, 15, -1, False),
    (2, False, 14, 14, -1, False),
    (2, True, 14, 14, -1, True),
    (2, True, 14, 14, 123, False),
    (2, True, 15, 14, 123, True),
])
def test_final_boss_by_act_map_and_actual_boss(act, boss, row, length, second, expected):
    rc = SimpleNamespace(act=act, combat_is_boss=boss, current_row=row,
                         map_length=length, second_boss_encounter=second)
    assert is_final_boss(rc) is expected


def test_potion_override_only_last_boss_and_reset():
    class Battle:
        def __init__(self): self.calls = []
        def legal_actions(self): return [(0, 0, 0, 0), (1, 0, 0, 0)]
        def mcts(self, budget, c, seed, hidden, greedy, epsilon, **kwargs):
            self.calls.append(kwargs)
            return [(1, 0, 0, 0)], budget, True

    battle = Battle()
    controller = FloorMctsController(123)
    for act, row, second, boss in [(2, 14, 123, True), (2, 15, 123, True),
                                   (0, 4, -1, False)]:
        rc = SimpleNamespace(act=act, combat_is_boss=boss, current_row=row,
                             map_length=14, second_boss_encounter=second)
        controller.prepare_combat(rc, 1)
        budget = controller.budget_for_context(8, False, boss)
        controller.plan(battle, 1, 'mcts-oracle', budget, .05, boss)
    assert battle.calls == [{}, {'potion_weight': 0.0}, {}]


def test_training_worker_wires_final_boss_callback(monkeypatch, tmp_path):
    import torch
    from deployment import train_armg_floor_prior_rl as trainer

    class Model:
        def eval(self): return self
        def load_state_dict(self, _value): pass

    def collect(seed, model, **kwargs):
        callback = kwargs['before_combat']
        rc = SimpleNamespace(act=2, combat_is_boss=True, current_row=14,
                             map_length=14, second_boss_encounter=-1)
        callback(rc, 1)
        assert trainer.base._mcts_plan.__self__.potion_weight == 0.0
        return {'seed': seed, 'status': 'terminated', 'mcts_searches': 0,
                'mcts_simulations': 0}

    monkeypatch.setattr(trainer, '_worker_model', None)
    monkeypatch.setattr(trainer, '_worker_version', None)
    monkeypatch.setattr(trainer, 'ArmGScorer', Model)
    monkeypatch.setattr(torch, 'load', lambda *_a, **_kw: {})
    monkeypatch.setattr(trainer.base, 'collect_episode', collect)
    task = (1, 2, 3, 4, 'dummy', True, 2000, 200, 1000, 2000, 5000, str(tmp_path), 'oracle')
    assert trainer._play(task)['status'] == 'terminated'
