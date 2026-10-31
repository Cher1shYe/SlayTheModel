"""Cross-cycle policy/optimizer lineage and reproducible validation contracts."""
from concurrent.futures import Future
import hashlib

import numpy as np
import pytest
import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, ArmGScorer
from agent import armg_train as base
from deployment import train_armg_hidden_mcts as trainer


class InlinePool:
    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def submit(self, fn, task):
        future = Future()
        try:
            future.set_result(fn(task))
        except Exception as exc:
            future.set_exception(exc)
        return future


def _prior(path, extension_hash, source=None):
    model = ArmGScorer()
    if source:
        source_data = torch.load(source, map_location='cpu', weights_only=False)
        model.load_state_dict(source_data['state_dict'])
    opt = torch.optim.Adam(model.parameters(), lr=1e-4)
    progress = {'stage': 'prior_complete', 'initialization': 'current_model' if source else 'random'}
    if source:
        progress['source_rl_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    base._save(path, model, opt, progress,
               {'information': 'oracle', 'simulations_per_decision': 2,
                'boss_simulations_per_decision': 3, 'path_cache': 'none',
                'simulator_sha256': extension_hash})


def test_rl_two_cycles_preserve_optimizer_and_keep_independent_seeds(tmp_path, monkeypatch):
    extension = tmp_path / 'extension.pyd'
    extension.write_bytes(b'isolated-test-extension')
    ext_hash = hashlib.sha256(extension.read_bytes()).hexdigest()
    monkeypatch.setattr(trainer.extension_loader, '_extension', str(extension))
    monkeypatch.setattr(trainer, 'ProcessPoolExecutor', InlinePool)
    tasks = []

    def episode(task):
        tasks.append(task)
        game_seed, _sample_seed, _search_seed, _version, _weights, deterministic, *_ = task
        obs = np.zeros(ARMG_OBS_DIM, dtype=np.float32)
        actions = np.zeros((2, ARMG_ACTION_DIM), dtype=np.float32)
        actions[1, 0] = 1.0
        return {'seed': game_seed, 'status': 'terminated', 'error': None,
                'floor': 10 + (game_seed % 2) * 10, 'won': False,
                'records': [] if deterministic else [(obs, actions, 1)],
                'normal_decisions': 0, 'boss_decisions': 0,
                'normal_simulations': 0, 'boss_simulations': 0}

    monkeypatch.setattr(trainer, '_play', episode)
    p0 = tmp_path / 'prior0.pt'
    _prior(p0, ext_hash)
    common = dict(games=2, batch_size=2, workers=1, simulations=2,
                  boss_simulations=3, eval_every=2, eval_runs=2, max_steps=100,
                  lr=3e-4, combat_mode='oracle')
    assert trainer.train(init_checkpoint=p0, out_dir=tmp_path/'r0', cycle_index=0, **common) == 0
    c0 = torch.load(tmp_path/'r0/latest.pt', map_location='cpu', weights_only=False)
    step0 = next(iter(c0['optimizer_state_dict']['state'].values()))['step'].item()
    p1 = tmp_path / 'prior1.pt'
    _prior(p1, ext_hash, tmp_path/'r0/latest.pt')
    assert trainer.train(init_checkpoint=p1, out_dir=tmp_path/'r1', cycle_index=1,
                         previous_rl=tmp_path/'r0/latest.pt', **common) == 0
    c1 = torch.load(tmp_path/'r1/latest.pt', map_location='cpu', weights_only=False)
    step1 = next(iter(c1['optimizer_state_dict']['state'].values()))['step'].item()
    assert step1 == step0 + 1
    assert c1['progress']['cycle_index'] == 1
    assert c1['progress']['cumulative_games'] == 4
    train_seeds = [[task[0] for task in tasks[i:i+2]] for i in (0, 4)]
    assert set(train_seeds[0]).isdisjoint(train_seeds[1])
    val0 = sorted((task[0], task[2]) for task in tasks[2:4])
    val1 = sorted((task[0], task[2]) for task in tasks[6:8])
    assert val0 == val1
    # The model fine-tuned from round zero may not be paired with round one's
    # optimizer; reject the broken lineage before creating an output folder.
    with pytest.raises(ValueError, match='lineage'):
        trainer.train(init_checkpoint=p1, out_dir=tmp_path/'bad', cycle_index=2,
                      previous_rl=tmp_path/'r1/latest.pt', **common)
    assert not (tmp_path/'bad').exists()


def test_cycle_requires_previous_and_never_overlaps_validation():
    with pytest.raises(ValueError, match='later cycles'):
        trainer.train(init_checkpoint='unused', out_dir='unused', cycle_index=1)
    with pytest.raises(ValueError, match='overlap'):
        trainer.train(init_checkpoint='unused', out_dir='unused', cycle_index=1000,
                      previous_rl='unused')
