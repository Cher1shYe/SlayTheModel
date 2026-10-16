#!/usr/bin/env python3
"""Build a train/val/test BC corpus from safe human and Spire Codex steps."""

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
        "--spire-codex",
        type=Path,
        default=REPOSITORY / "artifacts/reference/spire-codex/reconstructed-v1",
    )
    parser.add_argument(
        "--native-replays",
        type=Path,
        default=REPOSITORY / "artifacts/reference/spire-codex/native-replay-pilot",
    )
    parser.add_argument(
        "--human-input",
        type=Path,
        action="append",
        default=[REPOSITORY / "artifacts/human-dataset/episodes"],
    )
    parser.add_argument("--human-train-episode", action="append", required=True)
    parser.add_argument("--human-val-episode", action="append", required=True)
    parser.add_argument("--human-test-episode", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-window-steps", type=int, default=64)
    parser.add_argument("--trajectories-per-shard", type=int, default=128)
    parser.add_argument("--max-vocabulary-size", type=int, default=512)
    args = parser.parse_args()

    if importlib.util.find_spec("torch") is None:
        parser.error("PyTorch is required in the selected Python environment")
    from spireformer.mixed_bc import assemble_mixed_bc_dataset

    report = assemble_mixed_bc_dataset(
        args.spire_codex,
        args.human_input,
        args.output,
        human_train_episodes=args.human_train_episode,
        human_val_episodes=args.human_val_episode,
        human_test_episodes=args.human_test_episode,
        native_replay_root=args.native_replays,
        max_window_steps=args.max_window_steps,
        trajectories_per_shard=args.trajectories_per_shard,
        max_vocabulary_size=args.max_vocabulary_size,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
