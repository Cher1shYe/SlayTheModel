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
| P2g | affliction 公开事件：68 通过 + 2 采样 + 1 专用契约 + 10 待补 | 已完成 |
| P2h | 有符号临时状态与被偷牌事件：71 通过 + 2 采样 + 1 专用契约 + 7 待补 | 已完成 |
| P3a | 任意卡组生成器 + XS 冻结配置/协议（未训练） | 已完成 |
| P3b | 自对弈采集→XS 更新→验证 runner 打通（冒烟，未正式训练） | 已完成 |
| P3c | 契约拒绝 30→6：可见能力 opaque 编码 + 状态相关招式转移 | 已完成 |
| P3d | 契约拒绝 6→1：STUNNED 公开状态 + 零值力量/敏捷可见性 | 已完成 |
| P3e | 验证集 64/64 全可评估：Dampen 降级公开事件 | 已完成 |
| P3f | runner CLI/preflight/resume；训练后 checkpoint 复评 64/64 | 已完成 |
| P3g | 幻象复活/眩晕/砂坑公开状态：parity 75，准入 74，验证 64/64 | 已完成 |
| P3h | 玩家朝向公开簿记：parity 76，准入 75，验证 64/64 | 已完成 |
| P3i | runner 基线/配对增益/耗时报告与 `--no-baseline` | 已完成 |
| P3j | 剩余 2 个 parity 差距定位（Boss 问题选择、Lagavulin 唤醒意图） | 已完成（归档，不接入） |
| P3k | 并行采集（`--workers`，权重冻结 + 池复用），与串行轨迹一致 | 已完成 |
| P3l | 测试集门槛强制 + 断点恢复回归测试 | 已完成 |
| P3m | 验证集按遭遇分组诊断 + preflight 清单漂移/测试集校验 | 已完成 |
| P3n | 基线证据持久化（`baseline.json`）+ resume 配对比较不丢失 | 已完成 |
| P3o | 全流程同 seed 可复现 + 报告 provenance | 已完成 |
| P3p | 搜索目标信号诊断（熵/峰值/强制动作）与预算 8 抽样 | 已完成 |
| P3q | 初始策略诊断：network-only vs MCTS-8（+0.177 配对增益） | 已完成 |
| P3r | 不可区分招式变体 + 已知位置回退：诊断 16/16，pair +0.288 | 已完成 |
| P3s | 变体/位置回退的单元测试；globe head 根因定位（初始日志被清空） | 已完成 |
| P3t | 初始公开历史承载战斗开始事件：准入 76/76，验证 64/64 | 已完成 |
| P3u | 零值力量恢复：MCTS 诊断 16/16、0 拒绝（+0.244） | 已完成 |
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

### 步骤 10（2026-10-18）affliction 公开事件（P2g）

- `CardInstance.afflict/clear_affliction` 现在调用 `log_public_state_change`，`public_state_blob` 增加 `affliction` 字段；玩家/引擎可见日志能闭合“卡牌被 hexed/smog/bound/entangled”导致的牌面变化。
- `FRANTIC_ESCAPE` 的费用增长也写入公开日志；玩家能力簿记补充 `CHAINS_OF_BINDING`（`_bound_cards_this_turn`、`_bound_card_played`）。
- 扫描结果：**68 通过 + 2 采样 + 1 专用契约 + 10 待补**；queen、knights、living fog、vine shambler、the insatiable 由失败转通过。
- 回归：引擎 parity 274 项 + 卡牌/all-content 1020 项（1 xfail）通过。

### 步骤 11（2026-10-18）有符号临时状态与被偷牌事件（P2h）

- 基础状态允许 `DEXTERITY`/`SETUP_STRIKE` 负值（TENDER 类临时减益），`TENDER._cards_played_this_turn` 进入公开能力簿记；hunter killer、the lost and forgotten 转通过。
- Thieving Hopper 偷牌写入公开 `steal` 事件（牌面 + 回合），公开库存与已知位置同步更新；洗牌事件按原生规则重置位置；thieving hopper 转通过。
- 扫描结果：**71 通过 + 2 采样 + 1 专用契约 + 7 待补**；剩余为粒子敌人槽位（3）、召唤槽位（1）、回合侧（1）、意图唯一性（1）、Boss 伤害修正（1）。
- 回归：引擎 parity + 卡牌/all-content **1287 项通过（1 xfailed）**。

### 步骤 12（2026-10-18）任意卡组生成器与 P3 冻结配置（P3a）

- 新增 `sts2_env/az/all_decks.py`：`all-decks-v1` 任意卡组生成器。卡池为 146 张已准入初始卡（延迟卡不出现），卡组 8–30 张、同名最多 4 张、升级概率 0.3；遭遇仅取公开一致性扫描通过的 71 个；种子空间：训练 `[2^30,1.5·2^30)`、验证 `[1.5·2^30,·)`、测试 `[2^30+3·2^26,2^31)`，坐标为纯函数。
- `decks.py` 新增任意卡组校验（ALL_CONTENT）；`deck_observation` 对 ALL_CONTENT 放行到 30 张。
- 抽样证据 `docs/all_deck_generator.json`：192 train + 64 validation + 64 test；训练覆盖 **146/146 张卡、66/71 个遭遇**，卡组 8–30（均值 18.9），升级率 29.4%。
- 冻结 `configs/az_all_xs_v1/config.json`（`az-all-xs-v1`，XS 全新初始化、搜索预算 8、8 轮 × 48 局、batch 64、lr 3e-4、value 0.1）与 `protocol.json`（64 验证 + 64 测试配方、生成器清单 SHA、训练坐标规则）。
- 设计/诚实性约束见 `docs/AZ_ALL_XS_PLAN.md`；新增测试 `tests/test_az_all_decks.py`（9 项）与 `tests/test_az_all_xs_config.py`（4 项）。
- 回归：卡牌/all-content/transformer **1036 项通过（1 xfailed）**。本步**未启动训练**，不宣称任何学习增益。

### 步骤 13（2026-10-18）P3 runner 打通与遭遇鲁棒性（P3b）

- 新增 `sts2_env/az/all_runner.py`：`collect`（原生怪物 + 粒子信念 + 动态搜索采集，公开契约拒绝的配方记录并跳过）→ `update`（XS 策略/价值联合损失，实体 replay）→ `evaluate_recipes`（network-only V7 效用，契约拒绝单独计数）→ 每轮 `iteration-NNN.json`/`report.json` 证据与 checkpoint。
- `entity_transition.public_from_dict` 支持 ALL_CONTENT 槽位（`EnemySlot`）解码；`entity_encoder` 允许最多 5 个目标引用（多敌全体攻击）。
- 修复 `_validate_player_powers` 把敌人基础状态误并入玩家暴露集合（MANGLE 等）的问题；`galvanized` affliction 与 `_galvanized` 标记纳入卡牌公开状态。
- 新增 `scripts/audit_encounter_robustness.py`：71 个通过遭遇 × 2 卡组 × 6 步 → **70 稳定**，`globe_head` 排除；生成器准入改为 parity ∩ robustness（**70 遭遇**），重新生成 `docs/all_deck_generator.json` 与 `configs/az_all_xs_v1/{config,protocol}.json`。
- 管线冒烟（1 轮 / 2 局 / 预算 3 / 1 次更新）：采集与更新成功；验证 64 配方中 34 局完成、30 局被公开契约拒绝（逐条记录），完成局 mean V7 utility 0.328、无非法动作。**仅验证管线，不构成学习增益**。
- 新增 `tests/test_az_all_runner.py`（4 项）；回归：卡牌/all-content/transformer + runner 见下。

### 步骤 14（2026-10-18）P3 契约拒绝收敛（P3c）

- 玩家侧可见能力（Weak/Frail/Constrict/Hex/binding 等怪物减益）在无专用 op 时编码为显式的 `public_power` 金额 token，不再拒绝也不静默丢弃；已知能力路径不变。
- 状态相关招式转移：当前意图在**全招式表**唯一匹配时接受该观测招式；静态图之外的转移仅在来源/目标均为合法招式时放行（`_legal_transition` 保留对伪造 history 的拒绝）。
- 验证集复评：64 配方由 34 完成/30 拒绝 → **58 完成/6 拒绝**（尸体软泥意图歧义、猎手临时负敏捷簿记、骑士生成牌库存）；完成局 mean V7 utility 0.321、0 非法动作。
- 回归：**1047 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 15（2026-10-18）STUNNED 公开状态与拒绝收敛到 1（P3d）

- 公开意图新增“被击倒”状态：AI 处于 `STUNNED` 时以 `('STUNNED',0,1)` 表示（眩晕图标公开），可打断任意招式并在之后恢复脚本；`INTENT_NAMES`/`intent_stun` 词表与校验同步，伪造 history 仍拒绝。
- 公开能力序列不再包含**零值力量/敏捷**（游戏不显示），负值保留可见；修复猎手 TENDER 场景的能力序列误报。
- 验证集复评：64 配方 **63 完成 / 1 拒绝**（骑士精英的生成牌库存），完成局 mean V7 utility 0.347、0 非法动作。
- 回归：**1277 项通过（1 xfailed）**。still 不启动正式训练。

### 步骤 16（2026-10-18）验证集 64/64 全部可评估（P3e）

- Dampen 的公开降级：战斗内把升级牌降级时写入与 `combat.upgrade_card` 同形的 `upgrade` 事件（旧 token→新 token），公开库存与牌面状态对账闭合；`card_state_change` 在战斗开始时（尚未进入牌堆区）也能入账。
- 验证集复评：**64/64 配方全部完成、0 契约拒绝**；mean V7 utility 0.334、胜率 23.4%、0 非法动作。
- 回归：**1316 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 17（2026-10-18）runner CLI/preflight/resume 与训练后复评（P3f）

- `all_runner` 新增：`preflight`（不行动，仅构建+编码全部计划训练/验证配方）、`run(resume=True)`（从 report.json 最后一轮 checkpoint 与 replay 续跑）、`--preflight-only`/`--resume` 等 CLI（`python -m sts2_env.az.all_runner`）。
- 修复训练后策略触发的公开路径：无 pending card 的选择不再假设 `pending_card.token`（保留已知抽牌位置）。
- 校验：preflight 训练 8/8、验证 64/64 可编码（ready=true）；1 轮后 resume 扩到 2 轮正常（历史 2 轮、replay 16 行）；训练 1 次更新后的 checkpoint 复评 **64/64 完成、0 契约拒绝**（仅管线证据，不构成策略结论）。
- 新增测试：preflight、同 seed 采集可复现、无 pending card 的位置推进；回归 **1420 项通过（1 xfailed）**。

### 步骤 18（2026-10-18）运行时公开状态与准入扩到 74（P3g）

- 公开招式状态新增：被击倒 `STUNNED`（引擎 `_current_state_id`/空意图/STUN 意图）与幻象复活 `REVIVE_MOVE`（HEAL 意图，运行时注入、复活后恢复脚本）；粒子恢复时重建这些运行时状态与跟随招式。
- `spawned` 槽位初始 HP 改用生成时最大 HP（复活中/已倒下也可核对）；SANDPIT 恢复目标玩家；Dampen 降级写入 `upgrade(token→token)` 公开事件；战斗开始阶段的卡牌状态变更仅在 all-content 世界入账（不影响旧内容）。
- 结果：parity **75 通过 + 2 采样 + 1 专用契约 + 3 待补**（fogmog/living fog/obscura/insatiable 转通过）；鲁棒性 **74/75 稳定**（globe head 排除）；生成器准入 **74 遭遇**，重新冻结 `configs/az_all_xs_v1/{config,protocol}.json`。
- 复评：新协议验证集 **64/64 完成、0 契约拒绝**，mean V7 utility 0.357、0 非法动作；preflight 训练/验证全部可编码。
- 已知快照遗留（本轮用 `git stash` 在 HEAD 复现）：`test_az_content_expansion.py` 的 2 个 `setup_fogmog_normal` particle 轨迹用例在改动前即失败（Dazed ledger 与 Eye 招式历史不符），未在本轮修复。
- 回归：**1190 项通过（1 xfailed）**（排除上述 2 个既有失败用例）。仍不启动正式训练。

### 步骤 19（2026-10-18）玩家朝向公开簿记与准入 75（P3h）

- 新增 `SURROUNDED.facing` 公开能力簿记：玩家朝向由“攻击了哪一侧”决定并影响背击 1.5× 伤害，属于可见信息；粒子恢复后 Kaiser Crab 的 Crusher/Rocket 伤害与真实世界一致。
- 结果：parity **76 通过 + 2 采样 + 1 专用契约 + 2 待补**（kaiser crab 转通过；剩余 knowledge demon、lagavulin）；鲁棒性 **75/76 稳定**；生成器准入 **75 遭遇**，重新冻结 `configs/az_all_xs_v1/{config,protocol}.json`。
- 新协议复评：验证集 **64/64 完成、0 契约拒绝**，mean V7 utility 0.347、胜率 34.4%、0 非法动作（随机初始化 XS，仅管线证据）。
- 回归：**1190 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 20（2026-10-18）runner 基线、配对增益与耗时报告（P3i）

- `all_runner.paired_gain`：按 `scenario_id` 配对的 bootstrap（均值增益、95% 区间、P(gain>0)），仅作描述性报告，不自动做晋升决策。
- `run` 在首轮更新前评估一次**初始模型基线**并写入 `report.baseline`；每轮记录 `paired_vs_baseline` 与 `seconds{collect,update,evaluate,total}`；新增 `--no-baseline`。
- 报告字段与语义更新至 `docs/AZ_ALL_XS_PLAN.md` §5；新增 2 项 runner 测试（配对确定性/不匹配拒绝、基线+耗时+配对端到端）。
- 回归：**1192 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 21（2026-10-18）剩余两个 parity 差距定位（P3j）

- **knowledge_demon_boss**：失败发生在战斗开始后第 3 步——Boss 以 `PendingCardChoice(prompt='Curse of Knowledge')` 让玩家从两张**生成诅咒牌**（DISINTEGRATION / MIND_ROT）中选一张，选牌发生在敌方侧且没有可见牌堆来源；现有 `PublicChoiceState` 只支持 hand/discard/exhaust/revealed 来源。已归档为“需要生成选项的公开选择契约”，并在 `observe_choice` 增加显式拒绝分支（避免 IndexError）。
- **lagavulin_matriarch_boss**：被击倒后粒子按公开脚本恢复为 SLEEP，而真实 AI 选择 SLASH；公开意图只显示当前招式的伤害，无法唯一确定唤醒后的下一招。归档为“公开信息不足”，保持显式拒绝。
- 两者均**不接入**训练/验证/测试配方；`docs/ALL_ENCOUNTER_PARITY.md` 更新原因。回归 **1192 项通过（1 xfailed）**。

### 步骤 22（2026-10-18）并行采集（P3k）

- `all_runner.collect(..., workers=N)`：把当前权重冻结到临时 checkpoint，用 `self_play.Collector`（spawn、每 worker torch 单线程）按同一冻结权重采集；`run` 跨轮复用进程池，失败 chunk 自动回退串行并记录拒绝（不静默丢弃）。
- CLI 新增 `--workers`；`preflight`/验证路径不变。
- 实测（8 局、预算 2、max_turns 3）：串行 6.58s → 2 worker 冷启 4.48s → 复用水池 3.32s；与串行 episode id/动作/策略目标逐一相同。
- 新增 1 项并行=串行一致性测试；回归 **1193 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 23（2026-10-18）测试集门槛与恢复测试（P3l）

- `run(include_test=True)` 默认强制验证门槛：只有最近一轮相对初始基线的配对 `mean_gain > 0` 才打开 64 个测试配方；否则记录 `test_gate.passed=false` 且不评估测试集；`--force-test` 可显式覆盖并在报告中标注 `forced=true`。
- 新增 2 项 runner 测试：`resume` 从上一轮 checkpoint 续跑（历史保留、只采集新轮）、测试集门槛正/负两种结果。
- 回归：**1195 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 24（2026-10-18）验证诊断与 preflight 硬化（P3m）

- 每轮验证新增 `validation_by_encounter`：按遭遇汇总 episodes / win_rate / mean_utility / death_rate，便于定位拉低效用的怪物。
- `preflight` 硬化：校验协议中的生成器清单 SHA 与当前 `frozen_manifest` 一致（漂移直接拒绝），并额外探测 64 个测试配方可编码；`ready` 同时要求训练/验证/测试均无错误。
- 新增 2 项 runner 测试（验证分组覆盖全部 64 局、协议清单漂移拒绝）；回归 **1197 项通过（1 xfailed）**。仍不启动正式训练。

### 步骤 25（2026-10-18）基线证据持久化与 resume 配对（P3n）

- 首轮更新前把初始基线写成 `baseline.json`（summary + 每局 scenario/encounter/reward/终局原因），事后可复核；`--resume` 会加载该证据，恢复后的每轮 `paired_vs_baseline` 不再丢失（此前 resume 后比较为空）。
- 新增 1 项测试（resume 后配对增益仍为 +0.1、覆盖 64 局）；回归 **1198 项通过（1 xfailed）**。
- 另：`setup_fogmog_normal` 的 2 个既有 EXPANSION 粒子测试根因定位——`summon.acts_this_round` 把 `reviving` 槽位视为出手，而 `generation_after` 只在 `hp>0` 时记录 Dazed，幻象复活后两者不一致；修复需改动 EXPANSION 冻结语义，未在本轮实施（保持既有失败记录）。

### 步骤 26（2026-10-18）全流程可复现与 provenance（P3o）

- 新增短程全流程复现测试：同一 seed 两次 `run`（采集→更新→基线/候选验证→配对）得到相同 episode id/终局/验证效用/配对增益（30s 内完成）。
- `report.json` 新增 `provenance`：config/protocol 的 SHA-256、生成器清单 SHA、内容/奖励/规则版本，便于事后核对训练证据与冻结配置的对应关系。
- 新增 2 项测试；回归 **1200 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 27（2026-10-18）搜索目标信号诊断（P3p）

- `target_stats`：对采集行统计搜索目标的平均熵、平均最大概率、强制动作比例，写入每轮 `target_stats`；用于判断预算 8 是否提供可学习信号。
- 抽样诊断（4 配方、预算 8、max_turns 6）：3 局成功采集（1 局被公开契约拒绝并记录）、53 行，平均熵 **0.763 nat**、平均最大概率 **0.639**、强制动作 **13.2%**——目标既非均匀也非塌缩，具备可学习信号。
- 新增 1 项测试；回归 **1201 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 28（2026-10-18）初始策略诊断：network-only vs MCTS-8（P3q）

- 新增 `scripts/diagnose_all_xs_policy.py`：同一 16 个验证配方上比较初始 XS 的 network-only 与动态 MCTS（预算 8），结果 `docs/all_xs_policy_diagnostic.json`。
- 结果：两侧均 15/16 完成；胜率均 60%；mean V7 utility **0.301 → 0.478**（配对增益 **+0.177**，8 正/3 负/4 平）；决策 p50 10.3ms → 282ms（约 27×），整组 4.5s → 71.8s。
- 诊断还暴露 2 个只在 MCTS 轨迹出现的公开契约边界（turret operator 的私有招式、已知抽牌位置），已记录为后续收敛项；一局在两侧各被拒绝一次。
- 该测量仅说明搜索/管线价值，不构成学习增益；回归 **1201 项通过（1 xfailed）**，仍不启动正式训练。

### 步骤 29（2026-10-18）公开不可区分招式与已知位置回退（P3r）

- **公开不可区分招式变体**：同一怪物两个脚本状态显示完全相同的意图（如 Turret Operator 的 `UNLOAD_MOVE_1/2`）时，记录确定性规范招式，并允许同签名变体之间的脚本边；私有状态只有在签名不同才报错。修复 network-only 的 `Private move disagrees`。
- **已知抽牌位置回退**：`advance_positions` 在可见手牌增长无法全部归因于抽牌时（例如卡牌加入手牌）不再断言错误位置，而是**忘记**已知前后缀（未知顺序是合法的），修复 MCTS 轨迹的 `Visible draw contradicts known position`。
- 复评：16 个验证配方的 network-only 与 MCTS-8 均 **16/16 完成、0 契约拒绝**；mean V7 utility **0.220 → 0.508**，配对增益 **+0.288**（9 正/3 负/4 平）。完整验证集仍 64/64、0 拒绝；parity 76 通过 + 2 采样 + 1 专用契约 + 2 待补；鲁棒性 75/76 不变。
- 回归 **1201 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 30（2026-10-18）变体/位置回退回归测试与 globe head 根因（P3s）

- 新增 2 项单元测试锁定公开行为：同签名招式变体共享规范记录且变体间脚本边可用；可见手牌增长无法全归因抽牌时**忘记**已知位置而不报错。
- `setup_globe_head_normal` 鲁棒性失败的根因定位：战斗开始阶段的 affliction（galvanized）虽已允许入账，但 `ObservableCombatAdapter.__init__` 在首次观测前会清空 `visible_card_events`（“初始手牌已在初始状态中”），导致初始手牌状态与 `known_deck` 的库存对账缺少这些事件。修复需要把战斗开始事件纳入初始 `PublicHistory`（或让初始库存携带状态），属结构改动，本轮未做；该遭遇继续排除在准入集之外。
- 回归见下；仍不启动正式训练。

### 步骤 31（2026-10-18）初始公开历史与准入 76（P3t）

- 战斗开始阶段的卡牌状态事件（affliction/降级/生成状态）现在进入初始 `PublicHistory`：`make_scenario` 在遭遇构建前标记 all-content，adapter 只保留状态类事件、丢弃初始手牌抽牌事件，保证“初始手牌已在初始状态中”的约定不被破坏。
- 同签名变体的候选扩展：`move_from_intents` 在规范记录之外同时考虑同签名变体的后继（修复重复 UNLOAD/THRASH 的意图唯一性）。
- 保留手牌前缀与实际不一致时（回合末效果先移除了卡牌）改为忘记已知位置，不再误报。
- 结果：鲁棒性 **76/76 全部稳定**（globe head 恢复）；生成器准入 **76** 并重新冻结配置/协议；新协议验证集 **64/64、0 契约拒绝**（mean V7 utility 0.291、0 非法动作）；parity 仍 76 + 2 采样 + 1 专用契约 + 2 待补。
- 初始策略诊断（新协议 16 配方）：network-only **0.109** → MCTS-8 **0.347**，配对增益 **+0.212**（8 正/2 负/5 平）；MCTS 侧 1 局因 turret operator 粒子能力恢复差异被拒绝（逐条记录）。
- 回归 **1203 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 32（2026-10-18）零值力量恢复与 MCTS 诊断全通过（P3u）

- 根因：`foundation.restore` 会先移除所有敌人 STRENGTH 力量，只在 `strength` 非零时重建；当引擎保留一个 0 值 STRENGTH（如 Turret Operator 的临时增益耗尽）时，粒子会丢失该公开能力，导致 MCTS 采样报“Particle does not reproduce the root”。
- 修复：all-content 下按槽位的公开 `powers` 精确恢复（含 0 值与负值），旧内容路径不变。
- 复评：16 配方 network-only 与 MCTS-8 均 **16/16 完成、0 契约拒绝**；mean V7 utility **0.109 → 0.353**，配对增益 **+0.244**（9 正/2 负/5 平）。完整验证集仍 **64/64、0 拒绝**。
- 回归 **1203 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 33（2026-10-18）全量诊断与搜索侧契约收敛（P3v）

- 全量 64 配方诊断（初始 XS）：network-only **64/64、0 拒绝**，胜率 62.5%、mean V7 0.365；MCTS-8 **60/64**，胜率 68.3%、mean 0.540；共同 60 配方配对增益 **+0.131**（20 正/14 负/26 平）。
- 搜索侧修复：零值 DEXTERITY 的公开顺序校验；粒子恢复按公开行顺序重建 basic_statuses；ALL_CONTENT 的 **Purity 多选（位掩码）** 契约（含 `public_choice_mask`）；`is_set_choice` 对 `_pending_play` 的防御性访问。
- MCTS 剩余 4 个拒绝全部记录：3 个主敌人移除（gremlin_merc/axebots，需移除/召唤预算契约）与 1 个 knights_elite 粒子卡牌库存差异；网络侧不再有拒绝。
- 回归 **1203 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 34（2026-10-18）ALL_CONTENT Purity 掩码测试与 knights 库存根因（P3w）

- 新增 1 项测试锁定 ALL_CONTENT 的 Purity 原子集掩码：`is_set_choice` 识别、`public_mask` 给出位掩码、`_pending_play` 缺失时防御性返回 False。
- `knights_elite` 的 MCTS 拒绝根因定位：粒子模拟后 5 张卡在消耗堆呈 `hexed` 状态，而公开历史中的 5 条 `card_state_change` 未能让库存包含这些状态（口径/时机差异），属粒子路径的卡牌状态记账缺口；网络路径正常。未在本轮改动（避免影响既有 affliction 语义）。
- 回归 **1203 项通过（1 xfailed）**。仍不启动正式训练、不宣称学习增益。

### 步骤 35（2026-10-18）预算 8 吞吐实测与运行手册（P3x）

- 采集吞吐（8 局、预算 8、max_turns 6）：单 worker **58.5 s**，2 workers **26.6 s**（2.2×）。
- 据此估算：4×8 正式配置约 2–3 分钟采集 + 4 次 64 配方验证（~17 s/次）与 4 次更新；冻结的 8×48 预算约 **25 分钟**（2 workers）。
- 新增 `docs/AZ_ALL_XS_RUNBOOK.md`：preflight / smoke / 正式命令、输出字段、resume、测试集门槛、已知 4 个搜索侧拒绝与结果解读规则。
- 本轮仅文档与测量，无代码改动；正式训练仍未启动。

### 步骤 36（2026-10-18）搜索预算稳定性诊断（P3y）

- 新增 `scripts/diagnose_all_xs_budget.py`：在 8 个验证配方的同一公开状态上比较预算 8 与 32 的动作/目标。
- 结果：111 次决策，动作一致率 **78.4%**（逐局 66%–100%）；平均目标熵 0.849（8）vs 1.059（32）nat；耗时 175 s。
- 解读：预算 8 的目标大体稳定但仍有噪声；如需更稳目标可将 `budget` 提到 16/32，采集时间约线性增长（预算 8 实测 7.3 s/局）。
- 本轮仅新增诊断脚本与证据文件，无核心代码改动；正式训练仍未启动。

### 步骤 37（2026-10-18）主敌人召唤/胜利口径调查（未落地，回滚）

- 调查 `gremlin_merc`/`axebots` 的 MCTS 拒绝：引擎会追加**没有 Minion 力量**的召唤物（如 Gremlin 小怪），公开账本按“无 Minion 即 primary”把它们记成 primary + spawned，触发预算契约拒绝。
- 进一步发现原生胜利口径是**初始名单**：Gremlin Leader 死亡时仍存活的召唤物不阻止胜利；而搜索的 cutoff 估值要求“整份名单阵亡”。
- 尝试按“初始 primary 计预算、胜利看初始名单、cutoff 看整份名单”改造 `enemy_lifecycle`/`summon`/`all_content`，可修复 2/3 配方，但 `gremlin_merc` 的 0036 仍出现账本 spawned 标记丢失导致的口径冲突；为避免在未完全验证前改动奖励契约，**已回滚**（3 个配方维持记录在案的拒绝）。
- 结论：需要单独的“召唤 primary/初始名单预算”契约；本轮无代码改动。

### 步骤 38（2026-10-18）训练配方去重（48 局不再重复 16 个配方）

- 发现 `training_recipes` 在 `episodes > MAX_TRAINING_JOB(16)` 时按 `episode % 16` 取 job，导致冻结计划的每轮 48 局实际只有 **16 个不同配方**（后两批完全重复）。
- 修复：job 不变，超出 16 的批次按 `(iteration + 8 * (episode // 16)) % 32` 偏移 master；48 局现在得到 **48 个不同 scenario_id**，`episodes ≤ 16` 时配方与之前完全一致（4×8 命令不受影响）。
- 新增 1 项测试；runner 套件 **18 项通过**；回归见下。仍不启动正式训练。

### 步骤 39（2026-10-18）冻结训练计划唯一性测试（P3z）

- 新增测试：按冻结计划（8 轮 × 48 局）生成的全部 scenario_id 共 **384 个且互不重复**，锁定上一轮的去重修复。
- runner 套件 **19 项通过**；本轮无核心代码改动，正式训练仍未启动。

### 步骤 40（2026-10-18）结果报告生成器（P4a）

- 新增 `scripts/summarize_all_xs_run.py`：从 `report.json` 生成 markdown 报告（provenance、基线、每轮损失/效用/配对增益与 CI、目标统计、最弱遭遇、拒绝清单、测试门槛与阅读规则）。
- 新增 2 项测试（完整报告字段、空历史容错）；运行手册补充第 7 节渲染命令。
- 本轮不启动训练；正式训练仍需授权。

### 步骤 41（2026-10-18）Hexed 的 Ethereal 入账顺序修正（P4b）

- 发现 `HexPower.afflict_card` 先调用 `card.afflict('hexed')` 记录状态、再直接给卡牌加 `ethereal` 关键字，导致公开事件的 new state 缺少 Ethereal，而卡牌可见状态包含它（Hexed 隐含 Ethereal）。
- 修正为先加关键字、再记录 affliction，使事件与可见状态一致；全量内容/召唤/multi/morph 套件 **3568 项通过**（仅 2 项既有 fogmog 失败）。
- 复评：鲁棒性仍 **76/76**、parity 仍 **76 + 2 采样 + 1 专用 + 2 待补**，准入与协议不变。
- `knights_elite` 的 MCTS 拒绝仍未解决（剩余差异在 Hex 移除事件的卡牌跟踪上），已记录；本轮不启动训练。

### 步骤 42（2026-10-18）管线冒烟与 resume 复验（P4c，仅管线证据）

- 冒烟（2 局、1 次更新、预算 2、2 workers）：采集 3.6 s、更新 1.0 s、验证 15.9 s；64/64 验证、0 拒绝；对初始基线配对增益 **−0.045 [−0.092, −0.002]**（1 次小更新后略降，符合预期，不构成学习结论）。
- `--resume` 扩到 2 轮：从 `iteration-000.pt` 续跑、replay 23→45、基线证据继续生效；第 2 轮配对增益 **−0.049 [−0.116, 0.010]**。
- 结论：近期 choice/curriculum/hex 改动后端到端与恢复路径均正常；仍不启动正式训练、不宣称学习增益。

### 步骤 43（2026-10-18）knights 粒子 Hexed 库存差异的精确根因（P4d，未改代码）

- 逐事件对照后确认：公开历史里已有 5 条 `card_state_change`（hexed→null，Hex 力量移除时清除），但粒子世界的**消耗堆卡牌仍是 hexed**；`card_memory.inventory` 因此比可见状态少 5 个 hexed 状态而报错。
- 也就是说：粒子的卡牌恢复重放了初始 hex 事件，却没有把后续的清除事件应用到已进入消耗堆的卡牌；这是粒子恢复路径（而非 Hex 力量本身）的缺口。
- 本轮未改动代码（改动会触及 EXPANSION/all-content 的恢复语义，需要单独验证）；`knights_elite` 继续作为已知 MCTS 边界记录。

### 步骤 44（2026-10-18）粒子 Hex 跟踪恢复尝试（已回滚）

- 尝试在 `power_memory.restore` 中把已处于 hexed 的卡牌补入 HexPower 的私有跟踪列表，使力量移除时能清理它们。
- 结果：原始库存差异消失，但紧接着出现 `Changed card state absent from public inventory`（清除事件的 old state 不在库存中）——说明还有第二处状态事件口径不一致；为避免半修复，已回滚。
- `knights_elite` 仍为 1 个记录在案的 MCTS 边界（网络路径 64/64 正常）；本轮无代码改动。

### 步骤 45（2026-10-18）运行日志落盘（P4e）

- `main` 默认把进度行同时写入 `<out>/run.log`（UTF-8，追加），`--log-file` 可覆盖；stdout 行为不变。
- 新增 1 项测试；runner 套件 **20 项通过**；preflight 仍 `ready=true`、回归 **1206 项通过（1 xfailed）**。
- 仍不启动正式训练。

### 步骤 46（2026-10-18）状态总览生成器（P4f）

- 新增 `scripts/report_all_xs_status.py` 与生成的 `docs/AZ_ALL_XS_STATUS.md`：从冻结证据（config/protocol SHA、准入/鲁棒/生成器审计、初始策略诊断、预算诊断）与安全 preflight 汇总出唯一状态文档。
- 内容包含：冻结版本、覆盖（76/76 鲁棒、76 准入、146 卡池、训练抽样覆盖）、三套 split 的 preflight、先验 vs MCTS 诊断与配对增益、预算稳定性、已知 MCTS 拒绝、命令与诚实性规则。
- 新增 1 项测试（关键字段/数值必须在场）；本轮不启动训练。

### 步骤 47（2026-10-18）确认“召唤 primary”是显式契约拒绝（P4g）

- 复查 `tests/test_az_enemy_lifecycle.py`：`test_invalid_or_unsupported_states_rejected` 明确把 `spawned=True` 的 primary 列为应拒绝状态，32 项生命周期测试全通过。
- 结论修正：gremlin/axebot 的 3 个 MCTS 拒绝不是实现 bug，而是**有意为之的旧契约**；放宽需要新生命周期版本（如 `primary-roster-hp-v6`：初始名单计预算、召唤 primary 只参与胜利判定）并重新冻结奖励契约——属需要用户/规格确认的设计变更。
- 因此当前 4 个 MCTS 边界 = 3 个显式契约拒绝 + 1 个粒子恢复缺口；本轮无代码改动。
