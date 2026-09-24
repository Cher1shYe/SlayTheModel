"""Check NativeWorker model-root logs against strict JSONL and Python tensors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import torch

from .samples import read_jsonl
from .training import encode_actions, encode_observation, load_checkpoint

_MODEL_RESULT = re.compile(
    r"SLAY_WORKER_ALPHAZERO decision=\d+(?: choice)? shadow=(?:True|False) "
    r"model-root:(.*?) value=([-+]?(?:\d+\.?\d*|\.\d+))$"
)


def verify(checkpoint: Path, jsonl: Path, stdout: Path, tolerance: float = 1e-5) -> dict:
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    samples = read_jsonl(jsonl)
    logged = [_MODEL_RESULT.search(line.strip()) for line in stdout.read_text(encoding="utf-8").splitlines()]
    results = [match for match in logged if match]
    if not samples or len(results) != len(samples):
        raise ValueError(f"model-root log/sample mismatch: logs={len(results)}, samples={len(samples)}")
    model, _ = load_checkpoint(checkpoint)
    max_error = 0.0
    choices = 0
    for index, (sample, match) in enumerate(zip(samples, results, strict=True)):
        ids, actions = encode_actions(sample)
        visited = [position for position, action_id in enumerate(ids) if action_id in sample.visit_policy]
        if not visited:
            raise ValueError(f"sample {index} lacks visited legal actions")
        with torch.no_grad():
            logits, value = model(*encode_observation(sample), actions)
        expected_action = ids[max(visited, key=lambda position: float(logits[position]))]
        if match.group(1) != expected_action:
            raise ValueError(f"sample {index} native action differs from Python masked argmax")
        error = abs(float(match.group(2)) - float(value))
        if error > tolerance:
            raise ValueError(f"sample {index} value differs by {error}")
        max_error = max(max_error, error)
        choices += sample.legal_actions[0].kind == "NestedChoice"
    return {"samples": len(samples), "choiceSamples": choices, "maxAbsValueError": max_error}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--jsonl", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.checkpoint, args.jsonl, args.stdout), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
