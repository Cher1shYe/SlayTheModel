"""Five-character multi-seed full-run smoke.

Not a win-rate claim and not a substitute for the per-item effect tests: this
only checks that complete runs for every character terminate without engine
exceptions or unexpected truncation.  Evidence level: local C++ port
(ruleset native-41cef1ea-port-v10), not a differential against the unavailable
target DLL 9cb4f1ad...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.common import sim  # noqa: E402
from agent.heuristics import combat_policy, run_policy  # noqa: E402
from agent.run_env import RunEnv, play_run  # noqa: E402

CHARACTERS = {
    "IRONCLAD": sim.CardPool.IRONCLAD,
    "SILENT": sim.CardPool.SILENT,
    "DEFECT": sim.CardPool.DEFECT,
    "REGENT": sim.CardPool.REGENT,
    "NECROBINDER": sim.CardPool.NECROBINDER,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--max-steps", type=int, default=20000)
    parser.add_argument("--start-seed", type=int, default=1)
    args = parser.parse_args()

    started = time.time()
    report = []
    errors = 0
    truncations = 0
    for name, character in CHARACTERS.items():
        for seed in range(args.start_seed, args.start_seed + args.seeds):
            env = RunEnv(seed, character=character)
            try:
                result = play_run(env, run_policy, combat_policy,
                                  max_steps=args.max_steps)
            except Exception as exc:  # noqa: BLE001 - smoke must record failures
                errors += 1
                report.append({"character": name, "seed": seed,
                               "status": "exception", "error": repr(exc)})
                continue
            result["character"] = name
            if result["status"] == "error":
                errors += 1
            if result["status"] == "truncated":
                truncations += 1
            report.append(result)
    elapsed = time.time() - started
    summary = {
        "ruleset_id": sim.ENGINE_RULESET_ID,
        "public_obs_version": int(sim.PUBLIC_OBS_VERSION),
        "action_schema_version": int(sim.ACTION_SCHEMA_VERSION),
        "runs": len(report),
        "errors": errors,
        "truncations": truncations,
        "seconds": round(elapsed, 1),
        "steps_per_second": round(sum(r.get("steps", 0) for r in report) / elapsed, 1)
        if elapsed else 0.0,
        "results": report,
    }
    print(json.dumps(summary, indent=2))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
