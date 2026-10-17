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
| P1a | 剩余 31 张牌语义盘点与分类（19 可接入 / 8 多人语义 / 4+1 暂缓） | 已完成 |
| P1b | 19 张牌六链路 + MCTS 重建接入（累计 139/151） | 已完成 |
| P1c | 计数/延迟 7 张接入（NOSTALGIA/PROLONG/GAMBIT/AUTOMATION/PANACHE/ROLLING_BOULDER/BOMB），累计 146/151 | 已完成 |
| P1d | 剩余 5 张范围暂缓（药水/跨职业生成/隐藏身份）归档 | 已完成 |
| P2a | 全怪物静态清单与通用接入判据（122 怪物 / 81 遭遇；121+80 通过判据） | 已完成 |
| P2b | 通用公开阵容（roster）capture/restore/validate + 粒子与 MCTS 接入 | 进行中 |
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

用 `scripts/_tmp_card_audit.py`（临时脚本）逐张读取原生工厂与效果函数，并按单人语义分类：

- **真实单人机制（19）**：FEED、CORRUPTION、TANK、KNOCKDOWN、TAG_TEAM、GANG_UP、HAND_OF_GREED、GOLD_AXE、BOLAS、THRUMMING_HATCHET、BEACON_OF_HOPE（能力/延迟）、DEMONIC_SHIELD 等。
- **多人语义（8）**：ANY_ALLY 六张（DEMONIC_SHIELD、BELIEVE_IN_YOU、COORDINATE、INTERCEPT、LIFT、MIMIC）单人无合法目标 → 不可出；ALL_ALLIES 两张（HUDDLE_UP、RALLY）可出但只作用于队友 → 单人空操作。
- **暂缓（5）**：ALCHEMIZE（药水）、ENTROPY/JACK_OF_ALL_TRADES/SPLASH（跨职业生成）、HIDDEN_GEM（隐藏抽牌堆身份变异）。
- **待补契约（7）**：AUTOMATION、NOSTALGIA、PANACHE、PROLONG、ROLLING_BOULDER、THE_BOMB、THE_GAMBIT。

### 步骤 2（2026-10-17）19 张牌接入（P1b）

- 新增 `sts2_env/az/all_cards.py`：19 张牌的工厂表、机制描述、单人语义分组（`ALLY_REQUIRED`/`ALLY_ONLY`/`OUT_OF_COMBAT`/`RETURNING`）。
- 机制词表 v5：新增 `skill_cost_zero`、`skill_exhaust`、`gain_max_hp`、`knockdown`、`tag_team`、`gold`、`return_to_hand`、`ally_guard`，目标 `ally`/`allies`，条件 `ally_required`/`ally_present`。
- 玩家能力：新增 `TANK`（强化攻击受伤 ×2）、`CORRUPTION`（技能 0 费+消耗）、`BEACON_OF_HOPE`（单人无队友无效果）；公共账本按引擎实际累加。
- 敌人公开状态：新增 `KNOCKDOWN`、`TAG_TEAM`（可见但单人不触发），恢复时补 `_instances` 施加者。
- FEED：`player_max_hp` 放宽到 80..1080，粒子按公开值恢复；击杀提升最大生命。
- GOLD_AXE：粒子重建补回 `_played_cards_combat`（仅公开 `start` 事件计数）。
- BOLAS / THRUMMING_HATCHET：回手标记由公开出牌历史推导，按“最近打出”恢复同面牌（洗牌顺序相关）。
- 覆盖审计脚本升级 `ironclad-colorless-coverage-v5`，新增逐张 `notes`；重新生成清单：**139/151 接通（战士 87/87、无色 52/64），待接通 12**。
- 新增 `tests/test_az_ironclad_colorless_all.py`（112 项：描述/编码往返、XS 动态 MCTS 重建、粒子轨迹、逐机制行为断言）。
- 报告：`sts2-rl-agent/docs/AZ_IRONCLAD_COLORLESS_ALL.md`。

### 步骤 3（2026-10-17）计数／延迟 7 张接入（P1c/P1d，累计 146/151）

- 玩家能力新增：`NOSTALGIA`（牌顶回手）、`BLOCK_NEXT_TURN`（下回合格挡）、`THE_GAMBIT`（未格挡强化攻击即死）、`AUTOMATION`（每 10 抽 +能量）、`PANACHE`（每 5 次出牌伤害）、`ROLLING_BOULDER`（回合开始伤害递增）、`THE_BOMB`（3 回合倒计时爆炸）。
- `power_memory` 增加 `extras` 公共簿记（`_instances`/`_started`/`cards_left`/`damage`），并由出牌/抽牌/回合历史恢复；`player_abilities` 校验存在性与倒计时生命周期（THE_BOMB 只在出牌后 3 回合内存在）。
- 引擎公开日志补漏：打出牌被放回抽牌堆顶（Nostalgia）现在写入 `draw_insert` 事件；`BLOCK_NEXT_TURN` / `THE_BOMB` 结算后移除自身能力。
- 覆盖清单重新生成：**146/151 接通（战士 87/87、无色 59/64），剩余 5 张全部范围暂缓**（ALCHEMIZE 药水、ENTROPY/JACK_OF_ALL_TRADES/SPLASH 跨职业生成、HIDDEN_GEM 隐藏抽牌堆身份）。
- 新增测试并入 `tests/test_az_ironclad_colorless_all.py`（共 155 项）；报告与覆盖文档同步更新。

### 步骤 4（2026-10-18）全怪物静态清单与通用接入判据（P2a）

- 新增 `sts2_env/az/monster_registry.py`：从原生 act1–act4 遭遇表枚举 **81 个战斗遭遇**、**122 个怪物**，只读静态数据（工厂 + 招式图），不跑任务、不读世界。
- 通用接入判据（可复算）：① 当前招式能由可见意图唯一确定——不存在两个可及后继（含初始招式 64 次构造采样）显示相同意图签名；② 粒子能用公开招式历史重建同一 AI 状态。
- 结果：**121/122 怪物、80/81 遭遇**满足判据；唯一例外 `TEST_SUBJECT`（三形态同意图）由既有 `boss_phases` 专用契约处理，不用通用规则猜测。
- 新增 `scripts/audit_monster_coverage.py` 生成 `docs/MONSTER_COVERAGE.md` 与 `docs/monster_coverage.json`（逐遭遇阵容、逐怪物招式/歧义/多意图）。
- 新增 `tests/test_az_monster_registry.py`（7 项：遭遇表枚举、招式图不变量、容量上限、TEST_SUBJECT 显式拒绝）。
