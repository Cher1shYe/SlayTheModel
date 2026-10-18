"""Seeded arbitrary-deck scenarios for all-content self-play.

Every recipe is a pure function of ``(split, master_seed, iteration, job_id)``.
Training seeds live in a fresh namespace; validation/test use fixed masters so a
frozen manifest can be replayed exactly.  Only encounters that pass the public
parity audit are admitted, and only cards in the admitted initial pool are used.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import random

from .config import RULES_VERSION, SCHEMA_VERSION
from .content import ALL_CONTENT
from .content_expansion import initial_factories
from .monster_registry import ENCOUNTERS
from .scenarios import CombatScenario, DeckEntry

VERSION = 'all-decks-v1'
FAMILY = 'all-content-arbitrary-v1'
MIN_DECK_SIZE = 8
MAX_DECK_SIZE = 30
MAX_COPIES = 4
UPGRADE_PROBABILITY = 0.3
DUPLICATE_PROBABILITY = 0.25
PLAYER_HP = 80
# Fresh namespace below 2^31 (scenario seeds are capped at 2^31).  Earlier
# generators occupy [0, 2^30), so this contract starts at exactly 2^30.
TRAIN_SEED_OFFSET = 2**30
TRAIN_SEED_SPAN = 2**29
VALIDATION_SEED_OFFSET = TRAIN_SEED_OFFSET + TRAIN_SEED_SPAN
TEST_SEED_OFFSET = VALIDATION_SEED_OFFSET + 2**28
HELDOUT_SEED_SPAN = 2**28
HELDOUT_MASTER_SEEDS = {'validation': 189, 'test': 287}
PARITY_REPORT = Path(__file__).resolve().parents[2] / 'docs' / 'all_encounter_parity.json'
ROBUSTNESS_REPORT = Path(__file__).resolve().parents[2] / 'docs' / 'all_encounter_robustness.json'


def card_pool():
    """Sorted base tokens admitted as initial player cards (146 in v6)."""
    return tuple(sorted(initial_factories()))


def admitted_encounters():
    """Parity-passing encounters that also survive varied-deck robustness probes."""
    if not PARITY_REPORT.exists():
        raise ValueError('Encounter parity report is required before generating recipes')
    report = json.loads(PARITY_REPORT.read_text(encoding='utf-8'))
    if report.get('content') != ALL_CONTENT or not report.get('results'):
        raise ValueError('Encounter parity report belongs to another content version')
    passed = {name for name, entry in report['results'].items() if entry.get('status') == 'pass'}
    if not passed or passed - set(ENCOUNTERS):
        raise ValueError('Encounter parity report contains unknown encounters')
    robustness = json.loads(ROBUSTNESS_REPORT.read_text(encoding='utf-8'))
    if robustness.get('content') != ALL_CONTENT or not robustness.get('robust'):
        raise ValueError('Encounter robustness report belongs to another content version')
    robust = set(robustness['robust'])
    if not robust <= passed:
        raise ValueError('Robustness report contains encounters that failed parity')
    if robust != passed and set(robustness.get('unstable', ())) != passed - robust:
        raise ValueError('Robustness report does not explain every excluded encounter')
    return tuple(sorted(robust))


def _rng(*coordinates):
    digest = sha256(('|'.join(str(value) for value in (VERSION, *coordinates)))
                    .encode('utf-8')).digest()
    return random.Random(int.from_bytes(digest, 'big'))


def _seed(split, master_seed, iteration, job_id):
    base, span = {'train': (TRAIN_SEED_OFFSET, TRAIN_SEED_SPAN),
                  'validation': (VALIDATION_SEED_OFFSET, HELDOUT_SEED_SPAN),
                  'test': (TEST_SEED_OFFSET, HELDOUT_SEED_SPAN)}[split]
    digest = sha256(f'{VERSION}|{split}|{master_seed}|{iteration}|{job_id}'.encode()).digest()
    return base + int.from_bytes(digest[:8], 'big') % span


def sample_deck(rng):
    """Any admitted cards, bounded size and copies; upgrade flag per entry."""
    pool = list(card_pool())
    size = rng.randint(MIN_DECK_SIZE, MAX_DECK_SIZE)
    entries = Counter()
    if rng.random() < DUPLICATE_PROBABILITY:
        copies = Counter()
        while sum(copies.values()) < size:
            token = pool[rng.randrange(len(pool))]
            if copies[token] >= MAX_COPIES:
                continue
            copies[token] += 1
            entries[(token, rng.random() < UPGRADE_PROBABILITY)] += 1
    else:
        rng.shuffle(pool)
        for token in pool[:size]:
            entries[(token, rng.random() < UPGRADE_PROBABILITY)] += 1
    return tuple(DeckEntry(token, upgraded, count)
                 for (token, upgraded), count in sorted(entries.items()))


def generate_recipe(master_seed, iteration, job_id, split='train'):
    if (type(master_seed) is not int or not 0 <= master_seed < 1024
            or type(iteration) is not int or not 0 <= iteration < 1024
            or type(job_id) is not int or not 0 <= job_id < 1024
            or split not in ('train', 'validation', 'test')):
        raise ValueError('Unsupported generator coordinates')
    if split != 'train' and iteration != 0:
        raise ValueError('Held-out recipes are fixed at iteration zero')
    rng = _rng(split, master_seed, iteration, job_id)
    encounters = admitted_encounters()
    encounter = encounters[rng.randrange(len(encounters))]
    deck = sample_deck(rng)
    recipe = CombatScenario(
        SCHEMA_VERSION, f'all-{split}-{master_seed:04d}-{iteration:04d}-{job_id:04d}',
        FAMILY, split, 'Ironclad', 0, encounter, deck, PLAYER_HP, PLAYER_HP, (), (),
        _seed(split, master_seed, iteration, job_id), RULES_VERSION, ALL_CONTENT)
    validate_recipe(recipe)
    return recipe


STRATIFIED_VERSION = 'all-stratified-v1'
MAX_STRATIFIED_EPISODES = 1024


def stratified_recipe(iteration, job_id, split='train'):
    """Balanced encounter cycles and independent decks; seeds never collide.

    Odd affine permutation is bijective modulo each power-of-two seed span.
    Legacy generate_recipe stays unchanged for historical fixtures and test data.
    """
    if (type(iteration) is not int or not 0 <= iteration < 1024
            or type(job_id) is not int or not 0 <= job_id < MAX_STRATIFIED_EPISODES
            or split not in ('train', 'validation') or (split != 'train' and iteration != 0)):
        raise ValueError('Unsupported stratified coordinates')
    encounters = admitted_encounters()
    rng = _rng(STRATIFIED_VERSION, split, iteration, job_id)
    index = iteration * MAX_STRATIFIED_EPISODES + job_id
    base, span = ((TRAIN_SEED_OFFSET, TRAIN_SEED_SPAN) if split == 'train'
                  else (VALIDATION_SEED_OFFSET, HELDOUT_SEED_SPAN))
    seed = base + (1664525 * index + 1013904223) % span
    return validate_recipe(CombatScenario(
        SCHEMA_VERSION, f'all-{split}-stratified-{iteration:04d}-{job_id:04d}',
        FAMILY, split, 'Ironclad', 0, encounters[job_id % len(encounters)], sample_deck(rng),
        PLAYER_HP, PLAYER_HP, (), (), seed, RULES_VERSION, ALL_CONTENT))


def validate_recipe(recipe):
    if type(recipe) is not CombatScenario or recipe.content_manifest_version != ALL_CONTENT:
        raise ValueError('Recipe is not all-content')
    if recipe.encounter_id not in admitted_encounters():
        raise ValueError('Recipe encounter has not passed the parity audit')
    pool = set(card_pool())
    total = sum(entry.count for entry in recipe.deck)
    if not MIN_DECK_SIZE <= total <= MAX_DECK_SIZE:
        raise ValueError('Recipe deck size outside the arbitrary-deck bounds')
    copies = Counter()
    seen = set()
    for entry in recipe.deck:
        if (entry.card_id not in pool or type(entry.upgraded) is not bool
                or type(entry.count) is not int or entry.count < 1):
            raise ValueError('Recipe card is outside the admitted pool')
        key = (entry.card_id, entry.upgraded)
        if key in seen:
            raise ValueError('Duplicate deck entry')
        seen.add(key)
        copies[entry.card_id] += entry.count
    if max(copies.values()) > MAX_COPIES:
        raise ValueError('Recipe exceeds the copy limit')
    return recipe


def recipe_from_document(document):
    """Rebuild a frozen protocol recipe from its stored document."""
    parts = document['scenario_id'].split('-')
    if len(parts) < 2 or parts[0] != 'all' or parts[1] not in ('train', 'validation', 'test'):
        raise ValueError('Unrecognised frozen recipe identity')
    deck = tuple(DeckEntry(card, upgraded, count)
                 for card, upgraded, count in document['deck'])
    return validate_recipe(CombatScenario(
        SCHEMA_VERSION, document['scenario_id'], FAMILY, parts[1], 'Ironclad', 0,
        document['encounter'], deck, document['player_hp'], document['player_hp'], (), (),
        document['seed'], RULES_VERSION, ALL_CONTENT))


def frozen_manifest():
    pool = card_pool()
    return {
        'version': VERSION, 'content': ALL_CONTENT, 'family': FAMILY,
        'sampling': {'version': STRATIFIED_VERSION, 'encounter_rule': 'job_id % encounter_count',
                     'per_encounter': 4, 'max_episodes': MAX_STRATIFIED_EPISODES},
        'pool_size': len(pool), 'pool': list(pool),
        'encounters': list(admitted_encounters()),
        'deck_size': [MIN_DECK_SIZE, MAX_DECK_SIZE], 'max_copies': MAX_COPIES,
        'upgrade_probability': UPGRADE_PROBABILITY,
        'duplicate_probability': DUPLICATE_PROBABILITY,
        'train_seed_offset': TRAIN_SEED_OFFSET, 'heldout_master_seeds': dict(HELDOUT_MASTER_SEEDS),
        'seed_ranges': 'train [2^30, 1.5*2^30); validation [1.5*2^30, 1.75*2^30); test [1.75*2^30, 2^31)', 'seed_cap': 2**31,
        'note': 'Only parity-passing encounters and admitted initial cards; '
                'held-out splits never share coordinates with training.',
    }


