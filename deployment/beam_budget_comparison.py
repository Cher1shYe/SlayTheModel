"""Larger beam search and native MCTS with matched average decision time."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import statistics
import time

import eval_value_beam as base

BEAM_CHOOSE = base.choose


def evaluate(job):
    seed, kind, width, depth, budget = job
    if kind == 'mcts':
        def timed(state, width, depth):
            action, simulations, elapsed = base.sts.mcts_recommend_timed(state, budget)
            return action, simulations, 0
        base.choose = timed
    else:
        base.choose = BEAM_CHOOSE
    result = base.worker((seed, width, depth))
    result.update(kind=kind, budget_ms=budget, label=f'{kind}-w{width}d{depth}')
    if kind == 'mcts':
        result['simulations'] = result.pop('expanded')
    return result


def summary(rows):
    result={}
    for label in sorted({r['label'] for r in rows}):
        group=[r for r in rows if r['label']==label]
        searches=sum(r['searches'] for r in group)
        seconds=sum(r['search_seconds'] for r in group)
        errors=sum(r['status']=='error' for r in group)
        result[label]=dict(n=len(group),errors=errors,cutoffs=sum(r['status']=='cutoff' for r in group),
            mean_floor=statistics.mean(r['floor'] for r in group) if not errors else None,
            wins=sum(bool(r['win']) for r in group),max_floor=max(r['floor'] for r in group),
            searches=searches,mean_search_ms=seconds*1000/searches if searches else None,
            mean_run_seconds=statistics.mean(r['seconds'] for r in group),
            work_per_search=sum(r.get('expanded',r.get('simulations',0)) for r in group)/searches if searches else None)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--count',type=int,default=50)
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    seeds=[int(s) for s in (base.runtime.REPO/'eval/eval_seeds_50.txt').read_text(encoding='utf-8').splitlines() if s and not s.startswith('#')][:args.count]
    variants=((8,4),(16,8),(32,12))
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    config=dict(seeds=seeds,variants=variants,workers=args.workers,
        native_sha256=sha(base.sts.__file__),script_sha256=sha(__file__),base_script_sha256=sha(base.__file__),
        value_sha256=sha(base.runtime.REPO/'weights/armB_model_VAL256x256.pt'),
        noncombat='built-in Agent simulation_count_base=2000, same for all arms',
        scope='Ironclad A0; frozen weights; boolean Barricade fix; 800 actions/battle, 600 outer steps/run',
        matching='MCTS steady-clock deadline = corresponding beam total search_seconds / total searches on all 50 seeds, including cutoffs; actual call time includes cleanup and is reported',
        beam='same choose() as preceding experiment, no extra deduplication or heuristics',
        mcts='original native end-state reward, rollout, and best-path/root-visits action extraction; only stopping criterion changes',
        seed_protocol='Existing repeatedly used 50-seed evaluation set; no performance-based hyperparameter selection')
    (args.out/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    rows=[]; started=time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers,initializer=base.initialize,initargs=(True,)) as pool:
        for stage in ('beam','mcts'):
            if stage=='mcts':
                totals=summary(rows)
                budgets={f'w{w}d{d}':totals[f'beam-w{w}d{d}']['mean_search_ms'] for w,d in variants}
                if any(totals[f'beam-w{w}d{d}']['errors'] for w,d in variants):
                    raise RuntimeError('Cannot calibrate while beam has unexpected exceptions')
                (args.out/'budgets.json').write_text(json.dumps(budgets,indent=2))
                print('MCTS budgets '+json.dumps(budgets),flush=True)
            futures=[pool.submit(evaluate,(seed,stage,w,d,0. if stage=='beam' else budgets[f'w{w}d{d}']))
                     for seed in seeds for w,d in variants]
            for future in as_completed(futures):
                row=future.result(); rows.append(row)
                (args.out/f"{row['label']}-seed{row['seed']}.json").write_text(json.dumps(row,indent=2),encoding='utf-8')
                progress=dict(stage=stage,jobs_done=len(rows),jobs_total=len(seeds)*len(variants)*2,
                    wall_seconds=time.perf_counter()-started,summary=summary(rows))
                temp=args.out/'progress.tmp'
                temp.write_text(json.dumps(progress,indent=2),encoding='utf-8')
                temp.replace(args.out/'progress.json')
                print(f"{len(rows)}/{len(seeds)*len(variants)*2} {row['label']} seed={row['seed']} floor={row['floor']} {row['status']}",flush=True)
    result=dict(config=config,budgets=budgets,wall_seconds=time.perf_counter()-started,summary=summary(rows),runs=rows)
    (args.out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2),flush=True)


if __name__=='__main__':
    main()
