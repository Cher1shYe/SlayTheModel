from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import TOP_CONTENT, UP_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
from sts2_env.az.generation import EXPANDED_STRATA, generate_recipe, frozen_manifest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V3
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


def arranged(hand=None, discard=None, draw=None):
    hand = hand if hand is not None else ["HEADBUTT", "HEADBUTT+", "SHRUG_IT_OFF", "BURNING_PACT", "ARMAMENTS+"]
    discard = discard if discard is not None else ["ANGER+", "DEFEND_IRONCLAD", "BASH"]
    draw = draw if draw is not None else ["POMMEL_STRIKE", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"]
    counts = Counter(hand + discard + draw)
    r = replace(recipe(21), player_hp=80, encounter_id="setup_mawler_normal",
                deck=tuple(DeckEntry(t.removesuffix("+"), t.endswith("+"), n) for t,n in sorted(counts.items())))
    env = ObservableCombatAdapter(r, reward_version=V3)
    pool = env.world.hand + env.world.draw_pile
    def take(tokens):
        result = []
        for t in tokens:
            card = next(c for c in pool if card_token(c) == t)
            pool.remove(card)
            result.append(card)
        return result
    env.world.hand, env.world.discard_pile, env.world.draw_pile = take(hand), take(discard), take(draw)
    env._information = observe(env.world, PublicHistory(), env.limits,80,V3,TOP_CONTENT,*env.public_initial)
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


def test_ordered_discard_repeated_top_and_draw_no_double_damage():
    env = arranged()
    hp = env.information.enemy_hp
    matched_step(env,11)
    info = env.information
    assert info.enemy_hp == hp - 9 and info.energy == 2
    assert tuple(o.card.token for o in info.choice.options) == ("ANGER+","DEFEND_IRONCLAD","BASH")
    assert tuple(o.index for o in info.choice.options) == (0,1,2)
    matched_step(env,2)
    assert env.information.enemy_hp == hp - 9 and env.information.energy == 2
    assert env.information.known_top == ("DEFEND_IRONCLAD",)
    matched_step(env,11)
    matched_step(env,1)
    assert env.information.known_top == ("ANGER+","DEFEND_IRONCLAD")
    for seed in range(10):
        p = BeliefSampler().sample(env.information,np.random.default_rng(seed))
        assert tuple(map(card_token,p.world.draw_pile[:2])) == env.information.known_top
    matched_step(env,1)  # Shrug draws the first known card
    assert env.information.hand[-1] == "ANGER+"
    assert env.information.known_top == ("DEFEND_IRONCLAD",)
    matched_step(env,0,True)  # boundary consumes prefix and can reshuffle
    assert not env.information.known_top


@pytest.mark.parametrize("count",[0,1])
def test_zero_single_discard_native_auto(count):
    env = arranged(discard=["ANGER+"][:count])
    matched_step(env,11)
    assert env.information.choice is None
    assert env.information.known_top == (("ANGER+",) if count else ())


@pytest.mark.parametrize("hand",[
    ["HEADBUTT","BURNING_PACT"],
    ["HEADBUTT","BURNING_PACT","DEFEND_IRONCLAD"],
    ["HEADBUTT","BURNING_PACT","DEFEND_IRONCLAD","DEFEND_IRONCLAD"],
])
def test_burning_pact_draw_consumes_known_prefix(hand):
    env = arranged(hand=hand,discard=["ANGER+"],draw=["POMMEL_STRIKE","SHRUG_IT_OFF","BASH","DEFEND_IRONCLAD"])
    matched_step(env,11)
    matched_step(env,1,True)
    if env.information.choice:
        matched_step(env,1,True)
    assert not env.information.known_top
    assert "ANGER+" in env.information.hand


def test_full_hand_draw_limit_leaves_correct_prefix():
    env = arranged(hand=["HEADBUTT","BURNING_PACT+","DEFEND_IRONCLAD","DEFEND_IRONCLAD","DEFEND_IRONCLAD",
                         "STRIKE_IRONCLAD","STRIKE_IRONCLAD","STRIKE_IRONCLAD","BASH","POMMEL_STRIKE"],
                   discard=["ANGER+"],draw=["SHRUG_IT_OFF","BASH","POMMEL_STRIKE"])
    matched_step(env,11)
    matched_step(env,1,True)
    matched_step(env,1,True)  # exhaust one card, then draw up to capacity
    assert len(env.information.hand) == 10 and not env.information.known_top
    assert env.information.hand[-3] == "ANGER+"


def test_killing_headbutt_does_not_fabricate_top_or_choice():
    env = arranged()
    env.world.enemies[0].current_hp = 1
    env._information = observe(env.world,env.information.history,env.limits,80,V3,TOP_CONTENT,*env.public_initial)
    matched_step(env,11)
    assert env.outcome().done and not env.information.known_top


def test_large_generated_discard_no_choice_truncation():
    from sts2_env.az.card_generation import CardGeneration
    env = arranged()
    for _ in range(120):
        c=make_token("ANGER+");c.owner=env.world.player;env.world.discard_pile.append(c)
    history = PublicHistory(decisions=120,generated=tuple(CardGeneration(i,"ANGER+","ANGER+") for i in range(1,121)))
    env._information=observe(env.world,history,env.limits,80,V3,TOP_CONTENT,*env.public_initial)
    # Synthetic prehistory is only for a capacity fixture; synchronize adapter limits counter.
    env.actions=[0]*120
    matched_step(env,11)
    info=env.information
    assert len(info.choice.options)==123 and info.legal_mask[123]
    encoded=encode_information(info)
    assert encoded.legal_mask.shape==(421,)
    schema=schema_for("observable",V3,TOP_CONTENT)
    i=schema['numeric_features'].index('discard_order.122.token_id/42')
    assert encoded.numeric[i] > 0
    matched_step(env,123)
    assert env.information.known_top==("ANGER+",)


def test_hidden_unknown_order_and_continuation_isolation():
    initialize_worker()
    env=arranged();env.step(11);info=env.information
    altered=clone_state(env.world);altered.draw_pile.reverse();altered.rng.next_int(0,1000)
    altered._pending_play={"private":"not read"}
    other=observe(altered,info.history,info.limits,80,V3,TOP_CONTENT,*env.public_initial)
    assert other==info
    model=PolicyValueNetwork("observable",V3,TOP_CONTENT)
    saved=card_base._next_instance_id
    a=plan_observable(info,model,model_version="top",budget=8,search_seed=3)
    b=plan_observable(other,model,model_version="top",budget=8,search_seed=3)
    assert a.action==b.action and np.array_equal(a.root_visits,b.root_visits)
    assert saved==card_base._next_instance_id
    p=BeliefSampler().sample(info,np.random.default_rng(4));q=BeliefSampler().sample(info,np.random.default_rng(4))
    p.step(1)
    assert q.info==env.information==info
    with pytest.raises(ValueError):
        replace(info,known_top=("HEADBUTT+",)).validate()
    with pytest.raises(ValueError):
        replace(info,content_version=UP_CONTENT).validate()


def test_known_prefix_hidden_suffix_and_encoding_order():
    initialize_worker()
    env=arranged();env.step(11);env.step(2);env.step(11);env.step(1)
    info=env.information
    altered=clone_state(env.world)
    altered.draw_pile=altered.draw_pile[:2]+list(reversed(altered.draw_pile[2:]))
    altered.rng.next_int(0,1000)
    other=observe(altered,info.history,info.limits,80,V3,TOP_CONTENT,*env.public_initial)
    assert other==info
    model=PolicyValueNetwork("observable",V3,TOP_CONTENT)
    a=plan_observable(info,model,model_version="prefix",budget=8,search_seed=13)
    b=plan_observable(other,model,model_version="prefix",budget=8,search_seed=13)
    assert np.array_equal(a.root_visits,b.root_visits)
    reverse=tuple(reversed(info.known_top))
    reversed_info=replace(info,known_top=reverse,history=replace(info.history,known_top=reverse)).validate()
    assert not np.array_equal(encode_information(info).numeric,encode_information(reversed_info).numeric)
    p=BeliefSampler().sample(reversed_info,np.random.default_rng(1))
    assert tuple(map(card_token,p.world.draw_pile[:2]))==reverse


def test_upgrade_headbutt_then_retrieve_generated_copy():
    env=arranged(hand=["ARMAMENTS+","HEADBUTT","ANGER","SHRUG_IT_OFF"],discard=[],draw=["POMMEL_STRIKE","BASH"])
    matched_step(env,1)
    assert env.information.hand[0]=="HEADBUTT+"
    assert env.information.history.upgraded[0].source_token=="HEADBUTT"
    matched_step(env,16)  # Anger+ creates a public upgraded copy
    matched_step(env,11)
    options=env.information.choice.options
    action=next(i+1 for i,o in enumerate(options) if o.card.token=="ANGER+")
    matched_step(env,action)
    matched_step(env,1)
    assert env.information.hand[-1]=="ANGER+" and not env.information.known_top


def test_native_choice_capacity_rejection_is_explicit():
    from sts2_env.az.actions import public_mask
    env=arranged();env.step(11)
    choice=env.world.pending_choice
    choice.options=choice.options*141  # >420 candidates, never silently clamp
    with pytest.raises(ValueError,match="capacity"):
        public_mask(env.world,TOP_CONTENT)


def recipe(slot, seed=42):
    return generate_recipe(seed, 0, slot, content_version=TOP_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_topdeck_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        assert info.known_top == tuple(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile[:len(info.known_top)])
        encoded = encode_information(info)
        assert encoded.numeric.shape == (1191,)
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
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert env.information == predicted
    assert env.outcome().reward == env.information.terminal_value()


def test_topdeck_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(TOP_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(UP_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, TOP_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, UP_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (105,110,120,125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=TOP_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=TOP_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])
