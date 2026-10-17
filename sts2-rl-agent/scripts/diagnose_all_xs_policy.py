"""Diagnose network-only vs dynamic MCTS policy on held-out all-content recipes.

This is a measurement of the frozen pipeline (no training, no test split): it
reports the prior/search utility gap for the initial XS model so later training
can be compared against the same baseline.
"""
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sts2_env.az.all_runner import (SEARCH, evaluate_recipes, fresh_model, load_frozen_config,
                                  protocol_recipes)
from sts2_env.az.config import EpisodeLimits, atomic_json
from sts2_env.az.evaluation import summarize
from sts2_env.az.rewards import V7


def run_pass(model, recipes, simulations, limits, version):
    from sts2_env.az.evaluation import evaluate

    started = time.perf_counter()
    kept, rejected = [], []
    for recipe in recipes:
        try:
            kept.extend(evaluate(model, version, [recipe], simulations=simulations,
                                 policy='network', search_version=SEARCH, reward_version=V7,
                                 error_dir=str(ROOT / 'output' / 'az_all_xs_policy' / 'errors'),
                                 limits=limits))
        except Exception as exc:  # noqa: BLE001 - contract rejection is evidence
            rejected.append(dict(scenario_id=recipe.scenario_id,
                                 encounter=recipe.encounter_id,
                                 error=f'{type(exc).__name__}: {exc}'))
    elapsed = time.perf_counter() - started
    summary = summarize(kept) if kept else dict(episodes=0, win_rate=0.0, mean_utility=0.0)
    summary['wall_seconds'] = round(elapsed, 3)
    summary['search_simulations'] = simulations
    summary['contract_rejections'] = len(rejected)
    summary['contract_rejected'] = rejected
    return summary, kept


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    config = load_frozen_config(ROOT / 'configs' / 'az_all_xs_v1' / 'config.json')
    protocol = json.loads((ROOT / 'configs' / 'az_all_xs_v1' / 'protocol.json')
                          .read_text(encoding='utf-8'))
    recipes = protocol_recipes(protocol, 'validation')[:count]
    model = fresh_model(config)
    limits = EpisodeLimits(max_turns=6, max_decisions=24)
    prior_summary, prior_rows = run_pass(model, recipes, 0, limits, 'prior')
    search_summary, search_rows = run_pass(model, recipes, budget, limits, f'mcts{budget}')
    old = {row['scenario_id']: row['reward'] for row in prior_rows}
    new = {row['scenario_id']: row['reward'] for row in search_rows}
    common = sorted(set(old) & set(new))
    gains = [new[key] - old[key] for key in common]
    report = {
        'version': 'all-xs-policy-diagnostic-v1',
        'content': config['content'], 'reward': config['reward'],
        'recipes': count, 'budget': budget,
        'prior': prior_summary, 'search': search_summary,
        'paired_gain': {'episodes': len(gains), 'common_recipes': len(common),
                        'mean_gain': statistics.fmean(gains),
                        'positive': sum(gain > 0 for gain in gains),
                        'negative': sum(gain < 0 for gain in gains),
                        'equal': sum(gain == 0 for gain in gains)},
        'note': 'Initial XS weights only; measurement of the frozen pipeline, not training.',
    }
    atomic_json(ROOT / 'docs' / 'all_xs_policy_diagnostic.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()


