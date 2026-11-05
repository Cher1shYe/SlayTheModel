"""Prepare-only checkpoints: no games or optimization are run by these tests."""
import json
from pathlib import Path
import pytest
import torch
from agent.common import sim
from agent.nets import read_checkpoint
from deployment import train_armg_puct_prior_rl as trainer


def prepare(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setattr(trainer.extension_loader, '_extension', sim.__file__)
    return trainer.train(out_dir=tmp_path / 'new', fresh_init=True,
        combat_prior_mode='random', site_prior_mode='disabled', prior_weight=0,
        prepare_only=True, games=1, batch_size=1, workers=1,
        simulations=1, floor_increment=0, eval_every=1, eval_runs=1, **kwargs)


def test_prepare_random_starts_with_zero_games_and_fresh_optimizer(tmp_path, monkeypatch):
    assert prepare(tmp_path, monkeypatch) == 0
    out = tmp_path / 'new'
    data = read_checkpoint(out / 'latest.pt')
    assert data['progress']['games'] == 0
    assert data['progress']['source_games'] == 0
    assert data['progress']['training_games_in_target_environment'] == 0
    assert data['progress']['baseline'] is None
    assert data['optimizer_state_dict']['state'] == {}
    assert data['settings']['site_prior_mode'] == 'disabled'
    assert data['settings']['reproduces_original_training_configuration'] is False
    prior = read_checkpoint(out / 'combat_policy.pt')
    assert prior['progress']['total_games'] == 0
    assert prior['progress']['initialization'] == 'new_random_untrained'
    assert not (out / 'metrics.jsonl').exists()
    assert json.loads((out / 'progress.json').read_text())['state'] == 'prepared'


def test_prepare_warmstart_never_reuses_optimizer_or_progress(tmp_path, monkeypatch):
    first = tmp_path / 'first'; first.mkdir()
    prepare(first, monkeypatch)
    source = first / 'new/latest.pt'
    data = read_checkpoint(source)
    data['progress'].update(games=999, baseline=.8)
    data['optimizer_state_dict'] = {'unusable_old_optimizer': True}
    torch.save(data, source)
    before = source.read_bytes()
    prepare(tmp_path, monkeypatch, init_checkpoint=source)
    actual = read_checkpoint(tmp_path / 'new/latest.pt')
    assert actual['progress']['games'] == 0
    assert actual['optimizer_state_dict']['state'] == {}
    assert all(torch.equal(v, data['state_dict'][k]) for k,v in actual['state_dict'].items())
    assert source.read_bytes() == before


def test_missing_dependencies_are_explicit_and_create_no_run(tmp_path):
    with pytest.raises(ValueError, match='combat-checkpoint'):
        trainer.train(out_dir=tmp_path/'missing', fresh_init=True)
    assert not (tmp_path/'missing').exists()
    with pytest.raises(ValueError, match='prior-weight 0'):
        trainer.train(out_dir=tmp_path/'bad', fresh_init=True,
            combat_prior_mode='random', site_prior_mode='disabled')
    assert not (tmp_path/'bad').exists()
