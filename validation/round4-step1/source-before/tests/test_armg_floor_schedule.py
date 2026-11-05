"""No training: check floor schedules, prior targets and combat wiring."""
import math
from pathlib import Path

import numpy as np
import pytest

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, _CARD_OFF
from agent.armg_floor_schedule import (FloorCardSkipPrior, FloorMctsController,
                                       combat_budget, skip_elo_from_obs)
from agent.armg_site_prior_loss import CardSkipPrior
from agent.common import RACT, SCREEN

DATA = Path('runs/armg_spire_wr50_prior_20261030/data')


@pytest.mark.parametrize('floor,budget,elo', [(0, 2000, 1350), (1, 2000, 1350),
                                            (2, 2200, 1360), (8, 3400, 1420),
                                            (17, 5200, 1510), (49, 11600, 1830)])
def test_schedules(floor, budget, elo):
    obs = np.zeros(ARMG_OBS_DIM, np.float32)
    obs[3] = floor / 49
    assert combat_budget(floor) == budget
    assert skip_elo_from_obs(obs) == elo


def test_oracle_controller_uses_floor_and_battle_kind_and_no_path_cache():
    class Battle:
        def __init__(self):
            self.calls = []
        def legal_actions(self):
            return [(0, 0, 0, 0), (1, 0, 0, 0)]
        def mcts(self, budget, c, seed, hidden, greedy, epsilon):
            self.calls.append((budget, hidden))
            return [(1, 0, 0, 0), (0, 0, 0, 0)], budget, True
    battle = Battle()
    c = FloorMctsController(123)
    for floor, elite, boss in [(1, False, False), (8, True, False), (8, False, True), (8, False, True)]:
        budget = c.budget_for_context(floor, elite, boss)
        assert c.plan(battle, 17, 'mcts-oracle', budget, .05, boss) == ([(1, 0, 0, 0)], budget)
    assert battle.calls == [(2000, False), (4400, False), (5400, False), (5400, False)]
    assert c.floor_decisions == {(1, False, False): 1, (8, True, False): 1, (8, False, True): 2}
    assert c.elite_decisions == 1 and c.elite_simulations == 4400


def test_cannot_assign_both_elite_and_boss():
    with pytest.raises(ValueError):
        combat_budget(8, elite=True, boss=True)


def test_prior_uses_global_floor_while_default_remains_by_act():
    if not DATA.exists():
        pytest.skip('real website snapshot unavailable')
    new = FloorCardSkipPrior(DATA)
    old = CardSkipPrior(DATA)
    card = next(i for i, name in new.site.card_ids.items()
                if new.pools.get(name) == 'ironclad' and new.score(new.site.card_row(i))[1])
    obs = np.zeros(ARMG_OBS_DIM, np.float32)
    obs[4] = 1 / 3
    obs[38 + int(SCREEN.CARD_REWARD)] = 1
    features = np.zeros((2, ARMG_ACTION_DIM), np.float32)
    features[0, int(RACT.SKIP_CARD)] = 1
    features[1, int(RACT.TAKE_CARD)] = 1
    features[1, _CARD_OFF + card] = 1
    record = (obs, features, 0)
    def odds(prior, floor):
        obs[3] = floor / 49
        p = prior.target(record)['target']
        return float(p[0] / p[1])
    assert odds(new, 2) / odds(new, 1) == pytest.approx(math.exp(10*math.log(10)/800), rel=1e-6)
    assert odds(new, 8) / odds(new, 1) == pytest.approx(math.exp(70*math.log(10)/800), rel=1e-6)
    assert odds(old, 8) == pytest.approx(odds(old, 1))


def test_collect_passes_actual_floor_to_search(monkeypatch):
    import agent.armg_train as train
    class Run:
        floor, hp, won, truncated = 8, 1, False, False
        screen = SCREEN.COMBAT
        combat_is_boss = True
        class Battle:
            def legal_actions(self):
                return [(1, 0, 0, 0), (2, 0, 0, 0)]
        battle = Battle()
        def step_combat(self, *args):
            self.screen = SCREEN.RUN_OVER
            return True
    monkeypatch.setattr(train, 'new_run', lambda *args: Run())
    seen = []
    def plan(battle, seed, combat, simulations, epsilon, is_boss):
        seen.append((simulations, is_boss))
        return [(1, 0, 0, 0)], simulations
    monkeypatch.setattr(train, '_mcts_plan', plan)
    result = train.collect_episode(1, None, combat_budget_by_floor=combat_budget)
    assert result['status'] == 'terminated'
    assert seen == [(3400, True)]


@pytest.mark.parametrize('elite,boss,expected', [(False, False, 3400), (True, False, 4400),
                                                  (False, True, 5400)])
def test_collect_uses_public_combat_kind(monkeypatch, elite, boss, expected):
    import agent.armg_train as train
    class Run:
        floor, hp, won, truncated = 8, 1, False, False
        screen = SCREEN.COMBAT
        combat_is_boss = boss
        combat_is_elite = elite
        class Battle:
            def legal_actions(self):
                return [(1, 0, 0, 0), (2, 0, 0, 0)]
        battle = Battle()
        def observe_public(self):
            obs = [0] * 11
            obs[8:11] = [1, int(elite), int(boss)]
            return obs
        def step_combat(self, *args):
            self.screen = SCREEN.RUN_OVER
            return True
    monkeypatch.setattr(train, 'new_run', lambda *args: Run())
    seen = []
    def plan(battle, seed, combat, simulations, epsilon, is_boss):
        seen.append((simulations, is_boss))
        return [(1, 0, 0, 0)], simulations
    monkeypatch.setattr(train, '_mcts_plan', plan)
    result = train.collect_episode(1, None, combat_budget_by_context=lambda floor, e, b: combat_budget(floor, elite=e, boss=b))
    assert result['status'] == 'terminated'
    assert seen == [(expected, boss)]


def test_real_checkpoint_continues_optimizer_and_rng():
    import random
    import torch
    from agent.armg import ArmGScorer
    from deployment.train_armg_floor_prior_rl import _restore_continuation

    source = Path('runs/armg_ironclad_skip_site_rl_20261030/train/latest.pt')
    if not source.exists():
        pytest.skip('source checkpoint unavailable')
    checkpoint = torch.load(source, map_location='cpu', weights_only=False)
    model = ArmGScorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-4)
    _restore_continuation(checkpoint, model, optimizer)
    assert all(torch.equal(model.state_dict()[k], v) for k, v in checkpoint['state_dict'].items())
    saved_optim = checkpoint['optimizer_state_dict']
    restored_optim = optimizer.state_dict()
    assert saved_optim['param_groups'] == restored_optim['param_groups']
    assert saved_optim['state'].keys() == restored_optim['state'].keys()
    for key, value in saved_optim['state'].items():
        assert all(torch.equal(value[name], restored_optim['state'][key][name]) for name in value)
    assert torch.equal(torch.get_rng_state(), checkpoint['torch_rng_state'])
    assert random.getstate() == checkpoint['python_rng_state']
    actual_numpy, expected_numpy = np.random.get_state(), checkpoint['numpy_rng_state']
    assert actual_numpy[0] == expected_numpy[0] and np.array_equal(actual_numpy[1], expected_numpy[1])
    assert actual_numpy[2:] == expected_numpy[2:]
    assert checkpoint['progress']['games'] == 640
    assert checkpoint['progress']['baseline'] is not None


def test_simulator_migration_requires_matching_explicit_hashes_and_strict_settings(tmp_path):
    import torch
    from agent.armg import ArmGScorer
    from agent.armg_train import _save, _restore
    from deployment.train_armg_floor_prior_rl import _simulator_resume_settings

    old, new = 'a' * 64, 'b' * 64
    old_settings = {'simulator_sha256': old, 'workers': 8, 'train_seed_offset': 0,
                    'need_rules': False, 'relic_rules': False}
    new_settings = {**old_settings, 'simulator_sha256': new}
    previous = {'settings': {'simulator_sha256': old}}
    model = ArmGScorer()
    optimizer = torch.optim.Adam(model.parameters())
    path = tmp_path / 'latest.pt'
    _save(path, model, optimizer, {'games': 608}, old_settings)
    resumed = torch.load(path, map_location='cpu', weights_only=False)
    with pytest.raises(ValueError, match='both simulator migration hashes'):
        _simulator_resume_settings(previous, resumed, new_settings, None, None)
    with pytest.raises(ValueError, match='do not match'):
        _simulator_resume_settings(previous, resumed, new_settings, old, 'c' * 64)
    initial_settings, changed = _simulator_resume_settings(previous, None, new_settings, old, new)
    assert initial_settings == new_settings and not changed
    with pytest.raises(ValueError, match='do not match'):
        _simulator_resume_settings(previous, None, new_settings, 'c' * 64, new)
    restore_settings, changed = _simulator_resume_settings(previous, resumed, new_settings, old, new)
    assert changed and restore_settings == old_settings
    assert _restore(str(path), model, optimizer, restore_settings)['games'] == 608
    with pytest.raises(ValueError, match='settings differ'):
        _restore(str(path), model, optimizer, {**restore_settings, 'workers': 4})
    migrated = {'settings': new_settings,
                'progress': {'games': 608, 'simulator_changes': [{'from': old, 'to': new}]}}
    _, changed = _simulator_resume_settings(previous, migrated, new_settings, None, None)
    assert not changed
    migrated['progress']['simulator_changes'] = []
    with pytest.raises(ValueError, match='both simulator migration hashes'):
        _simulator_resume_settings(previous, migrated, new_settings, None, None)


def test_training_config_write_failure_does_not_hide_error(tmp_path, monkeypatch):
    from deployment import train_armg_floor_prior_rl as trainer
    config = tmp_path / 'config.json'
    config.write_text('old', encoding='utf-8')
    def fail_replace(*args):
        raise PermissionError('locked')
    monkeypatch.setattr(trainer.os, 'replace', fail_replace)
    with pytest.raises(PermissionError, match='locked'):
        trainer._atomic_json(config, {'simulator_sha256': 'new'}, strict=True)
    assert config.read_text(encoding='utf-8') == 'old'
    assert not (tmp_path / 'config.json.tmp').exists()


def test_real_run_preflight_without_launching_workers(tmp_path, monkeypatch):
    import json
    from deployment import train_armg_floor_prior_rl as trainer
    monkeypatch.setattr(trainer, '_supports_potion_weight', lambda: True)

    source = Path('runs/armg_ironclad_skip_site_rl_20261030/train/latest.pt')
    if not source.exists() or not DATA.exists() or not trainer.extension_loader._extension:
        pytest.skip('source checkpoint, snapshot, or isolated simulator unavailable')
    class PreflightDone(Exception):
        pass
    def no_pool(*args, **kwargs):
        raise PreflightDone()
    monkeypatch.setattr(trainer, 'ProcessPoolExecutor', no_pool)
    out = tmp_path / 'preflight'
    with pytest.raises(PreflightDone):
        trainer.train(init_checkpoint=source, out_dir=out, data_dir=DATA)
    settings = json.loads((out / 'config.json').read_text(encoding='utf-8'))
    assert settings['target_games'] == 2048 and settings['workers'] == 8
    assert settings['training_seed_base'] == 10320000
    assert settings['combat_budget_start'] == 2000 and settings['combat_budget_per_floor'] == 200
    assert settings['combat_budget_elite_bonus'] == 1000 and settings['combat_budget_boss_bonus'] == 2000
    assert settings['skip_elo_start'] == 1350 and settings['skip_elo_per_floor'] == 10
    assert settings['prior_weight'] == .1


def test_stopped_checkpoint_continuation_uses_fresh_seeds(tmp_path, monkeypatch):
    import json
    import torch
    from deployment import train_armg_floor_prior_rl as trainer
    monkeypatch.setattr(trainer, '_supports_potion_weight', lambda: True)
    source = Path('runs/armg_floor_prior_01_rl_20261030/latest.pt')
    if not source.exists() or not DATA.exists() or not trainer.extension_loader._extension:
        pytest.skip('stopped checkpoint, snapshot, or isolated simulator unavailable')
    checkpoint = torch.load(source, map_location='cpu', weights_only=False)
    old_games = checkpoint['progress']['games']
    old_base = checkpoint['settings']['training_seed_base']
    class PreflightDone(Exception):
        pass
    monkeypatch.setattr(trainer, 'ProcessPoolExecutor', lambda *args, **kwargs: (_ for _ in ()).throw(PreflightDone()))
    out = tmp_path / 'continued'
    with pytest.raises(PreflightDone):
        trainer.train(init_checkpoint=source, out_dir=out, data_dir=DATA, games=2048-old_games)
    settings = json.loads((out / 'config.json').read_text(encoding='utf-8'))
    assert settings['training_seed_base'] >= old_base + 2048
    assert settings['target_games'] == 2048 - old_games
