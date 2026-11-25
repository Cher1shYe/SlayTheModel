"""Fixed-seed evaluation (docs/plan.md 5): no search, one network call per decision.

    python -m spire_rl.evaluate --checkpoint runs/5090-1/ema.pt --games 1000

Default is max-probability play on 1,000 fixed seeds at A10; ``--sample`` samples from the policy
instead. Uses the same driver guards as training. On CPU results do not depend on the worker
count; with BF16 on a GPU, different batch padding could in principle flip an exact near-tie.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from . import net as N
from .rollout import Pool, unpack


def wilson(wins: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def summarize(results: list[dict]) -> dict:
    n = len(results)
    wins = sum(bool(r["won"]) for r in results)
    low, high = wilson(wins, n)
    deaths = Counter(str(r["encounter"]) for r in results if not r["won"] and r["encounter"] is not None)
    return {"games": n, "wins": wins, "win_rate": wins / max(1, n), "win_rate_95ci": [low, high],
            "floor_mean": float(np.mean([r["floor"] for r in results])) if n else 0.0,
            "reached_act2": sum(r["act"] >= 1 for r in results), "reached_act3": sum(r["act"] >= 2 for r in results),
            "reasons": dict(Counter(r["reason"] for r in results)),
            "errors": [r["error"] for r in results if "error" in r][:5],
            "deaths_by_encounter_id": dict(deaths.most_common())}


@torch.no_grad()
def play(net, device, seeds, workers, games, ascension, sample=False, infer_batch=512):
    amp = device.type == "cuda"
    pool = Pool(workers, games, 0, ascension, fixed_seeds=seeds)
    results = []
    try:
        steps = pool.reset()
        while True:
            results += [s.info for s in steps if s.info]
            live = [i for i, s in enumerate(steps) if s.obs is not None]
            if not live:
                break
            actions = [0] * len(steps)
            for k in range(0, len(live), infer_batch):
                idx = live[k:k + infer_batch]
                b = N.collate([unpack(steps[i].obs) for i in idx]).to(device)
                allowed = torch.zeros_like(b.cmask)
                for row, i in enumerate(idx):
                    allowed[row, :len(steps[i].allowed)] = torch.from_numpy(steps[i].allowed).to(device)
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=amp):
                    logits = net(b)["logp"].float()
                logits = logits.masked_fill(~allowed, float("-inf"))
                chosen = torch.distributions.Categorical(logits=logits).sample() if sample else logits.argmax(-1)
                for i, a in zip(idx, chosen.tolist()):
                    actions[i] = a
            steps = pool.act(actions)
    finally:
        pool.close()
    return sorted(results, key=lambda r: r["seed"])


def main(argv=None):
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--checkpoint", required=True, type=Path)
    a.add_argument("--games", type=int, default=1000)
    a.add_argument("--first-seed", type=int, default=1_000_000)
    a.add_argument("--ascension", type=int, default=10)
    a.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a.add_argument("--parallel", type=int, default=32, help="games at once per worker")
    a.add_argument("--infer-batch", type=int, default=512)
    a.add_argument("--sample", action="store_true", help="sample from the policy instead of max probability")
    a.add_argument("--out", type=Path, help="result JSON (default: next to the checkpoint)")
    a.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = a.parse_args(argv)
    device = torch.device(args.device)
    net = N.load(args.checkpoint, device)
    seeds = list(range(args.first_seed, args.first_seed + args.games))
    results = play(net, device, seeds, args.workers, args.parallel, args.ascension, args.sample, args.infer_batch)
    if sorted(r["seed"] for r in results) != seeds:
        raise SystemExit("evaluation did not finish every seed exactly once")
    mode = "sample" if args.sample else "max"
    summary = {"checkpoint": str(args.checkpoint), "mode": mode, "ascension": args.ascension,
               "first_seed": args.first_seed, **summarize(results)}
    out = args.out or args.checkpoint.with_name(f"eval-{args.checkpoint.stem}-{mode}-{args.games}.json")
    keep = ("seed", "won", "floor", "act", "reason", "encounter", "decisions")
    out.write_text(json.dumps({**summary, "per_seed": [{k: r[k] for k in keep} for r in results]}))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
