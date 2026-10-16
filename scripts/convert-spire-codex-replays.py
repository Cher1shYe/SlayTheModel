#!/usr/bin/env python3
"""Convert the curated Spire Codex archive to safe reconstructed JSONL."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY / "model" / "spireformer" / "spireformer" / "spire_codex.py"
SPEC = importlib.util.spec_from_file_location("spire_codex_converter", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
spire_codex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spire_codex
SPEC.loader.exec_module(spire_codex)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=REPOSITORY / "artifacts" / "reference" / "spire-codex" / "bulk",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY / "artifacts" / "reference" / "spire-codex" / "reconstructed-v1",
    )
    args = parser.parse_args()
    summary = spire_codex.convert_archive(args.archive, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
