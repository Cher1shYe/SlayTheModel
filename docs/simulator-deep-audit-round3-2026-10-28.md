# 第三轮扩展审计：药水、状态、遗物与整局衔接

日期：2026-10-28。项目：`D:\sts2_datacollection\sts2`。

本轮继续只测试与报告，没有修改模拟器、训练代码、现有测试或生成表。被测版本为 `a57a702` 加当前未提交修复；源码指纹保存于 `.scratch/deep-audit-round3-20261028/source-hashes.json`。测试结束复核这些源码哈希，变更数量为 0。

## 结论与范围

**在第二轮的 14 类问题之外，又确认 16 类支持内容中的问题；另把 2 类已标为 APPROXIMATE 的偏差和 2 类非 Ironclad 药水实现偏差单独列出。** 不能把本轮 31 条失败断言算成 31 个独立 bug，也不能把所有矩阵失败算成新根因。

第二轮的“自动打出带选择卡导致重复 UID”和“已知牌顶计数不随移牌更新”，在更大范围扫描中再次出现。现在还确认多个常用药水效果缺失、玩家镀层不衰减、怪物减益过早消失、事件胜利遗漏治疗等规则问题。现有单点回归不足以支持正式保真训练验收。

规则首要参考：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`。下文 `Potions/名称.cs`、`Powers/名称.cs`、`Relics/名称.cs`、`Monsters/名称.cs` 分别对应 `MegaCrit.Sts2.Core.Models.Potions`、`.Powers`、`.Relics`、`.Monsters` 命名空间目录；命令位于 `MegaCrit.Sts2.Core.Commands`。

定向探针使用隔离状态（高 HP、清空牌堆、指定效果等）；矩阵从正常 init 开始，仅执行合法动作，但使用自定义测试牌组，并非从初始爬塔奖励获取。没有真实客户端逐步差分执行。覆盖范围表仅称 EXECUTABLE 的项目本来就不等于 EFFECT_TESTED；本报告不是指责其已承诺所有规则准确，而是补足现有证据缺口。

## 本轮实际执行

| 测试 | 规模和结果 |
| --- | --- |
| 现有 pytest（本轮重跑） | **84 passed，23.38s**；测试耗时不作为性能基准 |
| 全部非多人卡两两组合 | 208 个 ID，21528 对，每对 2 个种子（50001 基础、50002 全升级），共 **43056 场、836920 步** |
| 上述不变量失败 | **68 场**：66 次重复 UID，2 次 knownTopCount > drawCount；0 截断 |
| 遗物 × 药水矩阵 | 241 个 relic_implemented 遗物 × 52 个 ironclad 药水，**12532 场、218582 步** |
| 遗物药水矩阵失败 | **6539 场**：6194 次重复 UID，345 次 knownTopCount > drawCount；0 截断 |
| 合计 | **55588 场、1055502 步**，6607 场不变量失败 |
| GCC 数组边界插桩 | 所有引擎 `.cpp` 和矩阵程序以 `-fsanitize=bounds -fno-sanitize-recover=bounds` 编译，完整矩阵退出码 **0**，`bounds-errors.txt` 为空 |
| 新定向探针 | **41 checks，31 failures，10 passes**；失败中 26 条属于主列表、3 条属于近似实现、2 条属于支持范围外药水 |

矩阵固定 20 张牌：4 张 A、4 张 B、6 Strike、6 Defend，80 HP，Ceremonial Beast。两两组合只排除 multiplayer 标记，包含特殊牌/状态牌等引擎输入，因此不能解释为每种牌组都能由当前完整爬塔奖励生成。

遗物药水矩阵固定 A=Headbutt、B=Havoc，用来放大已知脆弱路径。**6539 次失败并不表示 6539 个药水/遗物实现错误**，更不代表普通玩家失败概率。对每种不变量只打印前 12 个样例，汇总计数覆盖全部已测场景。每场发现第一个不变量失败后停止，最多 500 步；因此不覆盖损坏状态继续运行的后果。

自定义 bounds handler 在发现数组索引错误时输出源码行并退出 77。没有 libubsan，因此先单独插桩编译，再链接自定义处理器。此测试只覆盖 GCC bounds 检测到的数组访问，**不是完整 ASan、堆内存或所有未定义行为验证**。没有捕获越界不代表内存安全已被证明。

## T01：Liquid Memories 取回的牌没有变成零费

- 位置：`simulator/src/potions.cpp:304`；`battle.cpp` 的 DISCARD_TO_HAND 分支。
- 弃牌堆放 Bash，使用药水并完成选择，手中 Bash 应 **0 费**，实测 **2 费**。
- `Potions/LiquidMemories.cs` 明确调用 `EnergyCost.SetThisTurnOrUntilPlayed(0)` 后放入手牌。模拟器只移动牌。
- 优先级 P1，直接影响药水可提供的行动空间。

## T02：Bottled Potential 没有先把手牌洗回抽牌堆

- 位置：`potions.cpp:255`，只执行 shuffle(draw) 和 draw_cards(5)。
- 初始 10 张手牌、10 张抽牌堆，使用后正确应为 **手牌 5、抽牌堆 15**；实际 **手牌 10、抽牌堆 10**，满手时几乎无效果。
- `Potions/BottledPotential.cs` 顺序是 Add(Hand, Draw) → Shuffle → Draw(5)。
- 优先级 P1。

## T03：Clarity 缺少后续三回合的额外抽牌

- 位置：`potions.cpp:200`，只有立即 draw_cards(1)。
- 立即抽 1 张的正向控制通过；下一回合有足够抽牌堆时应抽 **6** 张，实际 **5**。
- `Potions/Clarity.cs` 还施加 ClarityPower 3；`Powers/ClarityPower.cs` 对起手抽牌 +1，并每次本方回合开始扣层数。
- 优先级 P1。

## T04：Radiant Tincture 缺少后续三回合的额外能量

- 位置：`potions.cpp:238`，只有当前回合 energy += 1。
- 当前 3→4 能量通过；下一回合应 **4**，实际 **3**。
- `Potions/RadiantTincture.cs` 还施加 RadiancePower 3；`Powers/RadiancePower.cs.AfterEnergyReset` 每次给 1 能量并扣层。
- 优先级 P1。

## T05：Shackling Potion 错误限制力量最低为零

- 位置：`potions.cpp:327–331`，跳过 strength<=0，且只减 min(strength,7)。
- 目标力量 0，应降到 **−7**，实际 **0**；目标力量 3，应降到 **−4**，实际 **0**。
- 本轮也验证目标原力量 3 在结束回合后恢复为 3，恢复路径控制通过，问题是施加量被截断。
- `Potions/ShacklingPotion.cs` 给所有目标施加 7 层临时负力量；`Powers/ShacklingPotionPower.cs` 派生 TemporaryStrengthPower，没有这个截断。
- 优先级 P1。

## T06：玩家 Plating 不衰减

- 位置：`battle.cpp:356` 给格挡，但玩家回合循环没有减少 PLATING；怪物侧另有衰减。
- 使用 Heart of Iron 得 7 镀层，完成一个敌方回合后应为 **6**，实际 **7**。
- `Powers/PlatingPower.cs.AfterTurnEnd` 在 Enemy side 结束时，对玩家也 Decrement。
- 优先级 P1；会系统性高估长期防御收益，并影响其它提供镀层的卡牌/遗物。

## T07：生成药水的卡池错误

- 位置：`potions.cpp:28–41` collect_type；`:130/144`。
- Colorless Potion 被限制为 colorless SKILL；C# 使用整个已解锁无色池，不限技能。200 个种子、600 个候选中，非技能数量为 **0**；运行结果与静态过滤逻辑一致，不是单凭未抽到就认定概率错误。
- Attack Potion 未限制为角色池。200 个种子、600 个候选中出现 **210 个非 Ironclad 池候选**，正确数量应为 0。
- `Potions/AttackPotion.cs` 使用 Owner.Character.CardPool；`Potions/ColorlessPotion.cs` 使用 ColorlessCardPool。
- 共享 collect_type 路径也用于 Skill/Power Potion，但本轮没有逐个定量采样这两种，因此仅标记为应继续核对的同源调用方。
- 优先级 P1；会使模拟器生成真实当前药水不会给出的牌。

## T08：药水发现卡选择不能跳过

- 位置：`potions.cpp` offer helper 调用 start_offer，未设置 optional。
- Attack Potion 的 pending.optional 实测 **false**，应为 **true**，合法动作因此没有跳过选择。
- `Potions/AttackPotion.cs` 的 FromChooseACardScreen 明确 canSkip:true；ColorlessPotion 亦如此。
- 优先级 P2；主定向断言只对 Attack Potion 执行。

## T09：从抽牌堆自动出牌遇空堆不洗弃牌堆

- 位置：`potions.cpp:266` Distilled Chaos 的 drawCount>0 循环；`cards_ironclad.cpp:94` Havoc 分支。
- 抽牌堆空、弃牌堆 3 张 Strike，Distilled Chaos 应洗牌后打 3 张，造成 **18**，实际 **0**。
- 抽牌堆空、弃牌堆 1 张 Strike，Havoc 应造成 **6**，实际 **0**。
- `Commands/CardPileCmd.cs.AutoPlayFromDrawPile` 在每次从牌堆取牌前调用 ShuffleIfNecessary，并先把待打出的牌移入 Play 堆。
- 优先级 P1。与第二轮自动出牌钩子遗漏不同，本项在进入出牌前就未取到应打出的牌。

## T10：Artifact 只覆盖少数入口，玩家减益与 Beetle Juice 绕过它

- 位置：`potions.cpp:250` 直接写怪物 SHRINK；`battle.cpp:72` add_player_power；`monsters.cpp:281` OP_POWER_PLAYER；手牌 Doubt 结算。
- 目标 Artifact 1，使用 Beetle Juice：应 SHRINK **0**、Artifact **0**，实际 **4/1**。
- 玩家 Artifact 1，回合末 Doubt：应 Weak **0** 并消耗 Artifact，实际 Weak **1**、Artifact **1**。
- Axebot 的 Hammer Uppercut 会依次施加 Weak 1、Frail 1。玩家 Artifact 1，在单独执行敌方回合后应 Weak **0**、Artifact **0**、Frail **1**；实际 **1/1/1**。Frail 1 作为第二个减益控制通过，证实该招式确实执行，而非测试命中了别的招式。
- Weak Potion 对怪物 Artifact 的控制测试通过，说明不是所有入口都错，而是实现不统一。
- `Powers/ArtifactPower.cs` 对目标收到的可见 Debuff 统一拦截并扣层，不限上述少数硬编码入口。
- 优先级 P1。玩家 Artifact 的正常来源覆盖本轮未做完整爬塔证明；敌方 Artifact 与 Beetle Juice 为已支持组合。

## T11：Foul Potion 击杀最后一个敌人时漏掉自身伤害

- 位置：`potions.cpp:354` 先逐个伤害怪物，再调用 damage_player；后者在 outcome 非 UNDECIDED 时直接返回。
- 玩家 20 HP、最后一个敌人 10 HP、无格挡，药水应同时伤害双方 12，玩家剩 **8**；实际玩家仍 **20**。
- `Potions/FoulPotion.cs` 对 CombatState.Creatures 批量调用 Damage；`Commands/CreatureCmd.cs` 对目标列表结算，不能因先处理敌人就取消玩家这部分代价。
- 优先级 P1，存在错误的无代价斩杀收益。本轮没有额外判定双方同时死亡时谁获胜，避免混入未验证的胜负顺序。

## T12：Self-Forming Clay 多次受伤只记一次

- 位置：`relics.cpp:584–585` 使用 set_aux(...,3) 覆盖，而非叠加。
- 同一回合两次各受到 1 点未格挡伤害，下一回合应获得 **6** 格挡，实际 **3**。
- `Relics/SelfFormingClay.cs` 每次伤害施加 SelfFormingClayPower 3；该能力为 Counter 堆叠。
- 优先级 P1；特别影响多段攻击敌人。测试为两次独立 damage_player，隔离验证计数。

## T13：Strength Potion 绕过 Ruined Helmet

- 位置：`potions.cpp` STRENGTH_POTION 直接修改 player.strength；`relics.cpp:624` 的 strength gain hook 没被调用。
- 持有尚未触发的 Ruined Helmet，使用力量药水，应首次力量增益翻倍为 **4**，实际 **2**。
- `Relics/RuinedHelmet.cs.TryModifyPowerAmountReceived` 对正力量统一修改，与力量来自卡牌或药水无关。
- 优先级 P2；其它直接写 strength 的路径是检查候选，不能因这一个复现就宣称全部同样错误。

## T14：Pantograph 治疗时机放错到 Boss 战后

- 位置：`relics.cpp:1123`，在 relics_combat_end(...,boss) 治疗；run.cpp 的进入 Boss 路径没有对应治疗。
- 玩家 30 HP、上限 80、持 Pantograph，开始 Boss 战时应 **55 HP**，实际 **30 HP**。
- `Relics/Pantograph.cs.AfterRoomEntered` 在进入 Boss room 时立即 Heal(25)，不是打赢后。
- 优先级 P1；直接改变能否存活到战斗结束。

## T15：事件战斗胜利跳过战后遗物钩子

- 位置：`run.cpp:751–754` 在 eventFight 分支直接 return，跳过后面的 relics_combat_end。
- Dense Vegetation 战斗胜利，玩家 30 HP、默认 Burning Blood，应恢复到 **36**，实际 **30**。
- 非事件战斗完全相同的 30 HP 胜利控制为 **36**，说明遗物并非没装备，而是事件分支漏调用。
- `Relics/BurningBlood.cs.AfterCombatVictory` 不排除事件来源的 CombatRoom。
- 测试手动设置胜利状态后进入 finish_combat，验证完成阶段，不冒称执行了整个事件战斗轨迹。
- 优先级 P1；其它战后遗物同属该调用缺口，但本轮定向数值只验证 Burning Blood。

## T16：怪物刚施加的 1 回合 Weak/Frail 在玩家行动前已消失

- 位置：`monsters.cpp:281` 未设置 duration skip；`battle.cpp:412–413` 无条件在敌回合末扣层。
- 定向执行 Axebot 的 Hammer Uppercut（生成状态表中本地 move=4）：招式施加 Weak 1、Frail 1，下一玩家回合两者应仍 **1**，实际均 **0**。
- 参考：`Monsters/Axebot.cs.HammerUppercutMove`；`Commands/PowerCmd.cs:103–105` 在向玩家施加 Debuff 时设置 SkipNextDurationTick；WeakPower/FrailPower 的 AfterTurnEnd 调用 TickDownDuration，该方法第一次清除 skip 标志而不减层。
- 已额外直接执行 monster_turn 验证招式确实施加了这两个减益；排除了用错怪物招式的测试错误。
- 优先级 P1；会系统性削弱部分敌人，影响收益评估与训练策略。

## 已声明为近似实现的具体偏差：不混入上述 16 类

### A01：The Boot 在格挡前抬高伤害

- `relics.cpp:561` 修改总伤害，发生在扣格挡之前。
- Strike 6 打 5 格挡，最终失血应由 1 抬到 **5**，实际 **1**。
- `Relics/TheBoot.cs` 使用 ModifyHpLostBeforeOsty，约束的是造成的 HP loss；现有 coverage 把这个事件遗物标为 APPROXIMATE。

### A02：History Course 复制原 UID，且前一回合没出牌仍反复触发

- `relics.cpp:414` 自动打出 lastPlayedCard 结构副本，未生成独立 UID；hasLastPlayed 也未按前一回合清理。
- 打一次 Strike 并结束回合后，原 UID 应只有 **1** 份，实际 **2**。下一回合不出任何牌再结束，下一轮仍额外造成 **6** 伤害，应为 **0**。
- `Relics/HistoryCourse.cs` 按 RoundNumber-1 查询历史，排除 IsDupe，并调用 CreateDupe()。
- coverage 已标 APPROXIMATE；其中 UID 冲突依然是危险的引擎不变量破坏，不应仅凭“近似”忽略。

## 支持范围外：两项内部 API 偏差

- **Ghost in a Jar**：本地实现给 Buffer 1，参考给 Intangible 1。探针实测 Intangible 为 0。当前生成表 ironclad=false、coverage UNSUPPORTED，不能把它列作正常 Ironclad 药水掉落漏洞，也不能用它证明当前声明范围中的 Intangible 可达。
- **Cosmic Concoction**：参考直接加入 3 张不同的升级无色牌，本地改成三选一且免费。实测药水后手牌 0、等待选择，而应直接手牌 3。当前为 Regent 池、ironclad=false，故单列。

## 正向控制与未覆盖

本轮正向控制包括：Clarity 立即抽牌、Radiant 当前加能量、Shackling 的已减力量恢复、普通胜利 Burning Blood、Fruit Juice 最大生命战后同步、Fire Potion 不吃力量/易伤、Block Potion 不吃敏捷/脆弱、Weak Potion 消耗怪物 Artifact、Axebot 第二减益。在同一引擎和探针下这些结果通过。

本轮没有重训模型，没有给出新的胜率或性能宣称。没有穷举所有状态/种子/怪物招式、全部事件流程、全部升级数值、多人或其他角色，也未验证完整实时客户端 RNG 对齐。大规模随机矩阵主要检验不变量，不能证明剩余内容规则正确；本轮新增确定问题来自参考源码核对和定向执行。

第二轮问题仍须保留，不因这轮报告更换列表而视为修复。建议下一步把“卡牌生命周期、伤害与状态入口、房间/战斗钩子”作为共享机制验收，再做逐个模型效果覆盖；继续只增加相同简单流程的随机局数，收益小于新增交互语义断言。

## 材料与复现

目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round3-20261028\`

- `probe.cpp` / `probe-results.txt`：41 项定向检查。
- `matrix.cpp` / `matrix-results.txt`：完整 55588 场组合扫描，含首批失败样例与汇总。
- `bounds_handler.cpp` / `bounds-errors.txt`：边界检测处理器及空错误日志。
- `source-hashes.json`：本轮源码指纹。
- `reproduce.ps1`：直接编译当前引擎源码并重新执行矩阵与定向探针；退出码 77 为数组越界，语义失败读取 FAIL/SUMMARY，不能只看退出码。

```powershell
Set-Location D:\sts2_datacollection\sts2
& .\.scratch\deep-audit-round3-20261028\reproduce.ps1
```

原有两轮报告和程序均保留，生产源码未改动。
