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
| P2b | 通用公开阵容 roster：capture/validate/create/restore + 原生遭遇构造 + 逐步 parity | 已完成 |
| P2c | all-content 版本：观测/校验/公开回合历史 + 场景与牌库接入 | 已完成 |
| P2d | all-content 粒子采样 + 实体编码 + 适配器/MCTS 接入 | 已完成 |
| P2e | 全遭遇一致性扫描：81 遭遇中 64 通过 + 1 专用契约 + 16 待补 | 已完成（16 项已知差异归档） |
| P2f | 差异收敛：65 通过 + 2 采样 + 1 专用契约 + 13 待补 | 已完成 |
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

### 步骤 5（2026-10-18）通用公开阵容 roster（P2b）

- 新增 `sts2_env/az/roster.py`：`EnemySlot` 公共槽位（怪物 ID、血量/格挡、公开能力、可见意图列表、由意图+历史推导的当前招式、已执行招式历史、逃跑标记）。
- 当前招式**从公开信息推导**（`move_from_intents`），原生私有状态机 ID 只用于校验推导一致；推导失败或存在歧义即拒绝，不做猜测。
- `create_slots` 以**原生遭遇 setup 作为构造 oracle**：按观测阵容重采样 setup（含 Exoskeleton 位置等逐槽参数），其余后召唤槽用怪物构造变体兜底；`restore_slots` 恢复 AI 状态日志/当前招式/能力/HP/格挡。
- 新增 `tests/test_az_roster.py`（19 项）：15 个跨幕遭遇（含女王、凯撒蟹、造门者、瀑布巨人 Boss、4 槽阵容）的捕获→校验→粒子重建往返，以及推进回合后与真实世界的逐槽 parity（对齐随机流作为 parity oracle）。
- 静态审计保持：121/122 怪物、80/81 遭遇通过判据（TEST_SUBJECT 由 Boss 专用契约处理）。

### 步骤 6（2026-10-18）all-content 内容版本与公开回合历史（P2c）

- 新增内容版本 `ironclad-colorless-all-v6`（信息版本 `ironclad-colorless-all-information-v1`），与 V4 共享**同一套卡牌契约**，仅把敌人半边换成通用 roster；V4 权重/Replay 不受影响。
- 新增 `sts2_env/az/all_content.py`：`observe_all`（卡牌半边复用 V4 编解码 + 通用 roster 捕获）、`validate_all`（卡牌半边以 V4 视图校验 + roster 校验 + 终局奖励账本）、`finish_history`（合并可见日志、按 `enemy_action` 事件追加实际出招，不读私有 AI 游标）、`roster_rows`。
- 接入：`content` 版本常量与 profiles、`scenarios`（全部 act1–act4 遭遇可用）、`decks`（共享 V4 卡池）、`information`（observe/validate/terminal_value 分派、`encounter` 字段、ALL_CONTENT 公开回合分支）。
- 卡牌契约补充：`SLIMED` 状态牌（史莱姆生成，含消耗/抽 1）、卡牌 `affliction`（bound/entangled）公开状态与恢复。
- 新增 `tests/test_az_all_content.py`（28 项）：13 个跨幕遭遇的初始观测与一整个公开回合校验；明确记录 Queen 暂缓原因（ChainsOfBinding 的公开 affliction 账本未实现），不静默接受。
- 未完成：粒子采样、实体编码、适配器与动态 MCTS 的 ALL_CONTENT 分派（P2d）。
- 回归：卡牌/roster/all-content 1003 项、Transformer 287 项串行通过。
- 已知快照遗留：`tests/test_az_t4_course.py` 有 5 项在改动前就失败（冻结 witness 缺 `exhausted_this_turn` 等新字段，`public_from_dict` 抛 KeyError）；已用 `git stash` 在未改动树上复现，确认不是本轮引入，未在本轮修复。

### 步骤 7（2026-10-18）all-content 粒子与 MCTS 全链路（P2d）

- `all_content.sample_particle`：从公开状态重建整场粒子（遭遇构造 → 牌堆/牌面记忆 → 玩家能力/状态 → 执行栈 → 通用敌人恢复），恢复后与根状态逐字段相等。
- `information` 分派：`BeliefSampler` 与 `SearchParticle.step` 走 all-content 的 `check_transition`/`finish_history`，不触碰 V4 路径。
- 实体编码：`all_entities.enemy_entities` 逐槽编码可见意图（攻击值→damage、其余意图图标→intent_* 操作）、公开能力、招式图位置与后继；`expanded_entities` 对 ALL_CONTENT 跳过旧十怪循环并复用卡牌半边；新增 intent_* / public_power 词表（registry v6）。
- 适配器/动作：`adapter`（奖励账本、公共初始、回合日志）、`actions`（4096 动作空间与随机目标别名归一）、`action_candidates` 全部支持 ALL_CONTENT。
- 修复：敌人状态 `skip_next_tick` 恢复时机、玩家侧怪物减益的首跳消耗（对齐 V4 口径）、SLIMED 在 `prototype`/出牌记忆中的构造。
- 测试 `tests/test_az_all_mcts.py`：**13 项通过**（nibbits/cultists/chompers 的逐步粒子 parity、编码确定性、XS 动态 MCTS 可重复性、奖励账本、内容不匹配拒绝）；**5 项 xfail 且写明原因**，逐项记录仍与真实世界有差异的遭遇（slimes 分裂、bowlbugs 位置脚本、axebots 逐槽构造、waterfall giant 多目标减益时序、kaiser crab 奖励账本/槽位能力）。
- 回归：卡牌/all-content 1016 项通过（5 xfailed）、Transformer 287 项通过；V4 路径未被改动。

### 步骤 8（2026-10-18）全遭遇 MCTS 一致性扫描（P2e）

- 新增 `scripts/audit_all_encounter_parity.py`：对全部 81 个 act1–act4 遭遇，逐步采样动作、重建粒子、与真实世界逐字段对比（对齐随机流仅作 parity oracle）。
- 结果：**64 通过 + 1 专用契约（TEST_SUBJECT）+ 16 待处理**；报告 `docs/ALL_ENCOUNTER_PARITY.md`，原始结果 `docs/all_encounter_parity.json`。
- 本轮修复：玩家 SHRINK 观测/粒子恢复、死亡槽位不得再获得公开出招（slimes/bowlbugs 复活出招问题）、召唤槽位 append-only 的初始 HP 与奖励账本、终局 V7 风险的公开入参、继承状态牌 `TOXIC`/`INFECTION`/`BECKON`/`FRANTIC_ESCAPE` 的描述与构造、`execution` 恢复使用状态牌工厂。
- 16 个待处理遭遇按类别归档（卡牌关键词/战斗变量/库存、负值临时状态、召唤槽位、能量、Boss 修正、粒子根状态、回合侧、意图唯一性、洗牌），全部为**显式拒绝**而非静默通过。
- 回归：卡牌/all-content **1020 项通过（1 xfailed）**、Transformer **287 项通过**。

### 步骤 9（2026-10-18）差异收敛与敌人能力簿记（P2f）

- 修复并转入通过：infested prisms（VITAL_SPARK 每回合触发计数进入敌人能力簿记 `EnemySlot.power_state`）、fabricator/ovicopter 归类为“召唤槽构造随机流不可见”的采样差异（槽位出现后即公开）、FRANTIC_ESCAPE 公开费用增长、`hexed`/`smog` 卡牌 affliction 状态（关键词与 `_smoggy`）。
- 扫描结果更新：**65 通过 + 2 采样差异 + 1 专用契约 + 13 待补**（报告 `docs/ALL_ENCOUNTER_PARITY.md`）。
- 13 项待补按原因收敛为：卡牌状态事件缺失（5）、临时负值基础状态（2）、粒子根状态（2）、回合侧（1）、意图唯一性（1）、洗牌（1）、Boss 伤害修正（1）。
- 回归：卡牌/all-content **1020 项通过（1 xfailed）**。
