"""Offline pretraining of the unified network's value head q on the training archives
(docs/claude-unified-net-design-20261116.md, step 3; user 2026-11-16: the macro policy starts
from scratch, the value head starts from what the archives say actually happened).

Labels per macro decision (episodes ending in WIN or DEATH only), state in act k:
  q0 = this run beat act k's boss               (always)
  q1 = it beat act k+1 too                      (only if act k was passed and k+1 exists)
  q2 = it beat act k+2 too                      (only if acts k and k+1 were passed and k+2 exists)
These are outcome labels (what happened), not a previous policy's choices, so nothing of the
old policies' behaviour (e.g. ignoring HP) is distilled. Online training later replaces them
with TD targets.

Streams the archive files (they do not fit in memory): each epoch visits the files in a
random order, a few at a time, with a fraction of each episode's decisions sampled.
Held out: games whose seed hash % 5 == 0 (the split of the act-boss offline test,
artifacts/analysis/claude-bossval-20261116), evaluated per act and distance to the boss
(AUC of q0) and with the HP counterfactual (+/-10% HP, everything else unchanged).

Usage (from model/spire_rl):
  python -m spire_rl.unified_pretrain --runs small-b-d1,small-a0-d1,small-a0-d2,small-a0-d3 \
      --root ../.. --out <net.pt> [--epochs 2] [--sample 0.3] [--max-files N] \
      [--device cuda] [--workers 6] [--init <net.pt>] [--max-hours H]
On a GPU the archive decoding is the bottleneck: ``--workers`` processes decode and batch the
files in the background (each takes its own share of the files of a chunk).
"""
from __future__ import annotations

import argparse
import os
import glob
import json
import time

import numpy as np
import torch
import torch.nn.functional as F

from . import unified_obs as uo
from .unified_net import UnifiedNet, UnifiedNetConfig, collate, load, save

BOSS_FLOOR = (17, 33, 48)
WIN, DEATH = 1, 2


def is_holdout(seed: int) -> bool:
    return (int(seed) * 2654435761 % 2**32) % 5 == 0


def _offsets(lengths: np.ndarray) -> np.ndarray:
    return np.concatenate([[0], np.cumsum(lengths)])


def file_samples(path: str, sample: float, rng: np.random.Generator, holdout: bool):
    """(UObs, labels[3], label mask[3], distance to boss) for the sampled decisions of one file."""
    with np.load(path) as zf:
        z = {k: zf[k] for k in zf.files if k not in ("forks_json", "meta")}
    off = {k: _offsets(z[k + "_len"]) for k in ("kind", "num", "edges", "cand_type", "cand_index", "cand_target",
                                                  "cand_target2", "cand_num")}
    eoff = _offsets(z["ep_length"])
    g_rows = z["num"][off["num"][:-1]]                         # first entity = GLOBAL
    act = np.argmax(g_rows[:, uo.G_ACT0:uo.G_ACT0 + 3], 1)
    floor = np.rint(g_rows[:, uo.G_FLOOR] * 49).astype(int)
    out = []
    for e in range(len(z["ep_length"])):
        oc = int(z["ep_outcome"][e])
        if oc not in (WIN, DEATH) or is_holdout(z["ep_seed"][e]) != holdout:
            continue
        s, t = eoff[e], eoff[e + 1]
        max_act = int(act[s:t].max())
        passed = [max_act > k or (k == 2 and oc == WIN) for k in range(3)]
        for i in range(s, t):
            if rng.random() >= sample:
                continue
            k = int(act[i])
            lab = np.zeros(3, np.float32); msk = np.zeros(3, np.float32)
            lab[0], msk[0] = passed[k], 1.0
            if k + 1 <= 2 and passed[k]:
                lab[1], msk[1] = passed[k + 1], 1.0
                if k + 2 <= 2 and passed[k + 1]:
                    lab[2], msk[2] = passed[k + 2], 1.0
            sl = lambda key: z[key][off[key][i]:off[key][i + 1]]
            m = {"kind": sl("kind"), "id": z["id"][off["kind"][i]:off["kind"][i + 1]], "num": sl("num"),
                 "edges": sl("edges"), "cand_type": sl("cand_type"), "cand_index": sl("cand_index"),
                 "cand_target": sl("cand_target"), "cand_target2": sl("cand_target2"), "cand_num": sl("cand_num")}
            out.append((uo.macro_obs(m), lab, msk, BOSS_FLOOR[k] - int(floor[i]), int(z["ep_seed"][e])))
    return out


def archive_files(root: str, runs: str) -> list[str]:
    """Archive files of the named runs: ``<root>/runs/training-review/<run>/archive`` (this
    Mac) or ``<root>/runs/<run>/archive`` (the training machine), or a directory path."""
    out = []
    for r in (x for x in runs.split(",") if x):
        for d in (f"{root}/runs/training-review/{r}/archive", f"{root}/runs/{r}/archive", f"{r}/archive", r):
            fs = glob.glob(f"{d}/rollout_*.npz")
            if fs:
                out += fs
                break
        else:
            raise SystemExit(f"no archive files for run {r!r} (looked in runs/training-review/{r}, runs/{r}, {r})")
    return sorted(out)


def q_loss(net: UnifiedNet, b, lab: torch.Tensor, msk: torch.Tensor):
    q_logit = net(b)["q_logit"]
    l = F.binary_cross_entropy_with_logits(q_logit, lab, weight=msk, reduction="sum")
    return l / msk.sum().clamp(min=1.0)


def _identity(x):
    return x


class ArchiveBatches(torch.utils.data.IterableDataset):
    """Batches of (UBatch, labels, mask[, HP+10% batch, HP-10% batch, distance, act]) from
    archive files, decoded in DataLoader workers. Files are visited in a seeded order (per
    ``epoch``), ``files_per_chunk`` at a time, shuffled within the chunk; worker w takes
    every n-th file of the order. ``repeat``: start over forever (new order each pass)."""

    def __init__(self, files, sample, batch, holdout, seed=0, files_per_chunk=6, repeat=False, hp_variants=False):
        super().__init__()
        self.files, self.sample, self.batch, self.holdout = list(files), sample, batch, holdout
        self.seed, self.files_per_chunk, self.repeat, self.hp_variants = seed, files_per_chunk, repeat, hp_variants
        self.epoch = 0

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        wid, nw = (info.id, info.num_workers) if info is not None else (0, 1)
        ep = self.epoch
        while True:
            order = np.random.default_rng([self.seed, ep]).permutation(len(self.files))[wid::nw]
            rng = np.random.default_rng([self.seed, ep, wid, 1])
            for c0 in range(0, len(order), self.files_per_chunk):
                smp = [s for fi in order[c0:c0 + self.files_per_chunk]
                       for s in file_samples(self.files[fi], self.sample, rng, self.holdout)]
                perm = rng.permutation(len(smp)) if not self.hp_variants else np.arange(len(smp))
                for i in range(0, len(perm), self.batch):
                    part = [smp[j] for j in perm[i:i + self.batch]]
                    obs = [s[0] for s in part]
                    item = [collate(obs), torch.from_numpy(np.stack([s[1] for s in part])),
                            torch.from_numpy(np.stack([s[2] for s in part]))]
                    if self.hp_variants:
                        item += [collate([with_hp(o, 0.1) for o in obs]), collate([with_hp(o, -0.1) for o in obs]),
                                 np.array([s[3] for s in part]), np.array([o.act for o in obs])]
                    yield item
            if not self.repeat:
                return
            ep += 1


def loader(ds: ArchiveBatches, workers: int):
    kw = dict(batch_size=None, collate_fn=_identity, num_workers=workers)
    if workers:
        kw.update(prefetch_factor=4, persistent_workers=False)
    return torch.utils.data.DataLoader(ds, **kw)


def default_workers() -> int:
    return 0 if os.uname().sysname == "Darwin" else max(1, min(8, (os.cpu_count() or 2) - 2))


def with_hp(o: uo.UObs, delta: float) -> uo.UObs:
    """Same decision with the HP fraction shifted by delta (GLOBAL entity and direct row)."""
    g = o.global_row.copy()
    frac = float(np.clip(g[uo.G_HPFRAC] + delta, 0.01, 1.0))
    g[uo.G_HPFRAC], g[uo.G_HP] = frac, frac * g[uo.G_MAXHP]
    num = o.num.copy()
    gi = int(np.where(o.kind == uo.K_GLOBAL)[0][0])
    num[gi, :uo.MACRO_NUM] = g
    return uo.UObs(o.kind, o.id, num, o.edges, g, o.player_row, o.cand_type, o.cand_index, o.cand_t1, o.cand_t2,
                   o.cand_num, o.in_combat, o.n_ctx)


def auc(p: np.ndarray, t: np.ndarray) -> float:
    t = t.astype(bool)
    if t.all() or (~t).all():
        return float("nan")
    _, inv, cnt = np.unique(p, return_inverse=True, return_counts=True)
    r = (np.concatenate([[0], np.cumsum(cnt)[:-1]]) + (cnt + 1) / 2.0)[inv]
    n1 = t.sum(); n0 = len(t) - n1
    return float((r[t].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


@torch.no_grad()
def evaluate(net: UnifiedNet, files: list[str], sample: float, seed: int = 123, workers: int = 0, batch: int = 256) -> dict:
    net.eval()
    dev = next(net.parameters()).device
    P, U, D, L, A, Dist = [], [], [], [], [], []
    ds = ArchiveBatches(files, sample, batch, holdout=True, seed=seed, hp_variants=True)
    for b, lab, _, bu, bd, dist, act in loader(ds, workers):
        p = torch.sigmoid(net(b.to(dev))["q_logit"][:, 0]).cpu().numpy()
        pu = torch.sigmoid(net(bu.to(dev))["q_logit"][:, 0]).cpu().numpy()
        pd = torch.sigmoid(net(bd.to(dev))["q_logit"][:, 0]).cpu().numpy()
        P.append(p); U.append(pu - p); D.append(pd - p)
        L.append(lab[:, 0].numpy()); A.append(act); Dist.append(dist)
    net.train()
    P, U, D, L, A, Dist = map(np.concatenate, (P, U, D, L, A, Dist))
    rows = []
    for a in range(3):
        for name, lo, hi in (("d=1", 1, 1), ("d=2-4", 2, 4), ("d=5-8", 5, 8), ("d=9-16", 9, 16), ("after boss", -99, 0)):
            sel = (A == a) & (Dist >= lo) & (Dist <= hi)
            if sel.sum() < 50:
                continue
            rows.append({"act": a + 1, "bin": name, "n": int(sel.sum()), "pass": float(L[sel].mean()),
                         "auc": auc(P[sel], L[sel]), "brier": float(np.mean((P[sel] - L[sel]) ** 2)),
                         "hp_up": float(U[sel].mean()), "hp_down": float(D[sel].mean())})
    return {"n": int(len(P)), "rows": rows}


def print_rows(ev: dict) -> None:
    for r in ev["rows"]:
        print(f"  act {r['act']} {r['bin']:10s} n {r['n']:6d} pass {r['pass']:.3f} AUC {r['auc']:.3f} "
              f"HP+10% {r['hp_up']:+.3f} HP-10% {r['hp_down']:+.3f}", flush=True)


def setup_device(name: str) -> torch.device:
    dev = torch.device(name)
    if dev.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    else:
        torch.set_num_threads(1)
    return dev


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True); ap.add_argument("--root", default="../.."); ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=2); ap.add_argument("--sample", type=float, default=0.3)
    ap.add_argument("--eval-sample", type=float, default=0.15); ap.add_argument("--files-per-chunk", type=int, default=6)
    ap.add_argument("--batch", type=int, default=128); ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--max-files", type=int); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--device", default="cpu"); ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--init", help="continue from this unified checkpoint (its architecture; --dim ignored)")
    ap.add_argument("--max-hours", type=float, help="stop (and save) after this long")
    ap.add_argument("--skip-eval0", action="store_true")
    args = ap.parse_args(argv)
    dev = setup_device(args.device)
    workers = default_workers() if args.workers is None else args.workers
    files = archive_files(args.root, args.runs)
    if args.max_files:
        files = files[::max(1, len(files) // args.max_files)][:args.max_files]
    print(f"files {len(files)} device {dev} workers {workers}", flush=True)
    torch.manual_seed(args.seed)
    net = load(args.init, dev) if args.init else UnifiedNet(UnifiedNetConfig(dim=args.dim)).to(dev)
    net.train()
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    t0 = time.time()
    deadline = t0 + 3600 * args.max_hours if args.max_hours else None
    log = {"args": vars(args), "evals": []}
    if not args.skip_eval0:
        ev = evaluate(net, files, args.eval_sample, workers=workers)
        log["evals"].append({"epoch": 0, **ev})
        print("epoch 0 holdout:", flush=True); print_rows(ev)
    step = 0
    ds = ArchiveBatches(files, args.sample, args.batch, holdout=False, seed=args.seed, files_per_chunk=args.files_per_chunk)
    stopped = False
    for ep in range(args.epochs):
        ds.epoch = ep
        losses = []
        for b, lab, msk in loader(ds, workers):
            loss = q_loss(net, b.to(dev, non_blocking=True), lab.to(dev), msk.to(dev))
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step(); step += 1
            losses.append(loss.item())
            if step % 200 == 0:
                print(f"  epoch {ep + 1} steps {step} loss {np.mean(losses[-200:]):.4f} [{time.time() - t0:.0f}s]", flush=True)
            if deadline and time.time() > deadline:
                stopped = True
                break
        ev = evaluate(net, files, args.eval_sample, workers=workers)
        log["evals"].append({"epoch": ep + 1, "steps": step, "stopped_early": stopped, **ev})
        save(args.out, net, {"pretrain": "q on archives", "epoch": ep + 1, "steps": step, "runs": args.runs,
                             "init": args.init or ""})
        print(f"epoch {ep + 1} holdout{' (stopped at --max-hours)' if stopped else ''}:", flush=True)
        print_rows(ev)
        json.dump(log, open(args.out + ".json", "w"), indent=1)
        if stopped:
            break
    print("saved", args.out)


if __name__ == "__main__":
    main()
