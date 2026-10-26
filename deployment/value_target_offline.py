"""Offline comparison of value objectives on one fixed dataset (idea 2 pilot).

Objectives:
  z_reg      regression on win + remaining-HP (current target)
  floor_reg  regression on run floor (2 * floor / 51)
  floor_pair GAZ-style pairwise sign target across runs at the same timestep
  z_pair     pairwise sign target on battle z (control)
All nets start from the armD r4 value checkpoint. Evaluation is on held-out
runs: per-run mean V vs floor (Spearman, run-pair accuracy), state R2 vs z,
and same-timestep pairwise accuracy.
"""
import json
import pickle
import random
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deployment'))
import selfplay_v2 as V2

V2.init_worker(str(ROOT / 'deployment/runs_v2/armD/source'))
import torch
import torch.nn.functional as F

torch.set_num_threads(8)
DATA = ROOT / 'deployment/runs_v2/value_diag/data.pkl'
VALUE_CKPT = ROOT / 'deployment/runs_v2/armD/round4_value.pt'
OUT = ROOT / 'deployment/runs_v2/value_diag'
OUT.mkdir(parents=True, exist_ok=True)


def base_net():
    net = V2.V.ValueNet(V2.V_ARCH)
    net.load_state_dict(torch.load(str(VALUE_CKPT), weights_only=True), strict=False)
    net.train()
    return net


def predict(net, X, bs=4096):
    outs = []
    net.eval()
    with torch.no_grad():
        for i in range(0, len(X), bs):
            outs.append(net.forward_tensor(torch.from_numpy(X[i:i + bs]))[0].numpy())
    net.train()
    return np.concatenate(outs) if outs else np.zeros(0, np.float32)


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    return float(np.corrcoef(ra, rb)[0, 1])


def r2(pred, target):
    pred = np.asarray(pred, np.float64)
    target = np.asarray(target, np.float64)
    base = float(((target - target.mean()) ** 2).mean())
    return float(1.0 - ((pred - target) ** 2).mean() / base) if base > 0 else float('nan')


def train_reg(target, epochs=6, lr=3e-4, batch=256):
    net = base_net()
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    X = torch.from_numpy(g['Xtr'])
    T = torch.from_numpy(target.astype(np.float32))
    n = len(X)
    for ep in range(epochs):
        perm = torch.randperm(n)
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            raw, _, _ = net.forward_tensor(X[idx])
            loss = F.smooth_l1_loss(raw, T[idx], beta=0.25)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
    return net


def sample_pairs(runs, batch, rng, key):
    xs1, xs2, ys = [], [], []
    guard = 0
    while len(xs1) < batch and guard < batch * 50:
        guard += 1
        r1, r2_ = rng.sample(runs, 2)
        n = min(len(r1['states']), len(r2_['states']))
        if n == 0:
            continue
        k = rng.randrange(n)
        if key == 'floor':
            t1, t2 = float(r1['floor']), float(r2_['floor'])
        else:
            t1, t2 = float(r1['z'][k]), float(r2_['z'][k])
        if abs(t1 - t2) < 1e-6:
            continue
        y = 1.0 if t1 > t2 else 0.0
        if rng.random() < 0.5:
            y = 1.0 - y
            xs1.append(r2_['states'][k])
            xs2.append(r1['states'][k])
        else:
            xs1.append(r1['states'][k])
            xs2.append(r2_['states'][k])
        ys.append(y)
    return (torch.from_numpy(np.stack(xs1)), torch.from_numpy(np.stack(xs2)),
            torch.tensor(ys, dtype=torch.float32))


def calibrate_to_z(net):
    pred = predict(net, g['Xtr'])
    a, b = np.polyfit(pred.astype(np.float64), g['ztr'].astype(np.float64), 1)
    with torch.no_grad():
        net.net[-1].weight.mul_(float(a))
        net.net[-1].bias.mul_(float(a)).add_(float(b))
    return float(a), float(b)


def train_pair(key, steps=2500, batch=256, lr=3e-4, tau=0.25):
    net = base_net()
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    rng = random.Random(12345 + (0 if key == 'floor' else 1))
    for step in range(steps):
        x1, x2, y = sample_pairs(g['train_runs'], batch, rng, key)
        v1 = net.forward_tensor(x1)[0]
        v2 = net.forward_tensor(x2)[0]
        loss = F.binary_cross_entropy_with_logits((v1 - v2) / tau, y)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
    calibrate_to_z(net)
    return net


def eval_net(name, net):
    Xv = g['Xva']
    pred = predict(net, Xv)
    per_run = []
    for r in g['val_runs']:
        if len(r['idx']) == 0:
            continue
        per_run.append(dict(floor=r['floor'], v=float(pred[r['idx']].mean()),
                            z=float(r['z'].mean())))
    floors = np.array([p['floor'] for p in per_run], np.float64)
    vs = np.array([p['v'] for p in per_run], np.float64)
    pairs = [(i, j) for i in range(len(per_run)) for j in range(i + 1, len(per_run))]
    acc = float(np.mean([bool((vs[i] > vs[j]) == (floors[i] > floors[j])) for i, j in pairs])) if pairs else float("nan")
    rng = random.Random(99)
    hits = 0
    tot = 0
    for _ in range(2000):
        r1, r2_ = rng.sample(g['val_runs'], 2)
        n = min(len(r1['states']), len(r2_['states']))
        if n == 0 or r1['floor'] == r2_['floor']:
            continue
        k = rng.randrange(n)
        p1 = float(predict(net, r1['states'][k:k + 1])[0])
        p2 = float(predict(net, r2_['states'][k:k + 1])[0])
        hits += int((p1 > p2) == (r1['floor'] > r2_['floor']))
        tot += 1
    out = dict(name=name, run_spearman=spearman(vs, floors),
               run_pair_accuracy=float(acc),
               same_k_pair_accuracy=(hits / tot if tot else None),
               state_r2_z=r2(pred, g['zva']),
               state_r2_floor=r2(pred, g['flva']),
               pred_mean=float(pred.mean()), pred_std=float(pred.std()))
    torch.save(net.state_dict(), OUT / (name + '_value.pt'))
    return out


def main():
    global g
    runs = pickle.load(open(DATA, 'rb'))
    runs.sort(key=lambda r: r['seed'])
    train_runs = [r for i, r in enumerate(runs) if i % 4 != 0]
    val_runs = [r for i, r in enumerate(runs) if i % 4 == 0]
    Xtr = np.concatenate([r['states'] for r in train_runs])
    ztr = np.concatenate([r['z'] for r in train_runs])
    fltr = np.concatenate([np.full(len(r['states']), r['floor'] / 51.0 * 2.0, np.float32)
                           for r in train_runs])
    Xva = np.concatenate([r['states'] for r in val_runs])
    zva = np.concatenate([r['z'] for r in val_runs])
    flva = np.concatenate([np.full(len(r['states']), r['floor'] / 51.0 * 2.0, np.float32)
                           for r in val_runs])
    pos = 0
    for r in val_runs:
        r['idx'] = np.arange(pos, pos + len(r['states']))
        pos += len(r['states'])
    g = dict(train_runs=train_runs, val_runs=val_runs, Xtr=Xtr, ztr=ztr, fltr=fltr,
             Xva=Xva, zva=zva, flva=flva)
    results = []
    results.append(eval_net('base_r4', base_net()))
    net = train_reg(ztr)
    results.append(eval_net('z_reg', net))
    net = train_reg(fltr)
    results.append(eval_net('floor_reg', net))
    net = train_pair('floor')
    results.append(eval_net('floor_pair', net))
    net = train_pair('z')
    results.append(eval_net('z_pair', net))
    print(json.dumps(dict(runs=len(runs), train_runs=len(train_runs), val_runs=len(val_runs),
                          train_states=len(Xtr), val_states=len(Xva), results=results), indent=2),
          flush=True)
    json.dump(dict(results=results), open(OUT / 'offline_results.json', 'w'), indent=2)


if __name__ == '__main__':
    main()
