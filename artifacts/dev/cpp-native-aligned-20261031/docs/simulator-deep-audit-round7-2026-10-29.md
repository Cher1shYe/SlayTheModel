# 高速模拟器第七轮深度审计（2026-10-29）

## 结论

当前模拟器“能跑完、无越界、快照可重放”的工程基线仍然成立，但还不能作为 STS2
Ironclad 真实轨迹的高保真训练环境。第七轮没有修改生产代码，只在
`.scratch/deep-audit-round7-20261029` 增加探针和静态审计。

本轮 152 条核心定向断言中，22 条作为正向对照或行为说明通过，130 条失败；失败可按
21 组根因归类。最重要的系统性差距是：

1. `Rng.NextInt/NextBool` 与 .NET `System.Random` 不一致，长期轨迹必然分叉；
2. 27 张只通过降费或关键字变化的牌被误判为不可升级；
3. 8 个初始怪物 Power 和 5 个招式动态施加的 Power 只有数值、没有规则；
4. 房间遭遇袋、事件袋、遗物池没有实现参考的 GrabBag/去重/合法过滤语义；
5. 事件和遗物加牌绕过统一牌堆变更 hook，Bing Bong 还复制同一 UID；
6. 随机卡池混入 `Ancient/Event` 卡，多张事件卡又只有普通攻击/格挡回退；
7. 奖励、商店、遗物获得效果、公开观察和快照校验仍有大量可复现的语义差异。

没有发现可稳定复现的 P0 崩溃、越界或非终止。此结论只针对本轮动态探针、静态交叉检查、
既有矩阵扫描和本机反编译源码，表示“测试范围内找到的全部可复现问题”，不等同于对真实客户端
逐步差分后绝对不存在其他缺陷。

## 路径与材料

- 项目：`D:\sts2_datacollection\sts2`
- Git HEAD：`a57a7029b69a85aee13bf38d41efa9597672fad6`
- 测试对象：上述 HEAD 加当前未提交修复；本轮未修改生产源码或正式测试。
- 反编译参考：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- 本轮目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round7-20261029`
- 第一批定向探针：`probe.cpp`、`probe-r7c.cpp`
- 第二批定向探针：`probe_r7d.cpp`
- 第二批结果：`probe-r7d-results.txt`
- 第三批定向探针：`probe_r7e.cpp`
- 第三批结果：`probe-r7e-results.txt`
- 卡牌效果覆盖审计：`card_effect_coverage.py`、`card-effect-coverage.txt`
- 古代选项引用审计：`ancient_relic_reference_audit.py`、
  `ancient-relic-reference-audit.txt`
- 已标记遗物引用审计：`implemented_relic_reference_audit.py`、
  `implemented-relic-reference-audit.txt`
- RNG 差分：`rng_compare.cpp`、`rng_compare.exe`
- 升级能力静态审计：`upgrade_audit.py`、`upgrade-audit.txt`
- 怪物 Power 静态审计：`monster_power_audit.py`、`monster-power-audit.txt`
- 遗物获得效果静态审计：`relic_obtain_audit.py`、`relic-obtain-audit.txt`
- 事件/遗物引用审计：`static_event_relic_audit.py`、`static-event-relic-audit.txt`
- 正式规则回归：`simulator/tests/rules_regression.cpp`
- Python 测试：`tests`
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`

## 验证基线

| 检查 | 结果 |
|---|---:|
| `rules_test.exe` | 288 / 288 pass |
| 第六轮探针 | 36 / 36 pass |
| 第五轮探针 | 58 / 58 pass |
| 第四轮探针 | 30 / 30 pass |
| 第三轮兼容探针 | 41 / 41 pass |
| 第二轮兼容探针 | 32 / 32 pass |
| 第七轮 `probe_r7c` | 53 checks，46 fail |
| 第七轮 `probe_r7d` | 79 checks，64 fail |
| 第七轮 `probe_r7e` | 20 checks，20 fail |
| 109 个 `relic_implemented()` 标记项 | 109 / 109 至少有一个非标记行为引用 |
| RNG 对 .NET 前 1,000 seeds × 2,000,000 draws | seed 0 第 155,215 次 `Next(100)` 分叉，C++=16，.NET=15 |
| Python `pytest tests -q` | 83 passed，1 skipped |
| 原生 `bench run 1000` | 68.9 runs/s；combat step 约 1.7 us |

此前同一生产源码上的遗物/药水矩阵 12,532 场、遭遇扫描 5,340 场、整局扫描 300 局和
1,000 局随机快照扫描仍为 0 failure。它们说明边界和重放契约没有被破坏，不能证明下面这些
语义 oracle 正确。

## R7-01：RNG 不是 .NET 语义（P1）

`simulator/include/sts2/common.h:177-185` 先把内部随机整数转成 `float`，再用
`float * range` 得到 `NextInt`。参考
`MegaCrit.Sts2.Core.Random/Rng.cs` 使用 `System.Random.Next` 的 double
采样和整数缩放。

确定性差分：

- seed `0`；
- 第 `155,215` 次 `Next(100)`；
- C++ 实际 `16`；
- .NET 参考 `15`。

`next_bool()` 也经由同一条有偏路径，而参考调用 `_random.Next(2)`。`next_gaussian_int`
另有 C++ `lround` 与 C# `Math.Round`（banker's rounding）的舍入差异。

影响：卡奖励、商店、洗牌、事件、目标、怪物 AI 和地图都会在足够长的轨迹中分叉。现有
单步规则测试全部通过不能抵消这个问题。

## R7-02：27 张合法可升级牌被误判（P1）

`simulator/src/run.cpp:261` 的 `card_upgradable()` 只检查伤害、格挡和 `varUp`，没有检查
`costUp` 与 `flagsUp`。由生成表交叉得到 27 张只降费或只改关键字的牌：

`AGGRESSION_CARD`、`BARRICADE_CARD`、`DARK_EMBRACE_CARD`、`HAVOC`、
`HELLRAISER_CARD`、`INFERNAL_BLADE`、`JUGGLING_CARD`、`STOKE`、
`TANK_CARD`、`UNMOVABLE`、`ALCHEMIZE`、`ANOINTED`、`BEACON_OF_HOPE`、
`CALAMITY_CARD`、`DISCOVERY`、`MAYHEM_CARD`、`NOSTALGIA_CARD`、`PROLONG`、
`SCRAWL`、`SECRET_TECHNIQUE`、`SECRET_WEAPON`、`STRATAGEM`、
`APOTHEOSIS`、`DISTRACTION`、`ENTRENCH`、`HELLO_WORLD_CARD`、`WISH`。

动态证据：

- `cost_or_keyword_only_upgrades_are_upgradable expected=0 actual=27`；
- `rest_offers_cost_only_upgrade expected=1 actual=0`。

影响所有 `card_upgradable()` 调用点：休息升级、随机升级遗物/事件、休息/奖励合法性、
Silver Crucible、Lava Lamp、Razor Tooth、Apotheosis/Agression 等战斗内升级和卡奖励
升级掷骰。

## R7-03：13 个正常三幕怪物 Power 没有规则钩子（P1）

### 初始 Power

| Power / 怪物 | 预期 -> 实际 |
|---|---|
| `ILLUSION` EyeWithTeeth/Parafright | 致命伤后进入 non-removed revive 状态 -> 直接死亡 |
| `HIGH_VOLTAGE` Zapbot | 敌方回合结束 Strength +2 -> 仍 0 |
| `RAVENOUS` CorpseSlug | 友方死亡后 Strength +4 并眩晕 -> 仍 0、未眩晕 |
| `SHRIEK` TerrorEel | 未格挡伤害使 HP 到阈值后眩晕并移除 Power -> 不触发，Power 仍 70 |
| `SKITTISH` PhantasmalGardener | 本回合首次卡牌攻击造成未格挡伤害后 +6 Block -> 仍 0 |
| `SURPRISE` GremlinMerc | 死亡生成 Sneaky/Fat 且阻止战斗即时结束 -> 不生成 |
| `THIEVERY` GremlinMerc | Gimme 偷 20 金 -> 99 仍为 99 |
| `HATCH` ToughEgg | 首次 HATCH 行动恢复成 19-22 HP Hatchling 并移除 HATCH -> 未孵化，Power 仍 1 |

`MINION` 的战斗结束总状态在本轮两个正常对照中表现正确，但击杀奖励仍受 R7-12 影响。

### 招式动态施加的 Power

第二轮静态审计只扫描了 `MON_INNATE`，漏掉了 `MON_OPS` 中的 `OP_POWER_SELF`。以下 5 个
Power 也完全没有 `.cpp` 规则引用：

- `PLOW`：CeremonialBeast 150 HP 阶段转场、清 Strength、眩晕；
- `SOAR`：OwlMagistrate 的 powered card attack 50% 减伤；
- `FLUTTER`：ThievingHopper 50% 减伤、每次未格挡攻击减层并眩晕；
- `BURROWED`：Tunneler 破 Block 后眩晕、移除 Power；
- `STEAM_ERUPTION`：WaterfallGiant 死亡阶段和阻止即时战斗结束。

动态失败示例：`soar_halves_powered_card_attack expected=95 actual=90`；
`plow_threshold_stuns expected=1 actual=0`；
`steam_eruption_death_does_not_end_combat expected=0 actual=1`。

参考根：

- `MegaCrit.Sts2.Core.Models.Powers/{Plow,Soar,Flutter,Burrowed,SteamEruption}Power.cs`
- `MegaCrit.Sts2.Core.Models.Monsters/{CeremonialBeast,OwlMagistrate,ThievingHopper,Tunneler,WaterfallGiant}.cs`

## R7-04：遭遇袋和事件抽取不符合 GrabBag（P1）

`simulator/src/run.cpp:328-375` 在 weak/normal/elite 池中独立有放回抽样，再对 elite 额外
洗牌。参考 `ActModel.cs::GenerateRooms` 使用 `GrabBag.GrabAndRemove`，并通过
`AddWithoutRepeatingTags` 排除与上一项相同或共享 tag 的遭遇。

动态证据：

- seed 2 的前三个 weak encounter 已出现重复；
- seed 3 的前三个 elite bag 已出现重复；
- 当前生成表没有参考 encounter tags，因此即使偶然不重复也不能恢复精确分布。

事件抽取同样只使用 `eventBag[eventBagPos % eventBagN]`，没有参考
`RoomSet.EnsureNextEventIsValid` 的“未访问 + IsAllowed”循环。`event_allowed_now()` 在
全仓未被调用。

- Wongo 在 act 1、gold=0 时仍进入 pool；
- StoneOfAllTime 在无药水时仍进入 pool；
- UnrestSite 在满血时仍进入 pool。

## R7-05：卡奖励/额外遗物阶段错误（P1）

`RunContext::roll_card_reward` 对所有非 Boss 奖励使用普通 `3% rare / 37% uncommon`。
参考精英使用 `EliteEncounter` 赔率 `10% rare / 40% uncommon`。

- `elite_reward_uses_elite_rarity_odds expected=1 actual=0`；
- 4,000 个奖励种子扫描得到 rare rate 约 0（只出现 5 个 rare slot/12,000），期望约 10%。

Boss 虽然强制 rare，但参考仍把 rarity offset 重置为 `-0.05`；当前保留旧 offset：

- `boss_reward_resets_rarity_offset expected=1 actual=0`。

Silver Crucible 当前只记录 `silverCrucibleUses=3`，卡奖励没有读取该值：

- `silver_crucible_upgrades_card_reward expected=1 actual=0`。

参考 `SilverCrucible.cs` 还要在前三次修改卡奖励后递增 `TimesUsed`。

额外奖励钩子也不完整：

- BlackStar 精英战后应多一个 relic reward；动态 `expected=2 actual=1`；
- LavaRock 在 act 1 Boss 战后应增加两个 relic reward；动态 `expected=2 actual=0`；
- DreamCatcher 休息回血后应出现卡奖励；动态画面仍不是 `CARD_REWARD`。

## R7-06：事件/遗物加牌绕过统一牌堆 hook（P1）

`events.cpp::add_deck_card` 和 `relics.cpp::add_deck_card` 都直接调用
`RunContext::add_card_to_deck()`；`RunContext::add_card_to_deck()` 本身也没有
`AfterCardChangedPiles` 派发。

动态失败：

| 场景 | 预期 -> 实际 |
|---|---|
| Wellspring 加 Guilty + Lucky Fysh | gold +15 -> +0 |
| Wellspring 加 Guilty + Bing Bong | 2 张 -> 1 张 |
| 连续 5 次事件加牌 + Book of Five Rings | 触发一次 +15 HP -> 不触发 |
| Wellspring 加 curse + Darkstone Periapt | max HP +6 -> +0 |

Bing Bong 即使走卡奖励入口也只把同一 `Card` 值复制两次，UID 相同：

`bing_bong_reward_clone_has_distinct_uid expected=1 actual=0`。

参考 `BingBong.cs` 通过 `RunState.CloneCard` 创建新实体，并且 `LuckyFysh` 与
`BookOfFiveRings` 会对原始添加和 clone 各触发一次。

## R7-07：事件内容有多项确定性错误（P1）

- DenseVegetation 的 Rest 应执行 mimicked rest-site heal（30% + 回血遗物）；100 max HP、
  20 HP 时应到 50，当前直接回满到 100。
- StoneOfAllTime Push 应附魔 Vigorous；当前变成随机永久升级。
- AromaOfChaos LetGo 当前从所有 `CardId` 中直接抽，seed 5 可把牌变成 status `SOOT`。
- `add_random_common_card()` 实际允许 common/uncommon/rare；RoomFullOfCheese Gorge 在
  seed 1 加入了 uncommon `DRUM_OF_BATTLE_CARD`。
- SpiritGrafter Let It In 应加入固定 `Metamorphosis`；当前抽取随机 colorless，动态实际为 0。
- Wongo bargain bin 必须为 common；seed 1 实际买到 rare。
- Wellspring Bottle 和 PotionCourier Ransack 应消费 `PlayerRng.Rewards`；两者 counter
  实测均为 0。
- `event_rng()` 每次操作都重新构造同一 seed，TabletOfTruth 等多页事件不会延续参考
  `EventModel.Rng.Counter`。
- SapphireSeed 的 Sown 仍用升级替代；BrainLeech、RoomFullOfCheese 等本应产生的 5/8 选 1、
  8 选 2 选择被单次 RNG 自动加入替代。

`HungryForMushrooms` 的 15 点事件伤害加 FragrantMushroom 自身 15 点伤是正确行为，本轮已用
正向检查固定为 HP 70；不把它列为 bug。

## R7-08：遗物获得和行为仍有大量错误（P1）

动态确认：

| 遗物 | 预期 -> 实际 |
|---|---|
| CallingBell | 加 CurseOfTheBell 并给 3 relic rewards -> 无 curse |
| PreservedFog | 移除 5 张并加 Folly -> 只有移除 |
| ScrollBoxes | 花光金币并从 bundle 选择 -> gold 仍 500 |
| SereTalon | 2 个不同 curse + 3 张 Wish -> 0/0 |
| TanxsWhistle | 加 Whistle -> 0 |
| DistinguishedCape | 加 3 张 Apparition -> 0 |
| SwordOfStone | 5 精英后换 SwordOfJade -> 不换 |
| PumpkinCandle | 只在取得该遗物的 act 加 1 能量 -> 永久 +1 |
| VeryHotCocoa | 每场战斗第一回合 +4 -> 只有下一场 |
| WongoMysteryTicket | 第 5 场给 3 relic 后停止 -> 第 5/10/15 场重复 |
| ToyBox | 只融化自己给的 4 个 wax relic -> 可融掉 Strawberry |
| ToastyMittens | 首回合优先 exhaust 非 Innate -> 未做到 |
| BowlerHat | 所有获得金币 +20% -> 只有战斗奖励 |
| AmethystAubergine | 除最终 act Boss 外均 +10 gold -> act 1 Boss 为 0 |
| BigMushroom | 每场第一回合少抽 2 张 -> 仍抽 5 |
| BloodSoakedRose | 取得时加 Enthralled -> 0 |

第三批探针又确认了 4 个古代遗物错误：

| 遗物 | 预期 -> 实际 |
|---|---|
| JewelryBox | 加 1 张 Apotheosis -> 加随机 rare，Apotheosis 数为 0 |
| GlassEye | 生成 5 个 card-reward 选择项 -> 直接加 3 张牌 |
| SeaGlass | 生成三层稀有度的 15 张网格选择池 -> 直接加 3 张 uncommon |
| Claws | 选择最多 6 张牌并全部变为 Maul -> 任意变换，Maul 数为 0 |

静态比较 74 个有实际 `AfterObtained` 体的遗物，其中 16 个在 `relics.cpp` 中没有对应
`RelicId` 引用：

`BEAUTIFUL_BRACELET`、`BYRDPIP`、`DOLLYS_MIRROR`、`ELECTRIC_SHRYMP`、
`FAKE_SNECKO_EYE`、`GNARLED_HAMMER`、`GOLDEN_COMPASS`、`KIFUDA`、
`NUTRITIOUS_SOUP`、`ORRERY`、`PAELS_CLAW`、`PAELS_GROWTH`、`PAELS_TOOTH`、
`PUNCH_DAGGER`、`ROYAL_STAMP`、`TRI_BOOMERANG`。

其中 BeautifulBracelet、ElectricShrymp、GoldenCompass、NutritiousSoup、PaelsClaw、
PaelsGrowth、PaelsTooth、TriBoomerang 可由当前古代选项路径出现。

只扫 `AfterObtained` 仍会漏掉战斗、奖励、休息和地图 hook。把当前
`generate_ancient_options()` 中可出现的 91 个遗物 ID 扩展到全部 `.cpp` 交叉检查后，
另有 15 个在 `events.cpp` 之外完全没有引用：

`BEAUTIFUL_BRACELET`、`BLACK_STAR`、`DRIFTWOOD`、`ELECTRIC_SHRYMP`、`GLITTER`、
`GOLDEN_COMPASS`、`LAVA_ROCK`、`MEAT_CLEAVER`、`NUTRITIOUS_SOUP`、`PAELS_CLAW`、
`PAELS_EYE`、`PAELS_GROWTH`、`PAELS_TOOTH`、`TRI_BOOMERANG`、`WAR_HAMMER`。

这组遗漏覆盖奖励 reroll、精英战升级 4 张、额外回合、Cook/Clone 休息选项、奖励附魔和
Golden Path 地图替换；它们不是只少显示文本，而是会改变合法动作或奖励轨迹。

## R7-09：附魔和选择动作没有数据模型（P1）

`Card` 没有 enchantment identity/amount，`RunAction` 也没有卡牌、遗物 bundle、附魔或
休息 Cook/Clone 选择。因此 `Sown`、`Vigorous`、`Swift`、`Imbued`、`Glam`、`Clone`
等只能被升级、随机卡或空效果替代。

MassiveScroll 参考要求从 Ironclad + colorless 的
`CardMultiplayerConstraint.MultiplayerOnly` 池生成 3 张并选择 1 张；当前直接给一张
Ironclad uncommon。

这不是单个事件误差，而是训练动作空间和牌实体模型的共同缺口。

## R7-10：商店经济与补货不等价（P1）

- 参考 `MerchantEntry.Cost` 把 decimal hook 结果直接转 `int`；当前 `lround`。
  75 × 0.5 应为 37，当前 38。
- 当前 `roll_shop()` 复用卡奖励 `cardRarityOdds`；参考商店使用
  `RollWithoutChangingFutureOdds(Shop)`。同 seed 只改 reward pity offset，当前在前五张商品
  已产生 rarity 差异。
- shop relic pool 未排除 TheCourier 与 OldCoin；5,000-seed 扫描可命中。
- Courier 卡补货保持旧 type+rarity；参考 character slot 按原 type 重新 roll rarity。
- Courier relic 补货应使用新 `RollRarity`；当前保持旧 rarity。
- Courier potion 补货应走 out-of-combat potion factory；当前保持旧 rarity。
- 牌组/遗物达到内部数组容量时，购买仍返回成功并扣金，实际 item 被静默丢弃：
  `shop_rejects_relic_purchase_when_relic_bag_full expected=0 actual=1`；
  card 版本也有同样问题。

全局遗物抽取还不是参考的 relic grab bag/seen/front-back queue。
`run_random_relic()`、`random_shared_relic()` 使用即时加权或统一 rarity pool，会使
Wongo、UnrestSite、Elite、Capsule、CallingBell 等后续遗物序列都不等价。

## R7-11：PowderedDemise 结算时机错误（P1）

`simulator/src/potions.cpp:272` 立即造成 9 点伤害。参考
`PowderedDemise.cs` 施加 `DemisePower`，在该敌人回合结束后才造成 9 点
Unblockable/Unpowered 伤害。

动态：40 HP 敌人使用药水后立即变 31；应为 40，并等待敌方回合结束。

## R7-12：Minion 击杀奖励被误判为 fatal（P1）

`FEED` 和 `HAND_OF_GREED` 只检查“原先 alive，攻击后 not alive”。参考还要求目标所有
Power 的 `ShouldOwnerDeathTriggerFatal()` 为真；`MinionPower` 明确返回 false。

动态：

- Feed 击杀 GasBomb 后 max HP 500 -> 503，应仍为 500；
- HandOfGreed 击杀 GasBomb 后 combat gold 0 -> 20，应仍为 0。

战斗最终结束状态本身在“主怪死亡”和“仅 minion”两个对照中表现正确，问题限于 fatal 奖励
条件和对应的死亡 hook 语义。

## R7-13：公开观察仍丢失可见或可推断状态（P1，训练影响）

`observe.h` 声称公开编码包含玩家可见信息。实测以下状态对生成完全相同的公开向量，但会
改变后续合法动作或结算：

### 战斗

- `exhaustedThisTurn`
- `hpLostThisTurn`
- `nextTurnEnergy`
- `nextTurnDraw`
- `player.tookUnblockedDamageThisTurn`
- `attackSkillPlaysThisTurn`
- `blockCardPlaysThisTurn`
- Monster `offBalance`
- Monster `stunned`
- Monster `slowCardsThisTurn`
- Monster `tempStrengthLoss`
- hand card `etherealThisCombat`

`skillsLocked` 的公开状态不可见，但 `legal_actions()` 确实能区分，因此这是观察缺口，
不是动作掩码缺口。

### 整局

- `rewardIsBoss`
- 相同药水数量下 `potionSlots`
- `teaSetPending` 与 `nextCombatDazed` 相互碰撞
- `mawBankPurchased`
- `cardsAdded`
- `silverCrucibleUses`
- `nextCombatUpgradeHand`
- `emberTeaCombats`
- `furCoatCombats`
- `toyBoxCombats`
- `wongoCombats`
- `swordOfStoneWins`
- `paelsWingSkips`

SealOfGold 在战斗中真实扣的是 `battle.gold`，公开整局观察仍编码旧的 `rc.gold`。

Rampage 等牌的公开手牌特征不编码 `bonusDamage`；动作特征能通过最终攻击值区分它。
公开 run deck 仍按 CardId 聚合，不保留“哪一张实例升级”的身份。`activePlay.nextPlay`
也不暴露剩余 replay 进度。

这会向策略网络输入状态混叠，直接违反 `agent/run_env.py` 对 public observation 的说明。

## R7-14：容量边界不是原子失败（P2）

`RunContext::add_card_to_deck()` 在 `deckCount == MAX_DECK` 时静默返回，但调用方通常仍
报告成功：

- 满牌组卡奖励 TAKE_CARD 返回 true，牌没有加入；
- 满牌组 Wellspring 加诅咒返回 true，牌被丢弃；
- 满遗物袋 BUY_RELIC 返回 true、扣金、标记 sold/refill；
- 满牌组 BUY_CARD 也返回 true、扣金并触发后续 relic 逻辑。

这些边界在真实 C# 数据中可能少见，但训练 fuzz、长局或 replay 输入不应出现“动作成功但
没有状态效果”的非原子转换。

## R7-15：快照恢复缺少语义校验（P2）

对预填充的不同字节执行相同 seed 初始化后，`state_hash` 相同，说明当前布局没有出现
填充字节污染，这是正向结果。

但 `RunContext::restore()` 只检查 magic/version/size。把合法 blob 的 `deckCount` 改成
`MAX_DECK+1` 后，restore 仍返回 true；随后 observation/legal action 可读越界。

如果 snapshot 只来自同进程可信代码，这是健壮性缺口；Python API 和日志回放若接收外部
blob，则应按不可信输入处理。

## R7-16：随机卡池混入 Event/Ancient，事件卡效果也大多未实现（P1）

参考 `CardFactory.FilterForCombat` 明确排除 `Basic`、`Ancient` 和 `Event`。当前多个入口
没有维护这个边界：

- `battle.cpp:1513-1569` 的 `random_card_of_type()` 与 `transform_card()` 只排除
  `SPECIAL/BASIC`；
- `cards_colorless.cpp:17-65` 的 Discovery、Splash、Jackpot 卡池允许 Ironclad 的
  `Ancient` 卡；
- `potions.cpp:30-46` 的 Attack/Skill/Power Potion 卡池允许 Ironclad 的 `Ancient` 卡；
- `relics.cpp:889` 的 New Leaf/Astrolabe/Pandora 等变换池允许 `Ancient` 卡。

2,000-seed 单项扫描分别得到：

| 生成入口 | 混入非普通卡池次数 |
|---|---:|
| `random_card_of_type(SKILL, true)` | 175 |
| 战斗内 `transform_card()` | 126 |
| Attack Potion 的三张 offer | 173 |
| Discovery 的三张 offer | 147 |
| Run 层 New Leaf 变换 | 143 |

这不是低概率边界：`CARD_DEFS` 还缺少独立的 `Event` 稀有度，单靠 `Rarity::ANCIENT` 也无法
还原 Ironclad ancient 卡和 EventCardPool 的归属。

23/27 张 EventCardPool 卡没有显式效果分支，其中多数落入
`BattleContext::play_card_effect()` 的普通攻击/格挡回退。已动态确认：

| 卡牌 | 预期 -> 实际 |
|---|---|
| Apotheosis | 升级手牌中的 Strike -> 未升级 |
| Apparition | Intangible 1 -> 0 |
| Caltrops | Thorns 3 -> 0 |
| Clash | 手牌含非攻击牌时不可打出 -> 仍可打出 |
| Exterminate | 对所有敌人 3×4 -> 只造成 3 |
| Peck | 2×3 -> 只造成 2 |
| Maul | 5×2 -> 只造成 5 |
| Rip and Tear | 7×2 -> 只造成 7 |
| FeedingFrenzy | 施加 Strength 5 power -> 0 |
| NeowsFury | 从弃牌堆返回 2 张 -> 0 |
| Rebound | 下一张牌回牌堆顶 -> 未回牌堆顶 |

静态对照还显示 Distraction、DualWield、Enlightenment、HelloWorld、MadScience、
Metamorphosis、Squash、Stack、ToricToughness、Wish 和 Whistle 的附加规则缺失。
其中 Whistle 只结算伤害而未眩晕，MadScience 缺少类型/rider 状态，Wish/Stack/双牌选择
需要当前不存在的嵌套卡牌选择动作。

## R7-17：奖励和界面近似仍然改变训练问题

以下即使不作精确 C# 差分，也会直接改变训练 MDP：

- 药水奖励在有空位时直接加入，参考是 reward selection；
- 事件的多选卡、bundle、附魔选择被单个 RNG 自动结果替代；
- 精英 relic 和宝藏遗物在进入奖励/房间时自动获得，没有奖励保留/离开选择；
- only 3 个事件标为 IMPLEMENTED，22 个近似、29 个排除；
- 125 个事件遗物为 APPROXIMATE，部分仍是 no-op；
- 牌顶公开观察只编码前 16 张已知牌；
- 200 回合后直接判负属于保护逻辑，并非游戏规则。

这些不是重新发现的代码缺陷，但仍是真实轨迹训练前必须显式接受的误差来源。

## 推荐修复顺序

1. 先替换 RNG 并建立 .NET 向量差分，再修卡奖励赔率、商店 pity offset 和事件 RNG 持久化。
2. 修 `card_upgradable`，把所有 cost/flags upgrade 加入正式回归。
3. 修 13 个怪物 Power 和 minion fatal/flags；这些会改变战斗内动作价值。
4. 建统一 `CardPile.Add/Remove/Transform/Clone` 入口，事件/遗物/奖励全部经同一 hook，
   clone 必须生成新 UID。
5. 拆分 CardPool/rarity 数据模型，修所有战斗生成、药水、变换和事件卡入口；随后实现本
   报告列出的 EventCardPool 卡牌。
6. 实现 GrabBag、encounter tags、event visited/IsAllowed、relic front/back/seen queue。
7. 修商店、Silver Crucible、BlackStar/LavaRock/DreamCatcher 和本报告列出的遗物。
8. 增加附魔、嵌套卡/bundle 选择和 reward selection 动作；否则不能声称完整 A0 行为空间。
9. 升级公开观察 schema，并对 130 条失败探针逐项保留正向对照。
10. 最后修容量原子性和 snapshot 输入校验，重跑全部矩阵、长局和快照 fuzz。

观测/动作布局升级后必须重训 checkpoints，不能继续热载当前 v7/v6 权重。

## 可复现命令

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round7-20261029\rng_compare.exe'
& '.\.scratch\deep-audit-round7-20261029\probe_r7c.exe'
& '.\.scratch\deep-audit-round7-20261029\probe_r7d.exe'
& '.\.scratch\deep-audit-round7-20261029\probe_r7e.exe'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\upgrade_audit.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\monster_power_audit.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\relic_obtain_audit.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\card_effect_coverage.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\ancient_relic_reference_audit.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round7-20261029\implemented_relic_reference_audit.py'
& '.\simulator\rules_test.exe'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```
