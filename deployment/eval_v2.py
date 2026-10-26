"""Evaluate a series of v2 checkpoints on a fixed seed list (puct + pure)."""
import argparse
import json
import random
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import selfplay_v2 as V2


def summarize(rows):
    battles = [b for r in rows for b in r['battles']]
    values = [(p, z) for r in rows for (p, z) in r['values']]
    preds = [p for p, _ in values]
    zs = [z for _, z in values]
    mse = statistics.mean((p - z) ** 2 for p, z in values) if values else float('nan')
    searched = sum(b.get('searched', 0) for b in battles)
    search_ms = sum(b.get('search_ms', 0.0) for b in battles)
    sims = sum(b.get('sims', 0) for b in battles)
    return dict(n=len(rows),
                mean_floor=statistics.mean(r['floor'] for r in rows),
                floors=[r['floor'] for r in rows],
                wins=sum(r['win'] for r in rows),
                battles=len(battles),
                battle_win=statistics.mean(b['win'] for b in battles) if battles else float('nan'),
                battle_hp=statistics.mean(b['hp'] for b in battles) if battles else float('nan'),
                value_mse=mse,
                decisions=sum(r['decisions'] for r in rows),
                mean_decision_ms=(search_ms / searched) if searched else None,
                mean_sims=(sims / searched) if searched else None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--source', type=Path, default=None)
    p.add_argument('--rounds', type=int, default=5)
    p.add_argument('--workers', type=int, default=64)
    p.add_argument('--eval-sims', type=int, default=512)
    p.add_argument('--extra-seeds', type=int, default=150)
    p.add_argument('--modes', default='puct,pure')
    p.add_argument('--only-rounds', default='')
    p.add_argument('--timed-ms', type=float, default=130.0)
    p.add_argument('--forest-trees', type=int, default=8)
    p.add_argument('--forest-sims', type=int, default=512)
    p.add_argument('--sim-cap', type=int, default=0)
    p.add_argument('--root-q', type=int, default=0)
    p.add_argument('--root-max', type=int, default=0)
    p.add_argument('--root-lcb', type=int, default=0)
    p.add_argument('--lcb-k', type=float, default=5.0)
    p.add_argument('--lcb-min-prop', type=float, default=0.15)
    p.add_argument('--root-min-visits', type=int, default=1)
    p.add_argument('--forest-q', type=int, default=0)
    p.add_argument('--forest-noise', type=float, default=0.0)
    p.add_argument('--cpuct-native', type=float, default=3.0)
    p.add_argument('--prior-temp', type=float, default=1.0)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    run = a.run.resolve()
    source = a.source.resolve() if a.source else run / 'source'
    base = [int(x) for x in (V2.ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
            .read_text(encoding='utf-8').splitlines()
            if x.strip() and not x.startswith('#')]
    rng = random.Random(424242)
    seeds = list(dict.fromkeys(base))
    while len(seeds) < len(base) + a.extra_seeds:
        s = rng.randint(1, 10 ** 9)
        if s not in seeds:
            seeds.append(s)
    cfg = dict(eval_sims=a.eval_sims, n_full=1, n_fast=1, p_full=0.0,
               archive_every=0, native_frac=0.0, native_sims=0,
               eval_timed_ms=a.timed_ms,
               forest_trees=a.forest_trees, forest_sims=a.forest_sims,
               eval_sim_cap=a.sim_cap, root_q=a.root_q,
               root_max=a.root_max, root_lcb=a.root_lcb, lcb_k=a.lcb_k,
               lcb_min_prop=a.lcb_min_prop, root_min_visits=a.root_min_visits,
               forest_q=a.forest_q, forest_noise=a.forest_noise,
               cpuct_native=a.cpuct_native, prior_temp=a.prior_temp)
    result = dict(seeds=len(seeds), rounds=[])
    only = {int(x) for x in a.only_rounds.split(',') if x.strip()}
    with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                             initargs=(str(source),)) as pool:
        for rnd in range(a.rounds + 1):
            if only and rnd not in only:
                continue
            wp = run / f'round{rnd}_policy.pt'
            wv = run / f'round{rnd}_value.pt'
            if not wp.exists():
                continue
            row = dict(round=rnd)
            for mode in [m for m in a.modes.split(',') if m]:
                jobs = [(s, mode, str(wp), str(wv), cfg, 1.0) for s in seeds]
                rows = list(pool.map(V2.play, jobs))
                bad = [r for r in rows if r['status'] != 'ok']
                if bad:
                    raise RuntimeError(bad[0]['error'])
                row[mode] = summarize(rows)
            result['rounds'].append(row)
            print(json.dumps(row), flush=True)
    base = result['rounds'][0]
    for row in result['rounds'][1:]:
        row['paired'] = {}
        for mode in row:
            if mode in ('round', 'paired') or mode not in base:
                continue
            diffs = [c - b for c, b in zip(row[mode]['floors'], base[mode]['floors'])]
            mean = statistics.mean(diffs)
            se = statistics.stdev(diffs) / len(diffs) ** 0.5 if len(diffs) > 1 else float('nan')
            row['paired'][mode] = dict(delta=mean, se=se,
                                       t=(mean / se) if se else float('nan'))
            print(f"paired {mode} round {row['round']}: "
                  f"{mean:+.2f} +- {se:.2f} (t={mean/se if se else float('nan'):.2f})",
                  flush=True)
    a.out.write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
