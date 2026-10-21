"""Audit and install retention-only runner changes in a stopped frozen run."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    base = args.experiment.resolve()
    source = Path(__file__).resolve().parent
    # All provenance must be computed with this run's frozen Python tree.
    sys.path.insert(0, str(base/'python'))
    from scripts.run_native_az_self_evolution import AlphaZeroBackend, runtime_hashes, sha
    from sts2_env.az.config import atomic_json, content_hash
    from sts2_env.az.native_platform import lock_run
    from sts2_env.az.model_factory import load_transformer_checkpoint
    from sts2_env.az.native_generic import CONTENT
    from sts2_env.az.rewards import V7
    held = lock_run(base/'runner.lock')
    helper = source/'native_checkpoint_retention.py'
    spec = importlib.util.spec_from_file_location('audited_retention', helper)
    retention = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retention)
    digest = retention.digest
    config = json.loads((base/'config.json').read_text())
    protocol = json.loads((base/'protocol.json').read_text())
    state_path = base/'run/state.json'
    state = json.loads(state_path.read_text())
    if state.get('retention_policy'):
        raise ValueError('Retention already installed; do not repeat migration')
    backend = AlphaZeroBackend(config['backend'], protocol, base/'run')
    backend.configure_workers(config['workers'])
    backend.configure_search('learned', 1.)
    runtime = json.loads((base/'runtime.json').read_text())
    inputs = json.loads((base/'build-inputs.json').read_text())
    if runtime != runtime_hashes(backend.repo) or any(digest(p) != h for p, h in inputs.items()):
        raise ValueError('Runtime or game dependency changed')
    frozen = base/'python/scripts'
    body = dict(config=config, protocol=protocol, provenance=backend.provenance,
        runtime=runtime, build_inputs=inputs, runner=sha(frozen/'run_native_az_self_evolution.py'),
        epoch_runner=sha(frozen/'run_native_epoch_experiment.py'))
    if content_hash(body) != state['identity']:
        raise ValueError('Old identity does not match untouched runtime/source/config')
    for name, expected in state['checkpoint_hashes'].items():
        if not (base/name).resolve().is_relative_to(base) or digest(base/name) != expected:
            raise ValueError(f'Checkpoint identity mismatch: {name}')
    epochs = []
    for dataset_path in sorted((base/'run').glob('iteration-*/dataset.json')):
        data = json.loads(dataset_path.read_text())
        per_epoch = math.ceil(data['samples']/config['training']['batch_size'])
        prefix = dataset_path.parent.relative_to(base).as_posix() + '/checkpoints/'
        counts = [int(Path(name).stem.split('-')[1]) for name in state['checkpoint_hashes']
                  if name.startswith(prefix)]
        for epoch in range(1, data['epochs'] + 1):
            step = epoch * per_epoch
            if step <= max(counts, default=0):
                name = prefix + f'update-{step:05d}.pt'
                if name not in state['checkpoint_hashes']:
                    raise ValueError(f'Epoch boundary checkpoint missing: {name}')
                epochs.append(name)
    pending = state.get('pending')
    latest = pending['update_checkpoint'] if pending else state['learner']
    _, payload = load_transformer_checkpoint(base/latest, 'XS', CONTENT, V7)
    training_state = payload.get('training_state')
    if not training_state or not {'optimizer', 'torch_rng', 'history', 'signature'} <= training_state.keys():
        raise ValueError('No complete optimizer/RNG recovery checkpoint')
    cache_files = {}
    for path in (base/'run').rglob('*.json'):
        if 'collection' in path.parts or 'baseline' in path.parts or 'validation' in path.parts:
            cache_files[path.relative_to(base).as_posix()] = digest(path)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    audit = base/'control'/f'retention-{stamp}'
    audit.mkdir(parents=True, exist_ok=False)
    for name in ('config.json', 'protocol.json', 'runtime.json', 'build-inputs.json', 'progress.json'):
        shutil.copy2(base/name, audit/name)
    shutil.copy2(state_path, audit/'state-before.json')
    shutil.copy2(frozen/'run_native_az_self_evolution.py', audit/'runner-before.py')
    new_body = dict(body, runner=sha(source/'run_native_az_self_evolution.py'), retention=sha(helper))
    evidence = dict(status='prepared', old_identity=state['identity'], new_identity=content_hash(new_body),
        old_runner_sha256=body['runner'], new_runner_sha256=new_body['runner'],
        retention_sha256=new_body['retention'], provenance=backend.provenance,
        cached_files=cache_files, epoch_checkpoints=epochs, recovery_checkpoint=latest,
        recovery_updates=len(training_state['history']), prior_checkpoints=len(state['checkpoint_hashes']),
        native_runtime_unchanged=True, config_unchanged=True)
    atomic_json(audit/'migration.json', evidence)
    shutil.copy2(source/'run_native_az_self_evolution.py', frozen/'run_native_az_self_evolution.py')
    shutil.copy2(helper, frozen/'native_checkpoint_retention.py')
    state.update(identity=evidence['new_identity'], retention_policy=retention.POLICY,
                 epoch_checkpoints=epochs, checkpoint_gc={})
    atomic_json(state_path, state)
    result = retention.prune_checkpoints(base, state_path, state)
    if any(digest(base/name) != expected for name, expected in cache_files.items()):
        raise ValueError('Battle cache changed during retention migration')
    evidence.update(status='completed', **result)
    atomic_json(audit/'migration.json', evidence)
    atomic_json(base/'progress.json', dict(status='stopped', phase='retention_migrated',
        audit=str(audit/'migration.json'), recovery_checkpoint=latest,
        updates=len(training_state['history']), **result))
    print(json.dumps(dict(audit=str(audit/'migration.json'), **result)))


if __name__ == '__main__':
    main()
