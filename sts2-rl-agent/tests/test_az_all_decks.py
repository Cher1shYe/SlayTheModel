"""Arbitrary-deck generator contract for all-content self-play."""
import json
from pathlib import Path

import pytest

from sts2_env.az import all_decks
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.scenarios import CombatScenario


def test_card_pool_is_the_admitted_initial_pool():
    pool = all_decks.card_pool()
    assert len(pool) == 146
    assert tuple(sorted(pool)) == pool
    for deferred in ('ALCHEMIZE', 'ENTROPY', 'JACK_OF_ALL_TRADES', 'SPLASH', 'HIDDEN_GEM'):
        assert deferred not in pool


def test_admitted_encounters_come_from_the_parity_and_robustness_reports():
    report = json.loads(all_decks.PARITY_REPORT.read_text(encoding='utf-8'))
    passed = {name for name, entry in report['results'].items() if entry['status'] == 'pass'}
    robustness = json.loads(all_decks.ROBUSTNESS_REPORT.read_text(encoding='utf-8'))
    assert all_decks.admitted_encounters() == tuple(sorted(robustness['robust']))
    assert set(all_decks.admitted_encounters()) <= passed
    assert len(all_decks.admitted_encounters()) >= 60


def test_recipes_are_deterministic_functions_of_coordinates():
    first = all_decks.generate_recipe(3, 7, 11)
    second = all_decks.generate_recipe(3, 7, 11)
    assert first == second
    other = all_decks.generate_recipe(3, 8, 11)
    assert other != first


def test_recipe_decks_respect_bounds_and_pool():
    pool = set(all_decks.card_pool())
    for master in range(6):
        for job in range(4):
            recipe = all_decks.generate_recipe(master, 1, job)
            total = sum(entry.count for entry in recipe.deck)
            assert all_decks.MIN_DECK_SIZE <= total <= all_decks.MAX_DECK_SIZE
            assert all(entry.card_id in pool for entry in recipe.deck)
            assert all(entry.count <= all_decks.MAX_COPIES for entry in recipe.deck)
            assert recipe.encounter_id in all_decks.admitted_encounters()
            assert recipe.content_manifest_version == ALL_CONTENT


def test_splits_use_disjoint_seed_namespaces():
    train = all_decks.generate_recipe(0, 0, 0, 'train')
    validation = all_decks.generate_recipe(all_decks.HELDOUT_MASTER_SEEDS['validation'], 0, 0,
                                           'validation')
    test = all_decks.generate_recipe(all_decks.HELDOUT_MASTER_SEEDS['test'], 0, 0, 'test')
    assert all_decks.TRAIN_SEED_OFFSET <= train.environment_seed < all_decks.VALIDATION_SEED_OFFSET
    assert (all_decks.VALIDATION_SEED_OFFSET <= validation.environment_seed
            < all_decks.TEST_SEED_OFFSET)
    assert test.environment_seed >= all_decks.TEST_SEED_OFFSET
    assert test.environment_seed < 2**31
    assert len({train.environment_seed, validation.environment_seed,
                test.environment_seed}) == 3
    with pytest.raises(ValueError):
        all_decks.generate_recipe(0, 1, 0, 'validation')


def test_generator_rejects_bad_coordinates():
    for coordinates in ((-1, 0, 0), (1024, 0, 0), (0, -1, 0), (0, 0, 1024), (0, 0, 0, 'nope')):
        with pytest.raises(ValueError):
            all_decks.generate_recipe(*coordinates)


def test_recipe_validation_rejects_outside_pool_and_size():
    recipe = all_decks.generate_recipe(1, 2, 3)
    with pytest.raises(ValueError):
        recipe.__class__(**{**recipe.__dict__,
                            'deck': (recipe.deck[0].__class__('NOT_A_CARD', False, 1),)})
    with pytest.raises(ValueError):
        CombatScenario(
            recipe.schema_version, recipe.scenario_id, recipe.family_id, recipe.split,
            recipe.character_id, recipe.ascension, recipe.encounter_id,
            recipe.deck * 6, recipe.player_hp, recipe.player_max_hp, (), (),
            recipe.environment_seed, recipe.rules_version, recipe.content_manifest_version)


def test_manifest_freezes_pool_encounters_and_seed_ranges():
    manifest = all_decks.frozen_manifest()
    assert manifest['version'] == all_decks.VERSION
    assert manifest['pool_size'] == len(manifest['pool']) == 146
    assert manifest['encounters'] == list(all_decks.admitted_encounters())
    assert manifest['deck_size'] == [8, 30]
    assert manifest['heldout_master_seeds'] == {'validation': 189, 'test': 287}


def test_generated_recipe_builds_an_observable_environment():
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.rewards import V7
    for master in range(3):
        recipe = all_decks.generate_recipe(master, 0, 0)
        env = ObservableCombatAdapter(recipe, reward_version=V7,
                                      limits=EpisodeLimits(max_turns=4, max_decisions=20))
        assert env.information.known_deck
        assert len(env.information.known_deck) == sum(e.count for e in recipe.deck)
        legal = [i for i, allowed in enumerate(env.information.legal_mask) if allowed]
        assert legal

