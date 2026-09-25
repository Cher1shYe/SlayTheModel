"""Verify recorded tree evaluator calls against the unchanged Python/ONNX model."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from .experiments import checked_model
from .samples import TrainingSample, _normalize_observation, read_jsonl
from .training import encode_actions, encode_observation, load_checkpoint


_FULL_MODEL_ARM = "model-prior_model-value"
_CHOICE_FIELDS = ("TriggerCardId", "Effect", "SourcePile", "MinCount",
                  "MaxCount", "Ordered", "CompletedSelections")


def _error(reference: np.ndarray, actual: np.ndarray, label: str, tolerance: float) -> float:
    if reference.shape != actual.shape or not np.isfinite(reference).all() \
            or not np.isfinite(actual).all():
        raise ValueError(f"{label} shape/finite mismatch")
    difference = float(np.max(np.abs(reference - actual)))
    if difference > tolerance:
        raise ValueError(f"{label} mismatch: {difference} > {tolerance}")
    return difference


def _sample_from_trace(row: dict, seed: str) -> TrainingSample:
    actions = row.get("legalActions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("tree evaluator has no legal action payload")
    nodes = []
    for action in actions:
        if not isinstance(action, dict) or not {"Key", "Kind", "CardId", "CardOccurrence",
                                                "TargetCombatId", "ChoiceKey", "SelectedCards"}.issubset(action):
            raise ValueError("tree evaluator legal action payload is incomplete")
        kind = "NestedChoice" if action["ChoiceKey"] is not None else action["Kind"]
        nodes.append({"kind": kind, "actionId": action["Key"], "payload": action,
                      "terminal": action["Kind"] == "EndTurn"})
    ids = [node["actionId"] for node in nodes]
    if ids != row.get("orderedActionIds"):
        raise ValueError("tree evaluator ordered legal action IDs differ from payload")
    return TrainingSample.from_dict({"schemaVersion": 1, "seed": seed,
                                     "startType": "full_combat", "observation": row["observation"],
                                     "legalActions": nodes, "visitPolicy": {ids[0]: 1},
                                     "valueTarget": 0, "outcome": "unresolved"})


def _check_root_context(report: dict, observation: dict) -> None:
    frame = report.get("choiceFrame")
    independent_base = report.get("liveBaseObservation")
    if independent_base is not None and _normalize_observation(independent_base) != \
            _normalize_observation(frame["Observation"] if frame else observation):
        raise ValueError("independent live base observation differs from tree root")
    exported = report.get("exportObservation")
    if exported is not None and _normalize_observation(exported) != \
            _normalize_observation(observation):
        raise ValueError("export observation differs from actual tree root")
    if frame is None:
        if _normalize_observation(observation)["choice"] is not None:
            raise ValueError("ordinary root has a false Choice context")
        return
    if not isinstance(frame, dict) or not all(field in frame for field in _CHOICE_FIELDS) \
            or not isinstance(frame.get("Candidates"), list) or not frame["Candidates"]:
        raise ValueError("choice frame lacks required context")
    expected = {field: frame[field] for field in _CHOICE_FIELDS}
    expected["Candidates"] = [
        {field: candidate[field] for field in
         ("CombatCardIndex", "ModelId", "UpgradeLevel")}
        for candidate in frame["Candidates"]]
    base = _normalize_observation(frame["Observation"])
    if base["choice"] is not None:
        raise ValueError("choice frame base observation already has Choice")
    expected_observation = dict(frame["Observation"])
    expected_observation["Choice" if "Choice" in expected_observation else "choice"] = expected
    expected_root = _normalize_observation(expected_observation)
    if _normalize_observation(observation) != expected_root:
        raise ValueError("tree root choice observation differs from current choice frame")
    live = report.get("liveChoiceEvidence")
    if not isinstance(live, dict) or live.get("MinCount") != frame["MinCount"] \
            or live.get("MaxCount") != frame["MaxCount"] \
            or live.get("Candidates") != expected["Candidates"] \
            or report.get("liveCompletedSelections") != frame["CompletedSelections"]:
        raise ValueError("independent live choice evidence differs from tree root")


def verify_frozen_root(checkpoint: Path, onnx: Path, report_path: Path,
                       tolerance: float = 1e-5,
                       export_jsonl: Path | None = None) -> dict:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    onnx_hash = checked_model(onnx)
    manifest = json.loads(onnx.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if manifest.get("checkpointSha256", "").lower() != checkpoint_hash:
        raise ValueError("checkpoint hash differs from ONNX manifest")
    model, _ = load_checkpoint(checkpoint)
    session = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("regressionOnly") is not True or report.get("searchOnly") is not True:
        raise ValueError("frozen tree parity requires regressionOnly/searchOnly artifact")
    rows = report.get("actualTreeEvaluatorInputs")
    if not isinstance(rows, list) or not rows or len(rows) > 160:
        raise ValueError("bounded actual tree evaluator trace is missing")
    full_model = [row for row in rows if row.get("arm") == _FULL_MODEL_ARM]
    if not full_model:
        raise ValueError("full-model actual tree evaluator trace is missing")
    first = full_model[0]
    if first.get("invocation") != 1 or first.get("stateKey") != report.get("stateKey") \
            or first.get("orderedActionIds") != report.get("legalActionIds") \
            or first.get("observation") != report.get("observation"):
        raise ValueError("first actual tree evaluator input differs from frozen root")
    _check_root_context(report, first["observation"])
    expanded = [row for row in rows if row.get("arm") == "expanded-choice-probe"]
    if report.get("rootKind") == "purity" and not any(
            row.get("stateKey") != report.get("stateKey") and
            isinstance(row.get("observation"), dict) and
            row["observation"].get("Choice", row["observation"].get("choice")) is not None
            for row in expanded):
        raise ValueError("newly expanded internal choice evaluator input is missing")
    if export_jsonl is not None:
        # The opt-in read is solely for a regression fixture. CombatDataset still
        # invokes the default reader and refuses these rows for training.
        validated = read_jsonl(export_jsonl, allow_regression=True)
        raw_rows = [json.loads(line) for line in export_jsonl.read_text(encoding="utf-8").splitlines()]
        matching = [(sample, raw) for sample, raw in zip(validated, raw_rows, strict=True)
                    if raw.get("stateKey") == report.get("stateKey")]
        if len(matching) != 1:
            raise ValueError("same-root independent export row is missing or duplicated")
        exported, raw_export = matching[0]
        if exported.observation != _normalize_observation(first["observation"]):
            raise ValueError("independent export observation differs from actual tree root")
        exported_ids, _ = encode_actions(exported)
        if exported_ids != first["orderedActionIds"] or [node.get("payload") for node in
                raw_export["legalActions"]] != first["legalActions"]:
            raise ValueError("independent export legal action payload/order differs from actual tree root")
    max_python_onnx = max_native_onnx = 0.0
    choice_nodes = 0
    seen = set()
    compared = [*full_model, *expanded]
    for row in compared:
        if row.get("actualTreeEvaluator") is not True or row.get("outsideSearch") is not None:
            raise ValueError("record is not an actual tree evaluator call")
        key = (row.get("arm"), row.get("invocation"))
        if key in seen or type(key[1]) is not int or key[1] < 1:
            raise ValueError("tree evaluator invocation is duplicated or invalid")
        seen.add(key)
        observation_json = row.get("observationJson")
        if not isinstance(observation_json, str) or json.loads(observation_json) != row.get("observation") \
                or hashlib.sha256(observation_json.encode("utf-8")).hexdigest() \
                != str(row.get("observationSha256", "")).lower():
            raise ValueError("tree evaluator observation hash/content differs")
        sample = _sample_from_trace(row, str(report.get("seed", "frozen-root")))
        ids, actions = encode_actions(sample)
        if ids != row["orderedActionIds"]:
            raise ValueError("Python/Native action order differs")
        entities, globals_ = encode_observation(sample)
        with torch.no_grad():
            python_logits, python_value = model(entities, globals_, actions)
        onnx_logits, onnx_value = session.run(None, {
            "entities": entities.numpy(), "globals": globals_.numpy(), "actions": actions.numpy(),
        })
        max_python_onnx = max(max_python_onnx,
                              _error(python_logits.numpy(), np.asarray(onnx_logits),
                                     "Python/ONNX logits", tolerance),
                              _error(python_value.numpy(), np.asarray(onnx_value),
                                     "Python/ONNX value", tolerance))
        max_native_onnx = max(max_native_onnx,
                              _error(np.asarray(onnx_logits), np.asarray(row["logits"]),
                                     "Native/ONNX logits", tolerance),
                              _error(np.asarray(onnx_value), np.asarray(row["value"]),
                                     "Native/ONNX value", tolerance))
        choice_nodes += sample.observation["choice"] is not None
    return {"treeNodes": len(compared), "fullModelNodes": len(full_model),
            "expandedChoiceNodes": len(expanded), "choiceNodes": choice_nodes,
            "onnxSha256": onnx_hash, "checkpointSha256": checkpoint_hash,
            "maxPythonOnnxError": max_python_onnx,
            "maxNativeOnnxError": max_native_onnx}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--export-jsonl", type=Path,
                        help="Optional same-root regression-only live/export row")
    parser.add_argument("--tolerance", type=float, default=1e-5)
    args = parser.parse_args()
    print(json.dumps(verify_frozen_root(args.checkpoint, args.onnx, args.report,
                                        args.tolerance, args.export_jsonl), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
