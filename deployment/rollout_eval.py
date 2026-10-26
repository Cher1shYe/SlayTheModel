"""One eval config per process (env read at import time in fast_puct)."""
import os
os.environ.setdefault('STS_FAST_PUCT', '1')
import argparse, statistics, sys
sys.path.insert(0, "deployment")
import selfplay_v2 as V
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--run', default='deployment/runs_v2/armD')
p.add_argument('--round', type=int, default=4)
p.add_argument('--source', default='deployment/runs_v2/lcb_src')
p.add_argument('--seeds', type=int, default=15)
p.add_argument('--workers', type=int, default=12)
p.add_argument('--sims', type=int, default=512)
p.add_argument('--timed-ms', type=float, default=0.0)
p.add_argument('--mode', default='puct')
p.add_argument('--root-lcb', type=int, default=0)
p.add_argument('--lcb-k', type=float, default=5.0)
p.add_argument('--lcb-min-prop', type=float, default=0.15)
p.add_argument('--cpuct-native', type=float, default=3.0)
p.add_argument('--prior-temp', type=float, default=1.0)
p.add_argument('--uniform-priors', type=int, default=0)
p.add_argument('--puct-anneal', type=float, default=0.0)
p.add_argument('--puct-prior-mode', type=int, default=0)
p.add_argument('--gaz-c-visit', type=float, default=50.0)
p.add_argument('--gaz-c-scale', type=float, default=1.0)
p.add_argument('--restarts', type=int, default=2)
p.add_argument('--value-prior-temp', type=float, default=0.05)
p.add_argument('--play-horizon', type=int, default=2)
p.add_argument('--play-samples', type=int, default=1)
p.add_argument('--playout-mode', type=int, default=1)
p.add_argument('--playout-eps', type=float, default=0.0)
p.add_argument('--name', default='')
a = p.parse_args()

run = Path(a.run)
seeds = [int(x) for x in open("sts-rl-agent/eval/eval_seeds_50.txt").read().splitlines()
         if x.strip() and not x.startswith("#")][:a.seeds]
wp = str(run / f"round{a.round}_policy.pt")
wv = str(run / f"round{a.round}_value.pt")
name = a.name or f"{a.mode}_sims{a.sims}_t{a.timed_ms}_lcb{a.root_lcb}"
print("cfg", name, "mix", os.environ.get('STS_ROLLOUT_MIX'), "N", os.environ.get('STS_ROLLOUT_N'),
      "sims", a.sims, "timed", a.timed_ms, "seeds", len(seeds), flush=True)
with ProcessPoolExecutor(max_workers=a.workers, initializer=V.init_worker,
                         initargs=(a.source,)) as pool:
    cfg = dict(eval_sims=a.sims, eval_timed_ms=a.timed_ms if a.timed_ms > 0 else 130.0,
               n_full=1, n_fast=1, p_full=0.0, archive_every=0,
               native_frac=0.0, native_sims=0, root_min_visits=1,
               root_lcb=a.root_lcb, lcb_k=a.lcb_k, lcb_min_prop=a.lcb_min_prop,
               cpuct_native=a.cpuct_native, prior_temp=a.prior_temp,
               uniform_priors=a.uniform_priors, puct_anneal=a.puct_anneal, puct_prior_mode=a.puct_prior_mode,
               gaz_c_visit=a.gaz_c_visit, gaz_c_scale=a.gaz_c_scale, restarts=a.restarts, value_prior_temp=a.value_prior_temp,
               play_horizon=a.play_horizon, play_samples=a.play_samples,
               playout_mode=a.playout_mode, playout_eps=a.playout_eps)
    rows = list(pool.map(V.play, [(s, a.mode, wp, wv, cfg, 1.0) for s in seeds]))
bad = [r for r in rows if r['status'] != 'ok']
if bad:
    print("ERROR", bad[0]['error'], flush=True)
    raise SystemExit(1)
fl = [r['floor'] for r in rows]
bs = [b for r in rows for b in r['battles']]
ms = [b['search_ms'] / max(1, b['searched']) for b in bs if b['searched']]
sim = [b['sims'] / max(1, b['searched']) for b in bs if b['searched']]
print("%s floor %.2f win %.4f hp %.4f ms/dec %.0f sims/dec %.0f" % (
    name, statistics.mean(fl), statistics.mean(b['win'] for b in bs),
    statistics.mean(b['hp'] for b in bs), statistics.mean(ms), statistics.mean(sim)), flush=True)
print("DONE", flush=True)
