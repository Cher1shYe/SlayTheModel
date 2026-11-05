import pytest
from deployment import replay_final_boss as replay


def test_selects_wins_and_losses_on_final_boss_but_not_earlier_rooms():
    records = [{'floor': 48, 'won': True}, {'floor': 48, 'won': False},
               {'floor': 47, 'won': False}, {'floor': 33, 'won': False}]
    assert replay._boss_cases(records) == records[:2]


def test_retry_only_uses_zero_weight_after_reproducing_original(monkeypatch):
    calls = []
    def fake(meta, weight):
        calls.append(weight)
        return {'won': True, 'floor': 48, 'hp': 12, 'final_steps': 8, 'final_decisions': 5}
    monkeypatch.setattr(replay, '_retry', fake)
    meta = {'original': {'won': True, 'floor': 48, 'hp': 12, 'steps': 107, 'mcts_searches': 15}, 'step_at_boss': 100, 'decisions_before_boss': 10}
    assert replay._verify_and_retry(meta)['verified_old_weight']
    assert calls == [4.0, 0.0]


def test_retry_refuses_mismatched_old_result(monkeypatch):
    calls = []
    def fake(meta, weight):
        calls.append(weight)
        return {'won': False, 'floor': 48, 'hp': 0, 'final_steps': 8, 'final_decisions': 5}
    monkeypatch.setattr(replay, '_retry', fake)
    meta = {'original': {'won': True, 'floor': 48, 'hp': 12, 'steps': 107, 'mcts_searches': 15}, 'step_at_boss': 100, 'decisions_before_boss': 10}
    with pytest.raises(RuntimeError, match='differs from original boss'):
        replay._verify_and_retry(meta)
    assert calls == [4.0]
