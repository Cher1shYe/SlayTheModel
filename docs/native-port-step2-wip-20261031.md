# C++ 原生规则对齐：第二部分暂停记录

2026-10-31，用户要求停止继续开发、释放资源，由用户自行上传到 `workspace_YE`。
本次提交是 **WIP 工作检查点，不是第二部分完成版，也不是可训练版本**。

## 工作位置和版本

- 可编辑副本：`artifacts/dev/cpp-native-aligned-20261031/`。
- C++ 来源：`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`。
- 原生参照：`v0.111.0 / 41cef1ea`；DLL SHA-256 为 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 第一部分完成版仍有独立证据：开发副本内 `validation/round4-step1/`。
- 第二部分开始前的源码备份：`validation/round4-step2/source-before/` 及其 manifest。它表示已验证的第一部分源码，不能与当前 WIP 源码混为一谈。
- 暂停时源码仍保留旧 ruleset v4、观察/动作 13/12、ArmG feature4、快照8声明；这些声明尚未随新布局升级。现存 Python 扩展/可执行文件也不是当前源码的完整新构建。

## 本轮范围与已经落盘的工作

用户最初要求补齐遗物的真实选择、跳过和持续状态；随后明确要求同时扩展另四个角色的完整牌池及相关机制。当前仍以铁甲单人、包括跨角色生牌为主；这不等于另外四个角色的整局流程已完成。

- 实际目标 DLL 导出了五角色牌池顺序、全部卡牌基础/升级数据。保留旧 ID，追加缺失词表；当前生成数据含 596 条卡牌记录（含保留的 Grapple），CardId::COUNT 为 597。原生 Sloth 保持旧 SLOTH_STATUS ID，Null 使用 NULL_CARD 避免宏冲突。
- Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher、Dusty Tome 的奖励候选生成及相关 RNG/遗物联动已有独立实现与对照；局外 15 候选选择、预配置角色/卡牌和恢复流程正在接入。
- Toy Box 蜡制遗物、Small/Large Capsule 生命周期，以及 Bone Tea、Fake Venerable Tea Set、Byrdpip/鸟蛋已有独立模块；固定物理药槽、Delicate Frond 和 Alchemical Coffer 改动尚在集成。
- 静默猎手、故障机器人、亡灵契约师的卡牌/机制源文件及原生样例已落盘；储君的卡牌分支和状态/API头文件已落盘，`simulator/src/regent.cpp` 尚未实现。
- 公共费用修正、Sly/Retain、充能球、Osty、星星、父卡牌执行帧和自动打牌队列开始接入。伤害、能力和回合代码已拆到 `battle_damage.cpp`、`battle_powers.cpp`、`battle_turns.cpp`，仍需完成统一调度。

## 验证边界

下表各项是独立目录内实际目标 DLL 的受控记录；原生样例生成成功不表示当前 C++ 已通过对应差分。

| 样例目录后缀 | 记录数 | 当前 C++ 状态（2026-11-04） |
| --- | ---: | --- |
| card-reward | 82 | C++ 差分通过，5932 项检查 0 失败 |
| persistent | 18 | C++ 差分通过，415 项检查 0 失败 |
| relic-lifecycle | 24 | C++ 差分通过（含 melted-hook、快照与父奖励检查） |
| silent | 240 | C++ 差分通过，242956 项检查 0 失败 |
| necrobinder | 198 | C++ 差分通过，3357 项检查 0 失败（184 卡牌、2 单人目标记录、12 机制样例） |
| defect | 176 | C++ 差分通过，191627 项检查 0 失败（172 卡牌记录、4 充能球记录） |

早期集成结果保留在 `validation/round4-step2/relic-integration-initial.json`。之后又修改了共享布局和执行机制，因此其通过结果不覆盖暂停时全部源码。暂停时没有运行新的全量构建、Python回归、整局冒烟或训练；当前源码尚未闭环，不能声明编译通过或原生等价。

## 2026-11-04 续接进展

上一节是 2026-10-31 暂停时的状态。本轮续接后：

- 当前源码可在 Windows/MSVC 19.51 + Ninja 下完整构建，assert 保持启用（`/UNDEBUG`）。全量 CTest 33/33 通过，其中新增 `regent_mechanics`。
- 上表六个样例集均完成 C++ 差分并通过；`native_step2_{card_rewards,persistent,relic_lifecycle,silent,defect,necrobinder}` 全部在 CTest 中。
- 储君（Regent）生命周期与费用钩子已实现并接入初始化、抽牌、生成、打牌、伤害和回合流程：
  `regent_reset_turn`、`regent_after_side_turn_start`、`regent_after_energy_reset`、`regent_before_hand_draw`、
  `regent_after_player_turn_start`、`regent_player_turn_end`、`regent_enemy_turn_end`、`regent_before/after_card_played`、
  `regent_power_changed`、`regent_card_generated`、`regent_card_entered_combat`、`regent_star_cost`、
  `regent_spend_energy`、`regent_spend_stars`、`regent_void_form_free`、`regent_reflect_block`。
  覆盖星费/星X、Void Form、Child of the Stars、Star Next Turn、Orbit、Monologue、Pale Blue Dot、Sword Sage、
  Arsenal、Supermassive 生成计数、Tyranny、Spectrum Shift、Reflect、Beat Into Shape 命中计数。
- **证据级别必须注意**：仓库里没有原生储君样例集，本轮实现依据的是本机安装 `sts2.dll` 的反编译阅读，
  由 `simulator/tests/regent_mechanics.cpp` 的 51 项自检覆盖。它是“C# 阅读 + 独立规则检查”，不是原生差分等价。
  本机 `sts2.dll` SHA-256 是 `0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9`，
  与差分参照 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4` 不是同一构建。
- 身份已随新布局升级：ruleset `native-41cef1ea-port-v5`、公开观察 v14、动作 schema v13、ArmG feature5、快照 v9。
  观察/动作尺寸由 597 卡、276 能力词表推导：公开观察 67775（战斗 44261）、卡牌特征 625、动作特征 717。
  `PORT_SOURCE.json` 同步并单列本机 DLL 哈希；旧 checkpoint 会被身份检查拒绝，需要重新训练或显式迁移。
- 本机 Python 回归：artifact `tests/` 为 352 passed / 0 failed / 16 skipped；workspace `tests/` 为 39 passed / 1 skipped。
  跳过项均是需要外部历史训练产物、隔离扩展或可选网站数据的用例。
- golden 重录：`test_map_golden_hashes` 的 9 个摘要按 v0.111 对齐后的生成器重录；地图结构仍由性质测试和
  原生 `native_act_41cef1ea.json` 差分覆盖。
- 收尾修复：`Card` 尾部 padding 清零（快照确定性）；回合末 EndOfTurn 局部费用修正按原生
  `PlayerCombatState.EndOfTurnCleanup` 在弃手后清理（此前从不清理 expiration 2，重复 Bullet Time 会耗尽修正槽）；
  相邻相同绝对费用修正去重；新增 `event_pool_type`、`prepare_dusty_tome`、`card_multiplayer_only` 绑定。
- 仍未完成：原生储君样例生成与差分；药槽空位模型与遗物选择/持续状态全部接入；Splash/跨角色生成与单人过滤审计；
  整局冒烟与训练。未提交、推送或替换参照证据。

## 2026-11-04 第二部分（Aeonglass / ByrdonisNest / Splash / 药水槽 / 原生顺序）

身份更新：ruleset `native-41cef1ea-port-v6`、公开观察 v15（67784 = 局外 23519 + 战斗 44265）、
动作 schema v13（717 维）、ArmG feature v6、快照 v10。`PORT_SOURCE.json` 已同步；
旧 checkpoint/快照会被身份检查拒绝。

- 药水腰带改为原生物理槽语义（null 空洞、首空位添加、保空位移除、满槽替换/丢弃），并接入快照校验、
  公开观察、Python 绑定与 ArmG 编码。
- Splash 使用全部已解锁角色池、仅当池数 >1 时排除持有者池、过滤可战斗生成 Attack、
  `GetDistinctForCombat` 取 3、可跳过、选中牌本回合免费入手。
- Aeonglass Boss 与 Wither/WitheringPresence 已实现（512/535 HP、Ebb 22/26+33 格挡、
  Eye Lasers 11x2/12x2、Increasing Intensity 假升级与累积力量、六张计数、Artifact 3）。
- ByrdonisNest 两个选项、宠物过滤、首次运行 Overgrowth 教学房间槽 0 已实现。
- 事件袋按原生 `AllEvents.Concat(AllSharedEvents)` 声明顺序构建（四种幕各自的名单）；
  Hive 遭遇按原生 20 项声明顺序并排除非原生 `SETUP_TUNNELER_NORMAL`；Boss 的
  `AllBossEncounters` 与 `BossDiscoveryOrder` 均按原生声明顺序。
- WhisperingHollow、WoodCarvings、ZenWeaver 已登记为 unsupported（清单完整，但按设计不入袋）。

验证（Windows/MSVC 19.51 + Ninja，Release + `/UNDEBUG`）：完整重建成功；CTest 33/33；
C++ rules_regression 539 项检查 0 失败；artifact pytest 363 passed / 0 failed / 16 skipped；
`bench.exe run 1000` 1000 局全部正常终止、0 截断、0 异常；同机交错吞吐中位数 68.2 → 65.3 局/秒。
workspace 根 `tests/` 不适用于该构建：它导入不同的 `deployment` 包布局，且基础仓库的
`sts2_sim` 扩展比其源码旧（缺少 `mcts_priors` 等绑定）。证据在
`artifacts/dev/cpp-native-aligned-20261031/validation/step2-aeonglass-events-20261104/`。

**仍未完成**：目标 DLL `9cb4f1ad…` 不在本机，`native-run-fixtures` 也没有整局原生轨迹
（`gameSceneLoaded=false`，仅受控遗物样例），因此同种子/同进度/同决策的整局长路径原生差分仍阻塞；
本地 `0861bfa1…` 的 `release_info.json` 虽标注同一 `41cef1ea/v0.111.0`，按约定不冒充目标参照。
本轮另按反编译实现 TeaMaster、RoundTeaParty、TrashHeap、ColossalFlower、WhisperingHollow、
TheLegendsWereTrue、JungleMazeAdventure、InfestedAutomaton、DollRoom、SlipperyBridge、
TheFutureOfPotions、ZenWeaver、Amalgamator 共十三个事件。当前事件清单 66 项中 22 IMPLEMENTED、
23 APPROXIMATE、21 UNSUPPORTED；缺失事件仍会改变事件袋 RNG。
仍未覆盖的事件按原因分：CrystalSphere 是交互式小游戏；FakeMerchant 是自定义商店 UI；
Trial/TinkerTime/BattlewornDummy/PunchOff 需要事件战斗编排；TheLanternKey 需要事件战斗 + 特殊卡奖励；
EndlessConveyor 是多轮加权菜品循环（含变化/无色卡/药水奖励）；
ColorfulPhilosophers/LuminousChoir/MorphicGrove/RanwidTheElder/RelicTrader/Bugslyer
需要多卡/遗物选择或未建模的卡池交互；WoodCarvings/Symbiote/SelfHelpBook/GraveOfTheForgotten/
FieldOfManSizedHoles 需要尚未建模的附魔（Corrupted/Sharp/SoulsPower/PerfectFit）；
WarHistorianRepy 原生 IsAllowed 恒为 false，不是实际缺口。
实现限制：SlipperyBridge 的跳过集合只记录前 62 个卡组位置；TheFutureOfPotions 的均匀三选一
顺序是近似实现。两者均在 `simulator/tests/rules_regression.cpp` 注明。
Wither 假升级层数未进入公开观察（少编码，无隐藏信息泄漏）；战斗单步吞吐约 1.9x 变慢待剖析。

## 恢复工作时的顺序

1. 重新核对文件和分工。此前并行任务已停止，不自动恢复旧 agent。
2. 完成储君机制、通用卡牌费用和自动打牌/选牌恢复；将各角色钩子接入初始化、抽牌、生成、打牌、伤害和回合流程。当前 `draw_cards` 声明/实现、新增调用与缺失定义仍待统一，回合状态机尚未完成。
3. 完成药槽空位模型、遗物奖励继续执行、Dream Catcher 正常奖励和 Prismatic Gem 全角色奖励池；检查 Splash、跨角色生成与单人过滤。
4. 统一 clone/快照校验/隐藏状态重采样、公开观察、Python绑定、ArmG和动作编码。补全可见/隐藏自动队列区别；新的 `AutoPlayRequest.visible` 尚未在所有入队路径正确赋值。
5. 统一 ruleset、schema、snapshot、引擎身份；重建后逐项跑新角色和遗物差分，再跑旧回归。修复每个失败后再汇总完成状态，保留此前失败证据。

已确认的注意点：负 Strength/Focus 等能力是否被 Artifact 拦截取决于原生 `GetTypeForAmount`，不能只看静态 Buff 类型；`Single` 也不能直接把 Amount 限制为1。多选中暂存实体、Nightmare 模板、父执行帧和药槽空位都需正确处理身份与观察。

## 上传方式

根 `.gitignore` 忽略 `artifacts/`，普通 `git add .` 不会上传主要 C++ 改动。
使用同目录 `native-port-step2-upload-paths.txt` 的明确清单强制添加。
清单包含当前开发源码、构建依赖头文件、测试/宿主源代码、文本证据与源码备份；排除了游戏 DLL、复制的游戏 App、原生反编译树、模型权重、编译产物、缓存和根目录无关改动。

```sh
cd /Users/yebohou/SlayTheModel
git switch workspace_YE
git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-step2-upload-paths.txt
git diff --cached --stat
git commit -F docs/native-port-step2-commit-message.txt
git push -u origin workspace_YE
```

以上命令由用户执行。本次仅准备本地文档和上传清单，没有代为暂存、提交或推送。

## 2026-11-04 第二批事件与附魔对齐（当前断点）

在上一批基础上又实现 9 个事件：MorphicGrove（金币门槛+两次变形/5 最大生命）、
Bugslayer（Exterminate/Squash）、EndlessConveyor（加权菜品轮换、每第五次
Seapunk Salad、40 金币锁）、Trial（商人/贵族/无名者三支线、驳回页与弃跑）、
PunchOff（第 6 层门槛、Nab 遗物、SETUP_PUNCH_OFF 事件战斗及战后遗物/药水奖励
延迟到奖励界面生成）、RanwidTheElder（药水/100 金币/可交易遗物换前沿遗物）、
RelicTrader（≥5 件可交易遗物、StableShuffle 后取三）、SelfHelpBook
（Sharp/Nimble/Swift）、WoodCarvings（Basic 牌转 Peck/ToricToughness 或
Slither 附魔）。

支撑改动：

- `relic_is_tradable` 按反编译实现 `RelicModel.IsTradable`：排除已融化、
  Starter/Event/Ancient，以及 46 个在原生类中覆写
  `HasUponPickupEffect`/`SpawnsPets` 的遗物（离线审计同一提交反编译得到，
  代码内有来源注释）。
- `RunContext::remove_relic` 同步移动 id/aux/wax/melted 槽位。
- 新增附魔 `SHARP`（攻击牌 +2 伤害）与 `SLITHER`（可附魔非 X 费可打出牌，
  每次抽到时用 `Rng.CombatEnergyCosts` 重掷 0..3 费）；`card_can_enchant`、
  快照校验上界与事件选择类型 7-10 同步扩展。
- WoodCarvings 的 kind-4 选择只允许 Basic 可变牌。

清单更新为 66 项中 **33 IMPLEMENTED / 23 APPROXIMATE / 10 UNSUPPORTED**。
10 个 unsupported 里 AROMA_PLACEHOLDER 在原生反编译中不存在，
WarHistorianRepy 的 `IsAllowed` 恒为 false；真实可玩缺口 8 项
（CrystalSphere、FakeMerchant 为交互 UI；TinkerTime 需 MadScience；
BattlewornDummy、TheLanternKey 需事件怪；FieldOfManSizedHoles、
GraveOfTheForgotten、Symbiote 需 PerfectFit/SoulsPower/Corrupted 附魔）。

验证（Windows/MSVC 19.51 + Ninja，Release + `/UNDEBUG`）：完整重建成功；
CTest 33/33；`rules_test.exe` 686 项检查 0 失败；artifact pytest 363 passed /
16 skipped / 0 failed；`bench.exe run 1000` 1000/1000 正常终止、0 截断、
0 异常、70.1 局/秒、战斗 4.0 µs/步。快照恢复用例的种子 32 在新事件规则下
提前结束，改用经验证的种子 4（250 步时仍未终止），跳过分支保留。

仍然阻塞：目标 DLL `9cb4f1ad…` 不在本机，无同种子目标差分；RelicTrader 的
StableShuffle 用遗物 key 作为 ModelId ordinal 的代理，需目标构建确认。
战斗单步约 4.0 µs（基线约 2.3 µs）待剖析。未提交、推送或覆盖旧证据。

### 续：第三批事件与事件战斗（2026-11-04，同日）

新增实现并进入原生事件袋：FieldOfManSizedHoles、GraveOfTheForgotten、
Symbiote（PerfectFit/SoulsPower/Corrupted 三种附魔）、BattlewornDummy
（BattleFriendV1/V2/V3 + `BattlewornDummyTimeLimitPower` 的敌方回合末递减/
第三次超时逃脱与 V1 药水、V2 两次 StableShuffle 升级、V3 前置遗物）、
TheLanternKey（MysteriousKnight 的 FlailKnight 随机分支 AI、100 金返还、
胜利后固定 LanternKey 特殊卡奖励）；ThisOrThat 由 APPROXIMATE 提升为
IMPLEMENTED（Ornate 使用 `PullNextRelicFromFront` 同一 rewards RNG 稀有度
roll + 前置抽取，再添加 Clumsy）。

引擎补充：事件战斗结束后可构造自定义奖励（药水/遗物/指定卡），超时逃脱以
`alive=false 且 hp>0` 与击杀区分；MysteriousKnight 走现有生成状态机，并对
生成数据缺失的 A8 HP 108、A9 Flail 10 / Ram 17 做显式补偿（`FAILURES.md`
16-18，生成器重生成仍是正确修复）。

事件清单更新为 66 项中 **39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED**。
5 项 unsupported 中 AROMA_PLACEHOLDER 无原生类、WarHistorianRepy
`IsAllowed` 恒 false、CrystalSphere 原生 `IsDeterministic=false`（交互
小游戏）；真实剩余缺口为 FakeMerchant（自定义商店库存 UI）与 TinkerTime
（MadScience 动态卡型/词条状态）。

验证：完整重建成功；CTest 33/33；`rules_test.exe` **775 项检查 0 失败**；
artifact pytest 363 passed / 16 skipped / 0 failed；`bench.exe run 1000`
1000/1000 正常终止、0 截断、0 异常。三次连续吞吐 66.7/67.2/66.5 局/秒、
战斗 4.4 µs/步，保存的单次样本 67.6 局/秒、4.2 µs/步；与 ~2.3 µs 基线的差距仍未
剖析，未以规则或选择换速度。目标 DLL 仍缺失，同种子目标差分继续阻塞。

### 续：第四批事件战斗奖励修正（2026-11-04，同日）

反编译核对发现事件战斗奖励被整体抑制是规则错误：
`EncounterModel.ShouldGiveRewards` 默认为 true，只有
`BattlewornDummyEventEncounter` 的三个变体覆写为 false；
`RewardsSet.WithRewardsFromRoom` 先按房间类型生成普通奖励（金币、药水判定、
三选一卡牌），再把 `CombatRoom.ExtraRewards` 追加到列表末尾。修复后：

- DenseVegetation、PunchOff、TheLanternKey（MysteriousKnight）恢复标准怪物
  奖励；PunchOff 追加遗物+药水，TheLanternKey 追加固定 LanternKey 特殊卡，
  放入下一个空奖励卡槽（不再覆盖标准卡槽 0），取/跳过仍是真实选择。
- 这些事件都传 `shouldResumeAfterCombat=false`：奖励列表生成时清除事件状态，
  离开奖励界面即结束房间回到地图。
- BattlewornDummy 保持 `ShouldGiveRewards=false`：无标准奖励、事件恢复、
  仅真实击杀后按其变体发奖。

回归新增：PunchOff 标准金币/三选一 + 额外遗物/药水 + 事件状态清零；
DenseVegetation 标准奖励与事件结束；TheLanternKey 标准卡槽 0 + 特殊卡槽 1。
`tests/test_smoke.py` 快照回放种子由 4 改为 5：修正后的奖励改变轨迹，种子 4
在 250 步前死亡（种子 5 已验证 250 步非终局，条件跳过分支保留）。

验证：完整重建成功；CTest 33/33；`rules_test.exe` **795 项检查 0 失败**；
artifact pytest 363 passed / 16 skipped / 0 failed；`bench.exe run 1000`
1000/1000 正常终止、0 截断、0 异常、70.4 局/秒、战斗 4.2 µs/步
（`validation/step2-aeonglass-events-20261104/*-final-20261104d.txt`）。
事件清单仍为 39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED。目标 DLL
`9cb4f1ad…` 仍缺失，同种子整局差分继续阻塞。

### 续：第五批事件 RNG 边界与事件精化（2026-11-04，同日）

核对反编译中全部双参数 `Rng.NextInt(min, max)`（原生 max 为排他上界），
修正 4 处实现内容的 off-by-one：

- PunchOff CalculateVars 金币：91..99 → 91..98。
- LuminousChoir 费用：`149 - NextInt(0,50)` → 100..149（原先允许 99）。
- WhisperingHollow 金币代价：`35 + NextInt(-9,10)` → 26..44（原先允许 45）。
- PunchOffEventEncounter 初始扣血：`NextInt(2,10)` → 2..9。

StoneOfAllTime 的 Lift 原先把 `NextItem(Player.Potions)` 的索引直接用于压缩
数组；现在按非空物理槽映射并调用 `potion_remove_at`，丢弃所选药水后保留空槽。

经反编译审计、补回归并提升为 IMPLEMENTED 的 4 个事件：DenseVegetation、
BrainLeech、PotionCourier、SpiritGrafter。事件清单更新为
**43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED**。

验证：完整重建；CTest 33/33；`rules_test.exe` **829 项检查 0 失败**；
artifact pytest 363 passed / 16 skipped / 0 failed；`bench.exe run 1000`
1000/1000 正常终止、0 截断、0 异常；本次并发负载下 65.1 局/秒、4.7 µs/步。
证据：`validation/step2-aeonglass-events-20261104/*-final-20261104e.txt`。

仍未修并已记录的 RNG 缺口：怪物 HP 抽样和部分遭遇随机使用 MonsterAi 流，
原生 `Creature.SetUniqueMonsterHpValue` 使用 Niche 流并排除同侧重复 HP；
109 个怪物中 108 个 HP 范围来自 512 次采样而非反编译。目标 DLL
`9cb4f1ad…` 仍缺失，同种子整局原生差分继续阻塞。

### 续：第六批 Orobas 锁定选项（2026-11-04，同日）

原生 Orobas 的 `OptionPool3` 在 TouchOfOrobas（需 Starter 稀有度遗物）与
ArchaicTooth（需牌组含 Bash/Neutralize/Unleash/FallingStar/Dualcast）都无法
建立时返回 `onChosen=null` 的禁用选项。C++ 现在把远古事件中 INVALID 遗物槽
标为不可选，并保留锁定分支下的一次 `NextItem` 抽取。ArchaicTooth 条件同步
修正为原生起始牌集合，不再错误接受 BREAK。

验证：完整重建；CTest 33/33；`rules_test.exe` **833 项检查 0 失败**；
artifact pytest 363 passed / 16 skipped / 0 failed；`bench.exe run 1000`
1000/1000 正常终止、0 截断、0 异常、70.5 局/秒、4.2 µs/步。
证据：`validation/step2-aeonglass-events-20261104/*-final-20261104f.txt`。
事件清单仍为 43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED；目标 DLL
`9cb4f1ad…` 仍缺失，同种子整局原生差分继续阻塞。

### 续：第七批 怪物初始 HP 与遭遇 RNG（2026-11-04，同日）

反编译 `Creature.SetUniqueMonsterHpValue` 确认初始 HP 从
`RunState.Rng.Niche` 抽取，并在同侧已创建生物的 MaxHp 之外按升序集合
`NextItem`；集合为空时退回整段均匀抽取。C++ 现按该算法两遍选择（先计数、
一次 `NextInt(0,count)`、再取第 k 个未占用值），`spawn_at` 改用 `nicheRng`。

HP 范围由新的提取器
`validation/step2-monster-hp-20261104/extract_hp.py` 从本地反编译的
`MinInitialHp`/`MaxInitialHp` 计算（A0/A8，含继承与 Axebot 默认
StockAmount=2）。106/109 匹配，23 个范围与原参考引擎采样值不同并已更新
（如 Crusher 209/219、Byrdonis 81..84、WaterfallGiant 240）。DOOR /
DOORMAKER / ROYAL_GUARD 在该反编译中无对应类，保留 sampled_only。

遭遇随机改用原生一次性 RNG：`EncounterModel.Rng = new Rng(seed + TotalFloor
+ hash(Id.Entry))`，`Id.Entry = StringHelper.Slugify(类名)`。`EncounterDef`
新增 `nativeEntry`（事件遭遇含 `_EVENT_ENCOUNTER` 等后缀；DoormakerBoss /
ToadpolesNormal 标为 null）。`begin_combat` 在 `++floor` 后构造该 RNG，
`setup_encounter` 用它处理 roster 选择、Decimillipede / ScrollsOfBiting /
TwoTailedRats / CorpseSlugs 的关联起始、以及 PunchOff 两次
`StartingHpReduction`；单 roster 遭遇不再消耗抽取。修正 Decimillipede
`StarterMoveIdx` 到 WRITHE/BULK/CONSTRICT 的映射，CorpseSlugs 改为一次
抽取轮转。MonsterAi 仍用于 `RollMove`/随机分支，与原生一致。

验证：clean 完整重建（exit 0、0 error）；CTest 33/33；`rules_test.exe`
**833 项检查 0 失败**；artifact pytest 363 passed / 16 skipped / 0 failed；
`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常（本次 52.5 局/秒、
5.7 µs/步；同机负载噪声区间约 51–108 局/秒）。证据：
`validation/step2-monster-hp-20261104/`（clean 重建 `build-clean-20261104h.txt`，
测试 `*-final-20261104i.txt`）。

仍为近似：roster 变体按采样权重选择，未逐遭遇重放原生 `NextItem(items)`；
`random_encounter_for_act` 的 bag 耗尽回退仍用 MonsterAi（原生为地图生成
UpFront）。`docs/MONSTERS_REFERENCE.md` 仍保留旧采样 HP。目标 DLL
`9cb4f1ad…` 仍缺失，同种子整局原生差分继续阻塞。

### 续：第八批 遭遇名单重新盘点（2026-11-04，同日）

新增 `extract_encounters.py`，自动比对反编译 `GenerateMonsters` 与
`content/monsters.json` 的采样 roster。修正 6 个确定性名单：AxebotsNormal
1 只；ExoskeletonsNormal/Weak 4/3 只；SlumberingBeetleNormal 为
Rock+Silk+Beetle；TunnelerNormal 为 Chomper(ScreamFirst)+Tunneler；
GremlinMercNormal 仅 Merc。Merc 的 Sneaky/Fat 不再作为初始成员，而由
`SurprisePower.AfterDeath` 在死亡时依次追加到敌方列表末尾，并把偷取金币
转给 Fat（`battle_damage.cpp`）。

6 个随机 roster（Flyconid、Slimes normal/weak、SlitheringStrangler、
Bowlbugs normal/weak、RubyRaiders）改为在 `native_random_roster` 中逐步重放
原生 `NextItem`/`NextBool` 抽取；SlimesWeak 使用原生 small1, medium, small2
顺序。DenseVegetation 的审计差异为解析器误报（原生按四个 Slots 循环）。

验证：完整重建；CTest 33/33；rules 833/0；monster audit 0 失败；pytest
363 passed / 16 skipped；1000 局冒烟 0 异常/0 截断（47.4 局/秒、6.8 µs/步）。
证据：`validation/step2-monster-hp-20261104/`（`*-final-20261104j.txt`、
`encounter-roster-audit*.txt`）。目标 DLL `9cb4f1ad…` 仍缺失，整局差分阻塞。

### 续：第九批 遗物抽取来源审计（2026-11-04，同日）

反编译核对全部 15 处 `RelicFactory.PullNextRelicFromFront/Back` 调用点。
`RelicModel.IsAllowedInShops` 在五个遗物上为 false（AmethystAubergine :85270、
BowlerHat :86427、LuckyFysh :90675、OldCoin :91661、TheCourier :95609），
商店 `MerchantRelicEntry.FillSlot`（:179906）和 Wongos 两处购买（:129531、
:129587）都按它过滤；C++ 此前只在前排无过滤、后排仅排除 OldCoin/TheCourier。
新增 `relic_allowed_in_shops` 与 `RunContext::pull_relic(..., shopsOnly)`；
前排被过滤的遗物按原生 `PullFromFront` 语义保留在队列中（只有 run-state
不允许的遗物会被清除）。

`WelcomeToWongos.GenerateInitialOptions` 在事件开始时以显式 `RelicRarity.Rare`
从玩家稀有队列前排抽取 FeaturedItem（不消耗 Rewards 随机数）并移出共享袋；
C++ 此前按 RelicId 顺序扫描、不消耗背包。现在事件开始即存入 `eventData[0]`，
FeaturedItem 购买直接获得该遗物，Bargain Bin 改为显式 Common 前排 + 商店过滤。
其余 12 处调用点（LargeCapsule、ToyBox、PaelsWing、BattlewornDummy V3、
LuminousChoir、Ranwid、RelicTrader、RoundTeaParty、ThisOrThat、Trial、
UnrestSite 等）与原生抽取顺序一致。

旧存档说明：上一版本写入的中途 Wongos checkpoint 在 `eventData[0]` 保存当时
扫描的遗物；快照布局未变，仍可恢复并按其获得。

同时复核 `TabletOfTruth`、`LostWisp`、`SapphireSeed`、`Wellspring` 并提升为 IMPLEMENTED：
TabletOfTruth 逐页费用 3/6/12/24/MaxHp-1、第五次升级全部可升级牌、致命分支先把
MaxHp 降到 1 再 Kill；LostWisp 金币为 `60 + base.Rng.NextInt(-15, 16)`，Claim
加 Decay 与 LostWisp 遗物（Power 牌触发 8 点 Unpowered 伤害）；SapphireSeed 的
Eat 回血 9 + 升级、Plant 只对 Sown 可附魔牌选择；Wellspring 的 Bottle 按
Ironclad+共享药水池顺序从 Rewards 流抽 1 瓶并作为药水奖励，Bathe 先移除
1 张再加 Guilty。以上均有 `map_event_audit` / `enchantment_contract` 回归。

验证（当前源码 clean 完整重建 `build-clean-20261104q.txt`，exit 0、0 error）：
CTest 33/33（`ctest-final-20261104q.txt`）；`rules_test.exe` 840 项检查 0 失败
（`rules-regression-final-20261104q.txt`，新增 7 项 Wongos/商店检查）；
monster audit 0 失败；pytest 363 passed / 16 skipped
（`pytest-final-20261104q.txt`）；1000 局冒烟 0 异常/0 截断、77.2 局/秒、
3.9 µs/步（`benchmark-runs-1000-final-20261104q.txt`）。事件清单现为
47 IMPLEMENTED / 14 APPROXIMATE / 5 UNSUPPORTED。目标 DLL `9cb4f1ad…`
仍缺失，同种子整局原生差分阻塞。
