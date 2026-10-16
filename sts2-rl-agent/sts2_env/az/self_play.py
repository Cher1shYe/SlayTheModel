"""Persistent spawn workers collect complete fights with frozen CPU weights."""
from concurrent.futures import ProcessPoolExecutor
from collections import deque
from dataclasses import asdict, dataclass
import hashlib
import multiprocessing
import os
from pathlib import Path

import torch

from .adapter import ObservableCombatAdapter
from .config import ACTION_VERSION, REWARD_VERSION, RULES_VERSION, EpisodeLimits, atomic_json, content_hash, derive_seed
from .encoder import OBSERVABLE_SCHEMA, encode_information, schema_for
from .network import load_checkpoint
from .observable_puct import plan_observable
from .scenarios import CombatScenario
from .search_config import LEGACY, validate_search


@dataclass(frozen=True)
class CollectionJob:
    job_id: str
    iteration: int
    master_seed: int
    scenario: dict
    checkpoint: str
    checkpoint_sha256: str
    model_version: str
    error_dir: str
    simulations: int = 64
    limits: EpisodeLimits = EpisodeLimits()
    reward_version: str = REWARD_VERSION
    search_version: str = LEGACY


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_models = {}


def initialize_worker():
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)


def collect_episode(job):
    validate_search(job.search_version)
    recipe = CombatScenario.from_dict(job.scenario)
    if recipe.split != "train" or job.simulations < 1:
        raise ValueError("Collection requires train recipes and positive budget")
    if file_digest(job.checkpoint) != job.checkpoint_sha256:
        raise ValueError("Frozen checkpoint was modified")
    key = (job.checkpoint_sha256, job.model_version)
    if key not in _models:
        model, metadata = load_checkpoint(job.checkpoint, "observable", job.reward_version, recipe.content_manifest_version)
        if metadata["model_version"] != job.model_version:
            raise ValueError("Job model version mismatch")
        _models.clear()
        _models[key] = model.requires_grad_(False).eval()
    model = _models[key]
    if model.reward_version != job.reward_version or model.content_version != recipe.content_manifest_version:
        raise ValueError("Job/model reward mismatch")
    schema = schema_for("observable", job.reward_version, recipe.content_manifest_version)
    episode_id = content_hash([job.master_seed, job.iteration, job.job_id])
    env = ObservableCombatAdapter(recipe, limits=job.limits, error_dir=job.error_dir, reward_version=job.reward_version)
    rows = []
    try:
        while not env.outcome().done:
            info = env.information
            step = len(rows)
            result = plan_observable(info, model, model_version=job.model_version,
                                     budget=job.simulations, training=True, search_version=job.search_version,
                                     temperature=1 if step < 10 else 0,
                                     search_seed=derive_seed(job.master_seed, job.iteration, job.job_id, f"search-{step}"))
            observation = encode_information(info).to_dict()
            env.step(result.action)
            rows.append(dict(episode_id=episode_id, scenario_id=recipe.scenario_id,
                             family_id=recipe.family_id, encounter_id=recipe.encounter_id, step_index=step,
                             information_mode="observable", model_version=job.model_version,
                             content_manifest_version=recipe.content_manifest_version,
                             encoder_version=schema["encoder_version"],
                             schema_hash=content_hash(schema),
                             action_schema_version=schema["action_schema_version"], reward_version=job.reward_version,
                             rules_version=RULES_VERSION, observation=observation,
                             legal_mask=list(info.legal_mask), root_visits=result.root_visits.tolist(),
                             policy_target=result.policy_target.tolist(), chosen_action=result.action,
                             search_simulations=result.simulations, search_seconds=result.elapsed,
                             forced_action=result.forced_action))
            if job.search_version != LEGACY:
                rows[-1]["search_version"] = job.search_version
        outcome = asdict(env.outcome())
        for row in rows:
            row.update(z=outcome["reward"], **{k: outcome[k] for k in
                       ("termination_reason", "final_hp", "turns", "decisions", "initial_hp", "enemy_final_hp", "enemy_max_hp", "enemy_initial_hp", "enemy_roster")})
        return dict(complete=True, episode_id=episode_id, job_id=job.job_id,
                    iteration=job.iteration, split=recipe.split, rows=rows,
                    debug=dict(trace=env.trace(), master_seed=job.master_seed,
                               checkpoint_sha256=job.checkpoint_sha256), worker_pid=os.getpid())
    except Exception as exc:
        atomic_json(Path(job.error_dir) / f"{episode_id}.json", dict(trace=env.trace(), error=repr(exc)))
        raise


class Collector:
    def __init__(self, workers=4):
        if type(workers) is not int or workers < 1:
            raise ValueError("Positive worker count required")
        self.workers = workers
        self.pool = ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"),
                                        initializer=initialize_worker)

    def collect(self, jobs):
        return list(self.iter_collect(jobs))

    def iter_collect(self, jobs):
        """Ordered bounded window; consumer commits before more work is submitted."""
        jobs = list(jobs)
        if len({(j.master_seed, j.iteration, j.job_id) for j in jobs}) != len(jobs):
            raise ValueError("Duplicate collection jobs")
        iterator = iter(jobs)
        pending = deque()
        try:
            for _ in range(min(self.workers, len(jobs))):
                pending.append(self.pool.submit(collect_episode, next(iterator)))
            while pending:
                future = pending.popleft()
                episode = future.result()
                del future
                yield episode
                del episode
                job = next(iterator, None)
                if job is not None:
                    pending.append(self.pool.submit(collect_episode, job))
        finally:
            for future in pending:
                future.cancel()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.pool.shutdown(wait=True, cancel_futures=True)
