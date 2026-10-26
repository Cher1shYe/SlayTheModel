"""GAZ PTP paired-value pilot with dual actors.

Current actor = armD r4 policy, historical actor = armD r0 (initial armB
weights).  Both actors play the same seeds with their own greedy battle
policy; states are paired at the same cumulative battle-decision index k
inside the same seed, and the target is sign(r_current - r_historical) with
r = final floor.  V is trained with a Bradley-Terry logistic loss on
V(s) - V(s'), then affinely calibrated to the base value net's scale on the
current actor's state distribution.  Finally the new value net is compared
with the base net inside PUCT@512 on 30 held-out seeds.
"""
import json
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path('/home/doulingfeng/idea/sts')
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v3_soft as V3

RUN = ROOT / 'deployment/runs_v2/armD'
OUT = ROOT / 'deployment/runs_v2/gaz_diag'
SOURCE = RUN / 'source'
CUR = (str(RUN / 'round4_policy.pt'), str(RUN / 'round4_value.pt'))
HIS = (str(RUN / 'round0_policy.pt'), str(RUN / 'round0_value.pt'))
BASE_VALUE = RUN / 'round4_value.pt'
STRIDE = 2
CAP = 200
N_SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 120
COLLECT_WORKERS = 48
EVAL_WORKERS = 32


def collect_one(job):
    seed, wp, wv = job
    sts = V3.sts
    policy, value = V3.load_nets(wp, wv)
    agnet = V3.load_armg()
    torch = V3.torch
    B = V3.B
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent()
    ag.simulation_count_base = 2000
    V3.SP._set_all_pauses(ag)
    ks, states = [], []
    k = 0
    t0 = time.perf_counter()
    try:
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
                if k % STRIDE == 0 and len(states) < CAP:
                    ks.append(k)
                    states.append(np.asarray(state, dtype=np.float32))
                with torch.inference_mode():
                    idx = int(policy.score(state, descs).argmax())
                actions[idx].execute(bc)
            bc.exit_battle(gc)
        if gc.outcome == sts.GameOutcome.UNDECIDED:
            raise RuntimeError('run truncated')
    except Exception as e:
        return dict(seed=seed, ok=False, error=repr(e), seconds=time.perf_counter() - t0)
    return dict(seed=seed, ok=True, floor=gc.floor_num,
                win=bool(gc.outcome == sts.GameOutcome.PLAYER_VICTORY),
                ks=ks, states=np.stack(states) if states else np.zeros((0, 893), np.float32),
                seconds=time.perf_counter() - t0)


def load_value(path):
    net = V3.V.ValueNet(V3.V_ARCH)
    net.load_state_dict(V3.torch.load(str(path), weights_only=True), strict=False)
    return net


def predict(net, X, bs=4096):
    net.eval()
    outs = []
    with V3.torch.no_grad():
        for i in range(0, len(X), bs):
            outs.append(net.forward_tensor(V3.torch.from_numpy(X[i:i + bs]))[0].numpy())
    net.train()
    return np.concatenate(outs) if outs else np.zeros(0, np.float32)


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    V3.init_worker(str(SOURCE))
    _all = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
            .read_text(encoding='utf-8').splitlines()
            if x.strip() and not x.startswith('#')]
    eval_seeds = _all[:30]
    evset = set(eval_seeds)
    seeds = [s for s in _all if s not in evset]
    rng = random.Random(777)
    while len(seeds) < N_SEEDS:
        s = rng.randint(1, 10 ** 9)
        if s not in seeds:
            seeds.append(s)
    seeds = seeds[:N_SEEDS]
    jobs = [(s, *CUR) for s in seeds] + [(s, *HIS) for s in seeds]

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=COLLECT_WORKERS, initializer=V3.init_worker,
                             initargs=(str(SOURCE),)) as pool:
        rows = list(pool.map(collect_one, jobs, chunksize=1))
    cur = {r['seed']: r for r in rows[:len(seeds)] if r['ok']}
    his = {r['seed']: r for r in rows[len(seeds):] if r['ok']}
    bad = [r for r in rows if not r['ok']]
    seeds_ok = [s for s in seeds if s in cur and s in his]
    print('collected %d/%d seeds ok (%d failed), %.1fs' % (
        len(seeds_ok), len(seeds), len(bad), time.perf_counter() - t0), flush=True)

    rng = random.Random(4242)
    rng.shuffle(seeds_ok)
    n_val = max(1, len(seeds_ok) // 5)
    val_seeds = set(seeds_ok[:n_val])
    train_seeds = [s for s in seeds_ok if s not in val_seeds]

    def pairs_for(seed_list):
        xs1, xs2, ys = [], [], []
        for s in seed_list:
            a, b = cur[s], his[s]
            ad = dict(zip(a['ks'], range(len(a['ks']))))
            bd = dict(zip(b['ks'], range(len(b['ks']))))
            both = sorted(set(ad) & set(bd))
            rA, rB = a['floor'], b['floor']
            if rA == rB:
                continue
            for k in both:
                xa = a['states'][ad[k]]
                xb = b['states'][bd[k]]
                y = 1.0 if rA > rB else 0.0
                if rng.random() < 0.5:
                    xa, xb = xb, xa
                    y = 1.0 - y
                xs1.append(xa)
                xs2.append(xb)
                ys.append(y)
        if not xs1:
            return (np.zeros((0, 893), np.float32), np.zeros((0, 893), np.float32),
                    np.zeros(0, np.float32))
        return (np.stack(xs1), np.stack(xs2), np.asarray(ys, np.float32))

    X1, X2, Y = pairs_for(train_seeds)
    V1, V2, VY = pairs_for(list(val_seeds))
    print('train pairs %d, val pairs %d' % (len(Y), len(VY)), flush=True)
    if len(Y) < 100:
        print('not enough pairs, abort', flush=True)
        return

    torch = V3.torch
    F = V3.F
    torch.set_num_threads(8)
    net = load_value(BASE_VALUE)
    opt = torch.optim.Adam(net.parameters(), lr=3e-4)
    tau = 0.5
    bs = 256
    steps = 3000
    X1t = torch.from_numpy(X1)
    X2t = torch.from_numpy(X2)
    Yt = torch.from_numpy(Y)
    t0 = time.perf_counter()
    loss = None
    for step in range(steps):
        idx = torch.randint(0, len(Y), (bs,))
        v1 = net.forward_tensor(X1t[idx])[0]
        v2 = net.forward_tensor(X2t[idx])[0]
        loss = F.binary_cross_entropy_with_logits((v1 - v2) / tau, Yt[idx])
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
    print('trained %d steps in %.1fs, final loss %.4f' % (
        steps, time.perf_counter() - t0, float(loss)), flush=True)

    def pair_acc(net_):
        if len(VY) == 0:
            return float('nan')
        p1 = predict(net_, V1)
        p2 = predict(net_, V2)
        return float(np.mean((p1 > p2) == (VY > 0.5)))

    acc0 = pair_acc(load_value(BASE_VALUE))
    acc1 = pair_acc(net)
    print('val pair acc: base %.4f -> ptp %.4f' % (acc0, acc1), flush=True)

    # calibrate scale/mean to the base net on the current actor's states
    XA = np.concatenate([cur[s]['states'] for s in seeds_ok if len(cur[s]['states'])])
    base = load_value(BASE_VALUE)
    pb = predict(base, XA)
    pn = predict(net, XA)
    a, b = np.polyfit(pn.astype(np.float64), pb.astype(np.float64), 1)
    with torch.no_grad():
        net.net[-1].weight.mul_(float(a))
        net.net[-1].bias.mul_(float(a)).add_(float(b))
    print('calibration a=%.4f b=%.4f; pred std %.4f -> %.4f' % (
        a, b, float(pn.std()), float(predict(net, XA).std())), flush=True)
    torch.save(net.state_dict(), OUT / 'gaz_ptp_value.pt')

    per_run = []
    for s in seeds_ok:
        r = cur[s]
        if len(r['states']) == 0:
            continue
        v = float(predict(net, r['states']).mean())
        per_run.append((r['floor'], v))
    floors = np.array([x[0] for x in per_run], np.float64)
    vs = np.array([x[1] for x in per_run], np.float64)
    rho = spearman(vs, floors)
    print('run spearman (floor vs mean V): %.4f' % rho, flush=True)

    # PUCT@512 comparison: base vs ptp, paired over 30 eval seeds
    eval_seeds = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
                  .read_text(encoding='utf-8').splitlines()
                  if x.strip() and not x.startswith('#')][:30]
    cfg = dict(eval_sims=512, n_full=1, n_fast=1, p_full=0.0, archive_every=0,
               archive_policy=0, behavior='search', prune_thr=0.0, native_frac=0.0,
               native_sims=0, native_soft=0, search_archive=0.0, native_timed_ms=0.0,
               n_full_timed_ms=0.0, eval_timed_ms=130.0, root_min_visits=1)
    wps = str(RUN / 'round4_policy.pt')
    ev_jobs = [(s, 'puct', wps, str(BASE_VALUE), cfg, 1.0) for s in eval_seeds] + \
              [(s, 'puct', wps, str(OUT / 'gaz_ptp_value.pt'), cfg, 1.0) for s in eval_seeds]
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=EVAL_WORKERS, initializer=V3.init_worker,
                             initargs=(str(SOURCE),)) as pool:
        ev = list(pool.map(V3.play, ev_jobs, chunksize=1))
    badr = [r for r in ev if r['status'] != 'ok']
    if badr:
        print('EVAL ERROR', badr[0]['error'], flush=True)
        return
    base_rows = ev[:len(eval_seeds)]
    ptp_rows = ev[len(eval_seeds):]
    bf = [r['floor'] for r in base_rows]
    pf = [r['floor'] for r in ptp_rows]
    d = [x - y for x, y in zip(pf, bf)]
    m = statistics.mean(d)
    se = statistics.stdev(d) / len(d) ** 0.5
    print('PUCT@512 base %.2f  ptp %.2f  paired %+.2f +- %.2f (t=%.2f) W/L/T %d/%d/%d' % (
        statistics.mean(bf), statistics.mean(pf), m, se, m / se,
        sum(x > 0 for x in d), sum(x < 0 for x in d), sum(x == 0 for x in d)), flush=True)
    json.dump(dict(seeds=len(seeds_ok), train_pairs=len(Y), val_pairs=len(VY),
                   val_pair_acc_base=acc0, val_pair_acc_ptp=acc1,
                   calib=dict(a=float(a), b=float(b)), run_spearman=rho,
                   eval=dict(base_mean=statistics.mean(bf), ptp_mean=statistics.mean(pf),
                             delta=m, se=se, t=m / se, base=bf, ptp=pf)),
              open(OUT / 'gaz_ptp_results.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
