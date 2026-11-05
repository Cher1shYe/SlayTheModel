import hashlib
import json
from pathlib import Path

import pytest

from deployment import run_armg_site_prior_rl_pipeline as pipeline


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _fixture(tmp_path, monkeypatch):
    baseline = tmp_path / 'baseline.pt'
    baseline.write_bytes(b'unchanged-baseline')
    extension = tmp_path / 'sim.pyd'
    extension.write_bytes(b'extension')
    monkeypatch.setenv('STS2_PRIOR_PYD', str(extension))
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'manifest.json').write_text('{}', encoding='utf-8')
    return baseline, extension, data


def test_training_failure_does_not_start_evaluation(tmp_path, monkeypatch):
    baseline, _, data = _fixture(tmp_path, monkeypatch)
    commands = []

    class FailedProcess:
        pid = 10
        def __init__(self, cmd, **kwargs):
            commands.append(cmd)
        def poll(self):
            return 1
        def wait(self):
            return 1

    monkeypatch.setattr(pipeline.subprocess, 'Popen', FailedProcess)
    root = tmp_path / 'run'
    with pytest.raises(RuntimeError, match='training did not complete'):
        pipeline.run(checkpoint=baseline, data_dir=data, root_dir=root, games=2,
                     workers=2, simulations=4, boss_simulations=7,
                     eval_runs=2, evaluation_games=2)
    assert len(commands) == 1
    assert 'deployment.train_armg_site_prior_rl' in commands[0]
    assert json.loads((root / 'progress.json').read_text(encoding='utf-8'))['state'] == 'failed'
    assert baseline.read_bytes() == b'unchanged-baseline'
    assert not (root / 'evaluation').exists()


def test_pipeline_validates_provenance_and_uses_fresh_evaluation_seeds(tmp_path, monkeypatch):
    baseline, extension, data = _fixture(tmp_path, monkeypatch)
    commands = []

    class SuccessfulProcess:
        pid = 11
        def __init__(self, cmd, **kwargs):
            commands.append(cmd)
            output = Path(cmd[cmd.index('--out-dir') + 1])
            output.mkdir()
            if 'deployment.train_armg_site_prior_rl' in cmd:
                candidate = output / 'latest.pt'
                candidate.write_bytes(b'candidate')
                settings = {'init_sha256': _sha(baseline), 'website_manifest_sha256': _sha(data / 'manifest.json'),
                            'simulator_sha256': _sha(extension), 'prior_weight': .05,
                            'skip_elos_by_act': [1400, 1500, 1600], 'information': 'oracle',
                            'prior_scope': 'ordinary skip and website-covered Ironclad reward cards; colorless/other actions remain in RL',
                            'simulations': 4, 'boss_simulations_per_decision': 7, 'path_cache': 'none'}
                (output / 'config.json').write_text(json.dumps(settings), encoding='utf-8')
                progress = {'state': 'completed', 'games': 2}
            else:
                assert '--start' in cmd and cmd[cmd.index('--start') + 1] == '30000'
                candidate = tmp_path / 'run' / 'train' / 'latest.pt'
                report = {'state': 'completed', 'paired': {'complete_pairs': 2, 'mean_floor_difference': 1.0},
                          'arms': {}, 'config': {'sha256': {'baseline': _sha(baseline), 'candidate': _sha(candidate)},
                                                 'simulator_sha256': _sha(extension)}}
                (output / 'summary.json').write_text(json.dumps(report), encoding='utf-8')
                progress = {'state': 'completed', 'completed_jobs': 4}
            (output / 'progress.json').write_text(json.dumps(progress), encoding='utf-8')
        def poll(self):
            return 0
        def wait(self):
            return 0

    monkeypatch.setattr(pipeline.subprocess, 'Popen', SuccessfulProcess)
    root = tmp_path / 'run'
    result = pipeline.run(checkpoint=baseline, data_dir=data, root_dir=root, games=2,
                          workers=2, simulations=4, boss_simulations=7,
                          eval_runs=2, evaluation_games=2)
    assert result['state'] == 'completed'
    assert len(commands) == 2 and 'deployment.evaluate_armg_checkpoints' in commands[1]
    assert (root / 'progress.md').exists()
    assert baseline.read_bytes() == b'unchanged-baseline'


def test_average_counts_only_complete_jsonl_batches(tmp_path):
    assert pipeline._train_average(tmp_path / 'missing') == (None, 0)
    path = tmp_path / 'metrics.jsonl'
    path.write_text('{"train":{"completed":2,"mean_floor":10}}\n'
                    '{"train":{"completed":1,"mean_floor":22}}\n'
                    '{"train":', encoding='utf-8')
    assert pipeline._train_average(path) == (14.0, 3)
