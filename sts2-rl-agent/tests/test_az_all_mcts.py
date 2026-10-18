"""All-encounter MCTS pipeline: particle parity, entity encoding, dynamic search.

Particles sample their own hidden future; exact parity is asserted only against
the native oracle after aligning the hidden chance stream and pile order, as in
the V4 tests.
"""
from collections import Counter
import numpy as np
import pytest
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.all_content import roster_rows
from sts2_env.az.config import EpisodeLimits, SCHEMA_VERSION, RULES_VERSION
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.content_expansion import CODEC
from sts2_env.az.dynamic_search import plan_dynamic
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.information import BeliefSampler
from sts2_env.az.model_factory import create_transformer
from sts2_env.az.rewards import V7
from sts2_env.az.scenarios import CombatScenario, DeckEntry
from sts2_env.az.search_config import DYNAMIC_RISK
from sts2_env.search.clone import clone_state

DECK = (['STRIKE_IRONCLAD'] * 3 + ['DEFEND_IRONCLAD'] * 3
        + ['BASH', 'GOLD_AXE', 'BOLAS', 'FEED'])
ENCOUNTERS = ['setup_nibbits_normal', 'setup_slimes_weak', 'setup_cultists_normal',
              'setup_bowlbugs_normal', 'setup_axebots_normal', 'setup_chompers_normal',
              'setup_waterfall_giant_boss', 'setup_kaiser_crab_boss']


def recipe(encounter, seed=21):
    entries = tuple(DeckEntry(name, False, count) for name, count in Counter(DECK).items())
    return CombatScenario(SCHEMA_VERSION, f'all-{encounter}-{seed}', 'ironclad-colorless-audit',
                          'train', 'Ironclad', 0, encounter, entries, 80, 80, (), (), seed,
                          RULES_VERSION, ALL_CONTENT)


def env_for(encounter, seed=21, turns=6, decisions=40):
    return ObservableCombatAdapter(recipe(encounter, seed), reward_version=V7,
                                   limits=EpisodeLimits(max_turns=turns, max_decisions=decisions))


def aligned_particle(env, rng):
    particle = BeliefSampler().sample(env.information, rng)
    assert particle.info == env.information
    for attr in ('draw_pile', 'discard_pile'):
        pool = list(getattr(particle.world, attr))
        ordered = []
        for card in getattr(env.world, attr):
            twin = next(x for x in pool if CODEC.capture(x) == CODEC.capture(card))
            pool.remove(twin)
            ordered.append(twin)
        setattr(particle.world, attr, ordered)
    particle.world.rng = clone_state(env.world.rng)
    return particle


@pytest.mark.parametrize('encounter', ENCOUNTERS)
def test_aligned_particle_parity_over_random_steps(encounter):
    env = env_for(encounter)
    rng = np.random.default_rng(7)
    steps = 0
    while not env.outcome().done and steps < 12:
        particle = aligned_particle(env, rng)
        legal = np.flatnonzero(env.information.legal_mask)
        action = int(rng.choice(legal))
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
        steps += 1
    assert steps > 0


@pytest.mark.parametrize('encounter', ENCOUNTERS[:4])
def test_entity_encoding_is_deterministic_and_complete(encounter):
    env = env_for(encounter)
    first = encode_entities(env.information)
    second = encode_entities(env.information)
    assert first == second
    assert first.content_version == ALL_CONTENT
    assert sum(e.kind == 'enemy' for e in first.entities) == len(env.information.enemies)
    assert {a.source_ref for a in first.actions if a.source_ref} >= {'hand/0'}


@pytest.mark.parametrize('encounter', ENCOUNTERS[:4])
def test_dynamic_mcts_rebuild_repeatability(encounter):
    torch.set_num_threads(1)
    torch.manual_seed(11)
    env = env_for(encounter, turns=3, decisions=15)
    model = create_transformer('XS', ALL_CONTENT, V7)
    before = env.information
    first = plan_dynamic(before, model, model_version='all-probe', budget=3, search_seed=5,
                         search_version=DYNAMIC_RISK)
    second = plan_dynamic(before, model, model_version='all-probe', budget=3, search_seed=5,
                          search_version=DYNAMIC_RISK)
    assert first.root_visits == second.root_visits
    assert first.action in {a.action_key for a in encode_entities(before).actions}
    assert before == env.information


def test_reward_ledger_is_primary_only():
    env = env_for('setup_nibbits_normal')
    ledger, rows, (initial, final, maximum) = roster_rows(env.information.enemies)
    assert initial == sum(slot.initial_hp for slot in env.information.enemies)
    assert final == sum(slot.hp for slot in env.information.enemies)
    assert maximum == sum(slot.max_hp for slot in env.information.enemies)


def test_wrong_content_for_all_env_is_rejected():
    from sts2_env.az.dynamic_search import plan_dynamic
    env = env_for('setup_nibbits_normal', turns=2, decisions=5)
    other = create_transformer('XS', 'ironclad-colorless-foundation-v4', V7)
    with pytest.raises(ValueError):
        plan_dynamic(env.information, other, model_version='mismatch', budget=1, search_seed=1,
                     search_version=DYNAMIC_RISK)
