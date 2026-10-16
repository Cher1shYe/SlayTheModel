#!/usr/bin/env python3
"""Assemble safe Spire Codex decisions into SpireFormer shards."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "model" / "spireformer"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=REPOSITORY / "artifacts/reference/spire-codex/reconstructed-v1",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "artifacts/reference/spire-codex/tensor-bc-v3",
    )
    parser.add_argument(
        "--native-replays",
        type=Path,
        default=None,
        help="Optional directory of hash-bound native combat replay plans and reports",
    )
    parser.add_argument("--max-window-steps", type=int, default=64)
    parser.add_argument("--trajectories-per-shard", type=int, default=128)
    parser.add_argument("--max-vocabulary-size", type=int, default=512)
    args = parser.parse_args()

    if importlib.util.find_spec("torch") is None:
        parser.error(
            "PyTorch is required; install model/spireformer dependencies in "
            "a supported Python >=3.10 environment"
        )
    from spireformer.spire_codex_tensor import assemble_spire_codex_dataset

    report = assemble_spire_codex_dataset(
        args.input,
        args.output,
        max_window_steps=args.max_window_steps,
        trajectories_per_shard=args.trajectories_per_shard,
        max_vocabulary_size=args.max_vocabulary_size,
        native_replay_root=args.native_replays,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
