"""Train a warm-start policy/value checkpoint from strict MCTS JSONL files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .training import CombatDataset, TrainConfig, train


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Strict sample JSONL paths")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hidden", type=int, default=128)
    args = parser.parse_args()
    config = TrainConfig(args.epochs, args.learning_rate, args.validation_fraction, args.seed, args.hidden)
    metadata = train(CombatDataset(args.inputs), args.checkpoint, config)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
