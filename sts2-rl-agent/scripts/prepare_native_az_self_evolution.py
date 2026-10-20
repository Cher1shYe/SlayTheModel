"""Prepare a new isolated 1024-fight/3-epoch, 8-worker run from this checkout."""
import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_native_runtime import build
from scripts.run_native_az_self_evolution import SEARCH, runtime_hashes
from scripts.run_native_epoch_experiment import sha
from sts2_env.az.config import atomic_json


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--ritsu', type=Path, required=True)
    parser.add_argument('--dotnet', default='dotnet')
    parser.add_argument('--native-source', type=Path, default=root.parent/'sts2-native')
    parser.add_argument('--initial', type=Path, default=root/'models/epoch1024_e3_500ms/candidate.pt')
    parser.add_argument('--protocol', type=Path, default=root/'configs/az_self_evolution1024_w8/protocol.json')
    parser.add_argument('--iterations', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 1000:
        raise ValueError('Iterations must be between 1 and 1000')
    base = args.out.resolve()
    initial_sha = sha(args.initial)
    if initial_sha != '9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13':
        raise ValueError('Expected the audited 1024-fight candidate')
    if not (args.native_source/'combat/CombatSolver.csproj').is_file():
        raise ValueError('Vendored native source missing')
    base.mkdir(parents=True, exist_ok=False)
    exclude = shutil.ignore_patterns('.git', '.godot', '.local', 'bin', 'obj', 'artifacts', '__pycache__', '*.pyc')
    shutil.copytree(args.native_source, base/'native', ignore=exclude)
    frozen = base/'python'
    frozen.mkdir()
    for name in ('scripts', 'sts2_env', 'docs'):
        shutil.copytree(root/name, frozen/name, ignore=exclude)
    (base/'models').mkdir()
    shutil.copyfile(args.initial, base/'models/initial.pt')
    shutil.copyfile(args.protocol, base/'protocol.json')
    config = dict(
        backend=dict(kind='native-generic-collection-v1', repo=str(base/'native'),
                     game=str(args.game.resolve()), budget_ms=500, fights_per_worker=2),
        workers=8, initial_sha256=initial_sha, training_seed_base=4_000_000,
        search=dict(prior_mode=SEARCH, leaf_mode='learned', value_mix=1., budget=500),
        training=dict(episodes_per_iteration=1024, epochs=3, iterations=args.iterations,
                      batch_size=64, learning_rate=.0003, value_weight=.5, init_seed=20261020),
        gate='296 paired frozen recipes; promote iff V7 gain bootstrap CI95 lower > 0',
        collection_model='learner')
    atomic_json(base/'config.json', config)
    inputs = build(base/'native', args.game, args.ritsu, args.dotnet)
    atomic_json(base/'build-inputs.json', inputs)
    atomic_json(base/'runtime.json', runtime_hashes(base/'native'))
    print(base)


if __name__ == '__main__':
    main()
