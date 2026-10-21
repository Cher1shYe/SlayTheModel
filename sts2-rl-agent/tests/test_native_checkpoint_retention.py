from copy import deepcopy
import json
from pathlib import Path

import pytest
import torch

from scripts.native_checkpoint_retention import digest, prune_checkpoints, safe_update_path
from scripts.run_native_epoch_experiment import train_epochs
from sts2_env.az.config import atomic_json
from sts2_env.az.model_factory import create_transformer, load_transformer_checkpoint, save_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, encode
from sts2_env.az.rewards import V7
from tests.test_az_native_generic import frame


def test_retained_resume_has_identical_adam_rng_and_weights(frame, tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(73)
    initial = create_transformer('XS', CONTENT, V7)
    samples = [dict(observation=deepcopy(encode(frame)),
                    policy_target={'opaque-one': 1., 'opaque-two': 0.}, z=z)
               for z in (-1., .5, .3, -.2, 1.)]
    config = dict(epochs=3, batch_size=2, init_seed=42, learning_rate=.0003, value_weight=.5)
    full, expected = train_epochs(initial, samples, config, 'same')
    first = 'models/initial.pt'
    save_transformer_checkpoint(tmp_path/first, initial)
    state = dict(learner=first, champion=first, history=[], epoch_checkpoints=[],
                 pending=dict(update_checkpoint=None), checkpoint_hashes={first: digest(tmp_path/first)})
    state_path = tmp_path/'state.json'
    atomic_json(state_path, state)

    class Interrupted(Exception):
        pass

    def persist(model, payload):
        count = len(payload['history'])
        name = f'run/iteration-000/checkpoints/update-{count:05d}.pt'
        save_transformer_checkpoint(tmp_path/name, model, training_state=payload)
        state['checkpoint_hashes'][name] = digest(tmp_path/name)
        state['pending']['update_checkpoint'] = name
        if count % 3 == 0:
            state['epoch_checkpoints'].append(name)
        atomic_json(state_path, state)
        prune_checkpoints(tmp_path, state_path, state)

    def interrupt(model, payload):
        persist(model, payload)
        if len(payload['history']) == 4:
            raise Interrupted()

    with pytest.raises(Interrupted):
        train_epochs(initial, samples, config, 'same', persist=interrupt)
    assert sorted(p.name for p in (tmp_path/'run/iteration-000/checkpoints').glob('*.pt')) == [
        'update-00003.pt', 'update-00004.pt']
    restored, payload = load_transformer_checkpoint(tmp_path/state['pending']['update_checkpoint'], 'XS', CONTENT, V7)
    resumed, actual = train_epochs(restored, samples, config, 'same', payload['training_state'], persist)
    assert actual == expected
    assert all(torch.equal(t, resumed.state_dict()[k]) for k, t in full.state_dict().items())
    assert sorted(p.name for p in (tmp_path/'run/iteration-000/checkpoints').glob('*.pt')) == [
        'update-00003.pt', 'update-00006.pt', 'update-00009.pt']


def fixture_state(base):
    names = ['models/initial.pt'] + [f'run/iteration-000/checkpoints/update-{i:05d}.pt' for i in range(1, 7)]
    for name in names:
        p = base/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name)
    state = dict(learner=names[6], champion=names[4],
        history=[dict(candidate=names[4]), dict(candidate=names[5])],
        epoch_checkpoints=[names[3], names[6]], pending=None,
        checkpoint_hashes={name: digest(base/name) for name in names})
    atomic_json(base/'state.json', state)
    return state, names


def test_gc_crash_recovery_and_candidate_champion_cache_protection(tmp_path, monkeypatch):
    state, names = fixture_state(tmp_path)
    cache = tmp_path/'run/iteration-000/collection/cache.json'
    cache.parent.mkdir(parents=True)
    cache.write_text('unchanged')
    original = Path.unlink
    deleted = []
    def interrupt(path, *args, **kwargs):
        if deleted:
            raise OSError('simulated crash during GC')
        original(path, *args, **kwargs)
        deleted.append(path)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', interrupt)
        with pytest.raises(OSError, match='simulated crash'):
            prune_checkpoints(tmp_path, tmp_path/'state.json', state)
    recovered = json.loads((tmp_path/'state.json').read_text())
    assert len(recovered['checkpoint_gc']) == 2
    prune_checkpoints(tmp_path, tmp_path/'state.json', recovered)
    assert not recovered['checkpoint_gc']
    assert all((tmp_path/name).exists() for name in [names[0], *names[3:]])
    assert not (tmp_path/names[1]).exists() and not (tmp_path/names[2]).exists()
    assert cache.read_text() == 'unchanged'


def test_uncommitted_pointer_and_tampered_deletion_are_rejected(tmp_path):
    state, names = fixture_state(tmp_path)
    changed = deepcopy(state)
    changed['learner'] = names[1]
    with pytest.raises(ValueError, match='committed'):
        prune_checkpoints(tmp_path, tmp_path/'state.json', changed)
    (tmp_path/names[1]).write_text('tampered')
    with pytest.raises(ValueError, match='checksum mismatch'):
        prune_checkpoints(tmp_path, tmp_path/'state.json', state)
    assert all((tmp_path/name).exists() for name in names)


@pytest.mark.parametrize('name', ['../outside.pt', 'run/cache.json', 'run/iteration-000/../checkpoints/update-00001.pt'])
def test_deletion_path_is_restricted(tmp_path, name):
    with pytest.raises(ValueError):
        safe_update_path(tmp_path, name)
