"""Interrupted collection preserves completed fights without changing seeds."""
from dataclasses import replace
import json

import pytest

from sts2_env.az import all_runner, entity_transition
from sts2_env.az.config import EpisodeLimits, content_hash
from sts2_env.az.episode_cache import cached_episode
from sts2_env.az.self_play import CollectionJob


def episode(job):
    return dict(complete=True, split='train', job_id=job.job_id,
                iteration=job.iteration, rows=[], outcome={'reward': 1},
                episode_id=content_hash([job.master_seed, job.iteration, job.job_id]))


def test_interrupted_collection_only_retries_missing_jobs(tmp_path, monkeypatch):
    calls = []
    fail = True

    def simulate(job, model, diagnostic):
        calls.append((job.job_id, job.master_seed))
        if fail and job.job_id == '000-01':
            raise RuntimeError('interrupted fight')
        return episode(job)

    monkeypatch.setattr(entity_transition, '_collect_entity_episode', simulate)
    kwargs = dict(iteration=0, budget=8, error_dir=tmp_path / 'errors',
                  limits=EpisodeLimits(), version='v', seed=100,
                  cache_dir=tmp_path / 'cache', cache_identity='frozen-run-model')
    recipes = all_runner.training_recipes(0, 3)
    failures = []
    first = all_runner.collect(None, recipes, failures=failures, **kwargs)
    assert len(first) == 2 and len(failures) == 1
    assert len(list((tmp_path / 'cache').glob('*.json'))) == 2
    fail = False
    calls.clear()
    resumed = all_runner.collect(None, recipes, **kwargs)
    assert calls == [('000-01', 101)]
    assert [e['job_id'] for e in resumed] == ['000-00', '000-01', '000-02']
    assert resumed[0] == first[0] and resumed[2] == first[1]


def job(tmp_path):
    return CollectionJob('000-00', 0, 42, {'scenario_id': 'recipe'}, '', '', 'v', '',
                         cache_dir=str(tmp_path), cache_identity='run-model')


@pytest.mark.parametrize('change', [dict(cache_identity='other-model'), dict(master_seed=43),
    dict(simulations=32), dict(leaf_mode='learned'), dict(scenario={'scenario_id': 'other'}),
    dict(limits=EpisodeLimits(max_turns=2, max_decisions=4))])
def test_cache_rejects_changed_inputs(tmp_path, change):
    original = job(tmp_path)
    cached_episode(original, lambda: episode(original))
    with pytest.raises(ValueError, match='identity mismatch'):
        cached_episode(replace(original, **change), lambda: pytest.fail('must not simulate'))


def test_cache_detects_corruption_and_never_saves_incomplete(tmp_path):
    original = job(tmp_path)
    with pytest.raises(ValueError, match='Invalid completed'):
        cached_episode(original, lambda: dict(episode(original), complete=False))
    assert not list(tmp_path.glob('*.json'))
    cached_episode(original, lambda: episode(original))
    path = tmp_path / '000-00.json'
    document = json.loads(path.read_text())
    document['episode']['outcome']['reward'] = -1
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='checksum'):
        cached_episode(original, lambda: pytest.fail('must not simulate'))


def test_parallel_workers_write_reusable_cache(tmp_path, monkeypatch):
    model = all_runner.fresh_model(all_runner.load_frozen_config('configs/az_all_xs_v1/config.json'))
    recipes = all_runner.training_recipes(0, 2)
    kwargs = dict(iteration=0, budget=1, error_dir=tmp_path / 'errors',
                  limits=EpisodeLimits(max_turns=1, max_decisions=2), version='test', seed=9,
                  cache_dir=tmp_path / 'cache', cache_identity='frozen-test-model')
    first = all_runner.collect(model, recipes, workers=2, **kwargs)
    assert len(list((tmp_path / 'cache').glob('*.json'))) == 2
    monkeypatch.setattr(entity_transition, '_collect_entity_episode',
                        lambda *args: pytest.fail('cached fights must not be simulated'))
    assert content_hash(all_runner.collect(model, recipes, workers=1, **kwargs)) == content_hash(first)


def test_failed_parallel_chunk_keeps_successful_worker_result(tmp_path, monkeypatch):
    from sts2_env.az import self_play
    calls = []

    def simulate(job, model, diagnostic):
        calls.append(job.job_id)
        if job.job_id == '000-01':
            raise RuntimeError('failed sibling')
        return episode(job)

    monkeypatch.setattr(entity_transition, '_collect_entity_episode', simulate)
    monkeypatch.setattr(self_play, 'collect_episode',
                        lambda job: entity_transition.collect_entity_episode(job, None))

    class FailedChunk:
        def collect(self, jobs):
            return [self_play.collect_episode(job) for job in jobs]

    model = all_runner.fresh_model(all_runner.load_frozen_config('configs/az_all_xs_v1/config.json'))
    failures = []
    results = all_runner.collect(model, all_runner.training_recipes(0, 2),
        iteration=0, budget=1, error_dir=tmp_path / 'errors', limits=EpisodeLimits(),
        version='test', seed=0, cache_dir=tmp_path / 'cache', cache_identity='frozen-model',
        workers=2, collector=FailedChunk(), failures=failures)
    assert len(results) == 1 and len(failures) == 1
    assert calls.count('000-00') == 1
