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
    prior_text = str(config.get('prior_weight', '未知'))
    if config.get('prior_weight_formula'):
        weight = state.get('next_prior_weight')
        prior_text = (f'{weight:.6f}（下一批）' if isinstance(weight, (int, float)) else '待更新')
        prior_text += '；公式：0.2 × (1 − 已完成训练局数 / 10000)，最低为 0'
    lines = [
        ('# A10 ArmG 从零训练进度' if config.get('ascension') == 10 else '# ArmG 强化学习与网站先验进度'), '',
        f'- 状态：{status_text}',
        f"- 阶段：{phases.get(state.get('stage'), state.get('stage', '未知'))}",
        f'- 强化学习进度：{games} / {target} 局' + (f'（{games / target * 100:.1f}%）' if target else ''),
        f'- 累计平均层数：{mean_text}（仅统计已完成并写入的批次）',
        f"- worker：{state.get('workers', '未知')}；战斗模式：{combat_label}",
        f"- 战斗 {search_label}：第 1 层 {config.get('combat_budget_start', '未知')} 次，之后每层增加 {config.get('combat_budget_per_floor', '未知')} 次"
        + (f"；精英战额外增加 {config['combat_budget_elite_bonus']} 次" if config.get('combat_budget_elite_bonus') else '')
        + (f"；Boss 战额外增加 {config['combat_budget_boss_bonus']} 次" if config.get('combat_budget_boss_bonus') else ''),
        f"- 卡牌先验损失权重：{prior_text}；跳过评分：第 1 层 {config.get('skip_elo_start', '未知')}，之后每层增加 {config.get('skip_elo_per_floor', '未知')}",
        f"- 更新时间（UTC）：{state.get('updated_utc', '未知')}",
    ]
    if config.get('reward_formula'):
        formula = config['reward_formula']
        if formula == '1.0 if won else floor / 50.0':
            lines.append('- 强化学习回报：通关为 1.0，其他对局为最终层数 / 50.0')
        elif formula == 'boss-count':
            lines.append('- 强化学习回报：实际击败 Boss 数量（0–4）；第三幕第一个 Boss 打赢得 3，全部通关得 4')
        elif formula == 'floor-boss-elite':
            lines.append('- 强化学习回报：最终层数 / 50 + 累计 Boss 加分 + 累计精英加分；第 i 个 Boss 击败后额外 +i（四个累计 +10），每个精英击败后额外 +0.15 × 所在幕数')
        elif formula == 'floor20-boss-elite01':
            lines.append('- 强化学习回报：最终层数 / 20 + 累计 Boss 加分 + 0.1 × 击败精英数；第 i 个 Boss 击败后额外 +i（四个累计 +10），精英加分不随幕数变化')
        elif formula in ('floor20-boss-elite01-actions', 'floor20-boss-elite01-actions-elo'):
            lines.append('- 强化学习回报：最终层数 / 20 + 累计 Boss 加分 + 0.1 × 击败精英数 + 0.05 × 火堆升级次数 + 0.02 × 商店删牌次数；第 i 个 Boss 额外 +i（四个累计 +10）')
            if formula.endswith('-elo'):
                lines.append('- 结算额外奖励：永久牌组中纳入统计的牌平均 Elo / 5000；打击、防御、痛击及缺失 Elo 牌按 1150，升级牌沿用原牌 Elo')
        else:
            lines.append(f'- 强化学习回报：{formula}')
    if config.get('deck_elo_excluded'):
        lines.append('- Elo 排除：多人专用牌、诅咒、状态、衍生、事件牌、腐化、Break 和 GRAPPLE，均不计入分子与分母')
    if config.get('algorithm') == 'ppo':
        lines.append(f"- 训练算法：PPO + 独立价值网络；每批最多 {config['ppo_epochs']} 轮，clip={config['clip_ratio']}，目标 KL={config['target_kl']}，γ={config['gamma']}，GAE λ={config['gae_lambda']}")
    if 'final_boss_potion_weight' in config:
        lines.append(f"- 最终 Boss 剩余药水评分权重：{config['final_boss_potion_weight']}；其他战斗：{config.get('other_battle_potion_weight', '未知')}")
    if 'combat_changed_at_games' in state:
        lines.append(f"- 战斗搜索切换：已保存 {state['combat_changed_at_games']} 局后改为纯 MCTS；此前批次为 PUCT 结果，此后使用纯 MCTS")
    if 'reward_changed_at_games' in state:
        suffix = 'Actor、Critic 与优化器继续保留，价值网络将适应新回报' if config.get('algorithm') == 'ppo' else '移动平均基线将从新回报重新建立'
        lines.append(f"- 奖励切换：第 {state['reward_changed_at_games']} 局保存后修改；此前回报统计使用旧公式，{suffix}")
    if state.get('inflight_total'):
        lines.append(f"- 当前批次已完成：{state.get('inflight_completed', 0)} / {state['inflight_total']} 局（尚未计入累计结果）")
    if state.get('interrupted_batch'):
        batch = state['interrupted_batch']
        lines.append(f"- 停止时未保存的批次：已完成 {batch.get('completed', 0)} / {batch.get('total', 0)} 局，未计入累计结果或模型")
    batch = state.get('last_batch') or {}
    ppo = batch.get('ppo')
    if ppo:
        lines.append(f"- 最近 PPO 更新：{ppo['updates']} 次；KL={ppo['exact_kl']:.5f}；裁剪比例={ppo['clip_fraction']:.3f}；策略熵={ppo['entropy']:.3f}；价值损失={ppo['value_loss']:.4f}；KL 提前停止={ppo['kl_early_stop']}")
    train = batch.get('train') or {}
    if isinstance(train.get('mean_floor'), (int, float)):
        lines.append(f"- 最近批次：{train['mean_floor']:.2f} 层（{train.get('completed', 0)} 局；通关率 {100 * train.get('win_rate', 0):.2f}%）")
    if isinstance(train.get('mean_reward'), (int, float)):
        if 'mean_floor_reward' in train:
            lines.append(f"- 最近批次平均回报：{train['mean_reward']:.4f}（层数 {train['mean_floor_reward']:.4f} + Boss {train['mean_boss_bonus']:.4f} + 精英 {train['mean_elite_bonus']:.4f}）")
            if 'mean_deck_elo_bonus' in train:
                lines[-1] = lines[-1][:-1] + f" + 牌组 Elo {train['mean_deck_elo_bonus']:.4f}）"
            if 'mean_upgrade_bonus' in train:
                lines[-1] = lines[-1][:-1] + f" + 敲牌 {train['mean_upgrade_bonus']:.4f} + 删牌 {train['mean_removal_bonus']:.4f}）"
                lines.append(f"- 最近批次行为：火堆升级 {train['campfire_upgrades']} 次；商店删牌 {train['shop_removals']} 次")
        else:
            counts = train.get('reward_counts', {})
            lines.append(f"- 最近批次平均回报：{train['mean_reward']:.4f}；回报分布：" + '，'.join(f"{i} 分 {counts.get(str(i), 0)} 局" for i in range(5)))
        strength = (batch.get('site_prior') or {}).get('strength')
        if isinstance(strength, (int, float)):
            lines.append(f'- 最近批次实际使用先验权重：{strength:.6f}')
    if 'mean_deck_elo_bonus' in train:
        lines.append(f"- 最近批次牌组平均 Elo：{train['mean_deck_elo']:.2f}；结算 Elo 奖励：{train['mean_deck_elo_bonus']:.4f}（已计入平均回报）；缺失 Elo 牌 {train['deck_elo_missing_cards']} 张")
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
