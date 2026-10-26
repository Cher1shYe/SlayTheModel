#!/usr/bin/env python3
"""Plot Arm G train/eval curves from the committed metric tracks.

Run: python eval/plot_armG.py <tag> [out_png]
"""
import sys, json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
tag = sys.argv[1] if len(sys.argv) > 1 else "G128x128"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / f"results/figures/armG_{tag}.png"
track = ROOT / f"results/metrics/armG_track_{tag}.jsonl"

g, tr, ev = [], [], []
for line in track.open():
    e = json.loads(line); g.append(e["game"]); tr.append(e["train"]); ev.append(e["eval"])

plt.figure(figsize=(9, 5))
plt.axhline(35, color="#d9534f", ls="--", lw=1.5, label="card-only ceiling (35)")
plt.plot(g, tr, "-o", ms=3, color="#2e8b57", label="train (random seeds)")
plt.plot(g, ev, "-o", ms=3, color="#9b59b6", label="eval (50 held-out seeds, greedy)")
plt.xlabel("training games"); plt.ylabel("avg floor reached")
plt.title(f"Arm G ({tag}): one small net, all non-combat decisions")
plt.legend(); plt.grid(alpha=0.25); plt.tight_layout()
plt.savefig(out, dpi=130)
print("saved", out, "| last eval", ev[-1], "| peak eval", max(ev))
