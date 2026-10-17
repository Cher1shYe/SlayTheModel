from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
import numpy as np
from sts2_env.az.natural_course import (export_witness,restore,seal,validate_course,
    collect_suffix,validate_suffix,advance)
from sts2_env.az.t4_protocol import (generate_protocol,validate_protocol,signature,
                                    network_gate,training_recipes)
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.boss_curriculum import block_rule_action
from sts2_env.az.information import BeliefSampler
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.entity_replay import EntityReplayBuffer
from sts2_env.az.scenarios import CombatScenario
from sts2_env.az.combo_diagnostic import sequence,probe
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V7
from sts2_env.az.content import BOSS_CONTENT

ROOT=Path(__file__).resolve().parents[1]


def read(path): return json.loads((ROOT/path).read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def course(): return read('configs/az_transformer_t4_v1/natural_course.json')


def test_frozen_course_matches_complete_witnesses(course):
    sources=[read(p) for p in sorted(course['source_sha256'])]
    # Source paths and export order are lexically frozen by the preparation script.
    entries=validate_course(course,sources)
    assert {e['category'] for e in entries}=={'phase-1','phase-2','burn-hand','purity-status-choice'}
    for e in entries:
        env=restore(e)
        assert env.information.initial_hp==e['recipe']['player_hp']
        assert env.information.history.decisions==len(e['prefix'])
        assert env.limits.max_decisions==e['limits']['max_decisions']
        particle=BeliefSampler().sample(env.information,np.random.default_rng(9))
        assert encode_entities(particle.info)==encode_entities(env.information)


@pytest.mark.parametrize('mutation',['prefix','hp','version','split','limits'])
def test_resealed_bad_natural_state_is_rejected(course,mutation):
    e=deepcopy(course['entries'][0]);e.pop('sha256')
    if mutation=='prefix': e['prefix'][0]='invalid'
    if mutation=='hp': e['public']['player_hp']-=1
    if mutation=='version': e['version']='old'
    if mutation=='split': e['recipe']['split']='test'
    if mutation=='limits': e['limits']['max_decisions']=1
    with pytest.raises(ValueError): restore(seal(e))


def test_incomplete_witness_rejected():
    w=read('docs/g23f_audit/rule-win-9cdfa66bbf7f.json')
    w['actions']=w['actions'][:-1]
    with pytest.raises(ValueError,match='Incomplete'): export_witness(w)


def rule_result(info):
    mapping=action_candidates(info)[1]; native=block_rule_action(info)
    key=next(k for k,v in mapping.items() if v==native)
    forced=len(mapping)==1
    return SimpleNamespace(action=key,policy_target={k:float(k==key) for k in mapping},
        root_visits={k:int(k==key and not forced) for k in mapping},simulations=0 if forced else 1,
        forced_action=forced)


def test_real_suffix_labels_scope_and_old_replay_rejection(course,tmp_path):
    entry=next(e for e in course['entries'] if e['category']=='phase-2')
    record=collect_suffix(entry,rule_result,'rule-test-not-trained')
    assert validate_suffix(record)
    assert record['rows'][0]['absolute_step']==len(entry['prefix'])
    assert record['outcome']['decisions']==len(entry['prefix'])+len(record['rows'])
    assert record['outcome']['initial_hp']==entry['recipe']['player_hp']
    assert all(r['z']==record['outcome']['reward'] for r in record['rows'])
    from sts2_env.az.natural_course import training_rows as late_rows
    from sts2_env.az.entity_replay import unpack_observation
    from sts2_env.az.transformer_network import batch_entities,keyed_targets
    samples=late_rows([record],course,generate_protocol())
    batch=batch_entities([unpack_observation(r['observation']) for r in samples[:2]])
    targets=keyed_targets(batch,[r['policy_target'] for r in samples[:2]])
    assert targets.shape[0]==min(2,len(samples))
    replay=EntityReplayBuffer(tmp_path,content_version=BOSS_CONTENT,reward_version=V7)
    with pytest.raises(ValueError): replay.validate(record)
    for field in ('z','absolute_step'):
        bad=deepcopy(record);bad['rows'][0][field]=123
        with pytest.raises(ValueError): validate_suffix(bad)
    bad=deepcopy(record);bad['rows'][0]['policy_target']={}
    with pytest.raises(ValueError): validate_suffix(bad)


def test_protocol_freeze_and_late_isolation(course):
    p=generate_protocol()
    assert p==read('configs/az_transformer_t4_v1/protocol.json')
    assert validate_protocol(p,course['entries'])==dict(train=48,validation=256,unseen_combination=24,unseen_id=24)
    assert len(training_recipes(p))==48
    with pytest.raises(ValueError,match='contaminated'): validate_protocol(p,initial_checkpoint='old-v7.pt')


@pytest.mark.parametrize('mutation',['id','combo','split','seed','metric'])
def test_protocol_rejects_leaks_even_after_resealing(mutation):
    p=generate_protocol();p.pop('sha256')
    if mutation=='id': p['groups']['train'][0]['deck'].append(dict(card_id='BLUDGEON',upgraded=True,count=1))
    if mutation=='combo':
        r=p['groups']['unseen_combination'][0]
        r['deck']=deepcopy(p['groups']['train'][0]['deck'])
        r['encounter_id']=p['groups']['train'][0]['encounter_id']
        r['family_id']=p['groups']['train'][0]['family_id']
    if mutation=='split':p['groups']['train'][0]['split']='test'
    if mutation=='seed':p['groups']['train'][1]['environment_seed']=p['groups']['train'][0]['environment_seed']
    if mutation=='metric':p['primary_metric']='win-rate'
    with pytest.raises(ValueError):validate_protocol(seal(p))


def test_signature_ignores_hp_seed_deck_order():
    from dataclasses import replace
    r=training_recipes(generate_protocol())[0]
    assert signature(r)==signature(replace(r,player_hp=80,environment_seed=99,deck=tuple(reversed(r.deck))))


def test_real_native_combo_order_and_public_search_reproducibility():
    w=read('docs/g23f_audit/rule-win-9cdfa66bbf7f.json'); recipe=CombatScenario.from_dict(w['recipe'])
    factory=lambda:ObservableCombatAdapter(recipe,reward_version=V7)
    good=sequence(factory,['ARMAMENTS+','BODY_SLAM+'])
    bad=sequence(factory,['BODY_SLAM+','ARMAMENTS+'])
    assert good[-1]['enemy_hp']==95 and bad[-1]['enemy_hp']==100
    assert good[-1]['cutoff_utility']>bad[-1]['cutoff_utility']
    info=factory().information
    a=probe(info,budget=8);b=probe(info,budget=8)
    assert a==b and sum(a['visits'].values())==8
    assert a['max_depth']==1
    assert probe(info,budget=32)['max_depth']>1


def test_gate_passes_only_full_network_population_to_utility_criterion(monkeypatch):
    from sts2_env.az import evaluation
    p=generate_protocol(); rows=[dict(scenario_id=r['scenario_id']) for r in p['groups']['validation']]
    called={}
    def gate(old,new,**kwargs):called.update(kwargs);return {'promote':False}
    monkeypatch.setattr(evaluation,'promotion_gate',gate)
    assert not network_gate(p,rows,rows,mode='network')['promote']
    assert called['criterion']=='utility-only-v1' and called['reward_version']==V7
    with pytest.raises(ValueError):network_gate(p,rows,rows,mode='search')
    with pytest.raises(ValueError):network_gate(p,rows[:-1],rows[:-1],mode='network')
    with pytest.raises(ValueError):network_gate(p,[{'scenario_id':'late'}]*256,rows,mode='network')


def test_unknown_mechanism_remains_rejected():
    from sts2_env.az.expanded_mechanics import describe_card
    with pytest.raises(ValueError,match='Unsupported'):describe_card('UNREGISTERED_T4_CARD')


def test_sampling_is_reproducible_and_does_not_mutate_course(course):
    from sts2_env.az.natural_course import sample_entry
    a=np.random.default_rng(17);b=np.random.default_rng(17)
    for _ in range(20):
        entry=sample_entry(course,a)
        assert entry==sample_entry(course,b)
        entry['prefix'].append('invalid-mutation')
    assert all('invalid-mutation' not in e['prefix'] for e in course['entries'])
