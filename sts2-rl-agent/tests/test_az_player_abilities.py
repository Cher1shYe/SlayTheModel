"""Synthetic V2 ability interactions, never experiment or heldout data."""
from dataclasses import replace
import numpy as np
import pytest
from tests.test_az_content_expansion import arranged, play, particle, check, recipe
from sts2_env.az.content import EXPANSION_CONTENT, BOSS_PROFILES
from sts2_env.az.content_expansion import POWER_FACTORIES
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.rewards import V7
from sts2_env.az.risk_reward import public_risk, world_risk


def step(env, action=0):
    p = particle(env, np.random.default_rng(15))
    expected = p.step(action)
    env.step(action)
    assert expected == env.information
    assert public_risk(env.information) == world_risk(env.world, EXPANSION_CONTENT)
    if not env.outcome().done: check(env.information)


def test_rage_block_is_after_body_slam_and_expires():
    env = arranged(['RAGE_CARD','BODY_SLAM','BODY_SLAM','DEFEND_IRONCLAD','BASH','TAUNT'],
                   ['RAGE_CARD','BODY_SLAM','BODY_SLAM'], encounter='setup_shrinker_beetle_weak')
    play(env, 'RAGE_CARD')
    hp = env.information.enemy_hp
    play(env, 'BODY_SLAM')
    assert env.information.enemy_hp == hp and env.information.player_block == 3
    play(env, 'BODY_SLAM')
    assert env.information.enemy_hp == hp-3 and env.information.player_block == 6
    step(env)
    assert 'RAGE' not in dict(env.information.player_abilities)


def test_fasten_applies_only_defend_tag_and_not_trigger_block():
    env = arranged(['FASTEN','RAGE_CARD','DEFEND_IRONCLAD','FINESSE','BODY_SLAM','BASH'],
                   ['FASTEN','RAGE_CARD','DEFEND_IRONCLAD','FINESSE','BODY_SLAM'])
    play(env, 'FASTEN'); play(env, 'RAGE_CARD'); play(env, 'DEFEND_IRONCLAD')
    assert env.information.player_block == 10
    play(env, 'FINESSE')
    assert env.information.player_block == 14
    # Rage is unpowered and must not receive Fasten's bonus.
    env2 = arranged(['FASTEN','RAGE_CARD','BODY_SLAM','BASH','TAUNT','FINESSE'], ['FASTEN','RAGE_CARD','BODY_SLAM'])
    play(env2,'FASTEN'); play(env2,'RAGE_CARD'); play(env2,'BODY_SLAM')
    assert env2.information.player_block == 3
    obs = check(env.information)
    assert any(o.kind == 'defend_block_bonus' for e in obs.entities for o in e.effects)


def test_feel_no_pain_purity_continuation_and_body_slam():
    env = arranged(['FEEL_NO_PAIN_CARD','PURITY','BODY_SLAM','BASH','TAUNT','DEFEND_IRONCLAD'],
                   ['FEEL_NO_PAIN_CARD','PURITY','BODY_SLAM','BASH','TAUNT'])
    play(env,'FEEL_NO_PAIN_CARD'); play(env,'PURITY')
    assert env.information.choice is not None
    # Select two cards by public option tokens; exact choice continuation rebuilt each step.
    from sts2_env.az.action_candidates import action_candidates
    def decode_set(a, count): return tuple(i for i in range(count) if a & (1 << i))
    actions, mapping = action_candidates(env.information)
    # Pick any legal set of exactly two cards without consuming Body Slam.
    chosen = next(a for a in mapping.values() if len(decode_set(a, len(env.information.choice.options))) == 2
                  and all(env.information.choice.options[i].card.token != 'BODY_SLAM'
                          for i in decode_set(a, len(env.information.choice.options))))
    step(env, chosen)
    assert env.information.player_block == 9  # two chosen cards + Purity itself
    hp = env.information.enemy_hp
    play(env,'BODY_SLAM')
    assert env.information.enemy_hp < hp


@pytest.mark.parametrize('upgraded', [False, True])
def test_demon_form_delayed_strength_and_persistent_reconstruction(upgraded):
    env = arranged(['DEMON_FORM_CARD','DEFEND_IRONCLAD','BASH','TAUNT','FINESSE','TREMBLE'],
                   ['DEMON_FORM_CARD'], upgraded=upgraded)
    play(env,'DEMON_FORM_CARD' + ('+' if upgraded else ''))
    assert env.information.player_strength == 0
    step(env); assert env.information.player_strength == (3 if upgraded else 2)
    step(env); assert env.information.player_strength == (6 if upgraded else 4)
    with pytest.raises(ValueError): replace(env.information, player_strength=0).validate()


def test_barricade_single_stack_and_cross_turn_block():
    env = arranged(['BARRICADE_CARD']*2+['DEFEND_IRONCLAD','BASH','TAUNT','FINESSE'], ['BARRICADE_CARD','DEFEND_IRONCLAD'], upgraded=True)
    play(env,'BARRICADE_CARD+'); play(env,'DEFEND_IRONCLAD+')
    before = env.information.player_block
    step(env)
    assert env.information.player_block == before
    play(env,'BARRICADE_CARD+')
    assert dict(env.information.player_abilities)['BARRICADE'] == 1


def test_plating_ticks_expire_and_reward_risk_matches():
    env = arranged(['ETERNAL_ARMOR','DEFEND_IRONCLAD','BASH','TAUNT','FINESSE','TREMBLE'], ['ETERNAL_ARMOR'], encounter='setup_shrinker_beetle_weak')
    play(env,'ETERNAL_ARMOR')
    assert dict(env.information.player_abilities)['PLATING'] == 7
    for expected in range(6, -1, -1):
        step(env)
        assert dict(env.information.player_abilities).get('PLATING', 0) == expected
    with pytest.raises(ValueError): replace(env.information, player_abilities=(('PLATING', 2),)).validate()


@pytest.mark.parametrize('encounter', [v['encounter'] for v in BOSS_PROFILES.values()])
@pytest.mark.parametrize('seed', [12, 18, 22])
def test_mixed_abilities_exhaust_and_boss_trajectory(encounter, seed):
    names = list(POWER_FACTORIES) + ['OFFERING','BLOODLETTING','BODY_SLAM','BODY_SLAM',
        'TRUE_GRIT','PURITY','BURNING_PACT','HEADBUTT','FASTEN','ULTIMATE_DEFEND',
        'DEFEND_IRONCLAD','INFLAME','DOMINATE','TREMBLE']
    env = ObservableCombatAdapter(recipe(names, seed % 2 == 0, encounter, seed), reward_version=V7,
                                 limits=EpisodeLimits(max_turns=15, max_decisions=120))
    rng = np.random.default_rng(seed)
    while not env.outcome().done:
        legal = np.flatnonzero(env.information.legal_mask)
        action = int(rng.choice(legal[1:] if len(legal)>1 else legal))
        step(env, action)


def test_ability_contract_rejects_duplicates_unknown_and_old_content():
    env = arranged(['RAGE_CARD','BODY_SLAM','BASH','TAUNT','FINESSE','TREMBLE'], ['RAGE_CARD'])
    play(env,'RAGE_CARD')
    for powers in [(('RAGE',3),('RAGE',3)), (('DARK_EMBRACE',1),), (('RAGE',True),)]:
        with pytest.raises(ValueError): replace(env.information, player_abilities=powers).validate()
    with pytest.raises(ValueError): replace(recipe(['FASTEN']*3+['BASH']*3), content_manifest_version='ironclad-colorless-powers-v2')


@pytest.mark.parametrize('name', POWER_FACTORIES)
def test_search_rebuild_with_active_ability(name):
    import torch
    from sts2_env.az.model_factory import create_transformer
    from sts2_env.az.dynamic_search import plan_dynamic
    from sts2_env.az.search_config import DYNAMIC_RISK
    from sts2_env.az.action_candidates import action_candidates
    torch.set_num_threads(1); torch.manual_seed(4)
    env = arranged([name,'BODY_SLAM','BASH','TAUNT','FINESSE','TREMBLE'], [name,'BODY_SLAM','FINESSE'])
    play(env,name)
    before = env.information
    model = create_transformer('XS', EXPANSION_CONTENT, V7)
    args = dict(model_version='engineering-active-powers', budget=4, search_seed=30, search_version=DYNAMIC_RISK)
    a = plan_dynamic(before, model, **args)
    b = plan_dynamic(before, model, **args)
    assert a.root_visits == b.root_visits and a.action in action_candidates(before)[1]
    assert before == env.information


def test_ethereal_burn_plating_order_controls_boss_wounds_and_risk():
    from types import SimpleNamespace as N
    from sts2_env.az.boss import generation_after, MONSTER, CLAW
    from sts2_env.az.player_abilities import block_before_enemy
    before = N(monster_id=MONSTER, boss=N(phase=N(cursor=(1,'alive',CLAW,0))),
        player_block=2, player_hp=80, player_vulnerable=0, enemy_strength=0,
        player_abilities=(('PLATING',7),('FEEL_NO_PAIN',3)), hand=('DAZED','BURN'),
        content_version=EXPANSION_CONTENT, intent=('ATTACK',8,2),basic_statuses=(),
        enemies=(N(hp=100,reviving=False,intent=('ATTACK',8,2),strength=0,slot=0,vulnerable=0),))
    assert block_before_enemy(before) == 10  # 2 + 7 + 3 - 2
    assert generation_after(before, False, 1)[0].count == 1
    assert public_risk(before) == 6/80


def test_plating_reapplication_decays_total_once_per_round():
    env = arranged(['ETERNAL_ARMOR']*2+['DEFEND_IRONCLAD','BASH','TAUNT','FINESSE'], ['ETERNAL_ARMOR'],
                   encounter='setup_shrinker_beetle_weak')
    play(env,'ETERNAL_ARMOR'); step(env)
    play(env,'ETERNAL_ARMOR')
    assert dict(env.information.player_abilities)['PLATING'] == 13
    step(env)
    assert dict(env.information.player_abilities)['PLATING'] == 12


def test_terminal_observer_does_not_allocate_card_instances():
    from sts2_env.az.information import observe
    from sts2_env.cards import base
    env = arranged(['STRIKE_IRONCLAD','BASH','TAUNT','FINESSE','TREMBLE','FASTEN'], ['STRIKE_IRONCLAD'],
                   encounter='setup_shrinker_beetle_weak')
    env.world.enemies[0].current_hp = 1
    env._information = observe(env.world, env.information.history, env.limits, 80, V7,
        EXPANSION_CONTENT, *env.public_initial)
    play(env, 'STRIKE_IRONCLAD')
    assert env.outcome().termination_reason == 'win'
    counter = base._next_instance_id
    again = observe(env.world, env.information.history, env.limits, 80, V7,
        EXPANSION_CONTENT, *env.public_initial)
    assert again == env.information and base._next_instance_id == counter
