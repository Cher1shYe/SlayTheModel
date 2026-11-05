"""Evaluate one frozen ArmG checkpoint with the same MCTS budget for every boss.

The training controller normally gives bosses a triple budget. This evaluation
uses the requested fixed number for every decision with multiple legal actions;
single-action states avoid unnecessary searches. It does not modify the
trainer. Results are appended after each finished episode.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import time

import torch

from agent.armg import ArmGScorer
import agent.armg_train as trainer
from agent.policy import TEST_SEED_BASE
from deployment.evaluate_armg import _summary, load_armg_checkpoint


_model = None
_original_plan = trainer._mcts_plan


def _fixed_budget_plan(battle, seed, combat, simulations, epsilon, is_boss):
    """Disable the boss multiplier and discard the plan after its first step."""
    plan, completed = _original_plan(battle, seed, combat, simulations, epsilon, False)
    return plan[:1], completed


def _init_worker(checkpoint: str):
    global _model
    torch.set_num_threads(1)
    _model = ArmGScorer()
    load_armg_checkpoint(checkpoint, _model)
    _model.eval()
    trainer._mcts_plan = _fixed_budget_plan


def _play(seed: int, simulations: int, max_steps: int):
    start = time.perf_counter()
    result = trainer.collect_episode(seed, _model, deterministic=True,
        combat="mcts-oracle", simulations=simulations, epsilon=0.05,
        max_steps=max_steps, ascension=0)
    result.pop("records", None)
    result["elapsed_seconds"] = time.perf_counter() - start
    return result


def run(checkpoint: Path, out_dir: Path, count: int, offset: int,
        simulations: int, workers: int, max_steps: int):
    if min(count, simulations, workers, max_steps) < 1 or offset < 0:
        raise ValueError("count, simulations, workers and max_steps must be positive; offset nonnegative")
    checkpoint = checkpoint.resolve(strict=True)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    # Check schema and collect provenance in the parent before starting workers.
    model = ArmGScorer()
    payload = load_armg_checkpoint(checkpoint, model)
    del model
    out_dir.mkdir(parents=True, exist_ok=True)
    config = {"checkpoint": str(checkpoint), "sha256": digest,
              "checkpoint_progress": payload.get("progress"),
              "checkpoint_training_settings": payload.get("settings"),
              "split": "test", "seed_start": TEST_SEED_BASE + offset,
              "count": count, "combat": "mcts-oracle",
              "information_mode": "oracle: full simulator state and future RNG",
              "simulations_per_search": simulations, "boss_multiplier": 1,
              "path_cache": "disabled: search each decision with multiple legal actions",
              "workers": workers, "max_steps": max_steps, "ascension": 0,
              "started_utc": datetime.now(timezone.utc).isoformat()}
    config_path = out_dir / "evaluation_config.json"
    results_path = out_dir / "episodes.jsonl"
    # Exclusive creation prevents accidental reuse or replacement of results.
    with config_path.open("x", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    start = time.perf_counter()
    results = []
    with results_path.open("x", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker, initargs=(str(checkpoint),)) as pool:
            pending = {pool.submit(_play, TEST_SEED_BASE + offset + i, simulations, max_steps):
                       TEST_SEED_BASE + offset + i for i in range(count)}
            for future in as_completed(pending):
                seed = pending[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"seed": seed, "status": "error", "won": False,
                              "floor": 0, "hp": 0, "error": f"{type(exc).__name__}: {exc}"}
                results.append(result)
                handle.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                if len(results) % 10 == 0 or len(results) == count:
                    print(json.dumps({"progress": len(results), "total": count,
                                      "summary": _summary(results)}, ensure_ascii=False), flush=True)
    summary = {"config": config, "summary": _summary(results),
               "elapsed_seconds": time.perf_counter() - start,
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
    parser.add_argument("--start", type=int, default=100)
    parser.add_argument("--simulations", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=5000)
    args = parser.parse_args(argv)
    run(args.checkpoint, args.out_dir, args.seeds, args.start,
        args.simulations, args.workers, args.max_steps)


if __name__ == "__main__":
    main()
