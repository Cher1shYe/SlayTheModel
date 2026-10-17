"""Synthetic engineering fixtures: no validation/heldout manifests or training."""
from dataclasses import replace
import json
import numpy as np
import pytest
import torch

from sts2_env.az.content import EXPANSION_CONTENT, BOSS_CONTENT, BOSS_PROFILES
from sts2_env.az.content_expansion import FACTORIES, CODEC, descriptor
from sts2_env.az.config import SCHEMA_VERSION, RULES_VERSION, EpisodeLimits
from sts2_env.az.scenarios import CombatScenario, DeckEntry
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V7
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.entity_transition import public_snapshot, public_from_dict
from sts2_env.az.entity_replay import pack_observation, unpack_observation
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.information import BeliefSampler
from sts2_env.search.clone import clone_state


def recipe(names, upgraded=False, encounter='setup_shrinker_beetle_weak', seed=123):
    from collections import Counter
    entries = tuple(DeckEntry(n, upgraded, count) for n, count in Counter(names).items())
    return CombatScenario(SCHEMA_VERSION, f'engineering-{seed}', 'ironclad-colorless-audit',
        'train', 'Ironclad', 0, encounter, entries, 80, 80, (), (), seed,
        RULES_VERSION, EXPANSION_CONTENT)


def check(info):
    assert public_from_dict(json.loads(json.dumps(public_snapshot(info)))) == info
    obs = encode_entities(info)
    assert unpack_observation(pack_observation(obs)) == obs
    actions, mapping = action_candidates(info)
    assert set(mapping.values()) == set(np.flatnonzero(info.legal_mask))
    return obs


def particle(env, rng):
    p = BeliefSampler().sample(env.information, rng)
    assert p.info == env.information
    check(p.info)
    # Align hidden randomness ONLY for the native parity oracle.
    for attr in ('draw_pile', 'discard_pile'):
        pool = list(getattr(p.world, attr)); ordered = []
        for c in getattr(env.world, attr):
            twin = next(x for x in pool if (x.card_id, x.upgraded) == (c.card_id, c.upgraded))
            pool.remove(twin); ordered.append(twin)
        setattr(p.world, attr, ordered)
    p.world.rng = clone_state(env.world.rng)
    return p


@pytest.mark.parametrize('name', FACTORIES)
@pytest.mark.parametrize('upgraded', [False, True])
@pytest.mark.parametrize('encounter', [v['encounter'] for v in BOSS_PROFILES.values()])
def test_complete_native_public_particle_trajectory(name, upgraded, encounter):
    env = ObservableCombatAdapter(recipe([name]*3 + ['STRIKE_IRONCLAD']*3 + ['DEFEND_IRONCLAD']*3,
        upgraded, encounter), reward_version=V7, limits=EpisodeLimits(max_turns=8, max_decisions=60))
    rng = np.random.default_rng(78)
    while not env.outcome().done:
        check(env.information)
        p = particle(env, rng)
        action = int(rng.choice(np.flatnonzero(env.information.legal_mask)))
        predicted = p.step(action)
        env.step(action)
        assert predicted == env.information
    assert public_from_dict(json.loads(json.dumps(public_snapshot(env.information)))) == env.information


@pytest.mark.parametrize('name', FACTORIES)
@pytest.mark.parametrize('upgraded', [False, True])
def test_descriptors_and_codec(name, upgraded):
    token = name + ('+' if upgraded else '')
    card = CODEC._reference(token)
    d = descriptor(token)
    assert (d.cost, d.card_type) == (card.cost, card.card_type.value)
    assert CODEC.capture(CODEC.restore(CODEC.capture(card))) == CODEC.capture(card)
    assert set(card.keywords) <= {o.kind for o in d.effects}
    from sts2_env.az.boss_cards import CODEC as OLD
    with pytest.raises(ValueError): OLD.capture(card)


def test_version_and_scope_rejection():
    with pytest.raises(ValueError):
        replace(recipe(['FINESSE']*3 + ['STRIKE_IRONCLAD']*3), content_manifest_version=BOSS_CONTENT)
    with pytest.raises(ValueError): recipe(['SKIM']*3 + ['STRIKE_IRONCLAD']*3)
    with pytest.raises(ValueError): recipe(['REAVE']*3 + ['STRIKE_IRONCLAD']*3)
    with pytest.raises(ValueError): descriptor('RAMPAGE')


@pytest.mark.parametrize('name', FACTORIES)
def test_dynamic_mcts_rebuild_and_network_shape(name):
    from sts2_env.az.model_factory import create_transformer
    from sts2_env.az.dynamic_search import plan_dynamic
    from sts2_env.az.search_config import DYNAMIC_RISK
    torch.set_num_threads(1); torch.manual_seed(11)
    env = ObservableCombatAdapter(recipe([name]*3 + ['STRIKE_IRONCLAD']*3), reward_version=V7,
        limits=EpisodeLimits(max_turns=3, max_decisions=15))
    model = create_transformer('XS', EXPANSION_CONTENT, V7)
    before = env.information
    a = plan_dynamic(before, model, model_version='engineering', budget=3,
        search_seed=29, search_version=DYNAMIC_RISK)
    b = plan_dynamic(before, model, model_version='engineering', budget=3,
        search_seed=29, search_version=DYNAMIC_RISK)
    assert a.root_visits == b.root_visits
    assert a.action in action_candidates(before)[1]
    assert before == env.information


def arranged(names, hand, *, discard=(), upgraded=False, hp=80, encounter='setup_bygone_effigy_elite'):
    from sts2_env.az.information import observe
    env = ObservableCombatAdapter(recipe(names, upgraded, encounter), reward_version=V7)
    pool = env.world.hand + env.world.draw_pile
    def take(tokens):
        result = []
        for name in tokens:
            c = next(c for c in pool if c.card_id.name == name)
            pool.remove(c); result.append(c)
        return result
    env.world.hand = take(hand)
    env.world.discard_pile = take(discard)
    env.world.draw_pile = pool
    env.world.player.current_hp = hp
    env._information = observe(env.world, env.information.history, env.limits, 80, V7,
        EXPANSION_CONTENT, *env.public_initial)
    return env


def play(env, name, rng=None):
    rng = rng if rng is not None else np.random.default_rng(2)
    p = particle(env, rng)
    slot = env.information.hand.index(name)
    actions, mapping = action_candidates(env.information)
    key = next(a.action_key for a in actions if a.source_ref == f'hand/{slot}')
    a = mapping[key]
    expected = p.step(a); env.step(a)
    assert env.information == expected


@pytest.mark.parametrize('draw', ['FINESSE', 'FLASH_OF_STEEL', 'MASTER_OF_STRATEGY', 'SCRAWL'])
def test_headbutt_known_top_then_new_draw(draw):
    names = ['HEADBUTT', draw, 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'BLOOD_WALL']
    env = arranged(names, ['HEADBUTT', draw], discard=['DEFEND_IRONCLAD'])
    play(env, 'HEADBUTT')
    assert env.information.known_top[0] == 'DEFEND_IRONCLAD'
    play(env, draw)
    assert env.information.known_top == ()
    assert 'DEFEND_IRONCLAD' in env.information.hand


def test_blood_wall_body_slam_order_and_self_damage_death():
    names = ['BLOOD_WALL', 'BODY_SLAM', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT']
    env = arranged(names, ['BLOOD_WALL', 'BODY_SLAM'])
    play(env, 'BLOOD_WALL')
    assert env.information.player_hp == 78 and env.information.player_block == 16
    hp = env.information.enemy_hp
    play(env, 'BODY_SLAM')
    assert env.information.enemy_hp < hp
    dying = arranged(names, ['BLOOD_WALL'], hp=1)
    play(dying, 'BLOOD_WALL')
    assert dying.outcome().reward == -1 and dying.world.player.block == 0


def test_duplicate_reference_factory_identity():
    from sts2_env.cards.factory import create_reference_card
    from sts2_env.core.enums import CardId
    cards = [create_reference_card(CardId.SALVO) for _ in range(3)]
    assert len({c.instance_id for c in cards}) == 3
    env = arranged(['SALVO']*3 + ['STRIKE_IRONCLAD']*3, ['SALVO']*3)
    play(env, 'SALVO'); play(env, 'SALVO'); play(env, 'SALVO')
    assert env.information.discard.count('SALVO') == 3


@pytest.mark.parametrize('new', ['FINESSE', 'BLOOD_WALL', 'SCRAWL', 'PRODUCTION', 'SALVO'])
def test_armaments_upgrade_new_cards_and_rebuild(new):
    env = arranged(['ARMAMENTS', new, 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT'],
        ['ARMAMENTS', new])
    play(env, 'ARMAMENTS')
    assert env.information.hand == (new+'+',)
    check(env.information)
    particle(env, np.random.default_rng(3))


from sts2_env.core.card_pools import CardPoolId, CHARACTER_CARD_POOLS_BY_ID, COLORLESS_CARD_POOL
SCOPED_IDS = (*CHARACTER_CARD_POOLS_BY_ID[CardPoolId.IRONCLAD], *COLORLESS_CARD_POOL)


@pytest.mark.parametrize('cid', SCOPED_IDS, ids=lambda c: c.name)
@pytest.mark.parametrize('upgraded', [False, True])
def test_scope_native_factory_identity_and_execution(cid, upgraded):
    from sts2_env.cards.factory import create_card
    from tests.test_all_cards_unit_coverage import _make_smoke_combat, _resolve_all_pending_choices
    from sts2_env.core.enums import TargetType
    a, b = create_card(cid, upgraded), create_card(cid, upgraded)
    assert a.instance_id != b.instance_id
    assert a is not b and a != b
    combat = _make_smoke_combat(a)
    target = 0 if a.target_type in (TargetType.ANY_ENEMY, TargetType.ANY_ALLY) else None
    assert combat.play_card(0, target)
    _resolve_all_pending_choices(combat)
    assert combat.pending_choice is None


def test_inventory_exhaustive_scope_and_no_silent_admission():
    from scripts.audit_ironclad_colorless_coverage import inventory
    inv = inventory()
    assert inv['total'] == 151
    assert len({r['id'] for r in inv['rows']}) == 151
    assert inv['admitted'] - inv['original_admitted'] == len(FACTORIES)
    assert inv['pending'] + inv['admitted'] == 151
    for row in inv['rows']:
        if row['network'] == 'blocked':
            assert row['blockers'] and not row['descriptor_hashes']


@pytest.mark.parametrize('followup,damage', [('BULLY', 12), ('DISMANTLE', 24)])
def test_vulnerable_conditional_damage_and_hits(followup, damage):
    names = ['TREMBLE', followup, 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT']
    env = arranged(names, ['TREMBLE', followup], encounter='setup_shrinker_beetle_weak')
    play(env, 'TREMBLE')
    hp = env.information.enemy_hp
    play(env, followup)
    assert env.information.enemy_hp == hp-damage


def test_dismantle_without_vulnerable_is_single_hit():
    names = ['DISMANTLE', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT', 'BLOOD_WALL']
    env = arranged(names, ['DISMANTLE'], encounter='setup_shrinker_beetle_weak')
    hp = env.information.enemy_hp
    play(env, 'DISMANTLE')
    assert env.information.enemy_hp == hp-8


def test_molten_fist_then_dominate_reads_updated_target_stacks():
    names = ['TREMBLE', 'MOLTEN_FIST', 'DOMINATE', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT']
    env = arranged(names, ['TREMBLE', 'MOLTEN_FIST', 'DOMINATE'], encounter='setup_shrinker_beetle_weak')
    play(env, 'TREMBLE'); play(env, 'MOLTEN_FIST')
    assert env.information.vulnerable == 4
    play(env, 'DOMINATE')
    assert env.information.player_strength == 4


def test_artifact_consumes_tremble_and_blocks_vulnerable_synergy():
    names = ['TREMBLE', 'BULLY', 'DOMINATE', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT']
    env = arranged(names, ['TREMBLE', 'BULLY', 'DOMINATE'], encounter='setup_cubex_construct_normal')
    assert env.information.enemy_artifact == 1
    play(env, 'TREMBLE')
    assert env.information.enemy_artifact == 0 and env.information.vulnerable == 0
    durability = env.information.enemy_hp + env.information.enemy_block
    play(env, 'BULLY'); play(env, 'DOMINATE')
    assert env.information.enemy_hp + env.information.enemy_block == durability-4
    assert env.information.player_strength == 0


def test_primal_force_transforms_new_attacks_but_keeps_new_skills():
    env = arranged(['PRIMAL_FORCE', 'BULLY', 'BREAK', 'FINESSE', 'TAUNT', 'DEFEND_IRONCLAD'],
        ['PRIMAL_FORCE', 'BULLY', 'BREAK', 'FINESSE'])
    play(env, 'PRIMAL_FORCE')
    assert env.information.hand == ('GIANT_ROCK', 'GIANT_ROCK', 'FINESSE')
    particle(env, np.random.default_rng(9))


@pytest.mark.parametrize('seed', range(6))
def test_mixed_new_cards_with_existing_choices_generation_and_exhaust(seed):
    names = ['BLOOD_WALL', 'TREMBLE', 'MOLTEN_FIST', 'DOMINATE', 'BULLY',
        'DISMANTLE', 'SALVO', 'SCRAWL', 'FINESSE', 'PRODUCTION',
        'HEADBUTT', 'ARMAMENTS', 'PURITY', 'TRUE_GRIT', 'BURNING_PACT',
        'ANGER', 'PRIMAL_FORCE', 'STOMP', 'BODY_SLAM', 'FLASH_OF_STEEL']
    env = ObservableCombatAdapter(recipe(names, bool(seed%2), 'setup_test_subject_boss', seed+650),
        reward_version=V7, limits=EpisodeLimits(max_turns=10, max_decisions=80))
    rng = np.random.default_rng(seed+50)
    while not env.outcome().done:
        check(env.information)
        p = particle(env, rng)
        a = int(rng.choice(np.flatnonzero(env.information.legal_mask)))
        expected = p.step(a); env.step(a)
        assert env.information == expected


def test_dominate_history_persists_and_cannot_cross_legacy_boundary():
    env = arranged(['TREMBLE', 'DOMINATE', 'STRIKE_IRONCLAD', 'DEFEND_IRONCLAD', 'BASH', 'TAUNT'],
        ['TREMBLE', 'DOMINATE'])
    play(env, 'TREMBLE'); play(env, 'DOMINATE')
    assert env.information.history.dominate_strength == 2
    p = particle(env, np.random.default_rng(9))
    expected = p.step(0); env.step(0)
    assert expected == env.information
    assert env.information.player_strength == 2
    with pytest.raises(ValueError):
        replace(env.information, history=replace(env.information.history, dominate_strength=3)).validate()
