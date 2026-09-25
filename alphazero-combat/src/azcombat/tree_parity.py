"""Strict Python/ONNX/Native numerical parity for opt-in tree-root captures."""
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
from .samples import read_jsonl
from .training import encode_actions, encode_observation, load_checkpoint


def _jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ValueError(f"empty or blank JSONL line: {path}")
    result = [json.loads(line) for line in lines]
    if any(not isinstance(item, dict) for item in result):
        raise ValueError(f"JSONL root must be an object: {path}")
    return result


def _max_error(expected: np.ndarray, actual: np.ndarray, label: str, tolerance: float) -> float:
    if expected.shape != actual.shape or not np.isfinite(expected).all() or not np.isfinite(actual).all():
        raise ValueError(f"{label} shape or finite-value mismatch")
    error = float(np.max(np.abs(expected - actual)))
    if error > tolerance:
        raise ValueError(f"{label} numerical mismatch: {error} > {tolerance}")
    return error


def verify(checkpoint: Path, onnx: Path, jsonl: Path, native_parity: Path,
           tolerance: float = 1e-5) -> dict:
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    onnx_hash = checked_model(onnx)
    manifest = json.loads(onnx.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    if manifest.get("checkpointSha256", "").lower() != checkpoint_hash:
        raise ValueError("checkpoint hash differs from ONNX manifest")
    model, _ = load_checkpoint(checkpoint)
    samples = read_jsonl(jsonl)
    raw_samples, native_rows = _jsonl(jsonl), _jsonl(native_parity)
    if len(samples) != len(raw_samples) or len(samples) != len(native_rows):
        raise ValueError("strict sample/native root parity count mismatch")
    session = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
    max_python_onnx = max_native_onnx = 0.0
    choices = 0
    seen_roots: set[tuple[str, int, int, str]] = set()
    required = {"seed", "decision", "choiceLayer", "stateKey", "observationJson",
                "observationSha256", "orderedActionIds", "logits", "value", "outsideSearch"}
    for index, (sample, raw, native) in enumerate(zip(samples, raw_samples, native_rows, strict=True)):
        if set(native) != required or native["outsideSearch"] is not True:
            raise ValueError(f"native parity row {index} has missing/extra fields or is not outside search")
        key = (native["seed"], native["decision"], native["choiceLayer"], native["stateKey"])
        if key in seen_roots:
            raise ValueError(f"duplicate parity root at row {index}")
        seen_roots.add(key)
        if native["seed"] != sample.seed or native["stateKey"] != raw.get("stateKey"):
            raise ValueError(f"seed/stateKey differs at row {index}")
        observation_json = native["observationJson"]
        if not isinstance(observation_json, str) or hashlib.sha256(observation_json.encode("utf-8")).hexdigest() \
                != native["observationSha256"].lower() or json.loads(observation_json) != raw["observation"]:
            raise ValueError(f"observation hash/content differs at row {index}")
        ids, actions = encode_actions(sample)
        if ids != native["orderedActionIds"]:
            raise ValueError(f"ordered legal actions differ at row {index}")
        provenance = raw.get("provenance", {})
        if onnx_hash.lower() not in provenance.get("modelLoadStatus", "").lower():
            raise ValueError(f"Native loaded model hash differs at row {index}")
        metrics = [item for item in provenance.get("decisionMetrics", [])
                   if item.get("stateKey") == native["stateKey"]
                   and item.get("parentDecision") == native["decision"]
                   and item.get("choiceLayer") == native["choiceLayer"]]
        if len(metrics) != 1 or metrics[0].get("searchMode") != "policy-value-tree-v1" \
                or metrics[0].get("networkPriorCalls", 0) < 1 \
                or metrics[0].get("networkValueCalls", 0) < 1 \
                or metrics[0].get("networkFallbacks") != 0:
            raise ValueError(f"tree guidance provenance differs at row {index}")
        entities, globals_, = encode_observation(sample)
        with torch.no_grad():
            torch_logits, torch_value = model(entities, globals_, actions)
        onnx_logits, onnx_value = session.run(None, {
            "entities": entities.numpy(), "globals": globals_.numpy(), "actions": actions.numpy(),
        })
        max_python_onnx = max(max_python_onnx,
                              _max_error(torch_logits.numpy(), np.asarray(onnx_logits),
                                         f"row {index} Python/ONNX logits", tolerance),
                              _max_error(torch_value.numpy(), np.asarray(onnx_value),
                                         f"row {index} Python/ONNX value", tolerance))
        max_native_onnx = max(max_native_onnx,
                              _max_error(np.asarray(onnx_logits), np.asarray(native["logits"]),
                                         f"row {index} Native/ONNX logits", tolerance),
                              _max_error(np.asarray(onnx_value), np.asarray(native["value"]),
                                         f"row {index} Native/ONNX value", tolerance))
        choices += sample.observation["choice"] is not None
    return {"roots": len(samples), "choiceRoots": choices, "onnxSha256": onnx_hash,
            "checkpointSha256": checkpoint_hash, "maxPythonOnnxError": max_python_onnx,
            "maxNativeOnnxError": max_native_onnx}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--jsonl", required=True, type=Path)
    parser.add_argument("--native-parity", required=True, type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-5)
    args = parser.parse_args()
    print(json.dumps(verify(args.checkpoint, args.onnx, args.jsonl, args.native_parity,
                            args.tolerance), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
