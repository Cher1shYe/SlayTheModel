"""Nested strength and end-turn boundaries, independent synthetic scenarios."""
import json
import numpy as np
from tests.test_az_content_expansion import arranged,play
from tests.test_az_foundation_interactions import rearrange_remaining
from tests.test_az_generation_foundation import observe_fixture
from tests.test_az_player_abilities import step


def test_rupture_brand_strength_waits_for_nested_choice():
    env=arranged(['RUPTURE_CARD','DARK_EMBRACE_CARD','STRATAGEM','BRAND','DEFEND_IRONCLAD','BASH','TAUNT','STRIKE_IRONCLAD'],
        ['RUPTURE_CARD','DARK_EMBRACE_CARD','STRATAGEM'],upgraded=True)
    for c in ['RUPTURE_CARD+','DARK_EMBRACE_CARD+','STRATAGEM+']:play(env,c)
    rearrange_remaining(env,['BRAND','DEFEND_IRONCLAD','BASH'])
    env.world.discard_pile=list(env.world.draw_pile);env.world.draw_pile=[];env.world.energy=3;observe_fixture(env)
    play(env,'BRAND+');assert env.information.player_strength==0
    step(env,1)
    assert env.information.choice.mechanism=='power:STRATAGEM' and env.information.player_strength==0
    while env.information.choice:step(env,int(np.flatnonzero(env.information.legal_mask)[0]))
    assert env.information.player_strength==4


def test_ethereal_dark_embrace_choice_precedes_enemy_round():
    env=arranged(['DARK_EMBRACE_CARD','STRATAGEM']+['DEFEND_IRONCLAD']*3+['STRIKE_IRONCLAD']*3,
        ['DARK_EMBRACE_CARD','STRATAGEM'],upgraded=True,encounter='setup_fogmog_normal')
    play(env,'DARK_EMBRACE_CARD+');play(env,'STRATAGEM+')
    saw_end_boundary=False
    for _ in range(18):
        if env.outcome().done:break
        before=env.information
        action=int(np.flatnonzero(before.legal_mask)[0]) if before.choice else 0
        step(env,action)
        if env.information.choice and json.loads(env.information.execution)['end_stage']=='finish':
            saw_end_boundary=True
            assert env.information.history.enemy_moves==before.history.enemy_moves
    assert saw_end_boundary


def test_hidden_stomp_updates_do_not_expose_draw_traversal_order():
    from dataclasses import replace
    from tests.test_az_content_expansion import recipe
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.adapter import ObservableCombatAdapter
    from sts2_env.az.information import BeliefSampler
    from sts2_env.az.action_candidates import action_candidates
    from sts2_env.az.rewards import V7
    scenario=recipe(['STOMP','STOMP','STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT'])
    scenario=replace(scenario,deck=(DeckEntry('STOMP',False,1),DeckEntry('STOMP',True,1),
        *[DeckEntry(n,False,1) for n in ('STRIKE_IRONCLAD','DEFEND_IRONCLAD','BASH','TAUNT')]))
    env=ObservableCombatAdapter(scenario,reward_version=V7)
    rearrange_remaining(env,['STRIKE_IRONCLAD'])
    assert all(c.owner is env.world.player for c in env.world.draw_pile)
    actions,mapping=action_candidates(env.information)
    action=mapping[next(a.action_key for a in actions if a.source_ref=='hand/0')]
    predictions=[BeliefSampler().sample(env.information,np.random.default_rng(seed)).step(action) for seed in range(8)]
    env.step(action)
    assert all(p==env.information for p in predictions)
