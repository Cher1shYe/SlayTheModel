"""Compare three frozen ArmG models using floor-budgeted root-prior PUCT."""
from __future__ import annotations
import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time
import numpy as np
import torch
from deployment import evaluate_battle_root_prior as root
import agent.armg_train as base
from agent.armg import ArmGScorer
from agent.armg_floor_schedule import FloorMctsController, combat_budget
from agent.combat_dagger import CombatPolicy, load_combat_checkpoint
from deployment.evaluate_armg import load_armg_checkpoint, _summary
from deployment.evaluate_armg_checkpoints import paired_summary as paired_two

ARMS = ('start', 'r640', 'r960')
SEED_BASE = 41_020_000
_worker_model = None
_worker_version = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FloorRootPuctController(FloorMctsController):
    def plan(self, battle, seed, combat, simulations, epsilon, is_boss):
        if (self.current_floor is None or bool(is_boss) != self.current_boss or
            simulations != combat_budget(self.current_floor, self.start, self.increment,
                      elite=self.current_elite, boss=self.current_boss,
                      elite_bonus=self.elite_bonus, boss_bonus=self.boss_bonus)):
            raise ValueError('missing or inconsistent floor-dependent PUCT budget')
        actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
        if not actions:
            raise RuntimeError('no legal combat action')
        if len(actions) == 1:
            return actions, 0
        search_seed = (self.search_seed + 7919 * self.decisions) & 0xFFFFFFFF
        self.decisions += 1
        if is_boss:
            self.boss_decisions += 1
        else:
            self.normal_decisions += 1
        if self.activity:
            self.activity(self)
        path, done = root._fixed_plan(battle, search_seed, combat, simulations, epsilon, is_boss)
        if done != simulations:
            raise RuntimeError('incomplete PUCT budget')
        self.simulations += done
        if is_boss:
            self.boss_simulations_completed += done
        else:
            self.normal_simulations += done
        if self.current_elite:
            self.elite_decisions += 1
            self.elite_simulations += done
        key = (self.current_floor, self.current_elite, self.current_boss)
        self.floor_decisions[key] = self.floor_decisions.get(key, 0) + 1
        return path, done


def _init_worker(combat_path):
    torch.set_num_threads(1)
    root._policy = CombatPolicy().eval()
    load_combat_checkpoint(combat_path, root._policy)
    root._current_arm = 'puct'
    if not hasattr(root.sim.BattleContext, 'mcts_priors'):
        raise RuntimeError('selected simulator does not support mcts_priors')


def _play(task):
    global _worker_model, _worker_version
    seed, search_seed, version, weights, active_dir, max_steps = task
    if _worker_model is None:
        _worker_model = ArmGScorer().eval()
    if _worker_version != version:
        _worker_model.load_state_dict(torch.load(weights, map_location='cpu', weights_only=True))
        _worker_version = version
    activity_path = Path(active_dir) / f'worker-{os.getpid()}.json'
    started, last = time.perf_counter(), [0.0]
    def activity(ctrl, force=False):
        now = time.perf_counter()
        if force or now - last[0] >= 10:
            data = {'seed': seed, 'arm': version, 'worker_pid': os.getpid(),
                    'elapsed_seconds': now-started, 'combat_decisions': ctrl.decisions,
                    'completed_simulations': ctrl.simulations}
            try:
                atomic_json(activity_path, data)
            except OSError:
                pass
            last[0] = now
    controller = FloorRootPuctController(search_seed, activity)
    old = base._mcts_plan
    base._mcts_plan = controller.plan
    try:
        activity(controller, True)
        result = base.collect_episode(seed, _worker_model, deterministic=True,
                     combat='mcts-oracle', simulations=2000, epsilon=0.05,
                     max_steps=max_steps, ascension=0, need_rules=False, relic_rules=False,
                     combat_budget_by_context=controller.budget_for_context)
        result.pop('records', None)
        expected = sum(combat_budget(f, elite=e, boss=b) * count
                       for (f,e,b), count in controller.floor_decisions.items())
        if result['mcts_searches'] != controller.decisions or result['mcts_simulations'] != expected:
            raise RuntimeError('episode used an inconsistent PUCT budget')
        result.update(arm=version, elapsed_seconds=time.perf_counter()-started,
                      normal_decisions=controller.normal_decisions, elite_decisions=controller.elite_decisions,
                      boss_decisions=controller.boss_decisions, search_seed=search_seed)
        return result
    finally:
        base._mcts_plan = old
        activity_path.unlink(missing_ok=True)


def atomic_json(path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def summaries(records, bootstrap=False):
    arms = {a: _summary([r for r in records if r['arm'] == a]) for a in ARMS}
    paired = {}
    for a in ('r640','r960'):
        items = [dict(r, arm='baseline' if r['arm']=='start' else 'candidate')
                 for r in records if r['arm'] in ('start',a)]
        paired[a+'_vs_start'] = paired_two(items, bootstrap=bootstrap)
    return arms, paired


def markdown(state, arms, paired, elapsed, total, active, workers):
    labels={'running':'运行中','completed':'已完成','incomplete':'未完成','failed':'失败'}
    lines=['# ArmG 三模型根先验 PUCT 配对评测','',
           f'- 状态：{labels.get(state,state)}',
           f'- 完成对局：{sum(a["episodes"] for a in arms.values())} / {total}',
           f'- 已用时间：{elapsed/60:.1f} 分钟',
           f'- {workers} worker；战斗采用 oracle 根节点网络先验 PUCT（n=1），每次只执行搜索结果的第一步',
           '- 每次预算：第 1 层 2000 次，每层 +200；精英 +1000，Boss +2000',
           '- 三个模型使用相同游戏种子与独立于游戏的搜索种子；局外贪心选择',
           '', '| 模型 | 已完成 | 平均层数 | 胜率 |', '|---|---:|---:|---:|']
    names={'start':'原 640 局起点','r640':'本次训练 640 局','r960':'本次训练 960 局'}
    for a in ARMS:
        x=arms[a]; n=x.get('completed',0); mean=x.get('mean_floor_completed'); win=x.get('win_rate_completed')
        lines.append(f'| {names[a]} | {n} | {mean:.2f} | {win*100:.2f}% |' if n else f'| {names[a]} | 0 | — | — |')
    for a, p in paired.items():
        if p['complete_pairs']:
            lines.append(f"- {names[a.split('_')[0]]} 相对起点：{p['mean_floor_difference']:+.2f} 层（{p['complete_pairs']} 对）")
    if active:
        lines += ['', f'- 当前活动 worker：{len(active)}']
    return '\n'.join(lines)+'\n'


def run(start_checkpoint, r640_checkpoint, r960_checkpoint, combat_checkpoint, out_dir,
        count=100, workers=8, max_steps=5000, seed_start=SEED_BASE, search_seed=20261030):
    if min(count, workers, max_steps) < 1 or seed_start < 0:
        raise ValueError('invalid evaluation parameters')
    if not root._extension or not hasattr(root.sim.BattleContext, 'mcts_priors'):
        raise RuntimeError('select a compatible isolated simulator with STS2_PRIOR_PYD')
    ckpts={a:Path(p).resolve(strict=True) for a,p in zip(ARMS,(start_checkpoint,r640_checkpoint,r960_checkpoint))}
    combat=Path(combat_checkpoint).resolve(strict=True)
    out=Path(out_dir).resolve(); out.mkdir(parents=True,exist_ok=False)
    active=out/'active'; active.mkdir()
    model=ArmGScorer(); paths={}; metadata={}
    for a,p in ckpts.items():
        data=load_armg_checkpoint(p,model)
        metadata[a]={'path':str(p),'sha256':sha(p),'progress':data.get('progress')}
        paths[a]=out/(a+'_weights.pt'); torch.save(model.state_dict(),paths[a])
    battle_snapshot=out/'combat_policy.pt'; shutil.copyfile(combat,battle_snapshot)
    battle_model=CombatPolicy(); load_combat_checkpoint(battle_snapshot,battle_model)
    rng=np.random.default_rng(search_seed)
    search_seeds=rng.integers(0,2**32,size=count,dtype=np.uint64).tolist()
    config={'checkpoints':metadata,'combat_checkpoint':str(combat),'combat_sha256':sha(battle_snapshot),
            'simulator':str(Path(root._extension).resolve()),'simulator_sha256':sha(root._extension),
            'count_per_model':count,'workers':workers,'seed_start':seed_start,'search_seed':search_seed,
            'budget':'2000 + 200*(max(floor,1)-1) + elite*1000 + boss*2000',
            'puct_depth':1,'puct_c':3.0,'combat':'oracle root-prior PUCT; random rollout',
            'path_cache':'none','ascension':0,'armg':'greedy without overlays','max_steps':max_steps,
            'started_utc':datetime.now(timezone.utc).isoformat()}
    atomic_json(out/'config.json',config)
    records=[]; start=time.perf_counter()
    def save(state, error=None, bootstrap=False):
        arms,paired=summaries(records,bootstrap=bootstrap)
        activity=[]
        for p in active.glob('worker-*.json'):
            try: activity.append(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, ValueError): pass
        data={'state':state,'completed_jobs':len(records),'total_jobs':count*len(ARMS),
              'elapsed_seconds':time.perf_counter()-start,'arms':arms,'paired':paired,
              'active_episodes':activity,'updated_utc':datetime.now(timezone.utc).isoformat()}
        if error: data['error']=error
        atomic_json(out/'progress.json',data)
        tmp=out/'progress.md.tmp'; tmp.write_text(markdown(state,arms,paired,data['elapsed_seconds'],count*len(ARMS),activity,workers),encoding='utf-8'); os.replace(tmp,out/'progress.md')
        return data
    save('running')
    try:
        with (out/'episodes.jsonl').open('x',encoding='utf-8',buffering=1) as stream:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),initializer=_init_worker,
                                     initargs=(str(battle_snapshot),)) as pool:
                jobs={}
                for i in range(count):
                    for a in ARMS:
                        task=(seed_start+i, int(search_seeds[i]), a, str(paths[a]), str(active), max_steps)
                        jobs[pool.submit(_play,task)]=(seed_start+i,a)
                pending=set(jobs)
                while pending:
                    done,pending=wait(pending,timeout=10,return_when=FIRST_COMPLETED)
                    for future in done:
                        seed,a=jobs[future]
                        try: item=future.result()
                        except Exception as exc: item={'seed':seed,'arm':a,'status':'error','won':False,'floor':0,'error':f'{type(exc).__name__}: {exc}'}
                        records.append(item); stream.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n'); stream.flush()
                    save('running')
        status='completed' if all(r['status']=='terminated' for r in records) and len(records)==count*len(ARMS) else 'incomplete'
        data=save(status, bootstrap=True)
        atomic_json(out/'summary.json', {'config':config, **data})
        return data
    except BaseException as exc:
        save('failed',error=f'{type(exc).__name__}: {exc}')
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start-checkpoint',required=True); p.add_argument('--r640-checkpoint',required=True)
    p.add_argument('--r960-checkpoint',required=True); p.add_argument('--combat-checkpoint',required=True)
    p.add_argument('--out-dir',required=True); p.add_argument('--count',type=int,default=100)
    p.add_argument('--workers',type=int,default=8); p.add_argument('--max-steps',type=int,default=5000)
    p.add_argument('--seed-start',type=int,default=SEED_BASE); p.add_argument('--search-seed',type=int,default=20261030)
    run(**vars(p.parse_args()))

if __name__=='__main__': main()
