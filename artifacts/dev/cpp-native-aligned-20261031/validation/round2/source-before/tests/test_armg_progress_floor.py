import json
from pathlib import Path

from deployment.armg_progress_floor import (BEGIN, END, add_floor_summary,
                                            floor_summary_lines, refresh)


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(v) + '\n' for v in values), encoding='utf-8')


def test_means_use_completed_episodes_and_weighted_rl_batches(tmp_path):
    _write_jsonl(tmp_path / 'round02/prior/episodes.jsonl', [
        {'status': 'terminated', 'floor': 10},
        {'status': 'terminated', 'floor': 20},
        {'status': 'truncated', 'floor': 50},
    ])
    _write_jsonl(tmp_path / 'round01/reinforce/metrics.jsonl', [
        {'train': {'completed': 3, 'mean_floor': 10},
         'validation': {'completed': 5, 'mean_floor': 40}},
    ])
    metrics = tmp_path / 'round02/reinforce/metrics.jsonl'
    _write_jsonl(metrics, [
        {'train': {'completed': 2, 'mean_floor': 20}},
        {'train': {'completed': 1, 'mean_floor': 50}},
        {'train': {'completed': 0, 'mean_floor': None}},
    ])
    with metrics.open('a', encoding='utf-8') as stream:
        stream.write('{"partial":')
    text = '\n'.join(floor_summary_lines(tmp_path, {'round': 2, 'stage': 'reinforce'}))
    assert '本轮先验采样：15.00 层（2 局）' in text
    assert '本轮强化学习：30.00 层（3 局）' in text
    assert '累计强化学习：20.00 层（6 局）' in text
    assert '最近一次验证（第 1 轮）：40.00 层（5 局）' in text


def test_guard_is_separate_and_keeps_terminated_only(tmp_path):
    _write_jsonl(tmp_path / 'round02/guard/episodes.jsonl', [
        {'arm': 'previous', 'status': 'terminated', 'floor': 12},
        {'arm': 'prior', 'status': 'terminated', 'floor': 17},
        {'arm': 'prior', 'status': 'error', 'floor': 0},
    ])
    text = '\n'.join(floor_summary_lines(tmp_path, {'round': 2, 'stage': 'guard'}))
    assert '上轮模型 12.00 层（1 局）' in text
    assert '先验候选 17.00 层（1 局）' in text
    assert '累计强化学习：暂无已记录的完整对局' in text


def test_refresh_reinstates_block_after_wrapper_overwrite(tmp_path):
    (tmp_path / 'progress.json').write_text(json.dumps({'round': 1}), encoding='utf-8')
    progress = tmp_path / 'progress.md'
    progress.write_text('# Progress\n', encoding='utf-8')
    assert refresh(tmp_path) == {'round': 1}
    first = progress.read_text(encoding='utf-8')
    assert first.count(BEGIN) == first.count(END) == 1
    refresh(tmp_path)
    assert progress.read_text(encoding='utf-8') == first
    progress.write_text('# Updated by wrapper\n', encoding='utf-8')
    refresh(tmp_path)
    updated = progress.read_text(encoding='utf-8')
    assert '# Updated by wrapper' in updated and updated.count(BEGIN) == 1


def test_replace_summary_block_preserves_other_text():
    text = '# Progress\n\n' + BEGIN + '\nold\n' + END + '\n\n# End\n'
    output = add_floor_summary(text, [BEGIN, 'new', END])
    assert '# End' in output and 'old' not in output and output.count(BEGIN) == 1
