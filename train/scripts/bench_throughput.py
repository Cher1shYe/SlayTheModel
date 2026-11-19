"""Throughput of 'network plays everything, no search' on this Mac (single thread).

Random legal actions everywhere (combat and out of combat); times per decision:
engine step, observation export from C++, Python encoding (obs.py), and network forward
for several batch sizes / widths. Usage (from train/):
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 PYTHONPATH=. python scripts/bench_throughput.py [runs]
"""
import random
import sys
import time

import numpy as np
import torch

from spire_rl import obs as uo
from spire_rl.sim import sim
from spire_rl.net import UnifiedNet, UnifiedNetConfig, collate, count_params

COMBAT = sim.RunScreen.COMBAT
T = {"step_combat": 0.0, "step_macro": 0.0, "entity_obs": 0.0, "macro_obs": 0.0, "encode": 0.0}
N = {"combat": 0, "macro": 0, "forced": 0}
samples = []
runs, floors = int(sys.argv[1]) if len(sys.argv) > 1 else 40, []
rng = random.Random(0)
t_all = time.perf_counter()
for r in range(runs):
    rc = sim.RunContext()
    rc.init(9_000_000 + r, 0)
    ctx = None
    steps = 0
    while not rc.is_terminal and steps < 5000:
        steps += 1
        if rc.screen == COMBAT:
            bc = rc.battle
            legal = bc.legal_actions()
            if not legal:
                rc.step_combat(1, 0, 0, 0)
                ctx = None
                continue
            if len(legal) == 1:
                N["forced"] += 1
                t = time.perf_counter(); rc.step_combat(*legal[0]); T["step_combat"] += time.perf_counter() - t
                continue
            if ctx is None:
                t = time.perf_counter(); m = rc.macro_observation(); T["macro_obs"] += time.perf_counter() - t
                t = time.perf_counter(); ctx = uo.run_context(m); T["encode"] += time.perf_counter() - t
            t = time.perf_counter(); e = bc.entity_observation(); T["entity_obs"] += time.perf_counter() - t
            t = time.perf_counter(); o = uo.combat_obs(ctx, e); T["encode"] += time.perf_counter() - t
            if len(samples) < 2000 and rng.random() < 0.3:
                samples.append(o)
            N["combat"] += 1
            a = legal[rng.randrange(len(legal))]
            t = time.perf_counter(); rc.step_combat(*a); T["step_combat"] += time.perf_counter() - t
        else:
            ctx = None
            t = time.perf_counter(); m = rc.macro_observation(); T["macro_obs"] += time.perf_counter() - t
            t = time.perf_counter(); o = uo.macro_obs(m); T["encode"] += time.perf_counter() - t
            n = len(m["cand_type"])
            if n == 0:
                break
            if len(samples) < 2000 and rng.random() < 0.3:
                samples.append(o)
            N["macro"] += 1
            k = rng.randrange(n)
            t = time.perf_counter(); rc.step(int(m["cand_type"][k]), int(m["cand_index"][k])); T["step_macro"] += time.perf_counter() - t
    floors.append(int(rc.floor))
wall = time.perf_counter() - t_all
dec = N["combat"] + N["macro"]
print(f"runs {runs} mean floor {np.mean(floors):.1f}  decisions {dec} (combat {N['combat']}, macro {N['macro']}, forced {N['forced']})")
print(f"wall {wall:.1f}s  = {1e6 * wall / dec:.0f} us/decision")
for k, v in T.items():
    print(f"  {k:12s} {1e6 * v / dec:7.0f} us/decision")

torch.set_num_threads(1)
for name, cfg in (("default 128x(3+2)", UnifiedNetConfig()),
                  ("256x(4+4)", UnifiedNetConfig(dim=256, ctx_layers=4, combat_layers=4, heads=8)),
                  ("384x(6+6)", UnifiedNetConfig(dim=384, ctx_layers=6, combat_layers=6, heads=8))):
    net = UnifiedNet(cfg).eval()
    print(f"net {name}: {count_params(net) / 1e6:.1f}M params")
    for bs in (1, 64, 256):
        obs = samples[:bs]
        t = time.perf_counter(); b = collate(obs); tc = time.perf_counter() - t
        with torch.no_grad():
            net(b)
            t = time.perf_counter()
            for _ in range(3):
                net(b)
            tf = (time.perf_counter() - t) / 3
        print(f"  batch {bs:4d}: collate {1e6 * tc / bs:6.0f} us/obs  forward(CPU 1 thread) {1e6 * tf / bs:7.0f} us/obs")
