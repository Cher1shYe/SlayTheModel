# 第五轮深度审计：内存安全、整局衔接、怪物能力与组合规则

日期：2026-10-28。本轮只增加诊断程序、结果与报告，未修复生产实现。

## 结论

不能认为第四轮的问题已覆盖主要缺口。本轮新增确认 **27 组主要问题**（包含旧观察问题的进一步扩展），另列 **1 组已标记 APPROXIMATE 的 Snecko Eye 偏差**和 **1 组第四轮 Hatchet 问题的终局状态扩展**。不同断言可能属于同一根因，不能把失败数当作 bug 数，也不将每组都宣称为首次发现。

优先级最高的是：

1. **遗物变牌卡池发生真实数组越界**，初始事件的合法选择即可触发。此前无插桩测试跑完不代表内存安全。
2. **Sozu + 战斗外 Entropic Brew 死循环**，环境 step 无法返回。
3. **营火/蛋遗物升级没有更新费用**，错误直接带入下一场战斗。
4. 多种玩家与怪物 Power 仅保存了数值，没有实现相应规则钩子。

尚不能承诺“所有问题都找完”。没有真实客户端逐步差分，也没有穷举全部事件、怪物阶段、卡牌组合和所有种子。本轮给出可复现的已确认结果及明确覆盖边界。

## 路径、版本与复现

- 项目：`D:\sts2_datacollection\sts2`
- HEAD：`a57a7029b69a85aee13bf38d41efa9597672fad6`，实际测试对象为 HEAD 加当前未提交修复。
- C# 规则参考根目录：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- 本轮测试及日志：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round5-20261028`
- 定向探针：该目录 `probe.cpp`、`probe-results.txt`。
- 扩展遭遇/整局扫描：该目录 `sweep.cpp`、`sweep-results.txt`、`sweep-errors.txt`。
- 越界最小复现：`probe.exe transform-bounds`，日志 `transform-results.txt`、`transform-errors.txt`。
- 整局越界轨迹：`run-bounds-trace.txt`、`run-bounds-errors.txt`。
- 死循环隔离测试：`timeout_check.py`、`timeout-results.txt`。
- 终局重复 UID：`duplicate-trace.txt`，以及 sweep 日志。
- 编译脚本：该目录 `reproduce.ps1`；源码指纹：`source-hashes.json`。
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`。

后文 C++ 路径相对此项目根目录；`Cards/`、`Powers/`、`Relics/`、`Potions/` 是参考目录下的 `MegaCrit.Sts2.Core.Models.Cards` 等命名空间文件夹；`Commands/`、`Factories/`、`Entities.Cards/` 分别对应 `MegaCrit.Sts2.Core.Commands`、`.Factories`、`.Entities.Cards`。

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round5-20261028\reproduce.ps1'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round5-20261028\timeout_check.py'
& '.\.scratch\deep-audit-round5-20261028\probe.exe' transform-bounds
& '.\.scratch\deep-audit-round5-20261028\sweep.exe' runs
```

`transform-bounds` 和插桩整局测试预期退出 77；不是编译失败。**不要直接运行 `probe.exe sozu-brew` 而不设外部超时**。`timeout_check.py` 在 3 秒后杀死并等待子进程退出。诊断探针本身可能在存在 FAIL 时退出 0，必须读 SUMMARY。脚本依赖第三轮 `.scratch\deep-audit-round3-20261028\bounds_handler.cpp`；`.scratch` 被 Git 忽略，交接时需复制。

## 本轮实际执行

| 检查 | 结果与限制 |
|---|---|
| 当前源码定向探针 | **58 checks，51 failures，7 passes**；包括正向控制，非随机错误率 |
| 现有原生回归及第二、三轮旧探针，使用本轮重新编译对象链接 | **153 + 32 + 41 = 226 项通过** |
| 遭遇扩展扫描 | 89 个非 INVALID 遭遇 × 60 配置，**5,340 场、183,610 步** |
| 扫描配置 | A0；24 张自定义牌组、随机 4 个互异 implemented 遗物、3 药水、300 HP；每步只选 legal_actions，克隆执行比对并检查牌堆/UID/公开观察有限数值 |
| 扫描结果 | **2 次终局 duplicate_uid**；**1 场达到 800 步上限**，不是通过；未观察到其余已检查不变量错误 |
| 300 次完整随机 run，无插桩首轮 | 19,422 步，未报状态/快照/重放不变量失败；但该结果被随后发现的越界削弱，不能据此认定安全 |
| 同种子完整 run，数组边界插桩 | 在首个种子 **810001**、第 0 步初始事件选择就退出 **77**，后续 299 个种子未完成插桩检查 |
| 最小 Astrolabe 复现 | 同样在 `relics.cpp:881` 的索引 128 触发 bounds handler |
| Sozu/Brew 超时测试 | 打印 ENTER 后 3 秒未返回，进程已终止；结合不推进循环的源码确认死循环 |
| Mummified Hand 选择扫描 | 100 个种子，49 次错过唯一应改费的 Bash |
| Entropic Brew 采样 | 2,000 次、6,000 瓶：rare 1,716（28.6%），Fruit Juice 0；分类/概率结论同时有静态代码依据 |

所有引擎 `.cpp` 以 `-O1 -fsanitize=bounds -fno-sanitize-recover=bounds` 独立重新编译，使用自定义 handler。测试驱动未插桩；这不是完整 ASan/UBSan，也不检测全部类型的越界。记录的生产 `.cpp/.h` 在本轮开始与结束哈希一致。

定向案例采用受控状态。怪物 Hardened Shell、Enrage、Slow 测试使用真实对应怪物的 spawn/自带能力；Painful Stabs/Nemesis 通过设置相应阶段能力隔离测试。不是所有案例都来自完整爬塔获取轨迹。

## R5-01：遗物变牌池越界（P0）

- `simulator/src/relics.cpp:873–881` 的 `transform_random_cards` 使用 `CardId pool[128]`，遍历符合条件的所有卡且无上限，写到索引 128。
- 证据：`BOUNDS_FAILURE ... relics.cpp line=881 index=128`。`RunContext.init(125,0)` 后 `add_relic(ASTROLABE)` 即复现；正常整局 seed 810001 初始 EVENT 上 legal action `(EVENT_CHOICE=12,index=2)` 也复现。
- 静态调用方包括 Astrolabe、Claws、New Leaf、Pandora's Box 等；不将每个调用方单独计 bug。
- 即使其中部分遗物标为 APPROXIMATE，也不能接受越界。无插桩可能静默破坏栈内存，因此“正常返回/克隆相同”不足以验收。

## R5-02：Sozu 药水阻止机制不一致，战斗外 Brew 死循环（P1）

- `simulator/src/run.cpp:910`：Entropic Brew 的 `while(potionCount < potionSlots)` 调用 `add_potion`，但 Sozu 使后者直接返回，数量不变，循环永不结束。
- 持有 Sozu 和预先获得的 Brew，3 秒隔离测试未返回。无需满槽或异常输入。
- 战斗路径则相反：Sozu + Brew 获得 **3** 瓶而非 0；Sozu + Alchemize 获得 **1** 瓶而非 0。
- 参考 `Relics/Sozu.cs.ShouldProcurePotion` 对所有获得药水路径阻止；`Potions/EntropicBrew.cs` 在 TryToProcure 失败时 break。
- Sozu 在覆盖表属于古代遗物近似项；这里单列主问题，因为死循环会阻塞训练，且战斗/整局接口相互矛盾。

## R5-03：永久升级只改标记，不改费用（P1）

- 营火升级 Corruption：升级应 2 费，deck 实测 3，下一场实际手牌仍 3。
- Toxic Egg 获得升级 Havoc：应 0 费，实测 1。
- `run.cpp:1007`、`:106` 只写 `upgraded=true`；`cards.cpp:26` 读取独立 `costForTurn`。奖励、事件、部分遗物还存在相同写法，需逐调用点审核，不应仅改两个复现入口。
- 参考 `Cards/Corruption.cs`、`Cards/Havoc.cs.OnUpgrade`，以及 `Models/CardModel.cs` 的升级流程。战斗内 `upgrade_card` 已同步费用，整局路径没有复用。

## R5-04—R5-13：玩家 Power 的规则与生命周期

| 编号/问题（均 P1） | 最小复现：应有 → 实测 | 代码与参考 |
|---|---|---|
| R5-04 Grapple 的核心机制错误，且不被 Artifact 阻止 | 实际打 Grapple 后 gain_block 应对目标造成 5 → 0；再打 Strike 应 6 → 11；回合结束应移除 → 仍 5；Artifact 应消费并阻止 → 未消费、仍施加 | `battle.cpp:716` 错当攻击加伤；`trigger_block_hooks` 缺钩子；debuff 白名单缺失。参考 `Powers/GrapplePower.cs`：由 Applier 获得格挡触发 Unpowered 伤害，AfterTurnEnd 移除 |
| R5-05 Colossus 易伤检查对象错误，持续层数清空 | 敌人易伤、攻击 10，应伤 5 → 10；只有玩家易伤，应伤 15 → 7；2 层过一敌方回合应 1 → 0 | `battle.cpp:729/476`；参考 `Powers/ColossusPower.cs` 检查 dealer.HasPower<VulnerablePower>()，TickDownDuration |
| R5-06 Gigantification 倍率、消耗和持续时间错误 | 喝药后两张 Strike 应 18、6 → 12、12；没攻击结束回合应仍 1 层 → 0 | `battle.cpp:707/427`；参考 `Powers/GigantificationPower.cs`：3 倍，下一个攻击命令结束减一层，不在回合末清空 |
| R5-07 FreeAttack 错误过期，破坏 X 费身份 | 未使用跨回合应仍 1 → 0；3 能量 Whirlwind 应造成 15、耗尽能量 → 0 伤害、剩 3 能量 | `battle.cpp:437/1459`；参考 `Powers/FreeAttackPower.cs` 不在回合末移除；`Entities.Cards/CardEnergyCost.cs.GetAmountToSpend` 对 CostsX 直接返回当前能量，不能把 X 改成普通 0 费 |
| R5-08 Cruelty 易伤倍率计算错误 | 10 基础伤害、Cruelty 50、易伤，应 10×(1.5+0.5)=20 → 22 | `battle.cpp:714` 用 1.5×1.5；参考 `Powers/CrueltyPower.cs.ModifyVulnerableMultiplier` 加到易伤倍率上 |
| R5-09 Howl From Beyond 时机错误且只处理一张 | 消耗堆两张 Howl，调用下一玩家回合开始，应各自动攻击、总 32 → 0 | `battle.cpp:397` 实现于玩家回合结束且 break；参考 `Cards/HowlFromBeyond.cs.BeforeHandDraw`，每张处于 Exhaust 的实例都触发 |
| R5-10 Drum of Battle 缺少回合抽牌前消耗 | 1 层、抽牌堆 10 张，下一回合应先消耗 1 → 0 | 能力被记录但 start_player_turn 无对应钩子；参考 `Powers/DrumOfBattlePower.cs.BeforeHandDrawLate`，按 Amount 消耗牌顶并按需洗牌 |
| R5-11 Aggression 忽略层数且发生在正常抽牌之后 | 2 层应回收升级 2 张 → 1；空抽牌堆、弃牌堆 1 Strike，应先回收升级 → 被普通抽牌洗回抽出，未升级 | `battle.cpp:338`；参考 `Powers/AggressionPower.cs.BeforeSideTurnStart`，Take(Amount)，先于手牌抽取 |
| R5-12 Automation 用本回合抽牌总数代替能力实例计数 | 施加后抽 7，跨回合再抽 3，应 +1 能量 → 0；施加前抽 7、施加后抽 3，应不触发 → +1 | `battle.cpp:524`；参考 `Powers/AutomationPower.cs` 每个实例独立 cardsLeft=10，不在回合边界重置 |
| R5-13 Stratagem 用随机单张替代手动多张选择 | 2 层洗牌应开启选择并取得 2 张 → 无 pending、随机取得 1 张 | `battle.cpp:503`；参考 `Powers/StratagemPower.cs.AfterShuffle` 的 FromSimpleGrid(...Amount) |

R5-07 特别说明：预期按本地参考代码推导，不能套用其他游戏版本中“免费 X 费仍保留能量”的直觉。此版本 GetAmountToSpend 对 X 费直接支付当前能量，FreeAttack 钩子不能将它改成固定 0 费。

## R5-14—R5-20：卡牌、药水、遗物交互

| 编号/问题 | 复现与影响 | 实现/参考 |
|---|---|---|
| R5-14 Brightest Flame 错误扣当前生命（P1） | 100/500 HP 应变 100/499 → 99/499；1/500 应变 1/499 → 1/500，连最大生命也不扣 | `cards_colorless.cpp:201`；`Cards/BrightestFlame.cs` → `Commands/CreatureCmd.cs.LoseMaxHp`，仅在当前 HP 超过新上限时扣当前 HP |
| R5-15 Snecko Oil 把 X 费变成固定费（P1） | 只有 Whirlwind 的手牌，喝药后应仍 X（-1）→ 2 | `potions.cpp:372`；`Potions/SneckoOil.cs` 明确排除 EnergyCost.CostsX |
| R5-16 Mummified Hand 没有过滤零费候选（P1） | Inflame 后手牌 Anger(0) 与 Bash(2)，唯一有效降费对象是 Bash；100 种子中 49 次仍 2 费 | `relics.cpp:685` 从全部手牌随机；`Relics/MummifiedHand.cs` 过滤 CostsEnergyOrStars |
| R5-17 Intimidating Helmet 看卡面费用而非实际资源消耗（P1） | 3 能量 Whirlwind 应得 4 格挡 → 0；FreeAttack 打 Bash 应 0 → 4。普通支付 2 能量 Bash 对照通过 | `relics.cpp:696`；`Relics/IntimidatingHelmet.cs.BeforeCardPlayed` 检查 cardPlay.Resources.EnergyValue，且触发时机也在出牌之前 |
| R5-18 Hand Drill 恰好破甲时漏触发（P1） | 敌方格挡 6，Strike 6，应施加易伤 2 → 0；格挡 5 的对照通过 | `battle.cpp:753` 额外要求 remaining>0；`Relics/HandDrill.cs` 只要求 DamageResult.WasBlockBroken |
| R5-19 Fisticuffs 不按实际伤害结果产格挡（P1） | Vigor 5 时应 12 格挡 → 7；目标 Intangible 时应 1 → 7；普通 7 的对照通过 | `cards_colorless.cpp:130` 预算伤害；`Cards/Fisticuffs.cs` 累加攻击结果 TotalDamage + OverkillDamage |
| R5-20 Omnislice 不按主目标实际伤害结果溅射（P1） | 主目标 Intangible，其他敌人应受 1 → 8；Vigor 5 时应受 13 → 8 | `cards_colorless.cpp:167`；`Cards/Omnislice.cs` 以首目标 DamageResult.TotalDamage + OverkillDamage 为溅射基数 |

## R5-21—R5-25：怪物能力仅有数值，无对应效果（P1）

| 编号 | 动态证据 | 参考与实现缺口 |
|---|---|---|
| R5-21 Hardened Shell | 正常 spawn Skulking Colony，自带 20；同回合两次 15，应总扣 20 → 30 | `Powers/HardenedShellPower.cs` 限制每玩家回合累计 HP 损失。`battle.cpp.damage_monster` 未实现限额及记录 |
| R5-22 Enrage | 正常 spawn Test Subject，玩家打 Defend，应 +2 力量 → 0 | `Powers/EnragePower.cs.AfterCardPlayed`；`after_card_played` 没有怪物侧技能触发 |
| R5-23 Slow | 正常 spawn Bygone Effigy，先打两张 Defend 再 Strike，应 floor(6×1.2)=7 → 6 | `Powers/SlowPower.cs` 统计已打出的卡并提高后续攻击伤害；当前只存 SLOW，没有计数/倍率 |
| R5-24 Painful Stabs | 设置该能力后敌方攻击造成 1 点未格挡伤害，应向弃牌堆加 Wound 1 → 0 | `Powers/PainfulStabsPower.cs.AfterAttack` 按未格挡 hit 数添伤口；`monster_attack_player` 缺钩子 |
| R5-25 Nemesis | 设置 Nemesis，首次怪物回合结束应 Intangible 1 → 0 | `Powers/NemesisPower.cs` 交替开关 Intangible，首次设置 SkipNextDurationTick；`monster_act` 无对应周期逻辑 |

参考 `Monsters/SkulkingColony.cs`、`BygoneEffigy.cs`、`TestSubject.cs` 可确认这些能力来自当前支持怪物，而非仅在理论上可构造的陌生能力。Painful Stabs/Nemesis 测试未走完整 Test Subject 复活链，属于阶段能力的最小单元复现。

## R5-26：Entropic Brew 战斗内生成池、稀有度与 RNG 错误（P1）

- `potions.cpp:310` 对 `ironclad && combatGen` 池均匀抽选，并使用通用 `rng`；potionRng.counter 完全不变。
- 参考 `Potions/EntropicBrew.cs` 在战斗内也调用 `PotionFactory.CreateRandomPotionOutOfCombat`，使用 CombatPotionGeneration；`Factories/PotionFactory.cs` 按 rare 10%、uncommon 25%、common 65% 选稀有度，不过滤 CanBeGeneratedInCombat。
- 2,000 次采样共 6,000 瓶，rare 1,716（28.6%），Fruit Juice 0。不是仅凭“没抽到”判错：实现明确过滤掉 Fruit Juice，其生成表 `ironclad=true, combatGen=false`；参考 OutOfCombat 工厂允许它。
- 本项与 R5-02 的死循环/Sozu 禁止是不同根因。

## R5-27：公开观察仍遗漏会改变转移的公开属性（P1，旧观察审计的扩展）

- 力量同为 5，一状态永久、一状态含 tempStrength=5：公开观察完全相同；结束回合实际力量相差 5。
- 同一张 Defend 当前都是 0 费，永久 freeCombat 与临时改费：状态和对应动作特征都相同，但未来费用不同。
- 抽牌堆同一张 Bash 的升级与未升级：公开观察相同，bag 只计卡 ID。玩家可查看抽牌堆构成与升级属性，此处不要求泄露隐藏顺序。
- 位置：`simulator/src/observe.cpp` 的 player scalars、card_features、push_card_bag、combat_action_features。即使模型接收当前动作特征，也无法区分前两个示例中的持续时间。
- 这一项不重复计入第四轮的第 9 个 Bomb/已知牌顶槽位限制；它验证的是另外的公开属性缺失。

## A1：Snecko Eye 的既有 APPROXIMATE 偏差

- mid-turn draw_cards 抽 8 张 Bash，全部仍原价 2；静态代码只有 `relics_hand_drawn` 在开局/回合手牌抽取后整体改费，draw_cards 没有逐张 ConfusedPower 钩子。
- 经 `relics_hand_drawn` 改费后 `costThisTurn=true`；参考 `Powers/ConfusedPower.cs.AfterCardDrawn` 使用 `SetThisCombat`，持续时间也不匹配。
- 8 张同价只作为采样佐证，不能单独排除随机巧合；确认依据是缺少逐张钩子与改费期限的代码，以及临时标记断言。
- `docs/a0-ironclad-coverage.md` 已将 SneckoEye 标为 APPROXIMATE，本报告不把它描述成违反“已完整支持”的承诺。

## E1：Hatchet 战斗胜利收尾造成重复 UID（第四轮 R4-04 扩展，P2）

- 扩展矩阵 seed 726885、726891 均发现；**两次 outcome 都已为 PLAYER_VICTORY**，没有证据表明这两个场景会在仍进行的战斗中刷出额外可用卡。
- 最小复现：敌方 HP 12、Panache 5、已打 4 张；打 Thrumming Hatchet 先造成 11 并入返回队列，随后 Panache 击杀；`finish_active_play` 的终局分支又将同一 UID 放入弃牌堆。实测两个容器各一份。
- 位置：`battle.cpp:1553` 的终局优先分支与返回队列；根因不是 queue_return_next_turn 缺少去重（该函数已有去重）。
- 重复 UID 不应无条件解释为正在进行的战斗实体复制漏洞，应修正终局收尾一致性并保留较低优先级。

## 覆盖边界和修复验收

- 本轮不是全量语义差分。怪物随机扫描主要检查不变量，不验证每个招式是否等价于 C#；没有逐个审计所有怪物 Power、所有事件分支和古代遗物次要效果。
- 遭遇扫描上限例：encounter 8、seed 720863，800 步。只记录为截断，尚未确认死循环，不计为新 bug。
- Sozu、Astrolabe 等涉及近似古代遗物，但数组越界和不返回不能用“近似规则”解释。
- 修复顺序：先 R5-01/02 保证内存和调用可返回；再 R5-03 保证永久牌组正确；随后补玩家/怪物 Power 事件钩子及伤害结果链；最后更新观察 schema 和迁移训练检查点。
- 修复后应将本轮最小复现并入正式回归，重跑带插桩的合法整局轨迹；旧 226 项全绿不足以验收。
- 本报告不修改实现、不调整预期来迎合现状，也未训练模型或声称新的胜率/速度。
