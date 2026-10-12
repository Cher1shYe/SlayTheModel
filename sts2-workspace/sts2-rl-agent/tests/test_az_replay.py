from copy import deepcopy
from dataclasses import replace
import json
import numpy as np
import pytest
import torch

from sts2_env.az.config import EpisodeLimits, content_hash
from sts2_env.az.learner import Learner
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.self_play import CollectionJob, Collector, collect_episode, file_digest, initialize_worker


@pytest.fixture
def job(tmp_path):
    initialize_worker()
    torch.manual_seed(7)
    checkpoint = tmp_path / "initial.pt"
    save_checkpoint(checkpoint, PolicyValueNetwork("observable"), "test", {}, {})
    return CollectionJob("0", 0, 42, starter_scenario(1).to_dict(), str(checkpoint),
                         file_digest(checkpoint), "test", str(tmp_path / "errors"), 4, EpisodeLimits(3, 100))


def test_serial_parallel_labels_and_persistent_pool(job):
    jobs = [replace(job, job_id=str(i)) for i in range(3)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as collector:
        parallel = collector.collect(jobs)
        again = collector.collect(jobs)
    def labels(episodes):
        return [[{k: v for k, v in r.items() if k != "search_seconds"} for r in e["rows"]] for e in episodes]
    assert labels(serial) == labels(parallel) == labels(again)
    assert {e["worker_pid"] for e in again} <= {e["worker_pid"] for e in parallel}


def test_commit_reload_eviction_retry_and_tensor_boundary(job, tmp_path):
    replay = ReplayBuffer(tmp_path / "replay", capacity=5)
    first = collect_episode(job)
    assert replay.commit(first)
    assert not replay.commit(collect_episode(job))
    second = collect_episode(replace(job, job_id="1"))
    replay.commit(second)
    assert replay.size == 3 and len(replay.committed) == 2
    restored = ReplayBuffer(tmp_path / "replay", capacity=5)
    assert not restored.commit(first)
    batch, counts = restored.sample(10, np.random.default_rng(3))
    assert set(batch[0]) == {"observation", "policy_target", "z"}
    assert sum(counts.values()) == 10
    assert all(r["z"] == -1 and r["termination_reason"] == "time_limit" for r in second["rows"])
    with pytest.raises(ValueError):
        ReplayBuffer(tmp_path / "replay", capacity=5, information_mode="full_state_debug")


@pytest.mark.parametrize("mutation", ["incomplete", "test", "version", "partial", "pi", "nan", "debug", "mask"])
def test_reject_invalid_episodes(job, tmp_path, mutation):
    episode = collect_episode(job)
    if mutation == "incomplete": episode["complete"] = False
    elif mutation == "test": episode["split"] = "test"
    elif mutation == "partial": episode["rows"].pop()
    elif mutation == "version": episode["rows"][0]["reward_version"] = "future"
    elif mutation == "debug": episode["rows"][0]["information_mode"] = "full_state_debug"
    elif mutation == "pi": episode["rows"][0]["policy_target"][0] += 0.1
    elif mutation == "nan": episode["rows"][0]["observation"]["numeric"][0] = float("nan")
    elif mutation == "mask": episode["rows"][0]["observation"]["legal_mask"][0] = False
    replay = ReplayBuffer(tmp_path / "replay")
    with pytest.raises(ValueError): replay.commit(episode)
    assert replay.size == 0


def test_balances_families_then_episodes(job, tmp_path):
    episode = collect_episode(job)
    replay = ReplayBuffer(tmp_path / "replay")
    for i in range(10):
        copy = deepcopy(episode)
        copy["episode_id"] = content_hash(i)
        for row in copy["rows"]:
            row["episode_id"] = copy["episode_id"]
            row["family_id"] = "rare" if i == 0 else "common"
        replay.commit(copy)
    _, counts = replay.sample(5000, np.random.default_rng(8))
    assert 0.47 < counts["rare"] / 5000 < 0.53


def test_fixed_batch_overfit_and_champion_unchanged(job, tmp_path):
    replay = ReplayBuffer(tmp_path / "replay")
    replay.commit(collect_episode(job))
    champion = PolicyValueNetwork("observable")
    original = deepcopy(champion.state_dict())
    learner = Learner(champion)
    samples, _ = replay.sample(16, np.random.default_rng(0))
    history = [learner.update(samples) for _ in range(100)]
    assert history[-1]["loss"] < history[0]["loss"] * 0.65
    assert history[-1]["kl_target_policy"] < 0.03
    assert history[-1]["value_mae"] < 0.05
    assert all(np.isfinite(h["gradient_norm"]) for h in history)
    assert all(torch.equal(original[k], v) for k, v in champion.state_dict().items())


def test_failed_worker_and_modified_checkpoint_are_not_losses(job):
    bad = replace(job, model_version="wrong")
    with Collector(1) as collector:
        with pytest.raises(ValueError): collector.collect([bad])
    with open(job.checkpoint, "ab") as stream: stream.write(b"changed")
    with pytest.raises(ValueError, match="modified"): collect_episode(job)


def test_interrupted_commit_manifest_is_authoritative(job, tmp_path, monkeypatch):
    import sts2_env.az.replay_buffer as module
    replay = ReplayBuffer(tmp_path / "replay")
    episode = collect_episode(job)
    atomic = module.atomic_json
    def interrupted(path, value):
        if path.name == "manifest.json":
            raise OSError("simulated interruption")
        atomic(path, value)
    monkeypatch.setattr(module, "atomic_json", interrupted)
    with pytest.raises(OSError): replay.commit(episode)
    assert replay.size == ReplayBuffer(tmp_path / "replay").size == 0
    monkeypatch.setattr(module, "atomic_json", atomic)
    assert replay.commit(episode)
    path = tmp_path / "replay" / "episodes" / f"{episode['episode_id']}.json"
    payload = json.loads(path.read_text())
    payload["job_id"] = "tampered"
    atomic(path, payload)
    with pytest.raises(ValueError, match="checksum"):
        ReplayBuffer(tmp_path / "replay")
