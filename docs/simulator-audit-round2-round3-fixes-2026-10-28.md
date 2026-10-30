# 第二轮/第三轮深度审计修复报告

日期：2026-10-28。项目：`D:\sts2_datacollection\sts2`。
基线：`a57a702` 加当时未提交的修复（与两份审计报告的被测版本相同）。本报告描述的是**当前工作区**的代码，不是该提交号本身。

未改动外部参考工程 `D:\project\sts2_compactformer\sts2-rl-agent`，未回退任何已有修复。规则判定以反编译 C# 的完整调用链为准；下文 `Cards/X.cs`、`Powers/X.cs`、`Relics/X.cs`、`Potions/X.cs`、`Commands/X.cs`、`Models/CardModel.cs` 均指该目录中的对应文件。

## 结论

第二轮 R01–R12 与 R13/R14 的全部已确认问题、第三轮 T01–T16 与 A01/A02 的全部已确认问题都已在实际代码中修复，并有可执行回归。第三轮标为“支持范围外”的 Ghost in a Jar / Cosmic Concoction 也按参考语义改正（仍不在 Ironclad 掉落池，故不改变声明范围）。

关键不变量结果：

| 检查 | 修复前 | 修复后 |
| --- | --- | --- |
| 第二轮定向探针 | 32 checks，29 FAIL | **32 checks，0 FAIL** |
| 第三轮定向探针 | 41 checks，31 FAIL | **41 checks，0 FAIL** |
| 双卡组合（1600 场） | 367 场重复 UID | **0** |
| 第三轮全矩阵（55,588 场、1,143,670 步） | 6,260 重复 UID + 347 knownTop 越界 | **0 failures，0 bounds 错误** |
| 原生规则回归 | 85 checks | **153 checks，0 failures** |
| pytest | 84 passed | **84 passed** |

**没有做真实客户端逐步差分，因此不能宣称完整保真。** 本报告的“正确”只表示与反编译 C# 的调用链一致，并已通过上述可执行检查。

## 第一优先级：统一出牌生命周期（R01–R07）

### 根因

旧实现把一次出牌拆成三个互不一致的路径：`play_card`（手动）、`auto_play_random`（自动）、`finish_pending_source`（选择结束）。三者各自决定源牌去向，因此：

- 自动打出带选择的牌时，选择收尾和自动出牌收尾各移动一次源牌（同一 UID 出现两份）；
- 手动选择结束不经过 `AfterCardPlayed` 与费用清理；
- replay/Duplication 只重复 `play_card_effect`，计数与钩子只记一次；
- 第二次 play 直接执行效果，覆盖尚未完成的第一次选择；
- 自动入口漏掉 Duplication 与 Hook；
- 从弃牌堆取牌的 Beat Down 在牌已被其它效果移走后仍按旧索引/UID 删除。

### 修改

`simulator/include/sts2/battle.h`、`simulator/src/battle.cpp` 引入 `ActivePlay` 帧，按 `CardModel.OnPlayWrapper` 建模：

- `begin_play`：一次性计算 `playCount = 1 + replay + bonusReplay`，再叠加 One-Two-Punch / Duplication / Throwing Axe（三者都是 `ModifyCardPlayCount`，对自动出牌同样生效）；每次 play 消耗一层。
- `run_active_play`：**每次 play** 才递增 `cardsPlayedThisTurn/ThisCombat`、攻击/技能计数，调用 `relics_card_about_to_play`，执行效果，再调用 `AfterCardPlayed`（Rage、Panache、relic 钩子、Nostalgia、Tender 等都在这里）。
- 效果内出现选择时置 `awaitingAfter` 并暂停；`maybe_finish_pending` 关闭选择后**恢复同一帧**（先补 `AfterCardPlayed`，再进入下一次 play）。因此复制的 Headbutt 会先后产生两次独立选择，不会互相覆盖。
- `finish_active_play`：所有 play 结束后**只移动一次**源牌，执行 Razor Tooth 升级、`EnergyCost.AfterCardPlayedCleanup`（`card_restore_cost`）、Nostalgia、exhaust/result pile。Power 牌不进入任何牌堆。
- `auto_play_random` 复用同一帧，自动解决选择；`auto_play_from_draw` 对应 `CardPileCmd.AutoPlayFromDrawPile`（每次取牌前必要时洗牌、先收集再依次执行）。
- Hellraiser、Stampede、Mayhem、Distraction 类遗物、HOWL 等全部自动入口改为走该帧；源码中已不存在 `play_card_effect` 的直接调用（除帧内部）。
- Beat Down 先快照弃牌堆攻击牌，再按 UID 从“当前所在的任一牌堆”摘除（`detach_card`）后自动打出；嵌套 Headbutt 把后续候选移到抽牌堆时也不会复制实体。复制品（HistoryCourse、Music Box、Juggling）使用新 UID。
- `queue_return_next_turn` 按 UID 去重：One-Two Punch / Hidden Gem 让 Thrumming Hatchet、Bolas 打两次时只回手一次。
- Duplication 在玩家回合结束时移除（`DuplicationPower.AfterTurnEnd`）。

### 规则依据

`Models/CardModel.cs:1444–1531`（`OnPlayWrapper`：`playCount` 计算、循环内 Before/OnPlay/After、循环后仅在仍位于 Play 堆时移动一次、之后才做费用清理）；`Powers/DuplicationPower.cs`、`OneTwoPunchPower.cs`、`Relics/ThrowingAxe.cs` 都是 `ModifyCardPlayCount`；`Powers/HellraiserPower.cs`、`StampedePower.cs` 调用 `CardCmd.AutoPlay`；`Commands/CardCmd.cs:33–112`；`Commands/CardPileCmd.cs:832–862`.

### 回归

`simulator/tests/rules_regression.cpp`：`r01_*`、`r02_*`、`r03_*`、`r04_*`（含 replay）、`r05_duplicated_headbutt_two_returns`、`r06_*`、`r07_duplication_expires`；审计探针的同名断言；双卡组合 1600 场。

## 第二优先级：伤害、格挡、状态与遗物

| 项 | 根因与修改 | C# 依据 | 回归 |
| --- | --- | --- | --- |
| R08 Bloodletting | 自伤改为 `CreatureCmd.Damage(Unblockable\|Unpowered\|Move)` 语义：`damage_player(x, true)`，不再走 `lose_hp`。RuPtion、Buffer、Self-Forming Clay、Tungsten Rod 等钩子全部进入。同类自伤牌/诅咒/能力（Blood Wall、Breakthrough、Hemokinesis、Offering、Brand、Beckon、Bad Luck、Regret、Crimson Mantle、Inferno、Royal Poison）一并改正。 | `Cards/Bloodletting.cs`；`Powers/RupturePower.cs`；`Powers/BufferPower.cs` | `r08_*`，探针 4 条 |
| R09 Thorns | `damage_monster` 新增 `poweredAttack` 维度：玩家 powered 攻击（含被完全格挡）在扣格挡前触发怪物荆棘；反伤以 Unpowered 结算（可被玩家格挡、不吃力量/易伤）。药水等 Unpowered 伤害不触发。玩家荆棘/Flame Barrier 对怪物攻击同样先/后反伤。 | `Powers/ThornsPower.cs`、`FlameBarrierPower.cs` | `r09_*` |
| R10 Whirlwind | 多段攻击合并为一条 AttackCommand，Vigor 只加一次、只消耗一次。`calc_player_damage` 不再隐式加 Vigor；各 `attack_*` 命令入口统一 `take_vigor`。 | `Cards/Whirlwind.cs`；`Powers/VigorPower.cs` | `r10_whirlwind_vigor_whole_command` |
| R11 Second Wind | 卡牌格挡改为 `gain_block(per, true)`（来自卡牌、powered），No Block 正确阻止。 | `Cards/SecondWind.cs`（`BlockVar(..., Move)`）；`Powers/NoBlockPower.cs` | `r11_*` |
| R12 Bomb | `MAX_BOMBS` 提升到 `MAX_PILE`（存储上界，远高于任何牌堆能产生的实例），不再在第 9 个静默丢弃。 | `Powers/TheBombPower.cs`（IsInstanced，无上限） | `r12_nine_bombs_*` |
| T05 Shackling | 移除 `strength<=0` 跳过与 `min(strength,7)` 截断：固定施加 7 点临时力量损失，可为负；敌方回合结束恢复。 | `Potions/ShacklingPotion.cs`；`Powers/ShacklingPotionPower.cs` | `t05_*` |
| T06 玩家 Plating | 敌方回合结束后玩家 Plating 减 1（`PlatingPower.AfterTurnEnd(side==Enemy)`）。敌人 Plating 仍按玩家数衰减。 | `Powers/PlatingPower.cs` | `t06_*` |
| T10 Artifact | `add_player_power` / `add_monster_power` 统一拦截可见减益：任意来源（怪物招式、诅咒 Doubt/Shame、Beetle Juice Shrink、药水）先扣 1 层 Artifact 并取消该次施加。 | `Powers/ArtifactPower.cs`；`Commands/PowerCmd.cs` | `t10_*`，探针 5 条 |
| T12 Self-Forming Clay | 每次未格挡伤害**累加** 3 点下回合格挡，而非覆盖。 | `Relics/SelfFormingClay.cs`；`SelfFormingClayPower` | `t12_*` |
| T13 Ruined Helmet | 力量药水、Fysh Oil 以及 Vajra/Sword of Jade/Sling of Courage/Brimstone/Red Skull/Shuriken/Rainbow Ring/Toasty Mittens/Girya/Ember Tea 等正力量来源统一走 `add_player_power(STRENGTH, …)`，由 `relics_strength_gain` 触发一次翻倍。Flex Potion 走 `FlexPotionPower`（非 StrengthPower），不翻倍，保持参考语义。 | `Relics/RuinedHelmet.cs.TryModifyPowerAmountReceived` | `t13_*` |
| T16 减益持续时间 | 对玩家施加任意可见减益时设置该能力的 “跳过下一次持续时间结算”；Weak/Frail/Vulnerable 在敌方回合结束时先清标志、不减层。Doubt/Shame 改走同一入口（同时受 Artifact 拦截）。 | `Commands/PowerCmd.cs:103–105`；`WeakPower.AfterTurnEnd` → `TickDownDuration` | `t16_*`，Axebot 探针 |

## 第三优先级：药水与整局钩子

| 项 | 修改 | C# 依据 | 回归 |
| --- | --- | --- | --- |
| T01 Liquid Memories | 取回的牌 `SetThisTurnOrUntilPlayed(0)`（`DISCARD_TO_HAND` 带 payload）。 | `Potions/LiquidMemories.cs` | `t01_*` |
| T02 Bottled Potential | 手牌全部放入抽牌堆 → 洗牌 → 抽 5；洗牌后 `knownTopCount` 归零。 | `Potions/BottledPotential.cs` | `t02_*` |
| T03 Clarity | 立即抽 1，并施加 Clarity 3；之后每个玩家回合起手 +1 抽，回合开始扣层。 | `Potions/Clarity.cs`；`Powers/ClarityPower.cs` | `t03_*` |
| T04 Radiant Tincture | 立即 +1 能量，并施加 Radiance 3；之后每次能量重置 +1 并扣层。 | `Potions/RadiantTincture.cs`；`Powers/RadiancePower.cs` | `t04_*` |
| T07 药水池 | Attack/Skill/Power Potion 只从 Ironclad 角色池取牌；Colorless Potion 从完整无色池取任意类型。 | `Potions/AttackPotion.cs` 等（`Owner.Character.CardPool` / `ColorlessCardPool`） | 探针 200 种子采样，`t07_*` |
| T08 可跳过 | 这些药水的发现界面 `optional=true`，`CONFIRM` 合法。 | `FromChooseACardScreen(canSkip: true)` | `t08_potion_offer_can_skip` |
| T09 抽牌堆自动出牌 | Havoc、Cascade、Distilled Chaos、Mayhem 统一走 `auto_play_from_draw`：每取一张前按需洗弃牌堆，先收集再执行。 | `Commands/CardPileCmd.cs:832–871` | `t09_*` |
| T11 Foul Potion | 先结算玩家 12 点（可格挡），再结算所有敌人；击杀最后敌人不再取消自身代价。 | `Potions/FoulPotion.cs`（`CombatState.Creatures` 批量 Damage） | `t11_*` |
| T14 Pantograph | 进入 Boss 战开始时治疗 25（`begin_combat` 内、复制 HP 之前），并删除战后治疗。 | `Relics/Pantograph.cs.AfterRoomEntered(RoomType.Boss)` | `t14_*` |
| T15 事件战胜利 | 事件战斗胜利同样调用 `relics_combat_end`（Burning Blood、Meat on the Bone 等）。 | `Relics/BurningBlood.cs.AfterCombatVictory` | `t15_*` |
| A01 The Boot | 从“扣格挡前的伤害”移到“扣格挡后的 HP 损失”：powered 攻击造成 1–4 点 HP 损失时提升为 5。 | `Relics/TheBoot.cs.ModifyHpLostBeforeOsty` | `a01_boot_after_block` |
| A02 History Course | 只重放“上一回合最后一次非复制攻击/技能”，并 `CreateDupe`（新 UID）；复制品的出牌不更新历史。 | `Relics/HistoryCourse.cs` | `a02_*` |
| 范围外两药水 | Ghost in a Jar 改为 Intangible 1（原为 Buffer）；Cosmic Concoction 改为直接加入 3 张不同的已升级无色牌（原为三选一）。 | `Potions/GhostInAJar.cs`、`CosmicConcoction.cs` | 第三轮探针 2 条 |

## 第四优先级：观测与搜索（R13/R14）

观测 schema 升级为 `PUBLIC_OBS_VERSION=5`、`ACTION_SCHEMA_VERSION=4`，新增/修正：

- 玩家可见计数：`cardsPlayedThisTurn`、`attacksPlayedThisTurn`、`skillsPlayedThisTurn`（Panache 每 5 张、Letter Opener 每 3 技能）。
- 已知牌顶：`knownTopCount` 标量 + 顶 8 张**有序**身份与升级标记（只读取 `knownTopCount` 区域，不泄露隐藏区）。
- Bomb 实例：数量 + 8 个槽位的倒计时与伤害。
- 卡牌 replay：`CARD_FEAT_DIM` 和动作特征都加入 `replay` / `bonusReplay`，使“同一动作执行几次”不再与状态无关。

已知信息维护：所有抽牌堆移牌统一走 `remove_draw_at` / `take_draw_top`（按索引移除时若落在已知前缀就缩减 `knownTopCount`）；Headbutt/Nostalgia/Secret Weapon/Jeweled Mask/Cascade/Havoc/Distilled Chaos/Beat Down 等路径全部覆盖；洗牌清零。`resample_hidden` 仍只打乱未知前缀。

同步：Python 的 `agent/common.py`、`agent/nets.py`、`agent/selfplay.py`、`agent/run_env.py` 和部署脚本都从扩展读取维度与版本；`load_checkpoint` 对缺失元数据、旧 `obs_version`、旧 `action_schema_version`、参数形状不符一律报错。现有 `runs/*.pt` 因此被明确拒绝，需要重训（见下）。

碰撞回归（原生）：Bomb、已知牌顶交换、Panache 计数、replay 四项分别断言“状态或动作特征可区分”，并验证行为差异（Bomb 下一回合 40 伤害、Panache 额外 5 伤害）。

## 验证

全部材料在 `.scratch/fix-verification-20261028/`（源码 SHA256 在 `source-hashes.json`）。重建并运行：

```powershell
Set-Location D:\sts2_datacollection\sts2
& .\.scratch\fix-verification-20261028\reproduce.ps1
```

| 项目 | 结果 |
| --- | --- |
| 扩展重建（MinGW -O3，静态链接） | 成功；`simulator/sts2_sim.cp312-win_amd64.pyd` |
| 原生规则回归（`rules_test.exe`） | 153 checks，0 failures |
| pytest | 84 passed |
| 第二轮定向探针 | 32 checks，0 FAIL |
| 第三轮定向探针 | 41 checks，0 FAIL |
| 双卡组合扫描 | 1600 场，28,538 步，0 failures，0 capped |
| 第三轮全矩阵（bounds 插桩） | 55,588 场，1,143,670 步，0 failures；`bounds-errors.txt` 为空 |
| 整局压力（新种子 42000000–42000999） | 1000 局、208,022 步、6,101 次快照恢复重放、24 胜，0 error / 0 truncated |
| 整局压力（对比种子 41000000–41000999） | 1000 局、211,131 步、6,196 次快照恢复重放、23 胜，0 error / 0 truncated |

具体计数见 `fuzz-*-results.txt`；训练/胜率数字只代表固定启发式策略，不是模型评估。

### 吞吐

同机、同策略、同种子范围，MinGW -O3 单线程（重复测量区间）：

| 路径 | 记录基线 | 当前 |
| --- | --- | --- |
| C++ 原生整局（500 局） | 102.3 runs/s | 95–122 runs/s |
| 战斗（Shrinker Beetle，2.89 回合） | ~240,000 combats/s | 193,000–216,000 |
| 战斗（Cultists，6.17 回合） | ~130,000 combats/s | 103,000–117,000 |
| 地图生成 | 9.08 ms/run | 6.9–9.0 ms/run |

整局吞吐没有下降；战斗微基准比 README 的单次记录低约 10–20%，重复测量本身即有约 10% 波动。没有减少模拟次数、跳过效果或丢弃待处理选择。与基线二进制直接 A/B 不可能：基线是未提交工作区，无法从提交号重建；这里的对照只是同机重复测量。

## 残余限制与范围外

- 没有真实客户端逐步差分、没有 RNG 全流对齐、没有多角色/多人验证。不可宣称完整保真。
- 自动出牌的 `OnPlay` 选择仍由策略层自动取第一项（模拟器既有约定，审计探针也以此断言）；手动出牌的选择完整保留并可暂停/恢复。这不是靠丢弃 pending 解决死锁：选择帧、复制帧与后续 play 都真实执行。
- 已知牌顶只编码顶 8 张的有序身份；`knownTopCount>8`（如大量 Innate 的开局）时第 9 张以后仅由计数与其余信息间接区分。
- Bomb 存储上界为 `MAX_PILE`；理论上一场战斗打出超过 160 张 Bomb 仍会受数组限制，但任何牌堆/回合上界都到不了该数量。
- Artifact 拦截列表覆盖引擎中会施加到玩家的可见减益集合；未逐一核对每个怪物能力的 `PowerType` 元数据。
- `lose_hp` 仍保留给真正的“失去生命”语义；当前声明范围内已无卡牌/能力调用它。
- 事件、药水、遗物的数值只覆盖本轮报告点名的内容；未做全内容穷举。
- 未启动长期正式训练。

## 训练适用范围

- 声明范围不变：v0.111.0、Ironclad、A0、单人、三幕。
- 观测/动作布局已变（v5 / v4），**所有旧 checkpoint 都会被 `load_checkpoint` 拒绝**；`runs/v4*` 不能继续用于比较或热启动。需要重新训练后才能给出新的模型成绩。
- 在重新训练前，只能用固定启发式/搜索做工程与回归验证；本报告没有新的胜率宣称。
