# 进展记录（按 spec_1.md 继续推进）

本文件按用户要求，每完成一步就简要记录“做了什么、怎么验证、提交在哪里”，便于回退。

- 仓库：https://github.com/Cher1shYe/SlayTheModel（快照分支 `snapshot/sts2-workspace-20261012`，提交 `248dcc4`）
- 工作分支：`feature/az-all-mcts-xs`（从快照分支切出，所有提交在本分支，可随时 `git switch snapshot/sts2-workspace-20261012` 回退）
- 工作目录：`D:\project\sts2_compactformer`（根仓库）；主要代码在 `sts2-rl-agent/`

## 目标（本阶段）

按 `sts2-rl-agent/spec_1.md` 继续：

1. **内容接入**：全战士（87）+ 全无色（64）卡牌、全怪物的 MCTS/粒子重建接入（六链路：engine / observation / action / network / belief-search / tests）。
2. **自进化**：以战斗内任意卡组与怪物为范围，训练出可出牌的网络；**先用 XS 档**（4 层 / d_model=128 / 4 头 / FFN 512）。
3. 验收沿用 spec_1 冻结口径：实际 network 整场 V7 效用为主指标，胜率仅诊断；不读取最终留出集。

## 计划与阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 拉取仓库、切工作分支、复制 `.venv-az`、恢复可跑测试 | 已完成 |
| P1 | 补齐剩余 31 张牌（战士 4 + 无色 27）的六链路与 MCTS 重建 | 进行中 |
| P2 | 全怪物通用公开状态 + 粒子重建 + MCTS 接入（新版本契约） | 未开始 |
| P3 | 全内容任意卡组 generator / 训练编排（XS 自进化） | 未开始 |

## 步骤记录

### 步骤 0（2026-10-17）环境与分支

- 浅克隆快照分支到工作目录；`git log` 确认 HEAD = `248dcc4`（V4 机制与本批生成闭合）。
- 从快照分支切出 `feature/az-all-mcts-xs`，后续所有提交在此分支。
- 按用户指定把 `C:\Users\15808\Desktop\github\sts2_laya\sts2-rl-agent\.venv-az` 复制到 `sts2-rl-agent/.venv-az`（Python 3.12.14、torch 2.14.1+cpu、numpy 2.5.3、gymnasium 1.4.0、pytest 9.1.1、psutil 7.2.2）。
- 复制后的 venv 自带 editable 安装仍指向源目录（`sts2_env` 导入到旧路径）；已 `pip uninstall sts2-rl-agent` 后在本仓库重新 `pip install -e . --no-deps`，`__editable__` 映射改为 `D:\project\sts2_compactformer\sts2-rl-agent\sts2_env`，`import sts2_env` 已指向本仓库。
- 用 venv 运行 `scripts/audit_ironclad_colorless_coverage.py`：复现快照结论 **接通 120/151（战士 83/87、无色 37/64），待接通 31**。
- 说明：本机另有其它项目的 python 任务在跑，不与本仓库共享进程；本仓库测试一律用 `.venv-az`。

### 步骤 1（2026-10-17）剩余 31 张牌的原生语义盘点

用 `scripts/_tmp_card_audit.py`（临时脚本）逐张读取原生工厂与效果函数，得到可行性分类（详见下一条提交的 P1 清单文档）。初步结论：

- 单人可执行、需新增公开状态/机制：Corruption（技能 0 费+消耗）、Demonic Shield（自伤+格挡，ANY_ALLY）、Feed（击杀提升最大生命）、Tank（TANK 能力）、Automation/Beacon of Hope/Nostalgia/Panache/Rolling Boulder/Prolong/The Bomb/The Gambit/Tag Team/Knockdown（能力或延迟结算）、Bolas/Thrumming Hatchet（回手）、Gold Axe（按本场出牌数）、Hand of Greed（金币在战斗外）、Gang Up（协同攻击）、Demonic Shield。
- 依赖多人队友的 ANY_ALLY/ALL_ALLIES：Believe in You、Coordinate、Huddle Up、Intercept、Lift、Mimic、Rally —— 需确认单人解析规则后再决定接入或显式拒绝。
- 明确暂缓（跨职业生成/药水）：Alchemize（药水不在战斗范围）、Entropy、Jack of All Trades、Splash。
