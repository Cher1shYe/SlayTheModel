"""Offline re-audit of preserved overkill failures; never launch a worker.

The original audit and frozen plan remain immutable. A continuation manifest
is a plan-only amendment, deliberately not an input to the old pilot runner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .experiments import sha256
from .natural_pilot import _source_snapshot
from .pilot_audit import _json, _relative, _require, audit_pilot


AUDITOR_VERSION = "azcombat.pilot-overkill-reaudit.v1"


def _preserved_inventory(manifest_path: Path, original_path: Path, original: dict) -> dict:
    root = manifest_path.parent
    inventory = {}
    for task in original["tasks"]:
        for attempt in task["attempts"]:
            for relative, identity in attempt["artifacts"].items():
                path = _relative(root, relative, label="original audit artifact")
                actual = {"sha256": sha256(path), "bytes": path.stat().st_size}
                _require(actual == identity, f"original evidence changed: {relative}")
                inventory[str(path)] = actual
    for path in (manifest_path, root / "manifest.sha256", original_path):
        inventory[str(path)] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    return inventory


def _assert_preserved(inventory: dict) -> None:
    for filename, identity in inventory.items():
        path = Path(filename)
        _require(path.stat().st_size == identity["bytes"] and sha256(path) == identity["sha256"],
                 f"evidence changed during re-audit: {path}")


def build_continuation(manifest: dict, report: dict, manifest_path: Path) -> dict:
    _require(not report["errors"] and report["failedAttempts"] == 0
             and report["attempts"] == report["completedCombats"] > 0,
             "continuation requires all existing attempts to pass full re-audit")
    accepted = [task for task in report["tasks"] if task["status"] == "complete"]
    remaining = [task for task in report["tasks"] if task["status"] == "planned"]
    _require(len(accepted) + len(remaining) == len(manifest["tasks"]),
             "continuation cannot omit rejected or unknown tasks")
    remaining_ids = {task["taskId"] for task in remaining}
    return {
        "format": "azcombat.natural-pilot-continuation-plan.v1",
        "status": "frozen-plan-only-not-executed",
        "executableByOriginalPilotRunner": False,
        "parentManifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "reauditVersion": AUDITOR_VERSION,
        "reason": "Remove false overkill<=unblocked audit constraint; preserve combat policy and reward.",
        "contracts": manifest["contracts"], "collectionRules": manifest["collectionRules"],
        "seedPartitions": manifest["seedPartitions"], "treeCandidate": manifest["treeCandidate"],
        "sourceSnapshotAtCollection": manifest["sourceSnapshot"],
        "sourceSnapshotAtReaudit": report["reaudit"]["currentSourceSnapshot"],
        "originalAudit": report["reaudit"]["originalAudit"],
        "originalStopErrors": report["reaudit"]["originalErrors"],
        "generatedScenarioBaseDirectory": str(manifest_path.parent),
        "tasks": [task for task in manifest["tasks"] if task["taskId"] in remaining_ids],
        "acceptedOriginalTasks": [{"taskId": task["taskId"],
                                   "attemptNumber": task["attempts"][0]["attemptNumber"],
                                   "outcome": task["attempts"][0]["outcome"],
                                   "artifacts": task["attempts"][0]["artifacts"]}
                                  for task in accepted],
        "executionRequirements": [
            "Explicit authorization and amendment-aware runner required; do not mutate parent manifest.",
            "Resolve scenario paths against generatedScenarioBaseDirectory and verify frozen hashes.",
            "Keep seed/deck/split/model/budgets/stop rules unchanged; never rerun accepted tasks.",
            "Freeze and verify execution source/build provenance before launch; no hidden source bypass.",
        ],
    }


def reaudit_pilot(manifest_path: Path, original_path: Path) -> tuple[dict, dict | None]:
    manifest_path = manifest_path.resolve(strict=True)
    original_path = original_path.resolve(strict=True)
    manifest, original = _json(manifest_path), _json(original_path)
    _require(original.get("format") == "azcombat.natural-pilot-audit.v1"
             and original.get("manifestSha256") == sha256(manifest_path),
             "original audit does not identify the frozen manifest")
    _require([task["taskId"] for task in original["tasks"]]
             == [task["taskId"] for task in manifest["tasks"]],
             "original audit task inventory differs from manifest")
    inventory = _preserved_inventory(manifest_path, original_path, original)
    repo = Path(__file__).resolve().parents[3]
    auditor_files = sorted((repo / "alphazero-combat/src/azcombat").glob("*.py"))
    auditor_hashes = {str(path.relative_to(repo)): sha256(path) for path in auditor_files}
    # Current audit code intentionally differs from the collection snapshot.
    # Native assemblies, frozen inputs and original artifact hashes are still
    # checked; this never changes the source guard of the execution runner.
    report = audit_pilot(manifest_path, verify_source=False, reaudit_overkill=True)
    _require(report["attempts"] == original["attempts"],
             "attempt inventory changed since original audit")
    for old, new in zip(original["tasks"], report["tasks"], strict=True):
        _require([a["attemptNumber"] for a in old["attempts"]]
                 == [a["attemptNumber"] for a in new["attempts"]],
                 f"attempt inventory changed for {old['taskId']}")
        for before, after in zip(old["attempts"], new["attempts"], strict=True):
            if "artifacts" in after:
                _require(before["artifacts"] == after["artifacts"],
                         f"artifact inventory changed for {old['taskId']}")
    _assert_preserved(inventory)
    _require(all(sha256(repo / name) == digest for name, digest in auditor_hashes.items()),
             "auditor source changed during re-audit")
    report["reaudit"] = {
        "version": AUDITOR_VERSION, "kind": "offline-only-no-new-execution",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "pythonExecutable": sys.executable, "auditorSourceSha256": auditor_hashes,
        "originalAudit": {"path": str(original_path), "sha256": sha256(original_path)},
        "originalStatus": original["status"], "originalErrors": original["errors"],
        "originalCompletedCombats": original["completedCombats"],
        "originalFailedAttempts": original["failedAttempts"],
        "originalManifestSourceSnapshot": manifest["sourceSnapshot"],
        "currentSourceSnapshot": _source_snapshot(repo),
        "collectionSourceUnchangedClaimed": False,
        "newWorkerRuns": 0, "newRetries": 0,
        "inputIntegrity": "original-hashes-match-before-and-after",
        "preservedArtifacts": inventory,
    }
    continuation = None
    if not report["errors"] and report["failedAttempts"] == 0:
        continuation = build_continuation(manifest, report, manifest_path)
    return report, continuation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--original-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    _require(not output.exists() and not output.is_relative_to(args.manifest.resolve().parent),
             "output must be a new directory outside the frozen pilot")
    report, continuation = reaudit_pilot(args.manifest, args.original_audit)
    output.mkdir(parents=True, exist_ok=False)
    audit_path = output / "audit.json"
    with audit_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if continuation is not None:
        continuation["reauditReport"] = {"path": str(audit_path), "sha256": sha256(audit_path)}
        plan_path = output / "continuation-manifest.json"
        with plan_path.open("x", encoding="utf-8") as handle:
            json.dump(continuation, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        with (output / "continuation-manifest.sha256").open("x", encoding="ascii") as handle:
            handle.write(sha256(plan_path) + "\n")
    print(json.dumps({"status": report["status"], "acceptedCombats": report["completedCombats"],
                      "errors": report["errors"], "report": str(audit_path),
                      "continuationTasks": len(continuation["tasks"]) if continuation else 0},
                     ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
