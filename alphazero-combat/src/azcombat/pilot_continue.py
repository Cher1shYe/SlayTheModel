"""Execute a source-frozen amendment without rerunning accepted original tasks."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

from .experiments import sha256
from .natural_pilot import (_assert_unchanged_inputs, _attempt_records, _canonical_json,
                            _launch_attempt, _read_frozen_manifest, _source_snapshot)
from .pilot_audit import _json, _require, audit_pilot
from .pilot_reaudit import _assert_preserved, build_continuation


def _ref(path: Path) -> dict:
    return {"path": str(path.resolve(strict=True)), "sha256": sha256(path)}


def _read_ref(reference: dict) -> tuple[Path, dict]:
    path = Path(reference["path"]).resolve(strict=True)
    _require(sha256(path) == reference["sha256"], f"frozen reference changed: {path}")
    return path, _json(path)


def _validate_plan(plan_path: Path) -> tuple[dict, Path, dict, dict]:
    plan_path = plan_path.resolve(strict=True)
    _require(plan_path.with_suffix(".sha256").read_text(encoding="ascii").strip()
             == sha256(plan_path), "continuation plan hash changed")
    plan = _json(plan_path)
    parent_path, parent = _read_ref(plan["parentManifest"])
    _read_frozen_manifest(parent_path)
    _, reaudit = _read_ref(plan["reauditReport"])
    _require(reaudit["manifestSha256"] == sha256(parent_path), "re-audit belongs to another pilot")
    expected = build_continuation(parent, reaudit, parent_path)
    expected["reauditReport"] = plan["reauditReport"]
    _require(plan == expected, "continuation changes frozen tasks, rules or accepted evidence")
    _assert_preserved(reaudit["reaudit"]["preservedArtifacts"])
    for task in plan["tasks"]:
        _require(not (parent_path.parent / "attempts" / task["taskId"]).exists(),
                 "remaining task already has an original attempt")
    return plan, parent_path, parent, reaudit


def freeze_continuation(plan_path: Path, output: Path) -> Path:
    plan, parent_path, parent, _ = _validate_plan(plan_path)
    output = output.resolve()
    _require(not output.exists() and not output.is_relative_to(parent_path.parent),
             "continuation requires a new directory outside original pilot")
    repo = Path(__file__).resolve().parents[3]
    effective = deepcopy(parent)
    effective["sourceSnapshot"] = _source_snapshot(repo)
    # Validate every original model, dependency, budget and scenario before any run.
    _assert_unchanged_inputs(parent_path, effective)
    effective["continuation"] = {
        "format": "azcombat.natural-pilot-execution-amendment.v1",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "plan": _ref(plan_path), "parentManifest": _ref(parent_path),
        "remainingTaskIds": [task["taskId"] for task in plan["tasks"]],
        "acceptedTaskIds": [task["taskId"] for task in plan["acceptedOriginalTasks"]],
        "sourceChangeReason": "Python overkill audit and amendment runner; launcher process cleanup only. No combat/search/model/budget changes.",
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "inputs").mkdir()
    (output / "attempts").mkdir()
    for relative in sorted({task["generatedScenario"] for task in parent["tasks"]}):
        source = (parent_path.parent / relative).resolve(strict=True)
        _require(source.is_relative_to(parent_path.parent / "inputs"), "scenario escapes inputs")
        shutil.copyfile(source, output / relative)
    path = output / "manifest.json"
    with path.open("xb") as handle:
        handle.write(_canonical_json(effective))
    with path.with_suffix(".sha256").open("x", encoding="ascii") as handle:
        handle.write(sha256(path) + "\n")
    return path


def _execution(path: Path) -> tuple[dict, dict[str, Path]]:
    manifest = _read_frozen_manifest(path)
    amendment = manifest["continuation"]
    _require(amendment["format"] == "azcombat.natural-pilot-execution-amendment.v1",
             "unknown execution amendment")
    plan_path, _ = _read_ref(amendment["plan"])
    plan, parent_path, parent, _ = _validate_plan(plan_path)
    _require(amendment["parentManifest"] == _ref(parent_path), "execution parent changed")
    _require(amendment["remainingTaskIds"] == [task["taskId"] for task in plan["tasks"]]
             and amendment["acceptedTaskIds"] == [task["taskId"] for task in plan["acceptedOriginalTasks"]],
             "execution task partition changed")
    expected = deepcopy(parent)
    expected["sourceSnapshot"] = manifest["sourceSnapshot"]
    expected["continuation"] = amendment
    _require(manifest == expected, "execution changes frozen collection conditions")
    _assert_unchanged_inputs(path, manifest)
    inherited = {task_id: parent_path.parent for task_id in amendment["acceptedTaskIds"]}
    for task_id in inherited:
        _require(not (path.parent / "attempts" / task_id).exists(), "accepted task was rerun")
    return manifest, inherited


def run_continuation(path: Path, *, limit: int | None = None) -> list[dict]:
    path = path.resolve(strict=True)
    _require(limit is None or type(limit) is int and limit > 0, "limit must be positive")
    manifest, inherited = _execution(path)
    # Audit any previously finished attempts before resuming; a failed attempt
    # never becomes an implicit retry, and paired roots remain checked.
    before = audit_pilot(path, reaudit_overkill=True, inherited_roots=inherited)
    _require(not before["errors"] and before["failedAttempts"] == 0,
             f"continuation has a prior failure: {before['errors']}")
    results = []
    for task in manifest["tasks"]:
        if task["taskId"] in inherited:
            continue
        records = _attempt_records(path.parent / "attempts" / task["taskId"])
        if records:
            _require(len(records) == 1 and records[0]["status"] == "complete",
                     "prior failed/running attempt requires explicit review")
            continue
        _execution(path)
        print(json.dumps({"event": "start", "taskId": task["taskId"]}), flush=True)
        try:
            result = _launch_attempt(path, manifest, task, 1)
        finally:
            # Failure records, partial outputs and unstarted tasks remain visible.
            report = audit_pilot(path, reaudit_overkill=True, inherited_roots=inherited)
            report["executionAmendment"] = manifest["continuation"]
            report_path = path.parent / f"audit-after-{task['taskId']}.json"
            with report_path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        _require(not report["errors"] and report["failedAttempts"] == 0,
                 f"post-attempt protocol failure: {report['errors']}")
        results.append(result)
        print(json.dumps({"event": "complete", "taskId": task["taskId"],
                          "outcome": result["outcome"], "samples": result["samples"],
                          "totalAccepted": report["completedCombats"]}), flush=True)
        if limit is not None and len(results) >= limit:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--plan", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "freeze":
        print(freeze_continuation(args.plan, args.output))
    else:
        print(json.dumps({"newAttempts": len(run_continuation(args.manifest, limit=args.limit))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
