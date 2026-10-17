"""Synthetic pool closure/interaction contracts; no dataset or trained policy."""
import numpy as np
import pytest
from sts2_env.az.content_expansion import CODEC
from sts2_env.az.generation_contract import audit
from tests.test_az_content_expansion import arranged,play,check
from tests.test_az_foundation_interactions import rearrange_remaining
from tests.test_az_player_abilities import step


def test_native_generation_pools_are_complete_or_explicitly_deferred():
    report=audit()
    assert report['character_combat_count']==79
    for name in ('DISCOVERY','INFERNAL_BLADE','CALAMITY_CARD','JACKPOT'):
        assert report['pools'][name]['admitted'] and not report['pools'][name]['missing']
    for name in ('JACK_OF_ALL_TRADES','ENTROPY'):
        assert not report['pools'][name]['admitted']
        assert 'SPLASH' in report['pools'][name]['candidates']
    assert 'SPLASH' not in CODEC.factories


@pytest.mark.parametrize('token',audit()['pools']['DISCOVERY']['candidates'])
def test_every_native_generated_face_supports_free_clone_and_cleanup(token):
    c=CODEC._reference(token)
    c.set_temporary_free_this_turn()
    clone=c.clone(999999)
    state=CODEC.capture(clone)
    restored=CODEC.restore(state)
    assert CODEC.capture(restored)==state
    clone.end_of_turn_cleanup();restored.end_of_turn_cleanup()
    assert CODEC.capture(restored)==CODEC.capture(clone)


def observe_fixture(env):
    from sts2_env.az.information import observe
    from sts2_env.az.rewards import V7
    from sts2_env.az.content import EXPANSION_CONTENT
    env._information=observe(env.world,env.information.history,env.limits,80,V7,EXPANSION_CONTENT,*env.public_initial)


@pytest.mark.parametrize('source',['BRAND','SECOND_WIND','BURNING_PACT'])
def test_exhaust_draw_choice_preserves_followup_effects(source):
    env=arranged(['DARK_EMBRACE_CARD','STRATAGEM',source,'DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD'],
        ['DARK_EMBRACE_CARD','STRATAGEM'],upgraded=True)
    play(env,'DARK_EMBRACE_CARD+');play(env,'STRATAGEM+')
    rearrange_remaining(env,[source,'DEFEND_IRONCLAD','BASH'])
    env.world.discard_pile=list(env.world.draw_pile);env.world.draw_pile=[];env.world.energy=3;observe_fixture(env)
    play(env,source+'+')
    if source!='SECOND_WIND':
        choice=env.information.choice
        step(env,next(i+1 for i,o in enumerate(choice.options) if o.card.token=='DEFEND_IRONCLAD+'))
    assert env.information.choice and env.information.choice.mechanism=='power:STRATAGEM'
    check(env.information)
    for _ in range(12):
        if not env.information.choice:break
        step(env,int(np.flatnonzero(env.information.legal_mask)[0]))
    assert not env.information.choice and not env.world._play_continuations
    if source=='BRAND':assert env.information.player_strength==2
    if source=='SECOND_WIND':assert env.information.player_block==7


def test_vicious_shockwave_resumes_remaining_enemies():
    env=arranged(['VICIOUS_CARD','STRATAGEM','SHOCKWAVE','DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD'],
        ['VICIOUS_CARD','STRATAGEM'],upgraded=True,encounter='setup_nibbits_weak')
    play(env,'VICIOUS_CARD+');play(env,'STRATAGEM+')
    rearrange_remaining(env,['SHOCKWAVE'])
    env.world.discard_pile=list(env.world.draw_pile);env.world.draw_pile=[];env.world.energy=3;observe_fixture(env)
    play(env,'SHOCKWAVE+')
    assert env.information.choice
    for _ in range(12):
        if not env.information.choice:break
        step(env,int(np.flatnonzero(env.information.legal_mask)[0]))
    assert not env.information.choice
    assert all(e.vulnerable==5 for e in env.information.enemies)


def test_discovery_choice_dynamic_search_is_repeatable_without_training():
    import torch
    from sts2_env.az.model_factory import create_transformer
    from sts2_env.az.dynamic_search import plan_dynamic
    from sts2_env.az.search_config import DYNAMIC_RISK
    from sts2_env.az.content import EXPANSION_CONTENT
    from sts2_env.az.rewards import V7
    env=arranged(['DISCOVERY','BASH','TAUNT','STRIKE_IRONCLAD','DEFEND_IRONCLAD','FINESSE'],['DISCOVERY'])
    play(env,'DISCOVERY');before=env.information
    torch.set_num_threads(1);torch.manual_seed(12)
    model=create_transformer('XS',EXPANSION_CONTENT,V7)
    kwargs=dict(model_version='synthetic',budget=4,search_seed=81,search_version=DYNAMIC_RISK)
    a=plan_dynamic(before,model,**kwargs);b=plan_dynamic(before,model,**kwargs)
    assert a.root_visits==b.root_visits and before==env.information
