"""Compare a later-round prior model with its preceding RL model.

Uses paired games, a common independent search stream and the same pure MCTS
oracle settings as training. Any failed or truncated episode fails the guard.
Set STS2_PRIOR_PYD to the same isolated simulator used by the checkpoints.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import time

import numpy as np
import torch

from deployment import evaluate_battle_root_prior as extension_loader
from deployment import train_armg_hidden_mcts as rl
from agent.armg import ArmGScorer
from agent import armg_train as base

ARMS = ('previous', 'prior')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paired_summary(records, *, iterations=20_000, bootstrap_seed=20261030):
    """Paired percentile bootstrap; only completed seed pairs are included."""
    groups = {arm: {} for arm in ARMS}
    for row in records:
        arm, seed = row['arm'], int(row['seed'])
        if arm not in groups or seed in groups[arm]:
            raise ValueError('unexpected arm or duplicate seed')
        groups[arm][seed] = row
    ids = sorted(set(groups['previous']) & set(groups['prior']))
    ids = [s for s in ids if groups['previous'][s]['status'] == groups['prior'][s]['status'] == 'terminated']
    differences = np.asarray([groups['prior'][s]['floor'] - groups['previous'][s]['floor'] for s in ids], dtype=np.float64)
    mean = float(differences.mean()) if len(differences) else None
    se = float(differences.std(ddof=1)/math.sqrt(len(differences))) if len(differences) > 1 else None
    ci = None
    if len(differences) >= 2:
        rng = np.random.default_rng(bootstrap_seed)
        draws = np.empty(iterations, dtype=np.float64)
        for start in range(0, iterations, 1000):
            size = min(1000, iterations-start)
            draws[start:start+size] = differences[rng.integers(0, len(differences), size=(size, len(differences)))].mean(axis=1)
        ci = [float(x) for x in np.quantile(draws, [0.025, 0.975])]
    return {'complete_pairs': len(ids), 'mean_floor_difference': mean,
            'floor_difference_se': se, 'ci_95': ci,
            'ci_method': 'paired bootstrap percentile',
            'bootstrap_iterations': iterations, 'bootstrap_seed': bootstrap_seed,
            'rollback': bool(ci is not None and mean < -1.0 and ci[1] < 0.0),
            'prior_only_wins': sum(groups['prior'][s].get('won', False) and not groups['previous'][s].get('won', False) for s in ids),
            'previous_only_wins': sum(groups['previous'][s].get('won', False) and not groups['prior'][s].get('won', False) for s in ids)}


def run(prior, previous_rl, out_dir, *, games=50, workers=8, simulations=2000,
        boss_simulations=10000, max_steps=5000, combat_mode='oracle'):
    if min(games, workers, simulations, boss_simulations, max_steps) < 1 or games < 2:
        raise ValueError('guard needs at least two games and positive settings')
    if combat_mode not in ('oracle', 'hidden') or not extension_loader._extension:
        raise ValueError('guard needs a matching isolated simulator and combat mode')
    extension = Path(extension_loader._extension).resolve(strict=True)
    prior = Path(prior).resolve(strict=True)
    previous_rl = Path(previous_rl).resolve(strict=True)
    p, old = (torch.load(x, map_location='cpu', weights_only=False) for x in (prior, previous_rl))
    pp, ps, old_settings = p.get('progress', {}), p.get('settings', {}), old.get('settings', {})
    if (pp.get('stage') != 'prior_complete' or pp.get('initialization') != 'current_model'
        or pp.get('source_rl_sha256') != _sha(previous_rl)
        or ps.get('information') != combat_mode or ps.get('simulations_per_decision') != simulations
        or ps.get('boss_simulations_per_decision') != boss_simulations or ps.get('path_cache') != 'none'
        or ps.get('simulator_sha256') != _sha(extension)
        or old_settings.get('information') != combat_mode or old_settings.get('simulations') != simulations
        or old_settings.get('boss_simulations_per_decision') != boss_simulations
        or old_settings.get('path_cache') != 'none' or old_settings.get('simulator_sha256') != _sha(extension)
        or old_settings.get('max_steps') != max_steps):
        raise ValueError('prior, previous RL or evaluation settings do not match')
    # Load through the checked schema, not just an arbitrary state dictionary.
    model = ArmGScorer()
    base._warm_start(str(prior), model)
    # state_dict tensors refer to model storage; clone before reusing the model.
    prior_weights = {key: value.detach().clone() for key, value in model.state_dict().items()}
    base._warm_start(str(previous_rl), model)
    previous_weights = {key: value.detach().clone() for key, value in model.state_dict().items()}
    del model, p, old
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    active = out/'active'
    active.mkdir()
    weight_paths = {arm: out/(arm+'_policy.pt') for arm in ARMS}
    torch.save(prior_weights, weight_paths['prior'])
    torch.save(previous_weights, weight_paths['previous'])
    del prior_weights, previous_weights
    seed = int(old_settings.get('seed', 20261030))
    validation_base = int(old_settings.get('validation_seed_base', rl.VALIDATION_SEED_BASE))
    generator = torch.Generator().manual_seed(seed ^ 0x2A9D1123)
    sampling_seeds = torch.randint(0, 2**31-1, (games,), generator=generator).tolist()
    search_seeds = torch.randint(0, 2**31-1, (games,), generator=generator).tolist()
    config = {'prior': str(prior), 'prior_sha256': _sha(prior),
              'previous_rl': str(previous_rl), 'previous_rl_sha256': _sha(previous_rl),
              'simulator': str(extension), 'simulator_sha256': _sha(extension),
              'games_per_arm': games, 'workers': workers, 'validation_seed_base': validation_base,
              'search_stream_seed': seed, 'independent_search_rng': True,
              'simulations_per_decision': simulations, 'boss_simulations_per_decision': boss_simulations,
              'combat_mode': combat_mode, 'path_cache': 'none', 'max_steps': max_steps,
              'started_utc': datetime.now(timezone.utc).isoformat()}
    (out/'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    records, started = [], time.perf_counter()

    def save(state, error=None):
        activities = []
        for path in active.glob('worker-*.json'):
            try:
                activities.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                pass
        progress = {'state': state, 'completed_jobs': len(records), 'total_jobs': 2*games,
                    'updated_utc': datetime.now(timezone.utc).isoformat(), 'elapsed_seconds': time.perf_counter()-started,
                    'active_episodes': activities, 'guard': paired_summary(records)}
        if error:
            progress['error'] = error
        rl._atomic_json(out/'progress.json', progress)
        return progress

    save('running')
    try:
        with (out/'episodes.jsonl').open('x', encoding='utf-8') as output:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
                tasks = {}
                for i in range(games):
                    for version, arm in enumerate(ARMS):
                        task = (validation_base+i, sampling_seeds[i], search_seeds[i], version,
                                str(weight_paths[arm]), True, simulations, boss_simulations, max_steps,
                                str(active), combat_mode)
                        tasks[pool.submit(rl._play, task)] = (validation_base+i, arm)
                pending = set(tasks)
                while pending:
                    done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                    for future in done:
                        game_seed, arm = tasks[future]
                        try:
                            record = dict(future.result())
                            record.pop('records', None)
                            record['arm'] = arm
                        except Exception as exc:
                            record = {'seed': game_seed, 'arm': arm, 'status': 'error',
                                      'error': f'{type(exc).__name__}: {exc}'}
                        records.append(record)
                        output.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
                        output.flush()
                    save('running')
        guard = paired_summary(records)
        if len(records) != 2*games or guard['complete_pairs'] != games:
            raise RuntimeError('guard has failed or incomplete episodes; RL not started')
        summary = {'state': 'completed', 'config': config, 'guard': guard,
                   'arms': {arm: base.summarize([x for x in records if x['arm'] == arm]) for arm in ARMS},
                   'episodes_path': str((out/'episodes.jsonl').resolve())}
        (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        save('completed')
        return summary
    except BaseException as exc:
        save('failed', f'{type(exc).__name__}: {exc}')
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prior', required=True)
    p.add_argument('--previous-rl', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--games', type=int, default=50)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--boss-simulations', type=int, default=10000)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--combat-mode', choices=('oracle', 'hidden'), default='oracle')
    args = vars(p.parse_args(argv))
    result = run(**args)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
