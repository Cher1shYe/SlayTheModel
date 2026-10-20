from collections import Counter
from copy import deepcopy

import pytest
import torch

from scripts.run_native_epoch_experiment import epoch_batches, train_epochs
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint, load_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, encode
from sts2_env.az.rewards import V7
from tests.test_az_native_generic import frame


def test_full_epochs_no_replacement_no_dropped_tail():
    batches = list(epoch_batches(1027, 3, 64, 25))
    assert len(batches) == 3 * 17
    for epoch in range(3):
        entries = [i for e, batch in batches if e == epoch for i in batch]
        assert Counter(entries) == Counter(range(1027))
        assert len([b for e, b in batches if e == epoch][-1]) == 3
    assert batches == list(epoch_batches(1027, 3, 64, 25))
    assert batches[0][1] != batches[17][1]


def test_epoch_native_optimizer_resume_exact(frame, tmp_path):
    torch.set_num_threads(1)
    torch.manual_seed(12)
    initial = create_transformer('XS', CONTENT, V7)
    packed = encode(frame)
    samples = [dict(observation=deepcopy(packed), policy_target={'opaque-one':1., 'opaque-two':0.}, z=v)
               for v in (-1., .3, 1., -.4, .8)]
    config = dict(learning_rate=3e-4, value_weight=.5, epochs=3, batch_size=2, init_seed=88)
    full, history = train_epochs(initial, samples, config, 'dataset')
    path = tmp_path/'interrupted.pt'
    class Interrupt(Exception): pass
    def save(model, state):
        if len(state['history']) == 4:
            save_transformer_checkpoint(path, model, training_state=state)
            raise Interrupt()
    with pytest.raises(Interrupt):
        train_epochs(initial, samples, config, 'dataset', persist=save)
    restored, payload = load_transformer_checkpoint(path, 'XS', CONTENT, V7)
    resumed, resumed_history = train_epochs(restored, samples, config, 'dataset', payload['training_state'])
    assert resumed_history == history
    assert len(history) == 9
    assert sum(r['samples'] for r in history) == 15
    assert all(torch.equal(t, resumed.state_dict()[k]) for k,t in full.state_dict().items())
    with pytest.raises(ValueError, match='dataset/schedule mismatch'):
        train_epochs(restored, samples, config, 'different', payload['training_state'])
