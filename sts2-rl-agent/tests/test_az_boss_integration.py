from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import BOSS_CONTENT, SUMMON_CONTENT
from sts2_env.az.generation import generate_recipe
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.information import BeliefSampler
from sts2_env.az.encoder import encode_information, schema_for
from sts2_env.az.rewards import V6


def recipe(job=0):
    return replace(generate_recipe(42, 0, job, content_version=SUMMON_CONTENT),
                   content_manifest_version=BOSS_CONTENT, encounter_id="setup_test_subject_boss", player_hp=80)


def test_boss_initial_and_end_turn():
    env = ObservableCombatAdapter(recipe(), reward_version=V6)
    info = env.information
    assert list(encode_information(info).numeric.shape) == schema_for("observable", V6, BOSS_CONTENT)["shapes"]["numeric"]
    particle = BeliefSampler().sample(info, np.random.default_rng(0))
    particle.step(0)
    env.step(0)
    assert env.information.player_hp == particle.info.player_hp == 60


@pytest.mark.parametrize("slot", range(180))
def test_complete_boss_pool_game_particle_parity(slot):
    from sts2_env.search.mcts import clone_state
    env = ObservableCombatAdapter(generate_recipe(42, 0, slot, content_version=BOSS_CONTENT), reward_version=V6)
    rng = np.random.default_rng(slot + 800)
    while not env.outcome().done:
        info = env.information
        assert list(encode_information(info).numeric.shape) == schema_for("observable", V6, BOSS_CONTENT)["shapes"]["numeric"]
        particle = BeliefSampler().sample(info, rng)
        for attr in ("draw_pile", "discard_pile"):
            available = list(getattr(particle.world, attr))
            ordered = []
            for card in getattr(env.world, attr):
                twin = next(c for c in available if (c.card_id, c.upgraded) == (card.card_id, card.upgraded))
                available.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
    assert env.outcome().reward == env.information.terminal_value()


def advance_form(env):
    from sts2_env.az.information import observe
    before = env.information
    phase = before.boss.phase.knock_out()
    env.world.kill_creature(env.world.enemies[0])
    history = replace(before.history, boss_events=phase.events)
    env._information = observe(env.world, history, env.limits, env.recipe.player_hp, V6, BOSS_CONTENT,
                               before.known_deck, (100,))
    env.step(0)


@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("job", [0, 30, 60, 90, 120, 150])
def test_later_forms_full_adapter_until_terminal(phase, job):
    from sts2_env.search.mcts import clone_state
    env = ObservableCombatAdapter(recipe(job), reward_version=V6)
    for _ in range(phase):
        advance_form(env)
    rng = np.random.default_rng(job + phase)
    while not env.outcome().done:
        info = env.information
        particle = BeliefSampler().sample(info, rng)
        for attr in ("draw_pile", "discard_pile"):
            available = list(getattr(particle.world, attr))
            ordered = []
            for card in getattr(env.world, attr):
                twin = next(c for c in available if (c.card_id,c.upgraded)==(card.card_id,card.upgraded))
                available.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
    assert env.outcome().reward == env.information.terminal_value()


def test_boss_spawn_replay_and_network_update(tmp_path):
    from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
    from sts2_env.az.self_play import initialize_worker, CollectionJob, Collector, collect_episode, file_digest
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.replay_buffer import ReplayBuffer
    from sts2_env.az.learner import Learner
    from sts2_env.az.rewards import V5
    initialize_worker()
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V6, BOSS_CONTENT)
    save_checkpoint(path, model, "boss-test", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V5, SUMMON_CONTENT)
    jobs = [CollectionJob(str(i), 0, 42, generate_recipe(42,0,i,content_version=BOSS_CONTENT).to_dict(),
                          str(path), file_digest(path), "boss-test", str(tmp_path / "errors"),
                          2, EpisodeLimits(8,100), V6) for i in (24,27,87,177)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V6, content_version=BOSS_CONTENT)
    for a,b in zip(serial, parallel):
        assert len(a["rows"]) == len(b["rows"])
        for x,y in zip(a["rows"],b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    loaded = ReplayBuffer(tmp_path / "replay", reward_version=V6, content_version=BOSS_CONTENT)
    assert loaded.size == replay.size
    samples,_ = loaded.sample(8,np.random.default_rng(0))
    assert np.isfinite(Learner(model).update(samples)["loss"])


def test_boss_evaluation_recomputes_v6_and_strata():
    from sts2_env.az.evaluation import evaluate, promotion_gate
    env_recipe = replace(recipe(), split="validation")
    rows = evaluate(None, "random", [env_recipe], simulations=0, policy="random", reward_version=V6)
    assert not promotion_gate(rows, rows, required_count=1, reward_version=V6)["promote"]
    with pytest.raises(ValueError, match="utility"):
        promotion_gate(rows, [{**rows[0], "reward": 0.999}], required_count=1, reward_version=V6)
    with pytest.raises(ValueError, match="stratum"):
        promotion_gate(rows, [{**rows[0], "family_id": "wrong"}], required_count=1, reward_version=V6)


def test_boss_hidden_draw_and_rng_do_not_change_public_search():
    from sts2_env.az.observable_puct import plan_observable
    from sts2_env.az.network import PolicyValueNetwork
    from sts2_env.az.self_play import initialize_worker
    from sts2_env.core.rng import Rng
    from sts2_env.az.information import observe
    initialize_worker()
    env = ObservableCombatAdapter(recipe(), reward_version=V6)
    info = env.information
    model = PolicyValueNetwork("observable", V6, BOSS_CONTENT)
    first = plan_observable(info, model, model_version="test", budget=4, search_seed=11)
    env.world.draw_pile.reverse()
    env.world.rng = Rng(9876)
    perturbed = observe(env.world, info.history, info.limits, info.initial_hp, V6, BOSS_CONTENT, info.known_deck, (100,))
    assert perturbed == info
    second = plan_observable(perturbed, model, model_version="test", budget=4, search_seed=11)
    assert first.action == second.action
    assert np.array_equal(first.policy_target, second.policy_target)


def test_boss_seed_splits_are_disjoint_from_previous_manifests():
    from pathlib import Path
    from sts2_env.az.scenarios import load_manifest
    from sts2_env.az.generation import frozen_manifest
    heldout = [r for r in frozen_manifest(BOSS_CONTENT) if r.split != "train"]
    training = [generate_recipe(seed, iteration, job, content_version=BOSS_CONTENT)
                for seed in (42,43) for iteration in range(3) for job in range(180)]
    new = {r.environment_seed for r in heldout + training}
    assert len(new) == len(heldout) + len(training)
    for path in Path("data/az").glob("*manifest.json"):
        if "boss" not in path.name:
            assert not new.intersection(r.environment_seed for r in load_manifest(path))
