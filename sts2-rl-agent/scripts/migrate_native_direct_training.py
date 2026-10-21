"""Audit a paused frozen run before switching to direct promotion without evaluation."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    base = args.experiment.resolve()
    source = Path(__file__).resolve().parent
    sys.path.insert(0, str(base/'python'))
    from scripts.run_native_az_self_evolution import AlphaZeroBackend, runtime_hashes, sha
    from sts2_env.az.config import atomic_json, content_hash
    from sts2_env.az.native_platform import lock_run
    from sts2_env.az.model_factory import load_transformer_checkpoint
    from sts2_env.az.native_generic import CONTENT
    from sts2_env.az.rewards import V7
    held = lock_run(base/'runner.lock')
    config = json.loads((base/'config.json').read_text(encoding='utf-8'))
    protocol = json.loads((base/'protocol.json').read_text(encoding='utf-8'))
    state_path = base/'run/state.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    progress = json.loads((base/'progress.json').read_text(encoding='utf-8'))
    if progress['status'] != 'paused' or state['pending'] is not None:
        raise ValueError('Migration requires a paused collection boundary')
    if config.get('promotion_mode') == 'direct-no-validation':
        raise ValueError('Already migrated')
    backend = AlphaZeroBackend(config['backend'], protocol, base/'run')
    backend.configure_workers(config['workers'])
    backend.configure_search('learned', 1.)
    runtime = json.loads((base/'runtime.json').read_text(encoding='utf-8'))
    inputs = json.loads((base/'build-inputs.json').read_text(encoding='utf-8'))
    if runtime != runtime_hashes(backend.repo) or any(sha(p) != h for p, h in inputs.items()):
        raise ValueError('Runtime or build input changed')
    frozen = base/'python/scripts'
    body = dict(config=config, protocol=protocol, provenance=backend.provenance,
        runtime=runtime, build_inputs=inputs, runner=sha(frozen/'run_native_az_self_evolution.py'),
        retention=sha(frozen/'native_checkpoint_retention.py'),
        epoch_runner=sha(frozen/'run_native_epoch_experiment.py'))
    if content_hash(body) != state['identity']:
        raise ValueError('Old identity mismatch')
    for name, digest in state['checkpoint_hashes'].items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name) != digest:
            raise ValueError(f'Checkpoint mismatch: {name}')
    _, payload = load_transformer_checkpoint(base/state['learner'], 'XS', CONTENT, V7)
    if not {'optimizer', 'torch_rng', 'history', 'signature'} <= payload['training_state'].keys():
        raise ValueError('Incomplete recovery checkpoint')
    cache = {p.relative_to(base).as_posix(): sha(p) for p in (base/'run').rglob('*.json')
             if {'collection', 'baseline', 'validation'} & set(p.parts)}
    audit = base/'control'/('direct-training-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    audit.mkdir(parents=True, exist_ok=False)
    for name in ('config.json', 'protocol.json', 'runtime.json', 'build-inputs.json', 'progress.json'):
        shutil.copy2(base/name, audit/name)
    shutil.copy2(state_path, audit/'state-before.json')
    shutil.copy2(frozen/'run_native_az_self_evolution.py', audit/'runner-before.py')
    old_identity = state['identity']
    config.update(promotion_mode='direct-no-validation',
                  gate='No evaluation; promote every completed training round directly')
    body.update(config=config, runner=sha(source/'run_native_az_self_evolution.py'))
    state.update(identity=content_hash(body), champion=state['learner'], champion_rows=None)
    evidence = dict(status='prepared', old_identity=old_identity, new_identity=state['identity'],
        cached_files=cache, checkpoint_hashes=state['checkpoint_hashes'],
        previous_champion=json.loads((audit/'state-before.json').read_text())['champion'],
        champion=state['champion'], runtime_unchanged=True,
        note='Historical evaluation records preserved; future evaluation disabled. Cache validated normally on resume.')
    atomic_json(audit/'migration.json', evidence)
    shutil.copy2(source/'run_native_az_self_evolution.py', frozen/'run_native_az_self_evolution.py')
    atomic_json(base/'config.json', config)
    atomic_json(state_path, state)
    if any(sha(base/name) != digest for name, digest in cache.items()):
        raise ValueError('Cache changed during migration')
    evidence['status'] = 'completed'
    atomic_json(audit/'migration.json', evidence)
    print(json.dumps({'audit': str(audit/'migration.json'), 'cached_files': len(cache),
                      'champion': state['champion']}))
    held.close()


if __name__ == '__main__':
    main()
