"""Train from strict MCTS data, or continue a checkpoint from audited candidate self-play."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .training import CombatDataset, TrainConfig, train, load_checkpoint
from .promotion import audit_bootstrap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path, help="Strict MCTS sample JSONL paths")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--init-checkpoint", type=Path, help="Existing cold-start checkpoint; never overwritten")
    parser.add_argument("--bootstrap-wave", type=Path, help="Reaudit candidate-only wave and train from exactly its files")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hidden", type=int)
    args = parser.parse_args()
    if args.bootstrap_wave is not None:
        if args.inputs or args.init_checkpoint is None:
            parser.error("--bootstrap-wave requires --init-checkpoint and no positional JSONL inputs")
        audit = audit_bootstrap(args.bootstrap_wave, args.init_checkpoint)
        if not audit["valid"]:
            raise ValueError("bootstrap data rejected: " + "; ".join(audit["reasons"]))
        inputs = [Path(item["path"]) for item in audit["inputFiles"]]
    else:
        if not args.inputs:
            parser.error("provide MCTS JSONL inputs or --bootstrap-wave")
        audit = None
        inputs = args.inputs
    parent_hidden = load_checkpoint(args.init_checkpoint)[0].hidden if args.init_checkpoint is not None else 128
    config = TrainConfig(args.epochs, args.learning_rate, args.validation_fraction, args.seed,
                         args.hidden if args.hidden is not None else parent_hidden)
    metadata = train(CombatDataset(inputs), args.checkpoint, config,
                     init_checkpoint=args.init_checkpoint, bootstrap_audit=audit)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
