"""Small helper to emit seeded inputs using the existing repository generator."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("Setup", "Search", "Deploy"), default="Setup")
    parser.add_argument("--execute", action="store_true", help="Run the existing unattended launcher; default only emits inputs")
    args = parser.parse_args()
    if args.count < 1 or args.count > 1000:
        parser.error("count must be 1..1000")
    repo_root = Path(__file__).resolve().parents[3]
    generator = repo_root / "combat" / "tools" / "GeneratedCombatScenarios" / "run.py"
    if not generator.is_file():
        parser.error(f"existing generator not found: {generator}")
    command = [sys.executable, str(generator), "--count", str(args.count), "--seed", args.seed,
               "--mode", args.mode, "--output", str(args.output.resolve())]
    if not args.execute:
        command.append("--write-inputs-only")
    return subprocess.run(command, cwd=repo_root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
