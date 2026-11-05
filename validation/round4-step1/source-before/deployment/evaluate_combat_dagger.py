"""Compare a DAgger combat policy with greedy and native MCTS on paired runs.

Every arm uses the same frozen ArmG, seed and simulator build.  MCTS oracle
uses future RNG/deck information unavailable to the student; its results are
labelled separately and should not be interpreted as player-usable strength.
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
import shutil
import time

import torch

from agent.armg import ArmGScorer
from agent.combat_dagger import CombatPolicy, load_combat_checkpoint
from agent.combat_dagger_collect import collect_episode
from deployment.evaluate_armg import load_armg_checkpoint

SPLITS = {"val": 21_000_000, "test": 31_000_000}
ARMS = ("student", "greedy", "mcts-oracle", "mcts-resampled")
_policy = _armg = None


def _init_worker(policy_path: str, armg_path: str):
    global _policy, _armg
    torch.set_num_threads(1)
    _policy = CombatPolicy()
    load_combat_checkpoint(policy_path, _policy)
    _policy.eval()
    _armg = ArmGScorer()
    load_armg_checkpoint(armg_path, _armg)
    _armg.eval()


def _play(seed: int, arm: str, sims: int, max_steps: int):
    started = time.perf_counter()
    result = dict(collect_episode(seed, _policy, _armg, battle_mode=arm,
                                  teacher_sims=sims, collect_labels=False,
                                  max_steps=max_steps))
    # Never emit the large per-decision vectors, even if an alternate collector
    # happens to return them in no-label mode.
    result.pop("records", None)
    result["arm"] = arm
    result["elapsed_seconds"] = time.perf_counter() - started
    return result


def summarize(results):
    done = [r for r in results if r["status"] == "terminated"]
    n = len(done)
    def average(key):
        return sum(float(r.get(key, 0)) for r in done) / n if n else None
    battles = sum(int(r.get("battles", 0)) for r in done)
    battle_wins = sum(int(r.get("battle_wins", 0)) for r in done)
    battle_hp = sum(float(r.get("battle_hp_sum", 0)) for r in done)
    return {"episodes": len(results), "completed": n,
            "errors": sum(r["status"] == "error" for r in results),
            "truncated": sum(r["status"] == "truncated" for r in results),
            "wins": sum(bool(r.get("won")) for r in done),
            "win_rate_completed": average("won"),
            "mean_floor_completed": average("floor"),
            "mean_elapsed_seconds_completed": average("elapsed_seconds"),
            "battles": battles, "battle_wins": battle_wins,
            "battle_win_rate": battle_wins / battles if battles else None,
            "mean_battle_end_hp_fraction": battle_hp / battles if battles else None,
            "combat_decisions": sum(int(r.get("combat_decisions", 0)) for r in done),
            "cycle_recoveries": sum(int(r.get("cycle_recoveries", 0)) for r in results),
            "mcts_searches": sum(int(r.get("mcts_searches", 0)) for r in done),
            "mcts_simulations": sum(int(r.get("mcts_simulations", 0)) for r in done)}


def paired_summary(results, arms):
    """Report each arm plus complete-pair differences vs the pure student."""
    groups = {arm: {} for arm in arms}
    for result in results:
        arm, seed = result["arm"], int(result["seed"])
        if arm not in groups or seed in groups[arm]:
            raise ValueError("unexpected arm or duplicate evaluation seed")
        groups[arm][seed] = result
    summary = {arm: summarize(list(group.values())) for arm, group in groups.items()}
    base = groups["student"]
    comparisons = {}
    for arm in arms:
        if arm == "student":
            continue
        pairs = [(base[s], r) for s, r in groups[arm].items() if s in base
                 and base[s]["status"] == r["status"] == "terminated"]
        # positive means student reached a higher floor than this baseline
        diffs = [float(a["floor"] - b["floor"]) for a, b in pairs]
        mean = sum(diffs) / len(diffs) if diffs else None
        se = (math.sqrt(sum((d - mean)**2 for d in diffs) /
                        (len(diffs) * (len(diffs) - 1))) if len(diffs) > 1 else None)
        comparisons[arm] = {"complete_pairs": len(pairs),
                            "student_minus_baseline_floor": mean,
                            "floor_difference_se": se,
                            "student_only_wins": sum(bool(a.get("won")) and not bool(b.get("won")) for a, b in pairs),
                            "baseline_only_wins": sum(bool(b.get("won")) and not bool(a.get("won")) for a, b in pairs)}
    return {"arms": summary, "paired_student_vs": comparisons}


def run(policy_path: Path, armg_path: Path, out_dir: Path, *, split: str,
        start: int, count: int, workers: int, sims: int, max_steps: int,
        arms: tuple[str, ...] = ("student", "greedy", "mcts-oracle")):
    if split not in SPLITS or min(count, workers, sims, max_steps) < 1 or start < 0:
        raise ValueError("invalid split, count, worker count, search budget or step limit")
    if "student" not in arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        raise ValueError("arms must be unique, supported and include student")
    if start + count >= 10_000_000:
        raise ValueError("evaluation seed range exceeds split")
    policy_path, armg_path = policy_path.resolve(strict=True), armg_path.resolve(strict=True)
    out_dir.mkdir(parents=True, exist_ok=False)
    frozen_policy, frozen_armg = out_dir / "policy.pt", out_dir / "armg.pt"
    shutil.copyfile(policy_path, frozen_policy)
    shutil.copyfile(armg_path, frozen_armg)
    torch.set_num_threads(1)
    policy, armg = CombatPolicy(), ArmGScorer()
    policy_data = load_combat_checkpoint(frozen_policy, policy)
    armg_data = load_armg_checkpoint(frozen_armg, armg)
    del policy, armg
    config = {"policy_path": str(policy_path), "policy_snapshot": str(frozen_policy.resolve()),
              "policy_sha256": hashlib.sha256(frozen_policy.read_bytes()).hexdigest(),
              "policy_progress": policy_data.get("progress"),
              "policy_training_settings": policy_data.get("settings"),
              "armg_path": str(armg_path), "armg_snapshot": str(frozen_armg.resolve()),
              "armg_sha256": hashlib.sha256(frozen_armg.read_bytes()).hexdigest(),
              "armg_progress": armg_data.get("progress"),
              "seed_split": split, "seed_start": SPLITS[split] + start,
              "count": count, "arms": list(arms), "simulations": sims,
              "ascension": 0, "max_steps": max_steps, "workers": workers,
              "student_information": "public combat observation",
              "mcts_oracle_information": "full simulator state including hidden future RNG and cards",
              "mcts_oracle_path_cache": "winning 15 / losing 5; boss simulation budget x3",
              "mcts_resampled_path_cache": "one action; boss simulation budget x3",
              "armg_rules": "original ArmG; need and relic overlays disabled",
              "started_utc": datetime.now(timezone.utc).isoformat()}
    (out_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    results, started = [], time.perf_counter()
    episodes_path = out_dir / "episodes.jsonl"
    with episodes_path.open("x", encoding="utf-8") as handle:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker,
                                 initargs=(str(frozen_policy.resolve()), str(frozen_armg.resolve()))) as pool:
            futures = {pool.submit(_play, SPLITS[split] + start + i, arm, sims, max_steps):
                       (SPLITS[split] + start + i, arm) for i in range(count) for arm in arms}
            for future in as_completed(futures):
                seed, arm = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"seed": seed, "arm": arm, "status": "error", "won": False,
                              "floor": 0, "error": f"{type(exc).__name__}: {exc}"}
                results.append(result)
                handle.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                if len(results) % 30 == 0 or len(results) == len(futures):
                    print(json.dumps({"progress": len(results), "total": len(futures)}), flush=True)
    report = {"config": config, **paired_summary(results, arms),
              "elapsed_seconds": time.perf_counter() - started,
              "episodes_path": str(episodes_path.resolve())}
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy-checkpoint", required=True, type=Path)
    p.add_argument("--armg-checkpoint", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--split", choices=tuple(SPLITS), default="val")
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=512)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--arms", nargs="+", choices=ARMS,
                   default=("student", "greedy", "mcts-oracle"))
    a = p.parse_args(argv)
    run(a.policy_checkpoint, a.armg_checkpoint, a.out_dir, split=a.split,
        start=a.start, count=a.seeds, workers=a.workers, sims=a.simulations,
        max_steps=a.max_steps, arms=tuple(a.arms))


if __name__ == "__main__":
    main()
