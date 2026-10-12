from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import MORPH_CONTENT, UP_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
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


def arranged(hand=None, discard=None, draw=None, family="ironclad-cycle"):
    hand = hand if hand is not None else ["HEADBUTT", "HEADBUTT+", "SHRUG_IT_OFF", "BURNING_PACT", "ARMAMENTS+"]
    discard = discard if discard is not None else ["ANGER+", "DEFEND_IRONCLAD", "BASH"]
    draw = draw if draw is not None else ["POMMEL_STRIKE", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"]
    from sts2_env.az.decks import MORPH_FAMILIES
    draw = list(draw)
    for required in MORPH_FAMILIES[family]:
        if required not in [t.removesuffix("+") for t in hand + discard + draw]: draw.append(required)
    counts = Counter(hand + discard + draw)
    r = replace(recipe(21), family_id=family, player_hp=80, encounter_id="setup_mawler_normal",
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
    env._information = observe(env.world, PublicHistory(), env.limits,80,V3,MORPH_CONTENT,*env.public_initial)
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
    return generate_recipe(seed, 0, slot, content_version=MORPH_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_morph_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        assert info.known_top == tuple(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile[:len(info.known_top)])
        encoded = encode_information(info)
        assert encoded.numeric.shape == (1744,)
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
        codec = codec_for(MORPH_CONTENT)
        for attr in ("draw_pile", "discard_pile", "exhaust_pile", "hand"):
            assert Counter(codec.capture(c) for c in getattr(particle.world,attr)) == Counter(codec.capture(c) for c in getattr(env.world,attr))
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert env.information == predicted
    assert env.outcome().reward == env.information.terminal_value()


def test_morph_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(MORPH_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(UP_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, MORPH_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, UP_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (105,110,120,125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=MORPH_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=MORPH_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])


def play(env, token):
    from sts2_env.core.enums import TargetType
    index = env.information.hand.index(token)
    card = env.world.hand[index]
    action = 11 + 5 * index if card.target_type == TargetType.ANY_ENEMY else 1 + index
    matched_step(env, action, True)


@pytest.mark.parametrize("upgraded", [False, True])
def test_transform_preserves_slots_replaces_stats_and_upgrade_order(upgraded):
    cause = "PRIMAL_FORCE+" if upgraded else "PRIMAL_FORCE"
    env = arranged(hand=[cause, "STOMP+", "STRIKE_IRONCLAD+", "ARMAMENTS+", "DEFEND_IRONCLAD", "PRIMAL_FORCE"], discard=[], draw=[])
    initial = len(env.information.known_deck)
    play(env, cause)
    result = "GIANT_ROCK+" if upgraded else "GIANT_ROCK"
    assert env.information.hand[:2] == (result, result)
    assert len(env.information.history.transformed) == 2
    assert all(s.turn_cost is None for s in env.information.hand_states[:2])
    play(env, "PRIMAL_FORCE")  # Replaces even already-generated rocks; normal cause removes old upgrade.
    assert env.information.hand[:2] == ("GIANT_ROCK", "GIANT_ROCK")
    play(env, "ARMAMENTS+")
    assert env.information.hand[:2] == ("GIANT_ROCK+", "GIANT_ROCK+")
    assert sum(map(len, (env.information.hand, env.information.draw_composition, env.information.discard, env.information.exhaust))) == initial
    before = env.information.enemy_hp
    play(env, "GIANT_ROCK+")
    assert env.information.enemy_hp < before


def test_transform_anger_copy_then_purity_and_no_attack_case():
    env = arranged(hand=["ANGER", "PRIMAL_FORCE", "PRIMAL_FORCE+", "PURITY", "DEFEND_IRONCLAD"], discard=[], draw=[])
    play(env, "ANGER")
    assert len(env.information.history.generated) == 1
    play(env, "PRIMAL_FORCE")
    assert not env.information.history.transformed
    play(env, "PRIMAL_FORCE+")
    play(env, "PURITY")
    matched_step(env, 1)
    assert env.information.choice is None
    matched_step(env, 0, True)


def test_reave_bottom_order_upgrades_headbutt_and_hidden_middle():
    env = arranged(hand=["REAVE", "REAVE+", "HEADBUTT", "ARMAMENTS+"], discard=["DEFEND_IRONCLAD"], draw=["STRIKE_IRONCLAD", "BASH"])
    play(env, "REAVE")
    assert env.information.known_bottom == ("SOUL",)
    play(env, "REAVE+")
    assert env.information.known_bottom == ("SOUL", "SOUL+")
    play(env, "HEADBUTT")
    matched_step(env, 1)  # take the visible Defend from discard
    assert env.information.known_top == ("DEFEND_IRONCLAD",)
    assert env.information.known_bottom == ("SOUL", "SOUL+")
    for seed in range(8):
        p = BeliefSampler().sample(env.information, np.random.default_rng(seed))
        assert tuple(map(card_token,p.world.draw_pile[-2:])) == ("SOUL", "SOUL+")
        assert card_token(p.world.draw_pile[0]) == "DEFEND_IRONCLAD"
    model = PolicyValueNetwork("observable", V3, MORPH_CONTENT)
    a = plan_observable(env.information, model, model_version="morph", budget=8, search_seed=7)
    env.world.draw_pile[1:-2] = reversed(env.world.draw_pile[1:-2])
    again = observe(env.world,env.information.history,env.limits,80,V3,MORPH_CONTENT,*env.public_initial)
    assert again == env.information
    b = plan_observable(again, model, model_version="morph", budget=8, search_seed=7)
    np.testing.assert_array_equal(a.root_visits,b.root_visits)
    matched_step(env,0,True)


def test_empty_draw_normalizes_suffix_then_soul_draw_crosses_reshuffle():
    env = arranged(hand=["REAVE", "REAVE+", "POMMEL_STRIKE", "SHRUG_IT_OFF", "HEADBUTT", "RESTLESSNESS", "ARMAMENTS+", "PURITY"], discard=[], draw=[])
    assert not env.information.draw_composition
    play(env,"REAVE")
    play(env,"REAVE+")
    assert env.information.known_top == ("SOUL", "SOUL+") and not env.information.known_bottom
    play(env,"SHRUG_IT_OFF")
    assert env.information.hand[-1] == "SOUL"
    play(env,"SOUL")
    assert "SOUL+" in env.information.hand
    assert not env.information.known_top and not env.information.known_bottom
    play(env,"SOUL+")


def test_reave_killing_blow_has_no_fabricated_generation():
    env = arranged(hand=["REAVE+", "BASH"], discard=[], draw=[])
    env.world.enemies[0].current_hp = 1
    env._information = observe(env.world,env.information.history,env.limits,80,V3,MORPH_CONTENT,*env.public_initial)
    play(env,"REAVE+")
    assert env.outcome().termination_reason == "win"
    assert not env.information.history.generated and not env.information.known_bottom


@pytest.mark.parametrize("upgrade", [False, True])
def test_draw_through_suffix_and_optional_reshuffle(upgrade):
    offering = "OFFERING+" if upgrade else "OFFERING"
    env = arranged(hand=["REAVE", "REAVE+", "BLOODLETTING", "WHIRLWIND", "POMMEL_STRIKE", offering], discard=[], draw=["DEFEND_IRONCLAD"], family="ironclad-burst")
    play(env,"REAVE")
    play(env,"REAVE+")
    assert env.information.known_bottom == ("SOUL", "SOUL+")
    play(env,offering)
    assert env.information.hand[4:6] == ("SOUL", "SOUL+")
    assert not env.information.known_bottom and not env.information.known_top


def test_retained_hand_limits_draw_without_losing_bottom():
    env = arranged(hand=["REAVE", "EQUILIBRIUM", "POMMEL_STRIKE", "SHRUG_IT_OFF", "HEADBUTT", "RESTLESSNESS", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"], discard=[], draw=["BASH", "BASH", "STRIKE_IRONCLAD"])
    play(env,"REAVE")
    play(env,"EQUILIBRIUM")
    matched_step(env,0,True)
    assert len(env.information.hand) == 10
    assert env.information.known_bottom == ("SOUL",)


def test_morph_ledger_and_position_forgery_rejected():
    env=arranged(hand=["REAVE", "PRIMAL_FORCE", "BASH"], discard=[],draw=[])
    play(env,"REAVE")
    info=env.information
    event=replace(info.history.generated[-1],result_token="GIANT_ROCK")
    with pytest.raises(ValueError):
        replace(info,history=replace(info.history,generated=(event,))).validate()
    with pytest.raises(ValueError):
        replace(info,known_bottom=("SOUL",)*421,history=replace(info.history,known_bottom=("SOUL",)*421)).validate()
    play(env,"PRIMAL_FORCE")
    info=env.information
    with pytest.raises(ValueError):
        replace(info,history=replace(info.history,transformed=())).validate()
    event=replace(info.history.transformed[0],source_token="DEFEND_IRONCLAD")
    with pytest.raises(ValueError):
        replace(info,history=replace(info.history,transformed=(event,))).validate()


def test_morph_schema_seeds_and_old_content_reject_generated_tokens():
    from sts2_env.az.content import SET_CONTENT
    from sts2_env.az.generation import generator_config
    from sts2_env.az.decks import validate_deck
    s=schema_for("observable",V3,MORPH_CONTENT)
    assert s["shapes"]["numeric"] == [1744] and s["action_size"] == 512
    assert len(s["card_vocabulary"]) == 61
    assert generator_config(MORPH_CONTENT)["heldout_master_seeds"] == {"validation":183,"test":281}
    assert generate_recipe(127,1023,1023,content_version=MORPH_CONTENT).environment_seed == 14*2**27-1
    assert not {r.environment_seed for r in frozen_manifest(MORPH_CONTENT)} & {r.environment_seed for r in frozen_manifest(SET_CONTENT)}
    r=recipe(21)
    with pytest.raises(ValueError):
        validate_deck(r.deck+(DeckEntry("SOUL",False,1),),r.family_id,MORPH_CONTENT)
    with pytest.raises(ValueError):
        replace(r,content_manifest_version=SET_CONTENT).validate()


