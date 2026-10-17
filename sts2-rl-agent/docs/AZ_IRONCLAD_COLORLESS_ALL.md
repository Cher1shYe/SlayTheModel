# 战士／无色 V5：剩余 19 张单人可执行牌接入

日期：2026-10-17。本轮目标（用户指定）：向“全战士 87 + 全无色 64”推进，并完成 MCTS/粒子重建接入。本批新增 **19 张及升级版**，累计 **139/151**（战士 **87/87**、无色 **52/64**），剩余 **12**。逐牌状态见 [覆盖清单](IRONCLAD_COLORLESS_COVERAGE.md) 与 `ironclad_colorless_coverage.json`。

本批不训练、不读取最终留出集，**不宣称策略学习增益**；验收工程链路与单人语义。

## 接入方式与语义边界

范围仍是单人 Ironclad、无遗物药水、ascension 0。三类牌分别处理，并在覆盖清单 `notes` 列逐张写明：

| 类别 | 牌 | 单人语义 | 验证 |
|---|---|---|---|
| 真实单人机制 | FEED、CORRUPTION、TANK、KNOCKDOWN、TAG_TEAM、GANG_UP、HAND_OF_GREED、GOLD_AXE、BOLAS、THRUMMING_HATCHET、BEACON_OF_HOPE | 伤害/格挡/最大生命/状态/能力/回手按原生规则执行 | 原生行为 + 粒子逐步对照 + MCTS 重建 |
| 多人牌（ANY_ALLY） | DEMONIC_SHIELD、BELIEVE_IN_YOU、COORDINATE、INTERCEPT、LIFT、MIMIC | 单人无合法队友目标，**不可出牌**；描述保留 `ally_required` 条件 | 合法动作表为空；信息状态与粒子不变 |
| 多人牌（ALL_ALLIES） | HUDDLE_UP、RALLY | 可出牌，但所有目标都是队友，**单人无效果**（仅消耗能量/进弃牌堆） | 出牌前后除能量与牌堆外无差异 |
| 战斗外奖励 | HAND_OF_GREED | 20/25 伤害照常；金币属于战斗外进程状态，不进入战斗观测 | 伤害断言；奖励不入编码 |

### 新增机制细节

- **FEED**：击杀时 `gain_max_hp`。`player_max_hp` 从固定 80 放宽为 `80..1080`，公共验证要求 `player_hp <= player_max_hp`；粒子按观测值恢复。
- **CORRUPTION**：新增玩家能力 `CORRUPTION`，描述为“技能 0 费 + 打出后消耗”；费用仍由原生 `modified_card_cost` 决定，能量合法性与手牌状态口径不变。
- **TANK**：新增玩家能力 `TANK`，受强化攻击伤害 ×2；队友 `GUARDED` 在单人不存在。原生实现中该能力 amount 会累加，公共账本按实际引擎累加，注释说明与 C# `StackType.Single` 的差异。
- **KNOCKDOWN / TAG_TEAM**：作为敌人公开状态进入 `foundation.basic_statuses`，附带 `enemy_turn_end` 持续期。KNOCKDOWN 只对“非施加者”的攻击加成，单人下即玩家攻击不受影响；TAG_TEAM 只对“其他玩家”的攻击触发。两者在单人都是可见但无效的减益，照实描述。
- **GANG_UP**：`calc_base + extra × 本回合其他友方对目标的有效攻击次数`；单人无友方，恒为 5/5。升级只改 `extra_damage`，不影响单人伤害。
- **GOLD_AXE**：`calc_base + extra × 本场已出牌数`。粒子重建补回 `_played_cards_combat`（只读公开 `start` 事件计数与卡牌类型）。
- **HAND_OF_GREED**：20/25 伤害；金币奖励属战斗外，不入战斗状态。
- **BOLAS / THRUMMING_HATCHET**：下一次抽牌前回到手牌。原生标记 `combat_vars['_return_before_hand_draw_round']` 不作为卡面状态编码，而是由公开出牌历史推导：本回合每打出一次，就在弃牌堆中最近的同面牌上恢复标记（牌堆顺序影响洗牌结果，因此按“最近打出”而非任意同面牌恢复）。升级版关键词（Hatchet+ 无消耗、BOLAS 变 4 伤）由原生工厂给出。
- **BEACON_OF_HOPE**：格挡分享给队友，单人无队友 → 能力可见、无效果。

## 公开状态、网络与搜索

1. `REGISTRY_VERSION` → `ironclad-colorless-mechanics-v5`：新增操作 `skill_cost_zero`、`skill_exhaust`、`gain_max_hp`、`knockdown`、`tag_team`、`gold`、`return_to_hand`、`ally_guard`，目标 `ally`/`allies`，条件 `ally_required`/`ally_present`。新增词表项只用于描述，执行仍由原生引擎完成。
2. `information_version` → `ironclad-colorless-information-v5`；实体 schema 版本 → `public-entities-ironclad-colorless-v5`（registry 哈希随之变化，旧权重/Replay 不可直接复用）。
3. `CardStatePolicy` 增加 `return_to_hand` 开关：允许回手标记存在但不进入卡面状态；其余卡面字段与 V4 完全一致。
4. 动态动作仍完全由原生合法掩码 + 卡牌描述生成候选，没有新增按 ID 的策略输出头；ANY_ALLY 牌天然没有候选。
5. 粒子重建：新增能力/状态经 `player_abilities`、`power_memory`、`foundation` 恢复；`_played_cards_combat` 与回手标记按公开历史恢复；恢复后 `observe` 与根状态逐字段相等。

## 验证

- 新增 `tests/test_az_ironclad_colorless_all.py`（112 项）：逐牌描述/编码往返、XS 动态 MCTS 重建、粒子轨迹逐步对照（18+1 张 × 基础/升级）、ANY_ALLY 不可出、ALL_ALLIES 空操作、FEED 击杀加最大生命、TANK 双倍受伤、GOLD_AXE 计数、GANG_UP 恒定、CORRUPTION 0 费消耗、回手牌回到手牌、KNOCKDOWN 状态生命周期、HAND_OF_GREED 伤害、BEACON 单人无效、暂缓牌仍拒绝。
- 既有 `test_az_content_expansion.py`（除全量轨迹慢测）、`test_az_player_abilities.py`、`test_az_simple_cards.py`、`test_az_transformer*.py` 回归。
- 覆盖审计脚本升级为 `ironclad-colorless-coverage-v5`，新增 `notes` 列，逐张记录单人语义。

## 明确未完成

剩余 12 张：

- 需要新增公开计数/延迟结算契约（7）：AUTOMATION（每 10 次抽牌 +1 能量）、NOSTALGIA（每回合前 N 张攻击/技能回牌顶）、PANACHE（每 5 张出牌造成伤害）、PROLONG（下回合格挡）、ROLLING_BOULDER（回合开始伤害并递增）、THE_BOMB（倒计时范围伤害）、THE_GAMBIT（受到未格挡强化攻击即死）。
- 范围暂缓（5）：ALCHEMIZE（药水不在战斗范围）、ENTROPY / JACK_OF_ALL_TRADES / SPLASH（跨职业生成池）、HIDDEN_GEM（隐藏抽牌堆身份变异没有公开牌面契约）。

下一步：补齐上述 7 张的公共计数契约，再进入全怪物 MCTS 接入（P2）。
