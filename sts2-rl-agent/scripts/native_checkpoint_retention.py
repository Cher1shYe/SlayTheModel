"""Crash-safe retention for immutable update checkpoints; never touch battle caches."""
import hashlib
import json
from pathlib import Path
import re

from sts2_env.az.config import atomic_json

POLICY = 'latest-epoch-candidate-champion-v1'
UPDATE = re.compile(r'run/iteration-\d{3,}/checkpoints/update-\d{5,}\.pt')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_update_path(base, name):
    if not UPDATE.fullmatch(name):
        raise ValueError('Refusing to delete a non-update artifact')
    base = Path(base).resolve()
    path = base.joinpath(*name.split('/'))
    if not path.resolve().is_relative_to(base):
        raise ValueError('Checkpoint escapes experiment directory')
    return path


def protected_checkpoints(state):
    result = {'models/initial.pt', state['learner'], state['champion']}
    pending = state.get('pending')
    if pending and pending.get('update_checkpoint'):
        result.add(pending['update_checkpoint'])
    result.update(state.get('epoch_checkpoints', []))
    for record in state['history']:
        result.add(record['candidate'])
        if record.get('champion'):
            result.add(record['champion'])
    return result


def prune_checkpoints(base, state_path, state):
    """Commit a GC journal before unlinking, so every interruption is recoverable.

    The caller must first durably publish its new recovery pointer. Unknown
    files are never removed. A queued deletion is idempotent after a crash.
    """
    if json.loads(Path(state_path).read_text(encoding='utf-8')) != state:
        raise ValueError('Checkpoint state must be committed before pruning')
    keep = protected_checkpoints(state)
    hashes = state['checkpoint_hashes']
    for name in keep:
        path = Path(base)/name
        if name not in hashes or not path.is_file() or not path.resolve().is_relative_to(Path(base).resolve()):
            raise ValueError(f'Protected checkpoint unavailable: {name}')
    queue = dict(state.get('checkpoint_gc', {}))
    if set(queue) & keep:
        raise ValueError('GC journal references a protected checkpoint')
    queue.update({name: value for name, value in hashes.items()
                  if name not in keep and UPDATE.fullmatch(name)})
    # Resolve/check every deletion target before committing or deleting any.
    paths = {name: safe_update_path(base, name) for name in queue}
    state['retention_policy'] = POLICY
    state['checkpoint_gc'] = queue
    state['checkpoint_hashes'] = {name: value for name, value in hashes.items() if name not in queue}
    atomic_json(state_path, state)
    removed, freed = 0, 0
    for name, path in paths.items():
        if path.exists():
            if digest(path) != queue[name]:
                raise ValueError(f'Obsolete checkpoint checksum mismatch: {name}')
            size = path.stat().st_size
            path.unlink()
            removed += 1
            freed += size
    state['checkpoint_gc'] = {}
    atomic_json(state_path, state)
    return dict(removed=removed, freed_bytes=freed, retained=len(state['checkpoint_hashes']))
