"""Fail-closed promotion assessment for the R4 engineering candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def assess_r4(index_path: Path, smoke_report_path: Path, onnx_manifest_path: Path) -> dict:
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    smoke = json.loads(Path(smoke_report_path).read_text(encoding="utf-8"))
    onnx = json.loads(Path(onnx_manifest_path).read_text(encoding="utf-8"))
    reasons: list[str] = []
    if index.get("status") != "admitted":
        reasons.append("R4 admission is not admitted")
    checkpoint = Path(smoke["checkpointPath"])
    onnx_path = Path(onnx_manifest_path).with_suffix(".onnx")
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest().lower() != smoke["checkpointSha256"].lower():
        reasons.append("checkpoint provenance changed")
    if onnx.get("checkpointSha256", "").lower() != smoke["checkpointSha256"].lower():
        reasons.append("ONNX was exported from a different checkpoint")
    if float(onnx.get("maxAbsError", 1.0)) > 1e-4:
        reasons.append("Python/ONNX parity exceeds tolerance")
    if smoke.get("metadata", {}).get("promotable") is not False:
        reasons.append("engineering checkpoint lacks explicit non-promotable marker")
    summary = index.get("summary", {})
    by_policy_outcome = summary.get("byPolicyOutcome", {})
    # The frozen R4 pilot is a training/coverage wave, never a promotion wave.
    if not index.get("plan", {}).get("seedUse", {}).get("sealedEvaluationLoaded", False):
        reasons.append("sealed evaluation seeds were not run")
    reasons.append("no complete paired Native evaluation wave with independent evaluation seeds")
    reasons.append("no natural nested-choice evaluation evidence")
    reasons.append("R4 pilot has one unresolved tree trajectory")
    return {"format": "azcombat.r4-promotion-assessment.v1", "approved": not reasons,
            "decision": "DENY", "reasons": reasons,
            "indexPath": str(Path(index_path).resolve()), "indexSha256": hashlib.sha256(Path(index_path).read_bytes()).hexdigest(),
            "smokeReportPath": str(Path(smoke_report_path).resolve()), "smokeReportSha256": hashlib.sha256(Path(smoke_report_path).read_bytes()).hexdigest(),
            "onnxManifestPath": str(Path(onnx_manifest_path).resolve()), "onnxManifestSha256": hashlib.sha256(Path(onnx_manifest_path).read_bytes()).hexdigest(),
            "checkpointSha256": smoke["checkpointSha256"], "onnxSha256": onnx.get("onnxSha256"),
            "parameterCount": smoke.get("metadata", {}).get("parameterCount"),
            "sealedEvaluationSeeds": smoke.get("metadata", {}).get("sealedEvaluationSeeds", []),
            "pilotSummary": {key: summary.get(key) for key in ("tasks", "samples", "ordinaryRows", "choiceRows", "byPolicy", "byOutcome")},
            "nextRequiredEvidence": ["paired Native evaluation on sealed HH seeds", "ordinary and nested-choice coverage", "settled death coverage", "candidate versus pure-MCTS paired reward/win audit"]}
