#!/usr/bin/env python3
"""Check whether published collector journals can train whole-run-act-v1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "model" / "spireformer"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Published .jsonl files or directories.")
    parser.add_argument(
        "--allow-policy", action="append", choices=("native-mcts", "first-legal"), default=[],
        help="Explicitly allow this recorded teacher source; unknown modes remain rejected.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Optional .json report path. Without this option the audit writes no files.",
    )
    args = parser.parse_args(argv)
    if args.output is not None and args.output.suffix != ".json":
        parser.error("--output must be a .json report, never a source .jsonl journal")

    from spireformer.act_readiness import audit_act_reward_data, format_readiness_summary

    try:
        report = audit_act_reward_data(args.inputs, allowed_policy_ids=args.allow_policy)
        if args.output is not None:
            sources = {Path(episode["source"]).resolve() for episode in report["episodes"]}
            if args.output.resolve() in sources:
                raise ValueError("--output must not overwrite a source journal")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(format_readiness_summary(report))
    if args.output is not None:
        print(f"Report: {args.output}")
    return 0 if report["training_ready_episode_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
