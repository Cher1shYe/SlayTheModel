"""Train a fresh A10 ArmG with boss rewards, decaying website prior and REINFORCE with floor-dependent pure MCTS and card-skip prior.

Load the exact extension specified by STS2_PRIOR_PYD before importing agent
modules. Each battle decision executes one action and uses its configured
floor-dependent simulation budget, including Boss fights. All nonterminated
episodes abort the batch. This module never runs training when imported.
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
from agent.armg import ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM, ArmGScorer
from agent.nets import checkpoint_config
from agent.armg_floor_schedule import FloorMctsController, FloorCardSkipPrior, combat_budget
from agent.armg_site_prior_loss import backward_prior
from deployment.train_armg_floor_prior_rl import _supports_potion_weight


def prior_strength(completed_games):
    return 0.2 * max(0.0, 1.0 - completed_games / 10000.0)


def episode_reward(ep, reward_mode='floor-boss-elite'):
    if ep['status'] != 'terminated':
        raise ValueError('only completed episodes have a reward')
    wins = ep['boss_wins']
    if reward_mode in ('floor-boss-elite', 'floor20-boss-elite01', 'floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
        return sum(reward_components(ep, reward_mode).values())
    if reward_mode == 'boss-count':
        return float(len(wins))
    if reward_mode == 'act-count':
        return float(sum(w['act'] < 3 or w['final_boss'] for w in wins))
    raise ValueError('unknown reward mode')


def reward_components(ep, reward_mode='floor-boss-elite'):
    n = len(ep['boss_wins'])
    if not 0 <= n <= 4 or any(w['act'] not in (1, 2, 3) for w in ep['elite_wins']):
        raise ValueError('invalid boss/elite victory events')
    if reward_mode not in ('floor-boss-elite', 'floor20-boss-elite01', 'floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
        raise ValueError('unsupported reward components')
    flat = reward_mode in ('floor20-boss-elite01', 'floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo')
    parts = {'floor_reward': ep['floor'] / (20.0 if flat else 50.0),
            'boss_bonus': n * (n + 1) / 2.0,
            'elite_bonus': 0.1 * len(ep['elite_wins']) if flat else sum(0.15 * w['act'] for w in ep['elite_wins'])}

    if reward_mode in ('floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
        parts.update(upgrade_bonus=.05 * ep['campfire_upgrades'], removal_bonus=.02 * ep['shop_removals'])
    if reward_mode.endswith('-elo'):
        parts['deck_elo_bonus'] = ep['deck_elo_bonus']
    return parts


def reward_summary(episodes, reward_mode):
    values = [episode_reward(ep, reward_mode) for ep in episodes]
    result = {'mean_reward': float(np.mean(values)), 'reward_mode': reward_mode}
    if reward_mode in ('floor-boss-elite', 'floor20-boss-elite01', 'floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
        parts = [reward_components(ep, reward_mode) for ep in episodes]
        result.update({f'mean_{key}': float(np.mean([p[key] for p in parts]))
                       for key in parts[0]})
        if reward_mode in ('floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
            result['campfire_upgrades'] = sum(ep['campfire_upgrades'] for ep in episodes)
            result['shop_removals'] = sum(ep['shop_removals'] for ep in episodes)
    if reward_mode.endswith('-elo'):
        result['mean_deck_elo'] = float(np.mean([ep['deck_mean_elo'] for ep in episodes]))
        result['deck_elo_missing_cards'] = sum(ep['deck_elo_missing_cards'] for ep in episodes)
    elif reward_mode not in ('floor-boss-elite', 'floor20-boss-elite01', 'floor20-boss-elite01-actions'):
        result['reward_counts'] = {str(i): values.count(float(i)) for i in range(5)}
    return result

TRAIN_SEED_BASE = 10_400_000
VALIDATION_SEED_BASE = 20_400_000
# Reserve independent environment seeds for each round. The prior collector
# uses a separate range.
CYCLE_SEED_STRIDE = 10_000
_worker_model = None
_worker_version = None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_json(path, data, *, strict=False):
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
        if strict:
            raise


def _play(task):
    global _worker_model, _worker_version
    game_seed, sampling_seed, search_seed, version, weight_path, deterministic, simulations, floor_increment, elite_bonus, boss_bonus, max_steps, activity_dir, combat_mode, ascension = task
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

    controller = FloorMctsController(search_seed, activity, simulations, floor_increment, elite_bonus, boss_bonus)
    original = base._mcts_plan
    base._mcts_plan = controller.plan
    try:
        activity(controller, force=True)
        episode = base.collect_episode(game_seed, _worker_model, deterministic=deterministic,
                                       combat='mcts-oracle' if combat_mode == 'oracle' else 'mcts-resampled', simulations=simulations,
                                       epsilon=0.05, max_steps=max_steps, ascension=ascension, track_boss_wins=True, track_elite_wins=True,
                                       need_rules=False, relic_rules=False,
                                       combat_budget_by_context=controller.budget_for_context,
                                       before_combat=controller.prepare_combat)
        if episode['status'] != 'terminated':
            raise RuntimeError(f"episode {game_seed} {episode['status']}: {episode.get('error')}")
        expected = sum(combat_budget(floor, simulations, floor_increment, elite=elite, boss=boss,
                                     elite_bonus=elite_bonus, boss_bonus=boss_bonus) * count
                       for (floor, elite, boss), count in controller.floor_decisions.items())
        if episode['mcts_searches'] != controller.decisions or episode['mcts_simulations'] != expected:
            raise RuntimeError(f"episode {game_seed} has an incomplete MCTS budget")
        episode['normal_decisions'] = controller.normal_decisions
        episode['boss_decisions'] = controller.boss_decisions
        episode['normal_simulations'] = controller.normal_simulations
        episode['boss_simulations'] = controller.boss_simulations_completed
        episode['elite_decisions'] = controller.elite_decisions
        episode['elite_simulations'] = controller.elite_simulations
        return episode
    finally:
        base._mcts_plan = original
        try:
            activity_path.unlink(missing_ok=True)
        except OSError:
            pass


def train(*, out_dir, data_dir, games=10000, batch_size=32, workers=8,
          simulations=5000, floor_increment=500, elite_bonus=5000, boss_bonus=10000,
          eval_every=640, eval_runs=50, max_steps=5000,
          seed=20261030, lr=3e-4, resume=None, combat_mode='oracle',
          training_seed_base=TRAIN_SEED_BASE, ascension=10, reward_mode='floor-boss-elite'):
    if min(games, batch_size, workers, simulations, eval_every, eval_runs, max_steps) < 1 or min(floor_increment, elite_bonus, boss_bonus) < 0 or lr <= 0:
        raise ValueError('training parameters must be positive')
    if combat_mode != 'oracle':
        raise ValueError('this run requires oracle mode')
    if ascension != 10 or reward_mode not in ('boss-count', 'act-count', 'floor-boss-elite', 'floor20-boss-elite01'):
        raise ValueError('A10 and a supported boss reward mode are required')
    if games > CYCLE_SEED_STRIDE:
        raise ValueError('training game count exceeds reserved seed range')
    if training_seed_base < 0:
        raise ValueError('training seed base must be nonnegative')
    cycle_seed_base = training_seed_base
    if not extension_loader._extension:
        raise RuntimeError('set STS2_PRIOR_PYD to the isolated MCTS extension')
    if not _supports_potion_weight():
        raise RuntimeError('the selected MCTS extension does not support final-boss potion_weight')
    extension_path = Path(extension_loader._extension).resolve(strict=True)
    data_path = Path(data_dir).resolve(strict=True)
    manifest = data_path / 'manifest.json'
    manifest_data = json.loads(manifest.read_text(encoding='utf-8'))
    for name in ('cards', 'relics', 'potions', 'community'):
        if _sha(data_path / (name + '.json')) != manifest_data['snapshots'][name]['sha256']:
            raise ValueError(f'website snapshot hash mismatch: {name}')
    if cycle_seed_base < VALIDATION_SEED_BASE + eval_runs and VALIDATION_SEED_BASE < cycle_seed_base + games:
        raise ValueError('training and validation seeds overlap')
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
    site_prior = FloorCardSkipPrior(snapshot_dir)
    activity_dir = out / 'active'
    activity_dir.mkdir(exist_ok=True)
    torch.set_num_threads(1)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = ArmGScorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    settings = {'combat': 'mcts-oracle', 'combat_policy_prior': False,
                'mcts_c': 3.0 * 2.0**0.5,
                'reward_formula': reward_mode, 'reward_mode': reward_mode,
                'information': combat_mode, 'simulations': simulations, 'epsilon': 0.05,
                'max_steps': max_steps, 'ascension': ascension, 'seed': seed, 'batch_size': batch_size,
                'eval_every': eval_every, 'eval_runs': eval_runs, 'lr': lr,
                'train_seed_offset': cycle_seed_base - 10_000_000,
                'need_rules': False, 'relic_rules': False, 'workers': workers,
                'combat_budget_start': simulations, 'combat_budget_per_floor': floor_increment,
                'combat_budget_elite_bonus': elite_bonus, 'combat_budget_boss_bonus': boss_bonus,
                'combat_budget_formula': 'start + increment * (max(floor, 1) - 1) + room bonus',
                'final_boss_potion_weight': 0.0,
                'other_battle_potion_weight': 4.0,
                'root_action': 'best winning rollout else most visited' if combat_mode == 'oracle' else 'most visited',
                'path_cache': 'none',
                'search_rng': 'independent per-episode RNG, not derived from game seed',
                'simulator_sha256': _sha(extension_path), 'initialization': 'random',
                'validation_seed_base': VALIDATION_SEED_BASE,
                'website_manifest_sha256': _sha(manifest), 'website_data_dir': str(data_path),
                'website_snapshot_dir': str(snapshot_dir),
                'prior_weight_formula': '0.2 * max(0, 1 - completed_training_games / 10000)',
                'prior_schedule_step': 'completed games before batch update',
                'best_selection': 'mean_floor (unchanged)',
                'skip_elo_start': 1350, 'skip_elo_per_floor': 10,
                'skip_elo_formula': '1350 + 10 * (max(floor, 1) - 1)',
                'prior_temperature': 2.0,
                'prior_scope': 'ordinary skip and website-covered Ironclad reward cards; colorless/other actions remain in RL',
                'training_seed_base': cycle_seed_base, 'target_games': games}
    progress = {'games': 0, 'baseline': None, 'best_floor': None, 'floor_sum': 0,
                'completed': 0, 'truncated': 0, 'errors': 0,
                'initialization': {'mode': 'random', 'seed': seed}}
    if resume:
        progress = base._restore(resume, model, optimizer, settings)
    else:
        base._save(out / 'initial.pt', model, optimizer, progress, settings)
        base._save(out / 'latest.pt', model, optimizer, progress, settings)
    state = {'state': 'running', 'stage': 'training', 'games': progress['games'],
             'target_games': games, 'workers': workers,
             'combat_budget_start': simulations, 'combat_budget_per_floor': floor_increment,
             'combat_budget_elite_bonus': elite_bonus, 'combat_budget_boss_bonus': boss_bonus,
             'combat_budget_formula': 'start + increment * (max(floor, 1) - 1) + room bonus',
             'started_utc': datetime.now(timezone.utc).isoformat(), 'last_batch': None,
             'mean_floor': (progress.get('floor_sum', 0) / progress['games'] if progress['games'] else None),
             'last_validation': None, 'active_episodes': []}
    _atomic_json(out / 'config.json', settings, strict=True)

    def save():
        active = []
        for p in activity_dir.glob('worker-*.json'):
            try:
                active.append(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        state['active_episodes'] = active
        state['ascension'] = ascension
        state['reward_mode'] = reward_mode
        if progress.get('reward_changes'):
            state['reward_changed_at_games'] = progress['reward_changes'][-1]['at_games']
        if progress.get('combat_changes'):
            state['combat_changed_at_games'] = progress['combat_changes'][-1]['at_games']
        state['next_prior_weight'] = prior_strength(progress['games'])
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
                  simulations, floor_increment, elite_bonus, boss_bonus, max_steps, str(activity_dir), combat_mode, ascension)
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
                            reward = episode_reward(ep, reward_mode)
                            old = progress['baseline']
                            progress['baseline'] = reward if old is None else 0.99 * old + 0.01 * reward
                            if ep['records']:
                                weighted.append((ep['records'], reward - progress['baseline']))
                        optimizer.zero_grad()
                        loss = None
                        prior_stats = None
                        if weighted:
                            loss = base.backward_weighted(model, weighted)
                            prior_stats = backward_prior(model, weighted, site_prior, prior_strength(progress['games']))
                            optimizer.step()
                        progress['games'] += count
                        progress['completed'] += count
                        progress['floor_sum'] += sum(ep['floor'] for ep in eps)
                        state['mean_floor'] = progress['floor_sum'] / progress['games']
                        event = {'games': progress['games'], 'train': base.summarize(eps),
                                 'baseline': progress['baseline'], 'loss': loss, 'site_prior': prior_stats,
                                 'seconds': round(time.monotonic() - started, 3)}
                        event['train'].update(reward_summary(eps, reward_mode))
                        for key in ('normal_decisions', 'boss_decisions', 'normal_simulations', 'boss_simulations', 'elite_decisions', 'elite_simulations'):
                            event['train'][key] = sum(ep[key] for ep in eps)
                        if progress['games'] % eval_every == 0 or progress['games'] == games:
                            state['stage'] = 'validation'
                            torch.save(model.state_dict(), weights)
                            val_seeds = [VALIDATION_SEED_BASE + i for i in range(eval_runs)]
                            validation = collect(pool, weights, progress['games'], val_seeds, True)
                            val = base.summarize(validation)
                            val.update(reward_summary(validation, reward_mode))
                            for key in ('normal_decisions', 'boss_decisions', 'normal_simulations', 'boss_simulations', 'elite_decisions', 'elite_simulations'):
                                val[key] = sum(ep[key] for ep in validation)
                            event['validation'] = val
                            state['last_validation'] = val
                            if val['completed'] == eval_runs and (progress['best_floor'] is None or
                                                                   val['mean_floor'] > progress['best_floor']):
                                progress['best_floor'] = val['mean_floor']
                                base._save(out / 'best.pt', model, optimizer, progress, settings)
                        base._save(out / 'latest.pt', model, optimizer, progress, settings)
                        with (out / 'episodes.jsonl').open('a', encoding='utf-8') as episode_log:
                            for ep in eps:
                                row = {k: v for k, v in ep.items() if k != 'records'}
                                row.update(batch_end=progress['games'], reward=episode_reward(ep, reward_mode), reward_mode=reward_mode)
                                if reward_mode in ('floor-boss-elite', 'floor20-boss-elite01', 'floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
                                    row.update(reward_components(ep, reward_mode))
                                episode_log.write(json.dumps(row, allow_nan=False) + '\n')
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
    p.add_argument('--out-dir', required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--games', type=int, default=10000)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=5000, help='floor 1 MCTS simulations')
    p.add_argument('--floor-increment', type=int, default=500, help='MCTS increment per floor (applies to all battles)')
    p.add_argument('--elite-bonus', type=int, default=5000, help='extra simulations for elite combat')
    p.add_argument('--boss-bonus', type=int, default=10000, help='extra simulations for Boss combat')
    p.add_argument('--eval-every', type=int, default=640)
    p.add_argument('--eval-runs', type=int, default=50)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--lr', type=float, default=3e-4)
    p.add_argument('--ascension', type=int, default=10)
    p.add_argument('--reward-mode', choices=('boss-count', 'act-count', 'floor-boss-elite', 'floor20-boss-elite01'), default='floor-boss-elite')
    p.add_argument('--training-seed-base', type=int, default=TRAIN_SEED_BASE)
    p.add_argument('--resume')
    p.add_argument('--combat-mode', choices=('oracle',), default='oracle')
    return train(**vars(p.parse_args(argv)))


if __name__ == '__main__':
    raise SystemExit(main())
