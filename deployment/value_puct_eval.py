"""PUCT@512 evaluation of the value nets trained under different targets.

Policy is fixed at armD r4 so the only change is the leaf value function.
Runs in a single process pool with seed-major, net-minor ordering so machine
load drift affects every net equally.
"""
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v2 as V2

RUN = ROOT / 'deployment/runs_v2/armD'
POLICY = RUN / 'round4_policy.pt'
VALUE_BASE = RUN / 'round4_value.pt'
DIAG = ROOT / 'deployment/runs_v2/value_diag'
SOURCE = RUN / 'source'


def main():
    seeds = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
             .read_text(encoding='utf-8').splitlines()
             if x.strip() and not x.startswith('#')][:30]
    nets = [
        ('base_r4', VALUE_BASE),
        ('z_reg', DIAG / 'z_reg_value.pt'),
        ('floor_reg', DIAG / 'floor_reg_value.pt'),
        ('floor_pair', DIAG / 'floor_pair_value.pt'),
        ('z_pair', DIAG / 'z_pair_value.pt'),
    ]
    cfg = dict(eval_sims=512, n_full=1, n_fast=1, p_full=0.0, archive_every=0,
               native_frac=0.0, native_sims=0, eval_timed_ms=130.0,
               root_min_visits=1)
    jobs = [(s, 'puct', str(POLICY), str(wv), cfg, 1.0)
            for s in seeds for _, wv in nets]
    with ProcessPoolExecutor(max_workers=32, initializer=V2.init_worker,
                             initargs=(str(SOURCE),)) as pool:
        rows = list(pool.map(V2.play, jobs, chunksize=1))
    bad = [r for r in rows if r['status'] != 'ok']
    if bad:
        raise RuntimeError(bad[0]['error'])
    by = {}
    i = 0
    for s in seeds:
        for name, _ in nets:
            by.setdefault(name, {})[s] = rows[i]
            i += 1
    out = dict(seeds=len(seeds), sims=512, nets={})
    for name, _ in nets:
        rs = list(by[name].values())
        bs = [b for r in rs for b in r['battles']]
        out['nets'][name] = dict(
            mean_floor=statistics.mean(r['floor'] for r in rs),
            floors=[r['floor'] for r in rs],
            wins=sum(r['win'] for r in rs),
            battle_win=statistics.mean(b['win'] for b in bs),
            battle_hp=statistics.mean(b['hp'] for b in bs),
            decisions=sum(r['decisions'] for r in rs))
        z = out['nets'][name]
        print('%-12s floor %.2f win %d/30 battle_win %.4f hp %.4f' % (
            name, z['mean_floor'], z['wins'], z['battle_win'], z['battle_hp']), flush=True)
    base = by['base_r4']
    out['paired'] = {}
    for name, _ in nets[1:]:
        diffs = [by[name][s]['floor'] - base[s]['floor'] for s in seeds]
        m = statistics.mean(diffs)
        se = statistics.stdev(diffs) / len(diffs) ** 0.5
        out['paired'][name] = dict(delta=m, se=se, t=m / se,
                                   wins=sum(d > 0 for d in diffs),
                                   losses=sum(d < 0 for d in diffs))
        print('paired %-12s %+.2f +- %.2f (t=%.2f)' % (name, m, se, m / se), flush=True)
    (DIAG / 'puct_eval.json').write_text(json.dumps(out, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
