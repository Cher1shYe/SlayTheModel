# 模拟器第二轮深度测试：修复后的交互与边界

日期：2026-10-28。项目：`D:\sts2_datacollection\sts2`。

本轮只新增审计程序、结果和本报告，没有修复或修改实现、现有测试、生成表。被测版本是 HEAD `a57a702` 加当前工作区未提交修复，不能仅用该提交号重现。源码 SHA256 在 `.scratch/deep-audit-round2-20261028/source-hashes.json`；原生探针直接编译当前全部引擎源文件，没有复用旧对象。Python 扩展为 `simulator/sts2_sim.cp312-win_amd64.pyd`（文件时间 18:33:39），晚于本轮所见最新源码修改时间 18:33:23。

## 结论

**上轮修复不等于全部问题关闭。当前确认 14 类问题，涉及出牌生命周期、卡牌身份、伤害与格挡规则、复制出牌、隐藏信息和训练输入。最严重的是自动出牌组合可以复制同一 UID 的实体牌。**

本轮 1600 场专门的双卡组合测试中，367 场发生重复 UID。所有这些战斗均从 `BattleContext::init` 正常初始化开始，使用基础 80 HP、正常能量、20 张牌的合法自定义牌组，只执行引擎给出的合法动作，没有中途篡改战斗状态。自定义牌组不是从整局奖励路径获取，故证明的是战斗层可达轨迹，不能说在任意普通爬塔中都有相同发生率。

规则参考仍是：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`。下面简写 `Powers/X.cs`、`Cards/X.cs`、`Relics/X.cs` 分别对应该目录内 `MegaCrit.Sts2.Core.Models.Powers`、`MegaCrit.Sts2.Core.Models.Cards`、`MegaCrit.Sts2.Core.Models.Relics`；`CardModel.cs` 位于 `MegaCrit.Sts2.Core.Models`。没有真实客户端逐步差分验证。

## 实际执行结果

| 测试 | 本轮结果 |
| --- | --- |
| 现有 pytest | 84 passed，12.40s |
| 新定向语义探针 | 32 checks，29 failures，3 passes；归并为下述问题，不能当作总体错误率 |
| 重新编译运行原卡牌/遭遇扫描 | 1930 场，106936 步，0 violations，0 capped |
| 新种子整局压力 | seeds 41000000–41000999，1000 局，221059 步，6462 次快照恢复/重复动作，0 error、0 truncated、0 分歧 |
| 新双卡组合扫描 | 1600 场，25573 步，367 场重复 UID，0 capped |

整局压力使用四分之一随机合法策略，其余为现有默认 oracle 启发式，与模型训练成绩无关；23 胜不是新模型评估。单卡扫描与普通整局压力没有覆盖到的交互，在组合测试中大量暴露。

组合扫描使用 4 张 A、4 张 B、6 张 Strike、6 张 Defend；每组 seeds 1–200，Ceremonial Beast，80/80 HP，随机合法动作，每局遇到第一个失败即停止：

| A + B | 发生重复 UID 的场数 / 200 |
| --- | --- |
| Beat Down + Headbutt | 73 |
| Havoc + Headbutt | 81 |
| Mayhem + Headbutt | 67 |
| Stampede + Headbutt | 145 |
| Hellraiser + Seeker Strike | 0 |
| Beat Down + Anger | 0 |
| Beat Down + Thrumming Hatchet | 1 |
| Beat Down + Rampage | 0 |

最后三组通过的案例不证明其全部语义正确。日志记录每组前两条失败完整动作轨迹，其余失败计入 GROUP。

## R01 — P1：自动打出带选择的卡牌，重复结算源牌，破坏 UID 唯一性

- 位置：`simulator/src/battle.cpp:1063`（finish_pending_source）、`:1468`（auto_play_random）；`simulator/src/cards_colorless.cpp:312`（Beat Down）。
- 自动打出 Headbutt 时，`auto_resolve_pending` 已经通过 `finish_pending_source` 把源牌放入弃牌堆，随后 `auto_play_random` 又调用 `finish_played_card` 放一次。
- 直接探针：同一 Headbutt UID 应只存在 1 份，实际 **2 份**。Beat Down + Headbutt 隔离场景实际 **3 份**。
- Beat Down 还在牌仍留在弃牌堆时自动打出它，之后才倒序寻找 UID 删除；嵌套选牌、回手等效果改变牌堆时，它无法保证删除的是原来那张实体，旧 `picks` 索引也可能失效。本轮不把所有 367 次错误归为同一条代码路径，但它们都已经实际破坏实体唯一性。
- 正常初始化轨迹：Havoc + Headbutt，seed 2，依次 PLAY Headbutt、PLAY Defend、PLAY Havoc，第 3 个动作后出现重复 UID 5。完整参数见 `combo-results.txt`。
- 参考：`CardModel.cs:1515–1531` 在执行完全部 play 后，只有源牌还位于 Play 堆才进行一次最终去向处理；`Cards/BeatDown.cs` 对牌模型列表调用 AutoPlay，不复制实体。
- 影响：错误增殖、同一 UID 选择歧义、错消耗/错弃牌，训练能学习利用不存在的牌堆行为。这不是单纯展示问题。

## R02 — P1：手动选择结束绕过正常收尾，遗物触发和临时费用清理遗漏

- 位置：`battle.cpp:1063–1089` 与 `:1437`。
- `finish_pending_source` 直接 move_to_discard/exhaust，没有执行 `relics_card_played`、费用恢复等正常收尾逻辑。
- 实测：持有 Letter Opener，依次打出两张 Defend，再打 Armaments 并完成升级选择，第三张技能应造成 **5** 伤害，实际 **0**。
- 给 Armaments 设置打出后应清理的临时 0 费，完成选择后，弃牌堆中的源牌仍是 **0 费**，预期恢复 **1 费**。本项是生命周期隔离测试，设置方式为当前提供的 `card_set_turn_cost`。
- 参考：`Relics/LetterOpener.cs` 的 AfterCardPlayed；`CardModel.cs:1506/1531`。不能只修普通不带选择的出牌路径。

## R03 — P1：Hellraiser / Stampede 仍绕过完整自动出牌生命周期

- 位置：`battle.cpp:454` 的 Hellraiser 分支；`:305` 的 Stampede 分支。
- 两处直接调用 `play_card_effect`，没有走已增加计数和钩子的 `auto_play_random`。
- Hellraiser 抽到 Strike：攻击计数预期 **1**，实际 **0**；已有 Rage 3 时格挡预期 **3**，实际 **0**。
- Stampede 在回合末自动打出 Strike，累计战斗攻击计数预期 **1**，实际 **0**。
- 参考：`Powers/HellraiserPower.cs`、`Powers/StampedePower.cs` 均调用 CardCmd.AutoPlay。上轮 D14 只修了一个入口，尚未覆盖其他入口。

## R04 — P1：复制出牌只重复效果，不重复每次出牌的计数和钩子

- 位置：`battle.cpp:1331–1401`。
- 计数递增在 replay 循环之前，after_card_played 在循环之后，所以多次执行只被记录为一次。
- Duplication + Strike + Rage 3：伤害 **12** 正确，但攻击计数为 **1**（应 2），格挡 **3**（应 6）。
- 参考：`CardModel.cs:1464–1506` 明确把 BeforeCardPlayed、OnPlay、AfterCardPlayed 都放在每一次 play 循环内。
- 影响：Rage、Panache、攻击/技能次数遗物等组合与真实游戏不同。

## R05 — P1：复制带选择的卡牌，后一次 pending 覆盖前一次选择

- 位置：`battle.cpp` 的 `play_card` replay 循环、`start_choice` 重置 pending。
- Duplication + Headbutt，弃牌堆有两张可选牌：完成所有可见选择后，应把 **2 张**牌放到抽牌堆顶，实际仅 **1 张**。
- 根因：循环在第一次选择尚未完成时直接执行第二次效果，没有保存暂停点/后续 replay，第二个选择覆盖第一个。
- 参考：`CardModel.cs:1488–1506` 每次 await OnPlay 完成才进入下一次；`Cards/Headbutt.cs` 每次执行独立等待选择。

## R06 — P1：自动出牌没有应用 Duplication/replay

- 位置：`battle.cpp:1468–1510`，只执行一次 play_card_effect。
- 带 Duplication 自动打出 Strike：应 **12** 伤害并消耗复制层数，实际 **6** 伤害，复制层数仍 **1**。
- 参考：`Powers/DuplicationPower.cs` 的 ModifyCardPlayCount 没有排除自动出牌，CardModel 的统一包装会调用它。
- 与 R04/R05 区别：这里是自动入口完全漏掉重复执行，不只是计数或选择错误。

## R07 — P2：Duplication 没在回合结束移除

- 位置：`battle.cpp:305` 的回合末状态清理。
- 带 Duplication 1 直接结束回合，下一回合仍为 **1**，预期 **0**。
- 参考：`Powers/DuplicationPower.cs.AfterTurnEnd` 在持有者回合结束 Remove(this)。
- 会让本应当回合使用的复制效果跨回合保留。

## R08 — P1：将 Bloodletting 的生命损失错当为不触发伤害钩子的直接扣血

- 位置：`cards_ironclad.cpp` BLOODLETTING 调用 lose_hp；`battle.cpp:834`。
- 有 Rupture 2 时打 Bloodletting，力量应 **+2**，实际 **+0**。
- 有 Buffer 1 时打 Bloodletting，HP 应维持 **500** 且 Buffer 消耗至 **0**；实际 HP **497**，Buffer 仍 **1**。
- 参考：`Cards/Bloodletting.cs` 实际调用 CreatureCmd.Damage，props 为 Unblockable | Unpowered | Move；名字 HpLossVar 不代表绕过伤害事件。`Powers/RupturePower.cs` 处理本方回合收到的未格挡伤害，`Powers/BufferPower.cs` 会把该次失血修改为 0。
- 这是上轮 D06 修复里的错误假设，需要区分真实 API 语义，而不是用“扣血不是伤害”一概跳过。其他 lose_hp 调用方本轮未逐个验证。

## R09 — P1：怪物荆棘触发条件、反伤可格挡性与来源判定错误

- 位置：`battle.cpp:642–674`。
- 完全被怪物格挡的 Strike 不触发反伤：HP 实际 **500**，应 **497**。
- 玩家有 10 格挡，攻击荆棘 3 的怪物：应 HP **500**、格挡 **7**；实际 HP **497**、格挡 **10**，反伤被错误设成不可格挡。
- 使用 Explosive Ampoule 造成 Unpowered 药水伤害也触发了荆棘：HP **497**，应 **500**。
- 参考：`Powers/ThornsPower.cs.BeforeDamageReceived` 对 powered attack（及特殊 Omnislice）在扣血前触发；反伤 props 为 Unpowered | SkipHurtAnim，没有 Unblockable。
- 当前通用 damage_monster 只有 fromPlayer 标志，不足以区分上述来源。

## R10 — P2：Whirlwind 的 Vigor 只加到第一段

- 位置：`cards_ironclad.cpp:346–347`；`battle.cpp` attack_all_from_card。
- 3 能量、Vigor 5、未升级 Whirlwind：应 `(5+5)×3=30`，实际 **20**。
- 每段都独立调用 hit_all，第一次就消耗 Vigor，后两段失去加成。
- 参考：`Cards/Whirlwind.cs` 创建一个 WithHitCount(3) 的 AttackCommand；`Powers/VigorPower.cs` 在这一个完整 AttackCommand 结束后才扣层数。

## R11 — P2：Second Wind 绕过 No Block

- 位置：`cards_ironclad.cpp:312` 的 `gain_block(per, false)`；`battle.cpp:766`。
- 有 No Block，打 Second Wind 消耗一张 Defend：格挡应 **0**，实际 **5**。
- 参考：`Cards/SecondWind.cs` 使用带 cardPlay 的 powered BlockVar；`Powers/NoBlockPower.cs` 阻止来自卡牌的非 Unpowered 格挡。
- fromCard=false 错误抹去了来源，说明来源与 powered 两个维度仍有混用。

## R12 — P2：第 9 个 Bomb 被静默丢弃

- 位置：`include/sts2/battle.h:159` MAX_BOMBS=8；`cards_colorless.cpp:271`。
- 定向大容量场景连续打出 9 张 Bomb（50 能量隔离规则）：实际只注册 **8** 个，第三次结束回合共造成 **320**，应 **360**。
- 参考：`Powers/TheBombPower.cs` IsInstanced=true，没有此 8 实例限制。
- 本轮已执行边界复现，但没有提供从标准初始牌组取得 9 张 Bomb/足够能量的整局轨迹，不夸大普通爬塔发生频率。不能把静默忽略视为正确容量策略。

## R13 — P1：v4 训练观测仍合并需要不同决策的可见状态

- 位置：`observe.cpp:119` public_combat_observation、card_features、combat_action_features；`agent/nets.py` CombatNet。
- Bomb 实例、计时/伤害存于独立数组，没有进入观测。其他字段相同的两个状态，一个下次回合末爆炸 40，一个没有 Bomb，观测完全相同；实测下一次结束回合怪物 HP 差 **40**。
- 已知牌顶顺序仍被 bag 编码抹掉：两张都已知的牌交换顺序，观测不变。
- Panache 同层数但 cardsPlayedThisTurn 为 0 或 4，观测不变；打同一 Strike 后，一个额外造成 **5** 伤害，另一个没有。
- 同一 Strike 的 replay 为 0 或 1，**状态观测与对应动作特征同时完全相同**，但其执行次数不同。
- 这些都是网络输入的缺失，不能靠扩大网络或增加训练样本恢复丢失的信息。当前 CombatNet 无跨步记忆；本报告不要求模型读取真正隐藏信息。
- 对比状态通过可控副本隔离字段，未声称每对状态均由同一完整历史自动产生。缺失字段及行为差异均已经实际验证。

## R14 — P1：非普通抽牌移走已知牌顶后，knownTopCount 不更新

- 位置：`battle.cpp:1103` resolve_choice 的 DRAW 分支；`:169` resample_hidden；类似直接移牌点还见 cards_colorless 的 add_from_draw。
- 抽牌堆有两张未知 Defend，再放已知 Strike 到顶，打 Secret Weapon 并选走 Strike 后，knownTopCount 应为 **0**，实际仍 **1**。
- 后续 resample_hidden 用这个残留计数，把原本未知的一张牌错误排除在随机化之外。隔离探针中的两张 Defend 同名，只验证计数不变量；错误冻结的后果由采样代码直接推出，没有冒称已测量策略胜率变化。
- 上轮 Headbutt “刚放到顶后立即采样”的测试不足以覆盖取走、消耗、自动打出等后续操作。

## 优先级与验收建议

1. 先处理 R01/R02/R03/R04/R05/R06 的共同出牌生命周期：源牌实体只移动一次，选择可暂停恢复，每次 replay 各自触发钩子，所有自动入口共用正确流程。
2. R08/R09/R10/R11 统一核对 damage/block 的来源、Unpowered、Unblockable 和多段 AttackCommand 边界，避免修正一个数值后仍漏触发链。
3. R13/R14 补齐玩家可见状态表示与已知信息维护；按兼容性要求重新版本化观测，不能让旧模型静默错位。
4. R07/R12 补生命周期和容量边界。把本轮组合轨迹纳入持续回归。

本轮不是全内容穷举，也没有证明其它原审计问题全部正确。没有进行客户端差分、所有内存路径的 sanitizer 扫描、正式模型重训或长期性能基准。**不建议把当前环境称为规则可靠的正式训练基座；可以继续调通训练工程，但正式比较策略前至少应消除卡牌增殖与主要结算错误。**

## 复现材料

全部新材料：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round2-20261028\`

- `probe.cpp` / `probe-results.txt`：32 条定向断言（包括 3 条正向控制/差异佐证）。高 HP/高能量等状态用于隔离规则，不代表默认战斗配置。
- `combo.cpp` / `combo-results.txt`：1600 场正常初始化双卡组合测试与失败动作轨迹。
- `run_fuzz.py` / `run-fuzz-results.txt`：新 1000 种子整局压力。
- `fuzz.exe` / `fuzz-results.txt`：直接用当前源码重编译第一轮 `deep-audit-20261028/fuzz.cpp` 后执行。
- `source-hashes.json`：本轮源码指纹。
- `reproduce.ps1`：重编译并运行新探针、组合扫描、整局压力和 pytest。诊断程序用 SUMMARY 记录失败，不用退出码表示语义通过；请读取失败计数。

运行：

```powershell
Set-Location D:\sts2_datacollection\sts2
& .\.scratch\deep-audit-round2-20261028\reproduce.ps1
```

本轮未改动前次报告或复现程序，未提交、回退或覆盖已有修复。
