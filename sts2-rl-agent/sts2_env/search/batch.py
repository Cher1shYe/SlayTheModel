"""Persistent process workers for independent combat searches.

Pass reproducible scenario recipes, not live CombatState objects containing
closures. This increases aggregate sampling throughput, not single-move speed.
"""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import hashlib
import multiprocessing
import pickle
from time import perf_counter

import numpy as np

from sts2_env.search.mcts import STS2CombatEnv, apply_action, legal_actions, search


@dataclass(frozen=True)
class SearchJob:
    scene_seed: int
    advance: int = 0
    simulations: int = 256
    rollout_depth: int = 40
    search_seed: int = 999
    mode: str = "auto"


def _signature(node):
    return (node.action, node.visits, node.total_value, tuple(node.untried),
            tuple(_signature(child) for child in node.children))


def run_job(job):
    env = STS2CombatEnv()
    env.reset(seed=job.scene_seed)
    rng = np.random.default_rng(job.scene_seed + 100)
    for _ in range(job.advance):
        if env.combat.is_over:
            break
        actions = legal_actions(env.combat)
        apply_action(env.combat, actions[int(rng.integers(len(actions)))])
    result = search(env.combat, job.simulations, job.rollout_depth,
                    job.search_seed, mode=job.mode)
    return dict(action=result.action, simulations=result.simulations,
                search_seconds=result.elapsed, clones=result.clones,
                tree_digest=hashlib.sha256(pickle.dumps(_signature(result.root))).hexdigest())


def _warmup(_):
    run_job(SearchJob(scene_seed=0, simulations=2, rollout_depth=0))


class SearchPool:
    """Reusable independent-search pool; call from a guarded main on Windows."""

    def __init__(self, workers=4):
        if workers < 1:
            raise ValueError("workers must be positive")
        self.workers = workers
        self.executor = None

    def __enter__(self):
        started = perf_counter()
        self.executor = ProcessPoolExecutor(
            max_workers=self.workers, mp_context=multiprocessing.get_context("spawn"))
        try:
            list(self.executor.map(_warmup, range(self.workers)))
        except BaseException:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None
            raise
        self.startup_seconds = perf_counter() - started
        return self

    def run(self, jobs):
        if self.executor is None:
            raise RuntimeError("Use SearchPool as a context manager")
        return list(self.executor.map(run_job, jobs, chunksize=1))

    def __exit__(self, *exc):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.executor = None
