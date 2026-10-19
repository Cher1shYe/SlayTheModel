"""Durable complete-fight cache; unfinished fights never become training data."""
from dataclasses import asdict
import json
from pathlib import Path

from .config import atomic_json, content_hash


def cached_episode(job, collect):
    if not job.cache_dir:
        return collect()
    if not job.cache_identity:
        raise ValueError('Episode cache requires frozen run/model identity')
    settings = asdict(job)
    # These are transport/output locations, not simulation inputs. The stable
    # identity supplied by the runner binds source, config and source weights.
    for key in ('checkpoint', 'checkpoint_sha256', 'error_dir', 'cache_dir'):
        settings.pop(key)
    identity = content_hash(settings)
    path = Path(job.cache_dir) / f'{job.job_id}.json'

    def validate(episode):
        if (episode.get('complete') is not True or episode.get('split') != 'train'
                or episode.get('job_id') != job.job_id
                or episode.get('iteration') != job.iteration
                or episode.get('episode_id') != content_hash(
                    [job.master_seed, job.iteration, job.job_id])):
            raise ValueError(f'Invalid completed episode cache: {path}')

    if path.exists():
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('identity') != identity:
            raise ValueError(f'Episode cache identity mismatch: {path}')
        episode = document['episode']
        if document.get('sha256') != content_hash(episode):
            raise ValueError(f'Episode cache checksum mismatch: {path}')
        validate(episode)
        return episode
    episode = collect()
    validate(episode)
    # Match the representation read on resume (tuples become lists, numeric
    # mapping keys become strings) before hashing or handing data to replay.
    episode = json.loads(json.dumps(episode, allow_nan=False))
    atomic_json(path, dict(identity=identity, sha256=content_hash(episode), episode=episode))
    return episode
