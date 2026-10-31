"""Memory-efficient threaded backend for deterministic paired PUCT evaluation.

The C++ search releases the GIL. Each task owns its RunContext, controller and
search RNG; only immutable evaluation-mode networks are shared.  This entrypoint
is deliberately restricted to greedy evaluation, never RL data collection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

import torch

from deployment import evaluate_latest_puct_100 as evaluation
from deployment import train_armg_puct_prior_rl as trainer
import agent.armg_train as base
from agent.armg import ArmGScorer
from agent.armg_floor_schedule import combat_budget
from agent.combat_dagger import CombatPolicy, load_combat_checkpoint

_model_lock = threading.Lock()
_shared_model = None
_shared_policy = None
_shared_paths = None
_search_slots = None
_search_parallelism = 8


def _models(weights, policy):
    global _shared_model, _shared_policy, _shared_paths
    paths = (str(Path(weights).resolve()), str(Path(policy).resolve()))
    with _model_lock:
        if _shared_paths is None:
            model = ArmGScorer().eval()
            model.load_state_dict(torch.load(paths[0], map_location='cpu', weights_only=True))
            combat = CombatPolicy().eval()
            load_combat_checkpoint(paths[1], combat)
            _shared_model, _shared_policy, _shared_paths = model, combat, paths
            Path(paths[0]).parent.joinpath('thread_backend.json').write_text(
                json.dumps({'backend': 'threads', 'max_parallel_searches': _search_parallelism}, indent=2),
                encoding='utf-8')
        if _shared_paths != paths:
            raise ValueError('threaded evaluation requires one frozen model and combat policy')
        return _shared_model, _shared_policy


def _play(task):
    (game_seed, _sampling_seed, search_seed, _version, weight_path, deterministic,
     simulations, floor_increment, elite_bonus, boss_bonus, max_steps,
     activity_dir, combat_mode, combat_path) = task
    if not deterministic or combat_mode != 'oracle':
        raise ValueError('threaded backend only supports greedy oracle evaluation')
    model, policy = _models(weight_path, combat_path)
    started, last = time.perf_counter(), 0.0
    activity_path = Path(activity_dir) / f'worker-thread-{threading.get_ident()}.json'

    def activity(controller, force=False):
        nonlocal last
        now = time.perf_counter()
        if not force and now - last < 10:
            return
        trainer._atomic_json(activity_path, {'seed': game_seed,
            'worker_tid': threading.get_ident(), 'mode': 'validation',
            'elapsed_seconds': now - started,
            'combat_decisions_started': controller.decisions,
            'normal_decisions': controller.normal_decisions,
            'boss_decisions': controller.boss_decisions,
            'completed_simulations': controller.simulations})
        last = now

    controller = trainer.FloorRootPuctController(policy, search_seed, activity,
                     simulations, floor_increment, elite_bonus, boss_bonus)
    def limited_plan(*args, **kwargs):
        with _search_slots:
            return controller.plan(*args, **kwargs)
    try:
        activity(controller, force=True)
        episode = base.collect_episode(game_seed, model, deterministic=True,
            combat='mcts-oracle', simulations=simulations, epsilon=0.05,
            max_steps=max_steps, ascension=0, need_rules=False, relic_rules=False,
            combat_budget_by_context=controller.budget_for_context,
            before_combat=controller.prepare_combat, mcts_plan=limited_plan)
        if episode['status'] != 'terminated':
            raise RuntimeError(f"episode {game_seed} {episode['status']}: {episode.get('error')}")
        expected = sum(combat_budget(f, simulations, floor_increment, elite=e, boss=b,
                       elite_bonus=elite_bonus, boss_bonus=boss_bonus) * n
                       for (f, e, b), n in controller.floor_decisions.items())
        if episode['mcts_searches'] != controller.decisions or episode['mcts_simulations'] != expected:
            raise RuntimeError('episode used an inconsistent PUCT budget')
        episode.update(normal_decisions=controller.normal_decisions,
            boss_decisions=controller.boss_decisions,
            normal_simulations=controller.normal_simulations,
            boss_simulations=controller.boss_simulations_completed,
            elite_decisions=controller.elite_decisions,
            elite_simulations=controller.elite_simulations)
        return episode
    finally:
        activity_path.unlink(missing_ok=True)


class _ThreadExecutor(ThreadPoolExecutor):
    def __init__(self, max_workers, mp_context=None):
        super().__init__(max_workers=max_workers, thread_name_prefix='puct-eval')

    def __exit__(self, exc_type, exc_value, traceback):
        # If one task fails, do not continue all queued evaluation episodes.
        self.shutdown(wait=True, cancel_futures=exc_type is not None)
        return False


def main():
    global _search_slots, _search_parallelism
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--retry-dir', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--simulations', type=int, default=2000)
    parser.add_argument('--floor-increment', type=int, default=200)
    parser.add_argument('--same-model-baseline')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--search-parallelism', type=int, default=8,
                        help='maximum simultaneous PUCT searches (does not change simulations)')
    args = parser.parse_args()
    _search_parallelism = args.search_parallelism
    if not 1 <= _search_parallelism <= args.workers:
        parser.error('search parallelism must be between 1 and workers')
    _search_slots = threading.BoundedSemaphore(_search_parallelism)
    del args.search_parallelism
    torch.set_num_threads(1)
    # Every episode receives its own controller and simulation state.
    trainer._play = _play
    evaluation.ProcessPoolExecutor = _ThreadExecutor
    evaluation.run(**vars(args))


if __name__ == '__main__':
    main()
