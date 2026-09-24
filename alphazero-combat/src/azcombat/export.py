"""ONNX candidate export with numerical and dynamic-shape parity checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

import numpy as np
import onnx
import onnxruntime as ort
import torch

from .samples import TrainingSample
from .training import (ACTION_DIM, ENTITY_DIM, GLOBAL_DIM, FEATURE_ABI, encode_actions,
                       encode_observation, load_checkpoint)


def export_onnx(checkpoint: Path, destination: Path, samples: Sequence[TrainingSample], tolerance: float = 1e-4) -> dict:
    """Refuse overwrite and validate multiple real decision shapes before use."""
    if destination.exists() or destination.with_suffix(".manifest.json").exists():
        raise FileExistsError("candidate ONNX/manifest already exists")
    if not samples:
        raise ValueError("at least one strictly validated parity sample is required")
    model, payload = load_checkpoint(checkpoint)
    for sample in samples:
        sample.validate()
    destination.parent.mkdir(parents=True, exist_ok=True)
    example_entities, example_global = encode_observation(samples[0])
    _, example_actions = encode_actions(samples[0])
    try:
        torch.onnx.export(model, (example_entities, example_global, example_actions), str(destination),
                          input_names=["entities", "globals", "actions"], output_names=["logits", "value"],
                          dynamic_axes={"entities": {0: "entity_count"}, "actions": {0: "action_count"},
                                        "logits": {0: "action_count"}}, opset_version=17, dynamo=False)
        onnx.checker.check_model(str(destination))
        session = ort.InferenceSession(str(destination), providers=["CPUExecutionProvider"])
        max_error = 0.0
        model.eval()
        for sample in samples:
            entities, globals_ = encode_observation(sample)
            _, actions = encode_actions(sample)
            with torch.no_grad():
                expected = model(entities, globals_, actions)
            actual = session.run(None, {"entities": entities.numpy(), "globals": globals_.numpy(),
                                        "actions": actions.numpy()})
            for predicted, reference in zip(actual, expected):
                error = float(np.max(np.abs(predicted - reference.numpy())))
                if not np.isfinite(error) or error > tolerance:
                    raise ValueError(f"ONNX numerical parity failed: error={error}, tolerance={tolerance}")
                max_error = max(max_error, error)
        manifest = {"format": "azcombat.onnx.v4", "featureAbi": FEATURE_ABI, "opset": 17,
                    "inputs": {"entities": ["N", ENTITY_DIM], "globals": [GLOBAL_DIM],
                               "actions": ["A", ACTION_DIM]},
                    "outputs": {"logits": ["A"], "value": []},
                    "checkpointSha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    "onnxSha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                    "paritySamples": len(samples), "maxAbsError": max_error,
                    "training": payload["metadata"]}
        destination.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    except Exception:
        destination.unlink(missing_ok=True)
        raise
