"""Compare two ArmG checkpoints on fresh, paired oracle-MCTS game seeds.

Set STS2_PRIOR_PYD to the isolated simulator extension before running. Both
arms use the same deterministic battle controller, true game seeds and
independent per-episode search seeds. Every non-forced battle decision runs
the full normal or Boss budget and executes exactly one action.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import time

import numpy as np
import torch

from deployment import evaluate_battle_root_prior as extension_loader
from deployment import train_armg_hidden_mcts as rl
from deployment.evaluate_armg import _summary, load_armg_checkpoint
from agent.armg import ArmGScorer

ARMS = ("baseline", "candidate")
# Kept separate from the small development smoke (41_050_000 onward).
SEED_BASE = 41_080_000


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paired_summary(records: list[dict], *, bootstrap: bool = False) -> dict:
    groups = {arm: {} for arm in ARMS}
    for record in records:
        arm, seed = record["arm"], int(record["seed"])
        if arm not in groups or seed in groups[arm]:
            raise ValueError("unexpected arm or duplicated seed")
        groups[arm][seed] = record
    seeds = sorted(set(groups["baseline"]) & set(groups["candidate"]))
    seeds = [s for s in seeds if groups["baseline"][s]["status"] == groups["candidate"][s]["status"] == "terminated"]
    differences = np.asarray([groups["candidate"][s]["floor"] - groups["baseline"][s]["floor"] for s in seeds], dtype=np.float64)
    mean = float(differences.mean()) if len(differences) else None
    se = float(differences.std(ddof=1) / math.sqrt(len(differences))) if len(differences) > 1 else None
    ci = None
    if bootstrap and len(differences) > 1:
        rng = np.random.default_rng(20261030)
        means = np.empty(20000)
        for start in range(0, len(means), 1000):
            size = min(1000, len(means) - start)
            means[start:start+size] = differences[rng.integers(0, len(differences), (size, len(differences)))].mean(axis=1)
        ci = [float(x) for x in np.quantile(means, [.025, .975])]
    return {"complete_pairs": len(seeds), "mean_floor_difference": mean,
            "floor_difference_se": se, "bootstrap_95_ci": ci,
            "candidate_only_wins": sum(bool(groups["candidate"][s].get("won")) and not bool(groups["baseline"][s].get("won")) for s in seeds),
            "baseline_only_wins": sum(bool(groups["baseline"][s].get("won")) and not bool(groups["candidate"][s].get("won")) for s in seeds)}


def run(baseline, candidate, out_dir, *, count=100, workers=8, simulations=2000,
        boss_simulations=10000, max_steps=5000, start=0, search_seed=20261030):
    if min(count, workers, simulations, boss_simulations, max_steps) < 1 or start < 0:
        raise ValueError("invalid evaluation settings")
    if not extension_loader._extension:
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated simulator extension")
    extension = Path(extension_loader._extension).resolve(strict=True)
    checkpoints = {"baseline": Path(baseline).resolve(strict=True),
                   "candidate": Path(candidate).resolve(strict=True)}
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    active = out / "active"
    active.mkdir()
    # Validate both schemas before launching; workers use immutable weight-only
    # snapshots, each associated with its own distinct cache version.
    model = ArmGScorer()
    paths, hashes, metadata = {}, {}, {}
    for arm in ARMS:
        data = load_armg_checkpoint(checkpoints[arm], model)
        hashes[arm] = _sha(checkpoints[arm])
        metadata[arm] = {"progress": data.get("progress"), "settings": data.get("settings")}
        paths[arm] = out / f"{arm}_weights.pt"
        torch.save(model.state_dict(), paths[arm])
    del model
    generator = torch.Generator().manual_seed(search_seed)
    sampling_seeds = torch.randint(0, 2**31 - 1, (count,), generator=generator).tolist()
    search_seeds = torch.randint(0, 2**31 - 1, (count,), generator=generator).tolist()
    config = {"checkpoints": {a: str(checkpoints[a]) for a in ARMS}, "sha256": hashes,
              "checkpoint_metadata": metadata, "simulator": str(extension), "simulator_sha256": _sha(extension),
              "seed_start": SEED_BASE + start, "count": count, "workers": workers,
              "simulations_per_decision": simulations, "boss_simulations_per_decision": boss_simulations,
              "combat_mode": "oracle", "path_cache": "none", "ascension": 0,
              "search_seed": search_seed, "independent_search_rng": True,
              "max_steps": max_steps, "started_utc": datetime.now(timezone.utc).isoformat()}
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    records, started = [], time.perf_counter()

    def save(state, error=None):
        activities = []
        for path in active.glob("worker-*.json"):
            try:
                activities.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        progress = {"state": state, "completed_jobs": len(records), "total_jobs": count * 2,
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": time.perf_counter() - started, "active_episodes": activities,
                    "arms": {a: _summary([r for r in records if r["arm"] == a]) for a in ARMS},
                    "paired": paired_summary(records)}
        if error:
            progress["error"] = error
        rl._atomic_json(out / "progress.json", progress)
        return progress

    save("running")
    try:
        with (out / "episodes.jsonl").open("x", encoding="utf-8") as output:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
                jobs = {}
                for i in range(count):
                    for version, arm in enumerate(ARMS):
                        task = (SEED_BASE + start + i, sampling_seeds[i], search_seeds[i], version,
                                str(paths[arm]), True, simulations, boss_simulations,
                                max_steps, str(active), "oracle")
                        jobs[pool.submit(rl._play, task)] = (SEED_BASE + start + i, arm)
                pending = set(jobs)
                while pending:
                    done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                    for future in done:
                        seed, arm = jobs[future]
                        try:
                            record = dict(future.result())
                            record.pop("records", None)
                            record["arm"] = arm
                        except Exception as exc:
                            record = {"seed": seed, "arm": arm, "status": "error", "won": False,
                                      "floor": 0, "hp": 0, "error": f"{type(exc).__name__}: {exc}"}
                        records.append(record)
                        output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                        output.flush()
                    save("running")
        paired = paired_summary(records, bootstrap=True)
        state = "completed" if paired["complete_pairs"] == count else "incomplete"
        report = {"state": state, "config": config,
                  "arms": {a: _summary([r for r in records if r["arm"] == a]) for a in ARMS},
                  "paired": paired, "episodes_path": str((out / "episodes.jsonl").resolve()),
                  "elapsed_seconds": time.perf_counter() - started}
        (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        save(state)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return report
    except BaseException as exc:
        save("failed", f"{type(exc).__name__}: {exc}")
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--count", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=2000)
    p.add_argument("--boss-simulations", type=int, default=10000)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--search-seed", type=int, default=20261030)
    args = vars(p.parse_args(argv))
    return run(**args)


if __name__ == "__main__":
    main()
