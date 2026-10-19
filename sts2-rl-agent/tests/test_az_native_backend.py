"""Expanded recorded native contracts and failure injection at lifecycle boundaries."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest
import torch

from sts2_env.az import native_backend as nb, all_runner as runner
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.native_pilot import (validate_raw, to_episode, encode_native,
                                     NativeReplayBuffer, NativeExpandedReplayBuffer)
from scripts.check_native_collection import sha

CONFIG = 'configs/az_native_xs_v2/config.json'
PROTOCOL = 'configs/az_native_xs_v2/protocol.json'


@pytest.fixture
def raws():
    return json.loads(gzip.decompress((Path(__file__).parent/'fixtures/native_expanded_v2.json.gz').read_bytes()))


def test_recorded_full_trajectories_cover_all_cards_and_both_encounters(raws, tmp_path):
    replay = NativeExpandedReplayBuffer(tmp_path/'replay')
    played = set()
    for raw in raws:
        validate_raw(raw)
        episode = to_episode(raw)
        replay.commit(episode)
        for step in raw['steps']:
            played.update(a['CardId'] for a in step['observation']['actions'] if a['Key']==step['action'] and a['CardId'])
    assert {'IRON_WAVE', 'POMMEL_STRIKE', 'TWIN_STRIKE'} <= played
    assert {r['encounter'] for r in raws} == set(nb.ENCOUNTERS)
    assert NativeExpandedReplayBuffer(tmp_path/'replay').size == sum(len(r['steps']) for r in raws)
    with pytest.raises(ValueError):
        NativeReplayBuffer(tmp_path/'replay')


def test_existing_card_effects_are_reused(raws):
    from sts2_env.az.expanded_entities import card_entity, pile_state
    for raw in raws:
        d = raw['steps'][0]['observation']
        obs, _ = encode_native(d)
        for i, c in enumerate(d['hand']):
            actual = next(e for e in obs.entities if e.ref==f'hand/{i}')
            assert actual == card_entity(f'hand/{i}', pile_state(c['id'], 0), 'hand', slot=i+1)


@pytest.mark.parametrize('mutation', [
    lambda r: r['recipe']['deck'].append('BASH'),
    lambda r: r.update(encounter='MAWLER_NORMAL'),
    lambda r: r['steps'][0]['observation']['enemies'][0].update(id='MAWLER'),
    lambda r: r['steps'][0]['observation']['enemies'][0].update(move='UNKNOWN'),
    lambda r: r['outcome'].update(finalHp=0),
    lambda r: r['outcome'].update(reward=float('nan')),
    lambda r: r['outcome'].update(searchReward=r['outcome']['reward']+1e-8),
    lambda r: r['steps'][0]['observation']['hand'][0].update(cost=9),
    lambda r: r['steps'][0]['observation']['hand'][0].update(baseValues={}),
    lambda r: r['steps'][0]['observation']['actions'][0].update(Key='not-the-visited-action'),
])
def test_expanded_corruption_fails_closed(raws, mutation):
    raw = deepcopy(raws[0])
    mutation(raw)
    with pytest.raises(ValueError):
        validate_raw(raw)


def test_frozen_validation_is_balanced_unique_disjoint_and_immutable():
    protocol = json.loads(Path(PROTOCOL).read_text())
    validation = nb.validate_protocol(protocol)
    assert protocol == nb.frozen_protocol()
    assert len(validation) == 24
    train = [r for iteration in range(3) for r in nb.training_recipes(iteration, 304)]
    assert len({r['scenario_id'] for r in train}) == 912
    assert not {r['seed'] for r in train} & {r['seed'] for r in validation}
    protocol['validation'][0]['hp'] = 1
    with pytest.raises(ValueError):
        nb.validate_protocol(protocol)


@pytest.mark.parametrize('mutation', [
    lambda p: p['validation'].__setitem__(1, p['validation'][0]),
    lambda p: p['validation'].__setitem__(0, nb.training_recipes(0, 1)[0]),
    lambda p: p.update(cards=['BASH']),
])
def test_refingerprinted_invalid_protocol_is_rejected(mutation):
    p = nb.frozen_protocol()
    mutation(p)
    p['manifest_sha256'] = content_hash({k:v for k,v in p.items() if k!='manifest_sha256'})
    with pytest.raises(ValueError):
        nb.validate_protocol(p)


def test_native_partial_batch_failure_reuses_completed_fights(raws, tmp_path, monkeypatch):
    backend = nb.NativeBackend(json.loads(Path(CONFIG).read_text())['backend'], nb.frozen_protocol(), tmp_path)
    checkpoint = tmp_path/'model.pt'
    checkpoint.write_bytes(b'fixture-model')
    by_recipe = {r['recipe']['scenario_id']: r for r in raws}
    recipes = tuple(r['recipe'] for r in raws)
    executed = []
    fail = [True]
    def execute(job_path, log):
        job = json.loads(job_path.read_text())
        for spec in job['cases']:
            executed.append(spec['recipe']['scenario_id'])
            raw = deepcopy(by_recipe[spec['recipe']['scenario_id']])
            raw.update(identity=job['identity'], modelSha256=job['modelSha256'])
            atomic_json(spec['output'], raw)
            if fail[0]:
                fail[0] = False
                raise RuntimeError('injected worker failure after durable fight')
    monkeypatch.setattr(backend, '_execute', execute)
    with pytest.raises(RuntimeError, match='injected'):
        backend.collect(checkpoint, recipes, tmp_path/'cache')
    episodes = backend.collect(checkpoint, recipes, tmp_path/'cache')
    assert len(episodes) == 4 and len(executed)==4 and len(set(executed))==4
    monkeypatch.setattr(backend, '_execute', lambda *a: pytest.fail('completed cache reran'))
    assert backend.collect(checkpoint, recipes, tmp_path/'cache') == episodes
    checkpoint.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        backend.collect(checkpoint, recipes, tmp_path/'cache')
    with pytest.raises(ValueError, match='Validation'):
        backend.collect(checkpoint, backend.validation, tmp_path/'forbidden')


@pytest.mark.parametrize('fault', ['baseline', 'update', 'evaluation'])
def test_existing_runner_native_recovery_and_champion_retention(raws, tmp_path, monkeypatch, fault):
    torch.set_num_threads(1)
    source_paths = []
    fixtures = tuple(r['recipe'] for r in raws[:2])
    monkeypatch.setattr(nb, 'training_recipes', lambda iteration, episodes: fixtures[:episodes])
    def collect(self, checkpoint, recipes, directory):
        source_paths.append(checkpoint.name)
        result = []
        for r in raws[:len(recipes)]:
            raw = deepcopy(r)
            raw.update(identity=content_hash([sha(checkpoint), str(directory)]), modelSha256=sha(checkpoint))
            result.append(to_episode(raw))
        return result
    def evaluate(self, model, recipes, **kwargs):
        rows = [dict(scenario_id=r['scenario_id'], encounter_id=r['encounter'], reward=0., termination_reason='death') for r in recipes]
        return dict(contract_rejections=0, mean_utility=0.), rows
    monkeypatch.setattr(nb.NativeBackend, 'collect', collect)
    monkeypatch.setattr(nb.NativeBackend, 'evaluate', evaluate)
    args = dict(iterations=2, episodes=2, updates=2, batch_size=8, seed=33, log=lambda *a: None)
    full = runner.run(CONFIG, PROTOCOL, tmp_path/'full', **args)
    assert source_paths == ['initial.pt', 'update-000-0002.pt']
    assert full['champion_checkpoint'] == 'initial.pt'
    assert not any(h['promoted'] for h in full['history'])
    atomic = runner.atomic_json
    def crash_update(path, value):
        atomic(path, value)
        pending = value.get('pending') if isinstance(value, dict) else None
        if pending and pending.get('update_checkpoint')=='update-001-0001.pt':
            raise RuntimeError('injected update boundary')
    fail_once = [True]
    def crash_eval(self, model, recipes, **kwargs):
        desired = 'baseline' if fault=='baseline' else 'candidate-1'
        if fail_once[0] and desired in kwargs['version']:
            fail_once[0] = False
            raise RuntimeError('injected evaluation boundary')
        return evaluate(self, model, recipes, **kwargs)
    if fault=='update':
        monkeypatch.setattr(runner, 'atomic_json', crash_update)
    else:
        monkeypatch.setattr(nb.NativeBackend, 'evaluate', crash_eval)
    with pytest.raises(RuntimeError, match='injected'):
        runner.run(CONFIG, PROTOCOL, tmp_path/'resumed', **args)
    monkeypatch.setattr(runner, 'atomic_json', atomic)
    monkeypatch.setattr(nb.NativeBackend, 'evaluate', evaluate)
    if fault != 'baseline':
        monkeypatch.setattr(nb.NativeBackend, 'collect', lambda *a: pytest.fail('pending collection repeated'))
    resumed = runner.run(CONFIG, PROTOCOL, tmp_path/'resumed', resume=True, **args)
    a, pa = runner.load_transformer_checkpoint(tmp_path/'full'/full['learner_checkpoint'], runner.TIER, runner.ALL_CONTENT, runner.V7)
    b, pb = runner.load_transformer_checkpoint(tmp_path/'resumed'/resumed['learner_checkpoint'], runner.TIER, runner.ALL_CONTENT, runner.V7)
    assert all(torch.equal(v, b.state_dict()[k]) for k,v in a.state_dict().items())
    assert full['history'][1]['updates'] == resumed['history'][1]['updates']
    assert {int(s['step']) for s in pb['training_state']['optimizer']['state'].values()} == {4}
    assert resumed['champion_checkpoint']=='initial.pt'


@pytest.mark.parametrize('override', [dict(include_test=True), dict(workers=2), dict(leaf_mode='learned'), dict(budget=8), dict(max_turns=4)])
def test_native_runner_rejects_unsupported_flags(tmp_path, override):
    with pytest.raises(ValueError, match='Native v2 requires'):
        runner.run(CONFIG, PROTOCOL, tmp_path/'run', **override)


def test_preflight_native_guards_and_cli_no_training(monkeypatch):
    assert runner.preflight(CONFIG, PROTOCOL, iterations=1, episodes=4)['ready']
    with pytest.raises(ValueError, match='40/100'):
        runner.preflight(CONFIG, PROTOCOL, max_decisions=4)
    monkeypatch.setattr(runner, 'run', lambda *a, **k: pytest.fail('preflight started a run'))
    runner.main(['--config', CONFIG, '--protocol', PROTOCOL, '--preflight-only'])
    with pytest.raises(ValueError, match='millisecond'):
        runner.main(['--config', CONFIG, '--protocol', PROTOCOL, '--preflight-only', '--budget', '8'])


def test_v7_rollout_roundoff_is_only_machine_precision():
    from sts2_env.az.risk_reward import utility
    differences = []
    for hp in range(1, 81):
        canonical = utility('win', hp, 80, 80, 1., 0.)
        native = .9 + .1*(hp/80)
        differences.append(abs(canonical-native))
    assert 0 < max(differences) <= 1e-15
