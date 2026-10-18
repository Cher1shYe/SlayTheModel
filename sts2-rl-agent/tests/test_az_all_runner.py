"""P3 all-content runner contract: reproducible episodes and honest rejections."""
from pathlib import Path
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


def test_training_recipes_stay_distinct_past_the_job_space():
    # The frozen plan asks for 48 episodes per iteration while only 16 job
    # coordinates exist; the master offset must keep every episode distinct.
    episodes = all_runner.training_recipes(0, 48)
    assert len({recipe.scenario_id for recipe in episodes}) == 48
    assert [recipe.scenario_id for recipe in episodes[:16]] == \
           [recipe.scenario_id for recipe in all_runner.training_recipes(0, 16)]


def test_frozen_training_plan_has_no_duplicate_recipes():
    ids = [recipe.scenario_id
           for iteration in range(8)
           for recipe in all_runner.training_recipes(iteration, 48)]
    assert len(ids) == 8 * 48
    assert len(set(ids)) == len(ids)


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
    assert result['validation'] == {'checked': 304, 'ok': 304, 'errors': []}
    assert result['test'] is None
    assert result['generator_manifest_sha']


def test_preflight_rejects_protocol_manifest_drift(tmp_path):
    import json
    from pathlib import Path
    protocol = json.loads((Path(__file__).resolve().parents[1] / PROTOCOL).read_text(
        encoding='utf-8'))
    protocol['generator_manifest_sha'] = '0' * 64
    path = tmp_path / 'protocol.json'
    path.write_text(json.dumps(protocol), encoding='utf-8')
    with pytest.raises(ValueError):
        all_runner.preflight(CONFIG, str(path), iterations=1, episodes=1, check_test=False)


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
        return [dict(episode_id='a' * 64, rows=[dict(policy_target={'end_turn': 1.0}, forced_action=False)] * 2,
                     outcome={'termination_reason': 'win'})]

    def fake_update(model, replay, **kwargs):
        kwargs['on_update'](model, dict(history=[{'loss': .5}]))
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
    monkeypatch.setattr(all_runner, 'save_transformer_checkpoint', lambda path, *a, **k: Path(path).write_bytes(b'fixture-checkpoint'))
    monkeypatch.setattr(all_runner, 'load_transformer_checkpoint', lambda *a, **k: (object(), {}))
    report = all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1,
                            updates=1, budget=1, seed=0, log=lambda *args: None)
    assert report['baseline']['mean_utility'] == pytest.approx(0.1)
    record = report['history'][0]
    assert set(record['seconds']) == {'collect', 'update', 'evaluate', 'total'}
    assert record['paired_vs_baseline']['mean_gain'] == pytest.approx(0.1)
    assert record['paired_vs_baseline']['episodes'] == 304
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




def test_legacy_weights_only_resume_is_rejected(tmp_path):
    (tmp_path / 'report.json').write_text('{}')
    with pytest.raises(ValueError, match='No v3 recovery state'):
        all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1, resume=True)


def test_test_split_opens_only_after_a_positive_validation_gain(tmp_path, monkeypatch):
    def fake_collect(model, recipes, **kwargs):
        return [dict(episode_id='d' * 64, rows=[dict(policy_target={'end_turn': 1.0}, forced_action=False)], outcome={'termination_reason': 'win'})]

    def fake_update(model, replay, **kwargs):
        kwargs['on_update'](model, dict(history=[{'loss': .5}]))
        return model, [{'loss': 0.5}]

    def fake_evaluate(model, recipes, *, version, error_dir, limits=None):
        baseline = 'baseline' in version
        rows = [dict(scenario_id=recipe.scenario_id, encounter_id=recipe.encounter_id,
                     reward=0.1 if baseline else 0.3, termination_reason='win',
                     final_hp=40, turns=2, decisions=4, decision_seconds=[0.01],
                     errors=0, illegal_actions=0) for recipe in recipes]
        return dict(episodes=len(rows), win_rate=1.0,
                    mean_utility=0.1 if baseline else 0.3,
                    contract_rejections=0, contract_rejected=[]), rows

    class FakeReplay:
        def __init__(self, *args, **kwargs):
            self.size = 0

        def commit(self, episode):
            self.size += 1

    monkeypatch.setattr(all_runner, 'collect', fake_collect)
    monkeypatch.setattr(all_runner, 'update', fake_update)
    monkeypatch.setattr(all_runner, 'evaluate_recipes', fake_evaluate)
    monkeypatch.setattr(all_runner, 'EntityReplayBuffer', FakeReplay)
    monkeypatch.setattr(all_runner, 'save_transformer_checkpoint', lambda path, *a, **k: Path(path).write_bytes(b'fixture-checkpoint'))
    monkeypatch.setattr(all_runner, 'load_transformer_checkpoint', lambda *a, **k: (object(), {}))
    report = all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1, updates=1,
                            budget=1, seed=0, include_test=True, log=lambda *args: None)
    assert report['test_gate']['passed'] is True
    assert 'test' in report

    def negative_evaluate(model, recipes, *, version, error_dir, limits=None):
        baseline = 'baseline' in version
        rows = [dict(scenario_id=recipe.scenario_id, encounter_id=recipe.encounter_id,
                     reward=0.3 if baseline else 0.0, termination_reason='win',
                     final_hp=40, turns=2, decisions=4, decision_seconds=[0.01],
                     errors=0, illegal_actions=0) for recipe in recipes]
        return dict(episodes=len(rows), win_rate=1.0,
                    mean_utility=0.3 if baseline else 0.0,
                    contract_rejections=0, contract_rejected=[]), rows

    monkeypatch.setattr(all_runner, 'evaluate_recipes', negative_evaluate)
    blocked = all_runner.run(CONFIG, PROTOCOL, tmp_path / 'blocked', iterations=1, episodes=1,
                             updates=1, budget=1, seed=0, include_test=True,
                             log=lambda *args: None)
    assert blocked['test_gate']['passed'] is False
    assert 'test' not in blocked


def test_validation_breakdown_covers_every_evaluated_encounter(tmp_path, monkeypatch):
    def fake_collect(model, recipes, **kwargs):
        return [dict(episode_id='e' * 64, rows=[dict(policy_target={'end_turn': 1.0}, forced_action=False)], outcome={'termination_reason': 'win'})]

    def fake_update(model, replay, **kwargs):
        kwargs['on_update'](model, dict(history=[{'loss': .5}]))
        return model, [{'loss': 0.5}]

    def fake_evaluate(model, recipes, *, version, error_dir, limits=None):
        baseline = 'baseline' in version
        rows = [dict(scenario_id=recipe.scenario_id, encounter_id=recipe.encounter_id,
                     reward=0.1 if baseline else 0.2,
                     termination_reason='win' if index % 2 == 0 else 'time_limit',
                     final_hp=40, turns=2, decisions=4, decision_seconds=[0.01],
                     errors=0, illegal_actions=0)
                for index, recipe in enumerate(recipes)]
        return dict(episodes=len(rows), win_rate=0.5, mean_utility=0.15,
                    contract_rejections=0, contract_rejected=[]), rows

    class FakeReplay:
        def __init__(self, *args, **kwargs):
            self.size = 0

        def commit(self, episode):
            self.size += 1

    monkeypatch.setattr(all_runner, 'collect', fake_collect)
    monkeypatch.setattr(all_runner, 'update', fake_update)
    monkeypatch.setattr(all_runner, 'evaluate_recipes', fake_evaluate)
    monkeypatch.setattr(all_runner, 'EntityReplayBuffer', FakeReplay)
    monkeypatch.setattr(all_runner, 'save_transformer_checkpoint', lambda path, *a, **k: Path(path).write_bytes(b'fixture-checkpoint'))
    monkeypatch.setattr(all_runner, 'load_transformer_checkpoint', lambda *a, **k: (object(), {}))
    report = all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1,
                            updates=1, budget=1, seed=0, log=lambda *args: None)
    breakdown = report['history'][0]['validation_by_encounter']
    assert sum(row['episodes'] for row in breakdown.values()) == 304
    assert all(0.0 <= row['win_rate'] <= 1.0 for row in breakdown.values())



def test_short_run_is_reproducible_for_a_seed(tmp_path):
    # Reproducibility needs a bounded fixture, not repeated full validation runs.
    # The complete frozen plan has separate coverage and preflight tests.
    import json
    from pathlib import Path
    config = json.loads(Path(CONFIG).read_text())
    protocol = json.loads(Path(PROTOCOL).read_text())
    protocol['validation'] = protocol['validation'][:4]
    config['evaluation']['validation_recipes'] = 4
    config_path, protocol_path = tmp_path / 'config.json', tmp_path / 'protocol.json'
    config_path.write_text(json.dumps(config))
    protocol_path.write_text(json.dumps(protocol))
    kwargs = dict(iterations=1, episodes=2, updates=1, budget=1, batch_size=8, seed=5,
                  max_turns=2, max_decisions=6, eval_max_turns=2, eval_max_decisions=6, log=lambda *args: None)
    first = all_runner.run(config_path, protocol_path, tmp_path / 'a', **kwargs)
    second = all_runner.run(config_path, protocol_path, tmp_path / 'b', **kwargs)
    assert first['history'][0]['episodes'] == second['history'][0]['episodes']
    assert first['history'][0]['outcomes'] == second['history'][0]['outcomes']
    assert first['final_validation']['mean_utility'] == pytest.approx(
        second['final_validation']['mean_utility'])
    assert first['history'][0]['paired_vs_baseline'] == \
           second['history'][0]['paired_vs_baseline']

def test_report_carries_config_and_protocol_provenance(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    def fake_collect(model, recipes, **kwargs):
        return [dict(episode_id='h' * 64, rows=[dict(policy_target={'end_turn': 1.0}, forced_action=False)], outcome={'termination_reason': 'win'})]

    def fake_update(model, replay, **kwargs):
        kwargs['on_update'](model, dict(history=[{'loss': .5}]))
        return model, [{'loss': 0.5}]

    def fake_evaluate(model, recipes, *, version, error_dir, limits=None):
        rows = [dict(scenario_id=recipe.scenario_id, encounter_id=recipe.encounter_id,
                     reward=0.1, termination_reason='win', final_hp=40, turns=2,
                     decisions=4, decision_seconds=[0.01], errors=0,
                     illegal_actions=0) for recipe in recipes]
        return dict(episodes=len(rows), win_rate=1.0, mean_utility=0.1,
                    contract_rejections=0, contract_rejected=[]), rows

    class FakeReplay:
        def __init__(self, *args, **kwargs):
            self.size = 0

        def commit(self, episode):
            self.size += 1

    monkeypatch.setattr(all_runner, 'collect', fake_collect)
    monkeypatch.setattr(all_runner, 'update', fake_update)
    monkeypatch.setattr(all_runner, 'evaluate_recipes', fake_evaluate)
    monkeypatch.setattr(all_runner, 'EntityReplayBuffer', FakeReplay)
    monkeypatch.setattr(all_runner, 'save_transformer_checkpoint', lambda path, *a, **k: Path(path).write_bytes(b'fixture-checkpoint'))
    monkeypatch.setattr(all_runner, 'load_transformer_checkpoint', lambda *a, **k: (object(), {}))
    report = all_runner.run(CONFIG, PROTOCOL, tmp_path, iterations=1, episodes=1, updates=1,
                            budget=1, seed=0, log=lambda *args: None)
    provenance = report['provenance']
    root = Path(__file__).resolve().parents[1]
    assert provenance['config_sha256'] == hashlib.sha256(
        (root / CONFIG).read_bytes()).hexdigest()
    assert provenance['protocol_sha256'] == hashlib.sha256(
        (root / PROTOCOL).read_bytes()).hexdigest()
    assert provenance['generator_manifest_sha']
    assert provenance['content'] == 'ironclad-colorless-all-v6'
    assert provenance['reward'] == 'risk-terminal-v7'

def test_target_stats_summarize_search_signal():
    stats = all_runner.target_stats([
        dict(rows=[dict(policy_target={'end_turn': 1.0}, forced_action=False),
                   dict(policy_target={'play:hand/0': 0.5, 'end_turn': 0.5}, forced_action=True)])
    ])
    assert stats['rows'] == 2
    assert stats['mean_entropy'] == pytest.approx((0.0 + 0.693147) / 2)
    assert stats['mean_max_prob'] == pytest.approx(0.75)
    assert stats['forced_fraction'] == pytest.approx(0.5)
    assert all_runner.target_stats([])['rows'] == 0


def test_tee_log_appends_lines_to_stdout_and_file(tmp_path, capsys):
    log = all_runner.tee_log(tmp_path / 'run.log')
    log('baseline', 0.3)
    log('iteration 0: ok')
    captured = capsys.readouterr()
    assert 'baseline 0.3' in captured.out
    text = (tmp_path / 'run.log').read_text(encoding='utf-8')
    assert text.splitlines() == ['baseline 0.3', 'iteration 0: ok']
