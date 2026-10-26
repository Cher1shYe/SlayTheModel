"""Fixed multi-round experiment; shared ArmG, paired evaluation, count/time MCTS."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]

def init_worker(source):
    global torch, sts, B, V, MC, SP, AG
    os.environ['STS_BOT_DIR'] = source
    sys.path[:0] = [str(ROOT/'simulator/build312/Release'), source]
    import torch
    import slaythespire as sts
    import armB_train as B
    import armB_value as V
    import armB_mcts as MC
    import armB_selfplay as SP
    import armG_train as AG
    torch.set_num_threads(1)
    AG.card_idx = lambda name: AG._vocab.get(name, AG.VOCAB_CAP-1)
    if os.environ.get('STS_FAST_PUCT') == '1':
        import fast_puct
        fast_puct.install(MC)

def play(job):
    seed, mode, wp, wv, budget = job
    t0 = time.perf_counter()
    torch.manual_seed(seed)
    policy, value = SP._load(wp, wv)
    agnet = SP._load_armg()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = 2000; SP._set_all_pauses(ag)
    rng = random.Random(seed)
    samples = []; decisions = 0; search_seconds = 0.; simulations = 0
    status = 'ok'; error = None
    try:
        for _ in range(600):
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE:
                kind, descs, actions = AG.build_choices(gc)
                if not descs:
                    if gc.screen_state == sts.ScreenState.REWARDS: gc.skip_reward_cards(); continue
                    raise RuntimeError('No noncombat actions: '+kind)
                with torch.inference_mode():
                    scores = agnet.score(torch.tensor(AG.obs_vec(gc)), descs)
                    index = int(scores.argmax())
                actions[index](gc); continue
            bc = sts.BattleContext(); bc.init(gc); pending = []
            for _ in range(800):
                if bc.outcome != sts.Outcome.UNDECIDED: break
                actions = sts.get_legal_actions(bc)
                if not actions: raise RuntimeError('Live battle has no actions')
                if len(actions)==1: actions[0].execute(bc); continue
                start = time.perf_counter()
                if mode == 'pure':
                    state = B.encode_battle(bc); hand = list(bc.hand)
                    with torch.inference_mode():
                        logits = policy.score(state,[B.cand_desc(bc,a,hand) for a in actions])
                    action = actions[int(logits.argmax())]
                elif mode == 'native':
                    action = sts.mcts_recommend(bc,int(budget)); simulations += int(budget)
                elif mode == 'timed':
                    action, count, elapsed = sts.mcts_recommend_timed(bc,budget); simulations += count
                else:
                    tree = MC.Node(bc.clone())
                    for _ in range(int(budget)): MC.simulate(tree,policy,value)
                    simulations += int(budget)
                    if tree.cands is None: raise RuntimeError('Search produced no candidates')
                    if [a.bits for a in tree.cands] != [a.bits for a in actions]:
                        raise RuntimeError('Search action order mismatch')
                    total = sum(tree.N)
                    if total <= 0: raise RuntimeError('Search produced zero visits')
                    visit = [n/total for n in tree.N]
                    idx = rng.choices(range(len(actions)),weights=visit)[0] if mode=='train' else max(range(len(actions)),key=lambda i:tree.N[i])
                    action = actions[idx]
                    if mode=='train':
                        state = B.encode_battle(bc); hand = list(bc.hand)
                        pending.append((state,[B.cand_desc(bc,a,hand) for a in actions],visit))
                    del tree
                search_seconds += time.perf_counter()-start; decisions += 1
                action.execute(bc)
            if bc.outcome == sts.Outcome.UNDECIDED:
                status = 'cutoff'; break
            terminal = V._battle_value(bc)
            samples.extend((s,c,v,terminal) for s,c,v in pending)
            bc.exit_battle(gc)
        if gc.outcome == sts.GameOutcome.UNDECIDED: status = 'cutoff'
    except Exception:
        status = 'error'; error = traceback.format_exc()
    return dict(seed=seed,mode=mode,floor=gc.floor_num,win=gc.outcome==sts.GameOutcome.PLAYER_VICTORY,
                status=status,error=error,seconds=time.perf_counter()-t0,decisions=decisions,
                search_seconds=search_seconds,simulations=simulations,samples=samples)

def summarize(rows):
    n=sum(r['decisions'] for r in rows)
    return dict(n=len(rows),mean_floor=statistics.mean(r['floor'] for r in rows),
                wins=sum(r['win'] for r in rows),cutoffs=sum(r['status']=='cutoff' for r in rows),
                errors=sum(r['status']=='error' for r in rows),
                mean_decision_ms=1000*sum(r['search_seconds'] for r in rows)/max(1,n),
                mean_run_seconds=statistics.mean(r['seconds'] for r in rows),
                mean_simulations=sum(r['simulations'] for r in rows)/max(1,n))

def dump(path,obj):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,indent=2),encoding='utf-8')
    for attempt in range(12):
        try:
            tmp.replace(path)
            return True
        except PermissionError:
            if attempt < 11:
                time.sleep(min(0.05 * 2**attempt, 0.5))
            elif path.name == 'progress.json':
                # A Windows viewer may deny delete-sharing. Keep the complete
                # pending snapshot; the next update retries without losing training.
                print('Progress file locked; pending snapshot: '+str(tmp),flush=True)
                return False
            else:
                raise

def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--rounds',type=int,default=6); p.add_argument('--games',type=int,default=40)
    p.add_argument('--sims',type=int,default=64); p.add_argument('--epochs',type=int,default=2)
    p.add_argument('--workers',type=int,default=4); p.add_argument('--eval-count',type=int,default=50)
    p.add_argument('--stabilize',action='store_true')
    p.add_argument('--initial-round',type=int,default=0)
    p.add_argument('--initial-dir',default=None,help='Directory with roundN_policy/value.pt for warm start')
    p.add_argument('--seed',type=int,default=20261026)
    p.add_argument('--restart-setup',action='store_true')
    p.add_argument('--fast-puct',action='store_true',help='Exact-search optimized stabilized PUCT inference')
    a=p.parse_args(); out=a.out.resolve()
    os.environ['STS_FAST_PUCT'] = '1' if a.fast_puct else '0'
    if a.fast_puct and not a.stabilize:
        p.error('--fast-puct requires --stabilize')
    if a.restart_setup and out.exists():
        # Only restart an initial setup/baseline failure, never overwrite training.
        if list(out.glob('train_*.json')) or (out/'before_pure.json').exists() or (out/'latest_training_state.pt').exists():
            raise RuntimeError('Restart setup refused: completed experiment data exists')
        backup=out/('failed_setup_'+str(time.time_ns())); backup.mkdir()
        for f in out.iterdir():
            if f.is_file(): shutil.copy2(f,backup/f.name)
    out.mkdir(parents=True,exist_ok=a.restart_setup)
    source=out/'source'; source.mkdir(exist_ok=a.restart_setup)
    # Reuse audited compatibility patches, without changing upstream files.
    template=ROOT/'deployment/training_audit_v3/selfplay'
    for pattern in ('*.py','armS_card_vocab.json','armG_model_G128x128_15k.pt'):
        for f in template.glob(pattern): shutil.copy2(f,source)
    if a.stabilize:
        from stabilize_selfplay import patch_source
        patch_source(source)
    init_worker(str(source)); torch.manual_seed(a.seed); random.seed(a.seed)
    weights=ROOT/'sts-rl-agent/weights'
    initial_p=weights/'armB_model_B256x256.pt'; initial_v=weights/'armB_model_VAL256x256.pt'
    if a.initial_round:
        initial_dir=Path(a.initial_dir).resolve() if a.initial_dir else ROOT/'deployment/selfplay_6x40_s64'
        initial_p=initial_dir/f'round{a.initial_round}_policy.pt'
        initial_v=initial_dir/f'round{a.initial_round}_value.pt'
    policy,value=SP._load(str(initial_p),str(initial_v))
    if a.stabilize:
        from stabilize_selfplay import verify
        dump(out/'stability_checks.json',verify(B,value))
    op=torch.optim.Adam(policy.parameters(),lr=3e-4); ov=torch.optim.Adam(value.parameters(),lr=3e-4)
    def save_models(i):
        wp=out/f'round{i}_policy.pt'; wv=out/f'round{i}_value.pt'
        torch.save(policy.state_dict(),wp); torch.save(value.state_dict(),wv)
        return str(wp),str(wv)
    wp0,wv0=save_models(0)
    seeds=[int(x) for x in (ROOT/'sts-rl-agent/eval/eval_seeds_50.txt').read_text(encoding='utf-8').splitlines() if x.strip() and not x.startswith('#')][:a.eval_count]
    rng=random.Random(a.seed); used=set(seeds)
    if a.initial_round:
        previous_paths={ROOT/'deployment/selfplay_6x40_s64/config.json',initial_dir/'config.json'}
        for previous_path in previous_paths:
            previous=json.loads(previous_path.read_text())
            used.update(previous['monitor_seeds'])
            for group in previous['training_seeds']: used.update(group)
    def fresh(n):
        found=[]
        while len(found)<n:
            s=rng.randint(1,10**9)
            if s not in used: used.add(s); found.append(s)
        return found
    monitors=fresh(10); training=[fresh(a.games) for _ in range(a.rounds)]
    config={**vars(a),'out':str(out),'eval_seeds':seeds,'monitor_seeds':monitors,'training_seeds':training,
            'torch':torch.__version__,'cuda_available':torch.cuda.is_available(),
            'noncombat':'frozen ArmG G128x128_15k for every arm; Ironclad A0',
            'buffer_cap':40000,'lr':3e-4,'training_seed':a.seed,
            'initial_policy':str(initial_p),'initial_value':str(initial_v),
            'warm_start':'weights only; fresh optimizers and replay buffer',
            'stability':'normalized state clipped to [-100,100]; reject nonfinite; inference value clamp [0,2]; raw value SmoothL1 beta=0.25; grad norm 1' if a.stabilize else 'original',
            'cutoff':'800 actions/battle or 600 outer steps; report stopped floor, never label incomplete battle; discard entire cutoff training game',
            'selection':'predeclared final round, not best monitor checkpoint',
            'sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(sts.__file__),Path(__file__),initial_p,initial_v,source/'armG_model_G128x128_15k.pt',*source.glob('*.py')]}}
    dump(out/'config.json',config); shutil.copy2(__file__,out/'driver_snapshot.py')
    if a.fast_puct:
        fast_path=ROOT/'deployment/fast_puct.py'
        shutil.copy2(fast_path,out/'fast_puct.py')
        config['sha256'][str(fast_path)]=hashlib.sha256(fast_path.read_bytes()).hexdigest()
        dump(out/'config.json',config)
    started=time.perf_counter(); progress={}; allrows={}; buffer=[]; history=[]
    def log(msg): print(msg,flush=True)
    with ProcessPoolExecutor(max_workers=a.workers,initializer=init_worker,initargs=(str(source),)) as pool:
        def run(label,seedlist,mode,wp,wv,budget):
            rows=[]; futures=[pool.submit(play,(s,mode,wp,wv,budget)) for s in seedlist]
            for f in as_completed(futures):
                r=f.result(); rows.append(r)
                progress.update(stage=label,done=len(rows),total=len(seedlist),wall_seconds=time.perf_counter()-started)
                dump(out/'progress.json',progress)
                if r['status']=='error':
                    dump(out/f'{label}_error.json',r); raise RuntimeError(r['error'])
            rows.sort(key=lambda r:r['seed'])
            allrows[label]=[{k:v for k,v in r.items() if k!='samples'} for r in rows]
            dump(out/f'{label}.json',{'summary':summarize(rows),'runs':allrows[label]})
            log(label+' '+json.dumps(summarize(rows)))
            return rows
        run('before_pure',seeds,'pure',wp0,wv0,a.sims)
        run('before_puct',seeds,'puct',wp0,wv0,a.sims)
        run('monitor_0',monitors,'puct',wp0,wv0,a.sims)
        wp,wv=wp0,wv0
        for i in range(1,a.rounds+1):
            rows=run(f'train_{i}',training[i-1],'train',wp,wv,a.sims)
            new=[sample for r in rows if r['status']=='ok' for sample in r['samples']]
            if not new: raise RuntimeError('No complete training samples')
            buffer=(buffer+new)[-40000:]
            progress.update(stage=f'update_{i}',new_samples=len(new),buffer=len(buffer)); dump(out/'progress.json',progress)
            SP.train(policy,value,op,ov,buffer,a.epochs)
            if not all(torch.isfinite(t).all() for net in (policy,value) for t in net.parameters()): raise RuntimeError('Nonfinite weights')
            wp,wv=save_models(i)
            torch.save(dict(round=i,policy=policy.state_dict(),value=value.state_dict(),opt_policy=op.state_dict(),opt_value=ov.state_dict(),buffer=buffer,torch_rng=torch.get_rng_state(),python_rng=random.getstate()),out/'latest_training_state.pt')
            rows=run(f'monitor_{i}',monitors,'puct',wp,wv,a.sims)
            history.append(dict(round=i,new_samples=len(new),buffer=len(buffer),**summarize(rows)))
            dump(out/'history.json',history)
        run('after_pure',seeds,'pure',wp,wv,a.sims)
        after=run('after_puct',seeds,'puct',wp,wv,a.sims)
        run('native_equal_count',seeds,'native',wp0,wv0,a.sims)
        budgets={label:summarize(allrows[label])['mean_decision_ms'] for label in ('before_puct','after_puct')}
        dump(out/'budgets.json',budgets)
        for label,ms in budgets.items(): run('native_time_'+label,seeds,'timed',wp0,wv0,ms)
    results={k:summarize(v) for k,v in allrows.items()}
    dump(out/'results.json',dict(summary=results,history=history,budgets=budgets,wall_seconds=time.perf_counter()-started))
    dump(out/'progress.json',dict(stage='complete',wall_seconds=time.perf_counter()-started))
    log('COMPLETE')

if __name__=='__main__':
    os.environ['OMP_NUM_THREADS']='1'; os.environ['MKL_NUM_THREADS']='1'
    main()
