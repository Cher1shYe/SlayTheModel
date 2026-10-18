"""Explicit, no-update diagnostics on training recipes or saved training episodes.

No validation/test recipes are accepted. These measurements diagnose the teacher
and value head, and are not held-out estimates of learning quality.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from .config import EpisodeLimits, atomic_json, derive_seed


def value_metrics(predictions, targets):
    p, z = np.asarray(predictions, dtype=float), np.asarray(targets, dtype=float)
    if p.ndim != 1 or p.shape != z.shape or not p.size or not np.isfinite([p, z]).all():
        raise ValueError('Expected nonempty paired finite values')
    variance = float(np.var(z))
    mse = float(np.mean((p-z)**2))
    return dict(count=len(p), mse=mse, mae=float(np.mean(abs(p-z))),
        prediction_mean=float(p.mean()), target_mean=float(z.mean()),
        zero_baseline_mse=float(np.mean(z*z)),
        fitted_constant_baseline_mse=variance,
        explained_variance_score=None if variance == 0 else 1-float(np.var(z-p))/variance,
        correlation=None if variance == 0 or np.var(p) == 0 else float(np.corrcoef(p, z)[0, 1]))


def value_diagnostic(model, episodes, max_rows=256):
    """Deterministic, bounded state sample; input file is the fixed diagnostic set."""
    from .entity_replay import unpack_observation
    if type(max_rows) is not int or max_rows < 1:
        raise ValueError('max_rows must be positive')
    if not episodes or any(e.get('split') != 'train' or not e.get('complete') for e in episodes):
        raise ValueError('Only complete training episodes may be diagnosed')
    rows = [(r, e['outcome']['termination_reason']) for e in sorted(episodes, key=lambda e: e['episode_id'])
            for r in e['rows']]
    if not rows:
        raise ValueError('Empty diagnostic episodes')
    indices = np.linspace(0, len(rows)-1, min(max_rows, len(rows)), dtype=int)
    groups = {}
    predictions, targets, selected = [], [], []
    for i in indices:
        row, outcome = rows[i]
        _, value = model.predict(unpack_observation(row['observation']))
        predictions.append(value)
        targets.append(row['z'])
        groups.setdefault(outcome, ([], []))
        groups[outcome][0].append(value)
        groups[outcome][1].append(row['z'])
        selected.append([row['episode_id'], row['step_index']])
    return dict(scope='saved-training-states; correlated states, not held-out evidence',
        rows_available=len(rows), sample=selected, aggregate=value_metrics(predictions, targets),
        by_outcome={k: value_metrics(*v) for k, v in sorted(groups.items())})


def search_diagnostic(model, recipes, budgets=(0, 8, 32), seed=123,
                      limits=EpisodeLimits(), error_dir='output/az_diagnostics/errors'):
    """Paired public-observation network/MCTS evaluation with no exploration noise."""
    from .adapter import ObservableCombatAdapter
    from .action_candidates import action_candidates
    from .entity_encoder import encode_entities
    from .dynamic_search import plan_dynamic
    from .evaluation import summarize
    from .all_runner import paired_gain, SEARCH
    from .rewards import V7
    if not recipes or any(r.split != 'train' for r in recipes):
        raise ValueError('Search diagnostics require training recipes only')
    if len({r.scenario_id for r in recipes}) != len(recipes):
        raise ValueError('Duplicate diagnostic recipe')
    if (not budgets or budgets[0] != 0 or len(set(budgets)) != len(budgets)
            or any(type(b) is not int or b < 0 for b in budgets)):
        raise ValueError('Unique nonnegative budgets must start with network budget 0')
    results = {}
    for budget in budgets:
        rows = []
        for index, recipe in enumerate(recipes):
            env = ObservableCombatAdapter(recipe, limits, error_dir, V7)
            latencies, coverage = [], []
            while not env.outcome().done:
                started = perf_counter()
                info = env.information
                if budget:
                    result = plan_dynamic(info, model, model_version='training-diagnostic', budget=budget,
                        training=False, temperature=0, search_version=SEARCH,
                        search_seed=derive_seed(seed, 0, index, f'diagnostic-{len(latencies)}'))
                    key = result.action
                    if not result.forced_action:
                        coverage.append(dict(legal=len(result.policy_target),
                            visited=sum(v > 0 for v in result.root_visits.values())))
                else:
                    priors, _ = model.predict(encode_entities(info))
                    key = max(sorted(priors), key=priors.get)
                _, mapping = action_candidates(info)
                latencies.append(perf_counter()-started)
                env.step(mapping[key])
            rows.append(dict(asdict(env.outcome()), scenario_id=recipe.scenario_id,
                encounter_id=recipe.encounter_id, decision_seconds=latencies,
                errors=0, illegal_actions=0, action_coverage=coverage))
        coverage = [c for row in rows for c in row['action_coverage']]
        results[str(budget)] = dict(summary=summarize(rows), rows=rows,
            search_coverage=dict(nonforced_states=len(coverage),
                mean_legal=None if not coverage else float(np.mean([c['legal'] for c in coverage])),
                mean_visited=None if not coverage else float(np.mean([c['visited'] for c in coverage])),
                mean_visited_fraction=None if not coverage else float(np.mean([c['visited']/c['legal'] for c in coverage]))))
        if budget:
            results[str(budget)]['paired_vs_network'] = paired_gain(results['0']['rows'], rows)
    return dict(scope='training-only paired diagnostic; no optimizer updates', seed=seed,
        limits=asdict(limits), recipes=[r.to_dict() for r in recipes], results=results)


def main():
    import argparse
    from .all_runner import training_recipes, TIER
    from .content import ALL_CONTENT
    from .model_factory import load_transformer_checkpoint
    from .network import code_digest
    from .rewards import V7
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--seed', type=int, default=123)
    sub = parser.add_subparsers(dest='mode', required=True)
    value = sub.add_parser('value')
    value.add_argument('--collection', required=True)
    value.add_argument('--max-rows', type=int, default=256)
    search = sub.add_parser('search')
    search.add_argument('--iteration', type=int, default=0)
    search.add_argument('--episodes', type=int, default=8)
    search.add_argument('--budgets', type=int, nargs='+', default=[0, 8, 32])
    search.add_argument('--max-turns', type=int, default=40)
    search.add_argument('--max-decisions', type=int, default=400)
    args = parser.parse_args()
    if Path(args.out).exists():
        parser.error('Use a new output file; diagnostics never overwrite evidence')
    model, payload = load_transformer_checkpoint(args.checkpoint, TIER, ALL_CONTENT, V7)
    report = dict(version='training-diagnostics-v1', source_digest=code_digest(),
        checkpoint_source_digest=payload.get('code_digest'),
        checkpoint_source_matches=payload.get('code_digest') == code_digest(),
        checkpoint=str(args.checkpoint), checkpoint_sha256=hashlib.sha256(Path(args.checkpoint).read_bytes()).hexdigest())
    if args.mode == 'value':
        data = Path(args.collection).read_bytes()
        report.update(collection=str(args.collection), collection_sha256=hashlib.sha256(data).hexdigest(),
            diagnostic=value_diagnostic(model, json.loads(data), args.max_rows))
    else:
        if not 0 <= args.iteration < 1024 or not 1 <= args.episodes <= 1024:
            parser.error('iteration must be 0..1023; episodes must be 1..1024')
        report['diagnostic'] = search_diagnostic(model, training_recipes(args.iteration, args.episodes),
            args.budgets, args.seed, EpisodeLimits(max_turns=args.max_turns, max_decisions=args.max_decisions),
            error_dir=str(Path(args.out).parent / 'errors'))
    atomic_json(args.out, report)


if __name__ == '__main__':
    main()
