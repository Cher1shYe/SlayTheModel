"""Collect battle states with both battle-level and run-level returns for the
value-target experiment (idea 2).

Each sampled state carries: battle z = win + hp (current target), run floor.
No training happens here; the offline script compares regression targets and
the GAZ-style pairwise sign objective on identical data.
"""
import argparse, json, os, pickle, random, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v2 as V2

EVAL = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt').read_text().splitlines()
        if x.strip() and not x.startswith('#')]
POLICY = ROOT / 'deployment/runs_v2/armD/round4_policy.pt'
VALUE = ROOT / 'deployment/runs_v2/armD/round4_value.pt'
SOURCE = ROOT / 'deployment/runs_v2/armD/source'


def init_worker(_):
    V2.init_worker(str(SOURCE))


def collect(seed):
    sts, B, torch = V2.sts, V2.B, V2.torch
    policy, _ = V2.load_nets(str(POLICY), str(VALUE))
    agnet = V2.load_armg()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = 2000; V2.SP._set_all_pauses(ag)
    states, zs, ts, bids = [], [], [], []
    step = 0
    battle_idx = 0
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state != sts.ScreenState.BATTLE:
            if not V2._noncombat(gc, agnet):
                continue
            continue
        bc = sts.BattleContext(); bc.init(gc)
        battle_idx += 1
        while bc.outcome == sts.Outcome.UNDECIDED:
            acts = sts.get_legal_actions(bc)
            if not acts:
                raise RuntimeError('no actions')
            if len(acts) > 1 and step % 2 == 0:
                states.append(np.asarray(B.encode_battle(bc), dtype=np.float32))
                ts.append(step); bids.append(battle_idx)
            if len(acts) == 1:
                acts[0].execute(bc)
            else:
                st = B.encode_battle(bc); hd = list(bc.hand)
                with torch.inference_mode():
                    lg = policy.score(st, [B.cand_desc(bc, a, hd) for a in acts])
                acts[int(lg.argmax())].execute(bc)
            step += 1
        if bc.outcome == sts.Outcome.UNDECIDED:
            raise RuntimeError('battle truncated')
        z, win, hp = V2.battle_targets(bc)
        # assign z to the states collected in this battle
        count = sum(1 for b in bids if b == battle_idx)
        zs.extend([z] * count)
        bc.exit_battle(gc)
    if gc.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('run truncated')
    return dict(seed=seed, floor=int(gc.floor_num),
                win=bool(gc.outcome == sts.GameOutcome.PLAYER_VICTORY),
                states=np.stack(states) if states else np.zeros((0, V2.B.STATE_DIM), np.float32),
                z=np.asarray(zs, np.float32), t=np.asarray(ts, np.int32),
                battle=np.asarray(bids, np.int32))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--runs', type=int, default=300)
    p.add_argument('--workers', type=int, default=32)
    p.add_argument('--out', type=Path, default=ROOT / 'deployment/runs_v2/value_diag/data.pkl')
    a = p.parse_args()
    rng = random.Random(20261027)
    seeds = list(EVAL)
    while len(seeds) < a.runs:
        s = rng.randint(1, 10 ** 9)
        if s not in seeds:
            seeds.append(s)
    seeds = seeds[:a.runs]
    with ProcessPoolExecutor(max_workers=a.workers, initializer=init_worker,
                             initargs=(str(SOURCE),)) as pool:
        runs = list(pool.map(collect, seeds, chunksize=1))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'wb') as f:
        pickle.dump(runs, f, protocol=4)
    n = sum(len(r['states']) for r in runs)
    floors = [r['floor'] for r in runs]
    print(json.dumps(dict(runs=len(runs), states=n,
                          floor_mean=float(np.mean(floors)), floor_std=float(np.std(floors)),
                          floor_min=min(floors), floor_max=max(floors),
                          wins=sum(r['win'] for r in runs)), indent=2), flush=True)


if __name__ == '__main__':
    main()
