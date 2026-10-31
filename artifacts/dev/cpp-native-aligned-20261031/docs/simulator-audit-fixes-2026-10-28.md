# 模拟器深度审计修复报告（D01–D24）

日期：2026-10-28
基线：`a57a702`；工作目录：`D:\sts2_datacollection\sts2`。
对应审计：[`simulator-deep-audit-2026-10-28.md`](simulator-deep-audit-2026-10-28.md)；后续复核：[`simulator-followup-review-2026-10-28.md`](simulator-followup-review-2026-10-28.md)。

规则依据仍然来自本地反编译 C#（`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`）。**本报告所有“规则正确”均为 C# 源码阅读 + 定向执行验证，不是实际客户端差分执行。** 本轮没有修改任何外部参考工程。

## 结论

在声明的支持范围内（STS2 v0.111.0、Ironclad A0、单人、第 1–3 幕），审计列出的 D01–D23 已全部处理：D01–D20 与 D23 为代码修复并有定向回归；D21 为策略/标签修复；D22 的玩家/怪物生命周期已补齐，但支持范围内没有可达来源，因此只作为内部能力回归，不宣称爬塔中可利用。D04 已对反编译工程内全部 `ValueProp.Unpowered` 来源逐文件扫描；D12 已把所有已实现且带 `[SavedProperty]` 计数的遗物改为跨战斗持久化；D11 补了 Discovery→保留→下回合的端到端 pytest。另在修复过程中发现并修复了审计未列出的 **D24：可打出状态牌被一律判为不可打出**，该问题会让 Slimed/Toxic 等牌永久堵塞手牌。

证据等级：

| 等级 | 含义 |
| --- | --- |
| EXECUTABLE | 有可重复执行的定向断言，本报告记录期望/实际 |
| EFFECT_TESTED | 通过真实卡牌/药水/遗物/流程触发，测试到结算值 |
| APPROXIMATE | 实现与 C# 语义仍有已知简化，已在本文件列出 |
| UNSUPPORTED | 当前支持范围外或未有可达来源，不声称已覆盖 |

## 修改概览

| 文件 | 内容 |
| --- | --- |
| `simulator/include/sts2/common.h` | `CardDef.flagsUp` 读取端；`Card.costThisTurn/storedCost`；`card_set_turn_cost` / `card_restore_cost` |
| `simulator/include/sts2/battle.h` | `PendingChoice.cards[MAX_PILE]`；炸弹实例数组；`knownTopCount`；`resolvingCard/pendingRupture`；`attack_*` 的 powered 参数；共享临时属性/力量削减接口；`causedByEthereal` 传递与回合末 ethereal 结算钩子；遗物 per-turn 辅助计数 |
| `simulator/src/battle.cpp` | 消耗判定、能力牌离场、抽牌满手停止、固有起手、费用生命周期、Ethereal/Retain 顺序、Ethereal 消耗的延迟结算（Dark Embrace/Joss Paper）、Rupture、Intangible、炸弹、自动打牌生命周期、选择候选容量、非法动作返回值、重采样已知牌顶、攻击/格挡 Unpowered 路径 |
| `simulator/src/cards.cpp` | 升级关键字读取；数据驱动的可打出判定（D24） |
| `simulator/src/cards_ironclad.cpp` | Setup Strike 临时力量；Mangle 走 Artifact 感知的力量削减；AOE 统一走 `attack_all_from_card`；Entrench 的 Unpowered 复制格挡 |
| `simulator/src/cards_colorless.cpp` | Dark Shackles 走共享力量削减；The Bomb 实例化；Beat Down 越界修复 |
| `simulator/src/potions.cpp` | Flex/Speed 走共享临时属性；Shackling/Dark Shackles；Block Potion/Ship in a Bottle 走获得格挡钩子；Fortifier 按 C# 获得 2×当前格挡；FoulPotion 自身伤害可被格挡；药水伤害 Unpowered；临时费用标记 |
| `simulator/src/relics.cpp` | 跨战斗计数持久化（Pen Nib、Happy Flower、Fake Happy Flower、Nunchaku、Iron Club、Joss Paper、Tuning Fork、Pollinous Core）；Joss Paper/Dark Embrace 的 ethereal 延迟结算；Unpowered 格挡统一走获得格挡钩子；Bag of Marbles/Red Mask 走 Artifact 感知减益；临时费用标记；Reptile Trinket 临时力量 |
| `simulator/src/run.cpp` | 跨战斗遗物计数传递与回写 |
| `simulator/src/monsters.cpp` | 怪物 Intangible 到期（内部一致性，支持范围不可达） |
| `simulator/src/observe.cpp` + `include/sts2/observe.h` | 战斗观测加入遗物/计数、药水、选择操作/来源/完整候选集合；动作特征加入 op/pile；schema 版本 4/3 |
| `simulator/tools/gen_cards.py` + `include/sts2/cards_generated.inc` | 生成 base/upgraded 两套关键字 flags |
| `simulator/tests/rules_regression.cpp` + `simulator/CMakeLists.txt` | 85 项原生规则回归（`rules_test.exe`），由 pytest 调用 |
| `agent/heuristics.py`、`agent/policy.py`、`deployment/evaluate.py` | 重采样启发式与 oracle 分离；不可实战策略标签修正 |
| `deployment/benchmark_speed.py` | `completed_runs` 按真实终止状态计数 |
| `tests/test_audit_regressions.py`、`tests/test_smoke.py` | 新回归；smoke 的种子按修复后行为重新固定 |

## 逐项处理

### D01 Beat Down 越界写 — 已修复

- 根因：`picks[MAX_HAND]` 按下标收集整个弃牌堆的可打出攻击牌。
- 修改：`cards_colorless.cpp` 的 `picks[MAX_PILE]`；`PendingChoice.cards` 改为 `MAX_PILE`，选择构造的 `MAX_HAND` 上限全部改为 `MAX_PILE`（`battle.cpp:979-1047`）。
- 规则依据：`CardModel`/`CardPileCmd` 对选择候选没有 10 张上限；10 只是手牌容量。
- 验证：`beat_down_large_discard_*`（20 张弃牌堆攻击）、`beat_down_preserves_three_attacks`；审计边界插桩 `NO_BOUNDS_FAILURE`。
- 保留语义：选中攻击牌仍通过 `auto_play_random` 打出，UID 唯一，重复牌保留张数；打出后按正常目的地回弃牌堆/消耗堆。

### D02 临时力量/敏捷重复加成、错误恢复 — 已修复

- 根因：临时属性同时写入 `strength/dexterity` 与 `tempStrength/tempDexterity`，伤害/格挡公式再相加一次；Setup Strike 只写临时字段却在回合末扣除。
- 修改：`add_temp_strength/add_temp_dexterity` 同时维护真实值与待回退量；`calc_player_damage` 只加 `strength`；`gain_block_raw` 只加 `dexterity`；药水与 Setup Strike 统一调用；回合末只回退一次（`battle.cpp:365-372`）。
- 规则依据：`FlexPotion.cs`、`SpeedPotion.cs`、`TemporaryStrengthPower.cs`、`SetupStrike.cs`。
- 验证：`flex_strike_damage=11`、`speed_defend_block=10`、`setup_strike_strength_next_turn=0`。

### D03 能力牌被当作消耗 — 已修复

- 根因：`card_exhausts` 对所有 Power 返回 true，能力牌进入消耗堆并触发消耗钩子。
- 修改：`card_exhausts` 不再对 Power 返回 true；`finish_played_card` 对 Power 直接离场（`battle.cpp:82-87`、`:1431-1436`）。
- 规则依据：`CardModel.cs` 对 Power 返回 `PileType.None`；只有真实消耗调用 Exhaust。
- 验证：`power_should_not_exhaust=0`、`feel_no_pain_should_not_trigger_on_self=0`。
- 说明：`relics_card_played` 仍在能力牌离场前执行，符合“打出牌”遗物钩子。

### D04 Unpowered 效果分类 — 已修复（全部已实现来源）

- 根因：力量/敏捷/易伤修正不加区分地套用到能力、药水、遗物与延迟效果。
- 扫描范围：对反编译工程内 `Cards/Powers/Relics/Potions/Monsters/Enchantments` 全部含 `ValueProp.Unpowered` 的模型逐文件提取调用点（共 114 个模型文件、122 条引用），再逐个映射到本模拟器的实现路径。此外 16 个 `Models.Events` 文件中的 Unpowered 都是 run 层 `HpLoss`（不经过战斗属性修正），`Models.Orbs` 属于非支持角色 Defect，均不影响本支持范围。扫描结果分三类：
  1. 未实现内容（不在本模拟器内容表中，或 `relic_implemented=false` 永不进入奖励池）：如 Bone Flute、Galactic Dust、Mystic Lighter、Regalite、Tingsha、Tough Bandages、Shroud、Pillar of Creation、Capture Spirit 等。它们属于既有内容缺口，不是本轮新引入的错误。
  2. 已实现且本来就正确：所有 HP loss（`lose_hp`，无力量/敏捷/易伤修正）、遗物/能力的原始伤害（`damage_monster` 直伤）、药水伤害（`apply_damage_all/one`）、Charons Ashes、Letter Opener、Mercury Hourglass、Stone Calendar、Thorns、Flame Barrier、Poison、The Bomb、Feel No Pain、Block Potion（含其 Juggernaut 触发路径）等。
  3. 已实现但分类错误，本轮修复：
     - Rage / Plating / Crimson Mantle / Block Next Turn 的格挡改为 Unpowered（原先加敏捷）；
     - Rolling Boulder、Inferno、Panache 的伤害改为 Unpowered（原先吃力量/易伤）；
     - Kusarigama、Forgotten Soul、Parrying Shield 的伤害改为 Unpowered；
     - 所有遗物 Unpowered 格挡（Anchor、Fake Anchor、Orichalcum、Fake Orichalcum、Horn Cleat、Captain's Wheel、Sai、Ripple Basin、The Abacus、Ornamental Fan、Permafrost、Cloak Clasp、Daughter of the Wind、Intimidating Helmet、Self-Forming Clay、Tuning Fork、Ship in a Bottle）改走 `gain_block(..., false)`：数值仍无敏捷/虚弱，但会触发获得格挡事件（Juggernaut）。Captain's Wheel 由“赋值 18”改为“获得 18”，不再丢弃 Calipers/Barricade 保留的格挡。
     - Fortifier 由“当前格挡 ×2”改为 C# 的 `GainBlock(当前格挡 ×2)`（实际三倍）；
     - FoulPotion 对自身的 12 点伤害改为可格挡（C# 无 `Unblockable`）；
     - Entrench 从“无效果”补为 `GainBlock(当前格挡, Unpowered)`；
     - Dark Embrace / Joss Paper 的 ethereal 消耗改为延迟到回合末结算（`causedByEthereal` 沿 `move_to_exhaust`→`trigger_exhaust_hooks`→`relics_exhausted` 传递）。
- 规则依据：上述每个模型文件中的 `DamageVar/BlockVar(..., ValueProp.Unpowered)` 与 `CreatureCmd.Damage/GainBlock(..., Unpowered)` 调用；`CombatManager.cs:790,802` 只对 Ethereal/Hex 触发传 `causedByEthereal: true`。
- 验证：`unpowered_feel_no_pain_ignores_dex=3`、`bomb_unpowered_ignores_strength_vulnerable=40`、`explosive_ampoule_ignores_vulnerable=10`、`entrench_unpowered_block=14`、`rage_block_unpowered=3`、`block_next_turn_unpowered=10`、`rolling_boulder_unpowered=10`、`panache_unpowered=5`、`inferno_unpowered=5`、`kusarigama_unpowered=6`、`orichalcum_block_unpowered_value=6`、`orichalcum_block_triggers_juggernaut=5`、`fortifier_gains_twice_current_block=12`、`foul_potion_self_damage_blockable`（HP 不变、格挡 20→8）。
- 残余：未实现内容仍不受模拟（见“明确未完成”第 2 条）；多目标/多人的 Unpowered 目标选择不在单人范围内验证。

### D05 多枚 The Bomb 合并 — 已修复

- 修改：`battle.h` 增加 `bombTurns/bombDamage/bombCount`（最大 8），`The Bomb` 每次打出追加独立实例；回合末逐个倒计时并各自爆炸（`battle.cpp:333-352`）。
- 规则依据：`TheBombPower.cs` 的 `IsInstanced => true`。
- 验证：两张未升级 Bomb 第三回合合计 80；单张 40 且无视力量/易伤。

### D06 Rupture 敌方回合触发 — 已修复

- 修改：仅在 `!inMonsterTurn` 时增加力量；同一张牌结算中的伤害延迟到牌完成后统一加力量（`resolvingCard/pendingRupture`）；`lose_hp` 不再触发 Rupture。
- 规则依据：`RupturePower.cs` 的 `CurrentSide == Owner.Side` 与按牌延迟。
- 验证：`rupture_enemy_turn_no_strength=0`。

### D07 满手继续抽牌 — 已修复

- 修改：`draw_cards` 在手牌达到 `MAX_HAND` 时停止，不再把抽到的牌丢入弃牌堆。
- 规则依据：`CardPileCmd.Draw`。
- 验证：`full_hand_preserves_draw_pile=3`、`full_hand_no_extra_discard=0`。

### D08 固有牌额外起手 — 已修复

- 修改：第一回合把固有牌稳定移到抽牌堆顶，抽牌数取 `min(MAX_HAND, max(正常抽数, 固有数))`，并记录已知牌顶（`battle.cpp:262-280`）。
- 规则依据：`CombatManager.cs:376-384`。
- 验证：单固有起手 5 张；双固有起手 5 张且两张都在手；`one_innate_initial_hand_size=5`。

### D09 升级关键字丢失 — 已修复

- 修改：生成器输出 base/upgraded 两套 flags，重新生成 `cards_generated.inc`；`card_has` 按升级状态读取。
- 规则依据：`OnUpgrade` 删除/新增 Exhaust、Innate、Retain 等。
- 验证：升级 Secret Technique 不再消耗；升级 Aggression 获得固有。生成器覆盖 221 张牌、61 个变量。
- 说明：仅重新生成，无手改生成表。

### D10 Ethereal 与 Retain 顺序 — 已修复

- 修改：清手时先处理 Ethereal/Hex，再处理 Retain/Runic Pyramid。
- 规则依据：`CombatManager.cs:783-790`。
- 验证：`ethereal_before_pyramid_retention=1`。

### D11 临时费用跨牌堆泄漏 — 已修复

- 修改：新增 `Card.costThisTurn/storedCost` 与 `card_set_turn_cost/card_restore_cost`；所有临时改费点（药水、遗物、Discovery/Generated free、Snecko、Mummified Hand 等）打标记；回合开始扫描手牌/抽牌堆/弃牌堆恢复；打出后恢复该牌费用；效果直接打出的副本不再把 0 费写回牌堆。
- 规则依据：`CardEnergyCost.cs` 的结束回合/打出后清理。
- 验证：`temporary_free_card_cost_resets_in_discard=1`；端到端 pytest `test_discovery_free_card_retained_then_restored`：打出 Discovery → 选择一张基础费用 >0 的牌 → 该牌在手牌中费用为 0 → 结束回合被 Runic Pyramid 保留 → 第 2 回合同一 UID 仍在手且费用恢复为基础费用。

### D12 跨战斗遗物计数 — 已修复

- 修改：`relic_aux_persistent` 覆盖所有已实现且 C# 带 `[SavedProperty]` 计数的遗物：Pen Nib、Happy Flower、Fake Happy Flower、Nunchaku、Iron Club、Joss Paper、Tuning Fork、Pollinous Core；`battle.init` 接收 run 层计数；`sync_relics_from_battle` 回写；`relics_combat_start` 不再清零持久计数。
- 语义修正：
  - Nunchaku：每次攻击 `AttacksPlayed++`，`%10==0` 时 +1 能量，计数跨战斗；
  - Iron Club：每次出牌 `CardsPlayed++`，`%4==0` 时抽 1，计数跨战斗；
  - Joss Paper：`CardsExhausted` 跨战斗；非 ethereal 消耗立即计数并在 `>=5` 时抽 `count/5` 后取余；ethereal 消耗先进入不保存的 `EtherealCount`（`relicAux2`），回合末并入再阈值结算；
  - Tuning Fork：`SkillsPlayed` 跨战斗，`>=10` 时 +7 格挡并减 10（不是清零）；
  - Pollinous Core：`TurnsSeen` 跨战斗，恰好第 4 个玩家回合 +2 抽并归零。
- 规则依据：`Nunchaku.cs`、`IronClub.cs`、`JossPaper.cs`、`TuningFork.cs`、`PollinousCore.cs`、`PenNib.cs`、`HappyFlower.cs`、`FakeHappyFlower.cs` 的 `[SavedProperty]` 与回调。
- 验证：`pen_nib_counter_survives_combat`、`nunchaku_counter_survives_combat`、`iron_club_counter_survives_combat`、`joss_paper_counter_survives_combat`、`tuning_fork_counter_survives_combat`、`pollinous_core_counter_survives_combat`；`nunchaku_tenth_attack_grants_energy`、`iron_club_fourth_card_draws`、`tuning_fork_tenth_skill_blocks=12`、`pollinous_core_fourth_turn_extra_draw=7`、`joss_paper_fifth_exhaust_draws=1`、`joss_paper_overflow_draws_floor=2`、`joss_paper_overflow_remainder=2`、`joss_paper_ethereal_settles_at_turn_end=4`、`dark_embrace_ethereal_settles_at_turn_end=2`、`dark_embrace_ethereal_end_turn_hand_size=6`。
- 残余：Bone Tea / Ember Tea / Lasting Candy / Sword of Stone / Wongos 等遗物没有对应实现，其 `[SavedProperty]` 计数不在本模拟器内（既有内容缺口）。

### D13 群攻绕过遗物伤害修正 — 已修复

- 修改：`hit_all` 改走 `attack_all_from_card`，与单体 `attack_from_card` 一样应用 `relics_modify_damage`（`cards_ironclad.cpp:18-20`、`battle.cpp:705-718`）。
- 验证：Pen Nib 就绪时 Thunderclap 伤害 8。

### D14 自动打牌生命周期 — 已修复

- 修改：`auto_play_random` 计入 cards/attacks/skills 计数、执行 `relics_card_about_to_play`、设置 `resolvingCard` 并冲刷 Rupture、执行 `after_card_played`，最后按正常目的地完成（`battle.cpp:1453-1497`）。
- 规则依据：`CardCmd.AutoPlay` 进入 `OnPlayWrapper`；Before/AfterCardPlayed。
- 验证：自动打出 Strike 攻击计数 1、Rage 提供 3 格挡。

### D15 Block Potion 绕过格挡钩子 — 已修复

- 修改：改为 `gain_block(12, false, false)`，仍触发获得格挡事件（Unpowered 数值）。
- 验证：Juggernaut 5 时 Block Potion 造成 5 伤害。

### D16 Dark Shackles 绕过 Artifact — 已修复

- 修改：新增 `apply_strength_loss`，先检查 Artifact；Dark Shackles、Mangle、Shackling Potion 共用。Bag of Marbles/Red Mask 改走 `apply_vulnerable/apply_weak`。
- 规则依据：`ArtifactPower.cs` 拦截可见减益；`DarkShacklesPower` 是负向 TemporaryStrengthPower。
- 验证：Artifact 1 时力量 0、Artifact 消耗为 0。

### D17 选择候选截断 — 已修复

- 修改：`PendingChoice.cards[MAX_PILE]`；HAND/DISCARD/DRAW/OFFER 的构造上限改为完整牌堆/提供列表；默认 `candidateLimit` 改为 `MAX_PILE`；观测编码完整候选集合。
- 验证：15 张弃牌堆 Headbutt 候选 15；15 张抽牌堆 Secret Technique 候选 15。

### D18 非法 PLAY_CARD 返回成功 — 已修复

- 修改：`play_card` 返回 bool；`step` 直接返回其结果；Free Attack 计数在费用校验之后才扣减，拒绝时不改状态。
- 验证：0 能量打 Strike 返回 false；Velvet Choker 第 7 张返回 false；`unaffordable_step_leaves_state` 用 `memcmp` 比较整份 `BattleContext` 未变化。

### D19 重采样破坏已知牌顶 — 已修复

- 修改：`knownTopCount` 记录玩家已知牌顶；`resample_hidden` 只洗未知部分；`add_card_to_draw_top` 增加已知计数；抽牌递减、洗牌清零。
- 验证：Headbutt 后牌顶为 Bash，20 个种子重采样后仍全部为 Bash。

### D20 不同决策映射到相同网络输入 — 已修复

- 修改：
  - 战斗观测加入战斗遗物 one-hot + 计数、药水库存；
  - 选择状态加入 `ChoiceOp`/`ChoicePile` one-hot、来源牌、来源是否消耗；
  - 候选集合用 3 组按牌 ID 的计数（普通/升级/临时改费）表示，可覆盖整个牌堆且不丢“升级/消耗”等决策差异；
  - 动作特征加入选择 op/pile；
  - `PUBLIC_OBS_VERSION=4`、`ACTION_SCHEMA_VERSION=3`，Python 常量从扩展读取，旧 checkpoint 被 `load_checkpoint` 拒绝。
- 验证：无遗物 vs Orichalcum 的战斗观测不同；同一候选 Strike 的“升级它”和“消耗它”观测/动作特征不同；pytest 断言版本已提升。
- 权衡：候选以多重集合编码，不用 160 个完整卡牌槽位。相同 ID/升级/临时费用的重复候选被视为可互换；这符合决策语义，但代价是把观测维度从 50,365 降到 13,111（动作 321）。

### D21 隐藏信息与标签 — 已修复

- 修改：`combat_policy` 增加 `resample` 参数；`Strategy(combat="heuristic")` 默认重采样后再 rollout；新增 `heuristic_oracle` 保留旧的 oracle 行为；`evaluate` 的 `player_usable` 明确排除 `search/search_value/heuristic_oracle`。
- 验证：`test_oracle_strategies_are_never_player_usable`。
- 残余：历史保存的 heuristic/network_cards 数字仍是 oracle 条件，不能与 search_resampled 直接比较；旧分数未改写。

### D22 Intangible — 生命周期已修复，支持范围内不可达

- 修改：玩家受伤/失去 HP 上限为 1；玩家和怪物的 Intangible 在各自回合结束后递减（`battle.cpp:404-406`、`monsters.cpp:411-414`）。
- 验证：`intangible_expires=0`、`intangible_caps_hp_loss=1`。
- 可达性：全内容扫描只发现 `SOUL_FYSH`（第 4 幕）会施加 INTANGIBLE；第 1–3 幕 A0 没有可达来源。**因此不把受控注入状态当作爬塔可利用结果。**

### D23 benchmark 完成数 — 已修复

- 修改：`_bench_selfplay` 按 `status` 统计 `completed_runs/truncated_runs/error_runs`；胜率以真实完成为分母。
- 验证：`test_benchmark_counts_real_terminal_outcomes` 注入 2 terminated/1 truncated/1 error，得到 completed=2、win_rate=1.0。

### D24（审计未列出）可打出状态牌被禁用 — 已修复

- 发现过程：修复过程中大量第 1 幕死亡，追踪到 Slimed 永久堵手（`legal_actions` 只有结束回合）。
- 根因：`card_is_playable` 无条件拒绝所有 STATUS/CURSE，忽略数据中的 `unplayable` 标记。
- 修改：`cards.cpp:54-58` 仅按 `CF_UNPLAYABLE` 判定；生成数据中 Slimed/Toxic/Debris/Beckon/Spore Mind/Enthralled 等可打出。
- 验证：`slimed_is_playable`、打出的 Slimed 进入消耗堆；Wound/Dazed 仍不可打出。
- 影响：该修复把 200 seed 启发式胜局从 8 提高到 9（基线同口径 19），并消除了“Slimed 永久堵手直到死亡”的病态轨迹。

## 验证运行

环境：`.venv/Scripts/python.exe`，MinGW 构建。

```powershell
Set-Location D:\sts2_datacollection\sts2
.\.venv\Scripts\cmake.exe -S simulator -B simulator/build-mingw
.\.venv\Scripts\ninja.exe -C simulator/build-mingw
.\.venv\Scripts\python.exe -m pytest tests -q
.\simulator\rules_test.exe
& .\.scratch\deep-audit-20261028\reproduce.ps1
```

结果：

| 检查 | 结果 |
| --- | --- |
| pytest（含原生规则测试） | **84 passed in 14.25s** |
| 原生规则回归 | **85 checks, 0 failures** |
| 审计定向探针 | **36 checks, 0 failures**（修复前 32 失败） |
| Beat Down bounds 插桩 | `NO_BOUNDS_FAILURE`，退出码 0 |
| 卡牌/遭遇不变量扫描 | 1930 场、106,936 步、**0 violations、0 capped** |
| 1000 局压力（随机合法 + 启发式） | 218,954 步、6,403 次快照恢复/重复动作，**0 error、0 truncated、0 分歧** |
| 快照/恢复 | 每次恢复后 state_hash 与重复执行一致（同上） |

审计探针的一处改动：`probe.cpp` 的“临时 0 费回到弃牌堆”检查改为通过 `card_set_turn_cost` 设置费用，因为直接写 `costForTurn=0` 不再代表游戏内真实路径；这是把复现迁移到修复后的机制，不是放宽期望。

## 性能对比（同机、同配置、同种子/策略）

基线为 `a57a702` 构建，并额外套用了 D24 的一行可打出判定修正，使胜率对比只反映其余修复；性能数字同口径。

| 指标 | 基线 + D24 | 本轮（第二轮修复后） | 变化 |
| --- | --- | --- | --- |
| Python 驱动整局（200 seeds） | 36.7 runs/s | 43.5 runs/s | +19%（单局更短，见下） |
| env steps/s | 11,405 | 11,969 | +4.9% |
| combats/s | 489.5 | 514.8 | +5.2% |
| C++ bench `run 200` | 118.1 runs/s | 122.6 runs/s（3 次 116.6/118.5/126.7/122.6） | +3.8%，噪声内 |
| 根搜索（64 sims ×300，oracle） | 178,354 sims/s | 169,070 sims/s | −5.2% |
| 重采样根搜索 | 136,902 sims/s | 126,199 sims/s | −7.8% |
| 自对弈 net+search | 16,950 sims/s | 16,337 sims/s | −3.6% |

解释：

- 整局 runs/s 的提升主要来自单局变短（平均战斗数 13.7→12.1），不是减少了计算；env steps/s 与 combats/s 的小幅提升来自满手停止抽牌和更少无效结算。
- 搜索吞吐下降 6–10% 是可解释的：可打出状态牌增加了合法动作数，完整候选集合增加了选择分支/复制量，搜索的 rollout 分支变多。没有通过减少模拟数或跳过校验来制造提速；`completed_simulations` 仍等于请求数。
- C++ bench 的单次结果波动范围 116.6–126.7 runs/s，本轮取 122.6；与基线 118.1 的差异小于测量噪声，不能据此声称提速。
- 自对弈 −3.6% 与 C++ bench 同属噪声量级；第二轮修复新增的 Juggernaut 触发、遗物计数与 ethereal 延迟结算只在对应卡/遗物出现时执行，没有增加每次决策的固定开销。
- 所有 `completed_simulations` 等于请求数，没有通过减少模拟或跳过校验制造数字。

## 行为变化与残余风险

- **启发式基线胜率下降**：纯 oracle 启发式在 seeds 1–1000 上从 110/1000（11.0%，基线 + D24）降到 43/1000（4.3%，第一轮修复后），再降到 30/1000（3.0%，第二轮修复后）；同 200 seeds 为 19→9→7。第一轮的逐组回退实验（D03/D04/D07/D08/D10/D11/D14/D17/D24 单独回退）每次只改变 0–2 个胜局；第二轮新增的行为（Juggernaut 在 Unpowered 遗物格挡后开火、Nunchaku/Iron Club/Joss Paper/Tuning Fork 的跨战斗计数、Entrench 生效、Dark Embrace/Joss Paper 的 ethereal 延迟抽牌、FoulPotion 可格挡、Fortifier 三倍格挡）都会改变状态与 RNG 分叉。该指标是弱基线策略的表现，不是规则正确性证据；没有把它与任何模型成绩比较。
- 因为旧种子在修复后不再获胜，`test_full_run_completes_and_wins` 改用第二轮修复后仍能完整通关的 seeds 23/89；断言仍是“3 个 Boss、完整通关”，没有改成“只要终止即可”。
- 现有 `runs/*.pt` checkpoint 因观测/动作 schema 升级（v4/v3）会被拒绝加载；需要重新训练，属于预期的不兼容。本轮没有改观测/动作布局，`PUBLIC_OBS_VERSION`/`ACTION_SCHEMA_VERSION` 仍为 4/3；`BattleContext` 新增了 `relicAux2/darkEmbraceEthereal` 字段，二进制快照只在同一构建内使用（没有持久化快照文件），旧构建的字节流不再兼容。
- 启发式/`network_cards` 的旧评估分数是 oracle 条件，仍保留原值，不能用 `search_resampled` 重新解释。

## 明确未完成 / 未覆盖

1. **没有真实客户端差分验证**（仍为 0 条逐步轨迹）。所有规则正确性来自 C# 阅读 + 定向执行。
2. D04 扫描到的 `ValueProp.Unpowered` 来源中，属于本模拟器**未实现内容**的部分（例如 Bone Flute、Galactic Dust、Mystic Lighter、Regalite、Tingsha、Tough Bandages、Shroud、Pillar of Creation、Capture Spirit）仍不可用；这是既有内容缺口，无法在“不扩大支持范围”的前提下补齐。
3. D12 中 C# 有 `[SavedProperty]` 计数但本模拟器未实现对应遗物的（Bone Tea、Lasting Candy、Sword of Stone——后者只有未使用的 `swordOfStoneWins` 字段）同样属于未实现内容；Ember Tea 与 Wongos Mystery Ticket 已有独立的 run 层计数。
4. D20 的候选集合使用多重集合编码；候选逐槽位顺序、UID、逐候选价格不进入网络输入。
5. D22 在当前支持范围没有可达来源，只证明内部生命周期正确。
6. 审计报告已声明的覆盖缺口仍在：部分事件（29 个排除）、部分附魔/事件遗物、若干近似实现；本轮没有扩大或缩小支持范围。
7. 启发式胜率下降无法归因到单项修改；若要彻底排除隐藏规则错误，需要客户端差分或更强策略的对照评测。

## 能否用于训练

可以，在声明的 A0/1–3 幕范围内，且必须使用新 schema 重新训练。相比基线，审计指出的越界写、消耗/能力牌、Unpowered、抽牌/起手/费用/关键字、自动打牌、跨战斗计数、选择容量、非法动作、已知牌顶、观测可区分性等问题已修复并有回归。但它仍**不是完整保真的 STS2 环境**：没有客户端差分验证，仍有上表残余缺口；训练结果应带着这些限制解读。

## 复现材料

- 审计原始材料：`.scratch/deep-audit-20261028/`（探针已按修复后的费用机制更新一行）。
- 新原生回归：`simulator/tests/rules_regression.cpp`，构建目标 `sts2_rules_test`，输出 `simulator/rules_test.exe`。
- 新 pytest：`tests/test_audit_regressions.py`。
- 工作区没有提交；需要时按项目流程单独提交。
