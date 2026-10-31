"""Run ArmG RL with a weak site prior, then compare to its frozen starting model.

Stages run sequentially in a fresh directory. A failed or incomplete training
run must not launch evaluation, and a failed evaluation cannot be reported as a
completed comparison. The old checkpoint and the prior snapshot stay read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _read(path):
    try:
        obj = json.loads(Path(path).read_text(encoding='utf-8'))
        return obj if isinstance(obj, dict) else None
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


def _train_average(path):
    count, floor_sum = 0, 0.0
    try:
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    train = json.loads(line).get('train') or {}
                    n, mean = train.get('completed'), train.get('mean_floor')
                    if isinstance(n, int) and n > 0 and isinstance(mean, (int, float)):
                        count += n
                        floor_sum += n * float(mean)
                except (ValueError, TypeError, AttributeError):
                    continue
    except OSError:
        pass
    return (floor_sum / count, count) if count else (None, 0)


def run(*, checkpoint, data_dir, root_dir, games=640, batch_size=32, workers=8,
        simulations=2000, boss_simulations=10000, eval_runs=50, evaluation_games=100,
        lr=3e-4, prior_weight=0.05, max_steps=5000, seed=20261030,
        evaluation_seed_offset=30000):
    if min(games, batch_size, workers, simulations, boss_simulations, eval_runs,
           evaluation_games, max_steps) < 1 or lr <= 0 or prior_weight < 0 or evaluation_seed_offset < 0:
        raise ValueError('invalid pipeline settings')
    baseline = Path(checkpoint).resolve(strict=True)
    data = Path(data_dir).resolve(strict=True)
    manifest = (data / 'manifest.json').resolve(strict=True)
    extension = os.environ.get('STS2_PRIOR_PYD')
    if not extension or not Path(extension).resolve(strict=True).is_file():
        raise ValueError('STS2_PRIOR_PYD must name the isolated simulator extension')
    extension = Path(extension).resolve()
    root = Path(root_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    original_sha, extension_sha, data_sha = _sha(baseline), _sha(extension), _sha(manifest)
    train, evaluation = root / 'train', root / 'evaluation'
    config = {'baseline': str(baseline), 'baseline_sha256': original_sha,
              'data_dir': str(data), 'data_manifest_sha256': data_sha,
              'simulator': str(extension), 'simulator_sha256': extension_sha,
              'training_games': games, 'batch_size': batch_size, 'workers': workers,
              'simulations_per_decision': simulations,
              'boss_simulations_per_decision': boss_simulations,
              'combat_mode': 'oracle', 'path_cache': 'none',
              'prior_weight': prior_weight, 'skip_elo_by_act': [1400, 1500, 1600],
              'prior_scope': 'ordinary skip and website-covered Ironclad reward cards; colorless/other actions remain in RL',
              'lr': lr, 'validation_games': eval_runs,
              'evaluation_games_per_arm': evaluation_games,
              'evaluation_seed_offset': evaluation_seed_offset,
              'max_steps': max_steps, 'seed': seed,
              'created_utc': datetime.now(timezone.utc).isoformat()}
    (root / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    state = {'state': 'running', 'stage': 'starting', 'wrapper_pid': os.getpid(),
             'child_pid': None, 'child_progress': None, 'baseline': str(baseline),
             'baseline_sha256': original_sha, 'config_path': str(root / 'config.json'),
             'started_utc': datetime.now(timezone.utc).isoformat()}

    def save():
        state['updated_utc'] = datetime.now(timezone.utc).isoformat()
        _write(root / 'progress.json', json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False))
        child = state.get('child_progress') or {}
        lines = ['# ArmG 强化学习与网站先验进度', '', f"- 状态：{state['state']}",
                 f"- 阶段：{state['stage']}", f'- 原模型备份：`{baseline}`',
                 f'- worker：{workers}；普通 MCTS：{simulations}；Boss：{boss_simulations}',
                 f'- 先验损失权重：{prior_weight}；跳过评分：1400 / 1500 / 1600',
                 f"- 更新时间（UTC）：{state['updated_utc']}"]
        if state['stage'] == 'training':
            lines.append(f"- 强化学习已完成：{child.get('games', 0)} / {games} 局")
            mean, count = _train_average(train / 'metrics.jsonl')
            if count:
                lines.append(f'- 已记录训练平均层数：{mean:.2f} 层（{count} 局）')
            prior = (child.get('last_batch') or {}).get('site_prior') or {}
            if prior.get('kl') is not None:
                lines.append(f"- 最近批次先验 KL：{prior['kl']:.4f}；加权损失：{prior_weight * prior['kl']:.4f}")
            if prior:
                lines.append(f"- 最近批次先验覆盖：{prior.get('eligible_decisions', 0)} 个选牌决策；"
                             f"{prior.get('covered_cards', 0)} 个战士卡牌候选")
                lines.append('- 最近批次各幕普通跳过次数：' + ' / '.join(
                    str(prior.get(f'act{act}_chosen_skip', 0)) for act in (1, 2, 3)))
            val = child.get('last_validation') or {}
            if val.get('mean_floor') is not None:
                lines.append(f"- 最近验证平均层数：{val['mean_floor']:.2f} 层（{val.get('completed', 0)} 局）")
            lines.append('- 正在进行的批次尚未计入平均层数。')
        if state['stage'] == 'evaluation':
            lines.append(f"- 评测已完成：{child.get('completed_jobs', 0)} / {evaluation_games*2} 局")
            for arm, title in (('baseline', '原模型'), ('candidate', '新模型')):
                summary = (child.get('arms') or {}).get(arm) or {}
                if summary.get('mean_floor_completed') is not None:
                    lines.append(f"- {title}中途平均：{summary['mean_floor_completed']:.2f} 层（{summary['completed']} 局）")
            lines.append('- 中途平均可能受完成顺序影响，以完整配对结果为准。')
        if state['state'] == 'completed':
            for arm, title in (('baseline', '原模型'), ('candidate', '新模型')):
                summary = (state.get('final_arms') or {}).get(arm) or {}
                if summary.get('mean_floor_completed') is not None:
                    lines.append(f"- {title}平均：{summary['mean_floor_completed']:.2f} 层（{summary['completed']} 局；通关 {summary['wins']} 局）")
            pair = state.get('final_paired') or {}
            if pair.get('mean_floor_difference') is not None:
                lines.append(f"- 配对平均差：{pair['mean_floor_difference']:+.2f} 层（{pair['complete_pairs']} 对）")
        if state.get('stage_log'):
            lines.append(f"- 阶段日志：`{state['stage_log']}`")
        if state.get('candidate'):
            lines.append(f"- 训练后模型：`{state['candidate']}`")
        if state.get('evaluation_summary'):
            lines.append(f"- 完整评测：`{state['evaluation_summary']}`")
        if state.get('error'):
            lines.append(f"- 错误：{state['error']}")
        lines.extend(['', '训练与评测均使用 oracle 纯 MCTS，逐步重搜，原模型保持不变。', ''])
        _write(root / 'progress.md', '\n'.join(lines))

    env = os.environ.copy()
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    child = None

    def execute(stage, cmd, directory):
        nonlocal child
        log = root / (stage + '.log')
        state.update(stage=stage, child_progress=None, stage_dir=str(directory), stage_log=str(log))
        save()
        with log.open('x', encoding='utf-8', buffering=1) as output:
            child = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT, env=env, creationflags=no_window)
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
            raise RuntimeError(f'{stage} did not complete successfully (exit={code}); see {log}')
        return result

    try:
        save()
        train_cmd = [sys.executable, '-u', '-m', 'deployment.train_armg_site_prior_rl',
                     '--init-checkpoint', str(baseline), '--data-dir', str(data),
                     '--out-dir', str(train), '--games', str(games), '--batch-size', str(batch_size),
                     '--workers', str(workers), '--simulations', str(simulations),
                     '--boss-simulations', str(boss_simulations), '--eval-every', str(games),
                     '--eval-runs', str(eval_runs), '--lr', str(lr), '--prior-weight', str(prior_weight),
                     '--max-steps', str(max_steps), '--seed', str(seed), '--combat-mode', 'oracle']
        result = execute('training', train_cmd, train)
        candidate = train / 'latest.pt'
        training_config = _read(train / 'config.json') or {}
        if (_sha(baseline) != original_sha or _sha(extension) != extension_sha or _sha(manifest) != data_sha or
                result.get('games') != games or not candidate.is_file() or candidate.stat().st_size == 0 or
                training_config.get('init_sha256') != original_sha or
                training_config.get('website_manifest_sha256') != data_sha or
                training_config.get('simulator_sha256') != extension_sha or
                training_config.get('prior_weight') != prior_weight or
                training_config.get('skip_elos_by_act') != [1400, 1500, 1600] or
                training_config.get('prior_scope') != config['prior_scope'] or
                training_config.get('information') != 'oracle' or
                training_config.get('simulations') != simulations or
                training_config.get('boss_simulations_per_decision') != boss_simulations or
                training_config.get('path_cache') != 'none'):
            raise RuntimeError('training output/provenance does not match the backup; evaluation not started')
        state['candidate'], state['candidate_sha256'] = str(candidate), _sha(candidate)
        eval_cmd = [sys.executable, '-u', '-m', 'deployment.evaluate_armg_checkpoints',
                    '--baseline', str(baseline), '--candidate', str(candidate), '--out-dir', str(evaluation),
                    '--count', str(evaluation_games), '--workers', str(workers), '--simulations', str(simulations),
                    '--boss-simulations', str(boss_simulations), '--max-steps', str(max_steps),
                    '--start', str(evaluation_seed_offset), '--search-seed', str(seed)]
        execute('evaluation', eval_cmd, evaluation)
        report = _read(evaluation / 'summary.json') or {}
        result_config = report.get('config') or {}
        if (report.get('state') != 'completed' or (report.get('paired') or {}).get('complete_pairs') != evaluation_games or
                (result_config.get('sha256') or {}).get('baseline') != original_sha or
                (result_config.get('sha256') or {}).get('candidate') != state['candidate_sha256'] or
                result_config.get('simulator_sha256') != extension_sha or _sha(baseline) != original_sha):
            raise RuntimeError('evaluation output, simulator or checkpoint provenance does not match')
        state.update(state='completed', stage='completed', evaluation_summary=str(evaluation / 'summary.json'),
                     final_arms=report.get('arms'), final_paired=report.get('paired'))
        save()
        return state
    except BaseException as exc:
        if child is not None and child.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=no_window, check=False)
            else:
                child.terminate()
            child.wait()
        state.update(state='failed', error=f'{type(exc).__name__}: {exc}', child_pid=None)
        save()
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--data-dir', required=True)
    p.add_argument('--root-dir', required=True)
    p.add_argument('--games', type=int, default=640)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--boss-simulations', type=int, default=10000)
    p.add_argument('--eval-runs', type=int, default=50)
    p.add_argument('--evaluation-games', type=int, default=100)
    p.add_argument('--lr', type=float, default=3e-4)
    p.add_argument('--prior-weight', type=float, default=0.05)
    p.add_argument('--max-steps', type=int, default=5000)
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--evaluation-seed-offset', type=int, default=30000)
    return run(**vars(p.parse_args(argv)))


if __name__ == '__main__':
    main()
