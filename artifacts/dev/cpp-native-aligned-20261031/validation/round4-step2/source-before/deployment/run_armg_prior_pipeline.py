"""Run ArmG prior collection/pretraining, then REINFORCE, sequentially.

Stages have separate output directories and subprocess logs. A failed or
incomplete pretraining stage cannot start reinforcement learning. Run this
wrapper as one hidden background process on Windows.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(path, data):
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(data, encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def run(root_dir, data_dir, *, workers=8, simulations=2000, boss_simulations=10000, prior_games=1000,
        prior_epochs=3, prior_lr=1e-4, rl_games=4000, rl_batch=32,
        rl_lr=3e-4, eval_every=400, eval_runs=50, max_steps=5000, combat_mode='oracle'):
    if min(workers, simulations, boss_simulations, prior_games, prior_epochs, rl_games, rl_batch,
           eval_every, eval_runs, max_steps) < 1 or min(prior_lr, rl_lr) <= 0:
        raise ValueError('invalid pipeline settings')
    if combat_mode not in ('oracle', 'hidden'):
        raise ValueError('combat_mode must be oracle or hidden')
    root = Path(root_dir).resolve()
    data = Path(data_dir).resolve(strict=True)
    ext = os.environ.get('STS2_PRIOR_PYD')
    if not ext or not Path(ext).resolve(strict=True).is_file():
        raise RuntimeError('STS2_PRIOR_PYD must specify the isolated simulator extension')
    if not (data / 'manifest.json').is_file():
        raise FileNotFoundError('prior data manifest is missing')
    root.mkdir(parents=True, exist_ok=True)
    pre, rl = root / 'pretrain', root / 'reinforce'
    if pre.exists() or rl.exists() or (root / 'pipeline_progress.json').exists():
        raise FileExistsError('pipeline output already exists; choose a fresh directory')
    state = {'state': 'running', 'stage': 'starting', 'wrapper_pid': os.getpid(),
             'started_utc': datetime.now(timezone.utc).isoformat(), 'data_dir': str(data),
             'pretrain_dir': str(pre), 'reinforce_dir': str(rl), 'workers': workers,
             'simulations_per_decision': simulations, 'prior_games': prior_games,
             'boss_simulations_per_decision': boss_simulations,
             'combat_mode': combat_mode, 'path_cache': 'none',
             'rl_games': rl_games, 'child_pid': None, 'child_progress': None}

    def save():
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        _write(root / 'pipeline_progress.json', json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False))
        child = state.get('child_progress') or {}
        current = child.get('games_completed', child.get('games', 0))
        active_stage = 'pretrain' if state['stage'] in ('starting', 'pretrain') else 'reinforce'
        target = state['prior_games'] if active_stage == 'pretrain' else state['rl_games']
        lines = ['# 局外策略训练进度', '', f"- 状态：{state['state']}",
                 f"- 当前阶段：{state['stage']}", f"- 当前阶段完成局数：{current} / {target}",
                 f"- worker 数：{workers}；普通战斗 MCTS：{simulations} 次；Boss：{boss_simulations} 次",
                 f"- 战斗信息模式：{combat_mode}；每次决策重新搜索",
                 f"- 最近更新：{state['updated_utc']}", f"- 运行进程 PID：{state['child_pid']}",
                 f"- 阶段详情：`{(pre if active_stage == 'pretrain' else rl) / 'progress.json'}`",
                 f"- 详细日志：`{root / (active_stage + '.log')}`"]
        if state.get('error'):
            lines.append(f"- 错误：{state['error']}")
        lines += ['', '说明：局内进度见阶段详情，阶段完成后才会自动开始下一阶段。', '']
        _write(root / 'progress.md', '\n'.join(lines))

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    child = None

    def execute(stage, cmd, directory):
        nonlocal child
        state['stage'], state['child_progress'] = stage, None
        save()
        with (root / (stage + '.log')).open('x', encoding='utf-8', buffering=1) as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                     env=env, creationflags=no_window)
            state['child_pid'] = child.pid
            while child.poll() is None:
                state['child_progress'] = _read(directory / 'progress.json')
                save()
                time.sleep(10)
            code = child.wait()
        result = _read(directory / 'progress.json')
        state['child_progress'], state['child_pid'] = result, None
        save()
        if code or not result or result.get('state') != 'completed':
            raise RuntimeError(f'{stage} did not complete successfully (exit={code}); see {root / (stage + ".log")}')
        return result

    try:
        save()
        prior_cmd = [sys.executable, '-u', '-m', 'agent.armg_prior_train', '--data-dir', str(data),
                     '--out-dir', str(pre), '--games', str(prior_games), '--workers', str(workers),
                     '--simulations', str(simulations), '--boss-simulations', str(boss_simulations), '--epochs', str(prior_epochs),
                     '--lr', str(prior_lr), '--max-steps', str(max_steps), '--combat-mode', combat_mode]
        result = execute('pretrain', prior_cmd, pre)
        if (result.get('stage') != 'completed' or result.get('games_completed') != prior_games or
                result.get('terminated') != prior_games or result.get('errors') or result.get('truncated')):
            raise RuntimeError('pretraining has incomplete or failed episodes; reinforcement not started')
        prior = pre / 'prior.pt'
        if not prior.is_file() or prior.stat().st_size == 0:
            raise RuntimeError('pretraining checkpoint missing; reinforcement not started')
        # Check model schema and random-initialization provenance before the
        # expensive second stage. No original ArmG weights are loaded here.
        import torch
        checkpoint = torch.load(prior, map_location='cpu', weights_only=False)
        if checkpoint.get('progress', {}).get('initialization') != 'random':
            raise RuntimeError('pretraining checkpoint lacks random-initialization provenance')
        prior_settings = checkpoint.get('settings', {})
        if (prior_settings.get('information') != combat_mode or
                prior_settings.get('simulations_per_decision') != simulations or
                prior_settings.get('boss_simulations_per_decision') != boss_simulations or
                prior_settings.get('path_cache') != 'none'):
            raise RuntimeError('pretraining checkpoint battle mode or budget does not match the pipeline')
        del checkpoint
        rl_cmd = [sys.executable, '-u', '-m', 'deployment.train_armg_hidden_mcts',
                  '--init-checkpoint', str(prior), '--out-dir', str(rl), '--games', str(rl_games),
                  '--batch-size', str(rl_batch), '--workers', str(workers), '--simulations', str(simulations),
                  '--boss-simulations', str(boss_simulations),
                  '--eval-every', str(eval_every), '--eval-runs', str(eval_runs),
                  '--lr', str(rl_lr), '--max-steps', str(max_steps), '--combat-mode', combat_mode]
        result = execute('reinforce', rl_cmd, rl)
        if result.get('games') != rl_games or not (rl / 'latest.pt').is_file():
            raise RuntimeError('reinforcement training did not reach target or save checkpoint')
        state['state'], state['stage'] = 'completed', 'completed'
        save()
        return 0
    except BaseException as exc:
        if child is not None and child.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=no_window, check=False)
            else:
                child.terminate()
            child.wait()
        state['state'], state['error'] = 'failed', f'{type(exc).__name__}: {exc}'
        state['child_pid'] = None
        save()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root-dir', required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--boss-simulations', type=int, default=10000)
    p.add_argument('--prior-games', type=int, default=1000)
    p.add_argument('--prior-epochs', type=int, default=3)
    p.add_argument('--prior-lr', type=float, default=1e-4)
    p.add_argument('--rl-games', type=int, default=4000)
    p.add_argument('--rl-batch', type=int, default=32)
    p.add_argument('--rl-lr', type=float, default=3e-4)
    p.add_argument('--eval-every', type=int, default=400)
    p.add_argument('--eval-runs', type=int, default=50)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--combat-mode', choices=('oracle', 'hidden'), default='oracle')
    return run(**vars(p.parse_args(argv)))


if __name__ == '__main__':
    raise SystemExit(main())
