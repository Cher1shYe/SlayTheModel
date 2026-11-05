from pathlib import Path

import pytest

from deployment.evaluate_latest_puct_100 import (
    ARMS, SEED_START, compare, compare_same_model, reference_records, same_model_reference,
)


def test_historical_replay_merges_outcomes_and_preserves_seed_set():
    source = Path('runs/armg_three_models_puct_root_100_20261030')
    retry = Path('runs/armg_final_boss_potion_zero_20261030')
    if not source.exists() or not retry.exists():
        pytest.skip('historical evaluation artifacts unavailable')
    baseline, _, _ = reference_records(source, retry)
    for arm, wins in zip(ARMS, (15, 14, 16)):
        rows = [baseline[arm, seed] for seed in range(SEED_START, SEED_START + 100)]
        assert sum(bool(r['won']) for r in rows) == wins
        assert all(r['status'] == 'terminated' for r in rows)


def test_pairing_uses_matching_game_seed():
    def row(seed, floor):
        return {'seed': seed, 'floor': floor, 'status': 'terminated', 'won': False}
    baseline = {(arm, 100): row(100, 10) for arm in ARMS}
    baseline.update({(arm, 200): row(200, 40) for arm in ARMS})
    results = [row(200, 45), row(100, 13)]
    for pair in compare(results, baseline).values():
        assert pair['complete_pairs'] == 2
        assert pair['mean_floor_difference'] == 4


def test_same_model_pair_reports_paired_wins_and_floors():
    old = {1: {'seed': 1, 'floor': 30, 'status': 'terminated', 'won': False},
           2: {'seed': 2, 'floor': 48, 'status': 'terminated', 'won': True}}
    new = [{'seed': 2, 'floor': 48, 'status': 'terminated', 'won': False},
           {'seed': 1, 'floor': 48, 'status': 'terminated', 'won': True}]
    result = compare_same_model(new, old)
    assert result['complete_pairs'] == 2
    assert result['mean_floor_difference'] == 9
    assert result['candidate_only_wins'] == result['baseline_only_wins'] == 1


def test_real_same_model_baseline_matches_checkpoint_and_search_seeds():
    import json
    source = Path('runs/armg_three_models_puct_root_100_20261030')
    retry = Path('runs/armg_final_boss_potion_zero_20261030')
    prior = Path('runs/armg_puct_latest896_same100_20261030')
    if not all(path.exists() for path in (source, retry, prior / 'summary.json')):
        pytest.skip('historical evaluation artifacts unavailable')
    baseline, _, _ = reference_records(source, retry)
    config = json.loads((prior / 'config.json').read_text(encoding='utf-8'))
    ref, previous_config = same_model_reference(
        prior, config['checkpoint_sha256'], config['simulator_sha256'], config['combat_policy_sha256'], baseline)
    assert len(ref) == 100
    assert previous_config['combat_budget'] == '2000+200*(floor-1), elite +1000, boss +2000'
    with pytest.raises(ValueError, match='checkpoint_sha256'):
        same_model_reference(prior, 'wrong', config['simulator_sha256'], config['combat_policy_sha256'], baseline)


@pytest.mark.parametrize('markdown_locked', [False, True])
def test_custom_budget_reaches_worker_and_progress(tmp_path, monkeypatch, markdown_locked):
    import json
    from deployment import evaluate_latest_puct_100 as evaluator
    checkpoint = Path('runs/armg_puct_3000_500_prior005_1024_20261030/latest.pt')
    source = Path('runs/armg_three_models_puct_root_100_20261030')
    retry = Path('runs/armg_final_boss_potion_zero_20261030')
    prior = Path('runs/armg_puct_latest896_same100_20261030')
    if not all(path.exists() for path in (checkpoint, source, retry, prior / 'summary.json')):
        pytest.skip('historical evaluation artifacts unavailable')
    submitted = []

    class Future:
        def __init__(self, task): self.task = task
        def result(self):
            return {'seed': self.task[0], 'status': 'terminated', 'won': False,
                    'floor': 20, 'hp': 0}

    class Pool:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, task):
            submitted.append(task)
            return Future(task)

    monkeypatch.setattr(evaluator, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(evaluator, 'wait', lambda pending, **kwargs: (set(pending), set()))
    if markdown_locked:
        original_atomic = evaluator._atomic
        def atomic_with_locked_markdown(path, content):
            if path.name == 'progress.md':
                raise PermissionError('simulated Windows preview sharing conflict')
            return original_atomic(path, content)
        monkeypatch.setattr(evaluator, '_atomic', atomic_with_locked_markdown)
        monkeypatch.setattr(evaluator.time, 'sleep', lambda _: None)
    output = tmp_path / 'run'
    evaluator.run(str(checkpoint), str(source), str(retry), str(output), count=1,
                  workers=8, simulations=8000, floor_increment=500,
                  same_model_baseline=str(prior))
    assert submitted[0][6:10] == (8000, 500, 1000, 2000)
    config = json.loads((output / 'config.json').read_text(encoding='utf-8'))
    assert config['historical_budget_comparable'] is False
    assert config['combat_budget_start'] == 8000 and config['combat_budget_per_floor'] == 500
    summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    assert summary['paired']['same_model_previous_budget']['complete_pairs'] == 1
    if not markdown_locked:
        assert '第 1 层 8000 次、每层 +500' in (output / 'progress.md').read_text(encoding='utf-8')
    else:
        assert len((output / 'episodes.jsonl').read_text(encoding='utf-8').splitlines()) == 1


def test_resume_skips_complete_seeds_repairs_partial_tail_and_checks_config(tmp_path, monkeypatch):
    import json
    from deployment import evaluate_latest_puct_100 as evaluator
    checkpoint = Path('runs/armg_puct_3000_500_prior005_1024_20261030/latest.pt')
    source = Path('runs/armg_three_models_puct_root_100_20261030')
    retry = Path('runs/armg_final_boss_potion_zero_20261030')
    prior = Path('runs/armg_puct_latest896_same100_20261030')
    if not all(path.exists() for path in (checkpoint, source, retry, prior / 'summary.json')):
        pytest.skip('historical evaluation artifacts unavailable')
    submitted = []

    class Future:
        def __init__(self, task): self.task = task
        def result(self):
            return {'seed': self.task[0], 'status': 'terminated', 'won': False,
                    'floor': 20, 'hp': 0}

    class Pool:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, task):
            submitted.append(task)
            return Future(task)

    monkeypatch.setattr(evaluator, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(evaluator, 'wait', lambda pending, **kwargs: (set(pending), set()))
    output = tmp_path / 'run'
    kwargs = dict(count=3, workers=8, simulations=8000, floor_increment=500,
                  same_model_baseline=str(prior))
    evaluator.run(str(checkpoint), str(source), str(retry), str(output), **kwargs)
    path = output / 'episodes.jsonl'
    first = path.read_text(encoding='utf-8').splitlines()[0]
    first_seed = json.loads(first)['seed']
    path.write_text(first + '\n{"incomplete":', encoding='utf-8')
    progress_path = output / 'progress.json'
    progress = json.loads(progress_path.read_text(encoding='utf-8'))
    progress['state'] = 'failed'
    progress_path.write_text(json.dumps(progress), encoding='utf-8')
    submitted.clear()
    with pytest.raises(ValueError, match='combat_budget'):
        evaluator.run(str(checkpoint), str(source), str(retry), str(output),
                      **(kwargs | {'simulations': 7000, 'resume': True}))
    evaluator.run(str(checkpoint), str(source), str(retry), str(output),
                  **(kwargs | {'workers': 2, 'resume': True}))
    assert len(submitted) == 2
    assert first_seed not in {task[0] for task in submitted}
    rows = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
    assert len(rows) == len({x['seed'] for x in rows}) == 3
    assert list(output.glob('episodes.partial.*.bin'))
    assert json.loads((output / 'summary.json').read_text(encoding='utf-8'))['state'] == 'completed'


def test_resume_rejects_duplicate_and_wrong_search_seed(tmp_path):
    import json
    from deployment.evaluate_latest_puct_100 import _load_resume_records
    path = tmp_path / 'episodes.jsonl'
    row = {'seed': SEED_START, 'search_seed': 123, 'arm': 'candidate', 'status': 'terminated',
           'won': False, 'floor': 20, 'hp': 0}
    baseline = {('r960', SEED_START): {'search_seed': 123}}
    path.write_text((json.dumps(row) + '\n') * 2, encoding='utf-8')
    with pytest.raises(ValueError, match='duplicated'):
        _load_resume_records(path, baseline, 2)
    row['search_seed'] = 456
    path.write_text(json.dumps(row) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='mismatched'):
        _load_resume_records(path, baseline, 2)


def test_evaluation_lock_rejects_concurrent_owner(tmp_path):
    from deployment.evaluate_latest_puct_100 import _evaluation_lock
    output = tmp_path / 'run'
    with _evaluation_lock(output):
        with pytest.raises(ValueError, match='another evaluation'):
            with _evaluation_lock(output):
                pass
    with _evaluation_lock(output):
        pass


def test_resume_rejects_live_and_recent_legacy_run(tmp_path):
    import json
    import os
    from datetime import datetime, timezone
    from deployment.evaluate_latest_puct_100 import _sha, _validate_resume_state
    (tmp_path / 'candidate_weights.pt').write_bytes(b'candidate')
    (tmp_path / 'combat_policy.pt').write_bytes(b'combat')
    config = {'frozen_weights_sha256': _sha(tmp_path / 'candidate_weights.pt'),
              'combat_policy_sha256': _sha(tmp_path / 'combat_policy.pt')}
    (tmp_path / 'config.json').write_text(json.dumps(config), encoding='utf-8')
    p = tmp_path / 'progress.json'
    p.write_text(json.dumps({'state': 'running', 'evaluation_pid': os.getpid()}), encoding='utf-8')
    with pytest.raises(ValueError, match='process is alive'):
        _validate_resume_state(tmp_path, {}, {}, 1)
    p.write_text(json.dumps({'state': 'running', 'updated_utc': datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
    with pytest.raises(ValueError, match='recently active'):
        _validate_resume_state(tmp_path, {}, {}, 1)
