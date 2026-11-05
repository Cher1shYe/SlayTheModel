"""Local entry point for training and throughput benchmarks.

    python -m deployment.train_local card
    python -m deployment.train_local selfplay
    python -m deployment.train_local armg
    python -m deployment.train_local combat-dagger
    python -m deployment.train_local benchmark
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["card", "selfplay", "armg", "combat-dagger", "benchmark"])
    args, rest = parser.parse_known_args(argv)
    if args.mode == "card":
        from agent.card_train import main as run
    elif args.mode == "selfplay":
        from agent.selfplay import main as run
    elif args.mode == "armg":
        from agent.armg_train import main as run
    elif args.mode == "combat-dagger":
        from agent.combat_dagger import main as run
    else:
        from deployment.benchmark_speed import main as run
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
