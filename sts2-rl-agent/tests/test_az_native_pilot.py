"""Recorded native engine contract plus existing replay/learner integration."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from sts2_env.az import all_runner as runner
from sts2_env.az.entity_encoder import NUMERIC_FIELDS
from sts2_env.az.entity_replay import EntityReplayBuffer, pack_observation, unpack_observation
from sts2_env.az.native_pilot import encode_native, to_episode, validate_raw, NativeReplayBuffer


@pytest.fixture
def raw():
    return json.loads(gzip.decompress((Path(__file__).parent/'fixtures/native_byrdonis_pilot.json.gz').read_bytes()))


def test_native_state_action_reward_and_tensor_roundtrip(raw):
    converted = validate_raw(raw)
    episode = to_episode(raw)
    assert len(converted) == raw['outcome']['decisions']
    for row, step, (observation, mapping) in zip(episode['rows'], raw['steps'], converted):
        assert unpack_observation(row['observation']) == observation
        assert row['chosen_action'] == mapping[step['action']]
        assert set(row['policy_target']) == set(mapping.values())
        assert sum(row['root_visits'].values()) == row['search_simulations']
        assert sum(row['policy_target'].values()) == pytest.approx(1.)
        assert row['z'] == raw['outcome']['reward']
    assert any(step['observation']['unblockedHits'] for step in raw['steps'])


def test_hidden_draw_order_and_native_action_ids_are_not_model_features(raw):
    d = raw['steps'][0]['observation']
    before, _ = encode_native(d)
    changed = deepcopy(d)
    changed['draw'].reverse()
    for card in changed['draw']:
        card['stateKey'] = 'private-placeholder'
    for i, action in enumerate(changed['actions']):
        action['Key'] = f'opaque-native-id-{i}'
    after, _ = encode_native(changed)
    assert pack_observation(before) == pack_observation(after)


def test_identical_cards_use_native_equivalence_classes(raw):
    d = raw['steps'][0]['observation']
    obs, mapping = encode_native(d)
    assert len(obs.actions) < len(d['hand']) + 1  # three equivalent Strikes in captured root
    assert len(set(mapping.values())) == len(mapping)
    altered = deepcopy(d)
    altered['actions'] = [a for a in altered['actions'] if a['CardId'] != 'BASH']
    with pytest.raises(ValueError, match='action classes'):
        encode_native(altered)


def test_native_intent_damage_is_preserved(raw):
    d = next(s['observation'] for s in raw['steps'] if 17 in s['observation']['enemies'][0]['hits'])
    obs, _ = encode_native(d)
    enemy = next(e for e in obs.entities if e.ref == 'enemy/0')
    assert enemy.numbers[NUMERIC_FIELDS.index('intent_damage')] == .17
    assert any(op.kind == 'damage' and op.amount == 17 for op in enemy.effects)


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(complete=False),
    lambda r: r.update(teacherInformation='observable'),
    lambda r: r.update(modelSha256='missing'),
    lambda r: r['outcome'].update(reward=.123),
    lambda r: r['steps'][0].update(featureParity=False),
    lambda r: r['steps'][0].update(successorParity=False),
    lambda r: r['steps'][0].update(action='unknown'),
    lambda r: r['steps'][0].update(seconds=float('nan')),
    lambda r: r['steps'][0].update(simulations=0),
    lambda r: r['steps'][0].update(hpAfter=-1),
    lambda r: r['steps'][0]['observation'].update(decisions=99),
    lambda r: r['steps'][0]['observation']['enemies'][0].update(id='UNKNOWN'),
    lambda r: r['steps'][0]['observation']['hand'][0].update(id='HAVOC'),
    lambda r: r['steps'][0]['observation']['actions'].pop(),
])
def test_corrupt_or_out_of_scope_data_is_rejected(raw, mutation):
    mutation(raw)
    with pytest.raises((ValueError, KeyError)):
        to_episode(raw)


def test_split_gate_and_policy_only_data_cannot_enter_search_replay(raw):
    raw['split'] = 'validation'
    with pytest.raises(ValueError, match='training fights'):
        to_episode(raw)
    raw['split'] = 'train'
    raw['arm'] = 'policy'
    for step in raw['steps']:
        step['simulations'] = 0
        step['visits'] = {k: 0 for k in step['visits']}
    with pytest.raises(ValueError, match='training fights'):
        to_episode(raw)


def test_atomic_replay_reload_and_no_legacy_mixing(raw, tmp_path):
    episode = to_episode(raw)
    replay = NativeReplayBuffer(tmp_path/'replay')
    assert replay.commit(episode)
    assert not replay.commit(episode)
    expected = replay.sample(8, np.random.default_rng(4))
    replay.release_memory()
    assert replay.sample(8, np.random.default_rng(4)) == expected
    reopened = NativeReplayBuffer(tmp_path/'replay')
    assert reopened.sample(8, np.random.default_rng(4)) == expected
    ordinary = EntityReplayBuffer(tmp_path/'ordinary', content_version=runner.ALL_CONTENT, reward_version=runner.V7)
    with pytest.raises(ValueError):
        ordinary.validate(episode)
    with pytest.raises(ValueError, match='version/capacity'):
        EntityReplayBuffer(tmp_path/'replay', capacity=50000, content_version=runner.ALL_CONTENT, reward_version=runner.V7)
    bad = deepcopy(episode)
    bad['rows'][0]['z'] += .1
    with pytest.raises(ValueError, match='audited source'):
        reopened.commit(bad)


def test_cached_case_identity_model_and_recipe_must_match(raw):
    from scripts.check_native_collection import check_case
    spec = dict(seed=raw['seed'], hp=raw['initialHp'], arm=raw['arm'], split=raw['split'])
    check_case(raw, raw['identity'], raw['modelSha256'], spec, raw['budgetMs'])
    for identity, model, case, budget in [
        ('0'*64, raw['modelSha256'], spec, raw['budgetMs']),
        (raw['identity'], '0'*64, spec, raw['budgetMs']),
        (raw['identity'], raw['modelSha256'], {**spec, 'seed': spec['seed']+1}, raw['budgetMs']),
        (raw['identity'], raw['modelSha256'], spec, raw['budgetMs']+1),
    ]:
        with pytest.raises(ValueError, match='provenance'):
            check_case(raw, identity, model, case, budget)


def test_existing_update_resume_and_champion_contract(raw, tmp_path):
    from scripts.check_native_collection import training_smoke
    from sts2_env.az.model_factory import save_transformer_checkpoint
    torch.set_num_threads(1)
    replay = NativeReplayBuffer(tmp_path/'replay')
    replay.commit(to_episode(raw))
    model = runner.fresh_model(runner.load_frozen_config('configs/az_all_xs_v1/config.json'), 19)
    save_transformer_checkpoint(tmp_path/'initial.pt', model)
    baseline = [dict(scenario_id='fixed', reward=raw['outcome']['reward'])]
    result = training_smoke(tmp_path, replay, baseline)
    assert result['exact_update_resume'] and result['champion_unchanged']
    assert result['champion_checkpoint'] != result['learner_checkpoint']
    assert all(np.isfinite(m['loss']) and np.isfinite(m['gradient_norm']) for m in result['metrics'])
    assert runner.promotion(baseline, [], 1) == (False, None)
