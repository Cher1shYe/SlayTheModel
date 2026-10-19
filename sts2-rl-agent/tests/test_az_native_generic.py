from copy import deepcopy
import json
import gzip
from pathlib import Path

import pytest
import torch

from sts2_env.az.native_generic import CONTENT, encode, validate_packed, GenericReplay
from sts2_env.az.native_transformer import batch_native
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint, load_transformer_checkpoint
from sts2_env.az.rewards import V7
from sts2_env.az.learner import Learner
from sts2_env.az.native_generic_backend import frozen_protocol, validate_protocol, make_recipe


@pytest.fixture
def frame():
    return dict(version='native-generic-observation-v1',initialHp=80,decisions=0,
        observation=dict(SchemaVersion=5,RoundNumber=1,CurrentSide='Player',
            Players=[dict(PlayerId=7,Energy=3,Piles=[dict(PileType='Draw',Cards=[
                dict(CombatCardIndex=10,ModelId='UNREGISTERED_A'),dict(CombatCardIndex=11,ModelId='UNREGISTERED_B')])])],
            Creatures=[dict(CombatId=1,PlayerId=7,CurrentHp=80),dict(CombatId=2,PlayerId=None,MonsterId='UNREGISTERED_ENEMY',CurrentHp=20)],
            EnemyIntents=[],Companions=[],ActiveChoice=None,PendingManualActions=[]),
        cards=[dict(index=10,data=dict(model='UNREGISTERED_A',upgrade=1)),dict(index=11,data=dict(model='UNREGISTERED_B',upgrade=0))],
        intents=[dict(target=2,intents=[dict(kind='Attack',damage=5)])],choice=None,
        actions=[dict(Key='opaque-one',features=dict(kind='Play',target=2,source=dict(model='UNREGISTERED_A'))),
                 dict(Key='opaque-two',features=dict(kind='EndTurn'))])


def test_unregistered_content_and_hidden_draw_order(frame):
    first=encode(frame)
    changed=deepcopy(frame)
    changed['observation']['Players'][0]['Piles'][0]['Cards'].reverse()
    assert encode(changed)==first
    changed['actions'][0]['Key']='different-opaque-key'
    a,b=batch_native([first]),batch_native([encode(changed)])
    for key in ('ids','numbers','owners'): assert torch.equal(a[key],b[key])


def test_action_equivariance_and_generic_update_checkpoint(frame,tmp_path):
    torch.set_num_threads(1); torch.manual_seed(9)
    model=create_transformer('XS',CONTENT,V7).eval()
    p=encode(frame); before,value=model.predict(p)
    reverse=deepcopy(p); reverse['actions'].reverse()
    after,value2=model.predict(reverse)
    assert after==pytest.approx(before,abs=1e-6)
    assert value2==pytest.approx(value,abs=1e-6)
    path=tmp_path/'generic.pt'; save_transformer_checkpoint(path,model)
    restored,_=load_transformer_checkpoint(path,'XS',CONTENT,V7)
    assert restored.predict(p)==(before,value)
    with pytest.raises(ValueError): load_transformer_checkpoint(path)
    learner=Learner(model)
    result=learner.update([dict(observation=p,policy_target={'opaque-one':1.,'opaque-two':0.},z=1.)])
    assert result['update']==1
    assert all(torch.isfinite(t).all() for t in learner.model.state_dict().values())
    assert any(not torch.equal(v,learner.model.state_dict()[k]) for k,v in model.state_dict().items())


@pytest.mark.parametrize('mutate',[
    lambda f:f['actions'][1].update(Key='opaque-one'),
    lambda f:f['actions'][0]['features'].update(target=999),
    lambda f:f['cards'].pop(),
    lambda f:f['observation']['Creatures'][0].update(CurrentHp=float('nan')),
    lambda f:f.update(version='unknown'),
    lambda f:f['actions'][0].update(features=dict(kind='Choose',selected=[])),
])
def test_invalid_protocol_rejected(frame,mutate):
    mutate(frame)
    with pytest.raises(ValueError): encode(frame)


def test_choice_and_new_content_manifest(frame):
    frame['choice']=dict(min=1,max=1,options=[dict(model='NEW_CARD',upgrade=1)])
    frame['actions']=[dict(Key='choose',features=dict(kind='Choose',selected=[dict(index=0,card=frame['choice']['options'][0])]))]
    encode(frame)
    frame['actions'][0]['features']['selected'][0]['index']=1
    with pytest.raises(ValueError): encode(frame)
    protocol=frozen_protocol(['NEW_CARD','OTHER_CARD+'],['NEW_ENCOUNTER'],4)
    rows=validate_protocol(protocol)
    train=make_recipe(123,'NEW_ENCOUNTER',protocol['cards'],'train')
    assert train['seed'] not in {r['seed'] for r in rows}
    protocol['validation'][0]['hp']=1
    with pytest.raises(ValueError): validate_protocol(protocol)


def test_generic_config_preflight():
    from sts2_env.az.all_runner import load_frozen_config,preflight
    assert preflight('configs/az_native_generic_v1/config.json','configs/az_native_generic_v1/protocol.json')['ready']


@pytest.fixture
def raws():
    return json.loads(gzip.decompress((Path(__file__).parent/'fixtures/native_generic_v1.json.gz').read_bytes()))


def test_recorded_generic_replay_and_strict_legacy_isolation(raws,tmp_path):
    from sts2_env.az.native_generic import validate_raw,to_episode
    from sts2_env.az.native_pilot import NativeExpandedReplayBuffer
    replay=GenericReplay(tmp_path/'replay')
    for raw in raws:
        validate_raw(raw); assert replay.commit(to_episode(raw))
        assert not replay.commit(to_episode(raw))
    assert GenericReplay(tmp_path/'replay').size==sum(len(r['steps']) for r in raws)
    with pytest.raises(ValueError): NativeExpandedReplayBuffer(tmp_path/'replay')
    assert any(s['observation']['choice'] for r in raws for s in r['steps'])
    assert all(0 <= s['automaticForcedChoices'] <= 16 for r in raws for s in r['steps'])


@pytest.mark.parametrize('mutate',[
    lambda r:r['outcome'].update(reward=0.),
    lambda r:r['steps'][0].update(hpAfter=-1),
    lambda r:r['steps'][0]['observation']['cards'][0]['data'].update(upgrade=9),
    lambda r:r['steps'][0]['visits'].update(invalid_action=1),
    lambda r:r['steps'][0].update(simulations=0),
    lambda r:r['steps'][0].update(featureParity=False),
    lambda r:r.update(wallSeconds=float('nan')),
])
def test_recorded_generic_corruption_fails(raws,mutate):
    from sts2_env.az.native_generic import validate_raw
    raw=deepcopy(raws[0]); mutate(raw)
    with pytest.raises(ValueError): validate_raw(raw)


@pytest.mark.parametrize('fault',['baseline','update','evaluation'])
@pytest.mark.parametrize('workers',[1,4])
def test_generic_runner_resume_learner_and_champion(raws,tmp_path,monkeypatch,fault,workers):
    from sts2_env.az import all_runner as runner, native_generic_backend as nb
    from sts2_env.az.native_generic import to_episode
    from sts2_env.az.config import content_hash
    from scripts.check_native_collection import sha
    torch.set_num_threads(1)
    sources=[]
    def collect(self,checkpoint,recipes,directory):
        assert self.workers==workers
        sources.append(checkpoint.name)
        raw=deepcopy(raws[0]); raw.update(identity=content_hash([sha(checkpoint),str(directory)]),modelSha256=sha(checkpoint))
        return [to_episode(raw)]
    def evaluate(self,model,recipes,**kwargs):
        return dict(contract_rejections=0,mean_utility=0.),[dict(scenario_id=r['scenario_id'],encounter_id=r['encounter'],reward=0.,termination_reason='death') for r in recipes]
    monkeypatch.setattr(nb.NativeBackend,'collect',collect)
    monkeypatch.setattr(nb.NativeBackend,'evaluate',evaluate)
    config='configs/az_native_generic_v1/config.json'; protocol='configs/az_native_generic_v1/protocol.json'
    args=dict(iterations=2,episodes=1,updates=2,batch_size=2,seed=33,workers=workers,log=lambda *a:None)
    full=runner.run(config,protocol,tmp_path/'full',**args)
    assert full['execution']['workers']==workers
    assert sources==['initial.pt','update-000-0002.pt']
    atomic=runner.atomic_json
    def fail_update(path,value):
        atomic(path,value)
        pending=value.get('pending') if isinstance(value,dict) else None
        if pending and pending.get('update_checkpoint')=='update-001-0001.pt': raise RuntimeError('injected')
    def fail_eval(self,model,recipes,**kwargs):
        if ('baseline' if fault=='baseline' else 'candidate-1') in kwargs['version']: raise RuntimeError('injected')
        return evaluate(self,model,recipes,**kwargs)
    if fault=='update': monkeypatch.setattr(runner,'atomic_json',fail_update)
    else: monkeypatch.setattr(nb.NativeBackend,'evaluate',fail_eval)
    with pytest.raises(RuntimeError,match='injected'): runner.run(config,protocol,tmp_path/'resumed',**args)
    monkeypatch.setattr(runner,'atomic_json',atomic)
    monkeypatch.setattr(nb.NativeBackend,'evaluate',evaluate)
    if fault!='baseline': monkeypatch.setattr(nb.NativeBackend,'collect',lambda *a:pytest.fail('repeated pending collection'))
    resumed=runner.run(config,protocol,tmp_path/'resumed',resume=True,**args)
    a,_=load_transformer_checkpoint(tmp_path/'full'/full['learner_checkpoint'],'XS',CONTENT,V7)
    b,p=load_transformer_checkpoint(tmp_path/'resumed'/resumed['learner_checkpoint'],'XS',CONTENT,V7)
    assert all(torch.equal(v,b.state_dict()[k]) for k,v in a.state_dict().items())
    assert full['history'][1]['updates']==resumed['history'][1]['updates']
    assert {int(s['step']) for s in p['training_state']['optimizer']['state'].values()}=={4}
    assert resumed['champion_checkpoint']=='initial.pt'


def test_generic_partial_collection_cache_and_source_invalidation(raws,tmp_path,monkeypatch):
    from sts2_env.az.native_generic_backend import NativeBackend
    from sts2_env.az.config import atomic_json
    config=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())
    protocol=json.loads(Path('configs/az_native_generic_v1/protocol.json').read_text())
    backend=NativeBackend(config['backend'],protocol,tmp_path)
    checkpoint=tmp_path/'model.pt'; checkpoint.write_bytes(b'fixture')
    by_id={r['recipe']['scenario_id']:r for r in raws}
    recipes=tuple(r['recipe'] for r in raws); executed=[]; fail=[True]
    def execute(path,log):
        job=json.loads(path.read_text())
        for spec in job['cases']:
            executed.append(spec['recipe']['scenario_id'])
            raw=deepcopy(by_id[spec['recipe']['scenario_id']])
            raw.update(identity=job['identity'],modelSha256=job['modelSha256'])
            atomic_json(spec['output'],raw)
            if fail[0]: fail[0]=False; raise RuntimeError('injected durable fight')
    monkeypatch.setattr(backend,'_execute',execute)
    with pytest.raises(RuntimeError,match='injected'): backend.collect(checkpoint,recipes,tmp_path/'cache')
    episodes=backend.collect(checkpoint,recipes,tmp_path/'cache')
    assert len(executed)==len(set(executed))==len(recipes)
    monkeypatch.setattr(backend,'_execute',lambda *a:pytest.fail('reran cached fight'))
    assert backend.collect(checkpoint,recipes,tmp_path/'cache')==episodes
    backend.provenance['collector_sha256']='changed'
    with pytest.raises(ValueError,match='changed'): backend.collect(checkpoint,recipes,tmp_path/'cache')
