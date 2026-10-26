"""Paired, interleaved benchmark: PUCT vs time-matched native MCTS.

Both modes run on the same seeds in one pool, with the two modes for each seed
queued adjacently, so machine load drifts affect both equally.
"""
import argparse, json, random, statistics, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, "deployment")
import selfplay_v2 as V2

p = argparse.ArgumentParser()
p.add_argument('--run', default='deployment/runs_v2/armD')
p.add_argument('--round', type=int, default=4)
p.add_argument('--source', default='deployment/runs_v2/lcb_src')
p.add_argument('--workers', type=int, default=24)
p.add_argument('--extra-seeds', type=int, default=100)
p.add_argument('--timed-ms', type=float, default=130.0)
p.add_argument('--sims', type=int, default=512)
p.add_argument('--cpuct', type=float, default=16.0)
p.add_argument('--prior-temp', type=float, default=1.0)
p.add_argument('--prior-mode', type=int, default=0)
p.add_argument('--anneal', type=float, default=0.0)
p.add_argument('--uniform-priors', type=int, default=0)
p.add_argument('--gaz-c-visit', type=float, default=50.0)
p.add_argument('--gaz-c-scale', type=float, default=1.0)
p.add_argument('--restarts', type=int, default=2)
p.add_argument('--value-prior-temp', type=float, default=0.05)
p.add_argument('--play-horizon', type=int, default=2)
p.add_argument('--playout-mode', type=int, default=1)
p.add_argument('--playout-eps', type=float, default=0.0)
p.add_argument('--modes', default='native_timed,puct_native_timed')
p.add_argument('--out', default='deployment/runs_v2/final_bench.json')
a = p.parse_args()

run = Path(a.run)
base = [int(x) for x in (V2.ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
        .read_text(encoding='utf-8').splitlines()
        if x.strip() and not x.startswith('#')]
rng = random.Random(424242)
seeds = list(dict.fromkeys(base))
while len(seeds) < len(base) + a.extra_seeds:
    s = rng.randint(1, 10 ** 9)
    if s not in seeds:
        seeds.append(s)
wp = str(run / f'round{a.round}_policy.pt')
wv = str(run / f'round{a.round}_value.pt')
modes = [m for m in a.modes.split(',') if m]
cfg = dict(eval_sims=a.sims, eval_timed_ms=a.timed_ms, n_full=1, n_fast=1, p_full=0.0,
           archive_every=0, native_frac=0.0, native_sims=0, root_min_visits=1,
           cpuct_native=a.cpuct, prior_temp=a.prior_temp,
           puct_prior_mode=a.prior_mode, puct_anneal=a.anneal,
           uniform_priors=a.uniform_priors,
           gaz_c_visit=a.gaz_c_visit, gaz_c_scale=a.gaz_c_scale,
           restarts=a.restarts, value_prior_temp=a.value_prior_temp,
           play_horizon=a.play_horizon,
           playout_mode=a.playout_mode, playout_eps=a.playout_eps)
jobs = [(s, m, wp, wv, cfg, 1.0) for s in seeds for m in modes]
print("seeds", len(seeds), "modes", modes, "cpuct", a.cpuct, "timed", a.timed_ms, flush=True)
with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                         initargs=(a.source,)) as pool:
    rows = list(pool.map(V2.play, jobs))
bad = [r for r in rows if r['status'] != 'ok']
if bad:
    print("ERROR", bad[0]['error'], flush=True)
    raise SystemExit(1)

by = {}
# rows are ordered seed-major then mode: rebuild
i = 0
for s in seeds:
    for m in modes:
        by.setdefault(m, {})[s] = rows[i]
        i += 1

out = dict(seeds=len(seeds), timed_ms=a.timed_ms, cpuct=a.cpuct, modes={})
for m in modes:
    rs = list(by[m].values())
    bs = [b for r in rs for b in r['battles']]
    ms = [b['search_ms'] / max(1, b['searched']) for b in bs if b['searched']]
    sim = [b['sims'] / max(1, b['searched']) for b in bs if b['searched']]
    out['modes'][m] = dict(
        mean_floor=statistics.mean(r['floor'] for r in rs),
        floors=[r['floor'] for r in rs],
        battle_win=statistics.mean(b['win'] for b in bs),
        battle_hp=statistics.mean(b['hp'] for b in bs),
        mean_decision_ms=statistics.mean(ms), mean_sims=statistics.mean(sim))
    z = out['modes'][m]
    print("%-20s floor %.2f win %.4f hp %.4f ms/dec %.1f sims/dec %.0f" % (
        m, z['mean_floor'], z['battle_win'], z['battle_hp'], z['mean_decision_ms'], z['mean_sims']),
        flush=True)

if len(modes) == 2:
    base_m, other = modes[0], modes[1]
    diffs = [by[other][s]['floor'] - by[base_m][s]['floor'] for s in seeds]
    mean = statistics.mean(diffs)
    se = statistics.stdev(diffs) / len(diffs) ** 0.5
    out['paired'] = dict(base=base_m, other=other, delta=mean, se=se, t=mean / se,
                         wins=sum(d > 0 for d in diffs), losses=sum(d < 0 for d in diffs))
    print("paired %s - %s: %+.2f +- %.2f (t=%.2f; %d win / %d loss / %d tie)" % (
        other, base_m, mean, se, mean / se, sum(d > 0 for d in diffs), sum(d < 0 for d in diffs),
        sum(d == 0 for d in diffs)), flush=True)
Path(a.out).write_text(json.dumps(out, indent=2), encoding='utf-8')
print("saved", a.out, flush=True)
