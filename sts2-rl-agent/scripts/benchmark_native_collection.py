"""Bounded collection/cache benchmark, with no training or promotion."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def summarize(raws,elapsed,worker_calls):
    steps=[s for r in raws for s in r['steps']]
    searched=[s for s in steps if s['simulations']>0]
    simulations=sum(s['simulations'] for s in searched)
    search_seconds=sum(s['seconds'] for s in searched)
    fight_seconds=sum(r['wallSeconds'] for r in raws)
    return dict(fights=len(raws),decisions=len(steps),searched_decisions=len(searched),
        completed_simulations=simulations,search_seconds=search_seconds,fight_seconds=fight_seconds,
        end_to_end_seconds=elapsed,worker_calls=worker_calls,
        simulations_per_search_second=simulations/search_seconds,
        simulations_per_end_to_end_second=simulations/elapsed,
        simulations_per_searched_decision=simulations/len(searched),
        seconds_per_fight=elapsed/len(raws),projected_296_fight_minutes=elapsed/len(raws)*296/60)


def main():
    from scripts.check_native_collection import sha
    from sts2_env.az.config import atomic_json
    from sts2_env.az.native_generic_backend import NativeBackend
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args(); out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    previous=Path('output/native_scope_final_20261019')
    aggregate=json.loads((previous/'aggregate-report.json').read_text())
    selections=[('fixed','GLOBE_HEAD_NORMAL'),('fixed','THE_OBSCURA_NORMAL'),
                ('upgraded','SLIMES_WEAK'),('fresh','FOGMOG_NORMAL')]
    recipes=[next(r['recipe'] for r in aggregate['cases'] if (r['group'],r['recipe']['encounter'])==key) for key in selections]
    protocol=json.loads((previous/'protocol.json').read_text())
    config=json.loads((previous/'config.json').read_text())
    config['backend']['fights_per_worker']=2
    checkpoint=out/'initial.pt'; shutil.copyfile(previous/'initial.pt',checkpoint)
    atomic_json(out/'recipes.json',recipes); atomic_json(out/'config.json',config); atomic_json(out/'protocol.json',protocol)
    report=dict(formal_training_started=False,updates=0,mode='mixed',value_mix=.5,budget_ms=250,arms={})
    def progress(stage): atomic_json(out/'progress.json',dict(stage=stage,report=report))
    backend=NativeBackend(config['backend'],protocol,out); backend.configure_search('mixed',.5)
    build=out/'build-job.json'
    atomic_json(build,dict(format=backend.format,catalogOutput=str(out/'catalog.json')))
    progress('build')
    start=perf_counter(); backend._execute(build,out/'build.log'); report['build_seconds']=perf_counter()-start
    report['provenance']=backend.provenance
    class InjectedFailure(RuntimeError): pass
    for size in (1,2):
        arm=f'worker_batch_{size}'
        cfg=dict(config['backend'],fights_per_worker=size)
        backend=NativeBackend(cfg,protocol,out); backend.configure_search('mixed',.5); backend.built=True
        original_execute=backend._execute; calls=[]; injected=False; saved={}
        directory=out/arm
        def execute(job,log):
            nonlocal injected
            spec=json.loads(job.read_text())
            original_execute(job,log)
            calls.append([c['recipe']['scenario_id'] for c in spec['cases']])
            if size==2 and not injected:
                injected=True
                raise InjectedFailure('Injected failure after first durable worker batch')
        backend._execute=execute
        progress(arm)
        start=perf_counter()
        try: raws=backend.fights(checkpoint,recipes,directory,'puct')
        except InjectedFailure:
            failed=json.loads((directory/'progress.json').read_text())
            assert failed['completed']==2 and failed['pending']==2
            for r in recipes[:2]:
                p=directory/f"{r['scenario_id']}.json"; saved[str(p)]=(sha(p),p.stat().st_mtime_ns)
            # New backend instance represents a restarted caller; old worker has exited.
            backend=NativeBackend(cfg,protocol,out); backend.configure_search('mixed',.5); backend.built=True
            fresh_execute=backend._execute
            def resume_execute(job,log):
                spec=json.loads(job.read_text()); fresh_execute(job,log)
                calls.append([c['recipe']['scenario_id'] for c in spec['cases']])
            backend._execute=resume_execute
            raws=backend.fights(checkpoint,recipes,directory,'puct')
            assert all((sha(p),Path(p).stat().st_mtime_ns)==v for p,v in saved.items())
            report['failure_resume']=dict(cached_reused=2,remaining_collected=2,files_unchanged=True)
        elapsed=perf_counter()-start
        assert len([x for call in calls for x in call])==len(recipes)
        report['arms'][arm]=summarize(raws,elapsed,len(calls))
        if size==2:
            def forbidden(*args): raise AssertionError('Cache hit started a worker')
            backend._execute=forbidden
            before={str(directory/f"{r['scenario_id']}.json"):(sha(directory/f"{r['scenario_id']}.json"),(directory/f"{r['scenario_id']}.json").stat().st_mtime_ns) for r in recipes}
            hit=perf_counter(); cached=backend.fights(checkpoint,recipes,directory,'puct')
            report['cache_hit_seconds']=perf_counter()-hit
            assert cached==raws and all((sha(p),Path(p).stat().st_mtime_ns)==v for p,v in before.items())
        progress(arm+'_completed')
    atomic_json(out/'report.json',report); progress('completed')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
