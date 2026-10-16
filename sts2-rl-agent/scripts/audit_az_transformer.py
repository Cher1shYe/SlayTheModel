"""Reproducible T0/T1 contract/resource audit. No self-play or training jobs.

Run from repository root: python scripts/audit_az_transformer.py
Synthetic gradient probes deliberately bypass game length limits; they measure
network scaling and do not certify support for such game states.
"""
import gc
import json
from dataclasses import asdict
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.entity_encoder import encode_entities, SCHEMA, SCHEMA_HASH
from sts2_env.az.model_factory import create_transformer, model_metadata
from sts2_env.az.transformer_network import batch_entities, TIERS
from sts2_env.az.network import code_digest
from sts2_env.az.config import atomic_json, content_hash


def synthetic_batch(reference, entities, actions):
    out = {}
    for key, value in reference.items():
        if not isinstance(value, torch.Tensor):
            out[key] = value
        elif key == 'state_index':
            out[key] = value
        else:
            width = actions if key in ('action_type', 'source', 'target_ref', 'choice_ref', 'legal_mask') else entities
            out[key] = value[:, torch.arange(width) % value.shape[1]].clone()
    out['entity_mask'].fill_(True)
    out['legal_mask'].fill_(True)
    # Reference indices still refer to valid original entities in the larger array.
    return out


def main():
    torch.set_num_threads(1)
    torch.manual_seed(19)
    process = psutil.Process()
    env = ObservableCombatAdapter(starter_scenario(8))
    fixtures = []
    for _ in range(3):
        observation = encode_entities(env.information)
        fixtures.append({'information': asdict(env.information), 'encoded': asdict(observation)})
        env.step(0)
    root = Path(__file__).resolve().parents[1]
    fixture_path = root / 'docs/transformer_public_fixtures.json'
    atomic_json(fixture_path, fixtures)
    reference = batch_entities([observation])
    report = {'scope': 'T0/T1 starter network-only slice; no quality experiment',
              'schema': SCHEMA, 'schema_hash': SCHEMA_HASH, 'code_digest': code_digest(),
              'fixture_digest': content_hash(fixtures),
              'device': 'cpu', 'platform': platform.platform(), 'processor': platform.processor(),
              'torch': str(torch.__version__), 'threads': 1, 'batch_size': 1,
              'available_ram_at_start': psutil.virtual_memory().available,
              'measurement_note': 'Single timed forward/backward per synthetic point; no latency SLO claim. '
                  'RSS after backward includes allocator retention. Process peak is cumulative, not per tier. '
                  'Adam base bytes are a formula, not measured optimizer allocation.',
              'tiers': {}, 'synthetic_gradient_probes': []}
    for tier in TIERS:
        # Actual CPU parameter allocation and numel, released before the next tier.
        model = create_transformer(tier)
        count = sum(p.numel() for p in model.parameters())
        report['tiers'][tier] = dict(model_metadata(model), fp32_adam_base_bytes=16*count,
                                     parameter_bytes=sum(p.numel()*p.element_size() for p in model.parameters()),
                                     cpu_parameter_allocation=True,
                                     rss_after_allocation=process.memory_info().rss,
                                     shape_check='meta tensors; no throughput claim for M/L/XL')
        if tier in ('XS', 'S'):
            for n in (128, 256, 512):
                for a in (32, 128, 512):
                    batch = synthetic_batch(reference, n, a)
                    model.zero_grad(set_to_none=True)
                    before = process.memory_info().rss
                    start = time.perf_counter()
                    logits, values = model(batch, action_chunk_size=32)
                    loss = logits.square().mean() + values.square().mean()
                    loss.backward()
                    elapsed = time.perf_counter() - start
                    if not torch.isfinite(loss) or not all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None):
                        raise RuntimeError('Nonfinite synthetic gradient probe')
                    report['synthetic_gradient_probes'].append({'tier': tier, 'entities': n, 'actions': a,
                        'seconds_forward_backward': elapsed, 'rss_before': before,
                        'rss_after_backward': process.memory_info().rss,
                        'input_tensor_bytes': sum(v.numel()*v.element_size() for v in batch.values() if isinstance(v, torch.Tensor)),
                        'finite_loss_and_gradients': True})
                    del logits, values, loss, batch
            report['tiers'][tier]['shape_check'] = 'real CPU forward/backward; pytest separately covers mixed game lengths and Adam update'
        del model
        gc.collect()
        with torch.device('meta'):
            shape_model = create_transformer(tier)
        meta = {k: v.to('meta') if isinstance(v, torch.Tensor) else v for k, v in reference.items()}
        logits, value = shape_model(meta)
        report['tiers'][tier]['output_shapes'] = [list(logits.shape), list(value.shape)]
        del shape_model, logits, value
        print(f'{tier}: {count:,} parameters', flush=True)
    mem = process.memory_info()
    report['process_peak_working_set_bytes'] = getattr(mem, 'peak_wset', None)
    atomic_json(root / 'docs/transformer_t0_t1_audit.json', report)
    print(json.dumps({'report': 'docs/transformer_t0_t1_audit.json', 'probes': len(report['synthetic_gradient_probes'])}))


if __name__ == '__main__':
    main()
