from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import G1_CONTENT, EXPANDED_CONTENT, DECK_CONTENT
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
    return generate_recipe(seed, 0, slot, content_version=G1_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_g1_complete_game_particle_parity(slot):
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        encoded = encode_information(info)
        assert encoded.numeric.shape == (286,)
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


def pending_choice(token="BURNING_PACT", encounter="setup_bygone_effigy_elite"):
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.information import PublicHistory
    r = replace(recipe(105), encounter_id=encounter, player_hp=80,
                deck=(DeckEntry("ASHEN_STRIKE", False, 1), DeckEntry("TRUE_GRIT", True, 1),
                      DeckEntry("BURNING_PACT", False, 1), DeckEntry("DEFEND_IRONCLAD", False, 3)))
    env = ObservableCombatAdapter(r, reward_version=V3)
    pool = env.world.hand + env.world.draw_pile
    first = next(c for c in pool if c.card_id.name == token)
    pool.remove(first)
    env.world.hand = [first, *pool[:3]]
    env.world.draw_pile = pool[3:]
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, G1_CONTENT, *env.public_initial)
    env.step(1)
    assert env.information.choice is not None
    return env


@pytest.mark.parametrize("token", ("TRUE_GRIT", "BURNING_PACT"))
def test_pending_choice_hidden_isolation_and_search(token):
    initialize_worker()
    env = pending_choice(token)
    info = env.information
    other_world = clone_state(env.world)
    other_world.draw_pile.reverse()
    other_world.rng.next_int(0, 100000)
    # The observer must not inspect either the engine continuation or AI memory.
    other_world._pending_play = {"private": "unreadable"}
    other_world.enemy_ais[other_world.enemies[0].combat_id].state_log = None
    changed = observe(other_world, info.history, info.limits, 80, V3, G1_CONTENT, *env.public_initial)
    assert info == changed
    model = PolicyValueNetwork("observable", V3, G1_CONTENT)
    saved = card_base._next_instance_id
    a = plan_observable(info, model, model_version="g1", budget=12, search_seed=17)
    b = plan_observable(changed, model, model_version="g1", budget=12, search_seed=17)
    assert np.array_equal(a.root_visits, b.root_visits) and a.action == b.action
    assert card_base._next_instance_id == saved
    p = BeliefSampler().sample(info, np.random.default_rng(5))
    sibling = BeliefSampler().sample(info, np.random.default_rng(5))
    p.step(1)
    assert sibling.info == info and env.information == info
    assert sibling.world.pending_choice is not None and env.world.pending_choice is not None


def test_choice_limits_and_legacy_rejection():
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.information import PublicHistory
    env = pending_choice()
    info = env.information
    terminal = observe(env.world, info.history, EpisodeLimits(max_turns=100, max_decisions=1),
                       80, V3, G1_CONTENT, *env.public_initial)
    assert terminal.termination_reason == "time_limit" and not any(terminal.legal_mask)
    with pytest.raises(ValueError):
        replace(info, content_version=EXPANDED_CONTENT).validate()
    with pytest.raises(ValueError):
        replace(info, choice=replace(info.choice, mechanism="unknown")).validate()
    with pytest.raises(ValueError):
        replace(info, legal_mask=(True,)*115).validate()


def test_g1_parallel_replay_learning_and_versions(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.learner import Learner
    from sts2_env.az.coordinator import Coordinator, TrainingConfig
    records = frozen_manifest(G1_CONTENT)
    validate_manifest(records)
    assert not {r.environment_seed for r in records} & {r.environment_seed for r in frozen_manifest(EXPANDED_CONTENT)}
    manifest = tmp_path / "manifest.json"
    save_manifest(manifest, records)
    coordinator = Coordinator(tmp_path / "coordinator", manifest,
                              TrainingConfig(iterations=10, content_version=G1_CONTENT, reward_version=V3))
    coordinator.close()
    initialize_worker()
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, G1_CONTENT)
    save_checkpoint(path, model, "g1", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, EXPANDED_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "g1",
                         str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (105, 110, 120, 125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=G1_CONTENT)
    for a,b in zip(serial, parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"], b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    restored = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=G1_CONTENT)
    assert restored.size == replay.size
    samples, _ = replay.sample(8, np.random.default_rng(9))
    assert np.isfinite(Learner(model).update(samples)["loss"])

