"""Orchestrator tests use fake coordinators/collectors, never train S smoke."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import pytest
from scripts import run_az_transformer_t3 as runner
from scripts.prepare_az_transformer_t3 import prepare,config
from sts2_env.az.config import atomic_json


@pytest.fixture
def preparation(tmp_path):
    p=tmp_path/'preparation'; prepare(p); return p


@pytest.mark.parametrize('argv',[[],['smoke'],['formal','--output','unused']])
def test_cli_never_starts_implicitly(monkeypatch,argv):
    monkeypatch.setattr(runner,'run',lambda *a:pytest.fail('Implicit run'))
    with pytest.raises(SystemExit): runner.main(argv)


def test_formal_requires_evidence_before_creating_output(preparation,tmp_path):
    with pytest.raises(ValueError,match='verified smoke'):
        runner.run(tmp_path/'formal',preparation,'formal')
    assert not (tmp_path/'formal').exists()


def smoke_fixture(root,preparation,monkeypatch):
    root.mkdir()
    (root/'payload').write_text('original')
    bound=runner.binding(preparation)
    atomic_json(root/'run.json',dict(binding=bound,mode='smoke',smoke_evidence=None))
    from sts2_env.az.scenarios import CombatScenario,save_manifest
    save_manifest(root/'manifest.json',[CombatScenario.from_dict(r) for r in runner.read(preparation/'smoke-manifest.json')])
    audit=lambda *a:dict(hash=runner.file_digest(root/'payload'))
    monkeypatch.setattr(runner,'audit_seed',audit)
    usage=dict(seconds=1.,peak_process_tree_rss_bytes=100)
    atomic_json(root/'resources.json',usage)
    evidence=root/'smoke_evidence.json'
    atomic_json(root/'timings.json',[])
    atomic_json(evidence,dict(status='passed',binding=bound,audit=audit(),resources=usage,test_evaluated=False,
                             timings_sha256=runner.file_digest(root/'timings.json')))
    return evidence


@pytest.mark.parametrize('change',['stale','failed','missing','tampered','runtime','resources','test'])
def test_smoke_evidence_rejects_invalid_artifacts(preparation,tmp_path,monkeypatch,change):
    path=smoke_fixture(tmp_path/'smoke',preparation,monkeypatch)
    assert runner.verify_smoke(path,preparation)==runner.file_digest(path)
    report=runner.read(path)
    if change=='stale': report['binding']['code_digest']='stale'
    elif change=='failed': atomic_json(path.parent/'error.json',{'error':'failed'})
    elif change=='missing': (path.parent/'payload').unlink()
    elif change=='tampered': (path.parent/'payload').write_text('changed')
    elif change=='runtime': report['binding']['runtime']['torch']='different'
    elif change=='resources': report['resources']['seconds']=0
    elif change=='test': report['test_evaluated']=True
    atomic_json(path,report)
    with pytest.raises((ValueError,FileNotFoundError)): runner.verify_smoke(path,preparation)


def fake_backend(monkeypatch,events,fail=False):
    class Replay:
        def release_memory(self): events.append('release')
    class Coordinator:
        def __init__(self,root,manifest,c):
            self.root=Path(root); self.root.mkdir(exist_ok=True)
            self.config=c; self.replay=Replay()
            path=self.root/'state.json'
            self.state=runner.read(path) if path.exists() else dict(phase='collect',iteration=0)
            (self.root/'initial.pt').write_bytes(b'fake initial')
            (self.root/'candidate.pt').write_bytes(b'fake candidate')
            events.append(('init',c.seed)); self.persist()
        def step(self,collector):
            if fail: raise RuntimeError('injected failure')
            events.append(('step',self.config.seed,self.state['iteration']))
            self.state['iteration']+=1
            if self.state['iteration']==self.config.iterations: self.state['phase']='done'
            self.persist()
        def persist(self): atomic_json(self.root/'state.json',self.state)
        def close(self): events.append(('close',self.config.seed))
    class Collector:
        pool=None
        def __init__(self,*a): pass
        def __enter__(self): return self
        def __exit__(self,*a): events.append('collector_closed')
    class Resources:
        def __init__(self,*a): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def snapshot(self): return dict(seconds=1.,peak_process_tree_rss_bytes=100)
    def audit(root,c):
        events.append(('audit',c.seed))
        assert runner.read(root/'state.json')['phase']=='done'
        return dict(initial='initial.pt',final='candidate.pt',initial_sha256=runner.file_digest(root/'initial.pt'),
            final_sha256=runner.file_digest(root/'candidate.pt'),decisions=10)
    monkeypatch.setattr(runner,'Coordinator',Coordinator)
    monkeypatch.setattr(runner,'Collector',Collector)
    monkeypatch.setattr(runner,'Resources',Resources)
    monkeypatch.setattr(runner,'audit_seed',audit)


def test_smoke_orchestration_no_final_tests_and_idempotent(preparation,tmp_path,monkeypatch):
    events=[]; fake_backend(monkeypatch,events)
    monkeypatch.setattr(runner,'final_evaluation',lambda *a:pytest.fail('Smoke accessed test'))
    root=tmp_path/'smoke'
    result=runner.run(root,preparation,'smoke')
    assert result['status']=='passed' and result['test_evaluated'] is False
    assert len([e for e in events if isinstance(e,tuple) and e[0]=='step'])==2
    assert runner.run(root,preparation,'smoke')==result
    assert len([e for e in events if isinstance(e,tuple) and e[0]=='step'])==2


def test_formal_interleaves_freezes_both_before_testing(preparation,tmp_path,monkeypatch):
    events=[]; fake_backend(monkeypatch,events)
    smoke=tmp_path/'smoke'; runner.run(smoke,preparation,'smoke'); events.clear()
    def final(root,frozen,pool,c):
        assert set(frozen)=={'42','43'}
        assert runner.read(root/'frozen_final_models.json')==frozen
        assert ('audit',42) in events and ('audit',43) in events
        return {'engineering':'passed','learning_gain':'not_met'}
    monkeypatch.setattr(runner,'final_evaluation',final)
    root=tmp_path/'formal'
    runner.run(root,preparation,'formal',smoke/'smoke_evidence.json')
    steps=[e[1:] for e in events if isinstance(e,tuple) and e[0]=='step']
    assert steps==[(42,0),(43,0),(42,1),(43,1),(42,2),(43,2)]
    events.clear()
    runner.run(root,preparation,'formal',smoke/'smoke_evidence.json')
    assert not any(isinstance(e,tuple) and e[0]=='step' for e in events)


def test_failure_stops_no_evidence_and_closes(preparation,tmp_path,monkeypatch):
    events=[]; fake_backend(monkeypatch,events,fail=True)
    root=tmp_path/'failed'
    with pytest.raises(RuntimeError,match='injected'): runner.run(root,preparation,'smoke')
    assert (root/'error.json').exists() and not (root/'smoke_evidence.json').exists()
    assert ('close',42) in events and 'collector_closed' in events
    with pytest.raises(ValueError,match='Failed run'): runner.run(root,preparation,'smoke')


def test_final_generation_requires_joint_freeze(tmp_path,monkeypatch):
    monkeypatch.setattr(runner,'generate',lambda *a:pytest.fail('Generated before freeze'))
    with pytest.raises(FileNotFoundError): runner.final_evaluation(tmp_path,{},None,config())


def test_real_auditor_rejects_incomplete_run(tmp_path):
    c=config(smoke=True)
    atomic_json(tmp_path/'state.json',dict(config=asdict(c),phase='collect',iteration=0,runtime={}))
    with pytest.raises(ValueError,match='Incomplete'): runner.audit_seed(tmp_path,c)


def audit_fixture(root,monkeypatch):
    """Synthetic artifacts isolate the auditor. Replay/network contracts tested separately."""
    import torch
    from types import SimpleNamespace
    from sts2_env.az.config import content_hash,EpisodeLimits
    from sts2_env.az.transformer_course import preparation_manifest,configuration,generate
    from sts2_env.az.scenarios import save_manifest
    c=config(smoke=True)
    records=[r.to_dict() for r in preparation_manifest(True)]
    root.mkdir()
    for f in ['initial.pt','candidate-0.pt','candidate-1.pt','training-0.pt','training-1.pt']:
        (root/f).write_text('synthetic fixture')
    atomic_json(root/'recipes.json',records); atomic_json(root/'generator.json',configuration(True))
    atomic_json(root/'state.json',dict(config=asdict(c),phase='done',iteration=2,round_failed=False,
        code_digest=runner.code_digest(),manifest_hash=content_hash(records),champion='initial.pt',
        champion_hash=runner.file_digest(root/'initial.pt'),runtime=dict(python=runner.platform.python_version(),
        torch=str(torch.__version__),numpy=runner.np.__version__,cpu_threads=1,deterministic_algorithms=True),
        candidate_hash=runner.file_digest(root/'candidate-1.pt')))
    committed={}
    episodes={}
    for i in range(2):
        recipes=[generate(42,i,j,smoke=True) for j in range(180)]
        save_manifest(root/f'manifests/train-{i}.json',recipes)
        for j,r in enumerate(recipes):
            identity=content_hash([42,i,str(j)])
            episode=dict(iteration=i,job_id=str(j),rows=[dict(scenario_id=r.scenario_id,model_version='initial',
                observation={},public_information={},forced_action=False,search_simulations=4)],outcome={'termination_reason':'death'})
            episodes[identity]=episode; committed[identity]=content_hash(episode)
    atomic_json(root/'replay/manifest.json',dict(compatibility={'synthetic':True},capacity=c.capacity,
                                               committed=committed,active=list(committed)))
    class Replay:
        compatibility={'synthetic':True}
        def __init__(self,*a,**kw): pass
        def read_episode(self,identity): return episodes[identity]
        def validate(self,episode): assert episode['rows']
        digest=staticmethod(content_hash)
    monkeypatch.setattr(runner,'EntityReplayBuffer',Replay)
    monkeypatch.setattr(runner,'unpack_observation',lambda o:SimpleNamespace(entities=[0],actions=[0]))
    monkeypatch.setattr(runner,'public_from_dict',lambda o:SimpleNamespace(boss=None,limits=EpisodeLimits()))
    history=[dict(update=j,loss=.1,family_counts={'fixture':32}) for j in range(1,5)]
    def checkpoint(path,c):
        if path.name=='initial.pt': return dict(statistics={'initialization':{}},model_version='initial')
        return dict(iteration=int(path.stem[-1]),statistics={'history':history},model_version='candidate',model_state={'w':torch.tensor(1.)},
            training_state=dict(updates=4,replay_hash=runner.file_digest(root/'replay/manifest.json'),optimizer={'state':{}}))
    monkeypatch.setattr(runner,'checkpoint',checkpoint)
    validation=[r for r in records if r['split']=='validation']
    rows=[dict(scenario_id=r['scenario_id'],family_id=r['family_id'],encounter_id=r['encounter_id'],
               initial_hp=r['player_hp'],reward_version=runner.V6,search_version=c.search_version) for r in validation]
    report=dict(promote=False,modes={m:dict(champion=rows,candidate=rows,gate={'clean':True}) for m in ('network','search')})
    for i in range(2): atomic_json(root/f'evaluation-{i}.json',report)
    monkeypatch.setattr(runner,'compare',lambda *a,**kw:report)
    return c,episodes,history


@pytest.mark.parametrize('change',['none','episode','updates','evaluation','champion','missing_episode','search_budget','batch'])
def test_auditor_recomputes_completion_not_passed_flags(tmp_path,monkeypatch,change):
    root=tmp_path/'seed-42'; c,episodes,history=audit_fixture(root,monkeypatch)
    if change=='episode': next(iter(episodes.values()))['job_id']='wrong'
    elif change=='updates': history.pop()
    elif change=='evaluation':
        report=runner.read(root/'evaluation-0.json'); report['promote']=True; atomic_json(root/'evaluation-0.json',report)
    elif change=='champion':
        state=runner.read(root/'state.json'); state['champion']='candidate-0.pt'; atomic_json(root/'state.json',state)
    elif change=='missing_episode':
        manifest=runner.read(root/'replay/manifest.json'); manifest['committed'].pop(next(iter(episodes)))
        atomic_json(root/'replay/manifest.json',manifest)
    elif change=='search_budget':
        identity=next(iter(episodes)); episodes[identity]['rows'][0]['search_simulations']=8
        manifest=runner.read(root/'replay/manifest.json'); manifest['committed'][identity]=runner.content_hash(episodes[identity])
        atomic_json(root/'replay/manifest.json',manifest)
    elif change=='batch': history[0]['family_counts']['fixture']=64
    if change=='none':
        report=runner.audit_seed(root,c)
        assert report['episodes']==360 and report['updates']==8 and report['decisions']==360
    else:
        with pytest.raises(ValueError): runner.audit_seed(root,c)


def test_final_utility_modes_and_generation_order(tmp_path,monkeypatch):
    frozen={}
    for seed in ('42','43'):
        path=tmp_path/f'{seed}.pt'; path.write_text('synthetic')
        frozen[seed]=dict(initial=path.name,final=path.name,initial_sha256=runner.file_digest(path),final_sha256=runner.file_digest(path))
    atomic_json(tmp_path/'frozen_final_models.json',frozen)
    seen=[]
    def generate(*args):
        from types import SimpleNamespace
        assert runner.read(tmp_path/'frozen_final_models.json')==frozen
        seen.append(args); return SimpleNamespace(to_dict=lambda:dict(scenario_id=str(args[2])))
    monkeypatch.setattr(runner,'generate',generate)
    monkeypatch.setattr(runner,'save_manifest',lambda path,rows:atomic_json(path,[r.to_dict() for r in rows]))
    monkeypatch.setattr(runner,'verify_rows',lambda rows,records,c:None)
    monkeypatch.setattr(runner,'evaluate_parallel',lambda pool,path,recipes,budget,*a,**kw:[{'budget':budget}])
    def gate(a,b,**kw):
        assert kw['criterion']=='utility-only-v1' and kw['required_count']==216
        return dict(clean=True,promote=a[0]['budget']==0)
    monkeypatch.setattr(runner,'promotion_gate',gate)
    monkeypatch.setattr(runner,'summarize',lambda r:{})
    monkeypatch.setattr(runner,'stratified_pairs',lambda a,b:{})
    report=runner.final_evaluation(tmp_path,frozen,None,config())
    assert len(seen)==216 and report['learning_gain']=='passed'
    assert not report['seeds']['42']['search']['promote']


def test_resume_committed_partial_state_without_repeating_round(preparation,tmp_path,monkeypatch):
    from sts2_env.az.scenarios import save_manifest,CombatScenario
    events=[]; fake_backend(monkeypatch,events)
    root=tmp_path/'interrupted'; root.mkdir()
    atomic_json(root/'run.json',dict(binding=runner.binding(preparation),mode='smoke',smoke_evidence=None))
    records=runner.read(preparation/'smoke-manifest.json')
    save_manifest(root/'manifest.json',[CombatScenario.from_dict(r) for r in records])
    atomic_json(root/'seed-42/state.json',dict(phase='collect',iteration=1))
    runner.run(root,preparation,'smoke')
    assert [e for e in events if isinstance(e,tuple) and e[0]=='step']==[('step',42,1)]


def test_evaluation_rows_bind_recipe_and_versions():
    c=config()
    records=[dict(scenario_id='a',family_id='f',encounter_id='e',player_hp=40)]
    rows=[dict(scenario_id='a',family_id='f',encounter_id='e',initial_hp=40,reward_version=runner.V6,search_version=c.search_version)]
    runner.verify_rows(rows,records,c)
    for key in ('scenario_id','family_id','encounter_id','initial_hp','reward_version','search_version'):
        bad=deepcopy(rows); bad[0][key]='wrong'
        with pytest.raises(ValueError): runner.verify_rows(bad,records,c)
