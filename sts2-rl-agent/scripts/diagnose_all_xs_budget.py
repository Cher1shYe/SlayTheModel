"""Compare search-target stability at budget 8 vs 32 on the same public states.

The deployment budget is 8; this measurement checks whether its chosen actions
and target entropy agree with a much larger budget at the same decision points.
No training and no test split: pure search diagnostics on validation recipes.
"""
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.all_runner import SEARCH, fresh_model, load_frozen_config, protocol_recipes
from sts2_env.az.config import EpisodeLimits, atomic_json
from sts2_env.az.dynamic_search import plan_dynamic
from sts2_env.az.rewards import V7


def entropy(target):
    values = np.array([target[key] for key in sorted(target)], dtype=float)
    positive = values[values > 0]
    return float(-(positive * np.log(positive)).sum())


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    small = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    large = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    config = load_frozen_config(ROOT / 'configs' / 'az_all_xs_v1' / 'config.json')
    protocol = json.loads((ROOT / 'configs' / 'az_all_xs_v1' / 'protocol.json')
                          .read_text(encoding='utf-8'))
    recipes = protocol_recipes(protocol, 'validation')[:count]
    model = fresh_model(config)
    limits = EpisodeLimits(max_turns=6, max_decisions=24)
    started = time.perf_counter()
    per_recipe, agreements, entropy_small, entropy_large = [], [], [], []
    for index, recipe in enumerate(recipes):
        env = ObservableCombatAdapter(recipe, reward_version=V7, limits=limits)
        decisions = 0
        agree = 0
        errors = []
        try:
            while not env.outcome().done:
                info = env.information
                key_small = plan_dynamic(info, model, model_version='budget-diagnostic',
                                         budget=small, search_seed=decisions, search_version=SEARCH)
                key_large = plan_dynamic(info, model, model_version='budget-diagnostic',
                                         budget=large, search_seed=decisions, search_version=SEARCH)
                agreements.append(key_small.action == key_large.action)
                entropy_small.append(entropy(key_small.policy_target))
                entropy_large.append(entropy(key_large.policy_target))
                agree += key_small.action == key_large.action
                decisions += 1
                _, mapping = action_candidates(info)
                env.step(mapping[key_small.action])
            outcome = env.outcome()
            per_recipe.append(dict(scenario_id=recipe.scenario_id,
                                   encounter=recipe.encounter_id, decisions=decisions,
                                   agree=agree, reward=outcome.reward))
        except Exception as exc:  # noqa: BLE001 - contract rejection is evidence
            errors.append(dict(scenario_id=recipe.scenario_id,
                               encounter=recipe.encounter_id,
                               error=f'{type(exc).__name__}: {exc}', decisions=decisions))
            per_recipe.append(dict(scenario_id=recipe.scenario_id,
                                   encounter=recipe.encounter_id, decisions=decisions,
                                   agree=agree, error=errors[-1]['error']))
    report = {
        'version': 'all-xs-budget-diagnostic-v1',
        'content': config['content'], 'reward': config['reward'],
        'recipes': count, 'budgets': [small, large],
        'searches': len(agreements),
        'agreement_rate': float(np.mean(agreements)) if agreements else None,
        'mean_entropy': {'small': statistics.fmean(entropy_small) if entropy_small else None,
                         'large': statistics.fmean(entropy_large) if entropy_large else None},
        'wall_seconds': round(time.perf_counter() - started, 2),
        'per_recipe': per_recipe,
        'note': 'Same public states; small acts, large is the reference. Not training.',
    }
    atomic_json(ROOT / 'docs' / 'all_xs_budget_diagnostic.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
