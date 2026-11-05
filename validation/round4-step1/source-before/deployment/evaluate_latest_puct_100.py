"""Evaluate a frozen ArmG checkpoint on the earlier 100 paired seeds.

Run in a process with STS2_PRIOR_PYD set to the potion-aware extension.
All historical results remain read-only; final-boss retries replace only
their corresponding outcomes when constructing the paired baselines.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import functools
import hashlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import torch
from deployment import train_armg_puct_prior_rl as trainer
from deployment.evaluate_armg import _summary, load_armg_checkpoint
from deployment.evaluate_armg_checkpoints import paired_summary
from deployment.armg_progress_floor import _process_alive
from agent.armg import ArmGScorer

ARMS = ('start', 'r640', 'r960')
LABELS = {'start': '原训练起点', 'r640': '之前训练 640 局', 'r960': '之前训练 960 局'}
SEED_START = 41020000


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def reference_records(source, retry_dir):
    source, retry_dir = Path(source), Path(retry_dir)
    config = json.loads((source / 'config.json').read_text(encoding='utf-8'))
    retry_config = json.loads((retry_dir / 'config.json').read_text(encoding='utf-8'))
    if _sha(source / 'config.json') != retry_config['original_config_sha256'] or _sha(source / 'episodes.jsonl') != retry_config['original_records_sha256']:
        raise ValueError('historical source does not match the recorded boss replay')
    records = _read_jsonl(source / 'episodes.jsonl')
    retries = _read_jsonl(retry_dir / 'retry.jsonl')
    index = {(r['arm'], int(r['seed'])): dict(r) for r in records}
    if len(records) != 300 or len(index) != 300 or any(r['status'] != 'terminated' for r in records):
        raise ValueError('historical evaluation is incomplete or has duplicate records')
    seen = set()
    for row in retries:
        key = (row['arm'], int(row['seed']))
        if key in seen or key not in index or not row.get('verified_old_weight'):
            raise ValueError('unverified, duplicate or unknown boss replay')
        old = index[key]
        if old['floor'] != 48 or bool(row['original_won']) != bool(old['won']):
            raise ValueError('boss replay does not match original outcome')
        seen.add(key)
        old.update(won=bool(row['won']), floor=int(row['floor']), hp=int(row['hp']))
    expected = {(r['arm'], int(r['seed'])) for r in records if r['floor'] == 48}
    if seen != expected:
        raise ValueError('final-boss replay set is incomplete')
    for arm in ARMS:
        if {seed for a, seed in index if a == arm} != set(range(SEED_START, SEED_START + 100)):
            raise ValueError(f'wrong historical seed set for {arm}')
    if _sha(source / 'combat_policy.pt') != config['combat_sha256']:
        raise ValueError('historical combat policy snapshot hash mismatch')
    return index, config, retry_config


def compare(results, baseline, bootstrap=False):
    out = {}
    for name in ARMS:
        pairs = []
        for r in results:
            old = baseline[(name, int(r['seed']))]
            pairs.extend((dict(old, arm='baseline'), dict(r, arm='candidate')))
        out[name] = paired_summary(pairs, bootstrap=bootstrap)
    return out


def _atomic(path, content):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(content, encoding='utf-8')
    os.replace(tmp, path)


def _publish_progress_markdown(path, content):
    """Avoid aborting the evaluation if Windows briefly locks its preview."""
    for attempt in range(3):
        try:
            _atomic(path, content)
            return True
        except PermissionError as exc:
            if attempt == 2:
                print(f'Could not update progress markdown (will retry later): {exc}',
                      file=sys.stderr, flush=True)
                return False
            time.sleep(0.05 * (attempt + 1))


def same_model_reference(path, checkpoint_hash, simulator_hash, combat_hash, baseline):
    """Verify that a completed prior evaluation used the same policy and seeds."""
    path = Path(path).resolve(strict=True)
    config = json.loads((path / 'config.json').read_text(encoding='utf-8'))
    summary = json.loads((path / 'summary.json').read_text(encoding='utf-8'))
    for key, expected in (('checkpoint_sha256', checkpoint_hash),
                          ('simulator_sha256', simulator_hash),
                          ('combat_policy_sha256', combat_hash),
                          ('combat', 'oracle root-prior PUCT n=1, c=3, epsilon=.05, one action per search'),
                          ('potion_weight', 'final boss 0, otherwise 4'),
                          ('ascension', 0), ('armg', 'greedy')):
        if config.get(key) != expected:
            raise ValueError(f'previous evaluation {key} differs')
    if summary.get('state') != 'completed':
        raise ValueError('previous evaluation is incomplete')
    rows = _read_jsonl(path / 'episodes.jsonl')
    index = {int(r['seed']): r for r in rows}
    if len(rows) != 100 or len(index) != 100 or set(index) != set(range(SEED_START, SEED_START + 100)):
        raise ValueError('previous evaluation has a wrong seed set')
    if any(r['status'] != 'terminated' or int(r['search_seed']) != int(baseline['r960', seed]['search_seed'])
           for seed, r in index.items()):
        raise ValueError('previous evaluation has unfinished games or mismatched search seeds')
    return index, config


def compare_same_model(results, baseline, bootstrap=False):
    pairs = []
    for r in results:
        pairs.extend((dict(baseline[int(r['seed'])], arm='baseline'), dict(r, arm='candidate')))
    return paired_summary(pairs, bootstrap=bootstrap)


def _load_resume_records(path, baseline, count):
    """Read complete records and identify a recoverable interrupted last write.

    A malformed line with a newline, a duplicate, or a wrong seed is corruption,
    not an incomplete write, and is never silently skipped.
    """
    raw = Path(path).read_bytes()
    lines = raw.splitlines(keepends=True)
    records, seeds = [], set()
    partial = b''
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            if i == len(lines) - 1 and not line.endswith(b'\n'):
                partial = line
                break
            raise ValueError('corrupt complete episode record')
        if not isinstance(row, dict) or type(row.get('seed')) is not int:
            raise ValueError('invalid episode record')
        seed = row['seed']
        if (seed in seeds or not SEED_START <= seed < SEED_START + count or
                row.get('arm') != 'candidate' or row.get('status') != 'terminated' or
                type(row.get('won')) is not bool or type(row.get('floor')) is not int or
                type(row.get('hp')) is not int or
                row.get('search_seed') != baseline['r960', seed]['search_seed']):
            raise ValueError(f'invalid, duplicated or mismatched episode seed {seed}')
        seeds.add(seed)
        records.append(row)
    return records, partial, bool(raw and not raw.endswith(b'\n'))


def _validate_resume_state(out, expected, baseline, count):
    """Check provenance and refuse a concurrent or recently active old run."""
    old = json.loads((out / 'config.json').read_text(encoding='utf-8'))
    progress = json.loads((out / 'progress.json').read_text(encoding='utf-8'))
    for key, value in expected.items():
        if key in ('workers', 'checkpoint_progress', 'frozen_weights_sha256'):
            continue
        # These hashes were added after the original experiment started.
        if key.startswith('reference_') and key not in old:
            continue
        if old.get(key) != value:
            raise ValueError(f'resume configuration differs: {key}')
    if _sha(out / 'candidate_weights.pt') != old.get('frozen_weights_sha256'):
        raise ValueError('resume candidate weights differ from frozen snapshot')
    if _sha(out / 'combat_policy.pt') != old.get('combat_policy_sha256'):
        raise ValueError('resume combat weights differ from frozen snapshot')
    if progress.get('state') == 'running':
        pid = progress.get('evaluation_pid')
        if isinstance(pid, int) and _process_alive(pid) is not False:
            raise ValueError('cannot resume while the evaluation process is alive')
        if not isinstance(pid, int):
            updated = datetime.fromisoformat(progress['updated_utc'])
            if (datetime.now(timezone.utc) - updated).total_seconds() < 180:
                raise ValueError('cannot resume a recently active evaluation')
    if progress.get('state') == 'completed':
        raise ValueError('evaluation has already completed')
    records, partial, missing_newline = _load_resume_records(out / 'episodes.jsonl', baseline, count)
    return old, progress, records, partial, missing_newline


@contextmanager
def _evaluation_lock(out):
    """Hold a process-scoped OS lock; it is released even after a crash."""
    lock_path = out.parent / f'.{out.name}.evaluation.lock'
    with lock_path.open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'\0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('another evaluation owns this output directory') from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('another evaluation owns this output directory') from exc
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _exclusive_run(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        out = Path(bound.arguments['out_dir']).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with _evaluation_lock(out):
            return func(*args, **kwargs)
    return wrapped


@_exclusive_run
def run(checkpoint, source, retry_dir, out_dir, count=100, workers=8,
        simulations=2000, floor_increment=200, same_model_baseline=None, resume=False):
    if not 1 <= count <= 100 or workers < 1 or simulations < 1 or floor_increment < 0:
        raise ValueError('invalid evaluation size or worker count')
    if not trainer._supports_potion_weight():
        raise RuntimeError('select the potion-aware simulator with STS2_PRIOR_PYD')
    source, retry_dir = Path(source).resolve(strict=True), Path(retry_dir).resolve(strict=True)
    baseline, old_config, retry_config = reference_records(source, retry_dir)
    simulator = Path(trainer.extension_loader._extension).resolve(strict=True)
    if _sha(simulator) != retry_config['new_simulator_sha256']:
        raise ValueError('simulator differs from the final-boss replay baseline')
    model = ArmGScorer().eval()
    checkpoint = Path(checkpoint).resolve(strict=True)
    payload = load_armg_checkpoint(checkpoint, model)
    same_reference = None
    same_config = None
    if same_model_baseline:
        same_reference, same_config = same_model_reference(
            same_model_baseline, _sha(checkpoint), _sha(simulator), old_config['combat_sha256'], baseline)
    out = Path(out_dir).resolve()
    weights = out / 'candidate_weights.pt'
    combat = out / 'combat_policy.pt'
    settings = {'checkpoint': str(checkpoint), 'checkpoint_sha256': _sha(checkpoint),
        'checkpoint_progress': payload.get('progress'),
        'historical_eval': str(source), 'boss_replay': str(retry_dir),
        'simulator_sha256': _sha(simulator), 'combat_policy_sha256': old_config['combat_sha256'],
        'count': count, 'workers': workers, 'seed_start': SEED_START,
        'combat': 'oracle root-prior PUCT n=1, c=3, epsilon=.05, one action per search',
        'combat_budget': f'{simulations}+{floor_increment}*(floor-1), elite +1000, boss +2000',
        'combat_budget_start': simulations, 'combat_budget_per_floor': floor_increment,
        'elite_bonus': 1000, 'boss_bonus': 2000,
        'same_model_baseline': str(Path(same_model_baseline).resolve()) if same_model_baseline else None,
        'same_model_baseline_budget': same_config.get('combat_budget') if same_config else None,
        'historical_budget_comparable': simulations == 2000 and floor_increment == 200,
        'potion_weight': 'final boss 0, otherwise 4', 'ascension': 0, 'armg': 'greedy',
        'reference_source_config_sha256': _sha(source / 'config.json'),
        'reference_source_records_sha256': _sha(source / 'episodes.jsonl'),
        'reference_retry_records_sha256': _sha(retry_dir / 'retry.jsonl'),
        'reference_same_model_records_sha256': _sha(Path(same_model_baseline) / 'episodes.jsonl') if same_model_baseline else None}
    if resume:
        old, old_progress, results, partial, missing_newline = _validate_resume_state(out, settings, baseline, count)
        settings['frozen_weights_sha256'] = old['frozen_weights_sha256']
        if partial or missing_newline:
            # Preserve an interrupted fragment before repairing the JSONL.
            if partial:
                fragment = out / ('episodes.partial.' + hashlib.sha256(partial).hexdigest() + '.bin')
                if not fragment.exists():
                    fragment.write_bytes(partial)
            repaired = ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in results)
            _atomic(out / 'episodes.jsonl', repaired)
        active = out / 'active'
        active.mkdir(exist_ok=True)
        for path in active.glob('worker-*.json'):
            path.unlink(missing_ok=True)
        previous_elapsed = float(old_progress.get('elapsed_seconds', 0))
    else:
        out.mkdir(parents=True, exist_ok=False)
        torch.save(model.state_dict(), weights)
        shutil.copyfile(source / 'combat_policy.pt', combat)
        if _sha(combat) != old_config['combat_sha256']:
            raise ValueError('saved combat policy snapshot mismatch')
        settings['frozen_weights_sha256'] = _sha(weights)
        active = out / 'active'; active.mkdir()
        results = []
        previous_elapsed = 0.0
    _atomic(out / 'config.json', json.dumps(settings, ensure_ascii=False, indent=2))
    started = time.monotonic()

    def save(state, error=None, bootstrap=False):
        stats = _summary(results)
        paired = compare(results, baseline, bootstrap=bootstrap)
        if same_reference is not None:
            paired['same_model_previous_budget'] = compare_same_model(results, same_reference, bootstrap=bootstrap)
        data = {'state': state, 'completed': len(results), 'target': count,
                'elapsed_seconds': previous_elapsed + time.monotonic() - started,
                'candidate': stats, 'paired': paired,
                'evaluation_pid': os.getpid(),
                'updated_utc': datetime.now(timezone.utc).isoformat()}
        if error:
            data['error'] = error
        _atomic(out / 'progress.json', json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
        lines = ['# 最新 ArmG 根先验 PUCT 评测', '', f'- 状态：{state}',
                 f'- 已完成：{len(results)} / {count} 局；worker：{workers}',
                 f'- 相同 100 个种子、oracle 根先验 PUCT；第 1 层 {simulations} 次、每层 +{floor_increment}，精英 +1000、Boss +2000',
                 '- 最终 Boss 剩余药水评分 0；其余战斗 4',
                 f'- 更新时间（UTC）：{data["updated_utc"]}']
        if not settings['historical_budget_comparable']:
            lines.append('- 历史模型评测使用第 1 层 2000 次、每层 +200；以下差值同时包含模型及预算差异。')
        if stats['completed']:
            lines.append(f'- 当前模型：平均 {stats["mean_floor_completed"]:.2f} 层，通关 {stats["wins"]} / {stats["completed"]} 局')
        for arm, pair in paired.items():
            if pair['complete_pairs']:
                name = '同模型旧预算' if arm == 'same_model_previous_budget' else LABELS[arm]
                lines.append(f'- 相对{name}：平均层数 {pair["mean_floor_difference"]:+.2f}（{pair["complete_pairs"]} 对）；新增胜局 {pair["candidate_only_wins"]}，新增败局 {pair["baseline_only_wins"]}')
        if error:
            lines.append(f'- 错误：{error}')
        _publish_progress_markdown(out / 'progress.md', '\n'.join(lines) + '\n')
        return data

    save('running')
    try:
        with (out / 'episodes.jsonl').open('a' if resume else 'x', encoding='utf-8', buffering=1) as stream:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
                pending = {}
                completed_seeds = {int(row['seed']) for row in results}
                for seed in range(SEED_START, SEED_START + count):
                    if seed in completed_seeds:
                        continue
                    old = baseline[('r960', seed)]
                    task = (seed, 0, int(old['search_seed']), 0, str(weights), True, simulations, floor_increment,
                            1000, 2000, 5000, str(active), 'oracle', str(combat))
                    pending[pool.submit(trainer._play, task)] = seed
                while pending:
                    done, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                    for future in done:
                        seed = pending.pop(future)
                        row = future.result()
                        row.pop('records', None)
                        row.update(arm='candidate', search_seed=int(baseline[('r960', seed)]['search_seed']))
                        results.append(row)
                        stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
                        stream.flush()
                    save('running')
        data = save('completed', bootstrap=True)
        _atomic(out / 'summary.json', json.dumps({'config': settings, **data}, ensure_ascii=False, indent=2, allow_nan=False))
        return data
    except BaseException as exc:
        save('failed', error=f'{type(exc).__name__}: {exc}')
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--source', required=True)
    p.add_argument('--retry-dir', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--count', type=int, default=100)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--floor-increment', type=int, default=200)
    p.add_argument('--same-model-baseline', help='completed prior evaluation of the same checkpoint')
    p.add_argument('--resume', action='store_true', help='resume an interrupted evaluation in the same output directory')
    run(**vars(p.parse_args()))


if __name__ == '__main__':
    main()
