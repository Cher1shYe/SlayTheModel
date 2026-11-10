# 第四轮第三部分：事件补齐（2026-11-08 起，进行中）

接续 `../round4-step2-resume-20261108/README.md`。目标：补齐交接文档 5.D 列出的原生事件。

**验证方式限制**：本机 .NET SDK、NuGet 缓存和原生样例宿主已在 11 月清理中删除，本步**没有实际 DLL 样例**。
全部实现只依据 v0.111.0 反编译源码，测试期望也来自源码阅读（`simulator/tests/native_step3_events.cpp`）。
状态标记为 IMPLEMENTED 只表示“已按源码实现”，不表示已与原生 DLL 差分。恢复 .NET 后应补样例。

## 基础设施修正（影响所有幕的事件序列）

- **事件池顺序**：普通幕原先按 C++ 枚举顺序拼列表，现按原生 `ActModel.AllEvents` + `ModelDb.AllSharedEvents` 声明顺序（`events.cpp` 内 `*_EVENT_ORDER`）。洗牌结果随之改变。
  未实现事件仍被排除，所以在全部补齐前，事件池长度和洗牌结果仍与原生不同。
- **解锁过滤**：`NativeProgressContext` 新增 `event1/2/3EpochRevealed`（默认 true），对应原生只按 epoch 移除 TrashHeap / Reflections / ColorfulPhilosophers。已接观察、Python 绑定和快照校验。
- **已访问事件**：`visitedEvents` 由 64 位扩为 2×64 位。原先编号 ≥64 的事件无法记为已访问。
- **观察事件位**：`PUB_EVENT_N` 64→96。观察 v14 布局因此变化（公开观察 71232→71267），v14 尚未提交或用于训练，因此未再升版本号。
- WarHistorianRepy 的 `IsAllowed` 恒为 false（只能经 Lantern Key 进入），已登记条件；它仍是 UNSUPPORTED，要和 TheLanternKey 一起做。

## 新实现的事件（17 个）

| 事件 | 幕 | 要点 |
| --- | --- | --- |
| WhisperingHollow（新注册） | 1 | 金币 35+NextInt(-9,10)；付钱换 2 个药水奖励，或用事件随机流变 1 张牌后受 9 点伤害 |
| WoodCarvings（新注册） | 1 | 基础牌变 Peck / Toric Toughness（新实体，走 Egg 钩子），或附魔 Slither；Slither 无可附魔牌时锁定 |
| ZenWeaver（新注册） | 2 | 50 金币得 2 张 Enlightenment；125/250 金币删 1/2 张牌 |
| Bugslayer | 2 | 得 Exterminate 或 Squash |
| InfestedAutomaton | 2 | 本角色牌池默认概率生成 1 张能力牌 / 原始 0 费非 X 牌，无升级判定 |
| MorphicGrove | 1 | 全部金币被偷 + 用事件随机流变 2 张，或 +5 最大生命 |
| ColorfulPhilosophers | 2 | 按原生颜色顺序列出其他已解锁角色，随机删到 3 个；选中后发普通/罕见/稀有各一组 3 选 1 奖励（带升级判定和卡牌奖励钩子） |
| RoundTeaParty | 3 | Royal Poison + 回满血；或两页：11 点伤害 + 从前端拉一件遗物 |
| TeaMaster | 1–2 | 50 金币 Bone Tea / 150 金币 Ember Tea / 免费 Tea of Discourtesy |
| LuminousChoir | 1 | 删 2 张 + 加 Spore Mind；或付 149−NextInt(0,50) 金币拉一件遗物 |
| DollRoom | 2 | 免费随机一个娃娃遗物；或受 5/15 伤害后从 StableShuffle（先按 ID 排序）结果中选 2 选 1 / 3 选 1 |
| Amalgamator | 2 | 删 2 张基础 Strike/Defend（新增网格过滤）后得 Ultimate Strike/Defend |
| TrashHeap | 底港 | 8 伤害 + 5 件固定遗物之一；或 100 金币 + 10 张固定牌之一（事件随机流） |
| TheFutureOfPotions | 共享 | 开始时为每瓶药水随机定牌型（普通药水不出能力）；用前 3 瓶之一换 3 选 1 同稀有度同类型奖励，全部升级；事件中不能用/丢药水 |
| SlipperyBridge | 共享 | 失去随机一张牌（首次不选基础牌），或受 3、4、5… 伤害重抽（避开上一张同名牌并记录已跳过的牌，`eventDeckMask`） |
| ColossalFlower | 2 | 逐层挖：35/75/135 金币，伤害 5/6/7，第三层可换 Pollinous Core |
| JungleMazeAdventure | 1 | 150/50 + (decimal)NextFloat(-15,15) 金币（按 .NET 7 位有效数字转换后截断）；独行另受 18 伤害 |

新增：Slither 附魔（抽到手牌时用战斗费用随机流设本场费用 0–3，表示方式同现有 Snecko Eye）；转换网格的 `eventRng` 标志（事件变牌用事件随机流）；`make_default_odds_event_cards`、`make_uniform_rarity_card_reward`、`queue_prepared_card_reward`。

## 顺带修复的既有问题

- **药水槽空位**：第二部分改成固定物理药槽后，多处仍按“紧凑列表”处理，属于真实错误：
  战斗结束同步只拷贝前 `potionCount` 个槽（空位后面的药水会丢失）；战斗中空位后的药水不能使用、观察中看不到；丢弃/局外使用/Stone of All Time 仍左移数组；快照校验拒绝带空位的药水栏。
  已全部改为按槽处理。Python `potions` 保持“已占用药水列表”的含义，新增 `potion_belt`（含 0 空位），ArmG 动作编码改用后者。
- 快照校验拒绝编号大于 NIMBLE 的附魔（静默猎手的 INKY 也会被误拒），已改为接受到 SLITHER。
- **牌组选择自动全选**：原生 `CardSelectorPrefs(prompt, n)` 的 MinSelect=MaxSelect，`RequireManualConfirmation=false`，删牌、变牌、升级在合格牌数 ≤ n 时都直接全选、不弹界面。C++ 原先只对升级/附魔类（网格 9 以上）这样做；删牌/变牌（6–8、Pael's Tooth 10）也会弹出只有一种结果的选择。变牌时原先由玩家点选顺序决定随机流顺序，原生按牌组顺序。已改为全部自动全选（删牌类咒诅优先，同原生排序）。这会改变 Astrolabe、Empty Cage、Biiig Hug 等在小牌组时的行为；`native_run_alignment` 中依赖旧行为的一项测试已按原生规则改写。
- 变牌选择排除 Quest 类型牌（原生 `FromDeckForTransformation`）。
- **Bowler Hat / Dragon Fruit**：v0.111.0 的 Bowler Hat 是 `ModifyGoldGained` 中 ×1.25、一次获得后截断；Dragon Fruit 每次获得金币只触发一次。C++ 原为 +20% 且把加成算作第二次获得（Dragon Fruit 触发两次），局外和战斗内两条路径都改了。`relic_contract`、`rules_regression` 中按旧规则写的 3 项期望已按原生源码更新（19→23 金币；Hand of Greed 36 金币、+1 最大生命）。这些旧期望来自基线规则，不是 DLL 样例。

## 已知限制

- Slither 与之后的其他改费操作的先后关系沿用现有“基础费用 + 本回合费用”模型，同交接文档 5.F 的通用费用修正栈缺口。
- LuminousChoir 的 `HasAvailableRelics` 为只读检查；原生同时会从遗物袋删除当前不允许的遗物，此副作用未模拟。
- TheLegendsWereTrue 需要 Spoils Map 的第二幕特殊地图与任务，未做。

## 结果

- C++：36 个程序全部通过（`cpp-tests.json`、`cpp-logs/`）；新测试 292 项检查。
- Python（无 torch）：167 通过，失败项与上一步相同（缺 torch 与 `rules_test` 路径），见 `python-no-torch/full-suite.txt`。两个 schema 测试的观察维度期望更新为 71267。
- 冒烟：`bench-1000.txt`，1000 局、0 异常、0 截断。

## 剩余未实现事件（17 个，不含占位 AROMA_PLACEHOLDER）

按依赖分组：

- 需新附魔：FieldOfManSizedHoles（PerfectFit：非首次洗牌时置于抽牌堆顶）、GraveOfTheForgotten（SoulsPower）、SelfHelpBook（Sharp 等）、Symbiote（Corrupted：强力攻击 ×1.5，打出时自伤 2）。都要改战斗结算。
- 需遗物移除/交易（IsTradable、IsUsedUp、AfterRemoved）：RelicTrader、RanwidTheElder。
- 需小游戏或多步交互：CrystalSphere（CrystalSphereMinigame）、TinkerTime、Trial、EndlessConveyor。
- 需专用战斗：TheLanternKey（+WarHistorianRepy）、BattlewornDummy、FakeMerchant、PunchOff。
- 需特殊地图/任务：TheLegendsWereTrue（Spoils Map）。
- 需宠物系统：ByrdonisNest。

改动前的文件备份在 `source-before/`（部分文件按扁平路径保存）。

## 2026-11-08 用户指示（无人值守批次）

用户要求：自行完成**附魔组**（FieldOfManSizedHoles、GraveOfTheForgotten、SelfHelpBook、Symbiote）和**遗物交易组**（RelicTrader、RanwidTheElder），过程随时记录。
特殊地图（TheLegendsWereTrue）、小游戏（CrystalSphere、TinkerTime、Trial、EndlessConveyor）、专用战斗（TheLanternKey/WarHistorianRepy、BattlewornDummy、FakeMerchant、PunchOff）、宠物（ByrdonisNest）、第三幕 Boss Aeonglass **本轮不做，保留为缺口**。
不提交、不推送、不改原生样例结果、不训练。用户可能明天提供 .NET 工具以恢复 DLL 样例。

### 进度日志
- 2026-11-08 08:10 开始附魔组：读完 4 个事件及 Sharp/Corrupted/SoulsPower/PerfectFit 源码。
- 08:3x 附魔战斗侧：新增 PERFECT_FIT/CORRUPTED/SOULS_POWER/SHARP；统一 enchant_card_damage（附魔加/乘先作用于牌面伤害，再加 Vigor/力量），覆盖 8 处出牌伤害 + Thrash 成长 + Osty 攻击；SoulsPower 去掉牌自身消耗。
- 08:5x **附魔组完成**（共 21 个事件已实现）：
  - FieldOfManSizedHoles：删 2 张后加 Normality（网格后置牌白名单加 NORMALITY），或给 1 张附 Perfect Fit。
  - Symbiote（第 2 幕起）：给攻击牌附 Corrupted（无可附魔牌时锁定），或用事件随机流变 1 张。
  - GraveOfTheForgotten：先加 Decay 再给带消耗的牌附 Souls Power，或得 Forgotten Soul。
  - SelfHelpBook：Sharp 2（攻击）/ Nimble 2（技能）/ Swift 2（能力），不满足的选项锁定；三项都不满足时只有“跳过”。
  - 新附魔：Sharp（强力攻击 + 层数）、Corrupted（强力攻击 ×1.5，每次打出后自伤 2 不可格挡）、Souls Power（去掉牌自身 Exhaust）、Perfect Fit（非初始洗牌后置于抽牌堆顶；多张时按原生监听顺序处理，未经 DLL 验证）。
  - 附魔伤害改为在 Vigor/力量之前作用于牌面伤害（原生 `Hook.ModifyDamage` 首步）。原 Vigorous 加成从 `calc_player_damage` 移到 `enchant_card_damage`（加法位置变化不改结果）；`enchantment_contract` 一项直接调用的单元测试相应改为先经附魔变换。
  - 事件变牌选择（kind 4）排除 Quest 牌。
  - 验证：C++ 36 个程序全过，新测试 346 项；冒烟 1000 局 0 异常。
- **环境问题（未处理）**：夜里 torch 2.15.0 已装完，但 `import torch` 会因 OpenMP 运行库重复加载（pip torch 自带 libomp 与 conda-forge 环境里的 libomp 冲突）直接中止进程，连带整个 pytest 崩溃。本轮按用户“暂不需要 torch”的说法未改环境；Python 测试改用 `python-no-torch/torch-stub/` 让 `import torch` 正常报缺失，结果与此前一致（167 通过）。可选修复：改装 conda-forge 的 pytorch，或让 torch 复用环境中的 libomp；需用户同意后再做。
- 09:xx **遗物交易组完成**（共 23 个事件已实现）：
  - 新增 `run_relic_tradable`（原生 IsTradable：非已用尽、无拾取效果、未熔化、无宠物、非 Starter/Event/Ancient；拾取效果名单由反编译 Relics/*.cs 生成，44 件）和 `run_remove_relic_at`（v0.111.0 没有遗物重写 AfterRemoved；移除槽位并同步移动计数/蜡制/熔化状态）。
  - RelicTrader（第 2 幕起，≥5 件可交易遗物）：开始时把可交易遗物按 ModelId 排序后用事件随机流洗牌取前 3；同时从遗物袋前端拉 3 件新遗物（各做一次稀有度判定，即使不交易也已从袋中取出）；选一组交换。
  - RanwidTheElder（第 2 幕起）：开始时随机选 1 瓶药水、1 件可交易遗物；给药水换 1 件遗物 / 付 100 金币换 1 件 / 给遗物换 2 件；事件中不能用/丢药水。
  - 验证：C++ 36 个程序全过，新测试 381 项；Python（torch 桩）167 通过；冒烟 1000 局 0 异常。
- **本轮结束状态**：34 个缺失事件已实现 23 个。剩余 11 个均为用户指定暂缓的缺口：
  TheLegendsWereTrue（特殊地图）；CrystalSphere、TinkerTime、Trial、EndlessConveyor（小游戏/多步）；TheLanternKey、WarHistorianRepy、BattlewornDummy、FakeMerchant、PunchOff（专用战斗）；ByrdonisNest（宠物）。另有第三幕 Boss Aeonglass。
  因为这些事件仍被排除在事件池外，各幕事件洗牌结果仍与原生不同。
- 用户随后要求按顺序继续补剩余缺口：小游戏类 → 专用战斗 → 特殊地图/宠物/Aeonglass。
- 10:xx EndlessConveyor 完成（24 个）：按权重抽菜（float 运算同原生），第 5n 次固定 Seapunk Salad，上一道不重复，Golden Fysh 不出现在第一道；可疑调料的药水奖励领完后才抽下一道（新增 event_resume_after_rewards），Jelly Liver 选牌变换后再抽。测试 411 项。
- 10:xx Trial 完成（25 个）：接受后事件随机流 NextInt(3) 选案；6 个结局（诅咒先加入再选牌/变牌，Doubt 本身可被变换）；“无名者有罪”发两组基础概率卡牌奖励（新增 make_default_odds_card_reward：非遭遇来源不用保底，无升级判定，含 IsCardReward 钩子）；拒绝后“加倍坚持”= 原生弹出放弃本局确认，按放弃处理（本局结束）。测试 429 项。
- 11:xx TinkerTime 准备：Card 新增 tinkerType/tinkerRider；新增 card_type/card_target（Mad Science 按实例），36 处“实例牌型/目标”读取改用它们（按 ID 生成卡池的静态读取保持不变）。回归全过。
- 12:xx **TinkerTime 完成（26 个），同时补上交接文档 5.A 的 Mad Science 缺口**：
  - 事件：三种牌型 TakeRandom(2) → 选型 → 该型三个附加效果 TakeRandom(2) → 选效果，生成配置好的 Mad Science。
  - Mad Science：攻击 12 伤（Violence ×3 次，Sapping 虚弱/易伤各 2，Choking Strangle 6）；技能 8 格挡（Energized +2 能量，Wisdom 抽 3，Chaos 生成本角色随机牌、本回合免费）；能力（Expertise 力量/敏捷 +2，Curious，Improvement）。升级加 Innate。
  - 新能力：Curious（能力牌费用 −层数，放在其他能力类改费之后、Chains of Binding 之前；与 Chains 的相对先后按原生应取决于施加顺序，未建模）、Improvement（战斗胜利后用战斗选牌随机流升级牌组中随机可升级牌，不放回）。
  - 结构改动：Card 加 tinkerType/tinkerRider；新增 card_type/card_target 按实例返回类型和目标，36 处实例读取改用（技能型 Mad Science 也算“会获得格挡”，可附 Nimble）。观察：卡牌特征与实例特征各 +2（CARD_FEAT_DIM 631，公开观察 72935、战斗 49248），v14 未冻结故未升版本号；Python 两处维度期望已更新。快照校验新字段只允许出现在 Mad Science 上。
  - 数据问题：导出的卡表中 Mad Science 格挡为 0（原生 BlockVar 8），代码里直接用 8。
  - 验证：C++ 36 个程序全过，新测试 447 项；Python 167；冒烟 1000 局 0 异常。
- 13:xx 开始 CrystalSphere（设计记录，便于中断后接手）：
  - 11×11 格；四角及其 2 层十字邻域先清开；物品按顺序放置（4×4 遗物、2 个 1×3 普通药水、2×2 稀有药水、2×2 普通/罕见/稀有卡牌奖励、2×2 诅咒、5 个 1×1 小金币、2 个 2×1 大金币），位置用事件随机流在可放位置（x 优先）中 NextItem；放置失败时原生会在不清空的情况下重试（最多 10 次），照搬。
  - 动作：新增 RunActionType CRYSTAL_SPHERE_SMALL / CRYSTAL_SPHERE_BIG，index = x*11+y，只能点仍隐藏的格；大工具清 8 邻域+自身（原生顺序：左右、上下、四角、中心）。物品所有格都清开时揭示（诅咒立即加 Doubt）。
  - 结束后按揭示顺序发奖励：药水在 ToReward 时用事件随机流选；金币/卡牌/遗物在发放填充时用事件随机流（金币 NextInt(a,a+1)，卡牌 3 选 1 同稀有度均匀含升级判定，遗物稀有度+前端拉取）。多个金币奖励分别领取（新增额外金币奖励槽）。
  - 观察：每格隐藏标记 + 已清开格上的物品类型；剩余次数。
- 14:xx **CrystalSphere 完成（27 个），小游戏组全部完成**：
  - 按上面的设计实现。选“预见未来”付 50+NextInt(1,50) 金币得 3 次，“分期付款”加 Debt 得 6 次。
  - 新动作 `CRYSTAL_SPHERE_SMALL` / `CRYSTAL_SPHERE_BIG`（index = x*11+y，仅隐藏格可点；ArmG 用现有“动作种类 + 槽位”编码，无需改 armg.py）。
  - 新状态 `CrystalSphereState`（隐藏位图、格→物品、物品类型/位置/是否放上、揭示顺序、剩余次数）和 `extraGoldRewards[8]`（领取 index 2..9，分别结算，Bowler Hat / Dragon Fruit 按次生效）。均接入快照校验与观察（运行观察 +1341 维，公开观察 74155）。
  - `draw_group` 增加随机流覆盖参数（CardCreationOptions.RngOverride）；卡牌奖励的升级判定也用该随机流。
  - 顺带修复：Python 端动作枚举与 `step` 范围检查漏了第二部分加的 `REST_HATCH`，Python 无法执行孵化；已补，并同步更新对应测试（改为“最大值+1”应被拒绝）。
  - 验证：C++ 36 个程序全过，新测试 520 项；Python 167；冒烟 1000 局 0 异常。
- 剩余：专用战斗（TheLanternKey、WarHistorianRepy、BattlewornDummy、FakeMerchant、PunchOff）、特殊地图（TheLegendsWereTrue）、宠物（ByrdonisNest）、Boss Aeonglass。
- **专用战斗事件（4 个完成，共 31 个）**：BattlewornDummy、TheLanternKey、PunchOff、WarHistorianRepy。
  - 这些事件战斗的怪物（Mysterious Knight、Punch Construct ×2、BattleFriend V1–V3、Fake Merchant）已在生成的怪物数据里，招式按已有数据驱动执行，本轮没有逐个与原生 AI 重新核对。
  - Battleworn Dummy：补上 BattlewornDummyTimeLimitPower（3 层，每个敌方回合结束 −1，归零时假人逃跑并记 RanOutOfTime，新增 `battlewornRanOutOfTime`）；该遭遇不给房间奖励；回到事件后 V1 一瓶随机药水、V2 用事件随机流 StableShuffle 升级 2 张、V3 一件前端遗物，超时则什么都没有。
  - **事件战斗奖励修正（影响已实现的 Dense Vegetation）**：原生事件遭遇是 Monster 房间，除 ShouldGiveRewards=false（仅 Battleworn）外都发普通战斗奖励（金币、药水判定、卡牌），再追加事件额外奖励。C++ 原先事件战斗一律不发普通奖励。现改为照原生发放；Fake Merchant 金币固定 300（不受 Poverty 影响）。第三轮 DLL 样例只测了 Dense Vegetation 的事件选项，没覆盖战后奖励，此项未经 DLL 验证。
  - The Lantern Key：还钥匙 100 金币；留钥匙则打 Mysterious Knight，额外奖励为 Lantern Key 卡（单卡奖励，可不拿）。牌组有 Lantern Key 时第三幕“?”房间固定为事件（仍消耗一次未知房随机数，同 Golden Compass），下一个事件改为 War Historian Repy。
  - War Historian Repy：笼子（History Course）/宝箱（2 药水 + 2 遗物），用掉一把钥匙；单人且还有第二把钥匙时可再选另一项。
  - Punch Off：抢（Injury + 遗物奖励）或打两只 Punch Construct（房间奖励 + 遗物 + 药水）。
  - 验证：C++ 36 个程序全过，新测试 552 项。
- **FakeMerchant 完成（32 个），专用战斗组全部完成**：
  - 开始时 9 件假遗物用事件随机流洗牌取 6 件，每件价格 round(50 × Shops.NextFloat(0.85,1.15))（.NET 银行家舍入）；事件房间不适用 Membership Card / The Courier 折扣（原生只在商店房间生效）。可买、可离开。
  - 在该事件中使用 Foul Potion 开战：Fake Merchant 战斗（房间奖励，金币固定 300）+ Fake Merchant's Rug + 所有未售出的假遗物。
  - **Foul Potion 局外使用修正**：原生只能在商人房间（+100 金币）或 Fake Merchant 事件中使用；C++ 原来在任何局外界面都能用并得 100 金币，已限制。
  - 事件选项上限 4→8、eventData 4→8（观察随之变化，公开观察 75347），以容纳 6 件商品 + 离开。
  - 验证：C++ 36 个程序全过，新测试 575 项；Python 167；冒烟 1000 局 0 异常。
- **地图生成对照（重要发现，进行中）**：做 Spoils Map 前核对了 C++ 普通地图生成，用原生探针录下的真实地图（4 个种子、6 张幕地图，含坐标与连线，`map-parity/compare_maps.py`）对照：
  - 原本 6 张全部不同（每张 40 多处）。原因：① 房间类型分配原生最多 3 轮、每轮只洗未分配的点，C++ 一轮洗所有点；② 原生 `PruneAndRepair`（剪枝后把类型数补回，最多 3 轮），C++ 只剪枝不修补；③ “前 6 行不能放休息/精英”C++ 写成前 5 行；④ 原生点的父子集合是 .NET HashSet（删除后复用空槽），C++ 用普通数组（已按 HashSet 语义模拟）。
  - 修正后：1/6 完全一致，其余每张仅差 2–14 处（`map-parity/result-step1.txt`），继续排查后处理（居中/展开/拉直）与剪枝细节。
  - 这些修改会改变所有局的地图，是之前未被发现的普通路径偏差。
- **地图生成已与原生逐点一致（6/6）**：继续排查后又修了三处——⑤ 原生按排序字典（Ordinal 字符串键）顺序处理重复路段组，C++ 按首次出现顺序；⑥ 原生“断开父子连接”会处理完首个可断路段里的所有连接，C++ 断一条就停；⑦ **关键**：原生 PruneAllButLast 在“已剪掉的数量”达到 n−1 时停止，C++ 写成“遍历到最后一个下标”就停，导致前面的路段剪不掉时原生仍会去剪最后一个而 C++ 不会。另修了 StraightenPaths 右移后原生会再检查一次该点、C++ 跳过的问题。
  - 现在用原生探针录下的 4 个种子、6 张幕地图（含 Underdocks/Overgrowth/Hive/Glory）全部逐点（坐标、类型、连线）一致（`map-parity/result-final.txt`）。这是本轮唯一有原生实际数据对照的部分。
  - 性能：分组仍用紧凑键，只对重复组生成字符串排序，速度与修改前相同（约 174 局/秒）。
  - 影响：所有局的地图都会变化（此前与原生不同）。C++ 36 个程序、Python 167 项均通过。

### 第 14 批：TheLegendsWereTrue / Spoils Map（特殊地图）— 2026-11-09

- **事件**：第一幕、牌组非空、HP≥10 才出现。选项 0「拿地图」：Spoils Map（任务牌，不可打出）加入牌组；选项 1「慢慢找出口」：受 8 点无视格挡伤害，然后用 Rewards RNG 从铁甲+共享药水池抽 1 瓶，作为自定义奖励（可拒领）。
- **特殊地图**（`map.cpp: generate_spoils_act_map`，逐行按原生 `SpoilsActMap.cs` 移植）：第二幕（index 1）建图时牌组里有 Spoils Map 就换成沙漏形地图，`Rng(seed, "spoils_map")`，宝箱固定在第 `mapLength−7` 行中列且该行只有它；距宝箱 ≤3 行时路径优先朝中列走；不做居中/扩散/拉直后处理；房间类型分配与剪枝复用已和原生逐点一致的普通地图逻辑（两者规则集原生代码相同）。
- **钩子顺序**：原生先遍历牌组卡牌、再遍历遗物，所以第二幕同时有 Golden Compass 时，金色路线覆盖 Spoils 地图，任务标记放到金色路线第一个宝箱（第 8 行）。
- **任务结算**：在任务点开宝箱时，先拿宝箱金币，再每张 Spoils Map 给 600 金（走正常得金钩子，Bowler 等生效）并移出牌组，然后照常给宝箱遗物。第二幕途中删掉这张牌，任务随之消失。其他宝箱、第三幕都不触发。
- **顺带修正**：Thieving Hopper 偷牌优先级——原生把任务牌和基础牌放同一档、Ancient 单独一档；C++ 之前把它们都放最后。（原生 Imbued 附魔档 C++ 没有该附魔，未移植。）Dolly's Mirror 原生不能复制任务牌，所以一局最多一张 Spoils Map。
- **新状态/接口**：`spoilsQuestRow/Col`（快照校验）；公开观察末尾 +3 维（是否有任务、行、列），公开观察 75347→75350；Python 绑定 `spoils_quest`。
- **验证**：C++ 36 个程序全过（step3 事件测试 1373 项，其中本批覆盖 5 个种子×2 个进阶的地图结构、事件两选项、有/无地图牌、快照、结算、删牌、Golden Compass、第三幕）；Python 167 通过（失败/错误仍只是 torch 桩与缺 rules_test 二进制，和之前相同）；1000 局冒烟 0 异常、约 168 局/秒；普通地图对照仍 6/6 一致。
- **限制**：本地没有原生拿 Spoils Map 的录像，**Spoils 地图本身没有原生实测对照**，只按源码移植+结构检查；原生 SpoilsCoord 是每张牌各自记的，C++ 合成一个运行级坐标（因为一局最多一张，结果相同）。
- **剩余**：ByrdonisNest（宠物系统）、第三幕 Boss Aeonglass。

### 第 15 批：ByrdonisNest（宠物）— 2026-11-09

- 宠物系统本体（鸟蛋卡、休息点「孵化」、Byrdpip 遗物、蛋→Byrd Swoop 变牌、战斗中获得时的处理）第二部分已做，本批对照原生 `HatchRestSiteOption`/`Player.HasEventPet` 复核一致。Byrdpip 宠物本身是 9999 血、什么都不做的生物，单人无数值影响，未单独建模。
- 新做事件：没有事件宠物（无 Byrdpip / Pael's Legion、牌组无鸟蛋）才出现；选项 0「吃」：+7 最大生命（同时 +7 当前生命）；选项 1「拿」：鸟蛋加入牌组。
- 原先“首次进入 Overgrowth 的发现顺序必须遇到 ByrdonisNest → 初始化直接拒绝”的限制随之解除，事件袋第 1 位正确放入 ByrdonisNest（`native_act_alignment` 测试改为断言这一点）。

### 第 16 批：第三幕 Boss Aeonglass — 2026-11-09

- **数据**：怪物/遭遇表由 `simulator/tools/gen_monsters.py` 生成并按字母排序；直接加会让全部旧 ID 后移，所以按已有 Seapunk 先例**追加到末尾**（`MonsterId::AEONGLASS`、`Encounter::SETUP_AEONGLASS_BOSS`），旧 ID 全部不变（已 diff 确认只有新增行）。数值按原生 `Aeonglass.cs` 写在生成器里，未改动历史提取数据 `monsters.json`。
- **Boss 池**：原生 Glory 的 `GenerateAllEncounters` 把 AeonglassBoss 放在旧表 Doormaker 按字母排序的同一位置，所以 Aeonglass 顶替 Doormaker 的位置，Boss 池顺序为 Aeonglass/Queen/TestSubject，抽取用的随机数不变。原生已无 Doormaker，C++ 保留但不再进池。发现顺序 Queen→TestSubject→Aeonglass；首次遇 Aeonglass 不再拒绝初始化（`aeonglassSeen=false` 时强制）。A10 第二 Boss 从同一池里选。
- **战斗**：HP 512（A8 起 535），神器 3；开战给玩家「Withering Presence」（每打 6 张牌往手里塞 1 张 Wither，计数重置为 6）。招式循环：Ebb（22/A9 26 伤害 + 33 格挡）→ Eye Lasers（11/A9 12 ×2）→ Increasing Intensity（所有 Wither +3 伤害，往弃牌堆加 1/A9 2 张 Wither，力量 +3/A9 4，之后每次多 +1）。
- **Wither**：状态牌，回合结束在手中受 3 点伤害（可被格挡、不受力量影响），每次「升级」+3；之后新生成的 Wither 直接对齐当前升级次数。升级量存在牌的 `bonusDamage` 字段，观察/快照/复制自动带上。
- **验证**：step3 事件测试 1723 项（本批：三档进阶的 HP/神器/开局意图、打 6 张牌出 Wither、回合结束 Wither 伤害、Ebb/Eye Lasers 数值、两轮 Intensity 后 Wither 伤害与力量、新生成 Wither 对齐、A9 两张 Wither、战斗中途快照恢复、300 个种子的 Glory Boss 分布无 Doormaker、发现顺序强制 Aeonglass）；C++ 36 个程序全过；Python 167 通过（失败/错误同前，均为 torch 桩与缺 rules_test 二进制）；1000 局冒烟 0 异常、约 169 局/秒；地图对照仍 6/6。
- **观察维度**：怪物/遭遇 one-hot 各 +1，公开观察 75350→75357，公开战斗观察 49248→49252。v14 布局本轮一直未冻结、未用于训练，按此前做法没有升版本号；**正式用于训练前需统一升观察/快照版本号**。
- **限制**：Aeonglass 没有原生实测对照（本地无原生对战录像），按源码移植；原生的 Imbued 附魔档位（偷牌）及 Wither 的“克隆后再对齐”叠加等极端组合未覆盖。

## 第三步事件补全：最终状态（2026-11-09）

- AGENTS.md 缺口表 D（31 个已注册未实现 + 3 个未注册事件）**全部实现**；仅剩纯占位 `AROMA_PLACEHOLDER`（非原生事件）。
- 缺口表 E：Aeonglass Boss 已实现并进入 Glory 池；ByrdonisNest 首次 Overgrowth 强制入口已可用。
- 额外完成：普通幕地图生成与原生逐点一致（6/6 张原生录制地图）。
- 仍未做/未验证：没有原生 DLL 受控样例对照本步任何事件（宿主已删除，需要用户提供 .NET 环境后补）；完整同种子长路径对照；torch 环境（OMP 冲突）未修，需用户同意后处理；观察/快照版本号待统一升级。未提交、未推送。

## 第四步：AGENTS.md 剩余缺口收尾（2026-11-09）

用户：不需要核对 DLL（另有人做），把剩余缺口做完。先逐项核对现状，避免重做。

### 核对结论：早先已完成、无需改动

- 第二部分的原生样例测试（均在 36 个程序里通过）已覆盖：Lead Paperweight、Arcane Scroll、Dream Catcher（休息奖励流程）、Dusty Tome、Sea Glass（5 角色）、Bone Tea、Fake Venerable Tea Set、Byrdpip、Toy Box（蜡制 5 件、每 3 战熔化）、Small/Large Capsule。AGENTS.md 表 B 中这些描述已过期。
- Delicate Frond、Alchemical Coffer：逐行对照原生一致（物理药槽、Combat Potion Generation 随机流、失败即停）。
- Massive Scroll：原生仅多人（IsAllowed 要求 >1 人），Neow 单人池里 C++ 已排除，单人不可达。
- Prismatic Gem +1 能量已有；Welcome to Wongo's 原生“消费触发”没有任何遗物监听 `GoldLossType.Spent`，无需实现。
- **生成时序**：原生开局用 `Rng.UpFront` 一次生成三幕房间；C++ 进入各幕才生成。核对源码后，UpFront 在 C++ 中只在开局（遗物袋、共享 Ancient）和每幕生成时消耗，原生遗物袋补充也不用它，**按源码推断**两种时序结果相同，因此未改代码。配套测试（第 18 批）只做 **C++ 内部**比较：24 局随机游玩到第三幕（为保证走到第三幕把血量设为 30000），每幕的房间袋、Boss、Ancient、UpFront 计数与同一种子“开局连续生成”完全一致。它证明中间的游戏过程不会动到这条随机流，**不是与原生的整局对照**。（2026-11-09 根据外部审阅修正措辞。）

### 第 17 批：奖励牌池、Splash、Wongo's、商店过滤

- **Prismatic Gem / Dingy Rug**：原生是 `ModifyCardRewardCreationOptions` 扩大整个牌池（Gem：所有已解锁角色牌池放前面；Rug：末尾并入无色），每张都按稀有度从合并池抽。C++ 原来是“第 3 张变无色”的旧近似。现在战斗奖励与 `queue_card_reward`（Lost Coffer、Glass Eye 等）都走 `native_card_reward_pool`；不持有这两件遗物时完全走原路径（随机序列不变）。Dream Catcher 等已有路径改用同一函数。
- **Splash**：原生从“除自己外的已解锁角色”攻击牌中取 3 张（只有铁甲解锁时才用铁甲）；C++ 原来固定铁甲。战斗现在会拿到运行的角色解锁掩码（此前战斗里该字段从未赋值，恒为全解锁）。
- **商店禁售**：原生 `IsAllowedInShops=false` 的 5 件（Amethyst Aubergine、Bowler Hat、Lucky Fysh、Old Coin、The Courier）；C++ 只排除了后两件。已补全。
- **Welcome to Wongo's**：精选稀有遗物在进入事件时就从玩家遗物袋前端按商店过滤取出（买不买都消耗）；特价遗物同样从前端按商店过滤取普通遗物（C++ 原来一个按 ID 扫描、一个无过滤）。账号 Wongo 积分（新字段 `wongoPoints`，Python `wongo_points`）：购买得 32/16/8 分，跨过 2000 的倍数得 WongoCustomerAppreciationBadge。
- **Wongo's Mystery Ticket**：原生在“第 5 场战斗之后的下一次战斗房间奖励”给 3 件遗物，且只给一次；不给奖励的战斗（Battleworn）不算。C++ 原来恰好第 5 场给，若那场不给奖励就永远丢失。现用计数 6 表示已给。

### 第 18 批：房间生成时序（见上，等价性测试）

### 第 19 批：账号 epoch 内容过滤

- 新增 `tools/gen_epoch_unlocks.py`：直接解析原生源码中各牌池/遗物池/药水池检查的 `IsEpochRevealed<X>()` 与对应 Epoch 的 Cards/Relics/Potions 列表，生成 `epoch_unlocks.inc`（57 个 epoch，锁住 60 张牌、45 件遗物、21 种药水；五个 C++ 改名的卡牌键已映射，全部解析成功）。
- `NativeProgressContext.revealedEpochs`（64 位，Python `revealed_epochs`，`sts2_sim.native_epoch_names()` 给出位序）；默认全揭示，行为与之前完全相同。战斗开始时复制到战斗，快照校验两者一致。
- 所有牌池枚举（奖励、商店、变牌、各类战斗生成、Splash、药水/遗物生成、遗物袋初始化与补充、ScrollBoxes 条件）都按此过滤。原有的事件 epoch、Neow/Orobas/Darv/Underdocks 开关与角色掩码保持独立字段，接入方需按存档一并填写。

### 第 20 批：费用修正栈、死亡清能力、强制选择、Dark Shackles、Royalties

- **费用修正栈**：Snecko Eye（SetThisCombat 随机）、Snecko Oil（本回合或打出前）、Frantic Escape（本战 +1）、各种“本战免费”现在都按原生插入顺序进入每张牌的修正栈，不再改写基础费用；战斗内升级/降级不再丢失这些修正。补上原生回合结束对所有牌堆的回合修正清理。每抽一次 Snecko 都会加一条修正，新的“整场绝对值”修正会使之前的全部失效，因此可精确压缩，栈不会溢出。
- **死亡**：玩家死亡（三条路径）后清空全部能力及其计数（原生 `RemoveAllPowersAfterDeath`，玩家侧无豁免能力）。只影响终局状态。
- **强制选择自动完成**：第二部分只在出牌循环内做；现在任何动作之后（回合流程、药水、遗物）和开战时，候选数 ≤ 必选数的选择都按原生规则直接完成。
- **Dark Shackles**：改为独立的 `DARK_SHACKLES` 临时降力量能力（神器整体抵挡；敌方回合结束恢复），不再借用通用临时减力量字段。
- **Royalties**：战斗结束追加对应金额的额外金币奖励（排在事件附加奖励之后；终局 Boss 不给，与原生一致）。

### 版本

ruleset `native-41cef1ea-port-v6`、公开观察 v15、动作 v14、快照 v10、ArmG 特征 6（`PORT_SOURCE.json` 同步）。公开观察 75357 维、战斗 49252 维。旧权重/快照会被拒绝。

### 验证（本节全部做完后）

- step3 事件测试 1947 项；C++ 36 个程序全部通过（`native_step1_downgrade` 的测试装载“本战免费”改为同样压入修正栈，原生结果未改）。
- Python 167 通过；10 失败 + 34 错误与此前相同（缺 torch、缺 cmake 的 `rules_test`）。
- 1000 局冒烟 0 异常、约 172 局/秒；普通地图仍 6/6 与原生一致。

### 仍未做 / 需要他人处理

- 本步所有改动均按源码移植，**未用 DLL 实测**（用户说明由他人负责）。
- `scripts/armg_live_worker.py` 手工拼接的局外观察扩展段仍是旧布局（新增的 Crystal Sphere、额外金币、Spoils 任务等字段未填），并且仍把 `ENCOUNTER.AEONGLASS_BOSS` 跳过；对接实机前需要按新布局更新，并填写 `revealed_epochs`、`wongo_points`。这些测试依赖 torch，本机无法运行。
- 13 处“本回合改费”（`card_set_turn_cost`）仍直接改写基础费用；与新栈混用的极端顺序可能与原生不同。
- `nextTurnEnergy` / `nextTurnDraw` 观察字段仍恒为 0（无写入方），保留占位。
- Thieving Hopper 的 Imbued 附魔档（C++ 无该附魔）、Wither 被复制后再对齐的叠加等极端组合未覆盖。
- torch 环境（OMP 冲突）未修。未提交、未推送。

## 第五步：继续原生规则对齐（2026-11-09，用户：torch 和网络不用管，只做原生适配）

### 第 21 批：剩余的“本回合改费”全部改为原生修正栈

- 12 处旧写法逐一对照原生调用改写：Distraction、Mad Science、Orobic Acid、Jeweled Mask、Crossbow、Mummified Hand、Attack/Skill/Power/Colorless 药水等的“本回合免费”→ `SetThisTurnOrUntilPlayed(0)`（回合结束或打出即失效）；Liquid Memories 同；Enlightenment → reduce-only 设为 1（升级版整场，未升级版本回合/打出前）；Stomp → `AddThisTurn(-1)`（每打一张攻击，所有牌堆中的 Stomp 本回合 -1；新进入战斗时补算本回合已打攻击数）。引擎中已无直接改写基础费用的地方。
- **Mummified Hand** 按原生四级候选顺序重写：①基础费用>0 且当前要花费 ②当前要花费 ③基础费用>0 ④任意牌；空集合不消耗随机数。C++ 原来只用一级、且用修正后费用判断（原生用 `CostModifiers.None` 的基础费用）。
- 抽出 `energy_cost_in_combat`（本地修正 + 全局费用钩子），出牌和 Mummified Hand 共用，行为不变。

### 第 22 批：Imbued 附魔 / Electric Shrymp

- 新增 `EnchantmentId::IMBUED`（末尾追加）：只能附在技能牌上；开战时放到抽牌堆底；第 1 回合在自动出牌阶段（排在能力、遗物之后）自动打出。
- **Electric Shrymp** 获得时原来什么都不做；现在打开“选一张牌附 Imbued”（卡牌网格 kind 15，只有一张可选时按原生直接完成）。
- Thieving Hopper 偷牌优先级补上 Imbued 档（与 Ancient 同档）。
- **顺带修正开局抽牌堆顺序**：原生第 1 回合先把 Imbued 移到底，再把其余 Innate 牌逐张移到顶——多张 Innate 时最终顺序与 C++ 原来相反，已按原生改。

### 第 23 批：变牌产生新实体

- Primal Force、Entropy、各种战斗内“变化”选择：原生 `CardCmd.Transform` 放入的是新卡牌实体（新 ID、无牌组关联），并触发“生成牌/进入战斗”钩子。C++ 原来沿用旧 ID，导致被变出的牌仍算“来自牌组”（Thieving Hopper 可偷、可能回写牌组）。已改。

### 第 24 批：卡牌奖励选项钩子 / Lasting Candy

- 原生所有 CardReward 生成后都会过 `TryModifyCardRewardOptions(+Late)`。C++ 战斗奖励原来只单独处理了 Fresnel、Silver Crucible、Lava Lamp，**Glitter、Silken Tress、Wing Charm 和蛋类对战斗奖励选项都没生效**；Lost Coffer / Glass Eye / Brain Leech 的卡牌奖励只处理了 Fresnel。现在统一走同一套钩子（按持有遗物顺序，Lava Lamp 只在战斗中）。
- **Lasting Candy**（此前未实现）：每第二次带卡牌奖励的战斗，额外加 1 张不重复的能力牌（按遭遇类型的基础稀有度、可升级判定）。奖励选项上限 3→4（`MAX_REWARD_CARD_CHOICES`），快照/观察随之扩展：公开观察 75357→75988（版本仍为 v15，本轮未冻结）。

### 验证

step3 事件测试 1979 项；C++ 36 个程序全过（`rules_regression` 的 Silver Crucible 单元测试改为和战斗结算一样，在生成奖励后调用钩子）；Python 167 通过（其余同前，torch 相关）；1000 局冒烟 0 异常、约 169 局/秒；地图 6/6。

### 仍可继续核对（需要 DLL 或范围较大）

- C++ double 与原生 decimal 的取整边界、固定牌堆/遗物容量边界（AGENTS.md 第 6 节）。
- `after_hand_drawn` 把回合开始与自动出牌阶段合在一起；Mayhem（能力）原生排在遗物之前，C++ 排在之后（只影响非铁甲的组合）。

## 第六步：根据外部审阅收尾（2026-11-09）

外部审阅提了四条意见，处理如下：

1. **基础稀有度蓝牌阈值错误（旧代码遗留）**：原生 `CardRarityOdds.RollWithBaseOdds` 规定掷出值 < 稀有率 + 蓝牌率 才算蓝牌。C++ 有两处写成了 < 0.37，导致低进阶下蓝牌实际只有 34%。一处是 `queue_card_reward`（Lost Coffer 一类的卡牌奖励），另一处是 `make_noncombat_card_candidates`（非战斗选牌网格），审阅只指出了前一处。两处都已改正，旧注释也一并改了。新增第 25 批测试：挑出掷出值落在 [0.37, 0.40) 的种子，要求得到蓝牌。所有原生样例仍然通过。
2. **时序测试措辞过头**：第 18 批 24 局测试只是 C++ 内部两种生成方式的比较（血量设为 30000 是为了走到第三幕），不是与原生的整局对照。README 与测试注释已改正。
3. **测试换机器后找不到样例**：14 个使用原生样例的测试原来用编译时写死的源码路径 `__FILE__` 定位样例，在另一台机器上运行时会去找原机器的目录。新增 `simulator/tests/port_root.h`：运行时依次用环境变量 `STS2_PORT_ROOT`、当前目录及其上级目录查找仓库根目录，最后才回退到编译时路径。已验证：故意从仓库外的副本编译测试（编译时路径错误），从仓库根目录、仓库子目录、或设置环境变量后在任意目录运行，均能通过。
4. **上传清单不完整**：旧清单缺新增的源码和工具（epoch 过滤表、生成器、`regent.cpp`、新测试、`port_root.h` 等）以及两个新的记录目录。已生成新清单 `docs/native-port-upload-paths-20261109.txt`（1813 条）：包含旧清单中仍存在的全部条目、全部新文件，以及所有改过的已提交文件；不含编译产物、`.pyc` 和第三方库的非构建文件。`git add --dry-run` 演练无报错，会加入或更新 277 个文件。

验证：C++ 36 个程序全过（step3 测试 1990 项）；Python 167 通过（其余同前，torch 相关）；1000 局冒烟 0 异常，速度 150–170 局/秒（多次运行有波动）；地图 6/6。

另：开发副本内的 `AGENTS.md`（仍写着 v4、第一部分）已改为指向仓库根 `AGENTS.md`。

## 第七步：给局外策略网络加 C++ 接口（2026-11-09，用户要求进入网络设计）

只新增接口，**没有改任何游戏规则**。网络与训练代码在仓库根 `model/spire_rl/`（说明见其 README）。

- `simulator/include/sts2/macro_obs.h`、`simulator/src/macro_obs.cpp`（新文件，已补进上传清单，共 1815 条）：
  - `macro_observation(rc)`：局外实体 token（全局、场景、牌组每张牌、遗物、药水槽、地图节点与连边、Boss、商店/奖励物品、奖励项、事件选项、水晶球格子），每个实体 = 类别 + ID + 80 维归一化数值；每个合法动作一个候选，带最多两个实体指针。可见性与公开观察相同：未打开的卡牌奖励不暴露内容，未揭开的水晶球格子 ID 为 0。`MACRO_OBS_VERSION = 1`。
  - `play_combat_mcts(...)`：在 C++ 内用隐藏信息重采样 MCTS 跑完一整场战斗，每步只执行第一步再重搜；只有一个合法动作时直接执行；检查选出的动作合法。
- `bindings.cpp`：`RunContext.macro_observation()`（返回 numpy 数组）、`RunContext.play_combat_mcts(...)`（两者都释放 GIL）、`sts2_sim.macro_vocab()`、模块常量 `MACRO_OBS_VERSION` 等。

验证：C++ 36 个程序全过；Python 167 通过（其余同前，torch/cmake 相关）；1000 局冒烟 0 异常 0 截断，167 局/秒；地图 6/6。随机局外选择 + MCTS 战斗的冒烟中：实体最多 93 个、候选最多 20 个，没有候选指向越界实体，无目标的候选只有离开/跳过/确认一类。
