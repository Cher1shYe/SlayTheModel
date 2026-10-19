from copy import deepcopy
import gzip
import json
from pathlib import Path
import pytest
from sts2_env.az.native_generic_backend import NativeBackend
from sts2_env.az.config import atomic_json


def setup(tmp_path,batch=2):
    config=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())['backend']
    config.update(budget_ms=250,fights_per_worker=batch)
    protocol=json.loads(Path('configs/az_native_generic_v1/protocol.json').read_text())
    backend=NativeBackend(config,protocol,tmp_path); backend.configure_search('mixed',.5)
    with gzip.open('tests/fixtures/native_scope_upgraded_v1.json.gz','rt',encoding='utf-8') as f: raws=json.load(f)
    checkpoint=tmp_path/'model.pt'; checkpoint.write_bytes(b'frozen model')
    return backend,raws,checkpoint


def test_generic_partial_worker_failure_survives_new_backend(tmp_path,monkeypatch):
    backend,raws,checkpoint=setup(tmp_path)
    recipes=[r['recipe'] for r in raws]; ran=[]
    def execute(job,log):
        j=json.loads(job.read_text())
        for spec in j['cases']:
            raw=deepcopy(next(r for r in raws if r['recipe']==spec['recipe']))
            raw.update(identity=j['identity'],modelSha256=j['modelSha256'])
            atomic_json(spec['output'],raw); ran.append(spec['recipe']['scenario_id'])
            if len(ran)==1: raise RuntimeError('injected partial batch')
    monkeypatch.setattr(backend,'_execute',execute)
    with pytest.raises(RuntimeError): backend.collect(checkpoint,recipes,tmp_path/'cache')
    progress=json.loads((tmp_path/'cache/progress.json').read_text())
    assert (progress['completed'],progress['pending'])==(1,1)
    backend,_,_=setup(tmp_path); monkeypatch.setattr(backend,'_execute',execute)
    assert len(backend.collect(checkpoint,recipes,tmp_path/'cache'))==2
    assert len(ran)==len(set(ran))==2
    monkeypatch.setattr(backend,'_execute',lambda *a: pytest.fail('cache relaunched worker'))
    backend.collect(checkpoint,recipes,tmp_path/'cache')
    assert json.loads((tmp_path/'cache/progress.json').read_text())['cached_at_start']==2
    checkpoint.write_bytes(b'changed model')
    with pytest.raises(ValueError,match='changed'): backend.collect(checkpoint,recipes,tmp_path/'cache')


@pytest.mark.parametrize('batch',[0,5,True])
def test_invalid_worker_batch_rejected(tmp_path,batch):
    with pytest.raises(ValueError,match='worker budget'): setup(tmp_path,batch)


def test_long_search_budget_rejects_oversized_batch(tmp_path):
    config=json.loads(Path('configs/az_native_generic_v1/config.json').read_text())['backend']
    config.update(budget_ms=1000,fights_per_worker=2)
    protocol=json.loads(Path('configs/az_native_generic_v1/protocol.json').read_text())
    with pytest.raises(ValueError,match='worker budget'): NativeBackend(config,protocol,tmp_path)


def test_malformed_completed_file_is_not_counted(tmp_path,monkeypatch):
    backend,raws,checkpoint=setup(tmp_path)
    def corrupt(job,log):
        spec=json.loads(job.read_text())['cases'][0]
        Path(spec['output']).write_text('{broken')
        raise RuntimeError('interrupted')
    monkeypatch.setattr(backend,'_execute',corrupt)
    with pytest.raises(RuntimeError): backend.collect(checkpoint,[raws[0]['recipe']],tmp_path/'cache')
    progress=json.loads((tmp_path/'cache/progress.json').read_text())
    assert progress['completed']==0 and len(progress['invalid'])==1


def test_parallel_failure_drains_and_resume_reuses_completed_fights(tmp_path,monkeypatch):
    import threading
    backend,raws,checkpoint=setup(tmp_path,batch=1)
    backend.configure_workers(4)
    monkeypatch.setattr(backend,'_prepare_parallel',lambda *a:None)
    barrier=threading.Barrier(2)
    ran=[]
    def execute(job,log):
        j=json.loads(job.read_text()); spec=j['cases'][0]
        barrier.wait(timeout=10)
        ran.append(spec['recipe']['scenario_id'])
        if spec['recipe']==raws[0]['recipe']: raise RuntimeError('parallel failure')
        raw=deepcopy(raws[1]); raw.update(identity=j['identity'],modelSha256=j['modelSha256'])
        atomic_json(spec['output'],raw)
    monkeypatch.setattr(backend,'_execute_parallel',execute)
    recipes=[r['recipe'] for r in raws]
    with pytest.raises(RuntimeError,match='parallel failure'):
        backend.collect(checkpoint,recipes,tmp_path/'cache')
    progress=json.loads((tmp_path/'cache/progress.json').read_text())
    assert progress['completed']==1 and progress['pending']==1 and progress['workers']==4
    saved=tmp_path/'cache'/f"{recipes[1]['scenario_id']}.json"
    before=saved.read_bytes(),saved.stat().st_mtime_ns
    backend,_,_=setup(tmp_path,batch=1) # Resume with one worker is allowed.
    def resume(job,log):
        j=json.loads(job.read_text()); assert len(j['cases'])==1
        assert j['cases'][0]['recipe']==recipes[0]
        raw=deepcopy(raws[0]); raw.update(identity=j['identity'],modelSha256=j['modelSha256'])
        atomic_json(j['cases'][0]['output'],raw)
    monkeypatch.setattr(backend,'_execute',resume)
    episodes=backend.collect(checkpoint,recipes,tmp_path/'cache')
    assert len(episodes)==2 and (saved.read_bytes(),saved.stat().st_mtime_ns)==before
    backend.configure_workers(4)
    monkeypatch.setattr(backend,'_prepare_parallel',lambda *a:pytest.fail('cache hit built worker'))
    assert backend.collect(checkpoint,recipes,tmp_path/'cache')==episodes


@pytest.mark.parametrize('workers',[0,5,True,1.5])
def test_invalid_parallel_count(tmp_path,workers):
    backend,_,_=setup(tmp_path)
    with pytest.raises(ValueError,match='1-4'): backend.configure_workers(workers)


def test_four_worker_bound_no_later_wave_after_failure(tmp_path,monkeypatch):
    import threading
    from sts2_env.az.config import content_hash
    backend,raws,checkpoint=setup(tmp_path,batch=1)
    backend.configure_workers(4)
    monkeypatch.setattr(backend,'_prepare_parallel',lambda *a:None)
    monkeypatch.setattr(backend,'raw_validator',lambda raw:None)
    recipes=[]
    for i in range(6):
        r=dict(raws[0]['recipe']); r.pop('scenario_id'); r['seed']=100+i
        recipes.append(dict(r,scenario_id=content_hash(r)))
    barrier=threading.Barrier(4); ran=[]
    def execute(job,log):
        j=json.loads(job.read_text()); spec=j['cases'][0]
        ran.append(spec['seed']); barrier.wait(timeout=10)
        if spec['seed']==100: raise RuntimeError('first wave failed')
        raw=deepcopy(raws[0]); raw.update(recipe=spec['recipe'],identity=j['identity'],modelSha256=j['modelSha256'])
        atomic_json(spec['output'],raw)
    monkeypatch.setattr(backend,'_execute_parallel',execute)
    with pytest.raises(RuntimeError,match='first wave failed'):
        backend.fights(checkpoint,recipes,tmp_path/'cache','puct')
    assert sorted(ran)==[100,101,102,103]
    p=json.loads((tmp_path/'cache/progress.json').read_text())
    assert (p['completed'],p['pending'])==(3,3)


def test_parallel_build_failure_marks_progress(tmp_path,monkeypatch):
    backend,raws,checkpoint=setup(tmp_path)
    backend.configure_workers(4)
    def failed(*args): raise RuntimeError('build failed')
    monkeypatch.setattr(backend,'_prepare_parallel',failed)
    with pytest.raises(RuntimeError,match='build failed'):
        backend.collect(checkpoint,[raws[0]['recipe']],tmp_path/'cache')
    assert json.loads((tmp_path/'cache/progress.json').read_text())['status']=='failed'
