from copy import deepcopy
from dataclasses import replace, asdict
import json
import random
import time
import numpy as np
import pytest
import torch

from sts2_env.az.config import EpisodeLimits, content_hash
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.scenarios import starter_scenario, save_manifest
from sts2_env.az.model_factory import create_transformer, save_transformer_checkpoint
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.entity_replay import EntityReplayBuffer, pack_observation, unpack_observation
from sts2_env.az.entity_transition import public_snapshot, public_from_dict
from sts2_env.az.dynamic_search import plan_dynamic, search_dynamic, VERSION
from sts2_env.az.self_play import CollectionJob, Collector, collect_episode, file_digest, initialize_worker
from sts2_env.az.replay_buffer import episode_digest
from sts2_env.az.coordinator import Learner, save_training, restore_training, Coordinator, TrainingConfig
from sts2_env.az.information import observe, BeliefSampler
from sts2_env.search.clone import clone_state


@pytest.fixture(autouse=True)
def setup():
    initialize_worker()
    torch.manual_seed(17)
    random.seed(17)


def make_job(tmp_path, job_id='0'):
    initial = tmp_path / 'initial.pt'
    if not initial.exists():
        save_transformer_checkpoint(initial, create_transformer(), 'initial')
    return CollectionJob(job_id, 0, 17, starter_scenario(2).to_dict(), str(initial), file_digest(initial),
                         'initial', str(tmp_path/'errors'), 2, EpisodeLimits(4, 100), search_version=VERSION)


def test_public_codec_replay_atomic_reload_and_audit(tmp_path, monkeypatch):
    episode = collect_episode(make_job(tmp_path))
    replay = EntityReplayBuffer(tmp_path/'replay', capacity=8)
    assert replay.commit(episode)
    assert not replay.commit(episode)
    assert replay.size == 4
    for row in episode['rows']:
        assert 'legal_mask' not in row['public_information']
        assert pack_observation(unpack_observation(row['observation'])) == row['observation']
        assert encode_entities(public_from_dict(row['public_information'])) == unpack_observation(row['observation'])
    samples, counts = replay.sample(6, np.random.default_rng(9))
    replay.release_memory()
    assert replay._episodes is None
    assert replay.sample(6, np.random.default_rng(9)) == (samples, counts)
    reloaded = EntityReplayBuffer(tmp_path/'replay', capacity=8)
    assert reloaded.sample(6, np.random.default_rng(9)) == (samples, counts)
    bad = deepcopy(episode)
    bad['rows'][0]['observation']['actions'][0][0] = 'bad-key'
    with pytest.raises(ValueError):
        replay.commit(bad)
    from sts2_env.az import replay_buffer
    original = replay_buffer.atomic_json
    def fail_manifest(path, value):
        if str(path).endswith('manifest.json'):
            raise OSError('injected commit interruption')
        return original(path, value)
    second = collect_episode(make_job(tmp_path, '1'))
    monkeypatch.setattr(replay_buffer, 'atomic_json', fail_manifest)
    with pytest.raises(OSError):
        replay.commit(second)
    assert len(replay.committed) == 1
    assert len(EntityReplayBuffer(tmp_path/'replay', capacity=8).committed) == 1
    monkeypatch.setattr(replay_buffer, 'atomic_json', original)
    assert replay.commit(second)
    third = collect_episode(make_job(tmp_path, '2'))
    replay.commit(third)
    assert replay.size == 8 and len(replay.episodes) == 2 and len(replay.committed) == 3


def test_optimizer_rng_next_update_exact_resume(tmp_path):
    job = make_job(tmp_path)
    replay = EntityReplayBuffer(tmp_path/'replay')
    replay.commit(collect_episode(job))
    learner, rng = Learner(create_transformer()), np.random.default_rng(7)
    samples, _ = replay.sample(4, rng)
    history = [learner.update(samples, microbatch_size=2)]
    path = tmp_path/'training.pt'
    save_training(path, learner, rng, replay, 'candidate', {}, history, 0)
    samples, counts = replay.sample(4, rng)
    expected = learner.update(samples, microbatch_size=2)
    weights = deepcopy(learner.model.state_dict())
    expected_random = (random.random(), torch.rand(3))
    restored, rng2, history2 = restore_training(path, replay)
    assert replay.sample(4, rng2) == (samples, counts) and history2 == history
    assert restored.update(samples, microbatch_size=2) == expected
    assert all(torch.equal(v, restored.model.state_dict()[k]) for k, v in weights.items())
    assert random.random() == expected_random[0]
    assert torch.equal(torch.rand(3), expected_random[1])
    replay.commit(collect_episode(make_job(tmp_path, 'other')))
    with pytest.raises(ValueError, match='Replay changed'):
        restore_training(path, replay)


def test_microbatch_gradient_accumulation(tmp_path):
    replay = EntityReplayBuffer(tmp_path/'replay')
    replay.commit(collect_episode(make_job(tmp_path)))
    samples, _ = replay.sample(5, np.random.default_rng(4))
    model = create_transformer()
    a, b = Learner(model), Learner(model)
    ma, mb = a.update(samples), b.update(samples, microbatch_size=2)
    assert abs(ma['loss'] - mb['loss']) < 1e-6
    for x, y in zip(a.model.parameters(), b.model.parameters()):
        torch.testing.assert_close(x.grad, y.grad, atol=2e-6, rtol=2e-4)


def test_search_public_boundary_and_particle_independence():
    env = ObservableCombatAdapter(starter_scenario(2))
    model = create_transformer()
    twin = clone_state(env.world)
    twin.draw_pile.reverse()
    for _ in range(10):
        twin.rng.next_int(0, 9999)
    info = observe(twin, env.information.history)
    original = env.information
    a = plan_dynamic(original, model, model_version='x', budget=4, search_seed=7)
    b = plan_dynamic(info, model, model_version='x', budget=4, search_seed=7)
    assert a.policy_target == b.policy_target and a.root_visits == b.root_visits
    assert env.information == original
    p = BeliefSampler().sample(original, np.random.default_rng(10))
    q = BeliefSampler().sample(original, np.random.default_rng(10))
    p.step(0)
    assert q.info == original
    with pytest.raises(TypeError):
        plan_dynamic(env.world, model, model_version='x')


def test_nodes_have_distinct_keys_and_enumeration_invariance():
    class State:
        def __init__(self, depth=0): self.depth = depth
        def terminal_value(self): return 1. if self.depth == 2 else None
        def key(self): return str(self.depth)
    class Particle:
        def __init__(self, public, rng): self.info = State(public.depth)
        def step(self, action):
            assert action.startswith(str(self.info.depth)+':')
            self.info = State(self.info.depth+1)
            return self.info
    def keys(s): return [f'{s.depth}:{i}' for i in range(s.depth+2)]
    def predict(s): return {k: 1/len(keys(s)) for k in keys(s)}, 0.
    a = search_dynamic(State(), Particle, predict, keys, model_version='x', budget=12, training=True)
    b = search_dynamic(State(), Particle, predict, lambda s: reversed(keys(s)), model_version='x', budget=12, training=True)
    assert a.root_visits == b.root_visits and a.policy_target == b.policy_target
    assert any(len(node.legal_mask) == 3 for e in a.root.edges.values() for node in e.outcomes.values())


def test_serial_parallel_collection(tmp_path):
    jobs = [make_job(tmp_path, str(i)) for i in range(2)]
    serial = [collect_episode(job) for job in jobs]
    with Collector(2) as collector:
        parallel = list(collector.iter_collect(jobs))
    assert [episode_digest(e) for e in serial] == [episode_digest(e) for e in parallel]


def test_parallel_evaluation_and_cache_match_serial(tmp_path):
    from sts2_env.az.evaluation import evaluate, evaluate_parallel
    from sts2_env.az.model_io import load_checkpoint
    job = make_job(tmp_path)
    model, _ = load_checkpoint(job.checkpoint, 'observable')
    recipes = [starter_scenario(3, 'validation')]
    expected = evaluate(model, 'initial', recipes, simulations=2, limits=job.limits, search_version=VERSION)
    with Collector(1) as collector:
        actual = evaluate_parallel(collector.pool, job.checkpoint, recipes, 2, 123, job.limits,
                                   tmp_path/'cache', search_version=VERSION)
        cached = evaluate_parallel(collector.pool, job.checkpoint, recipes, 2, 123, job.limits,
                                   tmp_path/'cache', search_version=VERSION)
    assert actual == cached
    assert [{k:v for k,v in r.items() if k != 'decision_seconds'} for r in expected] == [
        {k:v for k,v in r.items() if k != 'decision_seconds'} for r in actual]


class LocalCollector:
    def collect(self, jobs): return [collect_episode(j) for j in jobs]


def test_existing_coordinator_dynamic_resume(tmp_path):
    manifest = tmp_path/'manifest.json'
    save_manifest(manifest, [starter_scenario(2), starter_scenario(3, 'validation')])
    config = TrainingConfig(model_tier='XS', search_version=VERSION, workers=1, episodes_per_iteration=1,
        simulations=2, eval_simulations=2, validation_count=1, batch_size=2, microbatch_size=1,
        updates=2, iterations=1, max_decisions=3)
    run = Coordinator(tmp_path/'run', manifest, config)
    run.step(LocalCollector())
    assert run.state['phase'] == 'train'
    run.step()
    resumed = Coordinator(tmp_path/'run')
    resumed.step()
    assert resumed.state['phase'] == 'evaluate'
    resumed.step()
    resumed.step()
    assert resumed.state['phase'] == 'done'
    report = json.loads((tmp_path/'run/evaluation-0.json').read_text())
    assert report['promote'] is False


def test_replay_corruption_and_incompatible_versions(tmp_path):
    replay = EntityReplayBuffer(tmp_path/'replay')
    episode = collect_episode(make_job(tmp_path))
    replay.commit(episode)
    path = tmp_path/'replay/episodes'/f"{episode['episode_id']}.json.gz"
    path.write_bytes(b'corrupted')
    with pytest.raises((ValueError, OSError)):
        EntityReplayBuffer(tmp_path/'replay')
    with pytest.raises(ValueError):
        TrainingConfig(model_tier='XS')
    with pytest.raises(ValueError):
        TrainingConfig(search_version=VERSION)


def test_complete_natural_combat_reward_and_replay(tmp_path):
    job = replace(make_job(tmp_path), limits=EpisodeLimits())
    episode = collect_episode(job)
    assert episode['outcome']['termination_reason'] in ('win', 'death')
    replay = EntityReplayBuffer(tmp_path/'replay')
    replay.commit(episode)
    assert replay.size == episode['outcome']['decisions']
    expected = 1. if episode['outcome']['termination_reason'] == 'win' else -1.
    assert all(r['z'] == expected for r in episode['rows'])
