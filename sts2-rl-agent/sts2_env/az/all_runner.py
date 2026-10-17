"""P3 all-content XS self-evolution: collect -> update -> evaluate, with evidence.

The runner is deliberately in-process and sequential: one frozen XS model plays
seeded arbitrary-deck fights against native monsters with dynamic search, the
resulting public transitions enter a versioned entity replay, and the network is
updated on search targets plus the terminal V7 utility.  Validation is always
network-only; the frozen test split is opened only when asked explicitly.
"""
from __future__ import annotations

from dataclasses import replace
import json
import time
from pathlib import Path

import numpy as np
import torch

from .all_decks import (FAMILY, generate_recipe, recipe_from_document)
from .config import EpisodeLimits, atomic_json
from .content import ALL_CONTENT
from .entity_replay import EntityReplayBuffer
from .entity_transition import collect_entity_episode
from .evaluation import evaluate, summarize
from .learner import Learner
from .model_factory import create_transformer, load_transformer_checkpoint, save_transformer_checkpoint
from .rewards import V7
from .self_play import CollectionJob

VERSION = 'az-all-xs-runner-v1'
SEARCH = 'dynamic-risk-puct-v2'
TIER = 'XS'
MAX_TRAINING_MASTER = 32
MAX_TRAINING_JOB = 16


def load_frozen_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if (config.get('version') != 'az-all-xs-v1' or config.get('content') != ALL_CONTENT
            or config.get('reward') != V7 or config.get('model', {}).get('tier') != TIER):
        raise ValueError('Runner requires the frozen az-all-xs-v1 config')
    if config.get('model', {}).get('reuse_previous_weights') is not False:
        raise ValueError('Frozen config must forbid reuse of earlier weights')
    return config


def fresh_model(config):
    torch.manual_seed(int(config.get('training', {}).get('init_seed', 0)))
    return create_transformer(TIER, ALL_CONTENT, V7).eval()


def training_recipes(iteration, episodes):
    return tuple(generate_recipe(iteration % MAX_TRAINING_MASTER, iteration,
                                 episode % MAX_TRAINING_JOB, 'train')
                 for episode in range(episodes))


def collect(model, recipes, *, iteration, budget, error_dir, limits, version, seed,
            failures=None):
    """Collect every recipe that the public contract can replay; record the rest."""
    episodes = []
    for job_id, recipe in enumerate(recipes):
        job = CollectionJob(
            job_id=f'{iteration:03d}-{job_id:02d}', iteration=iteration, master_seed=seed + job_id,
            scenario=recipe.to_dict(), checkpoint='', checkpoint_sha256='',
            model_version=version, error_dir=str(error_dir), simulations=budget, limits=limits,
            reward_version=V7, search_version=SEARCH)
        try:
            episodes.append(collect_entity_episode(job, model))
        except Exception as exc:  # noqa: BLE001 - a rejected recipe is recorded, not hidden
            if failures is None:
                raise
            failures.append(dict(scenario_id=recipe.scenario_id,
                                 encounter=recipe.encounter_id,
                                 error=f'{type(exc).__name__}: {exc}'))
    if not episodes:
        raise ValueError('Every collection episode was rejected by the public contract')
    return episodes


def update(model, replay, *, learning_rate, batch_size, updates, seed):
    learner = Learner(model, learning_rate=learning_rate)
    rng = np.random.default_rng(seed)
    history = []
    for _ in range(updates):
        samples, counts = replay.sample(batch_size, rng)
        history.append(dict(learner.update_entities(samples), family_counts=counts))
    return learner.model.eval(), history


def evaluate_recipes(model, recipes, *, version, error_dir, limits=None):
    """Network-only evaluation; contract-rejected episodes are counted, not hidden."""
    kept, rejected = [], []
    for recipe in recipes:
        try:
            kept.extend(evaluate(model, version, [recipe], simulations=0, policy='network',
                                 search_version=SEARCH, reward_version=V7,
                                 error_dir=str(error_dir), limits=limits or EpisodeLimits()))
        except Exception as exc:  # noqa: BLE001 - public contract rejection is evidence
            rejected.append(dict(scenario_id=recipe.scenario_id, encounter=recipe.encounter_id,
                                 error=f'{type(exc).__name__}: {exc}'))
    summary = summarize(kept) if kept else dict(episodes=0, win_rate=0.0, mean_utility=0.0)
    summary['contract_rejections'] = len(rejected)
    summary['contract_rejected'] = rejected
    return summary, kept


def protocol_recipes(protocol, split):
    return tuple(recipe_from_document(document) for document in protocol[split])


def _probe_recipe(recipe, limits):
    """Build and encode one recipe without acting; public contract only."""
    from .adapter import ObservableCombatAdapter
    from .entity_encoder import encode_entities
    env = ObservableCombatAdapter(recipe, reward_version=V7, limits=limits)
    encode_entities(env.information)
    return recipe


def preflight(config_path, protocol_path, *, iterations=1, episodes=2, max_turns=6,
              max_decisions=24, validation_limit=None):
    """Validate planned training and held-out recipes before any training run."""
    config = load_frozen_config(config_path)
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    limits = EpisodeLimits(max_turns=max_turns, max_decisions=max_decisions)
    training_ok, training_errors = 0, []
    for iteration in range(iterations):
        for recipe in training_recipes(iteration, episodes):
            try:
                _probe_recipe(recipe, limits)
                training_ok += 1
            except Exception as exc:  # noqa: BLE001 - preflight records rejections
                training_errors.append(dict(scenario_id=recipe.scenario_id,
                                            encounter=recipe.encounter_id,
                                            error=f'{type(exc).__name__}: {exc}'))
    validation = protocol_recipes(protocol, 'validation')
    if validation_limit is not None:
        validation = validation[:validation_limit]
    validation_ok, validation_errors = 0, []
    for recipe in validation:
        try:
            _probe_recipe(recipe, limits)
            validation_ok += 1
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(dict(scenario_id=recipe.scenario_id,
                                          encounter=recipe.encounter_id,
                                          error=f'{type(exc).__name__}: {exc}'))
    return dict(version=VERSION, config=str(config_path), protocol=str(protocol_path),
                training={'planned': iterations * episodes, 'ok': training_ok,
                          'errors': training_errors},
                validation={'checked': len(validation), 'ok': validation_ok,
                            'errors': validation_errors},
                ready=not training_errors and not validation_errors)


def paired_gain(baseline, candidate, *, seed=1729, samples=2000):
    """Descriptive paired bootstrap of the mean V7 utility gain.

    Episodes are paired by scenario id, so both evaluations must cover the same
    recipes. This is reporting only; no promotion decision is derived here.
    """
    old = {row['scenario_id']: row['reward'] for row in baseline}
    new = {row['scenario_id']: row['reward'] for row in candidate}
    if set(old) != set(new) or not old:
        raise ValueError('Paired comparison needs identical episode sets')
    gains = np.array([new[key] - old[key] for key in sorted(old)], dtype=float)
    rng = np.random.default_rng(seed)
    means = gains[rng.integers(0, len(gains), size=(samples, len(gains)))].mean(axis=1)
    return dict(episodes=int(len(gains)), mean_gain=float(gains.mean()),
                ci95=[float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
                probability_positive=float((means > 0).mean()))


def run(config_path, protocol_path, out_dir, *, iterations=1, episodes=2, updates=1, budget=4,
        batch_size=16, learning_rate=None, seed=0, max_turns=6, max_decisions=24,
        include_test=False, resume=False, compare_baseline=True, log=print):
    config = load_frozen_config(config_path)
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    training = config['training']
    learning_rate = float(learning_rate or training['learning_rate'])
    limits = EpisodeLimits(max_turns=max_turns, max_decisions=max_decisions)
    version = f'{VERSION}-{seed}'
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    history = []
    start_iteration = 0
    baseline_summary, baseline_rows = None, []
    if resume and (out / 'report.json').exists():
        previous = json.loads((out / 'report.json').read_text(encoding='utf-8'))
        if previous.get('version') != VERSION:
            raise ValueError('Cannot resume a report from another runner version')
        history = previous['history']
        start_iteration = len(history)
        checkpoint = out / history[-1]['checkpoint']
        model, _ = load_transformer_checkpoint(checkpoint, TIER, ALL_CONTENT, V7)
        baseline_summary = previous.get('baseline')
        log(f'resume from iteration {start_iteration} ({checkpoint.name})')
    else:
        model = fresh_model(config)
    replay = EntityReplayBuffer(out / 'replay', capacity=50_000, content_version=ALL_CONTENT,
                                reward_version=V7)
    validation = protocol_recipes(protocol, 'validation')
    if baseline_summary is None and compare_baseline:
        # Frozen reference for relative reporting: the initial (unupdated) model.
        baseline_summary, baseline_rows = evaluate_recipes(
            fresh_model(config), validation, version=f'{version}-baseline',
            error_dir=out / 'errors', limits=limits)
        log(f"baseline: mean utility {baseline_summary['mean_utility']:.3f} "
            f"rejections {baseline_summary['contract_rejections']}")
    for iteration in range(start_iteration, iterations):
        started = time.perf_counter()
        recipes = training_recipes(iteration, episodes)
        failures = []
        collected = collect(model, recipes, iteration=iteration, budget=budget,
                            error_dir=out / 'errors', limits=limits, version=version,
                            seed=seed * 100_000 + iteration * 1_000, failures=failures)
        for episode in collected:
            replay.commit(episode)
        collected_at = time.perf_counter()
        model, update_history = update(model, replay, learning_rate=learning_rate,
                                       batch_size=batch_size, updates=updates,
                                       seed=seed * 1_000 + iteration)
        updated_at = time.perf_counter()
        validation_summary, validation_rows = evaluate_recipes(
            model, validation, version=version, error_dir=out / 'errors', limits=limits)
        evaluated_at = time.perf_counter()
        checkpoint = out / f'iteration-{iteration:03d}.pt'
        save_transformer_checkpoint(checkpoint, model, f'{version}-iter{iteration:03d}',
                                    config=config, statistics=validation_summary,
                                    iteration=iteration)
        comparison = None
        if compare_baseline and baseline_rows:
            common = {row['scenario_id'] for row in validation_rows}
            if all(row['scenario_id'] in common for row in baseline_rows):
                comparison = paired_gain(baseline_rows, validation_rows)
        record = dict(version=VERSION, iteration=iteration,
                      episodes=[episode['episode_id'] for episode in collected],
                      outcomes=[episode['outcome']['termination_reason'] for episode in collected],
                      replay_size=replay.size, updates=update_history,
                      rejected_recipes=failures,
                      seconds=dict(collect=round(collected_at - started, 3),
                                   update=round(updated_at - collected_at, 3),
                                   evaluate=round(evaluated_at - updated_at, 3),
                                   total=round(evaluated_at - started, 3)),
                      paired_vs_baseline=comparison,
                      validation=validation_summary, checkpoint=checkpoint.name)
        atomic_json(out / f'iteration-{iteration:03d}.json', record)
        history.append(record)
        log(f"iteration {iteration}: mean utility {validation_summary['mean_utility']:.3f} "
            f"win {validation_summary['win_rate']:.3f} replay {replay.size}")
    if not history:
        raise ValueError('No iteration completed')
    report = dict(version=VERSION, config=str(config_path), protocol=str(protocol_path),
                  iteration_budget=dict(iterations=iterations, episodes=episodes,
                                        updates=updates, budget=budget, batch_size=batch_size),
                  baseline=baseline_summary, history=history,
                  final_validation=history[-1]['validation'])
    if include_test:
        test = protocol_recipes(protocol, 'test')
        summary, _ = evaluate_recipes(model, test, version=version, error_dir=out / 'errors',
                                      limits=limits)
        report['test'] = summary
    atomic_json(out / 'report.json', report)
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='P3 all-content XS self-play runner')
    parser.add_argument('--config', default='configs/az_all_xs_v1/config.json')
    parser.add_argument('--protocol', default='configs/az_all_xs_v1/protocol.json')
    parser.add_argument('--out', default='output/az_all_xs_run')
    parser.add_argument('--iterations', type=int, default=1)
    parser.add_argument('--episodes', type=int, default=2)
    parser.add_argument('--updates', type=int, default=1)
    parser.add_argument('--budget', type=int, default=4)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--max-turns', type=int, default=6)
    parser.add_argument('--max-decisions', type=int, default=24)
    parser.add_argument('--include-test', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--no-baseline', action='store_true')
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args(argv)
    if args.preflight_only:
        result = preflight(args.config, args.protocol, iterations=args.iterations,
                           episodes=args.episodes, max_turns=args.max_turns,
                           max_decisions=args.max_decisions)
    else:
        result = run(args.config, args.protocol, args.out, iterations=args.iterations,
                     episodes=args.episodes, updates=args.updates, budget=args.budget,
                     batch_size=args.batch_size, seed=args.seed, max_turns=args.max_turns,
                     max_decisions=args.max_decisions, include_test=args.include_test,
                     resume=args.resume, compare_baseline=not args.no_baseline)
        result = {key: result[key] for key in ('version', 'history', 'final_validation')}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()




