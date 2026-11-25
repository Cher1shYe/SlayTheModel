"""Largest absolute value of every encoded input column, by entity kind / action kind (DEVLOG 50).

Plays the whole-run smoke setup (relics and cards injected, acts 1-3, see smoke_full_runs.py)
plus plain runs, encodes every decision with the training encoder and reports columns whose
magnitude exceeds a threshold. Used to find unnormalized features.

    cd train && PYTHONPATH=.:.. python scripts/scan_feature_range.py FIRST_SEED COUNT [THRESHOLD]
"""
import collections
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import smoke_full_runs as S                                   # noqa: E402
from spire_rl import public_obs as p                          # noqa: E402
from spire_rl import public_tactics as tactics                # noqa: E402
from spire_rl.driver import Driver                            # noqa: E402
from spire_rl.sim import sim                                  # noqa: E402


def scan(first, count, threshold=3.0):
    ent = collections.defaultdict(float)     # (kind, col) -> max |x|
    cand = collections.defaultdict(float)    # (action kind, col)
    rows = {"global_row": collections.defaultdict(float), "player_row": collections.defaultdict(float)}
    for seed in range(first, first + count):
        rc, rng, _ = S.setup(seed, plain=seed % 3 == 0)
        driver = Driver()
        for _ in range(4000):
            if rc.is_terminal:
                break
            try:
                state = p.from_simulator(rc)
            except Exception:
                break
            if not state.actions:
                break
            d = driver.decide(state)
            if d.verdict:
                break
            o = d.obs
            num = np.abs(np.asarray(o.num))
            big = np.argwhere(num > threshold)
            for r, c in big:
                key = (int(o.kind[r]), int(c))
                ent[key] = max(ent[key], float(num[r, c]))
            cn = np.abs(np.asarray(o.cand_num))
            for r, c in np.argwhere(cn > threshold):
                key = (p.ACTION_KINDS[int(o.cand_type[r])], int(c))
                cand[key] = max(cand[key], float(cn[r, c]))
            for name in rows:
                a = np.abs(np.asarray(getattr(o, name)))
                for c in np.flatnonzero(a > threshold):
                    rows[name][int(c)] = max(rows[name][int(c)], float(a[c]))
            if d.forced is not None:
                index = d.forced
            else:
                allowed = np.flatnonzero(d.allowed)
                plays = [i for i in allowed if state.actions[i].key.kind == "play"]
                index = int(rng.choice(plays if plays and rng.random() < 0.85 else list(allowed)))
            driver.chose(index)
            handle = p.candidate_handle(state, index)
            try:
                ok = rc.step_combat(*handle) if state.facts["combat"] is not None else rc.step(*handle)
            except Exception:
                break
            if not ok:
                break
    return ent, cand, rows


if __name__ == "__main__":
    first, count = int(sys.argv[1]), int(sys.argv[2])
    threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
    ent, cand, rows = scan(first, count, threshold)
    print("entity (kind, col): max")
    for k, v in sorted(ent.items(), key=lambda kv: -kv[1]):
        print(" ", k, round(v, 2))
    print("candidate (action, col): max")
    for k, v in sorted(cand.items(), key=lambda kv: -kv[1]):
        print(" ", k, round(v, 2))
    for name, d in rows.items():
        print(name, {k: round(v, 2) for k, v in sorted(d.items())})
