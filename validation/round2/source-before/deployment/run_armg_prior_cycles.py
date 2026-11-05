"""Run sequential fresh ArmG prior/RL cycles with durable progress reporting.

The first cycle initializes ArmG randomly.  Subsequent cycles collect using
the previous RL model and warm-start the next prior stage from its weights.
Each stage has a separate directory; a failure never starts the next stage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write(path, content):
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(content, encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(root_dir, data_dir, *, rounds=5, workers=8, simulations=2000,
        boss_simulations=10000, prior_games=200, initial_epochs=3,
        later_epochs=1, prior_lr=1e-4, prior_kl_weight=.5, rl_games=640,
        rl_batch=32, rl_lr=3e-4, eval_every=640, eval_runs=50, guard_games=50,
        max_steps=5000, seed=20261030, combat_mode='oracle'):
    if min(rounds, workers, simulations, boss_simulations, prior_games,
           initial_epochs, later_epochs, rl_games, rl_batch, eval_every,
           eval_runs, max_steps) < 1 or guard_games < 2 or min(prior_lr, rl_lr) <= 0 or prior_kl_weight < 0:
        raise ValueError('invalid cycle settings')
    if combat_mode not in ('oracle', 'hidden'):
        raise ValueError('invalid combat mode')
    data = Path(data_dir).resolve(strict=True)
    manifest = data / 'manifest.json'
    if not manifest.is_file():
        raise FileNotFoundError('prior data manifest is missing')
    ext = os.environ.get('STS2_PRIOR_PYD')
    if not ext or not Path(ext).resolve(strict=True).is_file():
        raise RuntimeError('STS2_PRIOR_PYD must specify the isolated simulator extension')
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    config = {'rounds': rounds, 'workers': workers, 'simulations_per_decision': simulations,
              'boss_simulations_per_decision': boss_simulations, 'combat_mode': combat_mode,
              'path_cache': 'none', 'prior_games_per_round': prior_games,
              'initial_epochs': initial_epochs, 'later_epochs': later_epochs,
              'prior_lr': prior_lr, 'prior_kl_weight': prior_kl_weight,
              'rl_games_per_round': rl_games, 'rl_batch': rl_batch, 'rl_lr': rl_lr,
              'eval_every': eval_every, 'eval_runs': eval_runs, 'guard_games': guard_games,
              'max_steps': max_steps,
              'seed': seed, 'data_dir': str(data), 'data_manifest_sha256': _digest(manifest),
              'simulator_path': str(Path(ext).resolve()), 'simulator_sha256': _digest(ext),
              'starting_model': 'random', 'created_utc': _utc()}
    (root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    state = {'state': 'running', 'stage': 'starting', 'round': 1, 'total_rounds': rounds,
             'completed_rounds': 0, 'completed_rl_games': 0, 'wrapper_pid': os.getpid(),
             'child_pid': None, 'child_progress': None, 'started_utc': _utc(),
             'prior_kl_weight': prior_kl_weight, 'guards': [],
             'config_path': str(root / 'config.json')}

    def save():
        state['updated_utc'] = _utc()
        _write(root / 'progress.json', json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False))
        child = state.get('child_progress') or {}
        target = prior_games if state['stage'] == 'prior' else 2 * guard_games if state['stage'] == 'guard' else rl_games
        current = child.get('games_completed', child.get('completed_jobs', child.get('games', 0)))
        lines = ['# 局外策略循环训练进度', '', f"- 状态：{state['state']}",
                 f"- 轮次：{state['round']} / {rounds}；已完成 {state['completed_rounds']} 轮",
                 f"- 当前阶段：{state['stage']}；阶段局数：{current} / {target}",
                 f"- 已完成强化学习局数：{state['completed_rl_games']}",
                 f"- 下次先验 KL 权重：{state['prior_kl_weight']}",
                 f'- worker：{workers}；普通 MCTS：{simulations}；Boss：{boss_simulations}；模式：{combat_mode}',
                 f"- 子进程 PID：{state['child_pid']}", f"- 最近更新（UTC）：{state['updated_utc']}"]
        if state.get('stage_dir'):
            lines.append(f"- 阶段详情：`{state['stage_dir']}/progress.json`")
        if state.get('stage_log'):
            lines.append(f"- 阶段日志：`{state['stage_log']}`")
        if state.get('error'):
            lines.append(f"- 错误：{state['error']}")
        lines += ['', '说明：前一阶段成功且检查点有效后才进入下一阶段。', '']
        # Floor reporting is observational and must not affect training.
        try:
            from deployment.armg_progress_floor import floor_summary_lines
            lines += ['', *floor_summary_lines(root, state), '']
        except (OSError, ValueError, TypeError, KeyError):
            pass
        _write(root / 'progress.md', '\n'.join(lines))

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    child = None

    def execute(stage, cmd, directory, logfile):
        nonlocal child
        state.update(stage=stage, child_progress=None, stage_dir=str(directory), stage_log=str(logfile))
        save()
        with logfile.open('x', encoding='utf-8', buffering=1) as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                     env=env, creationflags=no_window)
            state['child_pid'] = child.pid
            while child.poll() is None:
                state['child_progress'] = _read(directory / 'progress.json')
                save()
                time.sleep(10)
            code = child.wait()
        result = _read(directory / 'progress.json')
        state.update(child_progress=result, child_pid=None)
        save()
        if code or not result or result.get('state') != 'completed':
            raise RuntimeError(f'{stage} did not complete successfully (exit={code}); see {logfile}')
        return result

    try:
        save()
        replay_dirs = []
        previous_rl = None
        for index in range(rounds):
            if _digest(manifest) != config['data_manifest_sha256'] or _digest(ext) != config['simulator_sha256']:
                raise RuntimeError('the prior data manifest or simulator changed during the run')
            state['round'] = index + 1
            folder = root / f'round{index+1:02d}'
            folder.mkdir()
            pre, rl = folder / 'prior', folder / 'reinforce'
            cmd = [sys.executable, '-u', '-m', 'agent.armg_prior_train',
                   '--data-dir', str(data), '--out-dir', str(pre),
                   '--games', str(prior_games), '--workers', str(workers),
                   '--simulations', str(simulations), '--boss-simulations', str(boss_simulations),
                   '--epochs', str(initial_epochs if index == 0 else later_epochs),
                   '--lr', str(prior_lr), '--max-steps', str(max_steps),
                   '--seed', str(seed + index), '--seed-offset', str(index * prior_games),
                   '--combat-mode', combat_mode]
            if previous_rl is not None:
                cmd.extend(['--init-checkpoint', str(previous_rl), '--kl-weight', str(state['prior_kl_weight'])])
                if replay_dirs:
                    cmd.extend(['--replay-dirs', *(str(p) for p in replay_dirs)])
            prior_result = execute('prior', cmd, pre, folder / 'prior.log')
            if (prior_result.get('stage') != 'completed' or
                    prior_result.get('games_completed') != prior_games or
                    prior_result.get('terminated') != prior_games or
                    prior_result.get('errors') or prior_result.get('truncated')):
                raise RuntimeError('prior collection incomplete; reinforcement not started')
            prior = pre / 'prior.pt'
            if not prior.is_file() or prior.stat().st_size == 0:
                raise RuntimeError('prior checkpoint missing; reinforcement not started')
            # Check lineage before allowing the next, expensive stage to run.
            import torch
            payload = torch.load(prior, map_location='cpu', weights_only=False)
            metadata, prior_settings = payload.get('progress', {}), payload.get('settings', {})
            expected_source = _digest(previous_rl) if previous_rl is not None else None
            if (metadata.get('stage') != 'prior_complete' or
                    metadata.get('source_rl_sha256') != expected_source or
                    (previous_rl is None and metadata.get('initialization') != 'random') or
                    prior_settings.get('information') != combat_mode or
                    prior_settings.get('simulations_per_decision') != simulations or
                    prior_settings.get('boss_simulations_per_decision') != boss_simulations or
                    prior_settings.get('path_cache') != 'none' or
                    prior_settings.get('simulator_sha256') != config['simulator_sha256']):
                raise RuntimeError('prior checkpoint lineage, battle mode or budget mismatch')
            del payload
            replay_dirs.append(pre)
            if previous_rl is not None:
                # Compare candidate and previous RL policy on the same held-out
                # games.  Incomplete evaluations fail the stage, never roll back.
                guard = folder / 'guard'
                cmd = [sys.executable, '-u', '-m', 'deployment.evaluate_armg_prior_guard',
                       '--prior', str(prior), '--previous-rl', str(previous_rl),
                       '--out-dir', str(guard), '--games', str(guard_games),
                       '--workers', str(workers), '--simulations', str(simulations),
                       '--boss-simulations', str(boss_simulations),
                       '--max-steps', str(max_steps), '--combat-mode', combat_mode]
                execute('guard', cmd, guard, folder / 'guard.log')
                guard_report = _read(guard / 'summary.json')
                decision = (guard_report or {}).get('guard') or {}
                guard_config = (guard_report or {}).get('config') or {}
                difference, interval = decision.get('mean_floor_difference'), decision.get('ci_95')
                if ((guard_report or {}).get('state') != 'completed' or
                        not isinstance(decision.get('rollback'), bool) or
                        decision.get('complete_pairs') != guard_games or
                        guard_config.get('prior_sha256') != _digest(prior) or
                        guard_config.get('previous_rl_sha256') != _digest(previous_rl) or
                        guard_config.get('simulator_sha256') != config['simulator_sha256'] or
                        not isinstance(difference, (int, float)) or not math.isfinite(difference) or
                        not isinstance(interval, list) or len(interval) != 2 or
                        not all(isinstance(x, (int, float)) and math.isfinite(x) for x in interval) or
                        interval[0] > interval[1] or
                        decision['rollback'] != (difference < -1.0 and interval[1] < 0.0)):
                    raise RuntimeError('paired prior guard did not produce a complete decision')
                state['guards'].append({'round': index + 1, 'path': str(guard / 'summary.json'),
                                        **decision})
                if decision['rollback']:
                    # Preserve the candidate.  The RL trainer loads only this
                    # checkpoint's state_dict and separately resumes its Adam,
                    # baseline and RNG from previous_rl.
                    candidate = prior
                    candidate_payload = torch.load(candidate, map_location='cpu', weights_only=False)
                    previous_payload = torch.load(previous_rl, map_location='cpu', weights_only=False)
                    new_weights, old_weights = candidate_payload['state_dict'], previous_payload['state_dict']
                    if set(new_weights) != set(old_weights) or any(
                            new_weights[k].shape != old_weights[k].shape for k in new_weights):
                        raise RuntimeError('cannot fall back across incompatible policy schemas')
                    candidate_payload['state_dict'] = old_weights
                    candidate_payload['progress']['guard_rollback'] = True
                    candidate_payload['progress']['guard_report'] = str(guard / 'summary.json')
                    candidate_payload['progress']['rejected_candidate_sha256'] = _digest(candidate)
                    candidate_payload['optimizer_state_dict'] = previous_payload['optimizer_state_dict']
                    fallback = pre / 'guarded_prior.pt'
                    temporary = pre / 'guarded_prior.tmp'
                    torch.save(candidate_payload, temporary)
                    os.replace(temporary, fallback)
                    prior = fallback
                    state['prior_kl_weight'] *= 2
                    save()
            cmd = [sys.executable, '-u', '-m', 'deployment.train_armg_hidden_mcts',
                   '--init-checkpoint', str(prior), '--out-dir', str(rl),
                   '--games', str(rl_games), '--batch-size', str(rl_batch), '--workers', str(workers),
                   '--simulations', str(simulations), '--boss-simulations', str(boss_simulations),
                   '--eval-every', str(eval_every), '--eval-runs', str(eval_runs),
                   '--lr', str(rl_lr), '--max-steps', str(max_steps), '--combat-mode', combat_mode,
                   '--cycle-index', str(index)]
            if previous_rl is not None:
                cmd.extend(['--previous-rl', str(previous_rl)])
            rl_result = execute('reinforce', cmd, rl, folder / 'reinforce.log')
            if rl_result.get('games') != rl_games:
                raise RuntimeError('reinforcement stage did not reach its game target')
            previous_rl = rl / 'latest.pt'
            if not previous_rl.is_file() or previous_rl.stat().st_size == 0:
                raise RuntimeError('reinforcement checkpoint missing')
            state['completed_rounds'] = index + 1
            state['completed_rl_games'] = (index + 1) * rl_games
            state['latest_checkpoint'] = str(previous_rl)
            save()
        state.update(state='completed', stage='completed', child_pid=None)
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
        state.update(state='failed', error=f'{type(exc).__name__}: {exc}', child_pid=None)
        save()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root-dir', required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--rounds', type=int, default=5)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--boss-simulations', type=int, default=10000)
    p.add_argument('--prior-games', type=int, default=200)
    p.add_argument('--initial-epochs', type=int, default=3)
    p.add_argument('--later-epochs', type=int, default=1)
    p.add_argument('--prior-lr', type=float, default=1e-4)
    p.add_argument('--prior-kl-weight', type=float, default=.5)
    p.add_argument('--rl-games', type=int, default=640)
    p.add_argument('--rl-batch', type=int, default=32)
    p.add_argument('--rl-lr', type=float, default=3e-4)
    p.add_argument('--eval-every', type=int, default=640)
    p.add_argument('--eval-runs', type=int, default=50)
    p.add_argument('--guard-games', type=int, default=50)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--combat-mode', choices=('oracle', 'hidden'), default='oracle')
    return run(**vars(p.parse_args(argv)))


if __name__ == '__main__':
    raise SystemExit(main())
