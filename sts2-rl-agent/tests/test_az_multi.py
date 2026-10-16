from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import MULTI_CONTENT, UP_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
from sts2_env.az.generation import MULTI_STRATA, generate_recipe, frozen_manifest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V4
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


def arranged(hand=None, discard=None, draw=None, family="ironclad-cycle"):
    hand = hand if hand is not None else ["HEADBUTT", "HEADBUTT+", "SHRUG_IT_OFF", "BURNING_PACT", "ARMAMENTS+"]
    discard = discard if discard is not None else ["ANGER+", "DEFEND_IRONCLAD", "BASH"]
    draw = draw if draw is not None else ["POMMEL_STRIKE", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"]
    from sts2_env.az.decks import MORPH_FAMILIES
    draw = list(draw)
    for required in MORPH_FAMILIES[family]:
        if required not in [t.removesuffix("+") for t in hand + discard + draw]: draw.append(required)
    counts = Counter(hand + discard + draw)
    r = replace(recipe(21), family_id=family, player_hp=80, encounter_id="setup_nibbits_normal",
                deck=tuple(DeckEntry(t.removesuffix("+"), t.endswith("+"), n) for t,n in sorted(counts.items())))
    env = ObservableCombatAdapter(r, reward_version=V4)
    pool = env.world.hand + env.world.draw_pile
    def take(tokens):
        result = []
        for t in tokens:
            card = next(c for c in pool if card_token(c) == t)
            pool.remove(card)
            result.append(card)
        return result
    env.world.hand, env.world.discard_pile, env.world.draw_pile = take(hand), take(discard), take(draw)
    env._information = observe(env.world, PublicHistory(), env.limits,80,V4,MULTI_CONTENT,*env.public_initial)
    return env


def matched_step(env, action, align_unknown=False):
    p = BeliefSampler().sample(env.information,np.random.default_rng(9))
    if align_unknown:
        pool = list(p.world.draw_pile)
        result = []
        for c in env.world.draw_pile:
            twin = next(t for t in pool if card_token(t) == card_token(c))
            pool.remove(twin)
            result.append(twin)
        p.world.draw_pile = result
        p.world.rng = clone_state(env.world.rng)
    predicted = p.step(action)
    env.step(action)
    assert predicted == env.information


def recipe(slot, seed=42):
    return generate_recipe(seed, 0, slot, content_version=MULTI_CONTENT)


@pytest.mark.parametrize("slot", range(len(MULTI_STRATA)))
def test_multi_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V4)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        assert info.known_top == tuple(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile[:len(info.known_top)])
        encoded = encode_information(info)
        assert encoded.numeric.shape == (1804,)
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
        codec = codec_for(MULTI_CONTENT)
        for attr in ("draw_pile", "discard_pile", "exhaust_pile", "hand"):
            assert Counter(codec.capture(c) for c in getattr(particle.world,attr)) == Counter(codec.capture(c) for c in getattr(env.world,attr))
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert env.information == predicted
    assert env.outcome().reward == env.information.terminal_value()


def test_multi_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(MULTI_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(UP_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V4, MULTI_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", "win-timeout-hp-v3", UP_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V4) for slot in (21,45,93,141)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V4, content_version=MULTI_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V4, content_version=MULTI_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])


def play(env, token, target=0):
    from sts2_env.core.enums import TargetType
    index = env.information.hand.index(token)
    action = 11 + 5*index + target if env.world.hand[index].target_type == TargetType.ANY_ENEMY else 1+index
    matched_step(env, action, True)


def refresh(env):
    env._information = observe(env.world, env.information.history, env.limits, env.recipe.player_hp,
                               V4, MULTI_CONTENT, *env.public_initial)


@pytest.mark.parametrize("target", [0, 1])
def test_dead_slot_stays_and_second_enemy_still_acts(target):
    env=arranged(hand=["STRIKE_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"], discard=[], draw=[])
    env.world.enemies[target].current_hp = 6
    refresh(env)
    play(env,"STRIKE_IRONCLAD",target)
    assert not env.outcome().done and len(env.information.enemies)==2
    assert env.information.enemies[target].hp==0
    i=env.information.hand.index("STRIKE_IRONCLAD")
    assert not env.legal_mask()[11+5*i+target] and env.legal_mask()[11+5*i+1-target]
    p=BeliefSampler().sample(env.information,np.random.default_rng(1))
    assert p.world.enemies[target].escaped and p.world.enemies[target]._death_processed
    play(env,"STRIKE_IRONCLAD",1-target)
    matched_step(env,0,True)
    assert env.information.enemies[target].moves==()
    assert len(env.information.enemies[1-target].moves)==1
    initial=sum(e.initial_hp for e in env.information.enemies)
    assert env.outcome().enemy_initial_hp==initial


@pytest.mark.parametrize("upgraded", [False,True])
def test_whirlwind_repeated_hits_skip_dead_slot_and_consume_x_once(upgraded):
    token="WHIRLWIND"+("+" if upgraded else "")
    env=arranged(hand=[token,"DEFEND_IRONCLAD"],discard=[],draw=[])
    env.world.enemies[0].current_hp=3
    env.world.enemies[1].block=4
    refresh(env)
    hp=env.world.enemies[1].current_hp
    play(env,token)
    assert env.information.enemies[0].hp==0
    assert env.information.enemies[1].hp==hp-3*(8 if upgraded else 5)+4
    assert env.information.energy==0
    assert env.information.history.payments[-1].energy==3


@pytest.mark.parametrize("upgraded",[False,True])
def test_thunderclap_damage_before_vulnerability_per_live_target(upgraded):
    token="THUNDERCLAP"+("+" if upgraded else "")
    env=arranged(hand=[token,"STRIKE_IRONCLAD"],discard=[],draw=[])
    env.world.enemies[0].current_hp=3
    env.world.enemies[1].block=2
    refresh(env)
    hp=env.world.enemies[1].current_hp
    play(env,token)
    assert (env.information.enemies[0].hp,env.information.enemies[0].vulnerable)==(0,0)
    assert env.information.enemies[1].hp==hp-(7 if upgraded else 4)+2
    assert env.information.enemies[1].vulnerable==1
    play(env,"STRIKE_IRONCLAD",1)
    assert env.information.enemies[1].hp==hp-(7 if upgraded else 4)+2-9


@pytest.mark.parametrize("target",[0,1])
def test_headbutt_continuation_preserves_dead_original_target(target):
    env=arranged()
    env.world.enemies[target].current_hp=5
    refresh(env)
    play(env,"HEADBUTT",target)
    assert env.information.choice and env.information.history.pending_target==target
    p=BeliefSampler().sample(env.information,np.random.default_rng(4))
    assert p.world._pending_play["target"] is p.world.enemies[target]
    matched_step(env,1,True)
    assert env.information.choice is None and env.information.history.pending_target is None
    assert env.information.known_top==("ANGER+",)


def test_reave_generates_on_first_kill_but_not_combat_final_kill():
    env=arranged(hand=["REAVE","REAVE+"],discard=[],draw=[])
    for e in env.world.enemies: e.current_hp=1
    refresh(env)
    play(env,"REAVE",0)
    assert len(env.information.history.generated)==1 and not env.outcome().done
    assert env.information.known_bottom==("SOUL",)
    play(env,"REAVE+",1)
    assert env.outcome().termination_reason=="win"
    assert len(env.information.history.generated)==1
    assert env.information.terminal_value()==env.outcome().reward


def test_public_hidden_isolation_and_branch_independence():
    env=arranged()
    info=env.information
    model=PolicyValueNetwork("observable",V4,MULTI_CONTENT)
    first=plan_observable(info,model,model_version="test",budget=8,search_seed=31)
    env.world.draw_pile.reverse()
    env.world.rng=__import__('sts2_env.core.rng',fromlist=['Rng']).Rng(8888)
    refresh(env)
    assert env.information==info
    second=plan_observable(env.information,model,model_version="test",budget=8,search_seed=31)
    assert np.array_equal(first.root_visits,second.root_visits) and first.action==second.action
    a=BeliefSampler().sample(info,np.random.default_rng(3))
    b=BeliefSampler().sample(info,np.random.default_rng(3))
    snapshot=b.info
    a.step(0)
    assert b.info==snapshot and env.information==info
    assert b.world.enemies[1].get_power_amount(__import__('sts2_env.core.enums',fromlist=['PowerId']).PowerId.STRENGTH)==0


def test_reward_uses_all_initial_hp_and_net_loss_not_damage_history():
    from sts2_env.az.rewards import terminal_reward
    from sts2_env.az.multi import validate_health
    roster=[dict(slot=i,monster_id="NIBBIT",initial_hp=20,final_hp=20,max_hp=42) for i in range(2)]
    def reward(reason="time_limit"):
        initial,final,maximum=validate_health(roster)
        return terminal_reward(reason,30,40,final,maximum,V4,enemy_initial_hp=initial,enemy_roster=roster)
    assert reward()==pytest.approx(-.2)
    roster[0]["final_hp"]=0
    assert reward()==pytest.approx(0)
    roster[1]["final_hp"]=0
    assert reward()==pytest.approx(.2) and reward("win")==pytest.approx(.95)
    roster[0]["final_hp"]=20  # Healing/revival cannot accrue repeated damage credit.
    assert reward()==pytest.approx(0)
    with pytest.raises(ValueError): reward("win")
    with pytest.raises(ValueError): terminal_reward("death",0,40,0,84,V4,enemy_initial_hp=40)
    with pytest.raises(ValueError): terminal_reward("death",0,40,0,84,V4,enemy_initial_hp=40,enemy_roster=roster)
    roster.append(dict(roster[0],slot=2))
    with pytest.raises(ValueError): reward()


def test_schema_seed_isolation_and_roster_rejection():
    from sts2_env.az.content import MORPH_CONTENT
    from sts2_env.az.rewards import V3
    from sts2_env.az.generation import generator_config
    from sts2_env.az.multi import check_transition
    info=arranged().information
    schema=schema_for("observable",V4,MULTI_CONTENT)
    assert schema["action_schema_version"]=="combat-multi512-v3"
    assert schema["shapes"]["numeric"]==[1804]
    assert generator_config(MULTI_CONTENT)["strata"]==144
    assert generate_recipe(127,1023,1023,content_version=MULTI_CONTENT).environment_seed==15*2**27-1
    assert not {r.environment_seed for r in frozen_manifest(MULTI_CONTENT)} & {r.environment_seed for r in frozen_manifest(MORPH_CONTENT)}
    with pytest.raises(ValueError): schema_for("observable",V3,MULTI_CONTENT)
    with pytest.raises(ValueError): replace(info,content_version=MORPH_CONTENT).validate()
    for enemies in ((),info.enemies*2,tuple(reversed(info.enemies)),(replace(info.enemies[0],strength=9),info.enemies[1])):
        with pytest.raises(ValueError): replace(info,enemies=enemies).validate()
    env=arranged()
    slots=tuple(env.world.enemies)
    env.world.enemies.reverse()
    with pytest.raises(ValueError): check_transition(env.information,env.world,slots)
    env.world.enemies.reverse()
    dead=replace(info,enemies=(replace(info.enemies[0],hp=0),info.enemies[1]))
    with pytest.raises(ValueError): check_transition(dead,env.world,slots)
    env.world.enemies[1].max_hp += 1
    with pytest.raises(ValueError): check_transition(env.information,env.world,slots)


def test_terminal_enemy_round_does_not_fabricate_unperformed_back_move():
    env=arranged()
    env.world.player.current_hp=1
    refresh(env)
    matched_step(env,0,True)
    assert env.outcome().termination_reason=="death"
    assert env.information.enemies[1].strength==0
    assert env.information.history.roster_moves==((),())


def test_real_win_precedes_decision_limit():
    from sts2_env.az.config import EpisodeLimits
    env=arranged(hand=["THUNDERCLAP"],discard=[],draw=[])
    for e in env.world.enemies: e.current_hp=1
    env.limits=EpisodeLimits(1,100)
    refresh(env)
    play(env,"THUNDERCLAP")
    assert env.outcome().termination_reason=="win"


def test_multi_evaluation_cache_keeps_serialized_roster_identical(tmp_path):
    from sts2_env.az.evaluation import evaluate_parallel
    from sts2_env.az.config import EpisodeLimits
    initialize_worker()
    path=tmp_path/"model.pt"
    model=PolicyValueNetwork("observable",V4,MULTI_CONTENT)
    save_checkpoint(path,model,"cache-test",{},{})
    recipes=[generate_recipe(184,0,21,"validation",MULTI_CONTENT)]
    with Collector(1) as collector:
        args=(collector.pool,path,recipes,0,7,EpisodeLimits(4,100),tmp_path/"cache")
        first=evaluate_parallel(*args,reward_version=V4)
        second=evaluate_parallel(*args,reward_version=V4)
        assert first==second
        assert len(first[0]["enemy_roster"])==2

