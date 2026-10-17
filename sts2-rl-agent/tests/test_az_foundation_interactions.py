"""Public V4 status, reveal and continuation interactions."""
import pytest
import numpy as np
from tests.test_az_content_expansion import arranged,play,check
from tests.test_az_player_abilities import step
from sts2_env.az.foundation import amount
from sts2_env.az.risk_reward import public_risk,world_risk
from sts2_env.az.content import EXPANSION_CONTENT


def test_beat_down_pending_batch_hides_shuffle_and_rebuilds():
    from sts2_env.az.information import observe,BeliefSampler
    from sts2_env.az.execution import capture
    from sts2_env.az.content_expansion import CODEC
    from sts2_env.az.rewards import V7
    for seed in range(30):
        env=arranged(['BEAT_DOWN','HEADBUTT','BASH','STRIKE_IRONCLAD','DEFEND_IRONCLAD','TAUNT'],['BEAT_DOWN','DEFEND_IRONCLAD'])
        env.world.discard_pile=list(env.world.draw_pile);env.world.draw_pile=[]
        for _ in range(seed):env.world.shuffle_rng.next_float()
        env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
        play(env,'BEAT_DOWN')
        frames=[f for f in env.world._play_continuations if f['kind']=='random_batch']
        if env.information.choice and frames:break
    else:raise AssertionError('No nested batch fixture')
    before=capture(env.world,CODEC)
    frames[0]['cards'].reverse()
    assert capture(env.world,CODEC)==before
    p=BeliefSampler().sample(env.information,np.random.default_rng(99))
    assert p.info==env.information
    check(p.info)
    while p.info.choice:
        p.step(int(np.flatnonzero(p.info.legal_mask)[0]))
    assert not p.world._play_continuations and not p.world.play_pile


def test_dark_embrace_fiend_fire_pauses_exhaust_hooks_and_suffix():
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    env=arranged(['DARK_EMBRACE_CARD','STRATAGEM','FEEL_NO_PAIN_CARD','FIEND_FIRE','DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD'],
        ['DARK_EMBRACE_CARD','STRATAGEM','FEEL_NO_PAIN_CARD'],upgraded=True)
    for n in ('DARK_EMBRACE_CARD+','STRATAGEM+','FEEL_NO_PAIN_CARD+'):play(env,n)
    rearrange_remaining(env,['FIEND_FIRE','DEFEND_IRONCLAD','BASH'])
    env.world.discard_pile=list(env.world.draw_pile);env.world.draw_pile=[];env.world.energy=3
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
    play(env,'FIEND_FIRE+')
    assert env.information.choice and env.information.player_block==0
    check(env.information)
    for _ in range(8):
        if not env.information.choice:break
        step(env,int(np.flatnonzero(env.information.legal_mask)[0]))
    assert not env.information.choice and not env.world._play_continuations
    assert 'DEFEND_IRONCLAD+' in env.information.exhaust and 'BASH+' in env.information.exhaust


def test_weak_negative_strength_and_colossus_risk():
    env=arranged(['DARK_SHACKLES','UPPERCUT','COLOSSUS_CARD','TAUNT','BASH','DEFEND_IRONCLAD'],
      ['DARK_SHACKLES','UPPERCUT','COLOSSUS_CARD'],encounter='setup_shrinker_beetle_weak')
    play(env,'DARK_SHACKLES');assert env.information.enemy_strength==-9
    play(env,'UPPERCUT');play(env,'COLOSSUS_CARD')
    assert amount(env.information,0,'WEAK')==1
    assert public_risk(env.information)==world_risk(env.world,EXPANSION_CONTENT)
    step(env)
    assert env.information.enemy_strength==0 and amount(env.information,0,'WEAK')==0


def test_prowess_temporary_strength_and_pyre():
    env=arranged(['PROWESS','SETUP_STRIKE_CARD','DEFEND_IRONCLAD','TAUNT','BASH','PYRE'],
      ['PROWESS','SETUP_STRIKE_CARD','DEFEND_IRONCLAD'])
    play(env,'PROWESS');play(env,'SETUP_STRIKE_CARD');play(env,'DEFEND_IRONCLAD')
    assert env.information.player_strength==3 and env.information.player_block==6
    step(env);assert env.information.player_strength==1
    env=arranged(['PYRE','PYRE','TAUNT','BASH','DEFEND_IRONCLAD','STRIKE_IRONCLAD'],['PYRE'])
    play(env,'PYRE');assert env.information.max_energy==4
    step(env);assert env.information.energy==4


def test_brand_choice_strength_only_after_resolution():
    env=arranged(['BRAND','DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD','FINESSE'],['BRAND','DEFEND_IRONCLAD','BASH'])
    play(env,'BRAND');assert env.information.choice and env.information.player_strength==0
    step(env,1);assert env.information.player_strength==1


@pytest.mark.parametrize('name',['SECRET_TECHNIQUE','SECRET_WEAPON','SEEKER_STRIKE'])
def test_draw_reveal_choices_roundtrip_and_rebuild(name):
    env=arranged([name,'DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD','FINESSE'],[name])
    play(env,name)
    assert env.information.choice is not None
    assert all(o.pile=='revealed' for o in env.information.choice.options)
    check(env.information);step(env,1)


def test_thinking_ahead_topdeck_then_cinder_exhaust():
    env=arranged(['THINKING_AHEAD','CINDER','CINDER','BASH','TAUNT','DEFEND_IRONCLAD'],['THINKING_AHEAD','CINDER'])
    play(env,'THINKING_AHEAD')
    idx=next(i for i,o in enumerate(env.information.choice.options) if o.card.token=='CINDER')
    step(env,idx+1);assert env.information.known_top==('CINDER',)
    # Play another Cinder if the draw supplied it; the known top must be consumed.
    if 'CINDER' in env.information.hand:
        play(env,'CINDER');assert not env.information.known_top


def test_nested_cascade_havoc_choice_public_stack_roundtrip():
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    env=arranged(['CASCADE','HAVOC','TRUE_GRIT','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH'],
        ['CASCADE','DEFEND_IRONCLAD','BASH'],upgraded=True)
    pool=list(env.world.draw_pile)
    env.world.draw_pile=[next(c for c in pool if c.card_id.name==n) for n in ['HAVOC','STRIKE_IRONCLAD','TRUE_GRIT']]
    env.world.energy=1
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
    play(env,'CASCADE+')
    assert env.information.execution and env.information.choice
    check(env.information)
    step(env,1)
    assert not env.information.choice and not env.world.play_pile
    assert env.information.history.played_this_turn==('CASCADE+','HAVOC+','TRUE_GRIT+','STRIKE_IRONCLAD+')


def test_nested_execution_features_expose_parent_and_queue():
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    from sts2_env.az.entity_encoder import NUMERIC_FIELDS
    env=arranged(['CASCADE','HAVOC','TRUE_GRIT','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH'],
        ['CASCADE','DEFEND_IRONCLAD','BASH'],upgraded=True)
    pool=list(env.world.draw_pile)
    env.world.draw_pile=[next(c for c in pool if c.card_id.name==n) for n in ['HAVOC','STRIKE_IRONCLAD','TRUE_GRIT']]
    env.world.energy=1
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
    play(env,'CASCADE+')
    obs=check(env.information)
    field=lambda e,n:round(e.numbers[NUMERIC_FIELDS.index(n)]*100)
    leaf=next(e for e in obs.entities if e.ref=='pending')
    assert field(leaf,'execution_depth')==3 and field(leaf,'execution_auto')==1
    assert field(leaf,'execution_force_exhaust')==1 and field(leaf,'execution_after_hook')==1
    assert sorted(field(e,'execution_queue_position') for e in obs.entities if field(e,'execution_queue_position'))==[1]
    assert field(next(e for e in obs.entities if e.ref=='state'),'completed_plays')==0


def test_havoc_consumes_known_top():
    env=arranged(['HEADBUTT','HAVOC','DOMINATE','TAUNT','DEFEND_IRONCLAD','BASH'],
        ['DOMINATE','HEADBUTT','HAVOC','TAUNT'])
    play(env,'TAUNT')
    # Use Headbutt to put the observable Taunt on top.
    play(env,'HEADBUTT')
    if env.information.choice:
        idx=next(i for i,o in enumerate(env.information.choice.options) if o.card.token=='TAUNT')
        step(env,idx+1)
    assert env.information.known_top[0]=='TAUNT'
    play(env,'HAVOC')
    assert not env.information.known_top
    check(env.information)


@pytest.mark.parametrize('token',['AGGRESSION_CARD','DRUM_OF_BATTLE_CARD'])
def test_pile_powers_end_turn_particle_roundtrip(token):
    env=arranged([token,'STRIKE_IRONCLAD','BASH','DEFEND_IRONCLAD','FINESSE','TAUNT'],
        [token,'STRIKE_IRONCLAD'])
    play(env,token);play(env,'STRIKE_IRONCLAD')
    step(env)
    if token=='AGGRESSION_CARD':
        assert any(t.endswith('+') for t in env.information.hand)
    else:
        assert env.information.history.exhausted_this_turn
    check(env.information)


@pytest.mark.parametrize('source',['HAVOC','DRUM_OF_BATTLE_CARD','FINESSE'])
def test_stratagem_shuffle_resumes_pile_operation(source):
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    env=arranged(['STRATAGEM',source,'STRIKE_IRONCLAD','BASH','DEFEND_IRONCLAD','TAUNT'],
        ['STRATAGEM',source],upgraded=True)
    env.world.discard_pile.extend(env.world.draw_pile);env.world.draw_pile=[]
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
    play(env,'STRATAGEM+');play(env,source+'+')
    assert env.information.choice.mechanism=='power:STRATAGEM'
    check(env.information)
    step(env,1)
    assert env.information.choice is None
    assert env.world._pending_pile_operation is None and not env.world.play_pile
    if source=='DRUM_OF_BATTLE_CARD':
        step(env)
        while env.information.choice:step(env,1)
    check(env.information)


def test_stratagem_without_active_card_and_multi_selection():
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    env=arranged(['STRATAGEM','STRATAGEM','STRIKE_IRONCLAD','BASH','DEFEND_IRONCLAD','TAUNT'],
        ['STRATAGEM','STRATAGEM'],upgraded=True)
    env.world.discard_pile.extend(env.world.draw_pile);env.world.draw_pile=[]
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)
    play(env,'STRATAGEM+');play(env,'STRATAGEM+');step(env)
    assert env.information.pending_card is None and env.information.choice.max_choices==2
    check(env.information);step(env,1);check(env.information);step(env,2);step(env,0)
    assert env.information.choice is None
    check(env.information)


def rearrange_remaining(env,hand_names,draw_first=()):
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    pool=env.world.hand+env.world.draw_pile+env.world.discard_pile
    def take(name):
        c=next(c for c in pool if c.card_id.name==name);pool.remove(c);return c
    env.world.hand=[take(n) for n in hand_names]
    front=[take(n) for n in draw_first]
    env.world.draw_pile=front+pool;env.world.discard_pile=[]
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)


def test_hellraiser_nested_seeker_draw_finishes_before_no_draw():
    env=arranged(['HELLRAISER_CARD','BATTLE_TRANCE','SEEKER_STRIKE','DEFEND_IRONCLAD','BASH','TAUNT','FINESSE','STRIKE_IRONCLAD'],
        ['HELLRAISER_CARD','BATTLE_TRANCE'],upgraded=True)
    play(env,'HELLRAISER_CARD+')
    rearrange_remaining(env,['BATTLE_TRANCE'],['SEEKER_STRIKE'])
    play(env,'BATTLE_TRANCE+')
    assert env.information.choice and 'NO_DRAW' not in dict(env.information.player_abilities)
    step(env,1)
    assert not env.information.choice and dict(env.information.player_abilities)['NO_DRAW']==1
    assert not env.world.play_pile and env.world._pending_draw is None
    check(env.information)


def test_mayhem_choice_precedes_drum_and_normal_draw():
    env=arranged(['MAYHEM_CARD','DRUM_OF_BATTLE_CARD','TRUE_GRIT','STRIKE_IRONCLAD','BASH','DEFEND_IRONCLAD','TAUNT','FINESSE'],
        ['MAYHEM_CARD','DRUM_OF_BATTLE_CARD'],upgraded=True)
    play(env,'MAYHEM_CARD+');play(env,'DRUM_OF_BATTLE_CARD+')
    rearrange_remaining(env,['BASH','DEFEND_IRONCLAD'],['TRUE_GRIT','STRIKE_IRONCLAD'])
    step(env)
    # The previous hand is discarded before the next turn; True Grit may have no choice.
    if env.information.choice:step(env,1)
    assert not env.world._pending_hand_draw_hooks
    assert 'STRIKE_IRONCLAD+' in env.information.exhaust
    check(env.information)


@pytest.mark.parametrize('encounter',['setup_shrinker_beetle_weak','setup_test_subject_boss'])
def test_stampede_choice_does_not_advance_enemy_history_early(encounter):
    env=arranged(['STAMPEDE_CARD','SEEKER_STRIKE','BASH','DEFEND_IRONCLAD','TAUNT','FINESSE'],
        ['STAMPEDE_CARD','SEEKER_STRIKE'],upgraded=True,encounter=encounter)
    play(env,'STAMPEDE_CARD+');step(env)
    assert env.information.choice and env.information.turn==1
    assert not env.information.history.enemy_moves
    step(env,1)
    assert env.information.turn==2 and len(env.information.history.enemy_moves)==1
    check(env.information)
