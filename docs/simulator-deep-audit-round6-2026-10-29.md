# 高速模拟器第六轮深度审计（2026-10-29）

## 结论

第四、五轮已记录并修复的规则仍然通过，第五轮报告的 P0 越界和 Sozu/Brew 死循环也没有
复现。但当前版本仍有系统性正确性缺口。本轮新增 36 项检查，其中 6 项正向对照全部通过，
**30 项规则/观察断言失败**，归并为 8 组主要问题：

1. 8 张无色攻击牌没有走 `FromCard` 伤害修正链；
2. `Mummified Hand` 会把 X 费牌改成固定 0 费；
3. 正常三幕怪物的伤害上限与阶段生命周期大量缺失；
4. 多只在正常三幕可遇到的怪物即使拥有对应 Power，也没有回合/受击/死亡钩子；
5. 公开战斗观察仍漏掉多项会改变动作结果的可见计数；
6. `MembershipCard`、`TheCourier`、`LavaLamp` 和 `Planisphere` 被标为可执行但没有效果；
7. 战斗 RNG 流仍被折叠为一个通用 `rng`，选择、目标、AI 等流会互相扰动；
8. 已知事件/古代遗物近似、观察容量上限和 200 回合保护仍然存在。

本轮没有修改生产代码。新增内容只在被 Git 忽略的 `.scratch/deep-audit-round6-20261029`；
六个正向对照分别验证了普通伤害、铁甲卡牌 Pen Nib、Mummified Hand 普通牌降费、已有
Hardened Shell、关闭 Paper Cuts 后无效果，以及相同状态观察一致。因此失败不是探针无法命中
正常路径造成的。

本报告只声称上述受控状态与静态调用链有偏差，不能据此宣告“所有规则问题都已找完”。没有
真实客户端逐步差分，事件/遗物仍有已披露的 APPROXIMATE 项。

## 路径、版本与材料

- 项目：`D:\sts2_datacollection\sts2`
- Git HEAD：`a57a7029b69a85aee13bf38d41efa9597672fad6`
- 测试对象：HEAD 加当前全部未提交修复；不能只用 HEAD 复现。
- 权威规则参考：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- 本轮目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round6-20261029`
- 定向探针：本轮目录 `probe.cpp`、`probe-results.txt`、`probe-errors.txt`
- 编译复现：本轮目录 `reproduce.ps1`
- 源码指纹：本轮目录 `source-hashes.json`
- 历史规则测试：`D:\sts2_datacollection\sts2\simulator\tests\rules_regression.cpp`
- Python 测试：`D:\sts2_datacollection\sts2\tests`
- 第四轮报告：`D:\sts2_datacollection\sts2\docs\simulator-deep-audit-round4-2026-10-28.md`
- 第五轮报告：`D:\sts2_datacollection\sts2\docs\simulator-deep-audit-round5-2026-10-28.md`
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`

全部引擎 `.cpp` 使用 `-O1 -fsanitize=bounds -fno-sanitize-recover=bounds` 重新编译，
链接第三轮 `.scratch\deep-audit-round3-20261028\bounds_handler.cpp`。本轮 `probe-errors.txt`
为空。该插桩不是完整 ASan/UBSan，测试驱动自身也未插桩。

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round6-20261029\reproduce.ps1'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

## 验证结果

| 检查 | 结果 |
|---|---:|
| 第六轮定向探针 | 36 checks：6 pass，30 fail |
| 原生既有规则回归，新编译 | 233 / 233 pass |
| 第二轮原始探针，新编译 | 32 / 32 pass |
| 第三轮原始探针，新编译 | 41 / 41 pass |
| 第四轮原始探针，新编译 | 30 / 30 pass |
| 第五轮原始探针，新编译 | 58 / 58 pass |
| 遭遇扩展扫描 | 5,340 场、185,024 步、0 invariant failure、4 个 800 步截断 |
| 整局扫描 | 300 场、19,357 步、0 failure、0 capped |
| Sozu + 战斗外 Entropic Brew，3 秒限制 | 正常返回 |
| Python `pytest tests -q` | 84 passed |

4 个截断仍全部是 encounter 8 / ARCHITECT；第三轮增大步数检查已说明其在第 200 回合由
僵局保护结束。它们属于扫描预算与已知保护，不计为本轮新 bug。

矩阵和整局扫描没有逐步语义 oracle：它们只能说明边界、UID、克隆重放和合法动作不变量；
不能反证下面的规则错误，也不能把无失败解释成规则正确。

## R6-01：无色攻击牌绕过卡牌来源修正链（P1）

动态复现：Pen Nib 计数为 9，手牌 Flash of Steel 基础伤害 5。

- 预期：`5 × 2 = 10`；
- 实测：5；
- 正向对照：同为 Pen Nib 来源的铁甲 Strike 正确造成 12。

`simulator/src/cards_colorless.cpp` 中以下卡仍调用不带 `card` 的 `attack_monster`：

- Flash of Steel，`:144-145`
- Mind Blast，`:170-171`
- Rend，`:235-236`
- Seeker Strike，`:256-257`
- Volley，`:303-307`
- Bolas，`:353-354`
- Gold Axe，`:369-370`
- Jackpot，`:399-400`
- Salvo，`:422-423`

本地 C# 对应卡均使用 `DamageCmd.Attack(...).FromCard(this)`。因此 Pen Nib、Strike Dummy /
Miniature Cannon 等卡牌加法、卡牌倍率及其它未来 `cardSource` 钩子都会漏掉。第四轮只修了
Hand of Greed，没有消除这一整类路径。

参考：`MegaCrit.Sts2.Core.Models.Cards\{FlashOfSteel,MindBlast,Rend,SeekerStrike,Volley,Bolas,GoldAxe,Jackpot,Salvo}.cs`。

## R6-02：Mummified Hand 破坏 X 费身份（P2）

动态复现：手牌只有 Inflame 和 Whirlwind，打出 Inflame。

- 预期：Whirlwind 仍为 X 费 `-1`；
- 实测：变为固定 0 费。

`simulator/src/relics.cpp:690-704` 在“没有本地费用大于 0 的候选”时回退到任意手牌并设为
0 费。参考 `Relics/MummifiedHand.cs` 确实会执行第二次
`CostsEnergyOrStars(includeGlobalModifiers: true)` 查询，但查询结果没有赋值；X 费卡被
`!EnergyCost.CostsX` 排除，第二次查询也不会让它变成固定 0 费。

## R6-03：正常三幕怪物的伤害上限未实现（P1）

### HardToKill：Exoskeleton（第二幕普通）

- 拥有 HardToKill 9 时造成 15 点无格挡攻击；
- 预期 HP 损失 9；实测 15；
- `DamageDealt.unblocked` 同样为 15，不是 9。

参考：`Powers/HardToKillPower.cs` 的 `ModifyDamageCap` 返回 Amount 9。

### Slippery：Inklet（第一幕普通）及 Vantom（第一幕 Boss）

- Inklet 的 Slippery 1 受到 6 点攻击；
- 预期 HP 损失 1、Power 从 1 降为 0；
- 实测 HP 损失 6、Power 仍为 1。

参考：`Powers/SlipperyPower.cs` 将每段伤害上限设为 1，并在 `AfterDamageReceived` 中在
TotalDamage 非 0 时减 1。

`simulator/src/battle.cpp` 的 `damage_monster` 已实现 HardenedShell，但没有读取
`HARD_TO_KILL` 或 `SLIPPERY`。现有 Hardened Shell 正向对照通过，说明测试不是把“所有伤害”
误判成应被截断。

## R6-04：怪物死亡/逃跑/复活生命周期缺失（P1）

| 场景 | 预期 | 实测 |
|---|---|---|
| 第三幕 Axebot 的 Stock 2 被击杀 | 在原槽重生，Stock 变 1，战斗继续 | 怪物死亡，Stock 仍 2 |
| 第一幕 PhrogParasite 的 Infested 4 被击杀 | 战斗不结束，加入 4 个 Wriggler | outcome 直接变 PLAYER_VICTORY，Wriggler 0 |
| 第二幕 Decimillipede 单段死亡且其它段存活 | 进入 Reattach 复活流程 | `reviving=false` |
| 第二幕 ThievingHopper 第 5 次行动 Escape | 移除怪物并结束单怪战斗 | 怪物存活，战斗仍 UNDECIDED |
| 第三幕 Door 第一阶段死亡 | 生成 Doormaker 并继续 Boss 战 | 直接 PLAYER_VICTORY，Doormaker 0 |

实现缺口集中在 `simulator/src/battle.cpp` 的 `damage_monster` 死亡分支和
`simulator/src/monsters.cpp` 的移动执行：当前只特判 Test Subject 的 ADAPTABLE 复活；
`MON_INTENTS` 中的 ESCAPE 型意图只被记录，没有执行“移除实体”。

参考：
`Powers/StockPower.cs`、`Powers/InfestedPower.cs`、
`Powers/ReattachPower.cs`、`Powers/EscapeArtistPower.cs`、
`Powers/DoorRevivalPower.cs` 及对应 Monster 类。

这组问题会让训练环境提前结束战斗、遗漏敌人阶段、错误保留或丢失奖励，是当前最需要修复的
整局语义缺口之一。

## R6-05：正常三幕怪物 Power 仅有数值，没有规则钩子（P1）

本轮动态确认：

| Power / 怪物 | 应有行为 → 实测 |
|---|---|
| PaperCuts / ScrollOfBiting | 每次未格挡 powered attack 使玩家最大生命 -2 → 最大生命仍 500 |
| Territorial / Byrdonis | 敌方回合结束力量 +1 → 仍 0 |
| Rampart / LivingShield | 玩家回合开始给 TurretOperator 25 格挡 → 仍 0 |
| Slumber / SlumberingBeetle | 敌方回合结束从 3 减到 2 → 仍 3 |
| VitalSpark / InfestedPrism | 每回合首次受 unblocked powered attack 时玩家 +1 能量 → 仍 3 |
| PersonalHive / Entomancer | 玩家 powered attack 后向抽牌堆加入 Dazed → Dazed 0 |
| Imbalanced / BowlbugRock | 完全格挡 Headbutt 后进入失衡/DIZZY 分支 → 条件常量返回 false |

`simulator/src/monsters.cpp:55` 将 `COND_OFF_BALANCE` 固定写成 `return false`；其余 Power 在
`monsters_generated.inc` 的先天能力表中存在，但全仓没有对应 hook。

静态交叉检查还发现以下正常三幕可见能力没有运行时语义：

- `BACK_ATTACK_LEFT` / `BACK_ATTACK_RIGHT`（Kaiser Crab 成员标记）
- `CRAB_RAGE`（同伴死亡时 +5 力量、99 格挡）
- `GALVANIC`（GlobeHead；给 Power 牌施加 Galvanized 并在打出时造成伤害）
- `POSSESS_SPEED` / `POSSESS_STRENGTH`（The Forgotten / The Lost 死亡时返还偷取属性）
- `INFESTED`、`STOCK`、`REATTACH`、`DOOR_REVIVAL` 等生命周期项

参考根目录下对应的
`MegaCrit.Sts2.Core.Models.Powers/*.cs` 与 `MegaCrit.Sts2.Core.Models.Monsters/*.cs`。

## R6-06：公开观察仍遗漏会改变动作结果的计数（P1，训练影响）

以下状态对当前 `public_combat_observation` 与 `combat_action_features` 完全相同，但未来
转移不同：

1. Automation 初始 `cardsLeft=10` 对 `cardsLeft=1`：Power 图标显示的剩余抽牌数不同；
2. Hardened Shell 本回合尚未损失 HP 对已损失 5：公开显示剩余可损失量 20 对 15；
3. `unblockedHitsThisCombat=0` 对 `3`：Tear Asunder 命中数为 1 对 4；
4. `cardsPlayedThisCombat=0` 对 `10`：Gold Axe 伤害不同；

代码位置：`simulator/src/observe.cpp:141` 起的 public combat encoder 和 `:449` 起的 action
encoder；字段定义在 `simulator/include/sts2/battle.h:84,168,179,223`。这些不是隐藏抽牌顺序，
而是玩家可通过战斗历史或界面计数知道的信息。

修复时应同时升级 observation/action schema，并重训或明确拒绝旧 checkpoint。

## R6-07：四项“已实现”遗物实际无运行效果（P1/P2）

### MembershipCard

- C# 商店价格乘 0.5；
- 同 seed 同一商店，持有时价格与无遗物完全相同。

### TheCourier

- C# 商店价格乘 0.8，并在购买后补货；
- 同 seed 同一商店，价格与无遗物完全相同，当前购买逻辑也没有补货入口。

### LavaLamp

- 战斗中没有受到可计入的未格挡伤害时，本场所有可升级卡奖励应升级；
- 无伤胜利后 3 张奖励仍有 3 张未升级。

### Planisphere

- 每次进入 UNKNOWN 房间治疗 4；
- 当前源码没有房间进入钩子；该 ID 只在 `relics.cpp` 的 allow-list 中出现。

这四个遗物都在 `docs/a0-ironclad-coverage.md` 中标为 EXECUTABLE，其中前三个也可能从普通
商店/掉落入池，会让模型学习到错误的经济和奖励轨迹。

参考：`Relics/{MembershipCard,TheCourier,LavaLamp,Planisphere}.cs`。

## R6-08：战斗 RNG 流仍被折叠（P1，训练随机性）

参考运行状态拥有独立的 CombatCardGeneration、CombatPotionGeneration、
CombatCardSelection、CombatEnergyCosts、CombatTargets、MonsterAI 等流；
`RunRngType` 在 `simulator/include/sts2/run.h:30` 也有这些名字。

但 `BattleContext` 只有通用 `rng` 和 `potionRng`
（`simulator/include/sts2/battle.h:138-139`，初始化于 `simulator/src/battle.cpp:150-151`）。
卡牌选择、随机目标、Snecko 改费、洗牌和怪物选招都直接使用同一个 `rng`。例如：

- Mummified Hand 消耗的是参考的 CombatCardSelection 流，当前却推进怪物 AI/洗牌流；
- Snecko Oil / Confused 应使用 CombatEnergyCosts；
- 随机目标应使用 CombatTargets。

这不是单个随机数偏差，而是动作之间会产生额外因果耦合：多目标随机、选牌或遗物触发会改变
后续怪物招式。当前无插桩随机局能跑完不能证明轨迹与 C# 一致。

## 已知但不重复包装的限制

- README 已披露：54 个事件中 3 个完整、22 个近似、29 个不支持；125 个遗物为
  APPROXIMATE；附魔仍常用升级替代。
- 已知牌顶仍只完整编码前 16 张；Bomb 槽位已足够。
- 200 回合保护会把超长战斗直接判负，不等同真实客户端。
- 当前没有真实客户端逐步差分；本轮预期全部来自本地反编译 C#。
- 观察 schema v6 / action v5 的旧 checkpoint 已明确不兼容。

## 建议修复顺序与验收

1. 先修 R6-04 生命周期和 R6-03 伤害上限，避免 Boss/精英提前结束或伤害翻倍。
2. 修 R6-05 正常三幕 Power；每项保留“启用”和“关闭/无 Power”的正向对照。
3. 修 R6-01 的 FromCard 路径，再补 R6-02 的 X 费语义。
4. 修 R6-07 四项遗物，至少覆盖普通掉落入池、商店价格、无伤奖励和 UNKNOWN 房间。
5. 扩展观察 schema（R6-06）并拆分战斗 RNG 流（R6-08）；随后重训，不能热载旧权重。
6. 将本轮 30 个失败断言转成正式回归，保留 6 个正向对照；重跑 233 旧规则、旧四轮探针、
   带 bounds 的 5,340 场遭遇扫描和 300 个整局扫描。

不能用无 oracle 的随机局全绿替代上述语义断言；也不能通过调整期望、关闭断言或把缺失
Power 改标为 UNSUPPORTED 而继续让它们进入正常遭遇池来“修复”。
