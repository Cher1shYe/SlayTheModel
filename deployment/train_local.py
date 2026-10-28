"""Local entry point: card model, combat self-play, or throughput benchmark.

    python -m deployment.train_local card
    python -m deployment.train_local selfplay
    python -m deployment.train_local benchmark
"""
from __future__ import annotations

import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["card", "selfplay", "benchmark"])
    args, rest = parser.parse_known_args(argv)
    if args.mode == "card":
        from agent.card_train import main as run
    elif args.mode == "selfplay":
        from agent.selfplay import main as run
    else:
        from deployment.benchmark_speed import main as run
    return run(rest)


if __name__ == "__main__":
    sys.exit(main())
