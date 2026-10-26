"""Measure deck growth on the seed that overflows Deck::MAX_SIZE (96)."""
import json
import random
import sys
from pathlib import Path

ROOT = Path('/home/doulingfeng/idea/sts')
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v3_soft as V3

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 381834348
V3.init_worker(str(ROOT / 'deployment/runs_v2/armD/source'))
sts, AG, torch = V3.sts, V3.AG, V3.torch
log = []


def size(gc):
    try:
        return len(gc.deck)
    except Exception:
        return None


def patched_noncombat(gc, agnet):
    kind, descs, actions = AG.build_choices(gc)
    if not descs:
        if gc.screen_state == sts.ScreenState.REWARDS:
            gc.skip_reward_cards()
            return False
        raise RuntimeError('No noncombat actions: ' + kind)
    with torch.inference_mode():
        scores = agnet.score(torch.tensor(AG.obs_vec(gc)), descs)
    idx = int(scores.argmax())
    n = size(gc)
    try:
        actions[idx](gc)
    except Exception as e:
        log.append(dict(floor=gc.floor_num, screen=str(gc.screen_state), kind=kind,
                        deck=n, n_actions=len(descs), idx=idx, error=repr(e)))
        print(json.dumps(log[-1]), flush=True)
        actions[-1](gc)
    return True


V3._noncombat = patched_noncombat
policy, value = V3.load_nets(str(ROOT / 'deployment/runs_v2/armD/round4_policy.pt'),
                             str(ROOT / 'deployment/runs_v2/armD/round4_value.pt'))
agnet = V3.load_armg()
cfg = dict(eval_sims=512, n_full=1, n_fast=1, p_full=1.0, archive_every=0,
           archive_policy=0, behavior='search', prune_thr=0.0, native_frac=0.0,
           native_sims=0, native_soft=0, search_archive=0.0, native_timed_ms=0.0,
           n_full_timed_ms=0.0, eval_timed_ms=130.0,
           teacher_cpp=1, teacher_ms=130.0, teacher_cpuct=3.0,
           teacher_anneal=0.0, teacher_prior_mode=0, teacher_playout_mode=1,
           teacher_eps=0.05, teacher_prior_temp=1.0, teacher_topk=0,
           teacher_temp=1.0)
try:
    r = V3.run_fresh(seed, policy, value, agnet, cfg, random.Random(seed * 1000003 + 17),
                     mode='train')
    print(json.dumps(dict(ok=True, floor=r['floor'], overlfows=log)), flush=True)
except Exception as e:
    import traceback
    print(json.dumps(dict(ok=False, error=repr(e), overflows=log,
                          trace=traceback.format_exc()[-2000:])), flush=True)
