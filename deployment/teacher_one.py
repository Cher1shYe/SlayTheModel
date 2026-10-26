"""Run one teacher-driven training episode and report status (crash probe)."""
import json
import sys
from pathlib import Path

ROOT = Path('/home/doulingfeng/idea/sts')
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v3_soft as V3

seed = int(sys.argv[1])
V3.init_worker(str(ROOT / 'deployment/runs_v2/armD/source'))
wp = ROOT / 'deployment/runs_v2/armD/round4_policy.pt'
wv = ROOT / 'deployment/runs_v2/armD/round4_value.pt'
cfg = dict(eval_sims=512, n_full=1, n_fast=1, p_full=1.0, archive_every=0,
           archive_policy=0, behavior='search', prune_thr=0.0, native_frac=0.0,
           native_sims=0, native_soft=0, search_archive=0.0, native_timed_ms=0.0,
           n_full_timed_ms=0.0, eval_timed_ms=130.0,
           teacher_cpp=1, teacher_ms=130.0, teacher_cpuct=3.0,
           teacher_anneal=0.0, teacher_prior_mode=0, teacher_playout_mode=1,
           teacher_eps=0.05, teacher_prior_temp=1.0, teacher_topk=0,
           teacher_temp=1.0)
r = V3.play((seed, 'train', str(wp), str(wv), cfg, 1.0))
print(json.dumps(dict(seed=seed, status=r['status'], floor=r.get('floor'),
                      samples=len(r.get('samples', [])),
                      error=((r.get('error') or '')[-3000:]))), flush=True)
sys.exit(0 if r['status'] == 'ok' else 2)
