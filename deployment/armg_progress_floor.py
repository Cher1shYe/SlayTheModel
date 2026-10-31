"""Add completed-game mean floors to a running ArmG cycle progress file.

The legacy cycle wrapper overwrites progress.md, so an optional small watcher
republishes the supplemental section after each overwrite.  It only reads
training outputs and never signals, restarts, or changes a training process.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time

BEGIN = '<!-- FLOOR_SUMMARY_BEGIN -->'
END = '<!-- FLOOR_SUMMARY_END -->'


def _rows(path: Path):
    try:
        with path.open(encoding='utf-8') as source:
            for line in source:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    # A concurrently written JSONL line may be incomplete.
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _mean(sum_floor, count):
    return f'{sum_floor / count:.2f} 层（{count} 局）' if count else '暂无已记录的完整对局'


def floor_summary_lines(root: Path, state: dict) -> list[str]:
    """Use only completed episodes and completed RL batches, never live games."""
    try:
        current_round = max(1, int(state.get('round', 1)))
    except (ValueError, TypeError):
        current_round = 1
    lines = [BEGIN, '', '### 平均层数', '']
    folder = root / f'round{current_round:02d}'
    prior_floors = []
    for row in _rows(folder / 'prior' / 'episodes.jsonl'):
        floor = row.get('floor')
        if row.get('status') == 'terminated' and isinstance(floor, (int, float)) and math.isfinite(floor):
            prior_floors.append(float(floor))
    lines.append(f'- 本轮先验采样：{_mean(sum(prior_floors), len(prior_floors))}')

    current_sum = total_sum = 0.0
    current_count = total_count = 0
    last_validation = None
    for round_number in range(1, current_round + 1):
        for row in _rows(root / f'round{round_number:02d}' / 'reinforce' / 'metrics.jsonl'):
            train = row.get('train') or {}
            n, mean = train.get('completed'), train.get('mean_floor')
            if isinstance(n, int) and n > 0 and isinstance(mean, (int, float)) and math.isfinite(mean):
                total_sum += n * mean
                total_count += n
                if round_number == current_round:
                    current_sum += n * mean
                    current_count += n
            val = row.get('validation') or {}
            vn, vm = val.get('completed'), val.get('mean_floor')
            if isinstance(vn, int) and vn > 0 and isinstance(vm, (int, float)) and math.isfinite(vm):
                last_validation = (round_number, float(vm), vn)
    lines.append(f'- 本轮强化学习：{_mean(current_sum, current_count)}')
    lines.append(f'- 累计强化学习：{_mean(total_sum, total_count)}')
    if last_validation:
        r, mean, count = last_validation
        lines.append(f'- 最近一次验证（第 {r} 轮）：{mean:.2f} 层（{count} 局）')
    else:
        lines.append('- 最近一次验证：暂无结果')
    if state.get('stage') == 'guard':
        groups = {'previous': [], 'prior': []}
        for row in _rows(folder / 'guard' / 'episodes.jsonl'):
            floor, arm = row.get('floor'), row.get('arm')
            if (arm in groups and row.get('status') == 'terminated' and
                    isinstance(floor, (int, float)) and math.isfinite(floor)):
                groups[arm].append(float(floor))
        lines.append(f"- 当前配对验证：上轮模型 {_mean(sum(groups['previous']), len(groups['previous']))}；先验候选 {_mean(sum(groups['prior']), len(groups['prior']))}")
    lines += ['', '注：仅统计已正常结束并写入记录的局；强化学习进行中的批次暂不计入，验证与训练分别统计。', END]
    return lines


def add_floor_summary(original: str, lines: list[str]) -> str:
    start, end = original.find(BEGIN), original.find(END)
    if start >= 0 and end >= start:
        original = original[:start].rstrip() + original[end + len(END):]
    return original.rstrip() + '\n\n' + '\n'.join(lines) + '\n'


def _read_state(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def refresh(root: Path) -> dict | None:
    """Best-effort atomic replacement; sharing conflicts are harmless."""
    state = _read_state(root / 'progress.json')
    if not state:
        return None
    progress = root / 'progress.md'
    try:
        original = progress.read_text(encoding='utf-8')
        result = add_floor_summary(original, floor_summary_lines(root, state))
        if result != original:
            temporary = root / f'progress.floor.{os.getpid()}.tmp'
            try:
                temporary.write_text(result, encoding='utf-8')
                os.replace(temporary, progress)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    except OSError:
        pass
    return state


def _process_alive(pid: int):
    """Return None on access errors; never send signals to training."""
    if pid < 1:
        return None
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False if ctypes.get_last_error() == 87 else None
        try:
            code = wintypes.DWORD()
            return bool(code.value == 259) if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return None


def watch(root, interval=2):
    root = Path(root).resolve(strict=True)
    if interval <= 0:
        raise ValueError('interval must be positive')
    dead_since = None
    while True:
        state = refresh(root)
        if state and state.get('state') in ('completed', 'failed', 'stopped'):
            # Another process may have just published the final base text.
            time.sleep(min(interval, 2))
            refresh(root)
            return
        alive = _process_alive(int((state or {}).get('wrapper_pid') or 0))
        dead_since = (dead_since or time.monotonic()) if alive is False else None
        if dead_since is not None and time.monotonic() - dead_since > 15:
            return
        time.sleep(interval)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root-dir', required=True)
    p.add_argument('--interval', type=float, default=2)
    a = p.parse_args(argv)
    watch(a.root_dir, a.interval)


if __name__ == '__main__':
    main()
