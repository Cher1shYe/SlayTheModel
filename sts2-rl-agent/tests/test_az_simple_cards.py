"""V3 synthetic interaction fixtures; no experiment or final heldout data."""
from dataclasses import replace
import numpy as np
import pytest
from tests.test_az_content_expansion import arranged, play, recipe, particle, check
from tests.test_az_player_abilities import step
from sts2_env.az.content_expansion import SIMPLE_FACTORIES
from sts2_env.az.content import EXPANSION_CONTENT, BOSS_PROFILES
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.rewards import V7
from sts2_env.az.config import EpisodeLimits


def test_conflagration_counts_finished_cards_not_hits():
    env=arranged(['STRIKE_IRONCLAD','TWIN_STRIKE','CONFLAGRATION','BASH','TAUNT','DEFEND_IRONCLAD'],
        ['STRIKE_IRONCLAD','TWIN_STRIKE','CONFLAGRATION'],encounter='setup_shrinker_beetle_weak')
    play(env,'STRIKE_IRONCLAD'); play(env,'TWIN_STRIKE')
    hp=env.information.enemy_hp; play(env,'CONFLAGRATION')
    assert hp-env.information.enemy_hp==12


def test_expect_a_fight_counts_remaining_hand_attacks():
    env=arranged(['EXPECT_A_FIGHT','STRIKE_IRONCLAD','TWIN_STRIKE','CONFLAGRATION','BASH','TAUNT'],
        ['EXPECT_A_FIGHT','STRIKE_IRONCLAD','TWIN_STRIKE','CONFLAGRATION','BASH'])
    play(env,'EXPECT_A_FIGHT'); assert env.information.energy==5


def test_feel_no_pain_second_wind_body_slam_order():
    env=arranged(['FEEL_NO_PAIN_CARD','SECOND_WIND','DEFEND_IRONCLAD','BASH','TAUNT','BODY_SLAM'],
        ['FEEL_NO_PAIN_CARD','SECOND_WIND','DEFEND_IRONCLAD','BASH','TAUNT','BODY_SLAM'], encounter='setup_shrinker_beetle_weak')
    play(env,'FEEL_NO_PAIN_CARD'); play(env,'SECOND_WIND')
    assert env.information.player_block==16
    assert len(env.information.history.exhausted_this_turn)==2
    hp=env.information.enemy_hp; play(env,'BODY_SLAM'); assert hp-env.information.enemy_hp==16


def test_fiend_fire_exhausts_before_hits_and_self_exhausts_last():
    env=arranged(['FEEL_NO_PAIN_CARD','FIEND_FIRE','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'],
        ['FEEL_NO_PAIN_CARD','FIEND_FIRE','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'], encounter='setup_shrinker_beetle_weak')
    play(env,'FEEL_NO_PAIN_CARD'); hp=env.information.enemy_hp; play(env,'FIEND_FIRE')
    assert hp-env.information.enemy_hp==28
    assert env.information.player_block==15 and len(env.information.exhaust)==5


def test_pacts_end_dynamic_gate_after_atomic_purity():
    env=arranged(['PURITY','PACTS_END','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'],
        ['PURITY','PACTS_END','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'])
    slot=env.information.hand.index('PACTS_END')
    assert not any(a.source_ref==f'hand/{slot}' for a in action_candidates(env.information)[0])
    play(env,'PURITY')
    options=env.information.choice.options
    chosen=[i for i,o in enumerate(options) if o.card.token!='PACTS_END'][:3]
    step(env, sum(1<<i for i in chosen))
    assert len(env.information.exhaust)==4
    slot=env.information.hand.index('PACTS_END')
    assert any(a.source_ref==f'hand/{slot}' for a in action_candidates(env.information)[0])
    play(env,'PACTS_END')


def test_exhaust_condition_and_next_turn_reset():
    env=arranged(['MASTER_OF_STRATEGY','FORGOTTEN_RITUAL','EVIL_EYE','BASH','TAUNT','DEFEND_IRONCLAD'],
        ['MASTER_OF_STRATEGY','FORGOTTEN_RITUAL','EVIL_EYE'])
    play(env,'MASTER_OF_STRATEGY'); play(env,'FORGOTTEN_RITUAL')
    assert env.information.energy==5
    play(env,'EVIL_EYE'); assert env.information.player_block==16
    step(env); assert not env.information.history.exhausted_this_turn
    with pytest.raises(ValueError): replace(env.information,history=replace(env.information.history,exhausted_this_turn=('FEED',))).validate()


def test_battle_trance_single_no_draw_and_restored_end_turn():
    env=arranged(['BATTLE_TRANCE']*2+['MASTER_OF_STRATEGY','POMMEL_STRIKE','TAUNT','DEFEND_IRONCLAD'],
        ['BATTLE_TRANCE','BATTLE_TRANCE','MASTER_OF_STRATEGY'])
    play(env,'BATTLE_TRANCE'); n=len(env.information.hand)
    play(env,'BATTLE_TRANCE')
    assert len(env.information.hand)==n-1 and dict(env.information.player_abilities)['NO_DRAW']==1
    play(env,'MASTER_OF_STRATEGY'); assert len(env.information.hand)==n-2
    step(env); assert 'NO_DRAW' not in dict(env.information.player_abilities)
    assert env.information.hand


@pytest.mark.parametrize('draw',['PILLAGE','IMPATIENCE','STOKE','BATTLE_TRANCE'])
def test_new_draw_consumes_known_top(draw):
    env=arranged(['HEADBUTT',draw,'STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'],
        ['HEADBUTT',draw,'TAUNT'],discard=['DEFEND_IRONCLAD'])
    play(env,'HEADBUTT'); assert env.information.known_top==('DEFEND_IRONCLAD',)
    play(env,draw)
    assert not env.information.known_top and 'DEFEND_IRONCLAD' in env.information.hand


def test_impatience_does_not_draw_with_attack_in_hand():
    env=arranged(['IMPATIENCE','BASH','STRIKE_IRONCLAD','DEFEND_IRONCLAD','TAUNT','FINESSE'],['IMPATIENCE','BASH'])
    play(env,'IMPATIENCE'); assert env.information.hand==('BASH',)


def test_stone_armor_reuses_plating_and_power_removal():
    env=arranged(['STONE_ARMOR']*2+['BASH','STRIKE_IRONCLAD','DEFEND_IRONCLAD','TAUNT'],['STONE_ARMOR']*2)
    play(env,'STONE_ARMOR');play(env,'STONE_ARMOR')
    assert dict(env.information.player_abilities)['PLATING']==8
    assert env.information.history.removed_powers.count('STONE_ARMOR')==2 and not env.information.discard
    step(env);assert dict(env.information.player_abilities)['PLATING']==7


@pytest.mark.parametrize('name',['SWORD_BOOMERANG','VOLLEY'])
def test_random_attack_has_one_candidate_and_public_target_set(name):
    env=arranged([name,'SALVO','DEFEND_IRONCLAD','TAUNT','FINESSE','BASH'],[name,'SALVO'],
        encounter='setup_fogmog_normal')
    # Retain the random attack while the second creature is naturally summoned.
    play(env,'SALVO'); step(env)
    actions=action_candidates(env.information)[0]
    for slot,t in enumerate(env.information.hand):
        if t==name:
            candidates=[a for a in actions if a.source_ref==f'hand/{slot}']
            assert len(candidates)==1
            assert candidates[0].target_refs==tuple(f'enemy/{e.slot}' for e in env.information.enemies if e.hp>0 and not e.reviving)
            play(env,name); break
    else: pytest.fail('Fixture should redraw random attack')


def test_x_payment_zero_and_multi_energy():
    env=arranged(['VOLLEY','EXPECT_A_FIGHT','BASH','STRIKE_IRONCLAD','CONFLAGRATION','TAUNT'],
        ['VOLLEY','EXPECT_A_FIGHT','BASH','STRIKE_IRONCLAD','CONFLAGRATION'])
    play(env,'EXPECT_A_FIGHT'); assert env.information.energy==5
    play(env,'VOLLEY'); assert env.information.history.payments[-1].energy==5 and env.information.energy==0
    # Zero energy X is legal and consumes the card without dealing damage.
    env=arranged(['VOLLEY','ETERNAL_ARMOR','BASH','STRIKE_IRONCLAD','CONFLAGRATION','TAUNT'],['VOLLEY','ETERNAL_ARMOR'])
    play(env,'ETERNAL_ARMOR'); hp=env.information.enemy_hp;play(env,'VOLLEY'); assert env.information.enemy_hp==hp


@pytest.mark.parametrize('seed',range(6))
def test_innate_opening_hand_and_reconstruction(seed):
    env=ObservableCombatAdapter(recipe(['MIND_BLAST']*3+['DRAMATIC_ENTRANCE']*3+['BASH']*3,seed=seed),reward_version=V7)
    assert len(env.information.hand)==6
    assert all(t in ('MIND_BLAST','DRAMATIC_ENTRANCE') for t in env.information.hand)
    particle(env,np.random.default_rng(seed));check(env.information)


@pytest.mark.parametrize('encounter',[v['encounter'] for v in BOSS_PROFILES.values()])
@pytest.mark.parametrize('seed',[4,7,15])
def test_mixed_simple_cards_with_powers_choices_and_transform(encounter,seed):
    names=list(SIMPLE_FACTORIES)[:10]+['BATTLE_TRANCE','EVIL_EYE','FORGOTTEN_RITUAL','PURITY',
        'FEEL_NO_PAIN_CARD','RAGE_CARD','ARMAMENTS','HEADBUTT','BODY_SLAM','PRIMAL_FORCE']
    env=ObservableCombatAdapter(recipe(names, bool(seed%2),encounter,seed),reward_version=V7,
        limits=EpisodeLimits(max_turns=12,max_decisions=100))
    rng=np.random.default_rng(seed)
    while not env.outcome().done:
        legal=np.flatnonzero(env.information.legal_mask)
        action=int(rng.choice(legal[1:] if len(legal)>1 else legal))
        step(env,action)
