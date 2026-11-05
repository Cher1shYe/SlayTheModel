from pathlib import Path

from deployment.armg_floor_progress_watch import render


def test_render_reads_new_schedule_and_validation_settings():
    config = {
        'combat_budget_start': 2000, 'combat_budget_per_floor': 200,
        'combat_budget_elite_bonus': 1000, 'combat_budget_boss_bonus': 2000,
        'skip_elo_start': 1350, 'skip_elo_per_floor': 10,
        'prior_weight': 0.1, 'eval_every': 320, 'eval_runs': 25,
    }
    result = render({'state': 'running'}, config, Path('run'), True)
    assert '第 1 层 2000 次，之后每层增加 200 次；精英战额外增加 1000 次；Boss 战额外增加 2000 次' in result
    assert '跳过评分：第 1 层 1350，之后每层增加 10' in result
    assert '每 320 局及训练结束时评估 25 局' in result


def test_render_preserves_legacy_schedule_without_bonuses():
    config = {
        'combat_budget_start': 1000, 'combat_budget_per_floor': 200,
        'skip_elo_start': 1400, 'skip_elo_per_floor': 15,
    }
    result = render({'state': 'stopped'}, config, Path('run'), False)
    assert '第 1 层 1000 次，之后每层增加 200 次' in result
    assert '额外增加' not in result
    assert '跳过评分：第 1 层 1400，之后每层增加 15' in result


def test_render_reports_puct_reward_and_final_boss_potion():
    config = {
        'combat': 'puct-root-oracle', 'combat_budget_start': 3000,
        'combat_budget_per_floor': 500, 'combat_budget_elite_bonus': 0,
        'combat_budget_boss_bonus': 0, 'skip_elo_start': 1350,
        'skip_elo_per_floor': 10, 'prior_weight': .05,
        'reward_formula': '1.0 if won else floor / 50.0',
        'final_boss_potion_weight': 0.0, 'other_battle_potion_weight': 4.0,
    }
    state = {'state': 'running', 'games': 32, 'target_games': 1024,
             'workers': 8, 'mean_floor': 38.5}
    result = render(state, config, Path('run'), True)
    assert 'oracle 根先验 PUCT（n=1）' in result
    assert '战斗 PUCT：第 1 层 3000 次，之后每层增加 500 次' in result
    assert '额外增加' not in result
    assert '32 / 1024 局' in result
    assert '38.50 层' in result
    assert '卡牌先验损失权重：0.05' in result
    assert '通关为 1.0，其他对局为最终层数 / 50.0' in result
    assert '最终 Boss 剩余药水评分权重：0.0；其他战斗：4.0' in result
