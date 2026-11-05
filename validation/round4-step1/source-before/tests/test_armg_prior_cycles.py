"""Fast checks of cycle orchestration and failure boundaries."""
import json
from pathlib import Path

import pytest
import torch

from deployment import run_armg_prior_cycles as pipeline


def _setup(tmp_path, monkeypatch):
    ext = tmp_path / 'isolated.pyd'
    ext.write_bytes(b'extension')
    monkeypatch.setenv('STS2_PRIOR_PYD', str(ext))
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'manifest.json').write_text('{}', encoding='utf-8')
    return ext, data, tmp_path / 'run'


@pytest.mark.parametrize('rollback', [False, True])
def test_cycles_chain_state_and_keep_round_seeds_disjoint(tmp_path, monkeypatch, rollback):
    ext, data, root = _setup(tmp_path, monkeypatch)
    calls = []

    class Process:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.pid = 1234
            calls.append(cmd)
            args = cmd[cmd.index('-m') + 2:]
            arg = lambda flag: args[args.index(flag) + 1]
            out = Path(arg('--out-dir'))
            out.mkdir()
            if 'agent.armg_prior_train' in cmd:
                prior_source = Path(arg('--init-checkpoint')) if '--init-checkpoint' in args else None
                meta = {'stage': 'prior_complete', 'initialization': 'random' if prior_source is None else 'warm',
                        'source_rl_sha256': pipeline._digest(prior_source) if prior_source else None}
                settings = {'information': 'oracle', 'simulations_per_decision': 2,
                            'boss_simulations_per_decision': 3, 'path_cache': 'none',
                            'simulator_sha256': pipeline._digest(ext)}
                torch.save({'progress': meta, 'settings': settings,
                            'state_dict': {'w': torch.tensor([5.])},
                            'optimizer_state_dict': {'step': 7}}, out / 'prior.pt')
                result = {'state': 'completed', 'stage': 'completed', 'games_completed': 2,
                          'terminated': 2, 'errors': 0, 'truncated': 0}
            elif 'deployment.evaluate_armg_prior_guard' in cmd:
                result = {'state': 'completed'}
                guard = {'state': 'completed', 'config': {
                         'prior_sha256': pipeline._digest(Path(arg('--prior'))),
                         'previous_rl_sha256': pipeline._digest(Path(arg('--previous-rl'))),
                         'simulator_sha256': pipeline._digest(ext)},
                         'guard': {'rollback': rollback, 'complete_pairs': 2,
                         'mean_floor_difference': -2.0 if rollback else 0.0,
                         'ci_95': [-3.0, -1.0] if rollback else [-1.0, 1.0],
                         'method': 'paired bootstrap percentile'}}
                (out / 'summary.json').write_text(json.dumps(guard), encoding='utf-8')
            else:
                torch.save({'cycle': arg('--cycle-index'), 'state_dict': {'w': torch.tensor([1.])},
                            'optimizer_state_dict': {'step': 3}}, out / 'latest.pt')
                result = {'state': 'completed', 'games': 4}
            (out / 'progress.json').write_text(json.dumps(result), encoding='utf-8')

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(pipeline.subprocess, 'Popen', Process)
    assert pipeline.run(root, data, rounds=2, workers=1, simulations=2, boss_simulations=3,
                        prior_games=2, initial_epochs=1, later_epochs=1,
                        rl_games=4, rl_batch=2, eval_every=4, eval_runs=1, guard_games=2) == 0
    result = json.loads((root / 'progress.json').read_text(encoding='utf-8'))
    assert result['state'] == 'completed'
    assert result['completed_rounds'] == 2 and result['completed_rl_games'] == 8
    assert len(calls) == 5
    first, second = calls[0], calls[2]
    assert '--init-checkpoint' not in first
    assert second[second.index('--seed-offset') + 1] == '2'
    assert '--init-checkpoint' in second and '--replay-dirs' in second
    assert calls[1][calls[1].index('--cycle-index') + 1] == '0'
    assert 'deployment.evaluate_armg_prior_guard' in calls[3]
    assert calls[4][calls[4].index('--cycle-index') + 1] == '1'
    assert '--previous-rl' in calls[4]
    selected_prior = Path(calls[4][calls[4].index('--init-checkpoint') + 1])
    assert selected_prior.name == ('guarded_prior.pt' if rollback else 'prior.pt')
    assert result['prior_kl_weight'] == (1.0 if rollback else .5)
    assert result['guards'][0]['rollback'] is rollback
    if rollback:
        fallback = torch.load(selected_prior, map_location='cpu', weights_only=False)
        assert fallback['state_dict']['w'].item() == 1.0
        assert fallback['optimizer_state_dict']['step'] == 3
        assert fallback['progress']['guard_rollback'] is True
        candidate = torch.load(selected_prior.with_name('prior.pt'), map_location='cpu', weights_only=False)
        assert candidate['state_dict']['w'].item() == 5.0


def test_failed_prior_does_not_start_reinforcement(tmp_path, monkeypatch):
    _, data, root = _setup(tmp_path, monkeypatch)
    calls = []

    class Process:
        def __init__(self, cmd, **kwargs):
            self.pid = 1234
            calls.append(cmd)
            out = Path(cmd[cmd.index('--out-dir') + 1])
            out.mkdir()
            (out / 'progress.json').write_text('{"state":"failed"}', encoding='utf-8')

        def poll(self):
            return 1

        def wait(self):
            return 1

    monkeypatch.setattr(pipeline.subprocess, 'Popen', Process)
    with pytest.raises(RuntimeError, match='prior did not complete'):
        pipeline.run(root, data, rounds=1, workers=1, simulations=2, boss_simulations=3,
                     prior_games=2, initial_epochs=1, later_epochs=1,
                     rl_games=4, rl_batch=2, eval_every=4, eval_runs=1)
    result = json.loads((root / 'progress.json').read_text(encoding='utf-8'))
    assert result['state'] == 'failed'
    assert len(calls) == 1
    assert not (root / 'round01' / 'reinforce').exists()


def test_failed_paired_guard_never_starts_next_reinforcement(tmp_path, monkeypatch):
    ext, data, root = _setup(tmp_path, monkeypatch)
    calls = []

    class Process:
        def __init__(self, cmd, **kwargs):
            self.pid = 1234
            self.code = 0
            calls.append(cmd)
            out = Path(cmd[cmd.index('--out-dir') + 1])
            out.mkdir()
            if 'agent.armg_prior_train' in cmd:
                prev = Path(cmd[cmd.index('--init-checkpoint') + 1]) if '--init-checkpoint' in cmd else None
                progress = {'stage': 'prior_complete', 'initialization': 'current_model' if prev else 'random',
                            'source_rl_sha256': pipeline._digest(prev) if prev else None}
                settings = {'information': 'oracle', 'simulations_per_decision': 2,
                            'boss_simulations_per_decision': 3, 'path_cache': 'none',
                            'simulator_sha256': pipeline._digest(ext)}
                torch.save({'progress': progress, 'settings': settings}, out / 'prior.pt')
                result = {'state': 'completed', 'stage': 'completed', 'games_completed': 2,
                          'terminated': 2, 'errors': 0, 'truncated': 0}
            elif 'deployment.evaluate_armg_prior_guard' in cmd:
                self.code = 1
                result = {'state': 'failed', 'error': 'incomplete episode'}
            else:
                torch.save({}, out / 'latest.pt')
                result = {'state': 'completed', 'games': 4}
            (out / 'progress.json').write_text(json.dumps(result), encoding='utf-8')

        def poll(self):
            return self.code

        def wait(self):
            return self.code

    monkeypatch.setattr(pipeline.subprocess, 'Popen', Process)
    with pytest.raises(RuntimeError, match='guard did not complete'):
        pipeline.run(root, data, rounds=2, workers=1, simulations=2, boss_simulations=3,
                     prior_games=2, initial_epochs=1, later_epochs=1,
                     rl_games=4, rl_batch=2, eval_every=4, eval_runs=1, guard_games=2)
    result = json.loads((root / 'progress.json').read_text(encoding='utf-8'))
    assert result['state'] == 'failed' and result['completed_rounds'] == 1
    assert len(calls) == 4
    assert not (root / 'round02' / 'reinforce').exists()
