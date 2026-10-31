"""REINFORCE from an ArmG checkpoint plus a weak on-policy website prior.

Load the exact extension specified by STS2_PRIOR_PYD before importing agent
modules. Each battle decision executes one action and uses its configured
ordinary or Boss simulation budget. All
nonterminated episodes abort the batch.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import shutil
import tempfile
import time

from deployment import evaluate_battle_root_prior as extension_loader

import numpy as np
import torch

import agent.armg_train as base
from agent.armg import ArmGScorer
from agent.hidden_mcts_controller import HiddenMctsController
from agent.armg_site_prior_loss import CardSkipPrior, SKIP_ELO, backward_prior

TRAIN_SEED_BASE = 10_300_000
VALIDATION_SEED_BASE = 20_300_000
# Reserve independent environment seeds for each round. The prior collector
# uses a separate range.
CYCLE_SEED_STRIDE = 10_000
_worker_model = None
_worker_version = None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        # A user reading the file on Windows may briefly prevent replace.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _play(task):
    global _worker_model, _worker_version
    game_seed, sampling_seed, search_seed, version, weight_path, deterministic, simulations, boss_simulations, max_steps, activity_dir, combat_mode = task
    if _worker_model is None:
        torch.set_num_threads(1)
        _worker_model = ArmGScorer().eval()
    if _worker_version != version:
        _worker_model.load_state_dict(torch.load(weight_path, map_location='cpu', weights_only=True))
        _worker_version = version
    torch.manual_seed(sampling_seed)
    started = time.perf_counter()
    previous_update = 0.0
    activity_path = Path(activity_dir) / f'worker-{os.getpid()}.json'

    def activity(controller, force=False):
        nonlocal previous_update
        now = time.perf_counter()
        if not force and now - previous_update < 10:
            return
        _atomic_json(activity_path, {'seed': game_seed, 'worker_pid': os.getpid(),
                     'mode': 'validation' if deterministic else 'training',
                     'elapsed_seconds': now - started,
                     'combat_decisions_started': controller.decisions,
                     'normal_decisions': controller.normal_decisions,
                     'boss_decisions': controller.boss_decisions,
                     'completed_simulations': controller.simulations,
                     'updated_utc': datetime.now(timezone.utc).isoformat()})
        previous_update = now

    controller = HiddenMctsController(search_seed, activity, boss_simulations, mode=combat_mode)
    original = base._mcts_plan
    base._mcts_plan = controller.plan
    try:
        activity(controller, force=True)
        episode = base.collect_episode(game_seed, _worker_model, deterministic=deterministic,
                                       combat='mcts-oracle' if combat_mode == 'oracle' else 'mcts-resampled', simulations=simulations,
                                       epsilon=0.05, max_steps=max_steps, ascension=0,
                                       need_rules=False, relic_rules=False)
        if episode['status'] != 'terminated':
            raise RuntimeError(f"episode {game_seed} {episode['status']}: {episode.get('error')}")
        expected = controller.normal_decisions * simulations + controller.boss_decisions * boss_simulations
        if episode['mcts_searches'] != controller.decisions or episode['mcts_simulations'] != expected:
            raise RuntimeError(f"episode {game_seed} has an incomplete MCTS budget")
        episode['normal_decisions'] = controller.normal_decisions
        episode['boss_decisions'] = controller.boss_decisions
        episode['normal_simulations'] = controller.normal_simulations
        episode['boss_simulations'] = controller.boss_simulations_completed
        return episode
    finally:
        base._mcts_plan = original
        try:
            activity_path.unlink(missing_ok=True)
        except OSError:
            pass


def train(*, init_checkpoint, out_dir, data_dir, games=640, batch_size=32, workers=8,
          simulations=2000, boss_simulations=10000, eval_every=640, eval_runs=50, max_steps=5000,
          seed=20261030, lr=3e-4, resume=None, combat_mode='oracle',
          cycle_index=None, previous_rl=None, prior_weight=0.05):
    if min(games, batch_size, workers, simulations, boss_simulations, eval_every, eval_runs, max_steps) < 1 or lr <= 0:
        raise ValueError('training parameters must be positive')
    if combat_mode != 'oracle' or cycle_index is not None or previous_rl:
        raise ValueError('this run requires oracle mode and an independently initialized training run')
    if not np.isfinite(prior_weight) or prior_weight < 0:
        raise ValueError('prior weight must be finite and nonnegative')
    if cycle_index is None:
        if previous_rl:
            raise ValueError('previous RL checkpoint requires a cycle index')
        cycle_seed_base = TRAIN_SEED_BASE
    else:
        if cycle_index < 0 or games > CYCLE_SEED_STRIDE:
            raise ValueError('invalid cycle index or cycle seed capacity')
        if (cycle_index == 0) != (previous_rl is None):
            raise ValueError('cycle 0 must not have previous RL; later cycles must')
        cycle_seed_base = TRAIN_SEED_BASE + cycle_index * CYCLE_SEED_STRIDE
        if cycle_seed_base + games > VALIDATION_SEED_BASE:
            raise ValueError('cycle training seeds overlap validation seeds')
    if not extension_loader._extension:
        raise RuntimeError('set STS2_PRIOR_PYD to the isolated hidden MCTS extension')
    extension_path = Path(extension_loader._extension).resolve(strict=True)
    init_path = Path(init_checkpoint).resolve(strict=True)
    data_path = Path(data_dir).resolve(strict=True)
    manifest = data_path / 'manifest.json'
    manifest_data = json.loads(manifest.read_text(encoding='utf-8'))
    for name in ('cards', 'relics', 'potions', 'community'):
        if _sha(data_path / (name + '.json')) != manifest_data['snapshots'][name]['sha256']:
            raise ValueError(f'website snapshot hash mismatch: {name}')
    previous_path = Path(previous_rl).resolve(strict=True) if previous_rl else None
    previous = torch.load(previous_path, map_location='cpu', weights_only=False) if previous_path else None
    if previous is not None:
        previous_progress = previous.get('progress', {})
        previous_settings = previous.get('settings', {})
        if (prior_progress.get('source_rl_sha256') != _sha(previous_path) or
                previous_progress.get('cycle_index') != cycle_index - 1 or
                previous_progress.get('games') != previous_settings.get('cycle_target_games') or
                previous_settings.get('information') != combat_mode or
                previous_settings.get('simulations') != simulations or
                previous_settings.get('boss_simulations_per_decision') != boss_simulations or
                previous_settings.get('simulator_sha256') != _sha(extension_path) or
                previous_settings.get('path_cache') != 'none' or
                previous_settings.get('lr') != lr or
                previous.get('optimizer_state_dict') is None):
            raise ValueError('previous RL checkpoint or prior lineage does not match this cycle')
    out = Path(out_dir).resolve()
    if resume:
        if not out.is_dir():
            raise FileNotFoundError(out)
    else:
        out.mkdir(parents=True, exist_ok=False)
    snapshot_dir = out / 'data_snapshot'
    if not resume:
        snapshot_dir.mkdir()
        for name in ('cards', 'relics', 'potions', 'community', 'manifest'):
            shutil.copyfile(data_path / (name + '.json'), snapshot_dir / (name + '.json'))
    if _sha(snapshot_dir / 'manifest.json') != _sha(manifest):
        raise ValueError('saved website data manifest differs from requested manifest')
    for name in ('cards', 'relics', 'potions', 'community'):
        if _sha(snapshot_dir / (name + '.json')) != manifest_data['snapshots'][name]['sha256']:
            raise ValueError(f'saved website snapshot hash mismatch: {name}')
    site_prior = CardSkipPrior(snapshot_dir)
    activity_dir = out / 'active'
    activity_dir.mkdir(exist_ok=True)
    torch.set_num_threads(1)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = ArmGScorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    settings = {'combat': 'mcts-oracle' if combat_mode == 'oracle' else 'mcts-resampled',
                'information': combat_mode, 'simulations': simulations, 'epsilon': 0.05,
                'max_steps': max_steps, 'ascension': 0, 'seed': seed, 'batch_size': batch_size,
                'eval_every': eval_every, 'eval_runs': eval_runs, 'lr': lr,
                'train_seed_offset': cycle_seed_base - 10_000_000,
                'need_rules': False, 'relic_rules': False, 'workers': workers,
                'boss_simulations_per_decision': boss_simulations,
                'root_action': 'best winning rollout else most visited' if combat_mode == 'oracle' else 'most visited',
                'path_cache': 'none',
                'search_rng': 'independent per-episode RNG, not derived from game seed',
                'simulator_sha256': _sha(extension_path), 'init_sha256': _sha(init_path),
                'validation_seed_base': VALIDATION_SEED_BASE,
                'website_manifest_sha256': _sha(manifest), 'website_data_dir': str(data_path),
                'website_snapshot_dir': str(snapshot_dir), 'prior_weight': prior_weight,
                'skip_elos_by_act': list(SKIP_ELO),
                'prior_temperature': 2.0,
                'prior_scope': 'ordinary skip and website-covered Ironclad reward cards; colorless/other actions remain in RL',
                'training_seed_base': TRAIN_SEED_BASE}
    if cycle_index is not None:
        settings.update(cycle_index=cycle_index, cycle_target_games=games,
                        cycle_training_seed_base=cycle_seed_base,
                        previous_rl_sha256=_sha(previous_path) if previous_path else None,
                        validation_search_stream='fixed independent RNG across cycles')
    progress = {'games': 0, 'baseline': None, 'best_floor': None, 'completed': 0,
                'truncated': 0, 'errors': 0}
    if resume:
        progress = base._restore(resume, model, optimizer, settings)
    else:
        progress['initialization'] = base._warm_start(str(init_path), model)
        if previous is not None:
            # Continue the RL optimizer and baseline, while accepting the
            # deliberately updated policy weights from this cycle's prior.
            optimizer.load_state_dict(previous['optimizer_state_dict'])
            progress['baseline'] = previous_progress.get('baseline')
            torch.set_rng_state(previous['torch_rng_state'])
            random.setstate(previous['python_rng_state'])
            np.random.set_state(previous['numpy_rng_state'])
            progress['previous_rl'] = {'path': str(previous_path), 'sha256': _sha(previous_path)}
        if cycle_index is not None:
            progress['cycle_index'] = cycle_index
            progress['cumulative_games'] = ((previous_progress.get('cumulative_games',
                                              previous_progress.get('games', 0)) if previous else 0))
    state = {'state': 'running', 'stage': 'training', 'games': progress['games'],
             'target_games': games, 'workers': workers, 'simulations_per_decision': simulations,
             'boss_simulations_per_decision': boss_simulations,
             'started_utc': datetime.now(timezone.utc).isoformat(), 'last_batch': None,
             'last_validation': None, 'active_episodes': []}
    _atomic_json(out / 'config.json', settings)

    def save():
        active = []
        for p in activity_dir.glob('worker-*.json'):
            try:
                active.append(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        state['active_episodes'] = active
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        _atomic_json(out / 'progress.json', state)

    def collect(pool, weight_path, version, seeds, deterministic):
        # All seeds are generated by parent RNG, independently of game seeds.
        # Use the same independent search seeds for every validation round;
        # these draws do not advance the training RNG.
        generator = None
        if deterministic:
            generator = torch.Generator().manual_seed(seed ^ 0x2A9D1123)
        samples = torch.randint(0, 2**31 - 1, (len(seeds),), generator=generator).tolist()
        searches = torch.randint(0, 2**31 - 1, (len(seeds),), generator=generator).tolist()
        tasks = [(s, sample, search, version, str(weight_path), deterministic,
                  simulations, boss_simulations, max_steps, str(activity_dir), combat_mode)
                 for s, sample, search in zip(seeds, samples, searches)]
        pending = {pool.submit(_play, task) for task in tasks}
        episodes = []
        while pending:
            done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
            for future in done:
                episodes.append(future.result())
            state['inflight_completed'] = len(episodes)
            state['inflight_total'] = len(tasks)
            save()
        return episodes

    save()
    try:
        with (out / 'metrics.jsonl').open('a', encoding='utf-8', buffering=1) as log:
            with tempfile.TemporaryDirectory(prefix='.armg-workers-', dir=out) as tmp:
                weights = Path(tmp) / 'weights.pt'
                with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
                    while progress['games'] < games:
                        state['stage'] = 'training'
                        remaining_to_eval = eval_every - progress['games'] % eval_every
                        count = min(batch_size, games - progress['games'], remaining_to_eval)
                        started = time.monotonic()
                        torch.save(model.state_dict(), weights)
                        version = progress['games']
                        seeds = [cycle_seed_base + version + i for i in range(count)]
                        eps = collect(pool, weights, version, seeds, False)
                        # Apply baseline in deterministic game-seed order.
                        eps.sort(key=lambda ep: ep['seed'])
                        weighted = []
                        for ep in eps:
                            reward = ep['floor'] / 50.0
                            old = progress['baseline']
                            progress['baseline'] = reward if old is None else 0.99 * old + 0.01 * reward
                            if ep['records']:
                                weighted.append((ep['records'], reward - progress['baseline']))
                        optimizer.zero_grad()
                        loss = None
                        prior_stats = None
                        if weighted:
                            loss = base.backward_weighted(model, weighted)
                            prior_stats = backward_prior(model, weighted, site_prior, prior_weight)
                            optimizer.step()
                        progress['games'] += count
                        progress['completed'] += count
                        if cycle_index is not None:
                            progress['cumulative_games'] += count
                        event = {'games': progress['games'], 'train': base.summarize(eps),
                                 'baseline': progress['baseline'], 'loss': loss, 'site_prior': prior_stats,
                                 'seconds': round(time.monotonic() - started, 3)}
                        for key in ('normal_decisions', 'boss_decisions', 'normal_simulations', 'boss_simulations'):
                            event['train'][key] = sum(ep[key] for ep in eps)
                        if progress['games'] % eval_every == 0 or progress['games'] == games:
                            state['stage'] = 'validation'
                            torch.save(model.state_dict(), weights)
                            val_seeds = [VALIDATION_SEED_BASE + i for i in range(eval_runs)]
                            validation = collect(pool, weights, progress['games'], val_seeds, True)
                            val = base.summarize(validation)
                            for key in ('normal_decisions', 'boss_decisions', 'normal_simulations', 'boss_simulations'):
                                val[key] = sum(ep[key] for ep in validation)
                            event['validation'] = val
                            state['last_validation'] = val
                            if val['completed'] == eval_runs and (progress['best_floor'] is None or
                                                                   val['mean_floor'] > progress['best_floor']):
                                progress['best_floor'] = val['mean_floor']
                                base._save(out / 'best.pt', model, optimizer, progress, settings)
                        base._save(out / 'latest.pt', model, optimizer, progress, settings)
                        log.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
                        print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)
                        state['games'], state['last_batch'] = progress['games'], event
                        save()
        state['state'], state['stage'] = 'completed', 'done'
        save()
        return 0
    except BaseException as exc:
        state['state'], state['stage'] = 'failed', 'failed'
        state['error'] = f'{type(exc).__name__}: {exc}'
        save()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--init-checkpoint', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--games', type=int, default=640)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--boss-simulations', type=int, default=10000)
    p.add_argument('--eval-every', type=int, default=640)
    p.add_argument('--eval-runs', type=int, default=50)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--lr', type=float, default=3e-4)
    p.add_argument('--prior-weight', type=float, default=0.05)
    p.add_argument('--resume')
    p.add_argument('--combat-mode', choices=('oracle', 'hidden'), default='oracle')
    p.add_argument('--cycle-index', type=int, help='zero-based cycle; reserves distinct game seeds')
    p.add_argument('--previous-rl', help='completed previous cycle RL checkpoint')
    return train(**vars(p.parse_args(argv)))


if __name__ == '__main__':
    raise SystemExit(main())
