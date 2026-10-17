"""Sample the arbitrary-deck generator and report coverage; never trains."""
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sts2_env.az import all_decks
from sts2_env.az.config import atomic_json


def sample(split, masters, jobs):
    recipes = []
    for master in masters:
        for job in jobs:
            iteration = 0 if split != 'train' else master % 4
            recipes.append(all_decks.generate_recipe(master, iteration, job, split))
    return recipes


def summarize(split, recipes):
    sizes = [sum(entry.count for entry in recipe.deck) for recipe in recipes]
    cards = {entry.card_id for recipe in recipes for entry in recipe.deck}
    encounters = {recipe.encounter_id for recipe in recipes}
    upgrades = sum(entry.count for recipe in recipes for entry in recipe.deck if entry.upgraded)
    total = sum(sizes)
    duplicates = sum(1 for recipe in recipes
                     if len({entry.card_id for entry in recipe.deck}) < len(recipe.deck))
    return {
        'split': split, 'recipes': len(recipes),
        'deck_size': {'min': min(sizes), 'max': max(sizes),
                      'mean': round(statistics.fmean(sizes), 3)},
        'distinct_cards': len(cards),
        'distinct_encounters': len(encounters),
        'upgrade_rate': round(upgrades / total, 4),
        'decks_with_duplicate_entries': duplicates,
        'seed_bounds': [min(r.environment_seed for r in recipes),
                        max(r.environment_seed for r in recipes)],
    }


def main():
    train = sample('train', range(24), range(8))
    validation = sample('validation', [all_decks.HELDOUT_MASTER_SEEDS['validation']], range(64))
    test = sample('test', [all_decks.HELDOUT_MASTER_SEEDS['test']], range(64))
    manifest = all_decks.frozen_manifest()
    report = {
        'version': 'all-deck-generator-audit-v1',
        'generator': manifest,
        'splits': {'train': summarize('train', train),
                   'validation': summarize('validation', validation),
                   'test': summarize('test', test)},
        'admitted_encounters': len(manifest['encounters']),
        'admitted_pool': manifest['pool_size'],
        'note': 'Synthetic recipes only; no training, no final-holdout use beyond '
                'recipe construction.',
    }
    atomic_json(ROOT / 'docs/all_deck_generator.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'generator'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
