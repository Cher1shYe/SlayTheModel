"""Audit unpromoted candidate self-play; never grant champion status."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .promotion import audit_bootstrap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("bootstrap audit report already exists")
    report = audit_bootstrap(args.wave, args.checkpoint)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "runs": len(report["auditedRuns"]),
                      "below100Runs": report["below100Runs"], "reasons": report["reasons"]}, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
