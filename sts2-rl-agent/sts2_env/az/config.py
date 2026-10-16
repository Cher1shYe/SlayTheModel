"""Stable version, seed and atomic JSON contracts (no training dependencies)."""
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time

SCHEMA_VERSION = "az-scenario-v1"
RULES_VERSION = "az-combat-v1"
CONTENT_VERSION = "shrinker-starter-v1"
ACTION_VERSION = "combat-115-v1"
REWARD_VERSION = "win-loss-v1"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def derive_seed(master_seed, iteration, job_id, purpose):
    return int(content_hash([master_seed, iteration, job_id, purpose])[:16], 16) % (2**31)


def atomic_replace(source, destination):
    """Retry Windows access/sharing conflicts without weakening atomic publication.

    Keep the same fully flushed temporary file and original destination throughout.
    Sixteen attempts wait at most 11.55 seconds in total; persistent failures raise.
    Other errors (including POSIX permission errors) are never retried.
    """
    for attempt in range(16):
        try:
            os.replace(source, destination)
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 15:
                raise
            if attempt == 0:
                logging.getLogger(__name__).warning("Temporary Windows replace conflict for %s; retrying", destination)
            time.sleep(min(0.05 * 2 ** attempt, 1.0))
        else:
            if attempt:
                logging.getLogger(__name__).warning("Atomic replace recovered after %s retries: %s", attempt, destination)
            return


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value) + "\n"
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class EpisodeLimits:
    max_decisions: int = 400
    max_turns: int = 100

    def __post_init__(self):
        if any(type(n) is not int or n < 1 for n in (self.max_decisions, self.max_turns)):
            raise ValueError("Episode limits must be positive integers")
