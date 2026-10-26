"""Scale-matched search eval for the GAZ PTP value net.

The pair loss fixes only the ordering, so the raw output scale is arbitrary
(the trained net came out with std 10.3 and the regression calibration shrank
it to 0.13).  Here the net is rescaled to the base value net's mean/std on a
representative state sample, which keeps its ranking but gives it the same
influence inside PUCT as the baseline value function.  Base and scale-matched
nets are then compared with PUCT@512 on the 30 eval seeds.
"""
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path('/home/doulingfeng/idea/sts')
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v3_soft as V3
import gaz_ptp as G

V3.init_worker(str(G.SOURCE))
torch = V3.torch
torch.set_num_threads(8)

eval_seeds = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
              .read_text(encoding='utf-8').splitlines()
              if x.strip() and not x.startswith('#')][:30]

# representative state sample (2 eval seeds, labels unused)
rows = [G.collect_one((s, *G.CUR)) for s in eval_seeds[:2]]
rows = [r for r in rows if r['ok']]
XA = np.concatenate([r['states'] for r in rows])
print('calibration states', XA.shape, flush=True)

base = G.load_value(G.BASE_VALUE)
ptp = G.load_value(G.OUT / 'gaz_ptp_value.pt')
pb = G.predict(base, XA)
pn = G.predict(ptp, XA)
a = float(pb.std() / pn.std())
b = float(pb.mean() - a * pn.mean())
with torch.no_grad():
    ptp.net[-1].weight.mul_(a)
    ptp.net[-1].bias.mul_(a).add_(b)
torch.save(ptp.state_dict(), G.OUT / 'gaz_ptp_value_sm.pt')
print('scale-match a=%.4f b=%.4f; ptp std %.4f -> %.4f (base %.4f)' % (
    a, b, float(pn.std()), float(G.predict(ptp, XA).std()), float(pb.std())), flush=True)

cfg = dict(eval_sims=512, n_full=1, n_fast=1, p_full=0.0, archive_every=0,
           archive_policy=0, behavior='search', prune_thr=0.0, native_frac=0.0,
           native_sims=0, native_soft=0, search_archive=0.0, native_timed_ms=0.0,
           n_full_timed_ms=0.0, eval_timed_ms=130.0, root_min_visits=1)
wps = str(G.RUN / 'round4_policy.pt')
jobs = [(s, 'puct', wps, str(G.BASE_VALUE), cfg, 1.0) for s in eval_seeds] + \
       [(s, 'puct', wps, str(G.OUT / 'gaz_ptp_value_sm.pt'), cfg, 1.0) for s in eval_seeds]
with ProcessPoolExecutor(max_workers=32, initializer=V3.init_worker,
                         initargs=(str(G.SOURCE),)) as pool:
    ev = list(pool.map(V3.play, jobs, chunksize=1))
bad = [r for r in ev if r['status'] != 'ok']
if bad:
    print('ERROR', bad[0]['error'], flush=True)
    sys.exit(1)
bf = [r['floor'] for r in ev[:len(eval_seeds)]]
pf = [r['floor'] for r in ev[len(eval_seeds):]]
d = [x - y for x, y in zip(pf, bf)]
m = statistics.mean(d)
se = statistics.stdev(d) / len(d) ** 0.5
print('PUCT@512 scale-matched: base %.2f  ptp_sm %.2f  paired %+.2f +- %.2f (t=%.2f) W/L/T %d/%d/%d' % (
    statistics.mean(bf), statistics.mean(pf), m, se, m / se,
    sum(x > 0 for x in d), sum(x < 0 for x in d), sum(x == 0 for x in d)), flush=True)
json.dump(dict(base=statistics.mean(bf), ptp_sm=statistics.mean(pf), delta=m, se=se,
               t=m / se, scale=dict(a=a, b=b), base_floors=bf, ptp_floors=pf),
          open(G.OUT / 'gaz_ptp_sm_eval.json', 'w'), indent=1)
