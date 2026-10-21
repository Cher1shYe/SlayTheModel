"""Exact search equivalence and bounded, model-local evaluation reuse."""
from dataclasses import asdict, replace
import gzip
import json
from pathlib import Path

import pytest
import torch

from sts2_env.az import all_runner as runner
from sts2_env.az import dynamic_search as search
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.entity_transition import public_from_dict
from sts2_env.cards import base as card_base


@pytest.fixture(scope='module')
def model():
    torch.set_num_threads(1)
    return runner.fresh_model(runner.load_frozen_config('configs/az_all_xs_v1/config.json'), 7)


def state(name):
    if name == 'opening':
        return ObservableCombatAdapter(runner.training_recipes(8, 1)[0],
            EpisodeLimits(max_turns=40, max_decisions=400), reward_version=runner.V7).information
    filename = {'knights': 'knights_exhaust_upgrade', 'vigor': 'vigor_pending_hook'}[name]
    return public_from_dict(json.loads(gzip.decompress(
        (Path(__file__).parent/'fixtures'/f'{filename}.json.gz').read_bytes())))


@pytest.mark.parametrize('name', ['opening', 'knights', 'vigor'])
@pytest.mark.parametrize('mode', ['learned', 'heuristic', 'mixed'])
@pytest.mark.parametrize('training,seed', [(False, 123), (True, 7)])
def test_full_tree_exactly_matches_uncached(model, name, mode, training, seed):
    info = state(name)
    rng = torch.get_rng_state().clone()
    next_id = card_base._next_instance_id
    results = []
    final_ids = []
    for cached in (False, True):
        card_base._next_instance_id = next_id
        result = search.plan_dynamic(info, model, model_version='cache-regression',
            budget=16, max_depth=128, search_seed=seed, search_version=runner.SEARCH,
            training=training, temperature=int(training), leaf_mode=mode,
            cache_evaluations=cached)
        row = asdict(result)
        del row['elapsed']
        results.append(row)
        final_ids.append(card_base._next_instance_id)
        assert torch.equal(torch.get_rng_state(), rng)
    # Includes every outcome, prior, initial value, visit count and backup sum.
    assert results[0] == results[1]
    assert final_ids[0] == final_ids[1]


def test_depth_cutoff_reuses_predictions_but_next_search_does_not(model, monkeypatch):
    info = state('opening')
    original = model.predict
    calls = []
    def predict(observation):
        calls.append(observation)
        return original(observation)
    monkeypatch.setattr(model, 'predict', predict)
    kwargs = dict(model_version='cutoff', budget=32, max_depth=1,
                  search_seed=9, search_version=runner.SEARCH, leaf_mode='learned')
    reference = search.plan_dynamic(info, model, cache_evaluations=False, **kwargs)
    before = len(calls)
    calls.clear()
    cached = search.plan_dynamic(info, model, **kwargs)
    after = len(calls)
    assert cached.root == reference.root
    assert 0 < after < before
    calls.clear()
    search.plan_dynamic(info, model, **kwargs)
    assert len(calls) == after  # no cross-search/model-version cache
    bias = model.value[-2].bias
    saved = bias.detach().clone()
    try:
        with torch.no_grad():
            bias.add_(.25)
        changed = search.plan_dynamic(info, model, **kwargs)
        uncached = search.plan_dynamic(info, model, cache_evaluations=False, **kwargs)
        assert changed.root.initial_value != cached.root.initial_value
        assert changed.root == uncached.root
    finally:
        with torch.no_grad():
            bias.copy_(saved)


def test_cache_is_bounded_and_mask_is_part_of_identity(model, monkeypatch):
    info = state('opening')
    seen = []
    def encode(public):
        seen.append(public)
        if public.legal_mask != info.legal_mask:
            raise ValueError('invalid mask')
        return object()
    monkeypatch.setattr(search, 'encode_entities', encode)
    cache = search._SearchEvaluationCache(model, capacity=2)
    first = cache.encode(info)
    assert cache.encode(replace(info)) is first
    assert len(seen) == 1
    invalid = replace(info, legal_mask=tuple(not x for x in info.legal_mask))
    assert invalid.key() == info.key()
    with pytest.raises(ValueError, match='invalid mask'):
        cache.encode(invalid)
    for energy in range(5):
        cache.encode(replace(info, energy=energy))
        assert len(cache.entries) <= 2 and len(cache.identities) <= 2
