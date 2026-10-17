"""P3 all-content runner contract: reproducible episodes and honest rejections."""
import numpy as np
import pytest

from sts2_env.az import all_runner
from sts2_env.az.config import EpisodeLimits

CONFIG = 'configs/az_all_xs_v1/config.json'
PROTOCOL = 'configs/az_all_xs_v1/protocol.json'


def test_training_recipes_are_reproducible_and_admitted():
    first = all_runner.training_recipes(0, 4)
    second = all_runner.training_recipes(0, 4)
    assert first == second
    assert len({recipe.scenario_id for recipe in first}) == 4
    from sts2_env.az.all_decks import admitted_encounters
    assert all(recipe.encounter_id in admitted_encounters() for recipe in first)


def test_collection_records_rejected_recipes(monkeypatch):
    model = object()
    calls = []

    def fake(job, model_):
        calls.append(job.scenario['scenario_id'])
        if job.scenario['scenario_id'].endswith('-0000'):
            raise ValueError('public contract rejected this recipe')
        return {'episode_id': 'x' * 64, 'rows': [], 'outcome': {}}

    monkeypatch.setattr(all_runner, 'collect_entity_episode', fake)
    recipes = all_runner.training_recipes(0, 2)
    failures = []
    episodes = all_runner.collect(model, recipes, iteration=0, budget=1, error_dir='out',
                                  limits=EpisodeLimits(max_turns=2, max_decisions=4),
                                  version='v', seed=0, failures=failures)
    assert len(episodes) == 1
    assert failures[0]['scenario_id'] == recipes[0].scenario_id
    assert 'public contract' in failures[0]['error']
    with pytest.raises(ValueError):
        all_runner.collect(model, recipes, iteration=0, budget=1, error_dir='out',
                           limits=EpisodeLimits(max_turns=2, max_decisions=4),
                           version='v', seed=0)


def test_evaluation_counts_contract_rejections(monkeypatch):
    import json
    from pathlib import Path
    protocol = json.loads((Path(__file__).resolve().parents[1] / PROTOCOL).read_text(encoding='utf-8'))
    recipes = all_runner.protocol_recipes(protocol, 'validation')[:3]

    def fake_evaluate(model, version, batch, **kwargs):
        if batch[0].scenario_id == recipes[1].scenario_id:
            raise ValueError('public contract rejected this evaluation')
        return [dict(reward=0.5, termination_reason='win', final_hp=60, turns=3, decisions=5,
                     decision_seconds=[0.01], errors=0, illegal_actions=0)]

    monkeypatch.setattr(all_runner, 'evaluate', fake_evaluate)
    summary, kept = all_runner.evaluate_recipes(object(), recipes, version='v', error_dir='out')
    assert summary['episodes'] == 2 and len(kept) == 2
    assert summary['contract_rejections'] == 1
    assert summary['contract_rejected'][0]['scenario_id'] == recipes[1].scenario_id
    assert summary['mean_utility'] == 0.5


def test_preflight_accepts_the_frozen_plan():
    result = all_runner.preflight(CONFIG, PROTOCOL, iterations=1, episodes=1,
                                  max_turns=3, max_decisions=8)
    assert result['ready'] is True
    assert result['training'] == {'planned': 1, 'ok': 1, 'errors': []}
    assert result['validation']['checked'] == 64
    assert result['validation']['ok'] == 64


def test_collection_is_reproducible_for_a_seed(tmp_path):
    config = all_runner.load_frozen_config(CONFIG)
    model = all_runner.fresh_model(config)
    recipe = all_runner.training_recipes(0, 1)[0]
    kwargs = dict(iteration=0, budget=2, limits=EpisodeLimits(max_turns=2, max_decisions=6),
                  version='repro', seed=7)
    first = all_runner.collect(model, [recipe], error_dir=tmp_path / 'a', **kwargs)[0]
    second = all_runner.collect(model, [recipe], error_dir=tmp_path / 'b', **kwargs)[0]
    assert first['episode_id'] == second['episode_id']
    assert [row['chosen_action'] for row in first['rows']] == \
           [row['chosen_action'] for row in second['rows']]
    assert [row['policy_target'] for row in first['rows']] == \
           [row['policy_target'] for row in second['rows']]


def test_paired_gain_is_deterministic_and_needs_matching_episodes():
    baseline = [{'scenario_id': f's{index}', 'reward': 0.0} for index in range(10)]
    candidate = [{'scenario_id': f's{index}', 'reward': 0.1} for index in range(10)]
    first = all_runner.paired_gain(baseline, candidate)
    second = all_runner.paired_gain(baseline, candidate)
    assert first == second
    assert first['mean_gain'] == pytest.approx(0.1)
    assert first['episodes'] == 10
    with pytest.raises(ValueError):
        all_runner.paired_gain(baseline, candidate[:9])


def test_run_reports_baseline_timing_and_paired_comparison(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    protocol = json.loads((Path(__file__).resolve().parents[1] / PROTOCOL).read_text(
        encoding='utf-8'))
    calls = {'evaluate': 0}

    def fake_collect(model, recipes, **kwargs):
        return [dict(episode_id='a' * 64, rows=[{}, {}],
                     outcome={'termination_reason': 'win'})]

    def fake_update(model, replay, **kwargs):
        return model, [{'loss': 0.5}]

    def fake_evaluate(model, recipes, *, version, error_dir, limits=None):
        calls['evaluate'] += 1
        base = calls['evaluate'] == 1
        rows = [dict(scenario_id=recipe.scenario_id,
                     encounter_id=recipe.encounter_id,
                     reward=0.1 if base else 0.2, termination_reason='win',
                     final_hp=50, turns=3, decisions=5, decision_seconds=[0.01],
                     errors=0, illegal_actions=0) for recipe in recipes]
        summary = dict(episodes=len(rows), win_rate=1.0,
                       mean_utility=sum(row['reward'] for row in rows) / len(rows),
                       contract_rejections=0, contract_rejected=[])
        return summary, rows

    class FakeReplay:
        def __init__(self, *args, **kwargs):
            self.size = 0

        def commit(self, episode):
            self.size += len(episode['rows'])

    monkeypatch.setattr(all_runner, 'collect', fake_collect)
    monkeypatch.setattr(all_runner, 'update', fake_update)
    monkeypatch.setattr(all_runner, 'evaluate_recipes', fake_evaluate)
    monkeypatch.setattr(all_runner, 'EntityReplayBuffer', FakeReplay)
    monkeypatch.setattr(all_runner, 'save_transformer_checkpoint', lambda *a, **k: None)
    report = all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1,
                            updates=1, budget=1, seed=0, log=lambda *args: None)
    assert report['baseline']['mean_utility'] == pytest.approx(0.1)
    record = report['history'][0]
    assert set(record['seconds']) == {'collect', 'update', 'evaluate', 'total'}
    assert record['paired_vs_baseline']['mean_gain'] == pytest.approx(0.1)
    assert record['paired_vs_baseline']['episodes'] == 64
    assert (tmp_path / 'report.json').exists()


def test_parallel_collection_matches_sequential(tmp_path):
    config = all_runner.load_frozen_config(CONFIG)
    model = all_runner.fresh_model(config)
    recipes = all_runner.training_recipes(0, 2)
    limits = EpisodeLimits(max_turns=2, max_decisions=6)
    kwargs = dict(iteration=0, budget=1, error_dir=tmp_path / 'errors', limits=limits,
                  version='par', seed=3)
    sequential = all_runner.collect(model, recipes, **kwargs)
    parallel = all_runner.collect(model, recipes, workers=2, **kwargs)
    assert [e['episode_id'] for e in sequential] == [e['episode_id'] for e in parallel]
    assert [e['rows'][0]['chosen_action'] for e in sequential] == \
           [e['rows'][0]['chosen_action'] for e in parallel]
    assert [e['rows'][0]['policy_target'] for e in sequential] == \
           [e['rows'][0]['policy_target'] for e in parallel]


def test_one_episode_update_changes_weights(tmp_path):
    import torch
    config = all_runner.load_frozen_config(CONFIG)
    model = all_runner.fresh_model(config)
    before = [p.detach().clone() for p in model.parameters()]
    recipe = all_runner.training_recipes(0, 1)[0]
    episodes = all_runner.collect(model, [recipe], iteration=0, budget=2,
                                  error_dir=tmp_path / 'errors',
                                  limits=EpisodeLimits(max_turns=2, max_decisions=6),
                                  version='test', seed=1)
    replay = all_runner.EntityReplayBuffer(tmp_path / 'replay', capacity=100,
                                           content_version=config['content'],
                                           reward_version=config['reward'])
    replay.commit(episodes[0])
    updated, history = all_runner.update(model, replay, learning_rate=3e-4, batch_size=4,
                                         updates=1, seed=0)
    assert history and np.isfinite(history[0]['loss'])
    assert any(not torch.equal(a, b) for a, b in zip(before, updated.parameters()))



