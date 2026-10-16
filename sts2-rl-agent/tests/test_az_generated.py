from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import GEN_CONTENT, G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
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
    return generate_recipe(seed, 0, slot, content_version=GEN_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_generated_complete_game_particle_parity(slot):
    from collections import Counter
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        assert Counter(info.draw_composition) == Counter(c.card_id.name + ("+" if c.upgraded else "") for c in env.world.draw_pile)
        encoded = encode_information(info)
        assert encoded.numeric.shape == (301,)
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


def anger_world(upgraded=False):
    from sts2_env.az.scenarios import DeckEntry
    r = replace(recipe(105), player_hp=80, encounter_id="setup_bygone_effigy_elite",
                deck=(DeckEntry("ANGER", upgraded, 5), DeckEntry("ASHEN_STRIKE", False, 1),
                      DeckEntry("TRUE_GRIT", True, 1), DeckEntry("BURNING_PACT", False, 1),
                      DeckEntry("DEFEND_IRONCLAD", False, 4)))
    return ObservableCombatAdapter(r, reward_version=V3)


@pytest.mark.parametrize("upgraded", (False, True))
def test_generated_copy_conservation_and_terminal_kill(upgraded):
    from collections import Counter
    from sts2_env.az.information import PublicHistory
    env = anger_world(upgraded)
    pool = env.world.hand + env.world.draw_pile
    card = next(c for c in pool if c.card_id.name == "ANGER")
    pool.remove(card)
    env.world.hand, env.world.draw_pile = [card], pool
    # Native engine refuses generated cards once combat has ended.
    env.world.enemies[0].current_hp = 1
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, GEN_CONTENT, *env.public_initial)
    env.step(11)
    info = env.information
    token = "ANGER+" if upgraded else "ANGER"
    assert info.termination_reason == "win"
    assert not info.history.generated
    assert Counter(info.hand + info.draw_composition + info.discard + info.exhaust) == Counter(info.known_deck)
    assert not env.world.discard_pile


def test_generating_beyond_initial_capacity_and_hidden_search():
    from sts2_env.gym_env.action_space import action_to_card_and_target
    initialize_worker()
    env = anger_world()
    model = PolicyValueNetwork("observable", V3, GEN_CONTENT)
    while not env.outcome().done:
        info = env.information
        anger_actions = [int(a) for a in np.flatnonzero(info.legal_mask) if a and not info.choice
                         and info.hand[action_to_card_and_target(int(a))[0]] == "ANGER"]
        if len(info.known_deck) + len(info.history.generated) > 20:
            break
        env.step(anger_actions[0] if anger_actions else 0)
    info = env.information
    assert info.termination_reason is None and len(info.known_deck) + len(info.history.generated) > 20
    assert len(info.history.generated) > 5
    changed = clone_state(env.world)
    changed.draw_pile.reverse()
    changed.rng.next_int(0, 100000)
    other = observe(changed, info.history, info.limits, 80, V3, GEN_CONTENT, *env.public_initial)
    assert info == other
    saved = card_base._next_instance_id
    a = plan_observable(info, model, model_version="gen", budget=8, search_seed=2)
    b = plan_observable(other, model, model_version="gen", budget=8, search_seed=2)
    assert np.array_equal(a.root_visits, b.root_visits) and a.action == b.action
    assert card_base._next_instance_id == saved
    particle = BeliefSampler().sample(info, np.random.default_rng(4))
    assert sum(len(getattr(particle.world, name)) for name in ("hand", "draw_pile", "discard_pile", "exhaust_pile")) > 20
    with pytest.raises(ValueError):
        replace(info, history=replace(info.history, generated=())).validate()
    with pytest.raises(ValueError):
        replace(info, content_version=G1_CONTENT).validate()
    event = info.history.generated[0]
    with pytest.raises(ValueError):
        replace(info, history=replace(info.history, generated=(replace(event, result_token="BASH"),))).validate()


def test_generated_parallel_replay_and_update(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    initialize_worker()
    records = frozen_manifest(GEN_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(G1_CONTENT)}
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, GEN_CONTENT)
    save_checkpoint(path, model, "generated", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, G1_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "generated",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (105,110,120,125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=GEN_CONTENT)
    for a,b in zip(serial,parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    assert ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=GEN_CONTENT).size == replay.size
    samples,_ = replay.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])
