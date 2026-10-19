"""Value-only inference, search configuration and replay separation contracts."""
from copy import deepcopy
import json
import gzip
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from tests.test_az_native_generic import frame, raws
from sts2_env.az.native_generic import CONTENT, encode, GenericReplay, to_episode
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint
from sts2_env.az.rewards import V7
from sts2_env.az.native_generic_backend import NativeBackend, validate_settings
from sts2_env.az.all_runner import effective_settings


def test_value_only_matches_training_forward_without_fake_action(frame):
    torch.set_num_threads(1); torch.manual_seed(11)
    model=create_transformer('XS',CONTENT,V7).eval()
    _,value=model.predict(encode(frame))
    frame['actions']=[]
    assert model.predict_value(encode(frame,value_only=True))==pytest.approx(value,abs=1e-6)
    with pytest.raises(ValueError): encode(frame)
    frame['observation']['Creatures'][0]['CurrentHp']=1
    assert abs(model.predict_value(encode(frame,value_only=True))-value)>1e-7


@pytest.mark.parametrize('mode,mix',[('heuristic',.5),('learned',.5),('mixed',0.),('mixed',.35),('mixed',1.)])
def test_native_leaf_effective_settings_and_cache_identity(tmp_path,mode,mix):
    config=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())
    protocol=json.loads(Path('configs/az_native_generic_v1/protocol.json').read_text())
    settings=effective_settings(config,leaf_mode=mode,value_mix=mix)
    validate_settings(config,settings)
    backend=NativeBackend(config['backend'],protocol,tmp_path)
    backend.configure_search(settings['leaf_mode'],settings['value_mix'])
    assert backend.search_job==dict(leafMode=mode,valueMix=mix)
    assert backend.provenance['leaf_settings']==backend.search_job


@pytest.mark.parametrize('mode,mix',[('invalid',.5),('mixed',float('nan')),('mixed',-1),('mixed',1.1)])
def test_invalid_leaf_settings(mode,mix):
    config=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())
    with pytest.raises(ValueError): effective_settings(config,leaf_mode=mode,value_mix=mix)


def test_replay_rejects_other_leaf_targets(raws,tmp_path):
    episode=to_episode(raws[0])
    replay=GenericReplay(tmp_path/'r',leaf_mode='learned')
    with pytest.raises(ValueError,match='leaf'): replay.commit(episode)
    assert GenericReplay.compatibility_for('mixed',.3)!=GenericReplay.compatibility_for('mixed',.7)


def test_resident_value_service_same_checkpoint_parity_and_error_framing(frame,tmp_path):
    torch.set_num_threads(1)
    model=create_transformer('XS',CONTENT,V7).eval()
    checkpoint=tmp_path/'initial.pt'; save_transformer_checkpoint(checkpoint,model)
    branch=deepcopy(frame); branch['actions']=[]
    bad=deepcopy(branch); bad['observation']['Creatures'][0]['CurrentHp']=1
    requests=[dict(operation='value',observation=branch,expected=bad),
              dict(operation='value',observation=branch,expected=frame),frame]
    result=subprocess.run([sys.executable,'scripts/native_pilot_service.py','--source',str(Path.cwd()),'--checkpoint',str(checkpoint)],
        input=''.join(json.dumps(r)+'\n' for r in requests),text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    messages=[json.loads(line) for line in result.stdout.splitlines()]
    assert messages[0]['ready']
    assert 'Branch/live value features differ' in messages[1]['error']
    assert messages[2]['value']==pytest.approx(model.predict_value(encode(branch,value_only=True)),abs=1e-6)
    assert sum(messages[3]['priors'])==pytest.approx(1.)


@pytest.fixture
def learned_raws():
    return json.loads(gzip.decompress((Path(__file__).parent/'fixtures/native_leaf_learned_v1.json.gz').read_bytes()))


def test_recorded_leaf_values_enter_replay_and_balance_visits(learned_raws,tmp_path):
    from sts2_env.az.native_generic import validate_raw
    replay=GenericReplay(tmp_path/'replay',leaf_mode='learned')
    for r in learned_raws:
        validate_raw(r); replay.commit(to_episode(r))
    assert sum(s['leafDiagnostics']['leafBackups'] for r in learned_raws for s in r['steps'])>0
    assert sum(s['leafDiagnostics']['terminalBackups'] for r in learned_raws for s in r['steps'])>0
    assert GenericReplay(tmp_path/'replay',leaf_mode='learned').size==replay.size
    with pytest.raises(ValueError): GenericReplay(tmp_path/'replay',leaf_mode='mixed')


def test_recorded_mixed_value_arithmetic_and_weight_isolation(tmp_path):
    from sts2_env.az.native_generic import validate_raw
    rows=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/native_leaf_mixed_v1.json.gz').read_bytes()))
    replay=GenericReplay(tmp_path/'r',leaf_mode='mixed',value_mix=.5)
    for r in rows:
        validate_raw(r);replay.commit(to_episode(r))
        for s in r['steps']:
            d=s['leafDiagnostics']
            assert d['evaluatedValueSum']==pytest.approx(.5*(d['valueSum']+d['heuristicSum']),abs=1e-7)
    with pytest.raises(ValueError): GenericReplay(tmp_path/'r',leaf_mode='mixed',value_mix=.7)


@pytest.mark.parametrize('mutate',[
    lambda r:r.update(leafMode='mixed',valueMix=.2),
    lambda r:r.update(searchMode='root-prior-uniform-tree-rollout-v1'),
    lambda r:r['steps'][0]['leafDiagnostics'].update(valueSum=float('nan')),
    lambda r:r['steps'][0]['leafDiagnostics'].update(leafBackups=999999),
    lambda r:r['steps'][0]['leafDiagnostics'].update(evaluatedValueSum=999999),
])
def test_recorded_leaf_corruption_rejected(learned_raws,mutate):
    from sts2_env.az.native_generic import validate_raw
    r=deepcopy(learned_raws[0]);mutate(r)
    with pytest.raises(ValueError): validate_raw(r)


def test_learned_runner_cli_override_update_resume_and_champion(learned_raws,tmp_path,monkeypatch):
    from sts2_env.az import all_runner as runner
    from sts2_env.az.config import content_hash
    from scripts.check_native_collection import sha
    from sts2_env.az.model_factory import load_transformer_checkpoint
    torch.set_num_threads(1);sources=[]
    def collect(self,checkpoint,recipes,directory):
        assert self.search_job==dict(leafMode='learned',valueMix=.5)
        sources.append(checkpoint.name)
        r=deepcopy(learned_raws[0]);r.update(identity=content_hash([sha(checkpoint),str(directory)]),modelSha256=sha(checkpoint))
        return [to_episode(r)]
    def evaluate(self,model,recipes,**kwargs):
        return dict(contract_rejections=0,mean_utility=0.),[dict(scenario_id=r['scenario_id'],encounter_id=r['encounter'],reward=0.,termination_reason='death') for r in recipes]
    monkeypatch.setattr(NativeBackend,'collect',collect);monkeypatch.setattr(NativeBackend,'evaluate',evaluate)
    config='configs/az_native_generic_v1/config.json';protocol='configs/az_native_generic_v1/protocol.json'
    args=dict(iterations=2,episodes=1,updates=2,batch_size=2,seed=33,leaf_mode='learned',value_mix=.5,log=lambda *a:None)
    full=runner.run(config,protocol,tmp_path/'full',**args)
    assert sources==['initial.pt','update-000-0002.pt']
    atomic=runner.atomic_json
    def fail_update(path,value):
        atomic(path,value)
        pending=value.get('pending') if isinstance(value,dict) else None
        if pending and pending.get('update_checkpoint')=='update-001-0001.pt': raise RuntimeError('injected')
    monkeypatch.setattr(runner,'atomic_json',fail_update)
    with pytest.raises(RuntimeError,match='injected'): runner.run(config,protocol,tmp_path/'resumed',**args)
    monkeypatch.setattr(runner,'atomic_json',atomic)
    monkeypatch.setattr(NativeBackend,'collect',lambda *a:pytest.fail('repeated collection'))
    with pytest.raises(ValueError,match='differs'): runner.run(config,protocol,tmp_path/'resumed',resume=True,**dict(args,leaf_mode='mixed'))
    result=runner.run(config,protocol,tmp_path/'resumed',resume=True,**args)
    a,_=load_transformer_checkpoint(tmp_path/'full'/full['learner_checkpoint'],'XS',CONTENT,V7)
    b,p=load_transformer_checkpoint(tmp_path/'resumed'/result['learner_checkpoint'],'XS',CONTENT,V7)
    assert all(torch.equal(v,b.state_dict()[k]) for k,v in a.state_dict().items())
    assert full['history'][1]['updates']==result['history'][1]['updates']
    assert result['champion_checkpoint']=='initial.pt'
