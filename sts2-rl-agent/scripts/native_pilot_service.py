"""Resident CPU inference using the exact same codec as native training ingestion."""
import argparse
import atexit
import hashlib
import json
import os
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--checkpoint', required=True)
    args = parser.parse_args()
    os.chdir(args.source)
    sys.path.insert(0, args.source)
    import torch
    from sts2_env.az.native_pilot import encode_native
    from sts2_env.az.all_runner import load_transformer_checkpoint, TIER, ALL_CONTENT, V7
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    from sts2_env.az.native_generic import CONTENT, encode
    from sts2_env.az import native_transformer
    cache_option = os.environ.get('STS2_TOKEN_HASH_CACHE', '1')
    if cache_option not in ('0', '1'):
        raise ValueError('STS2_TOKEN_HASH_CACHE must be 0 or 1')
    native_transformer.TOKEN_HASH_CACHE_ENABLED = cache_option == '1'
    header = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    generic = header.get('content_manifest_version') == CONTENT
    model, _ = load_transformer_checkpoint(args.checkpoint, TIER, CONTENT if generic else ALL_CONTENT, V7)
    model.eval().requires_grad_(False)
    with open(args.checkpoint, 'rb') as stream:
        sha = hashlib.sha256(stream.read()).hexdigest()
    stats_path = os.environ.get('STS2_LEAF_REPEAT_STATS')
    stats = None
    if stats_path:
        from sts2_env.az.leaf_repeat_stats import LeafRepeatStats
        stats = LeafRepeatStats(sha)
        def save_stats():
            report = stats.report()
            report['token_hash_cache'] = native_transformer.token_ids.cache_info()._asdict()
            report['token_hash_cache_enabled'] = native_transformer.TOKEN_HASH_CACHE_ENABLED
            with open(stats_path, 'w', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
        atexit.register(save_stats)
    print(json.dumps(dict(ready=True, sha256=sha)), flush=True)
    for line in sys.stdin:
        try:
            start = perf_counter()
            d = json.loads(line)
            if d.get('operation') == 'value':
                if not generic: raise ValueError('Generic value checkpoint required')
                obs=encode(d['observation'],value_only=True)
                if 'expected' in d:
                    expected=encode(d['expected'],value_only=True)
                    if obs['entities'] != expected['entities']:
                        for i,(a,b) in enumerate(zip(obs['entities'],expected['entities'])):
                            if a!=b: raise ValueError(f'Branch/live value features differ at {i}: {a} != {b}')
                        raise ValueError('Branch/live entity count differs')
                encoded=perf_counter()
                if stats is not None and 'expected' not in d:
                    stats.observe(obs)
                value=model.predict_value(obs)
                print(json.dumps(dict(value=value,encodeMs=(encoded-start)*1000,inferMs=(perf_counter()-encoded)*1000)),flush=True)
                continue
            if generic:
                if stats is not None:
                    stats.begin_decision(d['decisions'])
                obs = encode(d)
                mapping = {a['Key']: a['Key'] for a in d['actions']}
            else:
                obs, mapping = encode_native(d)
            encoded = perf_counter()
            probabilities, _ = model.predict(obs)
            print(json.dumps(dict(priors=[probabilities[mapping[a['Key']]] for a in d['actions']],
                encodeMs=(encoded-start)*1000, inferMs=(perf_counter()-encoded)*1000)), flush=True)
        except Exception as exc:
            print(json.dumps(dict(error=f'{type(exc).__name__}: {exc}')), flush=True)


if __name__ == '__main__':
    main()
