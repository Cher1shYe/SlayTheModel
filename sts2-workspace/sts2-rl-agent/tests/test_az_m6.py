from collections import Counter
from dataclasses import replace
import numpy as np
import pytest
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits, CONTENT_VERSION
from sts2_env.az.content import M6_CONTENT, PROFILES
from sts2_env.az.encoder import encode_information
from sts2_env.az.information import BeliefSampler, observe
from sts2_env.az.network import PolicyValueNetwork, load_checkpoint, save_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.rewards import V2
from sts2_env.az.scenarios import starter_scenario, balanced_selection
from sts2_env.az.self_play import CollectionJob, Collector, collect_episode, file_digest, initialize_worker
from sts2_env.az.learner import Learner
from sts2_env.search.clone import clone_state
from sts2_env.cards import base as card_base


def recipe(monster, seed=0, hp=80, split="train"):
    return replace(starter_scenario(seed, hp=hp, split=split), encounter_id=PROFILES[monster]["encounter"],
                   content_manifest_version=M6_CONTENT)


@pytest.mark.parametrize("monster", PROFILES)
def test_public_particle_engine_full_games(monster):
    transitions = 0
    for seed in range(6):
        env = ObservableCombatAdapter(recipe(monster, seed), reward_version=V2)
        rng = np.random.default_rng(seed)
        while not env.outcome().done:
            info = env.information
            particle = BeliefSampler().sample(info, rng)
            assert particle.info == info
            assert particle.world.shuffle_rng is particle.world.monster_ai_rng is particle.world.rng
            # Test only: couple sampled state to real hidden order/RNG to compare rules.
            for attr in ("draw_pile", "discard_pile"):
                available = list(getattr(particle.world, attr))
                ordered = []
                for real in getattr(env.world, attr):
                    card = next(c for c in available if c.card_id == real.card_id)
                    available.remove(card)
                    ordered.append(card)
                setattr(particle.world, attr, ordered)
            particle.world.rng = clone_state(env.world.rng)
            action = int(rng.choice(np.flatnonzero(info.legal_mask)))
            hypothetical = particle.step(action)
            env.step(action)
            assert hypothetical == env.information
            transitions += 1
        assert env.information.terminal_value() == env.outcome().reward
    assert transitions > 40


@pytest.mark.parametrize("monster", PROFILES)
def test_hidden_rng_order_does_not_change_labels(monster):
    initialize_worker()
    env = ObservableCombatAdapter(recipe(monster), reward_version=V2)
    model = PolicyValueNetwork("observable", V2, M6_CONTENT)
    for _ in range(4):
        info = env.information
        changed = clone_state(env.world)
        changed.draw_pile.reverse()
        for _ in range(20): changed.rng.next_int(0, 1000)
        changed.enemy_ais[changed.enemies[0].combat_id].state_log = None
        other = observe(changed, info.history, info.limits, info.initial_hp, V2, M6_CONTENT)
        assert other == info
        saved = card_base._next_instance_id
        a = plan_observable(info, model, model_version="m6", budget=16, search_seed=7, training=True)
        b = plan_observable(other, model, model_version="m6", budget=16, search_seed=7, training=True)
        assert np.array_equal(a.root_visits, b.root_visits) and a.action == b.action
        assert card_base._next_instance_id == saved and env.information == info
        env.step(0)
        if env.outcome().done: break


def test_new_mechanics_and_legacy_rejection():
    fuzzy = ObservableCombatAdapter(recipe("FUZZY_WURM_CRAWLER"), reward_version=V2)
    fuzzy.step(0)
    fuzzy.step(0)
    assert fuzzy.information.enemy_strength == 7
    hp = fuzzy.world.player.current_hp
    fuzzy.step(0)
    assert hp - fuzzy.world.player.current_hp == 11  # 4 base + 7 strength
    nibbit = ObservableCombatAdapter(recipe("NIBBIT"), reward_version=V2)
    nibbit.step(0)
    nibbit.step(0)
    assert nibbit.information.enemy_block == 5
    nibbit.step(0)
    assert nibbit.information.enemy_strength == 2
    with pytest.raises(ValueError):
        replace(recipe("NIBBIT"), content_manifest_version=CONTENT_VERSION)
    with pytest.raises(ValueError):
        replace(fuzzy.information, enemy_strength=0).validate()


def test_m6_schema_checkpoint_replay_training(tmp_path):
    initialize_worker()
    model = PolicyValueNetwork("observable", V2, M6_CONTENT)
    path = tmp_path / "initial.pt"
    save_checkpoint(path, model, "m6", {}, {})
    with pytest.raises(ValueError): load_checkpoint(path, "observable", V2)
    load_checkpoint(path, "observable", V2, M6_CONTENT)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V2, content_version=M6_CONTENT)
    jobs, episodes = [], []
    for i, monster in enumerate(PROFILES):
        r = recipe(monster, i)
        info = ObservableCombatAdapter(r, reward_version=V2).information
        obs = encode_information(info)
        assert len(obs.numeric) == 73 and obs.numeric[-1] == 1
        model.predict(obs)
        job = CollectionJob(str(i), 0, 42, r.to_dict(), str(path), file_digest(path), "m6",
                            str(tmp_path / "errors"), 2, EpisodeLimits(3, 100), V2)
        episode = collect_episode(job)
        jobs.append(job)
        episodes.append(episode)
        replay.commit(episode)
        with pytest.raises(ValueError): ReplayBuffer(tmp_path / "legacy", reward_version=V2).commit(episode)
    _, counts = replay.sample(3000, np.random.default_rng(42))
    assert len(counts) == 3 and all(900 < n < 1100 for n in counts.values())
    assert np.isfinite(Learner(model).train(replay, np.random.default_rng(3), 2, 8)[-1]["loss"])
    with Collector(2) as collector:
        parallel = collector.collect(jobs)
    for serial, other in zip(episodes, parallel):
        assert [{k: v for k, v in row.items() if k != "search_seconds"} for row in serial["rows"]] == [
            {k: v for k, v in row.items() if k != "search_seconds"} for row in other["rows"]]


def test_balanced_manifest_selection():
    recipes = [recipe(m, i + j * 100, split="validation") for j, m in enumerate(PROFILES) for i in range(90)]
    selection = balanced_selection(recipes, 256)
    assert sorted(Counter(r.encounter_id for r in selection).values()) == [85, 85, 86]
    assert sorted(Counter(r.encounter_id for r in balanced_selection(recipes, 150)).values()) == [50, 50, 50]
