"""Select HP on fresh validation-only pilot seeds before freezing a new manifest."""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from sts2_env.az.config import EpisodeLimits, atomic_json
from sts2_env.az.evaluation import evaluate_parallel, summarize
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.rewards import V2
from sts2_env.az.scenarios import starter_scenario, save_manifest
from sts2_env.az.self_play import Collector, initialize_worker


def run(output, manifest, episodes=64):
    root = Path(output).resolve()
    if root.exists() and any(root.iterdir()) or Path(manifest).exists():
        raise ValueError("Use new output and manifest paths")
    initialize_worker()
    checkpoints = {}
    for seed in (42, 43):
        torch.manual_seed(seed)
        path = root / f"initial-{seed}.pt"
        save_checkpoint(path, PolicyValueNetwork("observable", V2), f"initial-{seed}", {}, {})
        checkpoints[seed] = path
    results = []
    with Collector(8) as collector:
        for hp in (10, 15, 20, 30, 40, 50, 60):
            recipes = [starter_scenario(30_000 + i, split="validation", hp=hp) for i in range(episodes)]
            summary = {}
            for label, policy, seed in (("random", "random", 42), ("rule", "rule", 42),
                                        ("initial-42", "network", 42), ("initial-43", "network", 43)):
                rows = evaluate_parallel(collector.pool, checkpoints[seed], recipes, 0, 123,
                                         EpisodeLimits(), root / "cache", policy, V2)
                summary[label] = summarize(rows)
            results.append(dict(initial_hp=hp, policies=summary))
            atomic_json(root / "report.json", dict(results=results, selected_hp=None))
            print(hp, {k: v["win_rate"] for k, v in summary.items()}, flush=True)
    eligible = [r for r in results if r["policies"]["rule"]["win_rate"] >= 0.75
                and 0.1 <= r["policies"]["random"]["win_rate"] <= 0.85]
    if not eligible:
        raise ValueError("Pilot has no suitable difficulty; retain diagnostics without freezing a manifest")
    chosen = min(eligible, key=lambda r: (abs(r["policies"]["random"]["win_rate"] - 0.5), r["initial_hp"]))
    hp = chosen["initial_hp"]
    recipes = [starter_scenario(start + i, split=split, hp=hp)
               for split, start, count in (("train", 40_000, 256), ("validation", 50_000, 256), ("test", 60_000, 150))
               for i in range(count)]
    save_manifest(manifest, recipes)
    atomic_json(root / "report.json", dict(results=results, selected_hp=hp, reward_version=V2,
                selection_rule="rule >= .75, .1 <= random <= .85; minimize abs(random-.5), then HP",
                pilot_seeds=[30_000, 30_000 + episodes - 1], manifest=str(Path(manifest).resolve()),
                test_evaluations=0))
    print(f"Frozen {manifest}: initial HP {hp}", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", default="output/az_hp_v2_difficulty")
    p.add_argument("--manifest", default="data/az/hp_v2_manifest.json")
    p.add_argument("--episodes", type=int, default=64)
    run(**vars(p.parse_args()))
