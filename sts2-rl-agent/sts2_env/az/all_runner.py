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
from .model_factory import (create_transformer, save_transformer_checkpoint)
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


def run(config_path, protocol_path, out_dir, *, iterations=1, episodes=2, updates=1, budget=4,
        batch_size=16, learning_rate=None, seed=0, max_turns=6, max_decisions=24,
        include_test=False, log=print):
    config = load_frozen_config(config_path)
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    training = config['training']
    learning_rate = float(learning_rate or training['learning_rate'])
    limits = EpisodeLimits(max_turns=max_turns, max_decisions=max_decisions)
    version = f'{VERSION}-{seed}'
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = fresh_model(config)
    replay = EntityReplayBuffer(out / 'replay', capacity=50_000, content_version=ALL_CONTENT,
                                reward_version=V7)
    validation = protocol_recipes(protocol, 'validation')
    history = []
    for iteration in range(iterations):
        recipes = training_recipes(iteration, episodes)
        failures = []
        collected = collect(model, recipes, iteration=iteration, budget=budget,
                            error_dir=out / 'errors', limits=limits, version=version,
                            seed=seed * 100_000 + iteration * 1_000, failures=failures)
        for episode in collected:
            replay.commit(episode)
        model, update_history = update(model, replay, learning_rate=learning_rate,
                                       batch_size=batch_size, updates=updates,
                                       seed=seed * 1_000 + iteration)
        validation_summary, _ = evaluate_recipes(model, validation, version=version,
                                                 error_dir=out / 'errors', limits=limits)
        checkpoint = out / f'iteration-{iteration:03d}.pt'
        save_transformer_checkpoint(checkpoint, model, f'{version}-iter{iteration:03d}',
                                    config=config, statistics=validation_summary,
                                    iteration=iteration)
        record = dict(version=VERSION, iteration=iteration,
                      episodes=[episode['episode_id'] for episode in collected],
                      outcomes=[episode['outcome']['termination_reason'] for episode in collected],
                      replay_size=replay.size, updates=update_history,
                      rejected_recipes=failures,
                      validation=validation_summary, checkpoint=checkpoint.name)
        atomic_json(out / f'iteration-{iteration:03d}.json', record)
        history.append(record)
        log(f"iteration {iteration}: mean utility {validation_summary['mean_utility']:.3f} "
            f"win {validation_summary['win_rate']:.3f} replay {replay.size}")
    report = dict(version=VERSION, config=str(config_path), protocol=str(protocol_path),
                  iteration_budget=dict(iterations=iterations, episodes=episodes,
                                        updates=updates, budget=budget, batch_size=batch_size),
                  history=history, final_validation=history[-1]['validation'])
    if include_test:
        test = protocol_recipes(protocol, 'test')
        summary, _ = evaluate_recipes(model, test, version=version, error_dir=out / 'errors',
                                      limits=limits)
        report['test'] = summary
    atomic_json(out / 'report.json', report)
    return report


