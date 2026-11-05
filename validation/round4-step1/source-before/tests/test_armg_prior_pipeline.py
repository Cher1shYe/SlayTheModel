import json

import pytest

from deployment import run_armg_prior_pipeline as pipeline


def test_failed_pretrain_never_starts_reinforcement(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'manifest.json').write_text('{}', encoding='utf-8')
    fake_extension = tmp_path / 'sim.pyd'
    fake_extension.write_bytes(b'test')
    monkeypatch.setenv('STS2_PRIOR_PYD', str(fake_extension))
    commands = []

    class FailedProcess:
        pid = 123
        def __init__(self, cmd, **kwargs):
            commands.append(cmd)
        def poll(self):
            return 1
        def wait(self):
            return 1

    monkeypatch.setattr(pipeline.subprocess, 'Popen', FailedProcess)
    out = tmp_path / 'run'
    with pytest.raises(RuntimeError, match='pretrain did not complete'):
        pipeline.run(out, data, workers=2, simulations=4, boss_simulations=7,
                     prior_games=6, rl_games=2, eval_runs=2)
    progress = json.loads((out / 'pipeline_progress.json').read_text(encoding='utf-8'))
    assert progress['state'] == 'failed'
    assert len(commands) == 1 and 'agent.armg_prior_train' in commands[0]
    assert '--boss-simulations' in commands[0] and '7' in commands[0]
    assert not (out / 'reinforce').exists()
