"""Strict, read-only reporting for a small paired evaluation wave.

This module deliberately does not implement a promotion gate.  It audits every
manifest run and every JSONL line, preserving structural failures in the report
instead of dropping bad runs or repairing their counters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from .samples import read_jsonl


_ASSEMBLY = re.compile(
    r"^SLAY_WORKER_ASSEMBLY label=(NativeWorker|Search|CombatSolver) "
    r"path=(.+?) mvid=([A-Fa-f0-9-]{36}) sha256=([A-Fa-f0-9]{64})$",
    re.MULTILINE,
)
_EXPORT = re.compile(r"^SLAY_WORKER_EXPORT_OUT=(.+)$", re.MULTILINE)
_FALLBACK = re.compile(r"fallback(?: reason)?=(.+)$", re.IGNORECASE | re.MULTILINE)
_ILLEGAL = re.compile(r"illegal action|invalid action|illegal replay action", re.IGNORECASE)
_WORKER_FAILED = re.compile(r"^SLAY_WORKER_FAILED\b", re.MULTILINE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(base: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("manifest artifact name must be a nonempty string")
    target = (base / name).resolve()
    if not target.is_relative_to(base.resolve()) or not target.is_file():
        raise ValueError(f"missing or out-of-wave artifact: {name}")
    return target


def _int_field(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value <= 0) or (not positive and value < 0):
        raise ValueError(f"{label} must be a {'positive ' if positive else ''}integer")
    return value


def _finite_number(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _normal_path(value: str) -> str:
    # Logs contain the path selected by the native loader.  Resolve only local
    # paths for comparison while retaining the original string in the report.
    try:
        return str(Path(value).resolve()).casefold()
    except (OSError, ValueError):
        return value.casefold()


def _diagnostic_names(base: Path, jsonl_name: str) -> list[str]:
    names = []
    for suffix in (
        ".diagnostic.json",
        ".live-action-diagnostic.json",
        ".choice-observation-diagnostic.json",
        ".policy-observation-diagnostic.json",
        ".prediction-observation-diagnostic.json",
    ):
        candidate = base / (jsonl_name + suffix)
        if candidate.is_file():
            names.append(candidate.name)
    return names


def _empty_run(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "seed": entry.get("seed"),
        "encounter": entry.get("encounter"),
        "scenario": entry.get("scenario"),
        "startType": entry.get("startType"),
        "policy": entry.get("policy"),
        "jsonl": entry.get("jsonl"),
        "sampleCount": 0,
        "choiceSamples": 0,
        "outcomes": [],
        "trajectorySearchMode": None,
        "searchModes": [],
        "networkPriorCalls": 0,
        "networkValueCalls": 0,
        "networkFallbacks": 0,
        "fallbackReasons": [],
        "illegalActionLines": 0,
        "workerFailureLines": 0,
        "diagnosticFiles": [],
        "simulations": {"total": 0, "minimum": 0, "maximum": 0},
        "elapsedMilliseconds": {"minimum": 0, "maximum": 0},
        "assemblies": {},
        "exportPaths": [],
        "errors": [],
    }


def _audit_run(base: Path, entry: Mapping[str, Any], requested: Mapping[str, Any]) -> dict[str, Any]:
    summary = _empty_run(entry)
    errors = summary["errors"]
    if entry.get("exitCode") != 0:
        errors.append(f"NativeWorker exitCode is {entry.get('exitCode')!r}")
    jsonl_name = entry.get("jsonl")
    try:
        jsonl = _inside(base, jsonl_name)
        summary["diagnosticFiles"] = _diagnostic_names(base, jsonl_name)
        if summary["diagnosticFiles"]:
            errors.append("diagnostic files are present: " + ", ".join(summary["diagnosticFiles"]))
        raw_lines = jsonl.read_text(encoding="utf-8").splitlines()
        summary["rawLineCount"] = len(raw_lines)
        if not raw_lines:
            raise ValueError("JSONL is empty")
        if any(not line.strip() for line in raw_lines):
            raise ValueError("JSONL contains a blank line")
        raw = [json.loads(line) for line in raw_lines]
        # read_jsonl is the single strict schema reader.  The raw count is
        # retained even if validation rejects the file.
        samples = read_jsonl(jsonl)
        summary["sampleCount"] = len(samples)
        if _sha256(jsonl).casefold() != str(entry.get("sha256", "")).casefold():
            errors.append("JSONL SHA256 differs from manifest")
        if len(raw) != len(samples):
            errors.append("strict sample count differs from raw JSONL line count")
        provenance = raw[0].get("provenance") if raw else None
        if not isinstance(provenance, Mapping):
            errors.append("provenance is missing from the first sample")
            provenance = {}
        if any(line.get("provenance") != provenance for line in raw):
            errors.append("provenance differs across samples")
        summary["outcomes"] = sorted({line.get("outcome") for line in raw})
        summary["choiceSamples"] = sum(
            bool(sample.legal_actions and sample.legal_actions[0].kind == "NestedChoice")
            for sample in samples
        )
        metrics = provenance.get("decisionMetrics")
        if not isinstance(metrics, list) or len(metrics) != len(raw):
            errors.append("decisionMetrics does not align one-to-one with samples")
            metrics = []
        if metrics and any(line.get("stateKey") != metric.get("stateKey")
                           or line.get("simulations") != metric.get("simulations")
                           for line, metric in zip(raw, metrics, strict=True)):
            errors.append("sample stateKey/simulations differs from decisionMetrics")
        modes = {metric.get("searchMode") for metric in metrics}
        summary["searchModes"] = sorted(mode for mode in modes if isinstance(mode, str))
        summary["trajectorySearchMode"] = provenance.get("searchMode")
        if not metrics or any(not isinstance(metric.get("searchMode"), str) for metric in metrics):
            errors.append("per-decision actual searchMode is missing")
        aggregate_mode = (summary["searchModes"][0] if len(summary["searchModes"]) == 1
                          else "mixed-search-modes")
        if provenance.get("searchMode") != aggregate_mode:
            errors.append("trajectory searchMode differs from actual per-decision modes")
        summary["networkPriorCalls"] = sum(
            _int_field(metric.get("networkPriorCalls"), "networkPriorCalls")
            for metric in metrics
        )
        summary["networkValueCalls"] = sum(
            _int_field(metric.get("networkValueCalls"), "networkValueCalls")
            for metric in metrics
        )
        summary["networkFallbacks"] = sum(
            _int_field(metric.get("networkFallbacks"), "networkFallbacks")
            for metric in metrics
        )
        if provenance.get("modelScored") != summary["networkPriorCalls"]:
            errors.append("provenance modelScored differs from summed prior calls")
        if provenance.get("modelUsed") != summary["networkValueCalls"]:
            errors.append("provenance modelUsed differs from summed value calls")
        if type(provenance.get("modelFallbacks")) is int:
            if provenance["modelFallbacks"] != summary["networkFallbacks"]:
                errors.append("provenance modelFallbacks differs from per-node fallback total")
        elif provenance:
            errors.append("provenance modelFallbacks is missing or non-integer")
        reasons = []
        for metric in metrics:
            reason = metric.get("networkFallbackReason")
            if reason is not None:
                if not isinstance(reason, str) or not reason:
                    errors.append("per-decision networkFallbackReason is malformed")
                else:
                    reasons.append(reason)
            if metric.get("networkFallbacks") and reason is None:
                errors.append("fallback count has no per-decision reason")
            if metric.get("networkFallbacks") == 0 and reason is not None:
                errors.append("fallback reason exists without a per-decision fallback")
        worker_stdout = _inside(base, entry["workerStdout"])
        worker_stderr = _inside(base, entry["workerStderr"])
        if _sha256(worker_stdout).casefold() != str(entry.get("workerStdoutSha256", "")).casefold():
            errors.append("worker stdout SHA256 differs from manifest")
        worker_text = worker_stdout.read_text(encoding="utf-8")
        worker_text += "\n" + worker_stderr.read_text(encoding="utf-8")
        reasons.extend(match.group(1).strip() for match in _FALLBACK.finditer(worker_text))
        summary["fallbackReasons"] = list(dict.fromkeys(reasons))
        summary["illegalActionLines"] = sum(1 for line in worker_text.splitlines() if _ILLEGAL.search(line))
        summary["workerFailureLines"] = len(_WORKER_FAILED.findall(worker_text))
        if summary["illegalActionLines"]:
            errors.append("worker log contains illegal/invalid action diagnostics")
        if summary["workerFailureLines"]:
            errors.append("worker log contains SLAY_WORKER_FAILED")
        if summary["networkFallbacks"]:
            # A fallback is evidence, not a successful tree-guided decision.
            errors.append("network fallback occurred")
        elif summary["fallbackReasons"]:
            errors.append("fallback reason was logged without a fallback counter")

        simulations = []
        elapsed = []
        requested_max = requested.get("maxSimulations")
        requested_budget = requested.get("budgetMilliseconds")
        for metric in metrics:
            simulation = _int_field(metric.get("simulations"), "simulations", positive=True)
            elapsed_ms = _finite_number(metric.get("elapsedMilliseconds"), "elapsedMilliseconds")
            if requested_max is not None and simulation > requested_max:
                errors.append(f"simulations {simulation} exceeds requested max {requested_max}")
            if requested_budget is not None and elapsed_ms + 1e-6 < requested_budget:
                errors.append(f"elapsedMilliseconds {elapsed_ms:g} is below requested budget {requested_budget}")
            if metric.get("maxSimulations") != requested_max:
                errors.append("per-decision maxSimulations differs from request")
            if metric.get("budgetMilliseconds") != requested_budget:
                errors.append("per-decision budgetMilliseconds differs from request")
            simulations.append(simulation)
            elapsed.append(elapsed_ms)
        if simulations:
            summary["simulations"] = {
                "total": sum(simulations), "minimum": min(simulations), "maximum": max(simulations)
            }
            summary["elapsedMilliseconds"] = {"minimum": min(elapsed), "maximum": max(elapsed)}

        policy = entry.get("policy")
        expected_mode = requested.get("baselineSearchMode") if policy == "baseline" else requested.get("candidateSearchMode")
        if expected_mode is None:
            errors.append(f"no requested search mode for policy {policy!r}")
        elif any(metric.get("searchMode") != expected_mode for metric in metrics) or not metrics:
            errors.append(f"actual per-decision searchMode differs from requested {expected_mode!r}")
        if provenance.get("requestedSearchMode") != expected_mode:
            errors.append("native requestedSearchMode differs from wave request")
        if policy == "baseline" and (summary["networkPriorCalls"] or summary["networkValueCalls"]):
            errors.append("baseline used network prior/value calls")
        if policy == "baseline" and any(metric.get("networkFallbacks") != 0 for metric in metrics):
            errors.append("baseline recorded a network fallback")
        model_status = provenance.get("modelLoadStatus", "")
        if policy == "baseline" and model_status != "pure-mcts:no-model-configured":
            errors.append("baseline loaded or attempted a model")
        if policy in {"candidate", "champion"} and (
                not isinstance(model_status, str) or not model_status.startswith("model-ready")
                or str(requested.get("candidateSha256", "")).upper() not in model_status.upper()):
            errors.append("candidate loaded model does not match requested ONNX SHA256")
        if policy in {"candidate", "champion"} and provenance.get("searchMode") == "policy-value-tree-v1":
            if any(metric.get("networkPriorCalls", 0) <= 0 or metric.get("networkValueCalls", 0) <= 0
                   for metric in metrics) or not metrics:
                errors.append("tree candidate lacks prior/value calls on a real decision")
            if provenance.get("modelShadow") is not False:
                errors.append("tree candidate ran in shadow mode")
        if provenance.get("maxSimulations") != requested_max:
            errors.append("provenance maxSimulations differs from request")
        if provenance.get("budgetMilliseconds") != requested_budget:
            errors.append("provenance budgetMilliseconds differs from request")
        for field, expected in (("seed", entry.get("seed")), ("encounter", entry.get("encounter"))):
            if provenance.get(field) != expected:
                errors.append(f"provenance {field} differs from manifest")
        if any(line.get("outcome") != raw[0].get("outcome") or line.get("valueTarget") != raw[0].get("valueTarget") for line in raw):
            errors.append("outcome/valueTarget differs across trajectory")
        if any(sample.start_type != entry.get("startType") for sample in samples):
            errors.append("sample startType differs from manifest")

        matches = _ASSEMBLY.findall(worker_text)
        loaded = {
            label: {"path": path, "mvid": mvid, "sha256": digest.upper()}
            for label, path, mvid, digest in matches
        }
        summary["assemblies"] = loaded
        if len(matches) != 3 or set(loaded) != {"NativeWorker", "Search", "CombatSolver"}:
            errors.append("worker log is missing or repeating loaded assembly identities")
        sample_assemblies = provenance.get("assemblies", {})
        expected_fields = {"NativeWorker": "nativeWorker", "Search": "search", "CombatSolver": "combatSolver"}
        for label, field in expected_fields.items():
            actual = loaded.get(label)
            recorded = sample_assemblies.get(field) if isinstance(sample_assemblies, Mapping) else None
            if not isinstance(recorded, Mapping) or actual is None:
                continue
            if (_normal_path(str(recorded.get("path", ""))) != _normal_path(actual["path"])
                    or str(recorded.get("mvid", "")).casefold() != actual["mvid"].casefold()
                    or str(recorded.get("sha256", "")).upper() != actual["sha256"]):
                errors.append(f"sample provenance differs from loaded {label} assembly")
        exported = _EXPORT.findall(worker_text)
        summary["exportPaths"] = exported
        if len(exported) != 1 or _normal_path(exported[0]) != _normal_path(str(jsonl)):
            errors.append("worker export path differs from the manifest JSONL")
        if entry.get("searchMode") != provenance.get("searchMode"):
            errors.append("run entry searchMode differs from native provenance")
        if entry.get("maxSimulations") != provenance.get("maxSimulations"):
            errors.append("run entry maxSimulations differs from native provenance")
        if entry.get("budgetMilliseconds") != provenance.get("budgetMilliseconds"):
            errors.append("run entry budgetMilliseconds differs from native provenance")
    except Exception as error:  # Preserve the failure in this run; report all runs.
        errors.append(f"strict audit failed: {error}")
    summary["valid"] = not errors
    return summary


def audit_wave(path: Path, *, expected_runs: int | None = None) -> dict[str, Any]:
    """Read and summarize a wave without changing any artifact."""
    wave = path.resolve()
    manifest_path = wave / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"wave manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("format") != "azcombat.wave.v2":
        errors.append(f"unsupported wave format: {manifest.get('format')!r}")
    if manifest.get("status") != "complete":
        errors.append(f"wave is not complete: {manifest.get('status')!r}")
    requested = {
        "baselineSearchMode": manifest.get("baselineSearchMode"),
        "candidateSearchMode": manifest.get("candidateSearchMode"),
        "maxSimulations": manifest.get("maxSimulations"),
        "budgetMilliseconds": manifest.get("decisionBudgetMilliseconds", manifest.get("budgetMilliseconds")),
        "candidateSha256": manifest.get("candidateSha256"),
    }
    model_path = manifest.get("candidateOnnx")
    if not isinstance(model_path, str) or not Path(model_path).is_file():
        errors.append("candidate ONNX referenced by wave manifest is missing")
    elif _sha256(Path(model_path)).casefold() != str(requested["candidateSha256"]).casefold():
        errors.append("candidate ONNX SHA256 differs from wave manifest")
    if requested["baselineSearchMode"] != "pure-mcts":
        errors.append("baselineSearchMode is not pure-mcts")
    if requested["candidateSearchMode"] != "policy-value-tree-v1":
        errors.append("candidateSearchMode is not policy-value-tree-v1")
    try:
        _int_field(requested["maxSimulations"], "manifest maxSimulations", positive=True)
        _int_field(requested["budgetMilliseconds"], "manifest budgetMilliseconds", positive=True)
    except ValueError as error:
        errors.append(str(error))
    entries = manifest.get("runs")
    if not isinstance(entries, list):
        raise ValueError("manifest runs must be a list")
    if expected_runs is not None and len(entries) != expected_runs:
        errors.append(f"expected {expected_runs} runs, found {len(entries)}")
    seen: set[str] = set()
    runs = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            runs.append({"valid": False, "errors": ["run entry is not an object"]})
            errors.append("run entry is not an object")
            continue
        name = entry.get("jsonl")
        if name in seen:
            errors.append(f"duplicate run JSONL entry: {name}")
        seen.add(name)
        summary = _audit_run(wave, entry, requested)
        runs.append(summary)
        errors.extend(f"{name}: {error}" for error in summary["errors"])
    return {
        "format": "azcombat.wave-smoke-report.v1",
        "wave": str(wave),
        "waveFormat": manifest.get("format"),
        "requested": requested,
        "runCount": len(runs),
        "runs": runs,
        "errors": errors,
        "valid": not errors and len(runs) > 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", required=True, type=Path)
    parser.add_argument("--expected-runs", type=int)
    parser.add_argument("--report", type=Path, help="Optional new report path; existing files are never overwritten")
    args = parser.parse_args()
    report = audit_wave(args.wave, expected_runs=args.expected_runs)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report is not None:
        if args.report.exists():
            raise FileExistsError(f"report already exists: {args.report}")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
