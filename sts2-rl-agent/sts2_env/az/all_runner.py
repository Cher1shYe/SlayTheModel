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
from .config import EpisodeLimits, RULES_VERSION, atomic_json
from .content import ALL_CONTENT
from .entity_replay import EntityReplayBuffer
from .entity_transition import collect_entity_episode
from .evaluation import evaluate, summarize
from .learner import Learner
from .model_factory import create_transformer, load_transformer_checkpoint, save_transformer_checkpoint
from .rewards import V7
from .self_play import CollectionJob

VERSION = 'az-all-xs-runner-v3'
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


def fresh_model(config, seed=None):
    torch.manual_seed(int(config.get('training', {}).get('init_seed', 0) if seed is None else seed))
    return create_transformer(TIER, ALL_CONTENT, V7).eval()


def training_recipes(iteration, episodes):
    # MAX_TRAINING_JOB recipes exist per master; offset the master once an
    # iteration asks for more episodes than that so every episode is distinct.
    return tuple(generate_recipe((iteration + 8 * (episode // MAX_TRAINING_JOB))
                                 % MAX_TRAINING_MASTER, iteration,
                                 episode % MAX_TRAINING_JOB, 'train')
                 for episode in range(episodes))


def collect(model, recipes, *, iteration, budget, error_dir, limits, version, seed,
            failures=None, workers=1, collector=None):
    """Collect every recipe that the public contract can replay; record the rest.

    ``workers > 1`` freezes the current weights to a temporary checkpoint and
    runs the entity collection in spawned processes (each worker loads the same
    frozen weights); a failed chunk falls back to sequential collection so one
    rejected recipe never hides the others.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError('Positive worker count required')
    if workers > 1 and len(recipes) > 1:
        return _collect_parallel(model, recipes, iteration=iteration, budget=budget,
                                 error_dir=error_dir, limits=limits, version=version,
                                 seed=seed, failures=failures, workers=workers,
                                 collector=collector)
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


def _collect_parallel(model, recipes, *, iteration, budget, error_dir, limits, version, seed,
                      failures, workers, collector=None):
    import hashlib
    from .self_play import Collector, collect_episode

    checkpoint = Path(error_dir).parent / f'collect-{iteration:03d}.pt'
    save_transformer_checkpoint(checkpoint, model, version)
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    jobs = [CollectionJob(
        job_id=f'{iteration:03d}-{job_id:02d}', iteration=iteration, master_seed=seed + job_id,
        scenario=recipe.to_dict(), checkpoint=str(checkpoint), checkpoint_sha256=digest,
        model_version=version, error_dir=str(error_dir), simulations=budget, limits=limits,
        reward_version=V7, search_version=SEARCH)
        for job_id, recipe in enumerate(recipes)]
    episodes = []

    def drain(collector):
        for start in range(0, len(jobs), workers):
            chunk = jobs[start:start + workers]
            try:
                episodes.extend(collector.collect(chunk))
                continue
            except Exception:  # noqa: BLE001 - one bad worker result, retry sequentially
                pass
            for job, recipe in zip(chunk, recipes[start:start + workers]):
                try:
                    episodes.append(collect_episode(job))
                except Exception as exc:  # noqa: BLE001
                    if failures is None:
                        raise
                    failures.append(dict(scenario_id=recipe.scenario_id,
                                         encounter=recipe.encounter_id,
                                         error=f'{type(exc).__name__}: {exc}'))

    if collector is None:
        with Collector(workers) as owned:
            drain(owned)
    else:
        drain(collector)
    if not episodes:
        raise ValueError('Every collection episode was rejected by the public contract')
    return episodes


def update(model, replay, *, learning_rate, batch_size, updates, seed,
           value_weight=1.0, resume_state=None, on_update=None):
    learner = Learner(model, learning_rate=learning_rate, value_weight=value_weight)
    rng = np.random.default_rng(seed)
    history = []
    if resume_state is not None:
        learner.optimizer.load_state_dict(resume_state['optimizer'])
        rng.bit_generator.state = resume_state['sample_rng']
        torch.set_rng_state(resume_state['torch_rng'])
        history = resume_state['history']
        learner.updates = len(history)
    else:
        torch.manual_seed(seed)
    for _ in range(len(history), updates):
        samples, counts = replay.sample(batch_size, rng)
        history.append(dict(learner.update_entities(samples), family_counts=counts))
        if on_update is not None:
            on_update(learner.model, dict(optimizer=learner.optimizer.state_dict(),
                sample_rng=rng.bit_generator.state, torch_rng=torch.get_rng_state(),
                history=history))
    return learner.model.eval(), history


def target_stats(episodes):
    """Search-target signal diagnostics: entropy, peak mass and forced actions."""
    rows = [row for episode in episodes for row in episode.get('rows', [])]
    if not rows:
        return dict(rows=0, mean_entropy=None, mean_max_prob=None, forced_fraction=None)
    entropies, peaks = [], []
    for row in rows:
        probabilities = np.array([row['policy_target'][key] for key in sorted(row['policy_target'])],
                                 dtype=float)
        positive = probabilities[probabilities > 0]
        entropies.append(float(-(positive * np.log(positive)).sum()))
        peaks.append(float(probabilities.max()))
    return dict(rows=len(rows),
                mean_entropy=float(np.mean(entropies)),
                mean_max_prob=float(np.mean(peaks)),
                forced_fraction=float(np.mean([bool(row['forced_action']) for row in rows])))


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


def preflight(config_path, protocol_path, *, iterations=None, episodes=None, max_turns=None,
              max_decisions=None, validation_limit=None, check_test=False):
    """Validate planned training and held-out recipes before any training run."""
    import hashlib
    from .all_decks import frozen_manifest

    config = load_frozen_config(config_path)
    effective = effective_settings(config, iterations=iterations, episodes=episodes, max_turns=max_turns, max_decisions=max_decisions)
    iterations, episodes = effective['iterations'], effective['episodes']
    max_turns, max_decisions = effective['max_turns'], effective['max_decisions']
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    manifest = frozen_manifest()
    expected_sha = protocol.get('generator_manifest_sha')
    actual_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if expected_sha != actual_sha:
        raise ValueError('Protocol does not match the current generator manifest')
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
    test_check = None
    if check_test and 'test' in protocol:
        test_recipes = protocol_recipes(protocol, 'test')
        test_ok, test_errors = 0, []
        for recipe in test_recipes:
            try:
                _probe_recipe(recipe, limits)
                test_ok += 1
            except Exception as exc:  # noqa: BLE001
                test_errors.append(dict(scenario_id=recipe.scenario_id,
                                        encounter=recipe.encounter_id,
                                        error=f'{type(exc).__name__}: {exc}'))
        test_check = {'checked': len(test_recipes), 'ok': test_ok, 'errors': test_errors}
    return dict(version=VERSION, scope="opening-construction-and-encoding-only",
                config=str(config_path), protocol=str(protocol_path),
                generator_manifest_sha=actual_sha,
                training={'planned': iterations * episodes, 'ok': training_ok,
                          'errors': training_errors},
                validation={'checked': len(validation), 'ok': validation_ok,
                            'errors': validation_errors},
                test=test_check,
                ready=not training_errors and not validation_errors
                and (test_check is None or not test_check['errors']))


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


def effective_settings(config, **overrides):
    """One resolved configuration for CLI, evidence and resume validation."""
    training = config['training']
    settings = dict(iterations=training['iterations'], episodes=training['episodes_per_iteration'],
        updates=training['updates_per_iteration'], budget=config['search']['budget'],
        batch_size=training['batch_size'], learning_rate=training['learning_rate'],
        value_weight=training['value_weight'], max_turns=training['max_turns'],
        max_decisions=training['max_decisions'], eval_max_turns=config['evaluation']['max_turns'],
        eval_max_decisions=config['evaluation']['max_decisions'], seed=training.get('init_seed', 0))
    settings.update({key: value for key, value in overrides.items() if value is not None})
    for key, value in settings.items():
        if key in ('learning_rate', 'value_weight'):
            if not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
                raise ValueError(f'Invalid {key}')
        elif type(value) is not int or value < (0 if key == 'seed' else 1):
            raise ValueError(f'Invalid {key}')
    if settings['iterations'] > 1024 or settings['episodes'] > 64:
        raise ValueError('Generator coordinate capacity exceeded')
    return settings


def promotion(reference, candidate, expected):
    if (len(reference) != expected or len(candidate) != expected
            or len({r['scenario_id'] for r in candidate}) != expected):
        return False, None
    try:
        comparison = paired_gain(reference, candidate)
    except ValueError:
        return False, None
    return comparison['ci95'][0] > 0, comparison


def run(config_path, protocol_path, out_dir, *, iterations=None, episodes=None, updates=None,
        budget=None, batch_size=None, learning_rate=None, seed=None, max_turns=None,
        max_decisions=None, eval_max_turns=None, eval_max_decisions=None,
        include_test=False, resume=False, compare_baseline=True, workers=1,
        enforce_test_gate=True, log=print):
    import hashlib
    from .config import content_hash
    from .network import code_digest
    config = load_frozen_config(config_path)
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    settings = effective_settings(config, iterations=iterations, episodes=episodes, updates=updates,
        budget=budget, batch_size=batch_size, learning_rate=learning_rate, seed=seed,
        max_turns=max_turns, max_decisions=max_decisions, eval_max_turns=eval_max_turns,
        eval_max_decisions=eval_max_decisions)
    if not compare_baseline or not enforce_test_gate:
        raise ValueError('Champion selection requires baseline and an enforced test gate')
    if type(workers) is not int or workers < 1:
        raise ValueError('Positive worker count required')
    limits = EpisodeLimits(max_turns=settings['max_turns'], max_decisions=settings['max_decisions'])
    eval_limits = EpisodeLimits(max_turns=settings['eval_max_turns'], max_decisions=settings['eval_max_decisions'])
    provenance = dict(config_sha256=hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        protocol_sha256=hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest(),
        generator_manifest_sha=protocol.get('generator_manifest_sha'),
        content=ALL_CONTENT, reward=V7, rules=RULES_VERSION, lifecycle=config['lifecycle'],
        source_digest=code_digest())
    identity = content_hash(dict(provenance=provenance,
        settings={k: v for k, v in settings.items() if k != 'iterations'}))
    # Only construction/encoding; never open test outcomes before the final gate.
    check = preflight(config_path, protocol_path, iterations=settings['iterations'],
        episodes=settings['episodes'], max_turns=limits.max_turns,
        max_decisions=limits.max_decisions, check_test=False)
    if not check['ready']:
        raise ValueError(f'Preflight rejected the run: {check}')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / 'state.json'
    version = f"{VERSION}-{settings['seed']}"
    validation = protocol_recipes(protocol, 'validation')
    if resume:
        if not state_path.exists():
            raise ValueError('No v3 recovery state; legacy runs cannot resume')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['identity'] != identity or state['version'] != VERSION:
            raise ValueError('Resume configuration/protocol differs from the saved run')
        if settings['iterations'] < len(state['history']):
            raise ValueError('Resume cannot reduce completed iterations')
        champion, _ = load_transformer_checkpoint(out / state['champion_checkpoint'], TIER, ALL_CONTENT, V7)
    else:
        if any(p.name != 'run.log' for p in out.iterdir()):
            raise ValueError('Output directory is not empty; use --resume or a fresh directory')
        champion = fresh_model(config, settings['seed'])
        baseline, rows = evaluate_recipes(champion, validation, version=f'{version}-baseline',
                                          error_dir=out / 'errors', limits=eval_limits)
        if baseline['contract_rejections'] or len(rows) != len(validation):
            raise ValueError('Baseline validation must complete without rejections')
        save_transformer_checkpoint(out / 'initial.pt', champion, version, config=config)
        atomic_json(out / 'baseline.json', dict(summary=baseline, rows=rows))
        state = dict(version=VERSION, identity=identity, history=[], pending=None,
            baseline=baseline, baseline_rows=rows, champion_checkpoint='initial.pt',
            champion_rows=rows, champion_validation=baseline, learner_checkpoint='initial.pt')
        atomic_json(state_path, state)
    replay = EntityReplayBuffer(out / 'replay', capacity=50_000,
                                content_version=ALL_CONTENT, reward_version=V7)

    def write_report():
        report = dict(version=VERSION, config=str(config_path), protocol=str(protocol_path),
            provenance=provenance, effective_settings=settings, iteration_budget=settings,
            baseline=state['baseline'], history=state['history'],
            champion_checkpoint=state['champion_checkpoint'],
            learner_checkpoint=state['learner_checkpoint'],
            final_validation=state['champion_validation'])
        atomic_json(out / 'report.json', report)
        return report

    collector = None
    try:
        if workers > 1:
            from .self_play import Collector
            collector = Collector(workers)
        for iteration in range(len(state['history']), settings['iterations']):
            started = time.perf_counter()
            pending = state['pending']
            if pending is None:
                recipes = training_recipes(iteration, settings['episodes'])
                failures = []
                collected = collect(champion, recipes, iteration=iteration, budget=settings['budget'],
                    error_dir=out / 'errors', limits=limits, version=f'{version}-{iteration}',
                    seed=settings['seed'] * 100_000 + iteration * 1_000,
                    failures=failures, workers=workers, collector=collector)
                if failures:
                    atomic_json(out / f'rejected-{iteration:03d}.json', failures)
                    raise ValueError('Collection contract rejection: training halted; see rejected recipes')
                cache = f'collection-{iteration:03d}.json'
                atomic_json(out / cache, collected)
                pending = dict(iteration=iteration, collection=cache, update_checkpoint=None)
                state['pending'] = pending
                atomic_json(state_path, state)
            collected = json.loads((out / pending['collection']).read_text(encoding='utf-8'))
            for episode in collected:
                replay.commit(episode)
            collected_at = time.perf_counter()
            candidate, payload = load_transformer_checkpoint(out / state['learner_checkpoint'], TIER, ALL_CONTENT, V7)
            training_state = payload.get('training_state')
            if training_state is not None:
                # Preserve optimizer/RNG across rounds; only round-local progress resets.
                training_state = dict(training_state, history=[])
            if pending['update_checkpoint']:
                candidate, payload = load_transformer_checkpoint(out / pending['update_checkpoint'], TIER, ALL_CONTENT, V7)
                training_state = payload['training_state']

            def persist_update(model, training_state):
                name = f"update-{iteration:03d}-{len(training_state['history']):04d}.pt"
                save_transformer_checkpoint(out / name, model, version, config=config,
                                            iteration=iteration, training_state=training_state)
                pending['update_checkpoint'] = name
                atomic_json(state_path, state)

            candidate, losses = update(candidate, replay, learning_rate=settings['learning_rate'],
                batch_size=settings['batch_size'], updates=settings['updates'],
                seed=settings['seed'] * 1000 + iteration, value_weight=settings['value_weight'],
                resume_state=training_state, on_update=persist_update)
            updated_at = time.perf_counter()
            summary, rows = evaluate_recipes(candidate, validation, version=f'{version}-candidate-{iteration}',
                                             error_dir=out / 'errors', limits=eval_limits)
            if summary['contract_rejections'] or len(rows) != len(validation):
                raise ValueError('Candidate validation must complete without rejections')
            promoted, vs_champion = promotion(state['champion_rows'], rows, len(validation))
            comparison = paired_gain(state['baseline_rows'], rows)
            checkpoint = f'iteration-{iteration:03d}.pt'
            save_transformer_checkpoint(out / checkpoint, candidate, version, config=config,
                                        statistics=summary, iteration=iteration)
            by_encounter = {}
            for row in rows:
                by_encounter.setdefault(row['encounter_id'], []).append(row)
            breakdown = {key: dict(episodes=len(group),
                win_rate=sum(r['termination_reason'] == 'win' for r in group) / len(group),
                mean_utility=float(np.mean([r['reward'] for r in group])),
                death_rate=sum(r['termination_reason'] == 'death' for r in group) / len(group))
                for key, group in sorted(by_encounter.items())}
            ended = time.perf_counter()
            record = dict(version=VERSION, iteration=iteration,
                episodes=[e['episode_id'] for e in collected],
                outcomes=[e['outcome']['termination_reason'] for e in collected],
                replay_size=replay.size, updates=losses, rejected_recipes=[],
                validation=summary, validation_rows=rows, validation_by_encounter=breakdown,
                checkpoint=checkpoint, promoted=promoted, paired_vs_champion=vs_champion,
                paired_vs_baseline=comparison, target_stats=target_stats(collected),
                seconds=dict(collect=collected_at-started, update=updated_at-collected_at,
                             evaluate=ended-updated_at, total=ended-started))
            if promoted:
                champion = candidate
                state.update(champion_checkpoint=checkpoint, champion_rows=rows, champion_validation=summary)
            if not pending['update_checkpoint']:
                raise ValueError('Learner update did not persist a recovery checkpoint')
            state['learner_checkpoint'] = pending['update_checkpoint']
            state['history'].append(record)
            state['pending'] = None
            atomic_json(out / f'iteration-{iteration:03d}.json', record)
            atomic_json(state_path, state)  # authoritative commit, before the derived report
            write_report()
            log(f"iteration {iteration}: candidate {summary['mean_utility']:.3f}, promoted={promoted}")
        report = write_report()
        if include_test:
            passed, comparison = promotion(state['baseline_rows'], state['champion_rows'], len(validation))
            report['test_gate'] = dict(required='paired validation CI95 lower > 0; zero rejections',
                                       passed=passed, comparison=comparison, enforced=True, forced=False)
            if passed:
                test = protocol_recipes(protocol, 'test')
                summary, rows = evaluate_recipes(champion, test, version=version,
                                                error_dir=out / 'errors', limits=eval_limits)
                if summary['contract_rejections'] or len(rows) != len(test):
                    raise ValueError('Final test contract rejection')
                report['test'] = summary
            atomic_json(out / 'report.json', report)
        return report
    finally:
        if collector is not None:
            collector.__exit__(None, None, None)


def tee_log(path):
    """Print to stdout and append the same lines to a UTF-8 log file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def log(*args):
        line = ' '.join(str(arg) for arg in args)
        print(line, flush=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')

    return log


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='P3 all-content XS self-play runner')
    parser.add_argument('--config', default='configs/az_all_xs_v1/config.json')
    parser.add_argument('--protocol', default='configs/az_all_xs_v1/protocol.json')
    parser.add_argument('--out', default='output/az_all_xs_run')
    parser.add_argument('--log-file', default=None)
    parser.add_argument('--iterations', type=int, default=None)
    parser.add_argument('--episodes', type=int, default=None)
    parser.add_argument('--updates', type=int, default=None)
    parser.add_argument('--budget', type=int, default=None)
    parser.add_argument('--batch-size', type=int, default=None)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--max-turns', type=int, default=None)
    parser.add_argument('--max-decisions', type=int, default=None)
    parser.add_argument('--eval-max-turns', type=int, default=None)
    parser.add_argument('--eval-max-decisions', type=int, default=None)
    parser.add_argument('--include-test', action='store_true')
    parser.add_argument('--force-test', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--no-baseline', action='store_true')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args(argv)
    if args.preflight_only:
        result = preflight(args.config, args.protocol, iterations=args.iterations,
                           episodes=args.episodes, max_turns=args.max_turns,
                           max_decisions=args.max_decisions)
    else:
        log = tee_log(args.log_file or Path(args.out) / 'run.log')
        result = run(args.config, args.protocol, args.out, iterations=args.iterations,
                     episodes=args.episodes, updates=args.updates, budget=args.budget,
                     batch_size=args.batch_size, seed=args.seed, max_turns=args.max_turns,
                     max_decisions=args.max_decisions, eval_max_turns=args.eval_max_turns,
                     eval_max_decisions=args.eval_max_decisions, include_test=args.include_test,
                     resume=args.resume, compare_baseline=not args.no_baseline,
                     workers=args.workers, enforce_test_gate=not args.force_test, log=log)
        result = {key: result[key] for key in ('version', 'history', 'final_validation')}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()











