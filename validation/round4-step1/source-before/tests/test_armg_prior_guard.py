"""Paired guard evaluation and no-silent-failure contracts."""
from concurrent.futures import Future
import hashlib
import json

import pytest
import torch

from agent.armg import ArmGScorer
from agent import armg_train as base
from deployment import evaluate_armg_prior_guard as guard


class InlinePool:
    def __init__(self, **_kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def submit(self, fn, task):
        f = Future()
        try:
            f.set_result(fn(task))
        except Exception as exc:
            f.set_exception(exc)
        return f


def _rows(differences):
    return [r for i,d in enumerate(differences) for r in (
        {'seed':i,'arm':'previous','status':'terminated','floor':20,'won':False},
        {'seed':i,'arm':'prior','status':'terminated','floor':20+d,'won':False})]


def test_bootstrap_rule_needs_both_magnitude_and_negative_ci():
    good = guard.paired_summary(_rows([-2]*50))
    assert good['mean_floor_difference'] == -2 and good['ci_95'] == [-2,-2] and good['rollback']
    edge = guard.paired_summary(_rows([-1]*50))
    assert edge['ci_95'][1] < 0 and not edge['rollback']
    uncertain = guard.paired_summary(_rows([-9]*25+[6]*25))
    assert uncertain['mean_floor_difference'] < -1 and uncertain['ci_95'][1] > 0 and not uncertain['rollback']
    assert uncertain == guard.paired_summary(_rows([-9]*25+[6]*25))


def _checkpoints(tmp_path):
    extension = tmp_path/'extension.pyd'
    extension.write_bytes(b'guard test')
    extension_sha = hashlib.sha256(extension.read_bytes()).hexdigest()
    old = tmp_path/'old.pt'
    model = ArmGScorer()
    opt = torch.optim.Adam(model.parameters())
    base._save(old, model, opt, {'games':2, 'cycle_index':0},
               {'information':'oracle','simulations':2,'boss_simulations_per_decision':3,
                'path_cache':'none','simulator_sha256':extension_sha,'max_steps':100,'seed':777})
    prior = tmp_path/'prior.pt'
    base._save(prior, model, opt,
               {'stage':'prior_complete','initialization':'current_model','source_rl_sha256':hashlib.sha256(old.read_bytes()).hexdigest()},
               {'information':'oracle','simulations_per_decision':2,'boss_simulations_per_decision':3,
                'path_cache':'none','simulator_sha256':extension_sha})
    return extension, old, prior


def test_guard_pairs_both_arms_and_reports_rollback(tmp_path,monkeypatch):
    extension, old, prior = _checkpoints(tmp_path)
    monkeypatch.setattr(guard.extension_loader, '_extension', str(extension))
    monkeypatch.setattr(guard, 'ProcessPoolExecutor', InlinePool)
    tasks=[]
    def play(task):
        tasks.append(task)
        return {'seed':task[0], 'status':'terminated','floor':20 if task[3] == 0 else 18,
                'won':False,'records':[]}
    monkeypatch.setattr(guard.rl, '_play', play)
    out=tmp_path/'guard'
    summary=guard.run(prior,old,out,games=2,workers=1,simulations=2,boss_simulations=3,max_steps=100)
    assert summary['state']=='completed' and summary['guard']['rollback']
    assert summary['guard']['complete_pairs']==2
    assert [(tasks[i][0],tasks[i][2]) for i in (0,2)] == [(tasks[i][0],tasks[i][2]) for i in (1,3)]
    assert json.loads((out/'progress.json').read_text(encoding='utf-8'))['state']=='completed'
    assert (out/'summary.json').is_file()


def test_guard_fails_if_one_episode_errors(tmp_path,monkeypatch):
    extension, old, prior = _checkpoints(tmp_path)
    monkeypatch.setattr(guard.extension_loader, '_extension', str(extension))
    monkeypatch.setattr(guard, 'ProcessPoolExecutor', InlinePool)
    def play(task):
        if task[3]==1:
            raise ValueError('failed sample')
        return {'seed':task[0], 'status':'terminated','floor':20,'won':False,'records':[]}
    monkeypatch.setattr(guard.rl, '_play', play)
    out=tmp_path/'guard'
    with pytest.raises(RuntimeError, match='incomplete episodes'):
        guard.run(prior,old,out,games=2,workers=1,simulations=2,boss_simulations=3,max_steps=100)
    assert json.loads((out/'progress.json').read_text(encoding='utf-8'))['state']=='failed'
    assert not (out/'summary.json').exists()


def test_guard_worker_switches_between_previous_and_prior_weights(tmp_path, monkeypatch):
    # Guard assigns a fixed distinct version to each immutable policy file.
    # Reusing a process after alternating arms must reload the right weights.
    model = ArmGScorer()
    with torch.no_grad():
        model.net[0].weight[0, 0] = 1.0
    old = tmp_path/'old_weights.pt'
    torch.save(model.state_dict(), old)
    with torch.no_grad():
        model.net[0].weight[0, 0] = 2.0
    prior = tmp_path/'prior_weights.pt'
    torch.save(model.state_dict(), prior)
    monkeypatch.setattr(guard.rl, '_worker_model', None)
    monkeypatch.setattr(guard.rl, '_worker_version', None)
    observed = []
    def fake_collect(seed, actor, **_kwargs):
        observed.append(actor.net[0].weight[0, 0].detach().item())
        return {'seed': seed, 'status': 'terminated', 'error': None,
                'floor': 1, 'won': False, 'records': [], 'mcts_searches': 0,
                'mcts_simulations': 0}
    monkeypatch.setattr(guard.rl.base, 'collect_episode', fake_collect)
    for version, weights in ((0, old), (1, prior), (0, old), (1, prior)):
        task = (20, 30, 40, version, str(weights), True, 2, 3, 100, str(tmp_path), 'oracle')
        guard.rl._play(task)
    assert observed == [1.0, 2.0, 1.0, 2.0]
