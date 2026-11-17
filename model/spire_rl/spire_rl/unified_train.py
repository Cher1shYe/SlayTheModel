"""Supervised training of the unified network on recorded combat data (teacher MCTS or
self-play; docs/claude-unified-net-design-20261116.md, steps 3-5).

Starts from a checkpoint (normally the value pretraining on the archives,
``unified_pretrain``, or the previous generation) and trains on ``unified_data`` parts:
* combat policy: imitate the search (default target 'mix' = half its chosen action, half
  its root visit distribution);
* q: per-act outcome labels (masked as in ``unified_data.q_labels``);
* combat auxiliary: death (logistic), HP left / max HP and potions used (squared error).
Out-of-combat states from the archives keep training q (``--macro-per-step`` per step,
``unified_pretrain.ArchiveBatches``), so the value head does not forget them.
Held out: games whose seed hash % 5 == 0 (same rule as the pretraining).

The parts are streamed (``--parts-per-chunk`` files at a time, shuffled within the chunk),
decoded and batched in DataLoader workers, so the data does not have to fit in memory.

Usage (from model/spire_rl):
  python -m spire_rl.unified_train --init <pretrained.pt> --data <part dir>[,<dir>] --out <net.pt>
      [--epochs 4] [--macro-runs small-b-d1,... --root ../..] [--device cuda] [--workers 6] [--max-hours H]
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch
import torch.nn.functional as F

from . import unified_data as ud
from .unified_net import UnifiedNet, UnifiedNetConfig, collate, load, save
from .unified_pretrain import (ArchiveBatches, _identity, archive_files, auc, default_workers, is_holdout, loader,
                               setup_device)


def batch_targets(samples: list) -> dict:
    """Collated batch + targets for a list of ``unified_data.Sample`` (CPU tensors)."""
    b = collate([s.obs for s in samples])
    c = b.ctype.shape[1]
    tgt = np.zeros((len(samples), c), np.float32)
    for i, s in enumerate(samples):
        tgt[i, :len(s.policy)] = s.policy
    return {"b": b, "policy": torch.from_numpy(tgt),
            "q": torch.from_numpy(np.stack([s.q for s in samples])),
            "q_mask": torch.from_numpy(np.stack([s.q_mask for s in samples])),
            "aux": torch.from_numpy(np.stack([s.aux for s in samples])),
            "kind": np.array([s.kind for s in samples]), "n_cand": np.array([len(s.policy) for s in samples])}


class PartBatches(torch.utils.data.IterableDataset):
    """Batches from part files: a seeded order of the files per ``epoch``,
    ``parts_per_chunk`` files at a time (worker w takes every n-th file), shuffled within
    the chunk; ``holdout`` selects the held-out games or the others."""

    def __init__(self, files, batch, holdout, target="mix", seed=0, parts_per_chunk=8, shuffle=True, limit=None):
        super().__init__()
        self.files, self.batch, self.holdout, self.target = list(files), batch, holdout, target
        self.seed, self.parts_per_chunk, self.shuffle, self.limit = seed, parts_per_chunk, shuffle, limit
        self.epoch = 0

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        wid, nw = (info.id, info.num_workers) if info is not None else (0, 1)
        order = (np.random.default_rng([self.seed, self.epoch]).permutation(len(self.files)) if self.shuffle
                 else np.arange(len(self.files)))[wid::nw]
        rng = np.random.default_rng([self.seed, self.epoch, wid, 2])
        given = 0
        for c0 in range(0, len(order), self.parts_per_chunk):
            smp = [s for fi in order[c0:c0 + self.parts_per_chunk] for s in ud.load_part(self.files[fi], self.target)
                   if is_holdout(s.game_seed) == self.holdout]
            perm = rng.permutation(len(smp)) if self.shuffle else np.arange(len(smp))
            for i in range(0, len(perm), self.batch):
                if self.limit is not None and given >= self.limit // nw:
                    return
                part = [smp[j] for j in perm[i:i + self.batch]]
                given += len(part)
                yield batch_targets(part)


def part_loader(ds, workers):
    kw = dict(batch_size=None, collate_fn=_identity, num_workers=workers)
    if workers:
        kw.update(prefetch_factor=4)
    return torch.utils.data.DataLoader(ds, **kw)


def losses(net: UnifiedNet, cb: dict | None, macro: tuple | None, dev, aux_coef: float = 0.5):
    parts, logs = [], {}
    if cb is not None:
        b = cb["b"].to(dev, non_blocking=True)
        out = net(b)
        tgt = cb["policy"].to(dev)
        pl = -(tgt * out["logp"].masked_fill(~b.cmask, 0.0)).sum(-1).mean()
        qm = cb["q_mask"].to(dev)
        ql = F.binary_cross_entropy_with_logits(out["q_logit"], cb["q"].to(dev), weight=qm, reduction="sum") / qm.sum().clamp(min=1)
        a = cb["aux"].to(dev)
        al = (F.binary_cross_entropy_with_logits(out["aux"][:, 0], a[:, 0]) + F.mse_loss(out["aux"][:, 1], a[:, 1])
              + 0.1 * F.mse_loss(out["aux"][:, 2], a[:, 2]))
        parts += [pl, ql, aux_coef * al]
        logs.update(policy=pl.item(), q_combat=ql.item(), aux=al.item())
    if macro is not None:
        mb, lab, msk = macro
        out = net(mb.to(dev, non_blocking=True))
        msk = msk.to(dev)
        ql = F.binary_cross_entropy_with_logits(out["q_logit"], lab.to(dev), weight=msk, reduction="sum") / msk.sum().clamp(min=1)
        parts.append(ql)
        logs["q_macro"] = ql.item()
    return sum(parts), logs


@torch.no_grad()
def evaluate(net: UnifiedNet, files: list[str], workers: int, limit: int = 30000, target: str = "mix") -> dict:
    net.eval()
    dev = next(net.parameters()).device
    hit, ce, n = 0, 0.0, 0
    P, L, K, D, Dp = [], [], [], [], []
    ds = PartBatches(files, 256, holdout=True, target=target, shuffle=False, limit=limit)
    for cb in part_loader(ds, workers):
        b = cb["b"].to(dev)
        out = net(b)
        lp = out["logp"].float().cpu()
        tgt = cb["policy"]
        for r in range(lp.shape[0]):
            c = int(cb["n_cand"][r])
            hit += int(int(lp[r, :c].argmax()) == int(tgt[r, :c].argmax()))
            ce += float(-(tgt[r, :c] * lp[r, :c]).sum())
        n += lp.shape[0]
        P.append(torch.sigmoid(out["q_logit"][:, 0]).cpu().numpy()); L.append(cb["q"][:, 0].numpy())
        K.append(cb["kind"]); D.append(cb["aux"][:, 0].numpy()); Dp.append(torch.sigmoid(out["aux"][:, 0]).cpu().numpy())
    net.train()
    if not n:
        return {"n": 0}
    P, L, K, D, Dp = map(np.concatenate, (P, L, K, D, Dp))
    return {"n": n, "policy_ce": ce / n, "top1_vs_teacher": hit / n,
            "q0_auc": {k: auc(P[K == j], L[K == j]) for j, k in enumerate(ud.KINDS) if (K == j).sum() > 50},
            "death_auc": {k: auc(Dp[K == j], D[K == j]) for j, k in enumerate(ud.KINDS) if (K == j).sum() > 50}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--init"); ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=4); ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4); ap.add_argument("--target", default="mix")
    ap.add_argument("--macro-runs", default=""); ap.add_argument("--root", default="../..")
    ap.add_argument("--macro-per-step", type=int, default=32); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--parts-per-chunk", type=int, default=8)
    ap.add_argument("--device", default="cpu"); ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--eval-limit", type=int, default=30000, help="held-out decisions per evaluation")
    ap.add_argument("--max-hours", type=float, help="stop (and save) after this long")
    args = ap.parse_args(argv)
    dev = setup_device(args.device)
    workers = default_workers() if args.workers is None else args.workers
    torch.manual_seed(args.seed)
    files = ud.part_files(args.data.split(","))
    if not files:
        raise SystemExit(f"no part_*.npz in {args.data}")
    print(f"parts {len(files)} device {dev} workers {workers}", flush=True)
    macro_files = archive_files(args.root, args.macro_runs) if args.macro_runs else []
    net = load(args.init, dev) if args.init else UnifiedNet(UnifiedNetConfig()).to(dev)
    net.train()
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=1e-4)
    log = {"args": vars(args), "evals": [{"epoch": 0, **evaluate(net, files, workers, args.eval_limit, args.target)}]}
    print("epoch 0", json.dumps(log["evals"][-1]), flush=True)
    macro_it = None
    if macro_files and args.macro_per_step:
        mds = ArchiveBatches(macro_files, 0.3, args.macro_per_step, holdout=False, seed=args.seed + 1, repeat=True)
        macro_it = iter(loader(mds, max(1, workers // 3) if workers else 0))
    t0 = time.time()
    deadline = t0 + 3600 * args.max_hours if args.max_hours else None
    ds = PartBatches(files, args.batch, holdout=False, target=args.target, seed=args.seed,
                     parts_per_chunk=args.parts_per_chunk)
    stopped, step = False, 0
    for ep in range(args.epochs):
        ds.epoch = ep
        tl = []
        for cb in part_loader(ds, workers):
            macro = next(macro_it)[:3] if macro_it is not None else None
            loss, parts = losses(net, cb, macro, dev)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step(); step += 1
            tl.append(parts)
            if step % 500 == 0:
                mean = {k: float(np.mean([p[k] for p in tl[-500:] if k in p])) for k in tl[-1]}
                print(f"  epoch {ep + 1} steps {step} [{time.time() - t0:.0f}s] {json.dumps(mean)}", flush=True)
            if deadline and time.time() > deadline:
                stopped = True
                break
        ev = evaluate(net, files, workers, args.eval_limit, args.target)
        log["evals"].append({"epoch": ep + 1, "steps": step, "stopped_early": stopped, **ev})
        mean = {k: float(np.mean([p[k] for p in tl if k in p])) for k in tl[-1]} if tl else {}
        print(f"epoch {ep + 1} [{time.time() - t0:.0f}s] train {json.dumps(mean)} | holdout {json.dumps(ev)}", flush=True)
        save(args.out, net, {"trained": "combat data", "epoch": ep + 1, "steps": step, "data": args.data,
                             "init": args.init or ""})
        json.dump(log, open(args.out + ".json", "w"), indent=1)
        if stopped:
            break
    print("saved", args.out)
    if stopped:
        raise SystemExit(3)                            # stopped by --max-hours: not a finished training


if __name__ == "__main__":
    main()
