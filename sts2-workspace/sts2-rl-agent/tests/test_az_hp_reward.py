from copy import deepcopy
from dataclasses import replace
import numpy as np
import pytest
import torch
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.encoder import encode_information
from sts2_env.az.evaluation import promotion_gate
from sts2_env.az.information import BeliefSampler
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.rewards import V1, V2, terminal_reward
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.self_play import CollectionJob, collect_episode, file_digest, initialize_worker
from sts2_env.az.learner import Learner
from sts2_env.az.coordinator import save_training, restore_training


def test_terminal_hp_ordering_and_no_dense_reward():
    assert terminal_reward(None, 10, 20, 10, 40, V2) == 0
    assert terminal_reward("win", 20, 20, 0, 40, V2) == 1
    assert terminal_reward("win", 10, 20, 0, 40, V2) == .9
    assert terminal_reward("death", 0, 20, 40, 40, V2) == -1
    assert terminal_reward("death", 0, 20, 20, 40, V2) == -.9
    assert terminal_reward("time_limit", 10, 20, 20, 40, V2) == -.9
    assert terminal_reward("win", 1, 20, 0, 40, V2) > terminal_reward("death", 0, 20, 0, 40, V2)
    with pytest.raises(ValueError): terminal_reward("error", 0, 20, 0, 40, V2)


def test_particle_and_environment_agree_on_shaped_terminal():
    for seed in range(5):
        env = ObservableCombatAdapter(starter_scenario(seed, hp=20), reward_version=V2)
        info = env.information
        particle = BeliefSampler().sample(info, np.random.default_rng(42))
        assert particle.info == info and particle.info.initial_hp == 20
        rng = np.random.default_rng(seed)
        while not env.outcome().done:
            env.step(int(rng.choice(np.flatnonzero(env.information.legal_mask))))
        assert env.information.terminal_value() == env.outcome().reward
        assert env.outcome().initial_hp == 20


def test_v2_collection_replay_learner_and_checkpoint_isolation(tmp_path):
    initialize_worker()
    model = PolicyValueNetwork("observable", V2)
    checkpoint = tmp_path / "v2.pt"
    save_checkpoint(checkpoint, model, "v2", {}, {})
    with pytest.raises(ValueError): load_checkpoint(checkpoint, "observable", V1)
    restored, _ = load_checkpoint(checkpoint, "observable", V2)
    recipe = starter_scenario(5, hp=20)
    env = ObservableCombatAdapter(recipe, reward_version=V2)
    obs = encode_information(env.information)
    assert obs.numeric[-1] == .25 and len(obs.numeric) == 62
    restored.predict(obs)
    job = CollectionJob("v2", 0, 42, recipe.to_dict(), str(checkpoint), file_digest(checkpoint),
                        "v2", str(tmp_path / "errors"), 4, EpisodeLimits(3, 100), V2)
    episode = collect_episode(job)
    assert all(r["z"] == episode["rows"][0]["z"] for r in episode["rows"])
    with pytest.raises(ValueError): ReplayBuffer(tmp_path / "v1").commit(episode)
    replay = ReplayBuffer(tmp_path / "v2", reward_version=V2)
    replay.commit(episode)
    assert np.isfinite(Learner(model).train(replay, np.random.default_rng(1), 2, 8)[-1]["loss"])
    learner, rng = Learner(model), np.random.default_rng(5)
    history = learner.train(replay, rng, 1, 8)
    save_training(tmp_path / "training.pt", learner, rng, replay, "v2", {}, history, 0)
    batch, _ = replay.sample(8, rng)
    expected = learner.update(batch)
    resumed, resumed_rng, _ = restore_training(tmp_path / "training.pt", replay)
    again, _ = replay.sample(8, resumed_rng)
    assert batch == again and expected == resumed.update(again)


def row(i, win, hp=20, enemy=20):
    reason = "win" if win else "death"
    return dict(scenario_id=str(i), reward=terminal_reward(reason, hp, 20, enemy, 40, V2),
                termination_reason=reason, final_hp=hp, initial_hp=20, enemy_final_hp=enemy, enemy_max_hp=40)


def test_promotion_never_trades_a_loss_for_hp_only_improvement():
    old = [row(i, True, hp=1) for i in range(256)]
    new = [row(i, i != 0, hp=20) for i in range(256)]
    report = promotion_gate(old, new, reward_version=V2)
    assert report["confidence_interval"][0] > 0  # scalar utility alone would promote
    assert not report["promote"] and not report["win_priority_satisfied"]
    same_wins_better_hp = [row(i, True, hp=20) for i in range(256)]
    assert promotion_gate(old, same_wins_better_hp, reward_version=V2)["promote"]
