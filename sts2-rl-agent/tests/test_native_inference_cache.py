from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest
import torch

from sts2_env.az import native_transformer as nt
from sts2_env.az.native_generic import encode
from sts2_env.az.leaf_repeat_stats import LeafRepeatStats


@pytest.mark.parametrize('value_only', [False, True])
def test_fixture_tensors_exact_with_cache(monkeypatch, value_only):
    nt.token_ids.cache_clear()
    for name in ('native_calamity_stomp_entry_v1', 'native_headbutt_terminal_v1', 'native_selector_turn_start_v1'):
        raw = json.loads(gzip.decompress((Path(__file__).parent/'fixtures'/f'{name}.json.gz').read_bytes()))
        for step in raw['steps']:
            packed = encode(step['observation'], value_only=value_only)
            monkeypatch.setattr(nt, 'TOKEN_HASH_CACHE_ENABLED', False)
            before = nt.batch_native([packed], value_only=value_only)
            monkeypatch.setattr(nt, 'TOKEN_HASH_CACHE_ENABLED', True)
            after = nt.batch_native([packed], value_only=value_only)
            assert before.keys() == after.keys()
            for key in before:
                assert torch.equal(before[key], after[key]) if torch.is_tensor(before[key]) else before[key] == after[key]
    assert nt.token_ids.cache_info().hits > nt.token_ids.cache_info().misses
    bad = deepcopy(packed)
    bad['schema'] = 'wrong'
    with pytest.raises(ValueError):
        nt.batch_native([bad], value_only=value_only)


def test_token_cache_buckets_and_bound():
    for buckets in (7, 19, 65536):
        assert nt.token_ids('x:number', buckets) == nt.token_ids.__wrapped__('x:number', buckets)
    assert nt.token_ids.cache_parameters()['maxsize'] == 65536


def test_leaf_repeats_exact_inputs_reset_and_capacity():
    stats = LeafRepeatStats('model-sha', capacity=2)
    p = {'schema':'v1', 'entities':[{'hp':8, 'decisions':3}], 'actions':[]}
    stats.observe(p)  # Calls outside a decision (preflight) are excluded.
    stats.begin_decision(0)
    stats.observe(p); stats.observe(deepcopy(p))
    changed = deepcopy(p); changed['entities'][0]['decisions'] = 4
    stats.observe(changed)
    changed['entities'][0]['hp'] = 7
    stats.observe(changed)
    assert stats.report()['repeats'] == 1
    assert stats.report()['untracked'] == 1
    stats.begin_decision(1)
    stats.observe(p)
    assert stats.report()['calls'] == 5
    assert stats.report()['repeat_rate'] == .2
    assert stats.report()['decisions'][1]['repeats'] == 0
