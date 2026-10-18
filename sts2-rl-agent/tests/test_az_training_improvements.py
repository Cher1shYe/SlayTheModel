"""Bounded fixtures for persistent learner, stratified replay and diagnostics."""
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import torch

from sts2_env.az import all_runner as runner
from sts2_env.az import training_diagnostics as diagnostics
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.replay_buffer import ReplayBuffer

CONFIG = 'configs/az_all_xs_v1/config.json'
PROTOCOL = 'configs/az_all_xs_v1/protocol.json'


@pytest.mark.parametrize('collection_model,leaf_mode', [('champion', 'heuristic'), ('learner', 'mixed')])
def test_rejected_learner_continues_and_second_round_resume_is_exact(tmp_path, monkeypatch, collection_model, leaf_mode):
    # Record actual collection weights, not just metadata or low-budget targets.
    import hashlib
    def fingerprint(model):
        return hashlib.sha256(b''.join(v.detach().cpu().numpy().tobytes()
            for v in model.state_dict().values())).hexdigest()
    captured = []
    collect = runner.collect
    def capture(model, *args, **kwargs):
        captured.append(fingerprint(model))
        return collect(model, *args, **kwargs)
    monkeypatch.setattr(runner, 'collect', capture)
    # Keep the champion initial, so continued learning cannot hide behind promotion.
    def evaluate(model, recipes, **kw):
        rows = [dict(scenario_id=r.scenario_id, encounter_id=r.encounter_id,
                     reward=0., termination_reason='win') for r in recipes]
        return dict(episodes=len(rows), mean_utility=0., win_rate=1., contract_rejections=0), rows
    monkeypatch.setattr(runner, 'evaluate_recipes', evaluate)
    settings = dict(iterations=2, episodes=1, updates=2, budget=1, batch_size=2,
                    max_turns=1, max_decisions=3, seed=19, collection_model=collection_model, leaf_mode=leaf_mode)
    full = runner.run(CONFIG, PROTOCOL, tmp_path / 'full', **settings)
    assert full['champion_checkpoint'] == 'initial.pt'
    assert full['learner_checkpoint'] == 'update-001-0002.pt'
    load = lambda path: runner.load_transformer_checkpoint(path, 'XS', ALL_CONTENT, 'risk-terminal-v7')
    initial, _ = load(tmp_path / 'full' / 'initial.pt')
    trained, payload = load(tmp_path / 'full' / full['learner_checkpoint'])
    assert any(not torch.equal(a, b) for a, b in zip(initial.parameters(), trained.parameters()))
    assert {int(s['step']) for s in payload['training_state']['optimizer']['state'].values()} == {4}
    # Rejected candidates remain learners; each collection uses the recorded source.
    for i in range(2):
        episode = json.loads((tmp_path / 'full' / f'collection-{i:03d}.json').read_text())[0]
        record = full['history'][i]
        expected = 'update-000-0002.pt' if i == 1 and collection_model == 'learner' else 'initial.pt'
        assert record['collection_checkpoint'] == expected
        source, _ = load(tmp_path / 'full' / expected)
        assert captured[i] == fingerprint(source)
        reference = runner.collect(source, runner.training_recipes(i, 1), iteration=i, budget=1,
            error_dir=tmp_path / 'reference', limits=EpisodeLimits(max_turns=1, max_decisions=3),
            version='reference', seed=19*100000+i*1000, leaf_mode=leaf_mode)[0]
        assert [r['policy_target'] for r in episode['rows']] == [r['policy_target'] for r in reference['rows']]
    atomic = runner.atomic_json
    def crash(path, value):
        atomic(path, value)
        pending = value.get('pending') if isinstance(value, dict) else None
        if Path(path).name == 'state.json' and pending and pending.get('update_checkpoint') == 'update-001-0001.pt':
            raise RuntimeError('second round crash')
    monkeypatch.setattr(runner, 'atomic_json', crash)
    with pytest.raises(RuntimeError, match='second round'):
        runner.run(CONFIG, PROTOCOL, tmp_path / 'resume', **settings)
    monkeypatch.setattr(runner, 'atomic_json', atomic)
    monkeypatch.setattr(runner, 'collect', lambda *a, **k: pytest.fail('recollected pending data'))
    resumed = runner.run(CONFIG, PROTOCOL, tmp_path / 'resume', resume=True, **settings)
    restored, restored_payload = load(tmp_path / 'resume' / resumed['learner_checkpoint'])
    assert all(torch.equal(a, b) for a, b in zip(trained.parameters(), restored.parameters()))
    assert full['history'][1]['updates'] == resumed['history'][1]['updates']
    assert {int(s['step']) for s in restored_payload['training_state']['optimizer']['state'].values()} == {4}


def test_all_replay_balances_encounters_not_episode_counts():
    replay = object.__new__(ReplayBuffer)
    replay.content_version = ALL_CONTENT
    def episode(encounter):
        return dict(rows=[dict(family_id='all', encounter_id=encounter,
                              observation=encounter, policy_target={}, z=0.)])
    replay.episodes = [episode('common') for _ in range(99)] + [episode('rare')]
    samples, counts = replay.sample(4000, np.random.default_rng(4))
    assert set(counts) == {'all/common', 'all/rare'}
    assert 1800 < counts['all/rare'] < 2200
    assert sum(s['observation'] == 'rare' for s in samples) == counts['all/rare']
    assert replay.sample(8, np.random.default_rng(7)) == replay.sample(8, np.random.default_rng(7))


def test_value_metrics_baselines_and_degenerate_cases():
    m = diagnostics.value_metrics([-1, 0, 1], [-1, 0, 1])
    assert m['mse'] == 0 and m['correlation'] == pytest.approx(1.)
    assert m['fitted_constant_baseline_mse'] == pytest.approx(2/3)
    assert diagnostics.value_metrics([0, 0], [-1, 1])['correlation'] is None
    assert diagnostics.value_metrics([0, 1], [1, 1])['explained_variance_score'] is None
    for p, z in [([], []), ([np.nan], [0]), ([0], [0, 1])]:
        with pytest.raises(ValueError):
            diagnostics.value_metrics(p, z)


def test_real_diagnostics_are_repeatable_no_update_and_train_only(tmp_path):
    model = runner.fresh_model(runner.load_frozen_config(CONFIG), 0)
    before = deepcopy(model.state_dict())
    recipes = runner.training_recipes(0, 1)
    episodes = runner.collect(model, recipes, iteration=0, budget=1, error_dir=tmp_path,
        limits=EpisodeLimits(max_turns=1, max_decisions=3), version='diagnostic-fixture', seed=7)
    a = diagnostics.value_diagnostic(model, episodes, max_rows=2)
    assert a == diagnostics.value_diagnostic(model, episodes, max_rows=2)
    assert a['aggregate']['count'] == min(2, len(episodes[0]['rows']))
    result = diagnostics.search_diagnostic(model, recipes, (0, 1, 2), limits=EpisodeLimits(max_turns=1, max_decisions=3), error_dir=tmp_path)
    assert set(result['results']) == {'0', '1', '2'}
    assert result['results']['2']['paired_vs_network']['episodes'] == 1
    assert result['results']['0']['rows'][0]['scenario_id'] == recipes[0].scenario_id
    assert all(torch.equal(v, before[k]) for k, v in model.state_dict().items())
    with pytest.raises(ValueError, match='training'):
        diagnostics.search_diagnostic(model, [replace(recipes[0], split='test')])
    with pytest.raises(ValueError, match='training'):
        diagnostics.value_diagnostic(model, [dict(episodes[0], split='validation')])
    with pytest.raises(ValueError, match='budgets'):
        diagnostics.search_diagnostic(model, recipes, (8, 32))


def test_diagnostics_cli_limits_provenance_and_no_overwrite(tmp_path, monkeypatch):
    import sys
    model = runner.fresh_model(runner.load_frozen_config(CONFIG), 0)
    checkpoint = tmp_path / 'model.pt'
    runner.save_transformer_checkpoint(checkpoint, model)
    output = tmp_path / 'diagnostics.json'
    def search(model, recipes, budgets, seed, limits, error_dir, leaf_mode, value_mix):
        assert leaf_mode == 'learned' and value_mix == .5
        assert limits.max_turns == 7 and limits.max_decisions == 23
        assert budgets == [0, 8, 32]
        assert all(r.split == 'train' for r in recipes)
        return {'fixture': True}
    monkeypatch.setattr(diagnostics, 'search_diagnostic', search)
    monkeypatch.setattr(sys, 'argv', ['diagnostics', '--checkpoint', str(checkpoint), '--out', str(output),
        'search', '--leaf-mode', 'learned', '--episodes', '1', '--max-turns', '7', '--max-decisions', '23'])
    diagnostics.main()
    report = json.loads(output.read_text())
    assert report['checkpoint_source_matches'] is True
    assert len(report['checkpoint_sha256']) == 64
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        diagnostics.main()
    assert output.read_bytes() == before


def test_search_diagnostic_does_not_hide_contract_errors(monkeypatch):
    import sts2_env.az.adapter as adapter
    def reject(*a, **k):
        raise ValueError('contract fixture')
    monkeypatch.setattr(adapter, 'ObservableCombatAdapter', reject)
    with pytest.raises(ValueError, match='contract fixture'):
        diagnostics.search_diagnostic(None, runner.training_recipes(0, 1))
