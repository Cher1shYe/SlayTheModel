# 高速模拟器第四、五轮审计修复报告（2026-10-28）

## 结论

第四轮 30 项定向断言与第五轮 58 项定向断言现已全部通过（审计时分别为 30 项中 23 失败、58 项中 51 失败），
第五轮的 P0 越界、P1 死循环、永久升级费用、玩家/怪物 Power 钩子、伤害结果链、药水工厂和观察
schema 均已按本地 C# 参考实现修复。旧有回归同时保持通过：原生 rules 233 项、第二轮 32 项、
第三轮 41 项、第四轮矩阵 12,532 场、第五轮遭遇扫描 5,340 场 + 整局扫描 300 场、Python 84 项。

本报告不声称“全绿即全部正确”：没有真实客户端逐步差分，随机扫描只验证不变量而非每一步语义；
标为 APPROXIMATE 的古代遗物/事件效果、观察容量上限、200 回合僵局保护等仍在残余风险中列出。

## 环境与版本

- 项目：`D:\sts2_datacollection\sts2`；HEAD `a57a7029b69a85aee13bf38d41efa9597672fad6`，
  本次修复全部位于工作区未提交改动之上；未使用 `reset`、`checkout --`，未覆盖既有未提交内容。
- 权威规则：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`（只读，未修改）。
- C++ 标准：C++17；MinGW `x86_64-w64-mingw32-g++.exe`（16.2.0），`.venv\Scripts\cmake.exe`。
- 测试材料：
  - `.scratch/deep-audit-round4-20261028/`：`probe.cpp`、`matrix.cpp`、`reproduce.ps1` 及结果；
  - `.scratch/deep-audit-round5-20261028/`：`probe.cpp`、`sweep.cpp`、`reproduce.ps1`、
    `timeout_check.py`、本次新增 `capcheck.cpp` 及结果；
  - 依赖 `.scratch/deep-audit-round3-20261028/bounds_handler.cpp`。
  - `.scratch` 为 Git 忽略目录，交接时需整目录复制。
- 本次修复未运行正式训练，未声称新的胜率或吞吐数字。

## 修改文件

| 文件 | 修复内容 |
|---|---|
| `simulator/include/sts2/common.h` | `card_apply_upgrade` 声明（永久升级同步费用） |
| `simulator/include/sts2/battle.h` | `ActivePlay.resultsToDraw/energySpent`、`DamageDealt`、`Monster` 濒死/慢速/无实体状态、回合出牌历史、Automation 实例数组、抽牌剩余量、格挡卡序号、`damage_monster`/`damage_player`/`begin_play` 新签名 |
| `simulator/include/sts2/observe.h` | schema v6/v5；`CARD_FEAT_DIM`、`PUB_COMBAT_BASE`、`PUB_KNOWN_TOP`、`PUB_BOMB_SLOTS` 容量策略 |
| `simulator/include/sts2/relics.h` | 伤害加法/乘法分相接口 |
| `simulator/src/battle.cpp` | 核心：Power 生命周期、伤害/格挡修正顺序、牌堆结果、抽牌钩子、自动出牌限制、怪物 Power 钩子、Hatchet/Aggression/Stratagem/Drum 回合顺序 |
| `simulator/src/cards.cpp` | `card_apply_upgrade` 同时改 `storedCost`/`costForTurn` |
| `simulator/src/cards_ironclad.cpp` | Fiend Fire 快照消耗 + 单次多段攻击命令 |
| `simulator/src/cards_colorless.cpp` | Hatchet 正常进弃牌堆、Brightest Flame、Fisticuffs/Omnislice 结果伤害、Hand of Greed 伤害来源 |
| `simulator/src/relics.cpp` | 变牌池容量、伤害加法/乘法、Vambrace 整卡、Mummified Hand 过滤、永久升级统一入口 |
| `simulator/src/potions.cpp` | Sozu 全路径阻止、Entropic Brew 战斗内工厂与 RNG、Snecko Oil 排除 X 费 |
| `simulator/src/run.cpp` | 战斗外 Brew 不死循环、药水池与 RNG、所有永久升级调用点、快照保留新字段 |
| `simulator/src/events.cpp` | 池数组按枚举容量、永久升级统一入口 |
| `simulator/src/monsters.cpp` | 遭遇池按 `Encounter::COUNT`、Nemesis 回合末切换 |
| `simulator/src/observe.cpp` | 临时力量/敏捷、`freeCombat`/`costThisTurn`、抽牌堆升级拆分、已知牌顶/炸弹槽位 |
| `simulator/tests/rules_regression.cpp` | 新增 ~80 项第四/五轮最小复现与正向对照（总计 233 项） |
| `tests/test_smoke.py` | 规则修正导致 RNG 轨迹改变后重钉获胜种子（148/163），仍要求三 Boss 胜利 |
| `README.md` | 观察维度与 schema 版本同步（17762 / 240 / 325，v6 / v5） |

## 逐项修复

### A. 牌堆结果、消耗与卡实体

**R4-01 Fiend Fire 消耗了触发抽牌后的手牌**
- 根因：`while (handCount > 0)` 边消耗边处理 Dark Embrace 抽进手牌的新牌。
- 修复：`cards_ironclad.cpp` 先快照 `Hand.Cards.ToList()`（含 Fiend Fire 自身），按快照 UID 精确消耗；
  抽牌钩子新进手牌的卡不参与。
- 依据：`Cards/FiendFire.cs` 的 `OnPlay` 快照。
- 回归：`r4_01_fiend_fire_exhausts_initial_only`（3）、`r4_01_fiend_fire_keeps_drawn`（3）。

**R4-02 Fiend Fire 多段只首段吃 Vigor**
- 根因：逐段 `hit` 每次都是独立攻击命令，Vigor 只在第一段消费。
- 修复：消耗完快照后一次 `hit(..., count)`，与 `WithHitCount` 一致；Vigor 只叠加一次。
- 回归：`r4_02_fiend_fire_vigor_all_hits` → `(7+5)*2=24`。

**R4-03 Nostalgia 覆盖消耗、忽略层数、嵌套归属错误**
- 根因：全局布尔 `nostalgiaPending` + 回顶分支优先于消耗判定，无法区分外层/自动打出的子卡。
- 修复：在 `begin_play` 一次性计算该次出牌的结果牌堆（`ActivePlay.resultsToDraw`），条件为
  Nostalgia 层数 > `attackSkillPlaysThisTurn`、Attack/Skill、非消耗/非能力/非强制消耗；
  子卡通过 `auto_play_random` 的 `forceExhaust` 仍强制消耗；层数用已打出次数比较。
- 依据：`Powers/NostalgiaPower.cs`、`Models/CardModel.cs`（结果牌堆在效果前确定）、`Cards/Havoc.cs`（子卡 forceExhaust）。
- 回归：`r4_03_nostalgia_keeps_exhaust`、`r4_03_nostalgia_two_stacks`、`r4_03_nostalgia_havoc_child_exhausts`、
  `r4_03_nostalgia_outer_returns`。

**R4-04 Thrumming Hatchet 离开正常牌堆且保留过期临时费用**
- 根因：`OnPlay` 把卡放进内部返回队列；新回合费用恢复又发生在队列回手之后。
- 修复：`OnPlay` 只攻击，按正常结果进入弃牌堆；`end_player_turn` 轮转上回合出牌历史，
  `start_player_turn` 的 `BeforeHandDraw` 用精确 UID 从任意牌堆召回；召唤前已执行 `card_restore_cost`，
  因此临时 0 费在召回前恢复。
- 依据：`Cards/ThrummingHatchet.cs` 的 `OnPlay`/`BeforeHandDraw`。
- 回归：`r4_04_hatchet_in_discard`（弃牌堆 1）、`r4_04_hatchet_cost_restored`（1 费）。

**R4-05 Hidden Gem 的 replay 跨回合被清空**
- 根因：每回合开始清空手牌 `replay`。
- 修复：Hidden Gem 修改的是 `BaseReplayCount`（本场战斗持久），删除跨回合清理；临时 replay 语义保留在
  其他来源的清除路径。
- 回归：`r4_05_hidden_gem_replay_persists`（2）。

**E1 Hatchet 胜利收尾产生重复 UID**
- 根因：Panache 击杀后 `finish_active_play` 的终局分支既把卡放进返回队列又放进弃牌堆。
- 修复：终局分支优先按正常结果牌堆落位并放弃返回队列；`recall` 与队列均有 UID 去重。
- 证据：`e1_hatchet_terminal_uid` 统计全部五个牌堆中该 UID 的副本数为 1；`e1_hatchet_panache_wins` 确认
  同时胜利。扩展矩阵 seed 726885/726891 由扫描复验（sweep 无 `duplicate_uid`）。

### B. 伤害/格挡修正链

**R4-06 格挡加法/乘法顺序、Unmovable 层数、Vambrace 范围**
- 根因：`gain_block` 先乘后加；Unmovable 用布尔；Vambrace 在第一次 `gain_block` 后即消耗。
- 修复：`gain_block` = (基础 + 敏捷 + 遗物加法) × (Unmovable 2^层) × Frail，最后取整；
  Unmovable 依据本回合第几张产格挡卡（`blockPlayIndex/blockCardPlaysThisTurn`）应用层数；
  Vambrace 状态机 0/1/2：本卡首次触发进入 1，该卡 `AfterCardPlayed` 才置 2（消耗）。
- 依据：`Hooks/Hook.cs`（Additive 先于 Multiplicative）、`Powers/UnmovablePower.cs`、`Relics/Vambrace.cs`。
- 回归：`r4_06_unmovable_doubles_dexterity`（16）、`r4_06_unmovable_two_stacks`（20）、
  `r4_06_vambrace_whole_card`（20）。

**R4-07 Flex Potion 漏触发 Ruined Helmet**
- 根因：临时力量直接改 `strength`，绕过 `StrengthPower` 施加钩子。
- 修复：`add_temp_strength` 先 `add_player_power(STRENGTH, amount)`（因此触发 Ruined Helmet 等
  BeforeApplied 钩子），再记录 `tempStrength` 供回合末扣除；`silent` 仅影响显示。
- 依据：`Powers/FlexPotionPower.cs` → `TemporaryStrengthPower.cs` → `Relics/RuinedHelmet.cs`。
- 回归：`r4_07_flex_triggers_helmet`（10）、`r4_07_flex_helmet_extra_persists`（5）。

**R4-09 Hand of Greed 绕过 Pen Nib**
- 根因：无色卡走 `attack_monster`，缺少卡牌来源，遗物倍率拿不到 `card`。
- 修复：`attack_from_card`，伤害修正链带 `card`；Pen Nib 在其阶段乘 2。
- 回归：`r4_09_pen_nib_hand_of_greed`。

**R4-13 Strike Dummy 加法发生在 Weak 之后**
- 根因：遗物 +3 在 Weak 乘算之后。
- 修复：伤害链拆为 `relics_damage_additive`（Strike Dummy、Miniature Cannon）→ 力量/能力 →
  Weak/Shrink/Vulnerable/Colossus/Slow 乘算 → `relics_damage_multiplier`（Pen Nib）→ floor。
- 依据：`Relics/StrikeDummy.cs`（ModifyDamageAdditive）、`Hooks/Hook.cs` 分相。
- 回归：`r4_13_strike_dummy_before_weak` → `floor((6+3)*0.75)=6`。

**R5-08 Cruelty 易伤倍率**
- 根因：把 1.5×1.5 当加法。
- 修复：易伤倍率 = `1.5/1.75 + cruelty/100`，再整体乘算。
- 回归：`r5_08_cruelty_additive`（10×2.0 = 20）。

**R5-18 Hand Drill 恰好破甲**
- 根因：额外要求 `remaining > 0`。
- 修复：`DamageDealt.blockBroken` 在格挡被打空的那一击即为真，包括恰好归零。
- 回归：`r5_18_hand_drill_exact_break`（易伤 2）；格挡 5 的正向对照保持。

**R5-19 / R5-20 Fisticuffs / Omnislice 按实际伤害结果**
- 根因：按预算伤害计算，未考虑 Intangible、Vigor 等实际结果。
- 修复：`damage_monster` 返回 `DamageDealt{total, unblocked, overkill, blockBroken}`；
  `total = blocked + unblocked`；Fisticuffs 获得 `total + overkill`，Omnislice 以主目标
  `total + overkill` 作为 Unpowered 溅射基数。
- 依据：`Models/DamageResult` 语义、`Cards/Fisticuffs.cs`、`Cards/Omnislice.cs`。
- 回归：`r5_19_fisticuffs_vigor`（12）、`r5_19_fisticuffs_intangible`（1，对照 7）、
  `r5_20_omnislice_intangible`（1）、`r5_20_omnislice_vigor`（13）。

### C. 自动出牌、限制与 X 费

**R4-08 自动打出的 X 费牌未应用 Chemical X**
- 修复：`auto_play_random` 的 X 值 = 当前能量 +（X 费牌且有 Chemical X ? 2 : 0），与手动路径共用。
- 回归：`r4_08_chemical_x_auto`（5 段 25 伤害）。

**R4-12 自动出牌绕过 Velvet Choker**
- 修复：自动路径先执行与手动一致的 `ShouldPlay` 限制（不可打出、Normality、Choker 6 张）。
- 回归：`r4_12_auto_choker_limit`（0 伤害）；手动拒绝对照保持。

**R5-07 FreeAttack 错误过期、破坏 X 费身份**
- 根因：回合末清除 FreeAttack；把 X 费改成固定 0 费。
- 修复：FreeAttack 跨回合保留，仅在实际打出 Attack 后消费；X 费仍按
  `CardEnergyCost.GetAmountToSpend` 支付当前能量（FreeAttack 只免"费用检查/支付"之外的限制，
  不把 CostsX 改成固定 0）。
- 回归：`r5_07_free_attack_survives`、`r5_07_free_x_damage`（15）、`r5_07_free_x_spends_energy`（0）。

**R5-17 Intimidating Helmet 看实际资源消耗**
- 修复：`ActivePlay.energySpent` 由 `play_card` 记录（实际扣除，含 X 费全能量），
  `BeforeCardPlayed` 时 `>= 2` 给 4 格挡。
- 回归：`r5_17_helmet_x_spend`（4）、`r5_17_helmet_free_attack_no_block`（0）。

**R5-15 Snecko Oil 把 X 费变成固定费**
- 修复：Snecko Oil 跳过 `cost == -1`（CostsX）的卡。
- 回归：`r5_15_snecko_keeps_x`（-1）。

**A1 Snecko Eye 的 Confused 逐张钩子与改费期限**
- 根因：只有 `relics_hand_drawn` 在整手抽完后统一改费，战斗中 `draw_cards` 没有逐张钩子；
  且标记为 `SetThisTurn`。
- 修复：`draw_cards` 对每张抽到的、非 X 费的卡执行 Confused：
  `costForTurn = rng(0..3)`、`costThisTurn = false`（SetThisCombat），并同步 `storedCost`，
  使费用在本场战斗内持续；Snecko Eye / Fake Snecko Eye 共用。
- 依据：`Powers/ConfusedPower.cs` 的 `AfterCardDrawn` 与 `SetThisCombat`。
- 回归：`a1_snecko_cost_not_turn_temporary`；第五轮探针 `snecko_midturn unchanged=3 of=8`
  说明仍有 3 张与改费前同价，属正常随机结果而非未改费。
- 残余：`SneckoEye` 仍在覆盖表中标为 APPROXIMATE（例如与真实客户端的抽牌顺序交互未差分）。

### D. 死亡时机与其余卡牌

**R4-10 The Gambit 把自伤当攻击且延迟死亡**
- 修复：`damage_player(..., poweredAttack)` 区分攻击伤害；怪物攻击传 true；自伤/foul potion 传 false。
  Gambit 在未格挡攻击伤害后立即移除能力、置 `hp=0`、`PLAYER_LOSS`，不再等到敌方回合末。
- 回归：`r4_10_gambit_ignores_self_damage`、`r4_10_gambit_kills_now`。

**R5-14 Brightest Flame 扣当前生命错误**
- 修复：先 `maxHp = max(0, maxHp - 1)`，仅当 `hp > maxHp` 才压到新上限。
- 回归：`r5_14_brightest_hp_unchanged`（100/499）、1 HP 时也不扣（`r5_14_brightest_one_hp_maxhp`）。

**R5-16 Mummified Hand 未过滤零费候选**
- 修复：只在 `card_cost > 0` 的手牌中随机；无候选时回退不选。
- 回归：`r5_16_mummified_never_zero_cost`（100 种子 0 次把 0 费 Anger 当目标）。

### E. 永久升级、药水池与 Sozu

**R5-01 变牌池越界（P0）**
- 根因：`CardId pool[128]` 而合格卡数超过 128。
- 修复：所有变牌池按 `CardId::COUNT`（及其它池按 `RelicId::COUNT`/`PotionId::COUNT`/`Encounter::COUNT`）
  定长；遍历有上限。
- 证据：`probe.exe transform-bounds` 在 `-fsanitize=bounds -fno-sanitize-recover=bounds` +
  自定义 handler 下 `ENTER add Astrolabe / RETURN add Astrolabe / exit=0`，stderr 0 字节（此前
  `BOUNDS_FAILURE ... index=128`，进程退出 77）。
- 回归：`r5_01_astrolabe_completes`（整局 Astrolabe 不终止）。

**R5-02 Sozu 不一致与战斗外 Brew 死循环（P1）**
- 根因：`add_potion` 被 Sozu 静默拒绝，`while (potionCount < slots)` 数量不变导致永不返回；战斗内路径
  又反向给 3 瓶。
- 修复：`add_potion`/`gain_random_combat_potion`/所有整局获得药水入口在 Sozu 下直接失败；
  Entropic Brew 以 `TryToProcure` 失败为 break；战斗内外一致。
- 证据：`timeout_check.py` 现为 `COMPLETED exit=0 / ENTER sozu-brew / RETURN sozu-brew`
  （3 秒限制内返回；修复前超时）。`r5_02_sozu_blocks_brew`、`r5_02_sozu_blocks_alchemize`。
- 依据：`Relics/Sozu.cs.ShouldProcurePotion`、`Potions/EntropicBrew.cs`。

**R5-03 永久升级只改标记不改费用（P1）**
- 根因：营火/蛋/事件/遗物各自只写 `upgraded=true`。
- 修复：新增 `card_apply_upgrade`（`cards.cpp`）统一改 `storedCost` 与（非临时改费时的）`costForTurn`；
  战斗内 `upgrade_card` 委托同一函数；所有调用点（run/events/relics/战斗内 Razor Tooth 等）改用该入口。
- 回归：`r5_03_rest_upgrade_cost`（Corruption 2）、`r5_03_rest_cost_in_battle`（下一场手牌仍 2）、
  `r5_03_egg_upgrade_cost`（Havoc 0）。
- 依据：`Cards/Corruption.cs`、`Cards/Havoc.cs.OnUpgrade`、`Models/CardModel.cs` 升级流程。

**R5-26 Entropic Brew 战斗内池/稀有度/RNG**
- 根因：战斗内按 `combatGen` 均匀抽选并用通用 `rng`，过滤掉了 Fruit Juice；`potionRng` 不前进。
- 修复：战斗内也调用 `random_potion_out_of_combat(potionRng)`：rare 10% / uncommon 25% / common 65%，
  铁卫池，无 `CanBeGeneratedInCombat` 过滤，使用 `potionRng`（对应 CombatPotionGeneration）。
- 回归：`r5_26_brew_uses_potion_rng`；第五轮探针 6,000 瓶采样 rare=602（~10.0%）、Fruit Juice=36。
- 依据：`Factories/PotionFactory.cs`、`Potions/EntropicBrew.cs`。

### F. 玩家 Power 生命周期（R5-04—R5-13）

| 项 | 根因 | 修复 | 回归 / 依据 |
|---|---|---|---|
| R5-04 Grapple | 被当成攻击加伤；缺获得格挡钩子；不在 debuff 白名单 | `trigger_block_hooks` 对带 Grapple 的怪物造成 Unpowered 伤害；`power_is_debuff` 含 GRAPPLE（Artifact 拦截）；敌方回合末移除 | `r5_04_grapple_on_block`、`r5_04_grapple_no_attack_bonus`、`r5_04_grapple_expires`、`r5_04_artifact_blocks_grapple`、`r5_04_artifact_consumed`；`Powers/GrapplePower.cs` |
| R5-05 Colossus | 检查玩家易伤而非攻击者 | `calc_monster_damage` 检查 `m.vulnerable`；每敌方回合减 1 层 | `r5_05_colossus_dealer_vulnerable`、`r5_05_colossus_ignores_player_vulnerable`、`r5_05_colossus_two_stacks`；`Powers/ColossusPower.cs` |
| R5-06 Gigantification | 2 倍且回合末清空 | 攻击 ×3；每张攻击牌 `AfterCardPlayed` 减 1 层，未攻击则保留 | `r5_06_gigantification_triples`、`r5_06_gigantification_consumed`、`r5_06_gigantification_unused_survives`；`Powers/GigantificationPower.cs` |
| R5-07 FreeAttack | 回合末清除；把 X 费变 0 | 跨回合保留；X 费仍支付当前能量 | 见 C 节；`Powers/FreeAttackPower.cs`、`Entities.Cards/CardEnergyCost.cs` |
| R5-08 Cruelty | 乘法当加法 | 加到易伤倍率 | `r5_08_cruelty_additive`；`Powers/CrueltyPower.cs` |
| R5-09 Howl From Beyond | 实现在回合末且只处理一张 | 移到 `start_player_turn` 的 BeforeHandDraw，遍历所有 Exhaust 副本逐个自动打出 | `r5_09_howl_all_copies`（32）；`Cards/HowlFromBeyond.cs` |
| R5-10 Drum of Battle | 无 BeforeHandDrawLate 钩子 | 回合抽牌前按 Amount 消耗牌顶，需要时洗牌 | `r5_10_drum_exhausts`（1）；`Powers/DrumOfBattlePower.cs` |
| R5-11 Aggression | 忽略层数且在普通抽牌后 | `start_player_turn` 最先从弃牌堆随机取 Amount 张攻击并升级，再抽牌/洗牌 | `r5_11_aggression_two_stacks`、`r5_11_aggression_before_shuffle`；`Powers/AggressionPower.cs` |
| R5-12 Automation | 用本回合抽牌总数代替实例 | 每个实例独立 `cardsLeft=10`，跨回合累计；`MAX_AUTOMATION=8` 实例槽 | `r5_12_automation_across_turns`（+1）、`r5_12_automation_ignores_prior_draws`（0）；`Powers/AutomationPower.cs` |
| R5-13 Stratagem | 随机单张代替选择 | 洗牌时打开 `DRAW_TO_HAND` 选择，候选为 Amount 张；`pendingDrawRemainder` 保证选择完成后继续剩余抽牌 | `r5_13_stratagem_choice`、`r5_13_stratagem_count`（2）；`Powers/StratagemPower.cs` |

### G. 怪物 Power（R5-21—R5-25）

| 项 | 修复 | 回归 / 依据 |
|---|---|---|
| R5-21 Hardened Shell | `damage_monster` 以 `shellHpLostThisTurn` 限制每玩家回合的未格挡 HP 损失；玩家回合开始重置 | `r5_21_hardened_shell_cap`（两次 15 只扣 20）；`Powers/HardenedShellPower.cs` |
| R5-22 Enrage | `after_card_played` 中玩家打出 Skill 时给所有带 Enrage 的存活怪物加力量 | `r5_22_enrage_on_skill`（+2）；`Powers/EnragePower.cs` |
| R5-23 Slow | 每张打出的牌使该怪物 `slowCardsThisTurn+1`，后续攻击伤害 ×(1+0.1n) | `r5_23_slow_scaling`（7）；`Powers/SlowPower.cs` |
| R5-24 Painful Stabs | `monster_attack_player` 每个未格挡 hit 向弃牌堆加 Wound | `r5_24_painful_stabs_wound`（1）；`Powers/PainfulStabsPower.cs` |
| R5-25 Nemesis | 怪物回合结束后切换 `nemesisIntangible`，置 INTANGIBLE 1/0；首次施加跳过首个 duration tick | `r5_25_nemesis_intangible`（1）；`Powers/NemesisPower.cs` |

这些钩子只在完整状态机上验证（`Skulking Colony`/`Test Subject`/`Bygone Effigy` 正常 spawn）；
Painful Stabs/Nemesis 使用阶段能力最小单元复现，未走完整复活链。

### H. 观察（R4-11、R5-27）

**R4-11 第 9 个 Bomb / 第 9 张之后已知牌顶**
- 修复：`PUB_KNOWN_TOP = 16`（有序身份 + 1 个计数），`PUB_BOMB_SLOTS = MAX_PILE = 160`
  （`TheBombPower.IsInstanced` 无层数上限，每个实例一个槽：拥有者 + 倒计时）。
- 容量策略：已知牌顶仍显式有界（16）；超过 16 张只暴露数量与前 16 顺序，这是公开记录的上限，
  不是静默截断。Bomb 不再有 8 个上限。
- 回归：`r4_11_ninth_bomb_observable`、`r4_11_ninth_bomb_changes_transition`（差 40 HP）、
  `r4_11_known_top_order_observable`。

**R5-27 公开但影响转移的属性**
- 修复：
  - 玩家标量增加 `tempStrength/tempDexterity`（`PUB_COMBAT_BASE` 14 项）；
  - 手牌/动作特征增加 `freeCombat` 与 `costThisTurn`，可区分永久免费与临时改费；
  - 抽牌/弃牌/消耗堆的可见 bag 按升级拆分（`push_card_bag_split`），升级身份不再合并。
- 不变：不泄露抽牌顺序、隐藏意图或 RNG。
- 回归：`r5_27_obs_temp_strength` 与转发对照、`r5_27_obs_permanent_vs_temp_free`、
  `r5_27_action_permanent_vs_temp_free`、`r5_27_obs_draw_upgrade_identity`。
- Schema 升到 v6 / action v5；维度 `PUBLIC_OBS_DIM=17762`、`CARD_FEAT_DIM=240`、`ACTION_FEAT_DIM=325`，
  `agent/common.py` 动态读取，README 已同步。旧检查点会被 `load_checkpoint` 拒绝。

## 验证

### 命令

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round4-20261028\reproduce.ps1'
& '.\.scratch\deep-audit-round5-20261028\reproduce.ps1'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round5-20261028\timeout_check.py'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

`reproduce.ps1` 均以 `-O1 -fsanitize=bounds -fno-sanitize-recover=bounds` 重新编译全部引擎 `.cpp`，
并链接第三轮自定义 `bounds_handler.cpp`。

### 结果

| 检查 | 结果 |
|---|---|
| 原生 rules（新编译，含新增第四/五轮回归） | `SUMMARY checks=233 failures=0` |
| 第二轮原始 probe | `checks=32 failures=0` |
| 第三轮原始 probe | `checks=41 failures=0` |
| 第四轮 probe | `checks=30 failures=0`（修复前 23 失败） |
| 第四轮遗物/药水矩阵 | `games=12532 steps=308903 failures=0 capped=0` |
| 第五轮 probe | `checks=58 failures=0`（修复前 51 失败） |
| 第五轮遭遇扫描 | `games=5340 steps=185024 failures=0 capped=4` |
| 第五轮整局扫描 | `games=300 steps=19357 failures=0 capped=0` |
| bounds stderr（probe/sweep） | 0 字节；两个进程均 `exit=0`（不再 77） |
| `probe.exe transform-bounds`（插桩） | `ENTER add Astrolabe` / `RETURN add Astrolabe`，exit=0，stderr 0 字节 |
| Sozu+Brew 3 秒限制 | `COMPLETED exit=0`（修复前超时） |
| Python `pytest tests -q` | `84 passed in 24.00s` |

扫描覆盖 `duplicate_uid`、`clone_divergence`（同一步在克隆状态上重放必须完全一致）、
`legal_rejected`、`pile_bounds`、`invalid_card`、`known_top_exceeds_draw`、`player_bounds`、
`nonfinite_obs`；结果均为 0，且 `run replay divergence` 为 0。

### 800 步截断的解释

4 个 capped 游戏全部是 encounter 8（`ARCHITECT`，9,999 HP），seed 720811 / 720849 / 720863 / 720866。
用新增 `capcheck.cpp`（与 sweep 完全相同的种子、牌组、遗物、药水和动作 RNG，仅把上限提到 5,000 步；
结果在 `capcheck-results.txt`，stderr 0 字节）复验，四局都在持续前进而非原地循环，例如 seed 720863：

```
step=200 turn=37  hp=281/281 m0_hp=8512/9999
step=400 turn=79  hp=261/261 m0_hp=6944/9999
step=600 turn=131 hp=239/239 m0_hp=5481/9999
step=800 turn=179 hp=218/218 m0_hp=4022/9999
FINAL outcome=2 turn=200 step=897 hp=209/209 m0_hp=3208/9999
```

四局均在 811–897 步、第 200 回合由引擎的僵局保护（`turn >= 200 -> PLAYER_LOSS`）结束。
因此 800 步截断是扫描预算对高生命 boss 的截断，不是死循环；`exit 77` 也不再出现。

## 残余风险与明确未声称

1. **无客户端差分**：所有预期均来自本地 C# 参考代码，未与真实游戏客户端逐步对比。
2. **随机扫描无逐步骤语义 oracle**：矩阵/sweep 只验证不变量、可重放性和有限观测，不能反证规则全部正确。
3. **观察上限**：`PUB_KNOWN_TOP=16` 仍是有界信息；超过 16 张已知牌顶只暴露数量与前 16 顺序。
   若训练需要完整顺序，应继续提高常量（会改变 `PUBLIC_OBS_DIM` 并使旧检查点失效）。
4. **200 回合僵局保护**：`end_player_turn` 的 `turn >= 200` 直接判负是刻意简化；真实长局
   （目前只见 9,999 HP 的 ARCHITECT 随机牌组）可能被误判。若引入更高生命/无限战斗内容需重新评估。
5. **自动化实例上限**：`MAX_AUTOMATION=8`，超过 8 个 Automation 实例的极端牌组会少触发。
6. **APPROXIMATE 项仍在**：Snecko Eye 的逐张钩子已补齐，但仍受覆盖表 APPROXIMATE 标记约束；
   古代遗物/事件的非审计次要效果、部分怪物 Power（本轮未列出的）仍可能只有数值没有效果，
   本轮只修复 R5-21—R5-25 点名的五种。
7. **事件近似**：事件卡/附魔 UI 仍用 RNG 替代；这不因本轮修复而改变。
8. **训练影响**：观察 schema v6/action v5 使旧检查点失效；本轮未训练新模型，也未比较胜率。

## 复现与交接

- 所有探针、结果文件、`source-hashes.json`、`reproduce.ps1`、`timeout_check.py`、`capcheck.cpp`
  位于 `.scratch/deep-audit-round4-20261028`、`.scratch/deep-audit-round5-20261028`，
  依赖 `.scratch/deep-audit-round3-20261028/bounds_handler.cpp`；这些目录被 Git 忽略，需随工作区一起复制。
- 探针即使断言失败也可能 exit 0；验收必须读取 `FAIL`/`SUMMARY failures=`，不能只看退出码
  （bounds 模式下越界会以 77 终止，这是唯一的退出码判据）。
