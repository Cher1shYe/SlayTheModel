"""Publish a readable progress.md for an existing floor-scheduled ArmG run.

This separate watcher only reads the trainer's JSON and never controls it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from deployment.armg_progress_floor import _process_alive


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def render(state, config, root, alive):
    names = {'running': '运行中', 'completed': '已完成', 'failed': '失败', 'stopped': '已停止'}
    phases = {'training': '强化学习采样与训练', 'validation': '评估', 'done': '完成', 'failed': '失败', 'stopped': '已停止'}
    status = state.get('state', 'unknown')
    if status == 'running' and alive is False:
        status_text = '训练进程已退出（未记录结束状态，请检查错误日志）'
    else:
        status_text = names.get(status, status)
    games = state.get('games', 0)
    target = state.get('target_games', 0)
    mean = state.get('mean_floor')
    mean_text = f'{mean:.2f} 层' if isinstance(mean, (float, int)) else '尚无已完成批次'
    combat = str(config.get('combat', 'mcts-oracle'))
    is_puct = 'puct' in combat.lower()
    combat_label = 'oracle 根先验 PUCT（n=1）' if is_puct else 'oracle 纯 MCTS'
    search_label = 'PUCT' if is_puct else 'MCTS'
    lines = [
        '# ArmG 强化学习与网站先验进度', '',
        f'- 状态：{status_text}',
        f"- 阶段：{phases.get(state.get('stage'), state.get('stage', '未知'))}",
        f'- 强化学习进度：{games} / {target} 局' + (f'（{games / target * 100:.1f}%）' if target else ''),
        f'- 累计平均层数：{mean_text}（仅统计已完成并写入的批次）',
        f"- worker：{state.get('workers', '未知')}；战斗模式：{combat_label}",
        f"- 战斗 {search_label}：第 1 层 {config.get('combat_budget_start', '未知')} 次，之后每层增加 {config.get('combat_budget_per_floor', '未知')} 次"
        + (f"；精英战额外增加 {config['combat_budget_elite_bonus']} 次" if config.get('combat_budget_elite_bonus') else '')
        + (f"；Boss 战额外增加 {config['combat_budget_boss_bonus']} 次" if config.get('combat_budget_boss_bonus') else ''),
        f"- 卡牌先验损失权重：{config.get('prior_weight', '未知')}；跳过评分：第 1 层 {config.get('skip_elo_start', '未知')}，之后每层增加 {config.get('skip_elo_per_floor', '未知')}",
        f"- 更新时间（UTC）：{state.get('updated_utc', '未知')}",
    ]
    if config.get('reward_formula'):
        formula = config['reward_formula']
        if formula == '1.0 if won else floor / 50.0':
            lines.append('- 强化学习回报：通关为 1.0，其他对局为最终层数 / 50.0')
        else:
            lines.append(f'- 强化学习回报：{formula}')
    if 'final_boss_potion_weight' in config:
        lines.append(f"- 最终 Boss 剩余药水评分权重：{config['final_boss_potion_weight']}；其他战斗：{config.get('other_battle_potion_weight', '未知')}")
    if state.get('inflight_total'):
        lines.append(f"- 当前批次已完成：{state.get('inflight_completed', 0)} / {state['inflight_total']} 局（尚未计入累计结果）")
    if state.get('interrupted_batch'):
        batch = state['interrupted_batch']
        lines.append(f"- 停止时未保存的批次：已完成 {batch.get('completed', 0)} / {batch.get('total', 0)} 局，未计入累计结果或模型")
    batch = state.get('last_batch') or {}
    train = batch.get('train') or {}
    if isinstance(train.get('mean_floor'), (int, float)):
        lines.append(f"- 最近批次：{train['mean_floor']:.2f} 层（{train.get('completed', 0)} 局；通关率 {100 * train.get('win_rate', 0):.2f}%）")
    val = state.get('last_validation')
    if val and isinstance(val.get('mean_floor'), (int, float)):
        lines.append(f"- 最近一次验证：{val['mean_floor']:.2f} 层（{val.get('completed', 0)} 局；通关率 {100 * val.get('win_rate', 0):.2f}%）")
    else:
        lines.append(f"- 最近一次验证：暂无结果（每 {config.get('eval_every', '未知')} 局及训练结束时评估 {config.get('eval_runs', '未知')} 局）")
    if state.get('error'):
        lines.append(f"- 错误：{state['error']}")
    active = state.get('active_episodes') or []
    if active:
        lines += ['', '### 当前工作进程', '', '| worker PID | 对局种子 | 已开始战斗决策 | 已完成模拟 |', '|---:|---:|---:|---:|']
        for ep in active:
            lines.append(f"| {ep.get('worker_pid', '?')} | {ep.get('seed', '?')} | {ep.get('combat_decisions_started', 0)} | {ep.get('completed_simulations', 0)} |")
        lines += ['', '注：活动信息按工作进程定期上报，可能有短暂延迟。']
    lines += ['', f'- 训练配置：`{root / "config.json"}`', f'- 训练指标：`{root / "metrics.jsonl"}`',
              f'- 最新模型：`{root / "latest.pt"}`', '']
    return '\n'.join(lines)


def refresh(root, pid):
    state = read_json(root / 'progress.json')
    config = read_json(root / 'config.json')
    if not isinstance(state, dict) or not isinstance(config, dict):
        return None
    alive = _process_alive(pid)
    temporary = root / f'progress.watch.{os.getpid()}.tmp'
    try:
        temporary.write_text(render(state, config, root, alive), encoding='utf-8')
        os.replace(temporary, root / 'progress.md')
    except OSError:
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return state, alive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-dir', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--interval', type=float, default=5)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('interval must be positive')
    root = Path(args.root_dir).resolve(strict=True)
    while True:
        result = refresh(root, args.pid)
        if result:
            state, alive = result
            if state.get('state') in ('completed', 'failed', 'stopped') or alive is False:
                return
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
