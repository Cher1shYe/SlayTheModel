from copy import deepcopy
from dataclasses import asdict
import json
import random
import numpy as np
import pytest
import torch

from sts2_env.az.config import EpisodeLimits, atomic_json
from sts2_env.az.coordinator import Coordinator, TrainingConfig, restore_training, save_training
from sts2_env.az.evaluation import evaluate, promotion_gate
from sts2_env.az.learner import Learner
from sts2_env.az.network import PolicyValueNetwork, load_checkpoint, save_checkpoint
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import starter_scenario
from sts2_env.az.self_play import CollectionJob, collect_episode, file_digest, initialize_worker


def paired(old, new, n=256):
    return ([dict(scenario_id=str(i), reward=old, errors=0, illegal_actions=0) for i in range(n)],
            [dict(scenario_id=str(i), reward=new, errors=0, illegal_actions=0) for i in range(n)])


def test_promotion_accept_reject_error_small_and_reproducible():
    old, new = paired(-1, 1)
    report = promotion_gate(old, new)
    assert report["promote"] and report["confidence_interval"] == [2., 2.]
    assert report == promotion_gate(old, new)
    assert not promotion_gate(new, old)["promote"]
    assert not promotion_gate(old, old)["promote"]
    assert not promotion_gate(old[:4], new[:4])["promote"]
    assert not promotion_gate(old[:255], new[:255])["promote"]
    assert TrainingConfig().validation_count == 256
    new[0]["errors"] = 1
    assert not promotion_gate(old, new)["promote"]
    new[0]["scenario_id"] = "unpaired"
    with pytest.raises(ValueError): promotion_gate(old, new)


def test_optimizer_rng_next_batch_and_update_exactly_resume(tmp_path):
    initialize_worker()
    torch.manual_seed(17)
    random.seed(17)
    model = PolicyValueNetwork("observable")
    initial = tmp_path / "initial.pt"
    save_checkpoint(initial, model, "initial", {}, {})
    job = CollectionJob("0", 0, 17, starter_scenario(2).to_dict(), str(initial), file_digest(initial),
                        "initial", str(tmp_path / "errors"), 4, EpisodeLimits(4, 100))
    replay = ReplayBuffer(tmp_path / "replay")
    replay.commit(collect_episode(job))
    learner, rng = Learner(model), np.random.default_rng(7)
    samples, _ = replay.sample(8, rng)
    history = [learner.update(samples)]
    path = tmp_path / "training.pt"
    save_training(path, learner, rng, replay, "candidate", {}, history, 0)
    samples, counts = replay.sample(8, rng)
    expected_metrics = learner.update(samples)
    expected_weights = deepcopy(learner.model.state_dict())
    expected_random = (random.random(), torch.rand(3))
    restored, restored_rng, restored_history = restore_training(path, replay)
    restored_samples, restored_counts = replay.sample(8, restored_rng)
    assert restored_samples == samples and counts == restored_counts and restored_history == history
    assert restored.update(restored_samples) == expected_metrics
    assert all(torch.equal(v, restored.model.state_dict()[k]) for k, v in expected_weights.items())
    assert random.random() == expected_random[0]
    assert torch.equal(torch.rand(3), expected_random[1])
    payload = torch.load(path, weights_only=True)
    payload["schema_hash"] = "wrong"
    torch.save(payload, path)
    with pytest.raises(ValueError, match="schema"):
        restore_training(path, replay)


class LocalCollector:
    def __init__(self): self.jobs = []
    def collect(self, jobs):
        self.jobs.extend(jobs)
        return [collect_episode(j) for j in jobs]


def tiny_config():
    return TrainingConfig(workers=1, episodes_per_iteration=2, simulations=2, eval_simulations=2,
                          validation_count=2, batch_size=8, updates=2, iterations=1, max_decisions=3)


def test_coordinator_interrupted_commit_training_and_reject(tmp_path, monkeypatch):
    root = tmp_path / "run"
    run = Coordinator(root, "data/az/m0_manifest.json", tiny_config())
    original_commit = run.replay.commit
    def interrupted(episode):
        original_commit(episode)
        raise OSError("interrupted after episode commit")
    monkeypatch.setattr(run.replay, "commit", interrupted)
    with pytest.raises(OSError): run.step(LocalCollector())
    resumed = Coordinator(root)
    collector = LocalCollector()
    resumed.step(collector)
    assert len(collector.jobs) == 1 and len(resumed.replay.committed) == 2
    resumed.step()  # first update persisted
    assert resumed.state["phase"] == "train"
    resumed = Coordinator(root)
    resumed.step()  # second update
    assert resumed.state["phase"] == "evaluate"
    resumed.step()  # actual small paired evaluation, promotion disabled
    assert resumed.state["phase"] == "finalize" and not resumed.state["promote"]
    resumed = Coordinator(root)
    resumed.step()
    assert resumed.state["phase"] == "done" and resumed.state["champion"] == "initial.pt"
    pointer = json.loads((root / "champion.json").read_text())
    assert pointer["checkpoint"] == "initial.pt"
    candidate, payload = load_checkpoint(root / "candidate-0.pt", "observable")
    assert len(payload["statistics"]["history"]) == 2


def test_finalize_accept_and_pointer_repair(tmp_path):
    run = Coordinator(tmp_path / "run", "data/az/m0_manifest.json", tiny_config())
    run.step(LocalCollector())
    run.step()
    run.step()
    # Synthetic gate acceptance isolates atomic promotion; real small eval cannot promote.
    run.state.update(phase="finalize", promote=True)
    run.persist()
    run.step()
    assert run.state["champion"] == "candidate-0.pt"
    atomic_json(run.root / "champion.json", {"checkpoint": "stale"})
    restored = Coordinator(run.root)
    pointer = json.loads((run.root / "champion.json").read_text())
    assert pointer["checkpoint"] == restored.state["champion"]


def test_resume_manifest_and_configuration_rejected(tmp_path):
    run = Coordinator(tmp_path / "run", "data/az/m0_manifest.json", tiny_config())
    with pytest.raises(ValueError, match="configuration"):
        Coordinator(run.root, config=TrainingConfig())
    atomic_json(run.root / "recipes.json", [])
    with pytest.raises(ValueError, match="manifest"):
        Coordinator(run.root)


def test_public_baselines_reproducible_and_train_split_rejected():
    recipe = starter_scenario(1234, split="validation")
    for policy in ("random", "rule"):
        one = evaluate(None, policy, [recipe], simulations=0, policy=policy)
        two = evaluate(None, policy, [recipe], simulations=0, policy=policy)
        assert [{k: v for k, v in r.items() if k != "decision_seconds"} for r in one] == [
            {k: v for k, v in r.items() if k != "decision_seconds"} for r in two]
    with pytest.raises(ValueError):
        evaluate(None, "random", [starter_scenario(1)], policy="random")
