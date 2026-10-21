"""Freeze independent scratch-PPO sources/config; build only the new runtime."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_native_runtime import build
from scripts.check_native_collection import sha
from scripts.run_native_az_self_evolution import runtime_hashes
from sts2_env.az.config import atomic_json
from sts2_env.az.native_generic_backend import validate_protocol


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--native-template', type=Path, required=True)
    p.add_argument('--protocol', type=Path, required=True)
    p.add_argument('--game', required=True)
    p.add_argument('--ritsu', required=True)
    p.add_argument('--dotnet', required=True)
    p.add_argument('--tier', choices=['XS', 'S'], default='XS')
    p.add_argument('--reuse-runtime', action='store_true',
                   help='Copy the audited template runtime; never rebuild its shared DLLs.')
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(args.protocol.read_text())
    validate_protocol(protocol)
    native = out/'native'
    shutil.copytree(args.native_template, native, ignore=shutil.ignore_patterns(
        'artifacts', 'bin', 'obj', '.godot', '.local', '.git', '__pycache__'))
    # Keep all audited simulation fixes in the template. Only replace the worker
    # collection adapter and add policy sampling; the PPO path performs no search.
    for name in ('GenericCollection.cs', 'PolicySampling.cs', 'NativeSession.cs'):
        shutil.copy2(root.parent/'sts2-native/tools/Sts2.NativeWorker'/name,
                     native/'tools/Sts2.NativeWorker'/name)
    if args.reuse_runtime:
        receipt = json.loads((args.native_template/'artifacts/build-inputs.json').read_text())
        if not receipt or any(sha(path) != digest for path, digest in receipt.items()):
            raise ValueError('Audited runtime dependencies changed')
        # This mode requires byte-identical worker sources, including the PPO adapter.
        for name in ('GenericCollection.cs', 'PolicySampling.cs', 'NativeSession.cs'):
            if sha(native/'tools/Sts2.NativeWorker'/name) != sha(args.native_template/'tools/Sts2.NativeWorker'/name):
                raise ValueError('Cannot reuse a runtime with modified worker sources')
        shutil.copytree(args.native_template/'artifacts/native-host', native/'artifacts/native-host')
    else:
        receipt = build(native, args.game, args.ritsu, args.dotnet)
    atomic_json(native/'artifacts/build-inputs.json', receipt)
    frozen = out/'python'
    for name in ('scripts', 'sts2_env', 'docs'):
        shutil.copytree(root/name, frozen/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    config = dict(algorithm='PPO-Clip', initialization='random', tier=args.tier, seed=20261021,
        workers=8, torch_threads=2, recipe_seed=8_000_000, rollout_battles=128,
        checkpoint_every=512, epochs=3, batch_size=64, microbatch=16,
        learning_rate=3e-4, clip=.2, entropy_weight=.01, value_weight=.5,
        gamma=1., gae_lambda=.95, max_grad_norm=.5, target_kl=.03,
        horizon='V7 finite 40-turn/100-decision; time_limit payoff without bootstrap',
        backend=dict(kind='native-generic-collection-v1', repo=str(native),
                     game=str(Path(args.game).resolve()), budget_ms=500, fights_per_worker=2))
    atomic_json(out/'config.json', config)
    atomic_json(out/'protocol.json', protocol)
    atomic_json(out/'expected.json', dict(runtime=runtime_hashes(native), dependencies=receipt,
        native_template=str(args.native_template.resolve()),
        native_sources={str(f.relative_to(native)):sha(f) for f in native.rglob('*.cs')
                        if not {'bin','obj','.godot'} & set(f.parts)}))
    (out/'README.md').write_text(
        f'# Scratch PPO\n\nRandom {args.tier} weights and fresh AdamW; no pretrained weights, MCTS labels or replay. '
        '128 sampled-policy battles per rollout, up to 3 PPO epochs; target-KL early stopping. '
        'Permanent post-update checkpoints every 512 trained battles; latest.pt persists every optimizer boundary. '
        'All behavior checkpoints and native trajectories are retained. V7 finite horizon, gamma=1, lambda=.95; '
        'time_limit remains a truncation flag but is a scored endpoint, never bootstrapped twice.\n\n'
        'Run python/scripts/run_native_ppo.py --experiment THIS_DIRECTORY; resume adds --resume. '
        'Create STOP to pause at a safe boundary; remove STOP before resuming. '
        'progress.json refreshes every 5 seconds. No automatic promotion or original self-evolution resume.\n',
        encoding='utf-8')
    print(out, flush=True)


if __name__ == '__main__':
    main()
