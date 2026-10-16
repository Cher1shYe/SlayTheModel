from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import SUMMON_CONTENT, UP_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
from sts2_env.az.generation import SUMMON_STRATA, generate_recipe, frozen_manifest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V5
from sts2_env.az.information import BeliefSampler, observe
from sts2_env.az.encoder import encode_information, schema_for
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.self_play import initialize_worker, CollectionJob, collect_episode, Collector, file_digest
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import balanced_selection, validate_manifest, save_manifest
from sts2_env.search.clone import clone_state
from sts2_env.cards import base as card_base
from sts2_env.az.decks import card_token, make_token
from sts2_env.az.information import PublicHistory
from sts2_env.az.scenarios import DeckEntry
from collections import Counter


def fogmog():
    tokens = ['STRIKE_IRONCLAD']*3 + ['DEFEND_IRONCLAD']*2 + [
        'BASH', 'ARMAMENTS', 'ARMAMENTS+', 'HEADBUTT', 'PURITY+', 'EQUILIBRIUM',
        'WHIRLWIND+', 'BURNING_PACT', 'REAVE', 'PRIMAL_FORCE', 'POMMEL_STRIKE', 'SHRUG_IT_OFF']
    from sts2_env.az.decks import MORPH_FAMILIES
    tokens += [t for t in MORPH_FAMILIES['ironclad-cycle'] if t not in [x.removesuffix('+') for x in tokens]]
    r = replace(recipe(26), family_id='ironclad-cycle', player_hp=80,
                deck=tuple(DeckEntry(t.removesuffix('+'),t.endswith('+'),n) for t,n in sorted(Counter(tokens).items())))
    return ObservableCombatAdapter(r,reward_version=V5)


def arrange(env, hand):
    world = env.world
    pool = world.hand + world.draw_pile + world.discard_pile
    chosen=[]
    for token in hand:
        card=next(c for c in pool if card_token(c)==token)
        pool.remove(card)
        chosen.append(card)
    world.hand, world.draw_pile, world.discard_pile = chosen, pool, []
    env._information=observe(world,env.information.history,env.limits,80,V5,SUMMON_CONTENT,*env.public_initial)


def matched(env, action):
    p=BeliefSampler().sample(env.information,np.random.default_rng(31))
    available=list(p.world.draw_pile)
    ordered=[]
    for c in env.world.draw_pile:
        twin=next(t for t in available if card_token(t)==card_token(c))
        available.remove(twin)
        ordered.append(twin)
    p.world.draw_pile=ordered
    p.world.rng=clone_state(env.world.rng)
    predicted=p.step(action)
    env.step(action)
    assert predicted==env.information


def play(env, token, target=0):
    index=env.information.hand.index(token)
    matched(env,index+1 if env.information.legal_mask[index+1] else 11+index*5+target)


def test_repeated_knockout_returns_to_distract_not_revive_loop():
    env=fogmog()
    matched(env,0)
    eye=env.world.enemies[1]
    for _ in range(3):
        arrange(env,['STRIKE_IRONCLAD'])
        play(env,'STRIKE_IRONCLAD',1)
        assert env.information.enemies[1].reviving
        assert not env.information.legal_mask[12]
        matched(env,0)
        assert env.world.enemies[1] is eye
        assert env.information.enemies[1].hp==6
        assert env.information.enemies[1].intent[0]=='STATUS_CARD'
    matched(env,0)
    assert env.information.history.generated[-1].result_token=='DAZED'
    assert env.information.history.generated[-1].count==3


@pytest.mark.parametrize('upgrade',[False,True])
def test_dazed_armaments_no_upgrade_or_premature_inventory_change(upgrade):
    env=fogmog();matched(env,0);matched(env,0)
    token='ARMAMENTS+' if upgrade else 'ARMAMENTS'
    arrange(env,[token,'DAZED','STRIKE_IRONCLAD'])
    previous=env.information.history.upgraded
    play(env,token)
    if not upgrade:
        assert env.information.choice
        assert env.information.history.upgraded==previous
        # Selecting unupgradable Dazed is a native no-op, not DAZED+.
        matched(env,1)
    assert 'DAZED' in env.information.hand
    assert 'DAZED+' not in env.information.hand


def test_equilibrium_does_not_retain_ethereal_dazed():
    env=fogmog();matched(env,0);matched(env,0)
    arrange(env,['EQUILIBRIUM','DAZED','STRIKE_IRONCLAD'])
    play(env,'EQUILIBRIUM')
    matched(env,0)
    assert 'DAZED' in env.information.exhaust
    assert env.information.hand[0]=='STRIKE_IRONCLAD'


@pytest.mark.parametrize('token',['PURITY+','BURNING_PACT','HEADBUTT'])
def test_dazed_selection_and_public_continuation(token):
    env=fogmog();matched(env,0);matched(env,0)
    arrange(env,[token,'DAZED','DEFEND_IRONCLAD'])
    if token=='HEADBUTT':
        cards=env.world.hand[1:]
        env.world.hand=env.world.hand[:1]
        env.world.discard_pile=cards
        env._information=observe(env.world,env.information.history,env.limits,80,V5,SUMMON_CONTENT,*env.public_initial)
    play(env,token)
    assert env.information.choice
    matched(env,1)
    assert env.information.choice is None
    if token=='HEADBUTT':assert env.information.known_top[0]=='DAZED'
    else:assert 'DAZED' in env.information.exhaust


def test_summon_hidden_rng_independence_and_branch_isolation():
    env=fogmog();matched(env,0);matched(env,0)
    original=env.information
    model=PolicyValueNetwork('observable',V5,SUMMON_CONTENT)
    a=plan_observable(original,model,model_version="test",budget=8,search_seed=7)
    env.world.draw_pile.reverse()
    env.world.rng=__import__('sts2_env.core.rng',fromlist=['Rng']).Rng(77)
    changed=observe(env.world,original.history,env.limits,80,V5,SUMMON_CONTENT,*env.public_initial)
    assert changed==original
    b=plan_observable(changed,model,model_version="test",budget=8,search_seed=7)
    assert np.array_equal(a.root_visits,b.root_visits)
    p=BeliefSampler().sample(original,np.random.default_rng(5))
    sibling=BeliefSampler().sample(original,np.random.default_rng(5))
    p.step(0)
    assert sibling.info==original==env.information


def test_summon_seed_spaces_and_full_stratum_coverage():
    from sts2_env.az.generation import generator_config
    from sts2_env.az.content import MULTI_CONTENT
    records=frozen_manifest(SUMMON_CONTENT)
    test=[r for r in records if r.split=='test']
    assert len(test)==180
    assert len({(r.family_id,r.encounter_id,r.player_hp) for r in test})==162
    assert not {r.environment_seed for r in records}&{r.environment_seed for r in frozen_manifest(MULTI_CONTENT)}
    assert recipe(0).environment_seed==5*2**27+42*1024*1024


def test_expanded_choice_capacity_does_not_truncate_or_change_purity():
    from types import SimpleNamespace
    from sts2_env.az.actions import public_mask
    from sts2_env.az.choice_sets import set_mask
    from sts2_env.az.content import MULTI_CONTENT
    choice=SimpleNamespace(num_options=600,is_multi=False,can_confirm=lambda:False)
    world=SimpleNamespace(pending_choice=choice,play_pile=[])
    mask=public_mask(world,SUMMON_CONTENT)
    assert mask.sum()==600 and mask[600] and not mask[601]
    with pytest.raises(ValueError):public_mask(world,MULTI_CONTENT)
    assert sum(set_mask(9,0,5,True,1024))==382
    assert not any(set_mask(9,0,5,True,1024)[512:])


def test_primary_kill_wins_with_live_eye_and_v5_replayable_reward():
    env=fogmog();matched(env,0)
    env.world.enemies[0].current_hp=6
    arrange(env,['STRIKE_IRONCLAD'])
    play(env,'STRIKE_IRONCLAD')
    outcome=env.outcome()
    assert outcome.done and outcome.termination_reason=='win'
    assert env.world.enemies[1].current_hp==6
    assert outcome.enemy_final_hp==0 and outcome.enemy_initial_hp==74
    from sts2_env.az.rewards import terminal_reward
    assert terminal_reward('win',outcome.final_hp,80,0,74,V5,
        enemy_initial_hp=74,enemy_roster=list(outcome.enemy_roster))==outcome.reward


def test_summoned_object_cannot_be_replaced_in_same_slot():
    env=fogmog();matched(env,0)
    from sts2_env.az.summon import check_transition
    from sts2_env.monsters.act1 import create_eye_with_teeth
    from sts2_env.core.rng import Rng
    env.world.enemies[1]=create_eye_with_teeth(Rng(9))[0]
    with pytest.raises(ValueError):check_transition(env.information,env.world,env.enemy_slots)


def test_unregistered_dazed_and_corrupt_generation_are_rejected():
    from sts2_env.az.card_generation import CardGeneration,generated_tokens
    from sts2_env.az.summon import DAZED_SOURCE,DAZED_MECHANISM
    from sts2_env.az.content import MULTI_CONTENT
    event=CardGeneration(1,DAZED_SOURCE,'DAZED','discard',DAZED_MECHANISM,3)
    assert generated_tokens((event,),1,SUMMON_CONTENT)==('DAZED',)*3
    with pytest.raises(ValueError):generated_tokens((event,),1,MULTI_CONTENT)
    with pytest.raises(ValueError):generated_tokens((replace(event,count=2),),1,SUMMON_CONTENT)
    with pytest.raises(ValueError):generated_tokens((replace(event,count=True),),1,SUMMON_CONTENT)


def recipe(slot, seed=42):
    return generate_recipe(seed, 0, slot, content_version=SUMMON_CONTENT)


@pytest.mark.parametrize("slot", range(len(SUMMON_STRATA)))
def test_summon_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V5)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        assert info.known_top == tuple(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile[:len(info.known_top)])
        encoded = encode_information(info)
        assert list(encoded.numeric.shape) == schema_for("observable",V5,SUMMON_CONTENT)["shapes"]["numeric"]
        saved = card_base._next_instance_id
        particle = BeliefSampler().sample(info, rng)
        assert particle.info == info and card_base._next_instance_id == saved
        assert particle.world.shuffle_rng is particle.world.monster_ai_rng is particle.world.rng
        for attr in ("draw_pile", "discard_pile"):
            available = list(getattr(particle.world, attr))
            ordered = []
            for c in getattr(env.world, attr):
                twin = next(t for t in available if (t.card_id, t.upgraded) == (c.card_id, c.upgraded))
                available.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        from sts2_env.az.g1 import codec_for
        codec = codec_for(SUMMON_CONTENT)
        for attr in ("draw_pile", "discard_pile", "exhaust_pile", "hand"):
            assert Counter(codec.capture(c) for c in getattr(particle.world,attr)) == Counter(codec.capture(c) for c in getattr(env.world,attr))
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert env.information == predicted
    assert env.outcome().reward == env.information.terminal_value()



def test_summon_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(SUMMON_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(UP_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V5, SUMMON_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", "win-timeout-hp-v3", UP_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V5) for slot in (24,26,51,159)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V5, content_version=SUMMON_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V5, content_version=SUMMON_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])


