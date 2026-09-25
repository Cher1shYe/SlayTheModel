"""Freeze and run explicit protocol-repair replays, retaining previous attempts."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

from .experiments import sha256
from .natural_pilot import _source_snapshot, _assert_unchanged_inputs, _read_frozen_manifest, _launch_attempt, _attempt_records, _canonical_json
from .pilot_audit import audit_pilot, _json, _require
from .pilot_continue import _ref, _read_ref


def freeze(parent_path: Path, audit_path: Path, regression: Path, output: Path) -> Path:
    parent_path, audit_path = parent_path.resolve(strict=True), audit_path.resolve(strict=True)
    parent, audit = _read_frozen_manifest(parent_path), _json(audit_path)
    _require(audit["manifestSha256"] == sha256(parent_path), "parent audit identity mismatch")
    proof = _json(regression)
    _require(proof["status"] == "passed" and proof["terminalCleanup"]["nativeDamage"] == 6
             and proof["terminalCleanup"]["predictedDamage"] == 6, "terminal regression not passed")
    output = output.resolve()
    _require(not output.exists(), "repair batch output already exists")
    inherited = {}
    failures = deepcopy(audit.get("historicalFailedAttempts", []))
    for task in audit["tasks"]:
        if task["status"] == "complete":
            attempt = task["attempts"][0]
            inherited[task["taskId"]] = attempt.get("artifactBaseDirectory", str(parent_path.parent))
        elif task["attempts"]:
            directory = parent_path.parent / "attempts" / task["taskId"] / "attempt-001"
            files = {str(p): sha256(p) for p in directory.iterdir() if p.is_file()}
            launcher = directory / "trajectory.launcher.stderr.txt"
            disk_full = launcher.is_file() and "磁盘空间不足" in launcher.read_text(encoding="utf-8")
            classification = "infrastructure-disk-full-retry" if disk_full else "protocol-repair-replay"
            failures.append({"taskId": task["taskId"], "classification": classification,
                             "originalAttempt": _ref(directory / "attempt.json"), "files": files})
    effective = deepcopy(parent)
    effective.pop("continuation", None)
    effective["sourceSnapshot"] = _source_snapshot(Path(__file__).resolve().parents[3])
    _assert_unchanged_inputs(parent_path, effective)
    effective["repair"] = {"parentManifest": _ref(parent_path), "parentAudit": _ref(audit_path),
                           "regression": _ref(regression), "inheritedRoots": inherited,
                           "previousFailedAttempts": failures,
                           "damageCaptureSource": "native-damage-command-v1",
                           "policy": "same original tasks, no budget/model/deck changes; stop on first error"}
    output.mkdir(parents=True)
    (output / "inputs").mkdir()
    (output / "attempts").mkdir()
    for relative in {t["generatedScenario"] for t in parent["tasks"]}:
        shutil.copyfile(parent_path.parent / relative, output / relative)
    path = output / "manifest.json"
    with path.open("xb") as f: f.write(_canonical_json(effective))
    with path.with_suffix(".sha256").open("x") as f: f.write(sha256(path) + "\n")
    return path


def validate(path: Path) -> tuple[dict, dict[str, Path]]:
    manifest = _read_frozen_manifest(path)
    repair = manifest["repair"]
    _, parent = _read_ref(repair["parentManifest"])
    _, audit = _read_ref(repair["parentAudit"])
    _read_ref(repair["regression"])
    expected = deepcopy(parent)
    expected.pop("continuation", None)
    expected["sourceSnapshot"] = manifest["sourceSnapshot"]
    expected["repair"] = repair
    _require(expected == manifest, "repair changes original task conditions")
    _assert_unchanged_inputs(path, manifest)
    inherited = {key: Path(value) for key, value in repair["inheritedRoots"].items()}
    _require(set(inherited) == {t["taskId"] for t in audit["tasks"] if t["status"] == "complete"},
             "repair inherited task set differs")
    for task in audit["tasks"]:
        if task["taskId"] in inherited:
            base = inherited[task["taskId"]]
            for name, identity in task["attempts"][0]["artifacts"].items():
                _require(sha256(base / name) == identity["sha256"], "accepted original evidence changed")
    for failure in repair["previousFailedAttempts"]:
        _read_ref(failure["originalAttempt"])
        for name, digest in failure["files"].items():
            _require(sha256(Path(name)) == digest, "original failure evidence changed")
    return manifest, inherited


def run(path: Path) -> None:
    path = path.resolve(strict=True)
    manifest, inherited = validate(path)
    for task in manifest["tasks"]:
        if task["taskId"] in inherited: continue
        records = _attempt_records(path.parent / "attempts" / task["taskId"])
        if records:
            _require(len(records) == 1 and records[0]["status"] == "complete", "prior attempt failed; review required")
            continue
        validate(path)
        print(json.dumps({"event": "start", "taskId": task["taskId"]}), flush=True)
        try:
            result = _launch_attempt(path, manifest, task, 1)
        finally:
            report = audit_pilot(path, inherited_roots=inherited, reaudit_overkill=True)
            report["historicalFailedAttempts"] = manifest["repair"]["previousFailedAttempts"]
            report["allExecutionAttempts"] = report["attempts"] + len(report["historicalFailedAttempts"])
            report["executionRepairManifest"] = _ref(path)
            report_path = path.parent / f"audit-after-{task['taskId']}.json"
            with report_path.open("x", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        _require(not report["errors"], str(report["errors"]))
        print(json.dumps({"event": "complete", "taskId": task["taskId"],
                          "outcome": result["outcome"], "samples": result["samples"],
                          "accepted": report["completedCombats"]}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    for name in ("parent", "audit", "regression", "output"): p.add_argument("--" + name, type=Path, required=True)
    p = sub.add_parser("run")
    p.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze": print(freeze(args.parent, args.audit, args.regression, args.output))
    else: run(args.manifest)


if __name__ == "__main__": main()
