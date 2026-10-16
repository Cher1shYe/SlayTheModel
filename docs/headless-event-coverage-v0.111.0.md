# Headless 原生事件与特殊界面覆盖（v0.111.0）

日期：2026-10-09。本文件记录代码连接范围、静态证据与已完成的逐事件原生对照；不把编译通过或类型可达当作逐事件验证。

## 实现边界

`tools/Sts2.HeadlessHost/NativeSpecialScreens.cs` 接入正在运行的原生 Godot 场景。它只投影公开状态，并触发原生输入回调；不自行实现事件奖励、随机数、扣钱、附魔、升级、变形或商店补货，不直接写入原生选择器的 `TaskCompletionSource`。

外部终端通过统一 bridge 选择动作。动作与当前原生对象和界面 revision 绑定，父动作返回的原生 Task 由 bridge 跟踪。父动作打开子选择器时可以继续提交子选择；同一特殊界面的上一次异步输入未完成时不再提交新输入。候选逐张切换，再走原生确认/返回，不枚举组合。

本机证据来自 `sts2.dll` v0.111.0（SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`）的 ABI、IL 与 ILSpy 反编译。反编译原文保留在忽略目录 `artifacts/native-source/v0.111.0/`，不随项目分发。整个事件命名空间有 68 个顶层模型文件，另有 `Mocks/MockEventModel`。普通事件均继续运行原生模型；存在事件中的遗物效果再打开子选择器等间接路径，下面只列直接调用证据。

## 交互家族与执行入口

| 界面 | 观察和动作 | 原生执行入口 |
|---|---|---|
| 普通事件和古代事件 | 当前文案、事件选项及原生可用状态 | 主 bridge 使用原生事件按钮；事件模型继续执行 |
| 战斗牌堆选择 `NCombatPileCardSelectScreen` | 原生过滤与排序后的 grid 候选，逐张切换、确认 | 派生 `OnCardClicked(CardModel)` 与原生确认按钮 |
| 通用选择 `NSimpleCardSelectScreen` | 同上，保留 min/max、可取消和手动确认条件 | 同上 |
| 牌组删牌 `NDeckCardSelectScreen` | 当前候选，选择集合，预览、确认、返回 | 同上 |
| 升级 `NDeckUpgradeSelectScreen` | 单卡/多卡候选，原生升级预览、确认 | 同上 |
| 附魔 `NDeckEnchantSelectScreen` | 通用附魔候选和真实约束，不按附魔名白名单 | 同上 |
| 变形 `NDeckTransformSelectScreen` | 真实候选和约束；原生预览/确认继续执行 | 同上 |
| 生成卡单选 `NChooseACardSelectionScreen` | 全部原生候选、可用时跳过，保留原生 350ms 防误选等待 | `SelectHolder(NCardHolder)` 与原生跳过按钮 |
| 卡牌奖励 | 奖励卡及原生 alternative 按钮（跳过、重抽、遗物替代奖励等） | `SelectCard(NCardHolder)`；alternative 的原生 Released 回调 |
| 卡牌包 `NChooseABundleSelectionScreen` | 包内卡牌、已选包、预览确认 | `OnBundleClicked(NCardBundle)` 与原生确认/返回 |
| 宝箱遗物 `NTreasureRoom` | 已打开宝箱的遗物名称、英文名、效果及拿取；保留原生 200ms 防误选 | 原生 `NTreasureRoomRelicHolder` Released → `PickRelic` → 同步器 |
| 遗物选择 `NChooseARelicSelection` | 候选遗物、描述、选择与跳过 | `SelectHolder(NRelicBasicHolder)` 与原生跳过按钮 |
| 普通商店/假商人库存 `NMerchantInventory` | 卡/遗物/药水/删牌报价、描述、库存和买得起状态 | 当前 `NMerchantSlot.OnSelected()`；保留原生交易、Task、补货和事件钩子 |
| 水晶球 `NCrystalSphereScreen` | 格子坐标、揭开状态、剩余次数、工具，完整公开物品类别 | `OnCellClicked(NCrystalSphereCell)`，原生大小占卜与继续按钮 |

`NCardGridSelectionScreen` 的六个原生派生类均由同一适配器覆盖。特别地，战斗牌堆选择器的 `_cards` 保持空列表，实际候选由 `UpdatePileContents` 写入 `_grid`；因此从 grid 内完整的 `_cards` 列表读取。`CurrentlyDisplayedCards` 实际只包含滑动窗口的 holder，会漏掉屏外候选；终端直接调用完整候选的原生 `OnCardClicked`，原生高亮方法允许 holder 尚未创建。原版抽牌堆排序只比较稀有度、标题和 model ID，相同键的卡实例仍有源顺序依赖；本接口按 model ID、升级数与独立随机实例键排序，实例键仅留在进程内，避免输出隐藏牌序。预览层打开时原生 `_grid.FocusBehaviorRecursive` 为 `Disabled`，此时不允许继续点击背景候选。

`NClickableControl.ForceClick()` 只触发 `OnRelease` 和 `Released`。卡牌 holder 与商店 slot 绑定的鼠标信号不同，不能一律 ForceClick；这里分别调用它们对应的原生选择入口。确认、返回、替代奖励和占卜工具按钮继续使用原生 Released 信号。所有直接调用前重新检查对象存活、界面可见、控件启用及当前库存/候选身份。

## 信息投影

- 所有原生对象只留在进程内部。JSON 只写白名单的字符串、数值、候选展示实体、格子和动作，不序列化模型对象图。
- 水晶球隐藏格不读取 `Item`。已揭开的碎片只写有无碎片；仅在原生 `_revealed` 已记录后写完整物品类别。终端用格子符号替代原版图像，不输出隐藏物品坐标、尺寸、完整布局、`Items` 或 RNG。
- 选牌预览模型不混入候选身份。抽牌堆候选采用公开字段与独立随机实例键排序，不暴露内部抽牌顺序。
- 商品价格使用当前原生 `Cost`；购买资格使用当前 `IsStocked`、`EnoughGold`、Hitbox 与库存输入阻塞状态。卡面/遗物/药水文字用原生本地化，英文名称来自游戏英文表。
- 商店关闭库存与离开商店是两个原生动作。假商人场景仍持有原生事件模型，不能用普通商店的离开回调代替。

## 事件模型清单

“普通原生事件按钮”表示无需逐事件重写规则，其所有效果仍由该原生模型执行；不等于每条分支已实机通过。古代事件授予的遗物以后触发的选牌也会进入上述公共选择器。

| 模型 | 直接交互/后续页面证据 | 验证状态 |
|---|---|---|
| `AbyssalBaths` | 高速探针种子 9/13 真实进入；种子 9 按 `IMMERSE → LINGER → EXIT_BATHS` 退出，验证 `LINGER` 会重新生成同名合法选项 | 已测该路径；其他分支未逐项核对 |
| `Amalgamator` | 原生删牌选择 | 未逐事件实测 |
| `AromaOfChaos` | 原生变形选择；原生升级选择 | 未逐事件实测 |
| `BattlewornDummy` | 原生奖励页 | 未逐事件实测 |
| `BrainLeech` | 原生奖励页 | 未逐事件实测 |
| `Bugslayer` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `ByrdonisNest` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `ColorfulPhilosophers` | 原生奖励页 | 未逐事件实测 |
| `ColossalFlower` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `CrystalSphere` | 水晶球原生棋盘、工具、格子、结算 | 未逐事件实测 |
| `Darv` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `DenseVegetation` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `DeprecatedAncientEvent` | 废弃占位类型；不宣称正常事件池可达 | 未逐事件实测 |
| `DeprecatedEvent` | 废弃占位类型；不宣称正常事件池可达 | 未逐事件实测 |
| `DollRoom` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `DoorsOfLightAndDark` | 原生删牌选择 | 未逐事件实测 |
| `DrowningBeacon` | 原生奖励页 | 未逐事件实测 |
| `EndlessConveyor` | 原生变形选择；原生奖励页 | 未逐事件实测 |
| `FakeMerchant` | 原生商店库存及假商人事件钩子、战斗转场 | 未逐事件实测 |
| `FieldOfManSizedHoles` | 原生附魔选择；原生删牌选择 | 未逐事件实测 |
| `GraveOfTheForgotten` | 原生附魔选择 | 未逐事件实测 |
| `HungryForMushrooms` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `InfestedAutomaton` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `JungleMazeAdventure` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `LostWisp` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `LuminousChoir` | 原生删牌选择 | 未逐事件实测 |
| `MorphicGrove` | 原生变形选择 | 未逐事件实测 |
| `Neow` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Nonupeipe` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Orobas` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Pael` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `PotionCourier` | 原生奖励页 | 未逐事件实测 |
| `PunchOff` | 原生奖励页 | 未逐事件实测 |
| `RanwidTheElder` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Reflections` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `RelicTrader` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `RoomFullOfCheese` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `RoundTeaParty` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `SapphireSeed` | 原生附魔选择；原生升级选择 | 未逐事件实测 |
| `SelfHelpBook` | 原生附魔选择 | 未逐事件实测 |
| `SlipperyBridge` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `SpiralingWhirlpool` | 原生附魔选择 | 2026-10-09 同规范化种子自然问号路径：`Observe` 的 9 张候选选 1 张并获得 `SPIRAL` 附魔、`Drink` 的 HP 75→80 均与无 `NGame` 探针对照一致；两分支随后进入同一 `CORPSE_SLUGS_WEAK`；仅这两条分支和该种子已验证 |
| `SpiritGrafter` | 原生升级选择 | 未逐事件实测 |
| `StoneOfAllTime` | 原生附魔选择 | 未逐事件实测 |
| `SunkenStatue` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `SunkenTreasury` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Symbiote` | 原生附魔选择；原生变形选择 | 未逐事件实测 |
| `TabletOfTruth` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Tanx` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TeaMaster` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Tezcatara` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TheArchitect` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TheFutureOfPotions` | 原生奖励页 | 未逐事件实测 |
| `TheLanternKey` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TheLegendsWereTrue` | 原生奖励页 | 未逐事件实测 |
| `ThisOrThat` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TinkerTime` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `TrashHeap` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Trial` | 原生变形选择；原生升级选择；原生奖励页；原生放弃整局确认弹窗 | 未逐事件实测 |
| `UnrestSite` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Vakuu` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `WarHistorianRepy` | 原生奖励页 | 未逐事件实测 |
| `WaterloggedScriptorium` | 原生附魔选择 | 未逐事件实测 |
| `WelcomeToWongos` | 普通原生事件按钮；效果与后续页面由原生模型驱动 | 未逐事件实测 |
| `Wellspring` | 原生删牌选择；原生奖励页 | 未逐事件实测 |
| `WhisperingHollow` | 原生变形选择；原生奖励页 | 未逐事件实测 |
| `WoodCarvings` | 原生附魔选择；原生牌组选牌 | 未逐事件实测 |
| `ZenWeaver` | 原生删牌选择 | 未逐事件实测 |

## 验证要求与当前结果

2026-10-07 macOS 原生终端实跑已走通铁甲开局涅奥、地图、首场 `NIBBIT` 战斗、战后回血、卡牌奖励拿取、领取药水与局外弃药，并实际验证过期动作拒绝。2026-10-09 又从新建自然跑局经本机 API 进入 `SPIRALING_WHIRLPOOL`，分别选 `Observe` 和 `Drink`，与同种子无 `NGame` 探针对照原生候选、最终状态及下一场 `CORPSE_SLUGS_WEAK` 入口；各分支都先通过首战 8/8 个决策点的状态核对。结果见[性能验证](headless-performance-gate-v0.1.md#同种子战后奖励与首个问号事件2026-10-09)。占卜、两种商店和表中其他特殊分支仍未通过本终端宿主实跑；人工终端客户端最终版本也仍待完整复跑。完整证据与版本边界见[终端说明](headless-terminal-v0.1.md#验证)。

已完成：对以上特殊屏幕的主要候选、预览、确认、交易与异步入口核对反编译方法体；bridge 临时编译工程 Release 通过，0 warnings / 0 errors。此处未启动 Steam、未安装 Mod，也没有将旧采集 JSONL 作为本 headless 的实测证据。

逐事件验收需要用原生固定种子或开发测试入口实际进入页面，并记录每条选择的前后 HP、金币、牌组、遗物、药水、原生选择结果及最终转场。至少覆盖：

1. 普通地图三幕流转、普通/精英/首领战斗、休息点、宝箱、奖励及终局。
2. 所有事件模型的可达选项和分支；事件开战、事件回到原页面、事件直接结束；`Trial` 的放弃弹窗 Yes/No。
3. 水晶球大小工具、边缘格、多个占卜次数、碎片与完整揭示、诅咒/奖励/子选牌及结束后的继续；核对隐藏 JSON 不随未揭示物品类别变化。
4. 普通商店与假商人购买每类商品、金币不足、药水槽满、补货、删牌取消/完成、购买附魔遗物打开子选择、关闭/重开库存、最终离开；假商人的药水特殊反应及战斗分支。
5. 六类 grid 选择器的单选、零选、可取消、多选数量边界、超过一屏的牌组和最后一张候选、预览返回/确认、无候选，以及战斗中牌堆变化；不应在预览层点击背景 grid。
6. 奖励 skip/reroll/alternative，卡包确认与返回，遗物选择/跳过；确认原生父 Task 继续并且只结算一次。
7. 中英文卡名和效果文字、商店报价、终端所有必要确认项；动作过期时拒绝，原生 Task 异常显示为错误而非伪装成功。

未通过的分支须留下具体原生类型/入口/错误，并修复对应适配器。不能将未知页面自动点第一个选项、直接修改玩家状态，或用通用“继续”绕过尚未支持的原生选择。

## 显式测试场景

`NativeSmokeScenario.EnterConfiguredAsync` 只在设置 `STS2_HEADLESS_SCENARIO` 时启用，并在正常新局创建后通过原生 `RunManager.EnterRoomDebug` 进入测试房间。支持 `crystal-sphere`、`merchant`、`fake-merchant`、`trial`、`transform`、`upgrade`、`enchant`、`treasure`、`rest`，以及 `event:EXACT_EVENT_ID`。例如 `transform` 进入 `MORPHIC_GROVE`，随后仍需要玩家通过菜单选择原生事件选项，不会直接赠送变形结果。

这些是局部集成测试局：保留新局的种子与原生 RNG 流，但通过开发入口改变房间路径；日志明确写 `HEADLESS_TEST_SCENARIO`，不能混入正常整局训练数据。该入口没有新增网络调试 API，不改变正常启动默认行为，也不自行修改金币、卡牌或事件效果。
