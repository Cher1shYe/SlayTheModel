"""Export and verify an isolated ONNX candidate from a warm-start checkpoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .export import export_onnx
from .training import CombatDataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--parity-jsonl", nargs="+", required=True, type=Path)
    args = parser.parse_args()
    manifest = export_onnx(args.checkpoint, args.onnx, CombatDataset(args.parity_jsonl).samples)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
