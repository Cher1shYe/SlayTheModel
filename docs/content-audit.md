# 内容与概率核查：模拟器 vs 原生 v0.111.0 反编译源码

2026-11-18 起（America/Los_Angeles）。用户要求：随机数序列不必与原生逐位一致，但训练时面对的东西必须与原生**分布一致**，包括会出现哪些内容、怪物数值与机制、地图生成、事件分支和所有可计算的概率。

方法：逐项阅读 `artifacts/native-source/v0.111.0/` 的原生实现，再对照 C++（`sim/src/`）的对应代码。只做静态对照，不是 DLL 执行对拍。本文件按核查顺序追加；“✓”表示逐行对照一致，“✗”表示确认不一致，“△”表示可疑或只在边界不同。

## 0. 结论速览

| 层 | 范围 | 状态 |
| --- | --- | --- |
| 存在性 | 卡牌/遗物/药水/事件/先古/怪物/遭遇的注册与池 | ✓（v13 注册审计）；23 个原标“近似实现”的事件已在 v16 核对并改标；33 件其他职业遗物未实现，Ironclad 正常掉落池不会抽到，若被抽到会明确报错 |
| 概率与生成 | 问号房、遭遇、地图、卡牌/药水/遗物/金币奖励、商店、宝箱、升阶 | 已核对，发现 6 处确定差异和 1 处训练配置问题，**均已在 v15 修正**（下表） |
| 机制 | 怪物（v9–v14 已做）、事件分支、遗物/卡牌/药水效果 | v16：全部事件出现条件、23 个原“近似”事件与 7 位先古已核对，修正 2 个先古选项池并补上 5 件无效果的先古遗物（第 8 节）；v17：怪物机制与回合触发（第 10 节）；v18：其余 41 个事件的选项效果已核对，修正 2 处 Maw Bank 差异（第 8 节）；v19：铁甲可得 265 件遗物效果已核对，修正 19 件，余下小缺口见第 12 节；v23–v27：随机数调用、药水、五个职业和无色/事件/状态/诅咒牌的效果已对照源码（第 13 节） |

### 确认的差异（v15 已修，`sim/tests/native_run_odds_v15.cpp` 回归）

| # | 项目 | 原生 | C++ | 影响 |
| --- | --- | --- | --- | --- |
| 1 | 问号房不出商店的规则 | 上一格**房间**是商店（含问号房抽中的商店），或下一格全是商店，则本次不能出商店（`RunManager.BuildRoomTypeBlacklist`，在记录本格历史之前判断） | `run.cpp` 在掷骰前已把 `lastPointType` 改成当前格，“上一格是商店”永远不成立；且用的是地图点类型而不是房间类型 | 商店后紧接问号房可能再出商店（原生不可能） |
| 2 | 精英战药水概率更新 | 门槛 = 当前概率 + 0.125；**按这个门槛**判掉落并更新（掉 −0.1，不掉 +0.1）（`PotionRewardOdds.Roll`） | 掉落按含加成门槛判，但更新按不含加成的门槛 | 精英战掉在加成区间时概率反而 +0.1，之后药水偏多 |
| 3 | 白兽雕像强制药水 | 直接返回掉落，不消耗随机数、不改概率 | 每场仍消耗一次并把概率 −0.1 | 持有期间概率一路下降，失去该遗物后几乎不掉药水 |
| 4 | 敌人逃跑后的金币 | 普通战金币按 `1 − 逃跑数/生成数` 比例缩放，比例为 0 时没有金币奖励；Gremlin Merc 另有规则（Fat Gremlin 逃跑给一半，被偷回则 0）（`RewardsSet`、`EncounterModel.CalculateGoldProportion`） | 一律给全额 | Thieving Hopper 逃跑原生不给金币，C++ 照给 |
| 5 | 商店遗物价格 | 普通 175 / 罕见 225 / 稀有 275 / 商店 200（`RelicModel.MerchantCost`） | 200 / 250 / 300 / 225 | 全部贵 25 |
| 6 | A6 起删牌价 | 100 起、每次 +50（`MerchantCardRemovalEntry`，Inflation） | 一直 75 起、每次 +25 | A10 下删牌便宜 25 起 |

小差异（△）：

- （v15 已修）原生 `Mathf.RoundToInt` / `Math.Round` 为“四舍六入五成双”，C++ `std::lround` 为“五入”。无色稀有牌基础价 150×1.15=172.5，原生 172，C++ 173；其余只在随机价格恰好落在 .5 时不同。v15 商店价格统一改为五成双；补货遗物的价格也改为按实际上架遗物的稀有度计算（原按掷出的稀有度，袋子回退时会错）。
- （未改）卡牌奖励某稀有度被抽空时，原生按 普通→罕见→稀有→普通 依次换；C++ 稀有抽空时重掷。对铁甲牌池实际上碰不到。

### 训练配置问题（v15 已按用户要求改为全解锁默认）

| # | 项目 | 说明 |
| --- | --- | --- |
| 7 | 第一幕永远是 Overgrowth | `RunContext.init` / `init_seed` 固定第一幕 Overgrowth；默认 `NativeProgressContext.underdocksUnlocked = false`。原生解锁后第一幕 50% Overgrowth、50% Underdocks。训练若用默认入口，**永远见不到 Underdocks 那一幕的怪、精英、Boss 和事件**。v15：用户指定模拟器默认为全解锁，`underdocksUnlocked` 默认 true，`init` / `init_seed` 改为按原生选第一幕。 |

## 1. 问号房（`Odds/UnknownMapPointOdds.cs`）

✓ 基础概率 普通怪 0.1 / 精英 −1（永不）/ 宝箱 0.02 / 商店 0.03，其余为事件；字典顺序 Monster、Elite、Treasure、Shop；未抽中的类型每次加自己的基础值，抽中的重置；每幕重置。
✓ Juzu Bracelet 去掉普通怪且其概率不增长；Golden Compass（指定幕）与 Lantern Key（第三幕）只剩事件，仍消耗一次随机数且不增长。
✓ 首局教程（`NumberOfRuns == 0`）：前两个问号必为事件、第三个必为普通怪；历史不含当前格，C++ 计数一致。训练默认 `numberOfRuns = 1`，不触发。
✗→✓（v15）不出商店规则，见差异 #1。

## 2. 卡牌奖励（`Odds/CardRarityOdds.cs`、`Factories/CardFactory.cs`）

✓ 普通战 稀有 3%（A7 1.49%）/ 罕见 37%；精英 10%（A7 5%）/ 40%；Boss 100% 稀有，用 0 偏移但仍重置保底；商店 9%（A7 4.5%）/ 37%。比较用严格小于。
✓ 保底偏移起点 −0.05，每张非稀有 +0.01（A7 +0.005），上限 0.4，出稀有重置。只有战斗来源的普通/精英/Boss 用并更新保底；商店用保底但不更新；其他来源用基础概率。
✓ 升级概率 = 幕序号 × 0.25（A7 ×0.125），稀有牌不升；随机数总是消耗；比较用 ≤。
✓ 一份奖励内不重复；Prismatic Gem / Dingy Rug 扩池；Lasting Candy、蛋类、Silver Crucible、Lava Lamp 等奖励钩子顺序。
△ 稀有度抽空的回退，见上。

## 3. 战斗奖励金币与药水（`Rewards/RewardsSet.cs`、`Odds/PotionRewardOdds.cs`、`Factories/PotionFactory.cs`）

✓ 金币 普通 10–20、精英 35–45、Boss 100；A3 ×0.75 后截断（7–15、26–33、75）。
✓ 药水基础 0.4，精英加 0.25×0.5；药水稀有度 稀有 ≤0.1、罕见 ≤0.35、其余普通；战斗内生成只用可在战斗生成的药水。
✗→✓（v15）精英更新、白兽雕像、逃跑比例，见差异 #2–#4。

## 4. 遭遇与事件抽取（`Models/ActModel.GenerateRooms`、`Runs/RunManager.GenerateRooms`、`Rooms/RoomSet.cs`）

✓ 弱怪数 Overgrowth/Underdocks 3、Hive/Glory 2；普通战到 `BaseNumberOfRooms`（15/15/14/13）；精英列 15 个；等权抓袋，优先不与上一场同标签/同遭遇，否则不加条件；袋空再装满；Boss `NextItem`；先古最后抽；A10 第三幕第二个 Boss 从其余 Boss 中抽；按访问次数取模。
✓ 事件袋 = 本幕事件 + 共享事件，按 epoch 过滤后洗牌。
待查：每个事件的出现条件 `IsAllowed`（金币、血量、遗物等），归入事件核对。

## 5. 遗物（`Factories/RelicFactory.cs`、`Runs/RelicGrabBag.cs`）

✓ 稀有度 普通 <0.5、罕见 <0.83、其余稀有（各调用处一致）；抽空按 商店→普通→罕见→稀有 回退，最后给 Circlet；共享袋可刷新，玩家袋不刷新（v11 已对池顺序）。
✓ 宝箱：`TreasureRoomRelics` 流掷稀有度，从共享袋前端取；金币 42–52，A3 ×0.75 截断。

## 6. 商店（`Entities/Merchant/*.cs`）

✓ 2 攻击 2 技能 1 能力 + 无色罕见、稀有各 1；一张打五折（再掷一次价格后整除 2）；卡牌基础价 50/75/150，无色 ×1.15，×[0.95, 1.05]；药水 3 瓶不重复，50/75/100 ×[0.95, 1.05]；遗物两件掷稀有度 + 一件商店稀有度，×[0.85, 1.15]；Membership Card ×0.5、The Courier ×0.8。
✗→✓（v15）遗物基础价、A6 删牌价，见差异 #5、#6。

## 7. 地图与升阶

✓ 各幕火堆数（Overgrowth/Underdocks 高斯 7±1 截到 6–7，Hive 6±1 截到 6–7，Glory 5–6）、问号数（高斯 12±1 截到 10–14，Hive/Glory 再 −1）、商店 3、精英 5（A1 起 8）。
✓ A1 精英 8、A2 先古回血 ×0.8 截断、A3 金币 ×0.75、A4 药水栏 −1、A5 进阶之灾、A7 稀有率与升级率、A8/A9 怪物数值（v14）、A10 双 Boss。
✗→✓（v15）A6 删牌价，见差异 #6。

## 8. 事件与先古（v16，2026-11-18 晚）

**出现条件**：57 个普通事件的 `IsAllowed` 逐个对照，全部一致（Dense Vegetation / Jungle Maze 的多人条件单人恒为真）。一处细节：判断“永恒”（不可删除）的牌表漏了 Forbidden Grimoire（死灵 Ancient 牌，铁甲正常拿不到），也没有考虑附魔 Tezcatara 余烬带来的永恒，已修。

**23 个原“近似实现”事件**：Aroma of Chaos、Dense Vegetation、Wellspring、Tablet of Truth、Unrest Site、Sapphire Seed、This or That、Room Full of Cheese、Potion Courier、Brain Leech、Stone of All Time、Welcome to Wongos、Reflections、Spirit Grafter、Lost Wisp 的选项、数值、随机范围、选牌约束和后续效果都与原生一致。这个标签是早期留下的，已改为“已实现”。核对的细节包括：

- 掉落用的随机流；
- 休息类效果会触发 Regal Pillow、Stone Humidifier、Dream Catcher；
- 事件选牌不受 Prismatic Gem 扩池影响（原生只对 IsCardReward 生效）；
- 不做升级判定（NoUpgradeRoll）。

**先古选项池**：Neow 在 v11 已用真实游戏对过；Darv、Vakuu、Tanx、Nonupeipe 一致；其余三位有问题：

| 先古 | 原生 | C++（v16 前） |
| --- | --- | --- |
| Tezcatara | 组 1 = Very Hot Cocoa、Yummy Cookie，牌组有基础打击时加 Nutritious Soup；组 2 = Biiig Hug、Storybook、Toasty Mittens；组 3 = Golden Compass、Pumpkin Candle、Toy Box、Seal of Gold | Seal of Gold 放在组 2（组 2 各 1/4、组 3 各 1/3）；Soup 无条件出现 |
| Pael | 已有事件宠物（Byrdpip、Pael's Legion 或牌组里的 Byrdonis Egg）时不提供 Pael's Legion；Pael's Claw 需要至少 3 张 Goopy 可附魔的牌（防御且未附魔） | Legion 总提供；Claw 按防御牌张数判断 |
| Orobas | Archaic Tooth 需要牌组有 Bash（其他职业起始牌在铁甲中拿不到） | Bash 或 Break 都算 |

**5 件“已实现”但没有效果的先古遗物**（拿到后什么都不发生）：

| 遗物（来源） | 原生效果，v16 已实现 |
| --- | --- |
| Nutritious Soup（Tezcatara） | 所有基础打击附魔 Tezcatara 余烬：基础费用永久为 0（升级不变）、永恒、受力量加成的攻击 +3 伤害 |
| Pael's Claw（Pael） | 所有可附魔的防御牌附魔 Goopy：加消耗；格挡 + (层数 − 1)；每打出一次层数 +1，并写回牌组（DeckVersion） |
| Tri-Boomerang（Tanx） | 获得时由玩家选 3 张攻击牌附魔 Instinct（受力量加成的攻击伤害 ×2）；可选不足 3 张时全部自动附魔，与原生选牌器一致 |
| War Hammer（Tanx） | 每赢一场精英战，随机升级 4 张可升级的牌（Niche 流） |
| Meat Cleaver（Tanx） | 火堆多一个“烹饪”：可删除的牌至少 2 张时可用，删 2 张、最大生命 +5；可取消、需手动确认 |

**配置**：Welcome to Wongos 的徽章取决于玩家存档的累计 Wongo 点数（每 2000 点一次）。默认 0，单局内几乎不可能拿到；属于玩家进度配置，未改。

**其余 41 个事件的选项效果（v18，2026-11-18 晚）**：逐个把原生事件类与 C++ 的初始化、选项可用性、选项效果和战后恢复并排对照，核对了数值、随机范围与所用随机流、选牌约束、奖励组成、多页流程与战斗事件的奖励。**39 个一致，2 处差异都与 Maw Bank 有关，已修**：

| 事件 | 原生 | C++（v18 前） |
| --- | --- | --- |
| Waterlogged Scriptorium | 付 55 / 99 金币用的是 `PlayerCmd.LoseGold`，不是商店购买，Maw Bank 不受影响 | 付钱后 Maw Bank 失效 |
| Fake Merchant | 假商人的货架就是商店遗物格（`NMerchantRelic`），购买走 `MerchantEntry.OnTryPurchaseWrapper` → `AfterItemPurchased`（不限房间，花费 > 0），Maw Bank 失效 | 购买后 Maw Bank 仍有效 |

原生 Maw Bank 只在 `AfterItemPurchased` 失效；C++ 的商店买卡/遗物/药水和商店删牌本来就正确。假商人价格只在商店房间吃折扣（`MerchantEntry.Cost` 判断 `MerchantRoom`），C++ 不打折，一致。回归测试 `sim/tests/native_event_options_v18.cpp`。

核对一致的包括：Endless Conveyor（菜品权重、去重、第 5 次固定海藻沙拉、各菜效果）、Crystal Sphere（11×11 格、四角清空、物品尺寸与放置重试、金币 10/30、诅咒 Doubt）、Tinker Time（类型与附加效果各随机取 2）、The Lantern Key 与 War Historian Repy（单人有钥匙时可领第二份）、Punch Off、Battleworn Dummy（三档奖励、超时无奖励）、Zen Weaver、Whispering Hollow、Wood Carvings、Spiraling Whirlpool 等。

**顺带发现（属于遗物效果，留待遗物核对修正）**：Lord's Parasol 原生进商店时白拿全部角色牌、无色牌、遗物、药水，并强制做一次不可取消的免费删牌；C++ 只白拿遗物。

## 9. 卡牌身份与编码（2026-11-18 晚，`parity/card_encoding_audit.py`）

目的：训练中网络在模拟器里选的牌，到原生客户端里必须是同一张；同一张牌两边送进网络的输入也必须相同。

**方法**：

- 对原生 DLL 注册表中的每张卡（596 个模型）、每个升级档，分别做两件事：
  - 取模拟器导出的一张新牌组卡，接口 `sts2_sim.public_card_template` 与真实牌组卡走同一个 `public_card_view`；
  - 按原生宿主 `DescribePublicCard` 的格式，用 DLL 注册数据构造同一张卡。
- 两者送进同一个 `public_obs._card` 和卡牌行编码器，比较公开事实的每个字段和 768 维输入的每个数。
- 同时检查身份映射：模拟器编号 → 原生模型 ID 是否一一对应；编号锁和动作键使用的映射表是否一致。
- 另外比对 C++ 实际执行用的打印伤害/格挡与 DLL 数值。

**结果**：1,148 个卡牌变体，**0 处差异**。

- 身份一一对应：GRAPPLE 是保留空槽，DEPRECATED_CARD 只用于原生旧存档兜底。
- 33 个改名别名（如 `AGGRESSION_CARD` → `AGGRESSION`、`SLOTH_STATUS` → `SLOTH`）都指向正确的原生卡。
- 类型、稀有度、目标、费用、X 费、星费、关键词、标签、动态数值、升级上限全部相同，编码后的网络输入逐位相同。
- 执行用的伤害/格挡也与 DLL 一致。

例外 2 个：Stardust 的 DLL 模板没有持有者时导出报错（已有带持有者的样例覆盖）；Mad Science 的注册模板未配置（类型为空），实际卡总是先由 Tinker Time 配置好类型才出现。

`parity/tests/test_card_encoding_audit.py` 锁定 0 差异，并验证篡改一张卡的关键词会被发现，防止核对永远空通过。

**范围**：这里核对的是新牌（未经修改）。战斗中的临时费用、临时关键词、附魔和加成走同一编码器，但没有逐卡穷举，由原生对照记录覆盖。网络用模型 ID 识别卡，不用显示名称；命令行显示的英文名由模型 ID 生成。

## 10. 怪物机制与回合触发（v17，2026-11-18 晚）

范围：全部活动怪物的专属触发和怪物施加的全部能力；数值部分 v14 已用 DLL 导出比过，见 [monster-number-audit.md](monster-number-audit.md)。

**方法**：

1. 列出原生 `Models/Monsters/*.cs` 中所有怪物覆写的钩子（死亡前/后、离场、受伤、血量变化、卡牌移动、毁灭死亡等），逐个看方法体。
2. 列出怪物施加的全部 68 种能力，抽出每种能力的触发方法和时机，与 C++ 实现对照。其中力量、易伤、虚弱等 12 种通用能力卡牌也在用、覆盖较多，这里没有逐行再看。
3. 重跑 `native_monster_ai.py --compare/--effects`：状态机剩余差异与第 8.4 节已核实的等价写法相同，招式效果剩余的 16 项都是已核实的特殊实现，没有新偏差。
4. 核对 C++ 回合末结算的时机：每只怪行动完立即结算，原生在敌方回合结束时统一结算。没有跨怪物的影响；被眩晕的怪同样会结算。

**确认并修正的差异**（ruleset v17，`sim/tests/native_monster_mechanics_v17.cpp`）：

| 怪物 / 能力 | 原生 | C++（v17 前） |
| --- | --- | --- |
| Shrinker Beetle（第一幕弱怪，Overgrowth Crawlers 也有） | Shrink −1 表示永久：只要甲虫活着，玩家攻击伤害一直 ×0.7，甲虫死亡时移除 | 改成 1 层，一回合后消失 |
| Slithering Strangler 的 Constrict | 施加者死亡时移除 | 不移除，玩家每回合末继续掉血 |
| Queen + Torch Head Amalgam（第三幕 Boss） | Amalgam 死亡时，如果 Queen 待出招是 Burn Bright For Me，立刻改成 Enrage | 没有，Queen 会多放一次 Burn Bright（同伴加力量、自己格挡 20） |
| Lagavulin Matriarch（Underdocks Boss） | 最后一个沉睡回合先移除镀甲（VeryEarly），再结算镀甲格挡（Early），所以醒来那回合没有格挡 | 先给格挡再移除，醒来那回合多约 10 格挡 |
| Vine Shambler 的 Tangled | 玩家攻击牌带 Entangled，费用 +层数；玩家回合末移除 | 能力没有任何效果，也不移除 |
| Ringing（Ceremonial Beast）/ Smog（Living Fog）/ Entangled | 都是卡牌附着（一张牌只能有一个），只限制被附着的牌；附着公开可见；Smog 在玩家回合末清除 | 限制所有牌，公开导出里没有这些附着，Smog 拖到下回合开始才清 |

**核对一致的**：

- 其余怪物钩子大多只是台词、动画、音效。Kin Priest 在随从全死后只说台词；Lagavulin Matriarch 的 IsShellAwake 只影响动画；Soul Fysh 的卡牌监听只影响动画；Test Subject 和 Cubex 的事件监听只改颜色和音效；Crusher/Rocket 的血量变化钩子只播放动画。
- 能力触发与时机一致：Flutter（Thieving Hopper：减伤 50%，降到 0 后眩晕）、Soar、Hard To Kill、Paper Cuts、Ravenous、Possess Strength/Speed、Tender、Territorial、High Voltage、Hatch、Escape Artist、Slumber、Slow（敌方回合开始清零）、Enrage、Thievery、Heist、Smoggy 的出牌限制本身。v10/v14 核对过的不再重复。

**小差异（未改）**：Lagavulin Matriarch 被打醒后，原生把意图显示为“眩晕”，C++ 显示为“沉睡”。下一回合同样不行动、之后出 Slash，规则等价，只是公开意图的标签不同。

**Thieving Hopper 偷牌规则（Swipe）**：v17 补充核对，与原生一致，未改规则。

- 候选是抽牌堆和弃牌堆中有 DeckVersion 的牌（战斗中生成的牌不算），按优先级取第一个非空档：
  1. 未附 Imbued 的罕见牌；
  2. 未附 Imbued 的普通 / 稀有 / 事件牌；
  3. 未附 Imbued 的基础 / 任务牌；
  4. 先古牌或附了 Imbued 的牌。
- 四档都空时从全部候选里挑；用 CombatCardGeneration 流均匀抽取；被眩晕时不偷；先偷后造成伤害。
- 偷走的牌同时离开牌组。打死跳蚤可以通过特殊卡牌奖励拿回；跳蚤逃跑则永久丢失。
- 新增测试锁定四档顺序、Imbued 降档、诅咒垫底和全空时的退回。原有 `monster_audit_regression` 已覆盖只偷牌组原有的牌、同档随机、眩晕不偷、死亡归还。

以上都是源码对照，不是 DLL 战斗对拍。

## 11. 尚未核对（下一阶段）

1. **事件**：出现条件、23 个原“近似”事件和先古（v16），其余 41 个事件的选项效果（v18）均已核对完（第 8 节）。
2. **遗物效果**：v19 已完成（第 12 节）。铁甲可得的 Shared / Ironclad / Event / Ancient 遗物按触发时机逐件核对，含数值；Lord's Parasol 已按原生重写，余下小缺口见第 12 节。
3. **卡牌效果**：v25–v27 已完成（第 13 节）。
4. **药水效果**：v24 已完成（第 13 节）。
5. 火堆其余选项。（休息回血 30% 向下取整、Regal Pillow 已核对一致；Thieving Hopper 偷牌规则已在 v17 核对一致。）

## 12. 遗物效果（v19，2026-11-18 晚至 11-19）

铁甲可得的 265 件遗物已逐件对照，修正 19 件，明细见 DEVLOG 第 23 节和 AGENTS.md。第 11 节第 2 项至此完成。

**v27 已修（DEVLOG 46）**：Unceasing Top 的空手检查、Ghost Seed 处理战斗中新进入的牌、History Course / Imbued / Mercury Hourglass 的时机、Gremlin Horn 在被阻止的死亡上触发、Intimidating Helmet 重放、Pen Nib 跨战斗。

**仍未处理的小缺口**：

- 同一时机的多个遗物按固定顺序结算，原生按遗物栏顺序；
- Lord's Parasol 白拿过程中弹出选牌时顺序不对：原生（`LordsParasol.PurchaseEverything`）逐件 `await` 购买，白拿到 Astrolabe 等带选牌的遗物时，要等选完才拿下一件遗物，最后拿药水；C++（`RunContext::lords_parasol_purchase_everything`）选牌界面打开后循环继续，后面的遗物进等待队列暂不生效，药水却当场拿走。例：Astrolabe 之后还有 Potion Belt（原生先加药水栏、多拿药水）或 Sozu（原生不再拿药水），C++ 结果不同；有 The Courier 时补货消耗随机数的先后也不同。强制免费删牌排在所有选牌之后这一点是对的。组合少见，影响小。

**A1 预览工作中发现的引擎差异（2026-11-19，已在 ruleset v20 修正）**：Perfected Strike 打出时没把自己算进打击牌张数（原生算）；伤害用 double 计算，少数乘数组合比原生 decimal 少 1；Unmovable 按出牌次数而不是获得格挡条数计数。详见 DEVLOG 第 29–30 节。

## 13. 随机数、药水与卡牌效果（v23–v27，2026-11-22 至 11-23）

都是读反编译源码并加定点回归测试，**不是原生 DLL 执行对拍**。

| 版本 | 范围 | 记录 |
| --- | --- | --- |
| v23 | 原生随机数调用：战斗生成牌的卡池、顺序、消耗次数，洗牌排序 | DEVLOG 42 |
| v24 | 药水效果 | DEVLOG 43 |
| v25 | 铁甲 90 张牌和相关能力 | DEVLOG 44 |
| v26 | 无色、事件、状态、诅咒、衍生、任务牌；玩家回合开始和结束的钩子顺序 | DEVLOG 45 |
| v27 | 静默、故障机器人、储君、亡灵法师各 91 张牌和相关能力；第 12 节的遗物时序 | DEVLOG 46 |
| v28 | 遗物上限 32 → 64（原生无上限）；整局冒烟测试（不是原生对照） | DEVLOG 48 |
| v30 | 铁甲可得 265 件遗物“原生钩子 ↔ 模拟器位置”复查；Tea of Discourtesy、Fur Coat 目标；Fur Coat 只比坐标为原生行为 | DEVLOG 55 |
| v29 | 遗物按原生时机与遗物栏顺序结算（回合开始各阶段、出牌后、消耗后、回合结束前）；Bag of Marbles 等目标与 Artifact；Lord's Parasol 逐件等待 | DEVLOG 54 |

默认全解锁时铁甲能通过 Kaleidoscope 拿到其他职业的牌，所以这四个职业也会进训练。


## 逐件核对台账（2026-11-25，ruleset v31）

全部 299 件遗物、595 张卡牌、65 种药水已逐行对照原生反编译源码，逐件结论在 [`item-audit.json`](item-audit.json)（状态：ok / fixed / not-implemented / out-of-scope，含日期、ruleset、备注），过程与修正见 DEVLOG 58–59。工具：`sim/tools/item_side_by_side.py`（并排显示原生类与模拟器代码）、`sim/tools/item_audit_mark.py`（更新台账）。这是读源码核对，不是原生执行对拍。
