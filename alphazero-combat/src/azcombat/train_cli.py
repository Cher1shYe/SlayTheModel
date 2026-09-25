"""Train from strict MCTS data, or continue a checkpoint from audited candidate self-play."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .training import CombatDataset, TrainConfig, train, load_checkpoint
from .promotion import audit_bootstrap
from .research_report import audit_wave, summarize_teacher


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path, help="Strict MCTS sample JSONL paths")
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--init-checkpoint", type=Path, help="Existing cold-start checkpoint; never overwritten")
    parser.add_argument("--bootstrap-wave", type=Path, help="Reaudit candidate-only wave and train from exactly its files")
    parser.add_argument("--teacher-wave", type=Path,
                        help="Reaudit the frozen pure-MCTS teacher wave and use only terminal trajectories")
    parser.add_argument("--seed-split", type=Path, help="Frozen train/validation/evaluation seed manifest")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hidden", type=int)
    args = parser.parse_args()
    teacher_report = None
    if args.teacher_wave is not None:
        if args.inputs or args.bootstrap_wave is not None or args.init_checkpoint is not None \
                or args.seed_split is None:
            parser.error("--teacher-wave requires --seed-split and no positional inputs/bootstrap/parent checkpoint")
        manifest = args.teacher_wave / "manifest.json" if args.teacher_wave.is_dir() else args.teacher_wave
        teacher_report = audit_wave(manifest)
        teacher_report["summary"] = summarize_teacher(teacher_report)
        if not teacher_report["summary"]["readyForTraining"]:
            raise ValueError("teacher wave lacks the predeclared minimum audited terminal data")
        if teacher_report["splitSha256"].lower() != hashlib.sha256(
                args.seed_split.read_bytes()).hexdigest().lower():
            raise ValueError("teacher wave and requested frozen seed split differ")
        audit = None
        inputs = [Path(path) for path in teacher_report["summary"]["trainingInputs"]]
    elif args.bootstrap_wave is not None:
        if args.seed_split is not None:
            parser.error("--bootstrap-wave cannot use a research seed split")
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
                     init_checkpoint=args.init_checkpoint, bootstrap_audit=audit,
                     seed_split=args.seed_split, teacher_report=teacher_report)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
