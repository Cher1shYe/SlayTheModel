"""Multi-seed Ironclad whole-run smoke under the training content profile.

    python validation/rl-audit-20261105/smoke.py --seeds 200

Runs the non-combat heuristic with a greedy battle controller for A0 and A10,
records terminal status (errors/truncations must stay 0), floors and per-second
throughput. This checks engine health, not model strength.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent import content_profile  # noqa: E402
from agent.common import SCREEN, new_run  # noqa: E402
from agent.heuristics import run_policy  # noqa: E402


def sweep(seeds: int, ascension: int) -> dict:
    floors, wins, errors, truncated, steps_total = [], 0, 0, 0, 0
    started = time.monotonic()
    for seed in range(1, seeds + 1):
        rc = new_run(seed, ascension, content_profile=content_profile.PROFILE)
        steps = 0
        try:
            while rc.screen != SCREEN.RUN_OVER and steps < 5000 and not rc.truncated:
                steps += 1
                if rc.screen == SCREEN.COMBAT:
                    if not rc.step_combat(*rc.battle.greedy_action(0.05, seed + steps)):
                        raise RuntimeError("rejected combat action")
                    continue
                if not rc.step(*run_policy(rc)):
                    raise RuntimeError(f"rejected action on {rc.screen.name}")
            steps_total += steps
            if rc.truncated:
                truncated += 1
            else:
                floors.append(int(rc.floor))
                wins += bool(rc.won)
        except (RuntimeError, ValueError) as exc:
            errors += 1
            print(json.dumps({"seed": seed, "error": str(exc)}), flush=True)
    seconds = time.monotonic() - started
    return {"seeds": seeds, "ascension": ascension, "content_profile": content_profile.identity(),
            "completed": len(floors), "errors": errors, "truncated": truncated,
            "wins": wins, "win_rate": wins / len(floors) if floors else None,
            "mean_floor": sum(floors) / len(floors) if floors else None,
            "max_floor": max(floors) if floors else None,
            "steps": steps_total, "seconds": round(seconds, 2),
            "runs_per_second": round(seeds / seconds, 1) if seconds else None,
            "microseconds_per_step": round(1e6 * seconds / max(steps_total, 1), 2)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--out", default=str(pathlib.Path(__file__).with_name("smoke.json")))
    args = parser.parse_args()
    report = [sweep(args.seeds, 0), sweep(args.seeds, 10)]
    pathlib.Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
