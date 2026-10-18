"""Full-horizon MCTS contract audit, fresh weights, no learning or test outcomes."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def probe(document):
    import torch
    from sts2_env.az.all_runner import load_frozen_config, fresh_model, SEARCH
    from sts2_env.az.scenarios import CombatScenario
    from sts2_env.az.evaluation import evaluate
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.rewards import V7
    torch.set_num_threads(1)
    from sts2_env.cards.base import reset_instance_counter
    reset_instance_counter()
    recipe = CombatScenario.from_dict(document)
    model = fresh_model(load_frozen_config(ROOT / 'configs/az_all_xs_v1/config.json'))
    try:
        rows = evaluate(model, 'readiness', [recipe], simulations=8, policy='network',
            search_version=SEARCH, reward_version=V7,
            error_dir=ROOT / 'output/readiness_audit/errors',
            limits=EpisodeLimits(max_turns=40, max_decisions=400))
        return dict(scenario_id=recipe.scenario_id, encounter=recipe.encounter_id, ok=True,
                    outcome=rows[0]['termination_reason'], decisions=rows[0]['decisions'])
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return dict(scenario_id=recipe.scenario_id, encounter=recipe.encounter_id,
                    ok=False, error=f'{type(exc).__name__}: {exc}')


def main():
    from sts2_env.az.all_runner import protocol_recipes, training_recipes, VERSION
    from sts2_env.az.all_decks import admitted_encounters
    from sts2_env.az.config import atomic_json
    from sts2_env.az.network import code_digest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--scope', choices=('validation', 'encounters', 'both'), default='both')
    parser.add_argument('--only', nargs='*', help='Encounter ids for focused repair checks')
    parser.add_argument('--out', default='docs/training_readiness_mcts.json')
    args = parser.parse_args()
    protocol = json.loads((ROOT / 'configs/az_all_xs_v1/protocol.json').read_text())
    recipes = list(protocol_recipes(protocol, 'validation')) if args.scope != 'encounters' else []
    if args.scope != 'validation':
        # A generated admitted deck held fixed across every admitted encounter.
        base = training_recipes(0, 1)[0]
        recipes += [replace(base, split='validation', scenario_id=f'readiness-encounter-{i:03d}', encounter_id=name)
                    for i, name in enumerate(admitted_encounters())]
    if args.only:
        recipes = [r for r in recipes if r.encounter_id in args.only]
    report = dict(runner=VERSION, source_digest=code_digest(), formal_training=False,
                  test_outcomes_opened=False, max_turns=40, max_decisions=400,
                  simulations=8, planned=len(recipes), results=[])
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(probe, r.to_dict()) for r in recipes]
        for future in as_completed(futures):
            row = future.result()
            report['results'].append(row)
            report['results'].sort(key=lambda r: r['scenario_id'])
            report['passed'] = sum(r['ok'] for r in report['results'])
            report['failed'] = len(report['results']) - report['passed']
            atomic_json(ROOT / args.out, report)
            print(f"{len(report['results'])}/{len(recipes)} {row}", flush=True)
    return 1 if report['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
