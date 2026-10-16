# STS2 v0.111.0 原生交互入口审计

日期：2026-10-07。此文是实施前的只读审计，不表示采集器已修复或已实机验证。

## 证据范围与方法

- 本机游戏只提供托管程序集 `sts2.dll`，没有完整 C# 源文件或 PDB。程序集 `game_version=v0.111.0`，SHA-256 为 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`，与仓库固定契约一致。
- 用 `tools/Sts2.AbiProbe` 扫描 `MegaCrit.Sts2` 的全部元数据：9,667 个类型、51,223 个方法。再对原生入队、选择、购买等关键方法做程序集范围的 IL 调用点反查，并用 `tools/Sts2.IlProbe` 阅读相关方法体。直接调用 `ActionQueueSynchronizer.RequestEnqueue` 的 IL 位置共有 13 处；选定的 `CardSelectCmd.From*` 入口共有 127 处直接调用，其中事件模型有 29 处、涉及 20 个事件类。69 个事件模型到 `Nodes` 的直接调用共有 96 处，主要是场景、卡面预览和特效。
- 这覆盖了托管程序集中的入口和调用关系，不等于逐行读完全部 51,223 个方法。Godot 场景的实时可见性、第三方 Mod 路径及某些模型效果是否在单人跑局触发，还需单独核验。不要把静态可达性当作实机发生率。

## 跑局交互的原生入口

| 交互 | 原生入口和结算路径 | 当前采集状态 |
|---|---|---|
| 战斗出牌 | `NCardPlay.TryPlayCard → CardModel.TryManualPlay → EnqueueManualPlay → RequestEnqueue` | 普通手动路径已绑定同一 `GameAction`；点击时内部状态是既定观察边界。 |
| 结束回合 | `NEndTurnButton.CallReleaseLogic → RequestEnqueue`；教学引导另有 `SecretEndTurnLogicViaFtue → RequestEnqueue` | 只覆盖前者；后者是确认教学弹窗后可触发的真实漏口。 |
| 药水使用/丢弃 | `NPotionHolder/NPotionPopup → PotionModel.EnqueueManualUse` 或 `NPotionPopup.OnDiscardButtonPressed → RequestEnqueue` | 可识别原生动作；局外结构化仅覆盖奖励页和普通商店的一部分稳定边界。 |
| 地图 | `NMapScreen.OnMapPointSelectedLocally → VoteForMapCoordAction → MapSelectionSynchronizer.PlayerVotedForMapCoord` | 同步器入口已观察；冻结发生在动作执行阶段，点击到执行之间的状态相等性尚未证明。 |
| 普通事件 | `NEventRoom.OptionButtonClicked → EventSynchronizer.ChooseLocalOption` | 已观察；事件模型效果可能打开后续选择器。 |
| 休息点 | `NRestSiteButton.SelectOption → RestSiteSynchronizer.ChooseLocalOption`，返回 `Task<bool>` | 已观察。 |
| 奖励 | `NRewardButton.GetReward → RewardsSetSynchronizer.SelectLocalReward`；另有 Proceed | 已观察；卡牌奖励的 alternative 实际选择仍明确记缺口。 |
| 商店与假商店 | `NMerchantSlot.OnSelected → MerchantEntry.OnTryPurchaseWrapper`，返回 `Task<bool>` | 后端包装方法已观察，但目前没有一次性的人工 UI 来源证明；假商店的局外药水 surface 未识别。 |
| 宝箱 | `NTreasureRoom` 开箱/Proceed；遗物选取或跳过经 `PickRelicLocally(int?)` | 已观察。 |
| 卡牌、牌组、遗物选择 | `CardSelectCmd.From*` / `RelicSelectCmd` → 对应选择器 → `PlayerChoiceSynchronizer` 回执 | 多种路径已观察；`NDeckUpgradeSelectScreen` 多选缺失。 |
| 水晶球 | `NCrystalSphereScreen` 占卜、格子、Proceed | 已设置对应钩子；仍须实机验证所有状态组合。 |

`NPotionLab` 继承主菜单 `NSubmenu`，不属于跑局操作。遗物栏的普通点击、古代事件对话点击和地图画线主要改变查看或显示状态；不能仅按 `OnPress` 名称认定为训练动作。事件模型 `Trial.DoubleDown` 另会打开 `NAbandonRunConfirmPopup`：Yes 可放弃整局，No 只关闭弹窗。这属于跑局控制入口，应核对终局记录，但不应未经设计就当成策略训练标签。69 个事件模型中有废弃和测试类型；本轮未逐个证明其所有效果的可达性。

## 已确认的缺口与误标风险

### 1. `LordsParasol` 自动购买会被当作人工商店决策

原生 `LordsParasol.AfterRoomEntered` 遇到 `MerchantRoom` 就启动 `PurchaseEverything`。其异步方法在卡、遗物、药水和删牌路径共五处调用 `OnTryPurchaseWrapper(ignoreCost: true)`。普通 UI 购买从 `NMerchantSlot.OnSelected` 进入，使用 `ignoreCost: false`。

采集器在 `MerchantEntry.OnTryPurchaseWrapper` 前缀直接调用 `CaptureMerchantChoice`，只检查在库、金币等条件，没有核对 UI 点击来源或 `ignoreCost`。因此遗物自动购买且本来买得起的商品可能被写为 `human-demonstration`；忽略费用才买得起的商品会落到未匹配点击/缺口路径。这是源码已证实的静态误标路径，不是已观察到的实机样本。本机已检查的正式 JSONL 未检出 `LORDS_PARASOL`。修复时应以 UI 入口产生的一次性商品/库存票据证明人工来源，并在包装方法和实际完成时核对同一对象；检查 `ignoreCost` 可排除这一已知自动路径，但不能作为普遍的人类来源证明。

### 2. 药水交互不是奖励页和商店专属

`NRun` 初始化整个跑局共用的 TopBar 和药水栏。`NPotionHolder.OnRelease`、`NPotionPopup.RefreshButtons` 没有按奖励页或商店限制。原生按钮还受角色存活、药水排队、`CanUseOrRemovePotions`、药水类型及按钮实际启用状态影响。`CanUseOrRemovePotions` 在 `RanwidTheElder`、`StoneOfAllTime`、`TheFutureOfPotions` 等事件中可被关闭。

当前 `CaptureManualOutsidePotionPreState` 只识别顶层奖励页或普通商店，遗漏其他原生允许的局外页面；假商店也不在普通商店识别内。已有 `HasVerifiedVisiblePotionBelt` 只证明药水栏与内部对象对应，不能证明弹窗的 Use/Discard 按钮当时可按。定向药水先经过 `NPotionHolder.TargetNode`，确认目标后才入队；仅在入队时读取当前页面会失去点击时 surface。应从实际 UI 输入入口保留票据，再与同一个 `GameAction` 及完成回执绑定。

### 3. 教学引导的结束回合绕过现有人工入口

`NCannotPlayCardFtue._Ready` 的确认按钮进入 `CloseFtueAndEndTurn`，调用 `NEndTurnButton.SecretEndTurnLogicViaFtue`，直接构造 `EndPlayerTurnAction` 并入队。采集器只 patch `CallReleaseLogic`，故这条可达路径缺少 `ManualCombatInputEvidence`，通常产生 gap；不能声称结束回合入口全覆盖。

### 4. 多张升级选择未进入多选白名单

`CardSelectCmd.FromDeckForUpgrade` 使用独立的 `NDeckUpgradeSelectScreen`，它与 `NDeckCardSelectScreen` 并列继承 `NCardGridSelectionScreen`。`PrepareMultiCardSelection` 的 selector 白名单没有 `NDeckUpgradeSelectScreen`。原生要求多选时，候选冻结会报 `multi_card_selection_options_unavailable`。`Trial` 等事件模型可调用该命令；不能只从已出现的 JSONL 缺口推断交互全集。

### 5. 回执类型和时序仍有边界

- 战斗中 `PlayerChoiceSynchronizer.PlayerChoiceReceived` 目前只结构化 `CombatCard` 与 `Index/Indexes`；其他类型仅写诊断。原生基版的 `CanonicalCard(s)`、`MutableCard(s)` 没有检到调用者，`Player` 只见于局外休息点；`DeckCard` 主要由局外牌组选牌产生，但尚未排除战斗期间由效果触发的情况。遇到未支持且确实发生的战斗回执，至少需要显式 gap。
- `NCardRewardSelectionScreen.OnAlternateRewardSelected` 可完成实际选择；当前采集器观察这个入口但实际使用会记 gap，尚未形成训练标签。
- 地图当前采集点位于 `VoteForMapCoordAction` 执行后端，晚于 `NMapScreen.OnMapPointSelectedLocally`。快速操作下的点击时前态需要核对，不能直接用执行时状态替代。
- 入队事件先于最终排队/执行，动作仍可能取消。`UsePotionAction` 和 `DiscardPotionGameAction` 在执行时重新检查药水槽或目标。商店 `Task<bool> == false` 还可能表示缺货、金币不足、购买/入牌失败或取消，不能解释为“玩家没有选择”。

### 6. 战斗药水的合法集与动作标签不完整

战斗中的手动弃药通过 `NPotionPopup.OnDiscardButtonPressed` 入队；采集器能识别同一原生动作，却会写 `combat_manual_potion_discard_not_structured`，没有对应训练决策。`FairyInABottle.Usage` 是 `PotionUsage.Automatic`，原生弹窗不允许手动 Use；`CollectorCombatProjector.GetPotionActions` 当前没有按 `Usage` 过滤，持有该药水时会把不可点击的手动使用动作列进合法集。

程序集范围的调用点反查还发现 `AutoSlay.Handlers.Rooms.CombatRoomHandler.UseAllPotions` 会调用 `PotionModel.EnqueueManualUse`。因此该模型方法本身也不是普遍有效的“人工点击”证明；当前配置的自动策略检查不包含游戏内 `AutoSlay`。这属于调试/自动跑局条件下的误标风险，尚无普通人类跑局样本证实触发。

`CallReleaseLogic` 还能构造 `UndoEndPlayerTurnAction`；采集器会标记入口，却没有为撤销结束回合建立动作标签。单人普通结束回合后按钮会禁用，当前只能列为条件性风险。战斗 UI 对卡牌和药水还检查 overlay、窥牌、选择器和行动禁用状态，不能只从模型的 `CanPlay` 或药水类型推断所有按钮可用性。

## 对后续实现的约束

先建立“人工 UI 输入 → 冻结点击时完整合法集 → 绑定同一原生动作/Task/选择回执 → 稳定结算”的证据链。局外药水作为当前页面合法集的一部分，而不是只挂在奖励页或商店的特例。自动效果调用同一个后端接口时，不得生成 human 行为标签。任何页面、按钮状态、对象身份或结果无法证明的路径，应保留 `coverage_gap`，使整局回报无效，不能补造样本。

这份审计只指出原生证据与当前采集器之间的关系；本轮没有修改采集器、安装 Mod、启动游戏或改写旧 JSONL。
