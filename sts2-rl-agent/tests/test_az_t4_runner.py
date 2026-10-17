from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import json
import numpy as np
import pytest
from sts2_env.az.t4_run_plan import plan,jobs
from sts2_env.az.t4_replay import MixedReplay
from sts2_env.az.t4_runner import drive
from sts2_env.az.config import content_hash,atomic_json
from sts2_env.az.natural_course import collect_suffix,normalized
from sts2_env.az.t4_protocol import generate_protocol,signature
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.entity_transition import public_snapshot
from sts2_env.az.entity_replay import EntityReplayBuffer,pack_observation
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.rewards import V7
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.scenarios import CombatScenario
from sts2_env.az.boss_curriculum import block_rule_action

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def inputs():
    return generate_protocol(),json.loads((ROOT/'configs/az_transformer_t4_v1/natural_course.json').read_text())


def rule(info):
    mapping=action_candidates(info)[1];native=block_rule_action(info)
    key=next(k for k,v in mapping.items() if v==native);forced=len(mapping)==1
    return SimpleNamespace(action=key,policy_target={k:float(k==key) for k in mapping},
        root_visits={k:int(k==key and not forced) for k in mapping},simulations=0 if forced else 1,forced_action=forced)


@pytest.fixture(scope='module')
def records(inputs):
    protocol,course=inputs;p=plan(protocol,course,'smoke',41)
    job=next(jobs(p,protocol,course,0));recipe=CombatScenario.from_dict(job['recipe'])
    env=ObservableCombatAdapter(recipe,reward_version=V7);rows=[];identity='a'*64
    while not env.outcome().done:
        info=env.information;keys=action_candidates(info)[1];forced=len(keys)==1
        public=public_snapshot(info)
        rows.append(dict(episode_id=identity,step_index=len(rows),family_id=recipe.family_id,
            encounter_id=recipe.encounter_id,scenario_id=recipe.scenario_id,model_version='test-rule',
            observation=pack_observation(encode_entities(info)),public_information=public,public_digest=content_hash(public),
            root_visits={k:int(k=='end_turn' and not forced) for k in keys},policy_target={k:float(k=='end_turn') for k in keys},
            chosen_action='end_turn',search_seconds=.1,search_simulations=0 if forced else 1,forced_action=forced))
        env.step(0)
    for row in rows:row['z']=env.outcome().reward
    full=normalized(dict(episode_id=identity,complete=True,split='train',rows=rows,outcome=asdict(env.outcome()),
        final_public=public_snapshot(env.information),compatibility=EntityReplayBuffer.compatibility_for(BOSS_CONTENT,V7),
        job_id='test',iteration=0))
    entry=next(e for e in course['entries'] if e['category']=='phase-2')
    late=collect_suffix(entry,rule,'test-rule')
    return full,late,normalized(recipe.to_dict())


def test_frozen_schedules_ratios_and_seed_isolation(inputs):
    protocol,course=inputs;seen=set()
    for mode,seed in [('smoke',41),('formal',42),('formal',43)]:
        p=plan(protocol,course,mode,seed)
        assert p['batch_full']==48 and p['batch_late']==16
        for iteration in range(p['rounds']):
            schedule=list(jobs(p,protocol,course,iteration))
            assert schedule==list(jobs(p,protocol,course,iteration))
            assert [j['kind'] for j in schedule]==['full','full','full','late']*45
            for j in schedule:
                if j['kind']=='full':
                    seed=j['recipe']['environment_seed'];assert seed not in seen;seen.add(seed)
                    assert signature(CombatScenario.from_dict(j['recipe'])) in {
                        signature(CombatScenario.from_dict(r)) for r in protocol['groups']['train']}


def test_disk_replay_ratio_fifo_retry_reload(inputs,records,tmp_path):
    protocol,course=inputs;full,late,recipe=records
    caps={'full':len(full['rows']),'late':len(late['rows'])}
    replay=MixedReplay(tmp_path,{'test':1},protocol,course,caps)
    replay.commit('a'*64,'full',full,recipe);replay.commit('b'*64,'late',late)
    assert not replay.commit('a'*64,'full',full,recipe)
    noisy=deepcopy(full);noisy['rows'][0]['search_seconds']=9
    assert not replay.commit('a'*64,'full',noisy,recipe)
    samples=replay.sample(np.random.default_rng(9))
    assert len(samples)==64 and sum('absolute_step' in r for r in samples)==16
    again=MixedReplay(tmp_path,{'test':1},protocol,course,caps)
    assert samples==again.sample(np.random.default_rng(9))
    replay.commit('c'*64,'full',full,recipe)
    assert replay.manifest['active']['full']==['c'*64]
    assert (tmp_path/'episodes'/('a'*64+'.json.gz')).exists()
    with pytest.raises(ValueError):MixedReplay(tmp_path,{'test':2},protocol,course,caps)
    with pytest.raises(ValueError):replay.commit('../bad','full',full,recipe)


def test_atomic_orphan_retry_and_no_missing_pool_fallback(inputs,records,tmp_path,monkeypatch):
    import sts2_env.az.t4_replay as module
    protocol,course=inputs;full,late,recipe=records
    replay=MixedReplay(tmp_path,{},protocol,course)
    original=module.atomic_json
    monkeypatch.setattr(module,'atomic_json',lambda *a:(_ for _ in ()).throw(OSError('simulated interrupted manifest')))
    with pytest.raises(OSError):replay.commit('a'*64,'full',full,recipe)
    assert not replay.manifest['committed']
    monkeypatch.setattr(module,'atomic_json',original)
    reloaded=MixedReplay(tmp_path,{},protocol,course)
    assert not reloaded.manifest['committed']
    reloaded.commit('a'*64,'full',full,recipe)
    with pytest.raises(ValueError,match='Both Replay'):reloaded.sample(np.random.default_rng(1))
    reloaded.commit('b'*64,'late',late)
    path=tmp_path/'episodes'/('a'*64+'.json.gz');path.write_bytes(b'corrupt')
    with pytest.raises(Exception):MixedReplay(tmp_path,{},protocol,course)


class FakeBackend:
    """State-machine fault injection only; never claims network evidence."""
    def __init__(self,root,fail=None):self.root=root;self.binding={'test':1};self.fail=fail
    def digest(self,path):return content_hash(json.loads((self.root/path).read_text()))
    def check(self,state):
        for p,d in state['artifacts'].items():assert self.digest(p)==d
    def initialize(self):atomic_json(self.root/'initial.json',{});return 'initial.json'
    def collect(self,i,j,c):
        atomic_json(self.root/f'job-{i}-{j}.json',{'champion':c})
        if self.fail==('collect',i,j):raise RuntimeError('injected')
    def update(self,i,u,c,previous):
        path=f'update-{i}-{u}.json';atomic_json(self.root/path,{'previous':previous,'champion':c})
        if self.fail==('update',i,u):raise RuntimeError('injected')
        return path
    def compare(self,i,c,n):
        path=f'eval-{i}.json';result={'promote':i==0};atomic_json(self.root/path,result)
        if self.fail==('evaluate',i,0):raise RuntimeError('injected')
        return result,path


@pytest.mark.parametrize('failure',[('collect',0,2),('update',0,1),('evaluate',0,0)])
def test_state_machine_recovers_boundary_without_extra_updates(tmp_path,failure):
    p={'rounds':2,'full_episodes':3,'late_episodes':1,'updates':2}
    root=tmp_path/'restart';root.mkdir()
    with pytest.raises(RuntimeError):drive(root,p,FakeBackend(root,failure))
    resumed=drive(root,p,FakeBackend(root))
    clean=tmp_path/'clean';clean.mkdir();reference=drive(clean,p,FakeBackend(clean))
    assert resumed==reference and resumed['phase']=='done'
    assert len(list(root.glob('update-*.json')))==4
    assert drive(root,p,FakeBackend(root))==resumed


def test_cli_no_flag_cannot_start(tmp_path,monkeypatch):
    from scripts.run_az_transformer_t4 import main
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):main(['smoke','--root',str(tmp_path/'never-created')])
    assert not (tmp_path/'never-created').exists()


def test_production_collection_forwards_correct_absolute_limits(inputs,tmp_path,monkeypatch):
    import sts2_env.az.t4_runner as module
    protocol,course=inputs;p=plan(protocol,course,'smoke',41)
    backend=module.Backend(tmp_path,p,protocol,course)
    monkeypatch.setattr(backend,'load',lambda path:(None,{'model_version':'test'}))
    monkeypatch.setattr(backend,'digest',lambda path:'digest')
    def inspect(job,model):
        assert job.limits.max_decisions==400 and job.limits.max_turns==100
        assert job.simulations==8 and job.reward_version==V7
        raise RuntimeError('stop before collection')
    monkeypatch.setattr(module,'collect_entity_episode',inspect)
    with pytest.raises(RuntimeError,match='stop before'):backend.collect(0,0,'unused.pt')
    assert not backend.replay.manifest['committed']


def test_real_optimizer_boundary_resume_matches_uninterrupted(inputs,records,tmp_path):
    import torch
    from sts2_env.az.t4_runner import Backend
    from sts2_env.az.learner import Learner
    from sts2_env.az.config import derive_seed
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    protocol,course=inputs;full,late,recipe=records
    # Tiny XS unit fixture only: no S experiment or orchestrated collection/evaluation.
    p=plan(protocol,course,'smoke',41)
    p.update(tier='XS',batch_full=2,batch_late=1,microbatch=1)
    backend=Backend(tmp_path,p,protocol,course);initial=backend.initialize()
    backend.replay.commit('a'*64,'full',full,recipe);backend.replay.commit('b'*64,'late',late)
    model,_=backend.load(initial);reference=Learner(model,p['learning_rate'],p['weight_decay'])
    for index in range(2):
        samples=backend.replay.sample(np.random.default_rng(derive_seed(41,0,index,'mixed-batch')),2,1)
        torch.manual_seed(derive_seed(41,0,index,'update-torch'))
        reference.update(samples,1)
    first=backend.update(0,0,initial,None)
    restarted=Backend(tmp_path,p,protocol,course)
    second=restarted.update(0,1,initial,first)
    actual,payload=restarted.load(second)
    assert payload['training_state']['updates']==2
    for name,value in actual.state_dict().items():assert torch.equal(value,reference.model.state_dict()[name]),name
    with pytest.raises(ValueError,match='boundary'):restarted.update(0,2,initial,first)


def test_disk_reserve_stops_instead_of_changing_budget(tmp_path,monkeypatch):
    import shutil
    from sts2_env.az.t4_runner import check_disk
    monkeypatch.setattr(shutil,'disk_usage',lambda p:SimpleNamespace(free=1))
    with pytest.raises(RuntimeError,match='disk reserve'):check_disk(tmp_path,2)


def test_validation_cache_is_network_only_and_detects_corruption(inputs,tmp_path,monkeypatch):
    import sts2_env.az.t4_runner as module
    protocol,course=inputs;p=plan(protocol,course,'smoke',41)
    backend=module.Backend(tmp_path,p,protocol,course);calls=[]
    monkeypatch.setattr(backend,'load',lambda path:(None,{'model_version':path}))
    monkeypatch.setattr(backend,'digest',lambda path:content_hash(path))
    def fake_evaluate(model,version,recipes,**kwargs):
        assert kwargs['simulations']==0 and kwargs['reward_version']==V7
        assert len(recipes)==1 and recipes[0].split=='validation'
        calls.append(version);r=recipes[0]
        return [dict(scenario_id=r.scenario_id,initial_hp=r.player_hp,family_id=r.family_id,encounter_id=r.encounter_id)]
    monkeypatch.setattr(module,'evaluate',fake_evaluate)
    monkeypatch.setattr(module,'network_gate',lambda *args,**kwargs:{'promote':False})
    backend.compare(0,'old','new');assert len(calls)==512
    backend.compare(0,'old','new');assert len(calls)==512
    path=next((tmp_path/'evaluation-cache').glob('*.json'));value=json.loads(path.read_text())
    value['row']['initial_hp']=-1;atomic_json(path,value)
    with pytest.raises(ValueError,match='cache corruption'):backend.compare(0,'old','new')


@pytest.mark.parametrize('round_pass,final_pass',[(False,False),(True,False),(False,True)])
def test_formal_requires_audited_smoke_before_creating_run(inputs,tmp_path,monkeypatch,round_pass,final_pass):
    import scripts.run_az_transformer_t4 as cli
    protocol,course=inputs;doc={'plans':{'41':plan(protocol,course,'smoke',41)}}
    monkeypatch.setattr(cli,'PREPARATION',tmp_path/'preparation')
    atomic_json(cli.PREPARATION/'execution.json',doc)
    monkeypatch.setattr(cli,'documents',lambda:(doc,protocol,course))
    monkeypatch.setattr(cli,'audit',lambda *args:{'all_network_gates_passed':round_pass,'network_utility_accepted':final_pass})
    run=tmp_path/'must-not-exist'
    with pytest.raises(ValueError,match='Formal blocked'):
        cli.main(['formal','--root',str(run),'--smoke-root','unused','--allow-experiment'])
    assert not run.exists()


def test_joint_champion_freeze_precedes_all_heldout_execution(inputs,tmp_path,monkeypatch):
    import sts2_env.az.t4_runner as module
    import sts2_env.az.evaluation as evaluation
    protocol,course=inputs;plans={str(s):plan(protocol,course,'formal',s) for s in (42,43)}
    for seed in (42,43):
        folder=tmp_path/f'seed-{seed}'
        atomic_json(folder/'state.json',{'champion':'candidate.pt'})
        atomic_json(folder/'candidate.pt',{'seed':seed});atomic_json(folder/'initial.pt',{'initial':seed})
    def incomplete(root,*args):
        if str(root).endswith('43'):raise ValueError('second seed incomplete')
    monkeypatch.setattr(module,'audit',incomplete)
    with pytest.raises(ValueError,match='incomplete'):module.finalize_holdouts(tmp_path,plans,protocol,course)
    assert not (tmp_path/'frozen_champions.json').exists()
    monkeypatch.setattr(module,'audit',lambda *args:{})
    calls=[]
    class Fake:
        def __init__(self,*args):pass
        def evaluate_rows(self,checkpoint,records):
            frozen=json.loads((tmp_path/'frozen_champions.json').read_text())
            assert set(frozen)=={'42','43'} and all(r['split']=='test' for r in records)
            calls.extend(r['scenario_id'] for r in records)
            return [{'scenario_id':r['scenario_id']} for r in records]
    monkeypatch.setattr(module,'Backend',Fake)
    monkeypatch.setattr(evaluation,'promotion_gate',lambda *args,**kwargs:{'clean':True,'mean_utility_difference':0.})
    monkeypatch.setattr(evaluation,'summarize',lambda rows:{'count':len(rows)})
    evidence=module.finalize_holdouts(tmp_path,plans,protocol,course)
    assert len(calls)==192 and evidence['network_battles']==192 and not evidence['used_for_promotion']
    atomic_json(tmp_path/'seed-43/candidate.pt',{'changed':True})
    with pytest.raises(ValueError,match='champions changed'):module.finalize_holdouts(tmp_path,plans,protocol,course)


def test_replay_resident_cache_is_bounded(inputs,records,tmp_path):
    protocol,course=inputs;full,late,recipe=records
    replay=MixedReplay(tmp_path,{},protocol,course)
    for index in range(18):replay.commit(f'{index:064x}','full',full,recipe)
    assert len(replay.cache)<=16 and replay.size('full')==18*len(full['rows'])
    restored=MixedReplay(tmp_path,{},protocol,course)
    assert len(restored.cache)<=16 and len(restored.manifest['active']['full'])==18


def test_execution_document_matches_current_source_and_budget():
    from scripts.run_az_transformer_t4 import documents,PREPARATION
    doc,_,_=documents()
    assert doc==json.loads((PREPARATION/'execution.json').read_text(encoding='utf-8'))
    assert doc['training_started'] is False
    assert doc['plans']['41']['updates']==4 and doc['plans']['42']['updates']==16
