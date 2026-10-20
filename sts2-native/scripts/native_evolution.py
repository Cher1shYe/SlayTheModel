"""Two-round native policy iteration. External Python simulation/replay is not used."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def summary(rows):
    return dict(n=len(rows), wins=sum(r['Won'] for r in rows),
                mean_hp=sum(r['finalHp'] for r in rows)/len(rows),
                utility=sum(r['outcome'] for r in rows)/len(rows),
                simulations=sum(r['simulations'] for r in rows),
                search_ms=sum(r['searchMs'] for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--game', required=True)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--build', action='store_true')
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    source, initial, output = (Path(v).resolve() for v in (args.source, args.checkpoint, args.output))
    output.mkdir(parents=True, exist_ok=True)
    os.chdir(source)
    sys.path.insert(0, str(source))
    import torch
    torch.set_num_threads(1)
    from sts2_env.az.model_factory import load_transformer_checkpoint, save_transformer_checkpoint
    from sts2_env.az.content import ALL_CONTENT
    from sts2_env.az.rewards import V7
    from sts2_env.az.learner import Learner
    from sts2_env.az.entity_replay import pack_observation
    from native_prior_features import encode_native
    # Freeze before observing any evaluation result. No hyperparameter sweep.
    config = dict(version='native-evolution-v1', initial_sha=digest(initial),
                  information_mode='full-state-search', observation_mode='observable',
                  objective='policy-distillation-only', reward='native-final-v1-policy-only',
                  encounter='BYRDONIS_ELITE', rounds=2, episodes=100, budget_ms=100,
                  updates=100, batch_size=32, learning_rate=0.0003, value_weight=0,
                  training_seeds=[list(range(101,201)),list(range(201,301))],
                  validation_seeds=list(range(1001,1013)), test_seeds=list(range(2001,2013)),
                  hp_cycle=[50,60,70,80], promotion='wins-not-lower-and-mean-utility-gain>0.005',
                  exploration='sample-root-visits-in-turns-1-2',
                  source_digests={str(f.relative_to(source)):digest(f) for f in (source/'sts2_env/az').glob('*.py')},
                  adapter_digests={name:digest(repo/'scripts'/name) for name in
                      ('native_evolution.py','native_prior_features.py','starter_prior_server.py')})
    manifest = output/'config.json'
    if manifest.exists() and read(manifest) != config:
        raise ValueError('Resume configuration/source differs; use a new output directory')
    atomic(manifest, config)
    frozen = output/'initial.pt'
    if not frozen.exists(): shutil.copyfile(initial, frozen)
    if digest(frozen) != config['initial_sha']: raise ValueError('Frozen initial model changed')
    needs_build = args.build
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell: raise ValueError('PowerShell required for native worker')

    def cases(seeds):
        return [dict(seed=s, hp=config['hp_cycle'][i%4]) for i,s in enumerate(seeds)]

    def run_set(name, checkpoint, mode, starts):
        nonlocal needs_build
        all_rows = []
        for offset in range(0,len(starts),8):
            batch = starts[offset:offset+8]
            stem = output/f'{name}-{offset:03d}'
            result, job_path = Path(str(stem)+'.json'), Path(str(stem)+'.job.json')
            job = dict(source=str(source),repo=str(repo),checkpoint=str(checkpoint),mode=mode,
                       budgetMs=config['budget_ms'],cases=batch,output=str(result))
            if job_path.exists() and read(job_path)!=job: raise ValueError('Job resume mismatch')
            atomic(job_path,job)
            valid = False
            if result.exists():
                r = read(result)
                valid = (r['modelSha256']==digest(checkpoint) and len(r['rows'])==len(batch)
                         and [(x['seed'],x['initialHp']) for x in r['rows']]==[(x['seed'],x['hp']) for x in batch])
            if not valid:
                env = os.environ.copy()
                env['STS2_EVOLUTION_JOB']=str(job_path)
                env['FrameworkPathOverride']=str(Path.home()/'.nuget/packages/microsoft.netframework.referenceassemblies.net48/1.0.3/build/.NETFramework/v4.8')
                cmd=[shell,'-NoProfile','-File',str(repo/'scripts/native-worker.ps1'),'-GameDir',args.game,'-Mode','evolution']
                if not needs_build: cmd+=['-SkipBuild']
                with Path(str(stem)+'.log').open('w',encoding='utf-8') as log:
                    subprocess.run(cmd,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT,
                                   check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                needs_build=False
                r=read(result)
            if r['format']!='native-evolution-v1' or r['informationMode']!='full-state-search' or r['reward']!=config['reward']:
                raise ValueError('Native episode contract mismatch')
            if r['modelSha256']!=digest(checkpoint) or len(r['rows'])!=len(batch):
                raise ValueError('Incomplete/mixed-model batch')
            all_rows.extend(r['rows'])
            print(f'{name}: {len(all_rows)}/{len(starts)} '+json.dumps(summary(all_rows)),flush=True)
        return all_rows

    def make_samples(rows):
        samples=[]
        for episode in rows:
            for step in episode['actionsTaken']:
                obs=encode_native(step['observation'])
                keys={a.action_key for a in obs.actions}
                if (set(step['policy'])!=keys or step['action'] not in keys or step['visits']<=0
                    or any(v<0 for v in step['policy'].values()) or abs(sum(step['policy'].values())-1)>1e-6):
                    raise ValueError('Invalid keyed search target')
                samples.append(dict(observation=pack_observation(obs),policy_target=step['policy'],z=episode['outcome']))
        return samples

    champion=frozen
    models={'initial':frozen}
    all_training=[]
    rounds=[]
    for iteration in (1,2):
        collected=run_set(f'r{iteration}-collect',champion,'collect',cases(config['training_seeds'][iteration-1]))
        all_training.extend(collected)
        samples=make_samples(all_training)
        candidate=output/f'candidate-{iteration}.pt'
        metrics_path=output/f'train-{iteration}.json'
        if not candidate.exists():
            torch.manual_seed(7300+iteration)
            model,_=load_transformer_checkpoint(champion,'XS',ALL_CONTENT,V7)
            learner=Learner(model,learning_rate=config['learning_rate'],value_weight=0)
            learner.model.value.requires_grad_(False)
            rng=random.Random(8300+iteration)
            history=[]
            start=time.perf_counter()
            for update in range(config['updates']):
                chosen=[samples[rng.randrange(len(samples))] for _ in range(config['batch_size'])]
                history.append(learner.update(chosen,microbatch_size=16))
                if (update+1)%20==0: print(f'TRAIN {iteration} step={update+1} loss={history[-1]["loss"]:.4f}',flush=True)
            statistics=dict(samples=len(samples),episodes=len(all_training),seconds=time.perf_counter()-start,history=history)
            atomic(metrics_path,statistics)
            save_transformer_checkpoint(candidate,learner.model,f'native-policy-{iteration}',
                config=dict(native_evolution=config,parent_sha=digest(champion)), statistics=statistics,
                iteration=iteration,training_state=dict(optimizer=learner.optimizer.state_dict(),updates=learner.updates,
                    torch_rng=torch.get_rng_state(),sampling_rng=rng.getstate()))
        else:
            _,payload=load_transformer_checkpoint(candidate,'XS',ALL_CONTENT,V7)
            if payload['run_config']!={'native_evolution':config,'parent_sha':digest(champion)}:
                raise ValueError('Candidate parent/config mismatch')
        models[f'candidate-{iteration}']=candidate
        validation={}
        # Reverse order in round 2; both receive the same disjoint validation starts.
        pairs=[('champion',champion),('candidate',candidate)]
        if iteration==2: pairs.reverse()
        for label, checkpoint in pairs:
            validation[label]={}
            for mode in ('search','policy'):
                rows=run_set(f'r{iteration}-validation-{label}-{mode}',checkpoint,mode,cases(config['validation_seeds']))
                validation[label][mode]=summary(rows)
        old,new=validation['champion']['search'],validation['candidate']['search']
        promote=new['wins']>=old['wins'] and new['utility']>old['utility']+0.005
        decision=dict(iteration=iteration,parent_sha=digest(champion),candidate_sha=digest(candidate),
                      promoted=promote,validation=validation,training=summary(collected))
        rounds.append(decision)
        atomic(output/f'round-{iteration}.json',decision)
        print('ROUND '+json.dumps(decision),flush=True)
        if promote: champion=candidate
    # Test split opens once after BOTH model updates and promotion decisions are fixed.
    tests={}
    for label,checkpoint in models.items():
        tests[label]={}
        for mode in ('search','policy'):
            tests[label][mode]=summary(run_set(f'test-{label}-{mode}',checkpoint,mode,cases(config['test_seeds'])))
    tests['uniform']={'search':summary(run_set('test-uniform',frozen,'uniform',cases(config['test_seeds'])))}
    atomic(output/'result.json',dict(config=config,rounds=rounds,test=tests,champion=str(champion),champion_sha=digest(champion)))
    print('COMPLETE '+str(output/'result.json'),flush=True)


if __name__=='__main__':
    main()
