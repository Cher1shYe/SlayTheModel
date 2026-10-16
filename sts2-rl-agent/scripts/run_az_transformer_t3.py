"""Explicit T3 smoke/formal orchestration and read-only smoke verification.

No work starts on import. CLI requires a mode and explicit experiment flag.
"""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import math
from pathlib import Path
import platform
import sys
from threading import Event, Thread
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch

from scripts.prepare_az_transformer_t3 import documents,config
from sts2_env.az.config import atomic_json,content_hash,EpisodeLimits
from sts2_env.az.coordinator import Coordinator
from sts2_env.az.entity_replay import EntityReplayBuffer,unpack_observation
from sts2_env.az.entity_transition import public_from_dict
from sts2_env.az.evaluation import compare,evaluate_parallel,promotion_gate,summarize,stratified_pairs
from sts2_env.az.model_factory import load_transformer_checkpoint
from sts2_env.az.network import code_digest
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.rewards import V6
from sts2_env.az.run_lock import RunLock
from sts2_env.az.scenarios import save_manifest,load_manifest
from sts2_env.az.self_play import Collector,file_digest
from sts2_env.az.transformer_course import generate,preparation_manifest,configuration


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def frozen(path,value):
    if Path(path).exists():
        if content_hash(read(path))!=content_hash(value): raise ValueError(f'Frozen artifact changed: {path}')
    else: atomic_json(path,value)


def binding(preparation):
    expected=documents()
    if any(read(Path(preparation)/name)!=value for name,value in expected.items()):
        raise ValueError('Preparation differs from current frozen protocol/code')
    return dict(version='transformer-t3-run-v1',plan_hash=content_hash(expected),code_digest=code_digest(),
        runner_digest=file_digest(__file__),prepare_digest=file_digest(Path(__file__).with_name('prepare_az_transformer_t3.py')),
        runtime=dict(python=platform.python_version(),torch=str(torch.__version__),numpy=np.__version__))


def finite(value):
    if isinstance(value,float) and not math.isfinite(value): raise ValueError('Nonfinite training history')
    if isinstance(value,dict):
        for v in value.values(): finite(v)
    if isinstance(value,(list,tuple)):
        for v in value: finite(v)


def checkpoint(path,c):
    model,payload=load_transformer_checkpoint(path,'S',BOSS_CONTENT,V6)
    del model
    if payload['code_digest']!=code_digest() or payload['run_config']!=asdict(c) or payload['torch_version']!=str(torch.__version__):
        raise ValueError('Checkpoint implementation/config mismatch')
    return payload


def verify_rows(rows,records,c):
    by_id={r['scenario_id']:r for r in records}
    if len(rows)!=len(records) or {r['scenario_id'] for r in rows}!=set(by_id):
        raise ValueError('Evaluation recipe mismatch')
    if any(any(row[k]!=by_id[row['scenario_id']][k] for k in ('family_id','encounter_id'))
           or row['initial_hp']!=by_id[row['scenario_id']]['player_hp']
           or row.get('reward_version')!=V6 or row.get('search_version')!=c.search_version for row in rows):
        raise ValueError('Evaluation metadata mismatch')


def audit_seed(root,c):
    """Recompute completion from underlying artifacts, never trust a passed flag."""
    root=Path(root)
    if any((root/'errors').rglob('*.json')): raise ValueError('Run has error artifacts')
    state=read(root/'state.json')
    runtime=dict(python=platform.python_version(),torch=str(torch.__version__),numpy=np.__version__,
                 cpu_threads=1,deterministic_algorithms=True)
    if (state['config']!=asdict(c) or state['phase']!='done' or state['iteration']!=c.iterations or state['runtime']!=runtime
            or state.get('round_failed') or state['code_digest']!=code_digest()):
        raise ValueError('Incomplete/incompatible seed run')
    smoke=c.iterations==2
    expected_manifest=json.loads(json.dumps([r.to_dict() for r in preparation_manifest(smoke)]))
    if read(root/'recipes.json')!=expected_manifest or state['manifest_hash']!=content_hash(expected_manifest):
        raise ValueError('Seed manifest mismatch')
    validation=[r for r in expected_manifest if r['split']=='validation']
    from sts2_env.az.scenarios import CombatScenario
    if read(root/'generator.json')!=configuration(smoke): raise ValueError('Generator mismatch')
    initial=checkpoint(root/'initial.pt',c)
    if initial['statistics'].get('initialization')!={}: raise ValueError('T3 must initialize independently')
    champion='initial.pt'
    champion_version=initial['model_version']
    rounds=[]
    # Capacity 1 avoids loading the active replay into RAM; audit each committed file below.
    replay=EntityReplayBuffer(root/'audit-unused',capacity=1,content_version=BOSS_CONTENT,reward_version=V6)
    replay.directory=root/'replay'
    manifest=read(replay.directory/'manifest.json')
    if manifest['compatibility']!=replay.compatibility or manifest['capacity']!=c.capacity:
        raise ValueError('Replay compatibility mismatch')
    expected_ids={content_hash([c.seed,i,str(j)]) for i in range(c.iterations) for j in range(180)}
    if set(manifest['committed'])!=expected_ids or not set(manifest['active'])<=expected_ids:
        raise ValueError('Incomplete/extra committed episodes')
    decisions,max_entities,max_actions=0,0,0
    phases=set()
    timeouts=[]
    for i in range(c.iterations):
        round_decisions=0; round_entities=0; round_actions=0; round_phases=set(); round_timeouts=[]
        recipes=[generate(c.seed,i,j,smoke=smoke) for j in range(180)]
        if load_manifest(root/f'manifests/train-{i}.json')!=recipes: raise ValueError('Training recipe mismatch')
        for j,recipe in enumerate(recipes):
            identity=content_hash([c.seed,i,str(j)])
            episode=replay.read_episode(identity)
            replay.validate(episode)
            if (replay.digest(episode)!=manifest['committed'][identity] or episode['iteration']!=i
                    or episode['job_id']!=str(j) or episode['rows'][0]['scenario_id']!=recipe.scenario_id
                    or episode['rows'][0]['model_version']!=champion_version):
                raise ValueError('Episode checksum/coordinates mismatch')
            if episode['outcome']['termination_reason']=='time_limit': timeouts.append(identity); round_timeouts.append(identity)
            decisions+=len(episode['rows'])
            round_decisions+=len(episode['rows'])
            for row in episode['rows']:
                if not row['forced_action'] and row['search_simulations']!=c.simulations:
                    raise ValueError('Collection search budget mismatch')
                obs=unpack_observation(row['observation'])
                max_entities=max(max_entities,len(obs.entities)); max_actions=max(max_actions,len(obs.actions))
                round_entities=max(round_entities,len(obs.entities)); round_actions=max(round_actions,len(obs.actions))
                public=public_from_dict(row['public_information'])
                if public.boss: phases.add(public.boss.phase.cursor[0]); round_phases.add(public.boss.phase.cursor[0])
                if public.limits!=EpisodeLimits(): raise ValueError('Nonstandard episode budget')
        candidate=f'candidate-{i}.pt'
        payload=checkpoint(root/candidate,c)
        if payload['iteration']!=i: raise ValueError('Candidate iteration mismatch')
        history=payload['statistics']['history']
        finite(history)
        if len(history)!=c.updates or [h['update'] for h in history]!=list(range(1,c.updates+1)):
            raise ValueError('Incomplete candidate updates')
        if any(sum(h['family_counts'].values())!=c.batch_size for h in history):
            raise ValueError('Effective training batch mismatch')
        training=checkpoint(root/f'training-{i}.pt',c)
        boundary=training.get('training_state',{})
        if (boundary.get('updates')!=c.updates or training['statistics']['history']!=history
                or any(not torch.equal(v,training['model_state'][k]) for k,v in payload['model_state'].items())):
            raise ValueError('Training boundary/candidate mismatch')
        if i==c.iterations-1 and boundary.get('replay_hash')!=file_digest(replay.directory/'manifest.json'):
            raise ValueError('Final training boundary Replay mismatch')
        for item in boundary['optimizer']['state'].values():
            if any(torch.is_tensor(v) and not torch.isfinite(v).all() for v in item.values()):
                raise ValueError('Nonfinite optimizer state')
        del training
        report=read(root/f'evaluation-{i}.json')
        for mode in ('network','search'):
            for role in ('champion','candidate'):
                rows=report['modes'][mode][role]
                verify_rows(rows,validation,c)
        rebuilt=compare(None,None,'audit','audit',[CombatScenario.from_dict(r) for r in validation],
            simulations=c.eval_simulations,reward_version=V6,search_version=c.search_version,
            promotion_policy=c.promotion_policy,evaluation_runner=lambda role,b:report['modes']['network' if b==0 else 'search'][role])
        if rebuilt!=report or not all(m['gate']['clean'] for m in rebuilt['modes'].values()):
            raise ValueError('Evaluation gate/summary/integrity mismatch')
        if report['promote']: champion=candidate; champion_version=payload['model_version']
        rounds.append(dict(iteration=i,promote=report['promote'],network=report['modes']['network']['gate'],
                           search=report['modes']['search']['gate'],decisions=round_decisions,max_entities=round_entities,
                           max_actions=round_actions,boss_phases=sorted(round_phases),timeout_episode_ids=round_timeouts))
    if state['champion']!=champion or state['champion_hash']!=file_digest(root/champion):
        raise ValueError('Champion does not follow recomputed network utility gates')
    if state['candidate_hash']!=file_digest(root/f'candidate-{c.iterations-1}.pt'):
        raise ValueError('Final candidate checksum mismatch')
    artifacts={str(p.relative_to(root)).replace('\\','/'):file_digest(p) for p in sorted(root.rglob('*'))
        if p.is_file() and (p.suffix=='.pt' or p.name in ('state.json','recipes.json','generator.json','manifest.json')
            or p.name.startswith('evaluation-') or p.parent.name in ('episodes','manifests'))}
    return dict(rounds=rounds,episodes=len(expected_ids),updates=c.iterations*c.updates,decisions=decisions,
        max_entities=max_entities,max_actions=max_actions,boss_phases=sorted(phases),timeout_episode_ids=timeouts,
        initial='initial.pt',initial_sha256=file_digest(root/'initial.pt'),final=champion,
        final_sha256=file_digest(root/champion),artifacts=artifacts)


def verify_smoke(evidence,preparation):
    evidence=Path(evidence).resolve()
    root=evidence.parent
    expected=binding(preparation)
    report=read(evidence)
    if (report.get('status')!='passed' or report.get('test_evaluated')is not False or report.get('binding')!=expected
            or read(root/'run.json')!=dict(binding=expected,mode='smoke',smoke_evidence=None)
            or (root/'error.json').exists() or (root/'frozen_final_models.json').exists()):
        raise ValueError('Smoke evidence is stale, failed or incompatible')
    usage=report.get('resources',{})
    if any(not isinstance(usage.get(k),(int,float)) or not math.isfinite(usage[k]) or usage[k]<=0
           for k in ('seconds','peak_process_tree_rss_bytes')):
        raise ValueError('Missing/invalid smoke resource measurements')
    if content_hash([r.to_dict() for r in load_manifest(root/'manifest.json')])!=content_hash(read(Path(preparation)/'smoke-manifest.json')):
        raise ValueError('Smoke run manifest mismatch')
    actual=audit_seed(root/'seed-42',config(smoke=True))
    if report.get('audit')!=actual or report.get('resources')!=read(root/'resources.json'):
        raise ValueError('Smoke evidence does not match underlying artifacts')
    if report.get('timings_sha256')!=file_digest(root/'timings.json'): raise ValueError('Smoke timings changed')
    return file_digest(evidence)


class Resources:
    def __init__(self,previous=None):
        self.previous=previous or {}
    def __enter__(self):
        import psutil
        self.process=psutil.Process(); self.stop=Event(); self.start=perf_counter(); self.peak=self.previous.get('peak_process_tree_rss_bytes',0)
        def sample():
            while not self.stop.is_set():
                total=0
                try: processes=[self.process,*self.process.children(recursive=True)]
                except psutil.Error: processes=[self.process]
                for p in processes:
                    try: total+=p.memory_info().rss
                    except psutil.Error: pass
                self.peak=max(self.peak,total)
                self.stop.wait(.2)
        self.thread=Thread(target=sample,daemon=True); self.thread.start()
        return self
    def snapshot(self):
        return dict(seconds=self.previous.get('seconds',0)+perf_counter()-self.start,peak_process_tree_rss_bytes=self.peak,
                    measurement='200 ms sampled sum RSS; shared pages may be counted twice')
    def __exit__(self,*args):
        self.stop.set(); self.thread.join()


def final_evaluation(root,frozen_models,pool,c):
    # Both champions are frozen BEFORE this function is called or any test recipe exists.
    if read(root/'frozen_final_models.json')!=frozen_models: raise ValueError('Missing joint champion freeze')
    for paths in frozen_models.values():
        for role in ('initial','final'):
            if file_digest(root/paths[role])!=paths[role+'_sha256']: raise ValueError('Frozen model changed')
    recipes=[generate(287,0,j,'test') for j in range(216)]
    path=root/'test-manifest.json'
    if path.exists():
        if load_manifest(path)!=recipes: raise ValueError('Final manifest changed')
    else: save_manifest(path,recipes)
    reports={}
    for seed,paths in frozen_models.items():
        reports[seed]={}
        for mode,budget in (('network',0),('search',c.eval_simulations)):
            old,new=[evaluate_parallel(pool,root/paths[role],recipes,budget,123,EpisodeLimits(),
                root/'test_cache',reward_version=V6,search_version=c.search_version) for role in ('initial','final')]
            for rows in (old,new): verify_rows(rows,[r.to_dict() for r in recipes],c)
            gate=promotion_gate(old,new,required_count=216,reward_version=V6,criterion='utility-only-v1')
            if not gate['clean']: raise ValueError('Unclean final evaluation')
            result=dict(initial=old,final=new,initial_summary=summarize(old),final_summary=summarize(new),
                        paired=gate,strata=stratified_pairs(old,new))
            frozen(root/f'test-{seed}-{mode}.json',result)
            reports[seed][mode]=gate
    return dict(engineering='passed',learning_gain='passed' if all(r['network']['promote'] for r in reports.values()) else 'not_met',
                acceptance='network-utility-v1',quality_acceptance='not_claimed',seeds=reports)


def run(output,preparation,mode,smoke_evidence=None):
    if mode not in ('smoke','formal'): raise ValueError('Explicit smoke/formal mode required')
    if mode=='smoke' and smoke_evidence is not None: raise ValueError('Smoke cannot inherit another smoke run')
    bound=binding(preparation)
    evidence_hash=verify_smoke(smoke_evidence,preparation) if mode=='formal' and smoke_evidence else None
    if mode=='formal' and evidence_hash is None: raise ValueError('Formal run requires verified smoke evidence')
    root=Path(output).resolve(); preparation=Path(preparation).resolve()
    protected=[preparation]+([Path(smoke_evidence).resolve().parent] if smoke_evidence else [])
    if any(root==p or root in p.parents or p in root.parents for p in protected): raise ValueError('Run directories must be isolated')
    smoke=mode=='smoke'; seeds=(42,) if smoke else (42,43)
    with RunLock(root),ExitStack() as stack:
        root.mkdir(parents=True,exist_ok=True)
        if (root/'error.json').exists(): raise ValueError('Failed run retained; use a new directory')
        if not (root/'run.json').exists() and any(root.iterdir()): raise ValueError('New run requires empty directory')
        frozen(root/'run.json',dict(binding=bound,mode=mode,smoke_evidence=evidence_hash))
        if (root/'smoke_evidence.json').exists() and smoke:
            verify_smoke(root/'smoke_evidence.json',preparation)
            return read(root/'smoke_evidence.json')
        cs={}
        try:
            records=read(preparation/f'{mode}-manifest.json')
            from sts2_env.az.scenarios import CombatScenario
            manifest=root/'manifest.json'
            if manifest.exists():
                    if content_hash([r.to_dict() for r in load_manifest(manifest)])!=content_hash(records): raise ValueError('Run manifest changed')
            else: save_manifest(manifest,[CombatScenario.from_dict(r) for r in records])
            for seed in seeds:
                c=Coordinator(root/f'seed-{seed}',manifest,config(seed,smoke)); cs[seed]=c; stack.callback(c.close)
                c.replay.release_memory()
            with Resources(read(root/'resources.json') if (root/'resources.json').exists() else None) as resource,Collector(config(smoke=smoke).workers) as collector:
                timings=read(root/'timings.json') if (root/'timings.json').exists() else []
                while any(c.state['phase']!='done' for c in cs.values()):
                    for seed,c in cs.items():
                        iteration=c.state['iteration']
                        while c.state['phase']!='done' and c.state['iteration']==iteration:
                            atomic_json(root/'progress.json',dict(mode=mode,seed=seed,iteration=iteration,phase=c.state['phase']))
                            phase=c.state['phase']; started=perf_counter()
                            c.step(collector)
                            timings.append(dict(seed=seed,iteration=iteration,phase=phase,seconds=perf_counter()-started))
                            atomic_json(root/'timings.json',timings)
                            atomic_json(root/'resources.json',resource.snapshot())
                        c.replay.release_memory()
                audits={str(s):audit_seed(root/f'seed-{s}',config(s,smoke)) for s in seeds}
                if smoke:
                    usage=resource.snapshot()
                    usage['audited_training_decisions_per_active_second']=audits['42']['decisions']/max(usage['seconds'],1e-9)
                    report=dict(status='passed',binding=bound,audit=audits['42'],resources=usage,test_evaluated=False,
                                timings_sha256=file_digest(root/'timings.json'))
                    atomic_json(root/'resources.json',report['resources'])
                    frozen(root/'smoke_evidence.json',report)
                else:
                    frozen_models={s:{role:str(Path(f'seed-{s}')/a[role]).replace('\\','/') for role in ('initial','final')}
                                   |{role+'_sha256':a[role+'_sha256'] for role in ('initial','final')} for s,a in audits.items()}
                    frozen(root/'frozen_final_models.json',frozen_models)
                    report=final_evaluation(root,frozen_models,collector.pool,config())
                    report['training_audits']=audits
                    frozen(root/'report.json',report)
                    atomic_json(root/'resources.json',resource.snapshot())
                atomic_json(root/'progress.json',dict(mode=mode,phase='complete'))
                return report
        except BaseException as exc:
            atomic_json(root/'error.json',dict(error=repr(exc),mode=mode))
            for c in cs.values(): c.state['round_failed']=True; c.persist()
            raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['verify-smoke','smoke','formal'])
    parser.add_argument('--preparation',default='configs/az_transformer_t3_v1')
    parser.add_argument('--output')
    parser.add_argument('--smoke-evidence')
    parser.add_argument('--start-experiment',action='store_true')
    args=parser.parse_args(argv)
    if args.mode=='verify-smoke':
        if not args.smoke_evidence: parser.error('--smoke-evidence required')
        print(verify_smoke(args.smoke_evidence,args.preparation)); return
    if not args.start_experiment or not args.output:
        parser.error('Run modes require --start-experiment and --output; preparation is not authorization')
    run(args.output,args.preparation,args.mode,args.smoke_evidence)


if __name__=='__main__': main()
