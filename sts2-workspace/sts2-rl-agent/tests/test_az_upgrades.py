from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import UP_CONTENT, GEN_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
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


def recipe(slot, seed=42):
    return generate_recipe(seed, 0, slot, content_version=UP_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_upgrades_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        encoded = encode_information(info)
        assert encoded.numeric.shape == (334,)
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


def arranged(source_up=False, mixed=False):
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.information import PublicHistory
    r = replace(recipe(84), player_hp=80, encounter_id="setup_mawler_normal",
        deck=(DeckEntry("ARMAMENTS", source_up, 2), DeckEntry("BODY_SLAM", False, 1),
              DeckEntry("IRON_WAVE", False, 1), DeckEntry("IMPERVIOUS", False, 1),
              DeckEntry("ANGER", mixed, 1), DeckEntry("TRUE_GRIT", False, 1), DeckEntry("DEFEND_IRONCLAD", mixed, 2)))
    env = ObservableCombatAdapter(r, reward_version=V3)
    pool = env.world.hand + env.world.draw_pile
    hand = []
    for name in ("ARMAMENTS", "DEFEND_IRONCLAD", "BODY_SLAM", "ANGER", "TRUE_GRIT"):
        card = next(c for c in pool if c.card_id.name == name)
        pool.remove(card)
        hand.append(card)
    env.world.hand, env.world.draw_pile = hand, pool
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, UP_CONTENT, *env.public_initial)
    return env


def matched_step(env, action):
    particle = BeliefSampler().sample(env.information, np.random.default_rng(8))
    # These test actions do not draw or shuffle. This is not production RNG copying.
    predicted = particle.step(action)
    env.step(action)
    assert predicted == env.information


def test_filtered_candidates_upgrade_cost_and_no_double_block():
    env = arranged(mixed=True)
    matched_step(env, 1)
    info = env.information
    assert info.choice is not None and tuple(o.index for o in info.choice.options) == (1, 3)
    assert info.player_block == 5 and info.energy == 2
    matched_step(env, 1)  # first candidate is hand[1], not hand[0]
    info = env.information
    assert info.hand[1] == "BODY_SLAM+" and info.hand_states[1].cost == 0
    assert info.player_block == 5 and info.energy == 2
    assert info.history.upgraded[0].source_token == "BODY_SLAM"
    assert info.history.upgraded[0].hand_index == 1
    matched_step(env, 16)  # free Body Slam targets the sole enemy
    assert env.information.energy == 2


def test_mass_upgrade_then_generate_upgraded_copy():
    from collections import Counter
    from sts2_env.gym_env.action_space import action_to_card_and_target
    from sts2_env.az.card_upgrades import inventory
    env = arranged(source_up=True)
    matched_step(env, 1)
    assert env.information.choice is None
    assert len(env.information.history.upgraded) == 4
    assert all(t.endswith("+") for t in env.information.hand)
    action = next(int(a) for a in np.flatnonzero(env.information.legal_mask) if a
                  and env.information.hand[action_to_card_and_target(int(a))[0]] == "ANGER+")
    matched_step(env, action)
    info = env.information
    assert info.history.generated[-1].result_token == "ANGER+"
    counts = inventory(info.known_deck, info.history.generated, info.history.upgraded, info.history.decisions)
    assert counts["ANGER+"] == 2 and counts["ANGER"] == 0
    assert counts == Counter(info.hand + info.draw_composition + info.discard + info.exhaust)
    with pytest.raises(ValueError):
        replace(info, history=replace(info.history, upgraded=())).validate()
    with pytest.raises(ValueError):
        replace(info, content_version=GEN_CONTENT).validate()


@pytest.mark.parametrize("candidates", (0, 1))
def test_native_zero_and_one_candidate_auto_resolution(candidates):
    from sts2_env.az.information import PublicHistory
    env = arranged(mixed=True)
    # Keep Armaments and either an upgraded or an unupgraded card; move others to draw.
    keep = [env.world.hand[0], env.world.hand[2] if candidates else env.world.hand[1]]
    env.world.draw_pile += [c for c in env.world.hand if all(c is not k for k in keep)]
    env.world.hand = keep
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, UP_CONTENT, *env.public_initial)
    matched_step(env, 1)
    assert env.information.choice is None and len(env.information.history.upgraded) == candidates


def test_upgrade_choice_hidden_information_and_sibling_isolation():
    initialize_worker()
    env = arranged(mixed=True)
    env.step(1)
    info = env.information
    altered = clone_state(env.world)
    altered.draw_pile.reverse()
    altered.rng.next_int(0,1000)
    altered._pending_play = {"private": "not read"}
    other = observe(altered, info.history, info.limits,80,V3,UP_CONTENT,*env.public_initial)
    assert other == info
    model = PolicyValueNetwork("observable",V3,UP_CONTENT)
    saved = card_base._next_instance_id
    a = plan_observable(info,model,model_version="upgrade",budget=8,search_seed=3)
    b = plan_observable(other,model,model_version="upgrade",budget=8,search_seed=3)
    assert a.action == b.action and np.array_equal(a.root_visits,b.root_visits)
    assert card_base._next_instance_id == saved
    p = BeliefSampler().sample(info,np.random.default_rng(4))
    q = BeliefSampler().sample(info,np.random.default_rng(4))
    p.step(1)
    assert q.info == env.information == info and q.world.hand[1].upgraded is False


def test_upgrade_ledger_rejects_fabricated_source():
    from sts2_env.az.card_upgrades import inventory, CardUpgrade
    from sts2_env.az.card_generation import CardGeneration
    with pytest.raises(ValueError):
        inventory(("ARMAMENTS",), (), (CardUpgrade(1,0,"BASH","BASH+","ARMAMENTS"),), 1)
    with pytest.raises(ValueError):
        inventory(("ANGER",), (CardGeneration(1,"ANGER+","ANGER+"),), (), 1)
    with pytest.raises(ValueError):
        inventory(("ARMAMENTS","BASH"), (), (CardUpgrade(1,0,"BASH","BASH+","ARMAMENTS+"),), 1)

def test_upgrades_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(UP_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(GEN_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, UP_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, GEN_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (105,110,120,125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=UP_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=UP_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])
