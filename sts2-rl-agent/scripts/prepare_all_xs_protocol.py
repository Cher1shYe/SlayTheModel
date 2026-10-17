"""Freeze the P3 all-content XS protocol: config, evaluation recipes, bindings."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sts2_env.az import all_decks
from sts2_env.az.config import atomic_json

OUT = ROOT / 'configs' / 'az_all_xs_v1'
VERSION = 'az-all-xs-v1'
VALIDATION_COUNT = 64
TEST_COUNT = 64
TRAIN_ITERATIONS = 8
EPISODES_PER_ITERATION = 48
SEARCH_BUDGET = 8
LEARNING_RATE = 3e-4
BATCH_SIZE = 64


def recipe_document(recipe):
    return {
        'scenario_id': recipe.scenario_id,
        'encounter': recipe.encounter_id,
        'seed': recipe.environment_seed,
        'player_hp': recipe.player_hp,
        'deck': [[entry.card_id, entry.upgraded, entry.count] for entry in recipe.deck],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = all_decks.frozen_manifest()
    config = {
        'version': VERSION,
        'status': 'frozen-before-training',
        'content': manifest['content'],
        'reward': 'risk-terminal-v7',
        'rules_version': __import__('sts2_env.az.config', fromlist=['RULES_VERSION']).RULES_VERSION,
        'generator': manifest,
        'search': {'policy': 'dynamic-risk-puct-v2', 'version': 'all-content-search-v1',
                   'budget': SEARCH_BUDGET, 'deterministic_tiebreak': 'action-index'},
        'model': {'tier': 'XS', 'initialization': 'fresh', 'reuse_previous_weights': False},
        'training': {
            'iterations': TRAIN_ITERATIONS,
            'episodes_per_iteration': EPISODES_PER_ITERATION,
            'batch_size': BATCH_SIZE,
            'learning_rate': LEARNING_RATE,
            'value_weight': 0.1,
            'self_play': 'native monsters, all-content information state, particle belief',
            'targets': 'search visit distribution + terminal V7 utility',
        },
        'evaluation': {'validation_recipes': VALIDATION_COUNT, 'test_recipes': TEST_COUNT,
                       'metric': 'mean network V7 utility (network-only, max_turns 40)',
                       'holdout_policy': 'test split opened only for the final gate'},
        'gate': {'requires': 'validation utility gain over frozen baseline before opening test'},
        'notes': [
            'Held-out splits use fixed master seeds; training coordinates never overlap.',
            'Only parity-passing encounters and admitted initial cards are used.',
            'No weights or replay are reused from earlier content versions.',
        ],
    }
    atomic_json(OUT / 'config.json', config)
    validation = [all_decks.generate_recipe(all_decks.HELDOUT_MASTER_SEEDS['validation'], 0, job,
                                            'validation') for job in range(VALIDATION_COUNT)]
    test = [all_decks.generate_recipe(all_decks.HELDOUT_MASTER_SEEDS['test'], 0, job, 'test')
            for job in range(TEST_COUNT)]
    protocol = {
        'version': VERSION + '-protocol',
        'content': manifest['content'],
        'generator_manifest_sha': __import__('hashlib').sha256(
            json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        'train_plan': {'iterations': TRAIN_ITERATIONS,
                       'episodes_per_iteration': EPISODES_PER_ITERATION,
                       'coordinate_rule': 'master = iteration % 32, job = episode % 16'},
        'validation': [recipe_document(r) for r in validation],
        'test': [recipe_document(r) for r in test],
        'note': 'Recipes are pure functions of their frozen coordinates and this manifest.',
    }
    atomic_json(OUT / 'protocol.json', protocol)
    print(json.dumps({'config': str(OUT / 'config.json'), 'protocol': str(OUT / 'protocol.json'),
                      'validation': len(validation), 'test': len(test)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
