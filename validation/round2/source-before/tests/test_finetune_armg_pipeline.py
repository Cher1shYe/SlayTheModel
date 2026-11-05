import hashlib
import json
from pathlib import Path

import pytest

from deployment import run_finetune_armg_pipeline as pipeline


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _value(cmd, option):
    return cmd[cmd.index(option) + 1]


def _inputs(tmp_path, monkeypatch):
    baseline = tmp_path / 'original.pt'
    baseline.write_bytes(b'original model')
    ext = tmp_path / 'extension.pyd'
    ext.write_bytes(b'isolated simulator')
    monkeypatch.setenv('STS2_PRIOR_PYD', str(ext))
    sources = []
    for i in range(3):
        p = tmp_path / f'source{i}'
        p.mkdir()
        sources.append(p)
    return baseline, ext, sources


def test_completed_pipeline_runs_evaluation_after_matching_finetune(tmp_path, monkeypatch):
    baseline, ext, sources = _inputs(tmp_path, monkeypatch)
    started = []
    class FakeProcess:
        pid = 123
        def __init__(self, cmd, **kwargs):
            module = cmd[cmd.index('-m') + 1]
            started.append(module)
            out = Path(_value(cmd, '--out-dir'))
            out.mkdir()
            if module.endswith('finetune_armg_prior'):
                (out / 'finetuned.pt').write_bytes(b'candidate')
                (out / 'config.json').write_text(json.dumps({'checkpoint_sha256': _sha(baseline)}), encoding='utf-8')
                (out / 'progress.json').write_text(json.dumps({'state': 'completed', 'stage': 'completed', 'epoch': 3}), encoding='utf-8')
            else:
                candidate = Path(_value(cmd, '--candidate'))
                config = {'sha256': {'baseline': _sha(baseline), 'candidate': _sha(candidate)}, 'simulator_sha256': _sha(ext)}
                report = {'state': 'completed', 'config': config, 'paired': {'complete_pairs': 2, 'mean_floor_difference': 1.0}, 'arms': {}}
                (out / 'summary.json').write_text(json.dumps(report), encoding='utf-8')
                (out / 'progress.json').write_text(json.dumps({'state': 'completed'}), encoding='utf-8')
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(pipeline.subprocess, 'Popen', FakeProcess)
    root = tmp_path / 'run'
    result = pipeline.run(checkpoint=baseline, sources=sources, root_dir=root, games=2, workers=2)
    assert started == ['deployment.finetune_armg_prior', 'deployment.evaluate_armg_checkpoints']
    assert result['state'] == 'completed'
    assert baseline.read_bytes() == b'original model'
    assert '配对平均层数差：+1.00' in (root / 'progress.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('bad_provenance', [False, True])
def test_finetune_failure_or_wrong_backup_blocks_evaluation(tmp_path, monkeypatch, bad_provenance):
    baseline, _, sources = _inputs(tmp_path, monkeypatch)
    started = []
    class FakeProcess:
        pid = 123
        def __init__(self, cmd, **kwargs):
            module = cmd[cmd.index('-m') + 1]
            started.append(module)
            out = Path(_value(cmd, '--out-dir'))
            out.mkdir()
            (out / 'finetuned.pt').write_bytes(b'candidate')
            (out / 'config.json').write_text(json.dumps({'checkpoint_sha256': 'wrong' if bad_provenance else _sha(baseline)}), encoding='utf-8')
            (out / 'progress.json').write_text(json.dumps({'state': 'completed' if bad_provenance else 'failed', 'stage': 'completed'}), encoding='utf-8')
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(pipeline.subprocess, 'Popen', FakeProcess)
    root = tmp_path / 'run'
    with pytest.raises(RuntimeError):
        pipeline.run(checkpoint=baseline, sources=sources, root_dir=root, games=2)
    assert started == ['deployment.finetune_armg_prior']
    assert json.loads((root / 'progress.json').read_text(encoding='utf-8'))['state'] == 'failed'
    assert baseline.read_bytes() == b'original model'
