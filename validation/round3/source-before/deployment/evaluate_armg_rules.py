"""Paired 2x2 evaluation of ArmG deck-need and relic policy overlays.

All four arms use the same frozen model, seeds, battle controller and budget.
Validation seeds default to offset 100, past prior model-selection seeds 0..49.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import time
from dataclasses import asdict

import torch

from agent.armg import ArmGScorer
from agent.armg_train import collect_episode
from agent.armg_need import NeedConfig
from agent.policy import TEST_SEED_BASE, VAL_SEED_BASE
from deployment.evaluate_armg import _summary, load_armg_checkpoint

ARMS = {"baseline": (False, False), "need": (True, False),
        "relic": (False, True), "both": (True, True)}
_model = None


def _init_worker(checkpoint: str):
    global _model
    torch.set_num_threads(1)
    _model = ArmGScorer()
    load_armg_checkpoint(checkpoint, _model)
    _model.eval()


def _play(seed: int, arm: str, options: dict):
    need, relic = ARMS[arm]
    started = time.perf_counter()
    result = collect_episode(seed, _model, deterministic=True,
                             need_rules=need, relic_rules=relic, **options)
    result.pop("records", None)
    result["arm"] = arm
    result["elapsed_seconds"] = time.perf_counter() - started
    return result


def paired_summary(results: list[dict]) -> dict:
    by_arm = {arm: {r["seed"]: r for r in results if r["arm"] == arm} for arm in ARMS}
    summary = {}
    for arm in ARMS:
        values = list(by_arm[arm].values())
        data = _summary(values)
        data["need_decisions"] = sum(int(r.get("need_decisions", 0)) for r in values)
        data["relic_decisions"] = sum(int(r.get("relic_decisions", 0)) for r in values)
        summary[arm] = data
    baseline = by_arm["baseline"]
    paired = {}
    for arm in ("need", "relic", "both"):
        pairs = [(baseline[s], r) for s, r in by_arm[arm].items()
                 if s in baseline and baseline[s]["status"] == r["status"] == "terminated"]
        diff = [float(b["floor"] - a["floor"]) for a, b in pairs]
        mean = sum(diff) / len(diff) if diff else None
        se = (math.sqrt(sum((d - mean) ** 2 for d in diff) / (len(diff) * (len(diff) - 1)))
              if len(diff) > 1 else None)
        paired[arm] = {"complete_pairs": len(pairs), "mean_floor_difference": mean,
                       "floor_difference_se": se,
                       "only_overlay_wins": sum(b["won"] and not a["won"] for a, b in pairs),
                       "only_baseline_wins": sum(a["won"] and not b["won"] for a, b in pairs)}
    return {"arms": summary, "paired_vs_baseline": paired}


def run(checkpoint: Path, out_dir: Path, count: int, offset: int,
        simulations: int, workers: int, combat: str, max_steps: int, split: str = "val"):
    if min(count, simulations, workers, max_steps) < 1 or offset < 0:
        raise ValueError("invalid count, simulations, workers, max steps or offset")
    checkpoint = checkpoint.resolve(strict=True)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    model = ArmGScorer()
    payload = load_armg_checkpoint(checkpoint, model)
    del model
    out_dir.mkdir(parents=True, exist_ok=True)
    if split not in ("val", "test"):
        raise ValueError("split must be val or test")
    seed_base = VAL_SEED_BASE if split == "val" else TEST_SEED_BASE
    config = {"checkpoint": str(checkpoint), "sha256": digest,
              "checkpoint_progress": payload.get("progress"),
              "checkpoint_training_settings": payload.get("settings"),
              "seed_start": seed_base + offset, "count": count,
              "split": split, "combat": combat, "simulations": simulations,
              "information_mode": "oracle: future simulator state available" if combat == "mcts-oracle"
                                  else "hidden-state-resampled search" if combat in ("search", "mcts-resampled")
                                  else "greedy",
              "boss_multiplier": 3 if combat.startswith("mcts-") else 1,
              "path_cache": "winning 15 / losing 5" if combat == "mcts-oracle"
                            else "first action" if combat == "mcts-resampled" else "none",
              "epsilon": 0.05, "ascension": 0, "max_steps": max_steps, "workers": workers,
              "need_config": asdict(NeedConfig()),
              "rule_source_sha256": {name: hashlib.sha256(
                  (Path(__file__).resolve().parents[1] / "agent" / f"armg_{name}.py").read_bytes()
              ).hexdigest() for name in ("need", "relic")},
              "arms": {k: {"need_rules": n, "relic_rules": r} for k, (n, r) in ARMS.items()},
              "started_utc": datetime.now(timezone.utc).isoformat()}
    with (out_dir / "evaluation_config.json").open("x", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    options = {"combat": combat, "simulations": simulations, "epsilon": 0.05,
               "max_steps": max_steps, "ascension": 0}
    started = time.perf_counter()
    results = []
    results_path = out_dir / "episodes.jsonl"
    with results_path.open("x", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker, initargs=(str(checkpoint),)) as pool:
            pending = {pool.submit(_play, seed_base + offset + i, arm, options):
                       (seed_base + offset + i, arm)
                       for i in range(count) for arm in ARMS}
            for future in as_completed(pending):
                seed, arm = pending[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"seed": seed, "arm": arm, "status": "error", "won": False,
                              "floor": 0, "hp": 0, "error": f"{type(exc).__name__}: {exc}"}
                results.append(result)
                handle.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                if len(results) % 40 == 0 or len(results) == count * len(ARMS):
                    print(json.dumps({"progress": len(results), "total": count * len(ARMS)},
                                     ensure_ascii=False), flush=True)
    summary = {"config": config, **paired_summary(results),
               "elapsed_seconds": time.perf_counter() - started,
               "episodes_path": str(results_path.resolve())}
    with (out_dir / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--split", choices=("val", "test"), default="val")
    parser.add_argument("--start", type=int, default=100)
    parser.add_argument("--simulations", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--combat", choices=("mcts-oracle", "mcts-resampled", "search", "greedy"),
                        default="mcts-oracle")
    parser.add_argument("--max-steps", type=int, default=5000)
    args = parser.parse_args(argv)
    run(args.checkpoint, args.out_dir, args.seeds, args.start, args.simulations,
        args.workers, args.combat, args.max_steps, args.split)


if __name__ == "__main__":
    main()
