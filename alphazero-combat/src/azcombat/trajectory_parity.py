"""Numerical parity for recorded natural-trajectory evaluator callbacks.

This verifies recorded roots, not unrecorded internal nodes or promotion quality.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

from .actual_tree_parity import _error
from .experiments import checked_model
from .native_probe import _audit_tree_parity
from .samples import read_jsonl
from .training import encode_actions, encode_observation, load_checkpoint


def verify_trajectory(checkpoint, onnx, samples_path, trace_path, tolerance=1e-5):
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("invalid parity tolerance")
    model_hash = checked_model(onnx)
    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    manifest = json.loads(onnx.with_suffix('.manifest.json').read_text(encoding='utf-8'))
    if manifest.get('checkpointSha256', '').lower() != checkpoint_hash:
        raise ValueError('checkpoint differs from ONNX manifest')
    samples = read_jsonl(samples_path)
    raw = [json.loads(line) for line in samples_path.read_text(encoding='utf-8').splitlines()]
    if not raw:
        raise ValueError('empty trajectory')
    summary = _audit_tree_parity(trace_path, raw, raw[0]['provenance']['decisionMetrics'])
    traces = [json.loads(line) for line in trace_path.read_text(encoding='utf-8').splitlines()]
    model, _ = load_checkpoint(checkpoint)
    model.eval()
    session = ort.InferenceSession(str(onnx), providers=['CPUExecutionProvider'])
    maximum_python = maximum_native = 0.0
    for index, (sample, trace) in enumerate(zip(samples, traces, strict=True)):
        ids, actions = encode_actions(sample)
        if ids != trace['orderedActionIds']:
            raise ValueError(f'row {index}: encoded action order differs')
        entities, globals_ = encode_observation(sample)
        with torch.no_grad():
            logits, value = model(entities, globals_, actions)
        onnx_logits, onnx_value = session.run(None, {
            'entities': entities.numpy(), 'globals': globals_.numpy(), 'actions': actions.numpy()})
        for label, python, native, exported in (
                ('logits', logits.numpy(), trace['logits'], onnx_logits),
                ('value', value.numpy(), trace['value'], onnx_value)):
            maximum_python = max(maximum_python, _error(
                python, np.asarray(exported), f'row {index} Python/ONNX {label}', tolerance))
            maximum_native = max(maximum_native, _error(
                np.asarray(exported), np.asarray(native), f'row {index} Native/ONNX {label}', tolerance))
    return {**summary, 'scope': 'recorded-natural-decision-roots-only',
            'tolerance': tolerance, 'maxPythonOnnxError': maximum_python,
            'maxNativeOnnxError': maximum_native, 'onnxSha256': model_hash,
            'checkpointSha256': checkpoint_hash,
            'samplesSha256': hashlib.sha256(samples_path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'onnx', 'samples', 'trace', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = verify_trajectory(args.checkpoint, args.onnx, args.samples, args.trace)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
