from types import SimpleNamespace

import pytest
import torch

from deployment import train_armg_a10_boss_rl as trainer
from agent import armg_train as base
from agent.common import OUTCOME, SCREEN


@pytest.mark.parametrize('wins,expected', [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)])
def test_rewards_use_actual_boss_wins_not_floor(wins, expected):
    events = [{'act': a, 'final_boss': final} for a, final in
              [(1, False), (2, False), (3, False), (3, True)]][:wins]
    ep = {'status': 'terminated', 'floor': 49, 'won': wins == 4, 'boss_wins': events}
    assert trainer.episode_reward(ep, 'boss-count') == expected
    assert trainer.episode_reward(ep, 'act-count') == min(wins, 2) + (wins == 4)


def test_prior_schedule_uses_training_counter_and_clamps():
    assert trainer.prior_strength(0) == .2
    assert trainer.prior_strength(32) == pytest.approx(.19936)
    assert trainer.prior_strength(5000) == .1
    assert trainer.prior_strength(10000) == 0
    assert trainer.prior_strength(12000) == 0


@pytest.mark.parametrize('act', [1, 2, 3])
def test_floor20_flat_elite_reward_is_independent_of_act(act):
    ep = {'status': 'terminated', 'floor': 40, 'boss_wins': [{}, {}],
          'elite_wins': [{'act': act}, {'act': act}]}
    assert trainer.episode_reward(ep, 'floor20-boss-elite01') == pytest.approx(5.2)
    summary = trainer.reward_summary([ep], 'floor20-boss-elite01')
    assert summary['mean_floor_reward'] == 2.0
    assert summary['mean_boss_bonus'] == 3.0
    assert summary['mean_elite_bonus'] == pytest.approx(.2)
    ep.update(floor=49, boss_wins=[{}] * 4, elite_wins=[])
    assert trainer.episode_reward(ep, 'floor20-boss-elite01') == pytest.approx(12.45)


@pytest.mark.parametrize('bosses,bonus', [(0, 0), (1, 1), (2, 3), (3, 6), (4, 10)])
def test_floor_and_cumulative_boss_and_per_elite_rewards(bosses, bonus):
    ep = {'status': 'terminated', 'floor': 49, 'won': True,
          'boss_wins': [{}] * bosses,
          'elite_wins': [{'act': 1}, {'act': 2}, {'act': 2}, {'act': 3}]}
    assert trainer.episode_reward(ep) == pytest.approx(.98 + bonus + 1.2)
    summary = trainer.reward_summary([ep], 'floor-boss-elite')
    assert summary['mean_elite_bonus'] == pytest.approx(1.2)
    assert 'reward_counts' not in summary
    ep['elite_wins'] = []
    assert trainer.episode_reward(ep) == pytest.approx(.98 + bonus)


@pytest.mark.parametrize('outcome,count', [(OUTCOME.PLAYER_VICTORY, 1), (OUTCOME.PLAYER_LOSS, 0), (OUTCOME.TRUNCATED, 0)])
def test_elite_reward_records_actual_win_once(monkeypatch, outcome, count):
    class Run:
        screen = SCREEN.COMBAT
        combat_is_boss = False
        act = 1
        floor = 25
        hp = 10
        won = False
        battle = SimpleNamespace(outcome=OUTCOME.UNDECIDED)
        steps = 0
        def observe_public(self): return [0] * 8 + [1, 1, 0]
        def step_combat(self, *action):
            self.steps += 1
            if self.steps == 2:
                self.screen = SCREEN.RUN_OVER
                self.battle.outcome = outcome
            return True
    rc = Run()
    monkeypatch.setattr(base, 'new_run', lambda *args: rc)
    monkeypatch.setattr(base, '_combat_action', lambda *args: (0, 0, 0, 0))
    monkeypatch.setattr(base, 'completed_run_status', lambda rc: 'terminated')
    ep = base.collect_episode(1, None, combat='greedy', track_elite_wins=True)
    assert len(ep['elite_wins']) == count
    if count:
        assert ep['elite_wins'] == [{'act': 2, 'floor': 25}]


@pytest.mark.parametrize('victory', [False, True])
def test_collector_counts_boss_victory_only_on_combat_exit(monkeypatch, victory):
    class Run:
        screen = SCREEN.COMBAT
        combat_is_boss = True
        act = 2
        floor = 49
        map_length = 14
        current_row = 15
        second_boss_encounter = 123
        hp = 10
        won = False
        battle = SimpleNamespace(outcome=OUTCOME.UNDECIDED)
        def step_combat(self, *action):
            self.screen = SCREEN.RUN_OVER
            self.won = victory
            self.battle.outcome = OUTCOME.PLAYER_VICTORY if victory else OUTCOME.PLAYER_LOSS
            return True
    rc = Run()
    monkeypatch.setattr(base, 'new_run', lambda seed, ascension: rc)
    monkeypatch.setattr(base, '_combat_action', lambda *args: (0, 0, 0, 0))
    monkeypatch.setattr(base, 'completed_run_status', lambda rc: 'terminated')
    ep = base.collect_episode(1, None, combat='greedy', ascension=10, track_boss_wins=True)
    assert len(ep['boss_wins']) == int(victory)
    if victory:
        assert ep['boss_wins'][0] == {'act': 3, 'floor': 49, 'final_boss': True}


def test_fresh_initial_state_and_resume(tmp_path, monkeypatch):
    class StopBeforeWorkers(Exception): pass
    def stop(*args, **kwargs): raise StopBeforeWorkers()
    monkeypatch.setattr(trainer, 'ProcessPoolExecutor', stop)
    out = tmp_path / 'fresh'
    kwargs = dict(out_dir=out, data_dir='runs/armg_spire_wr50_prior_20261030/data',
                  games=32)
    with pytest.raises(StopBeforeWorkers):
        trainer.train(**kwargs)
    initial = torch.load(out / 'initial.pt', weights_only=False)
    assert initial['optimizer_state_dict']['state'] == {}
    assert initial['progress']['baseline'] is None
    assert initial['progress']['games'] == 0
    assert initial['progress']['initialization']['mode'] == 'random'
    assert initial['settings']['ascension'] == 10
    assert initial['settings']['combat'] == 'mcts-oracle'
    assert initial['settings']['combat_policy_prior'] is False
    assert initial['settings']['combat_budget_start'] == 5000
    assert initial['settings']['combat_budget_per_floor'] == 500
    with pytest.raises(StopBeforeWorkers):
        trainer.train(**kwargs, resume=out / 'latest.pt')
    with pytest.raises(ValueError, match='settings differ'):
        trainer.train(**kwargs, resume=out / 'latest.pt', reward_mode='act-count')
