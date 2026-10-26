"""Compare armD r4 and softB r6 policy priors as PUCT priors on the same states.

For each held-out battle state and each policy net: score the state, run the
same 130 ms C++ teacher search used in training, and measure how close the
prior is to its own teacher's root-visit distribution (KL, top-1 agreement),
plus prior sharpness.  Small policy drift or no KL improvement means the
distillation did not transfer; large drift with no floor gain means the prior
is not the bottleneck.
"""
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path('/home/doulingfeng/idea/sts')
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v3_soft as V3

SOURCE = ROOT / 'deployment/runs_v2/softB/source'
V3.init_worker(str(SOURCE))
sts, AG, B, torch = V3.sts, V3.AG, V3.B, V3.torch

NETS = [
    ('armD_r4', ROOT / 'deployment/runs_v2/armD/round4_policy.pt',
     ROOT / 'deployment/runs_v2/armD/round4_value.pt'),
    ('softB_r6', ROOT / 'deployment/runs_v2/softB/round6_policy.pt',
     ROOT / 'deployment/runs_v2/softB/round6_value.pt'),
]
nets = {}
for tag, p, v in NETS:
    pol, _ = V3.load_nets(str(p), str(v))
    nets[tag] = pol

agnet = V3.load_armg()
STOP = 0


def probs_of(pol, state, descs):
    t0 = time.perf_counter()
    with torch.inference_mode():
        logits = pol.score(state, descs)
        pr = torch.softmax(logits, dim=0).tolist()
    return pr, (time.perf_counter() - t0) * 1000.0


def teacher(bc, actions, priors, money_ms):
    budget = max(1.0, 130.0 - money_ms)
    best, bits, visits, _ev, count = sts.mcts_stats_ex_timed(
        bc, budget, {int(a.bits): float(p) for a, p in zip(actions, priors)},
        3.0, 0.0, 0, 1, 0.05, True)
    arr = [0.0] * len(actions)
    by = {int(b): int(v) for b, v in zip(bits, visits)}
    for i, a in enumerate(actions):
        arr[i] = float(by.get(int(a.bits), 0))
    tot = sum(arr)
    if tot > 0:
        arr = [x / tot for x in arr]
    return arr, count


def ent(p):
    return -sum(x * math.log(x) for x in p if x > 1e-12)


def kl(p, q):
    return sum(x * math.log(x / max(y, 1e-12)) for x, y in zip(p, q) if x > 1e-12)


rows = []


def measure(bc, actions, state, descs):
    prs = {}
    tch = {}
    for tag, pol in nets.items():
        pr, pms = probs_of(pol, state, descs)
        prs[tag] = pr
        tch[tag] = teacher(bc, actions, pr, pms)
    a = prs['armD_r4']
    b = prs['softB_r6']
    row = dict(K=len(actions),
               prior_H_a=ent(a) / math.log(len(a)),
               prior_H_b=ent(b) / math.log(len(b)),
               prior_top1_a=max(a), prior_top1_b=max(b),
               kl_ab=kl(b, a), argmax_ab=int(max(range(len(a)), key=a.__getitem__) ==
                                             max(range(len(b)), key=b.__getitem__)))
    for tag in nets:
        t = tch[tag][0]
        row['visit_H_' + tag] = ent(t) / math.log(len(t))
        row['visit_top1_' + tag] = max(t)
        row['kl_tp_' + tag] = kl(t, prs[tag])
        row['kl_pt_' + tag] = kl(prs[tag], t)
        row['agree_' + tag] = int(max(range(len(t)), key=t.__getitem__) ==
                                  max(range(len(prs[tag])), key=prs[tag].__getitem__))
        row['sims_' + tag] = tch[tag][1]
    rows.append(row)


def play_seed(seed, stride=2, cap=24):
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent()
    ag.simulation_count_base = 2000
    V3.SP._set_all_pauses(ag)
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state != sts.ScreenState.BATTLE:
            V3._noncombat(gc, agnet)
            continue
        bc = sts.BattleContext()
        bc.init(gc)
        k = 0
        while bc.outcome == sts.Outcome.UNDECIDED:
            actions = sts.get_legal_actions(bc)
            if not actions:
                raise RuntimeError('no actions')
            if len(actions) == 1:
                actions[0].execute(bc)
                continue
            state = B.encode_battle(bc)
            hand = list(bc.hand)
            descs = [B.cand_desc(bc, a, hand) for a in actions]
            k += 1
            if k % stride == 0 and len(rows) < cap * 8:
                measure(bc, actions, state, descs)
            with torch.inference_mode():
                idx = int(nets['armD_r4'].score(state, descs).argmax())
            actions[idx].execute(bc)
        bc.exit_battle(gc)


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seeds = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
             .read_text(encoding='utf-8').splitlines()
             if x.strip() and not x.startswith('#')][:n_seeds]
    for s in seeds:
        play_seed(s)
        print('seed', s, 'rows', len(rows), flush=True)
    keys = ['prior_H_a', 'prior_H_b', 'prior_top1_a', 'prior_top1_b', 'kl_ab',
            'argmax_ab', 'visit_H_armD_r4', 'visit_H_softB_r6',
            'visit_top1_armD_r4', 'visit_top1_softB_r6',
            'kl_tp_armD_r4', 'kl_tp_softB_r6', 'kl_pt_armD_r4', 'kl_pt_softB_r6',
            'agree_armD_r4', 'agree_softB_r6', 'sims_armD_r4', 'sims_softB_r6']
    summ = {k: dict(mean=statistics.mean(r[k] for r in rows),
                    median=statistics.median(r[k] for r in rows)) for k in keys}
    out = dict(states=len(rows), seeds=n_seeds, summary=summ, rows=rows)
    (ROOT / 'deployment/runs_v2/soft_diag/prior_drift.json').write_text(
        json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps(summ, indent=1), flush=True)


if __name__ == '__main__':
    main()
