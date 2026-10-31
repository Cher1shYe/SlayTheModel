# 高速模拟器第八轮深度审计（2026-10-29）

## 结论

当前模拟器仍能完成大量整局和战斗，且本轮没有发现新的稳定崩溃、越界或永久卡死。
它仍不具备“与 STS2 参考实现等价的高保真训练环境”资格。本轮在既有第七轮问题之外
又确认了三类系统性缺陷：

1. 奖励和商店药水绕过 rarity 分层、去重和合法池过滤；
2. 遭遇生成时附带的初始招式、起始 HP、初始格挡等状态没有进入运行时；
3. 战斗卡生成没有携带 `CanBeGeneratedInCombat`，并把 Character 池、Colorless 池、
   combat-only 行为和奖励池混用。

这些都不是显示层差异，会直接改变卡牌奖励、战斗动作价值、事件战斗和 run outcome。

本轮没有修改生产源码，只新增和运行 `.scratch/deep-audit-round8-20261029` 下的探针。

## 测试对象与路径

- 项目：`D:\sts2_datacollection\sts2`
- STS1 参考：`D:\sts2_datacollection\sts1`
- STS2 反编译参考：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- Git HEAD：`a57a7029b69a85aee13bf38d41efa9597672fad6`，工作树包含大量未提交修复
- 新探针目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029`
- 新综合探针：`round10_findings.cpp`
- 新综合结果：`round10-findings-results.txt`
- 新药水池探针：`round10_potion_pool.cpp`
- 新药水池结果：`round10-potion-pool-results.txt`
- 正式回归源码：`simulator/tests/rules_regression.cpp`
- Python 测试：`tests`
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`

## 工程基线

| 检查 | 结果 |
|---|---:|
| `sts2_rules_test` 正式构建 | 失败，6 个测试调用写错 |
| 仅修正调用形态后的同一规则测试 | 345 / 345 pass |
| `pytest tests -q` | 81 passed, 2 failed, 1 skipped |
| 现有 Python 失败 | `test_full_run_completes_and_wins`、`test_jsonl_trajectory_and_batch` |
| 第 9 轮 5000 seed 随机整局扫描 | 0 error、0 cap、5000 / 5000 terminated、0 win |
| 第 9 轮持久化遭遇矩阵 | 5340 场 0 failure、3 capped |
| 第 9 轮持久化整局矩阵 | 300 局 0 failure、0 capped |

正式 `sts2_rules_test` 在 `simulator/tests/rules_regression.cpp` 约 2379-2440 行把
`event_begin(r, ...)` 写成了 `r.event_begin(...)`。受影响的 6 个事件测试分别为
RoomFullOfCheese、DenseVegetation、SpiritGrafter、WelcomeToWongos、Wellspring 和
PotionCourier。现有 `simulator/rules_test.exe` 不能证明当前测试源码可构建。

两个 Python 失败都是旧固定 seed 必胜 oracle：seed 273 在 floor 19 死亡，seed 443
也已死亡。固定 seed 在规则修复后漂移不是模拟器稳定性的反例，但测试合同需要重写为
可验证的终局/轨迹性质，不能继续维护“某 seed 必须胜利”的脆弱断言。

公开 schema 当前实际值：

- `PUBLIC_OBS_VERSION=7`
- `ACTION_SCHEMA_VERSION=6`
- `PUBLIC_OBS_DIM=17815`
- `PUBLIC_COMBAT_OBS_DIM=10378`
- `CARD_FEAT_DIM=241`
- `ACTION_FEAT_DIM=330`

`README.md:193-197` 仍写 `PUBLIC_OBS_DIM=17805`、`PUBLIC_COMBAT_OBS_DIM=10368`，
文档已过期。

## 新问题 R8-01：奖励和商店药水池严重错误（P1）

`simulator/src/run.cpp` 的 `random_potion_from()` 只检查 `ironclad` 布尔值，然后
在 52 个池项中均匀抽取。官方 `PotionFactory` 先从 Character + SharedPool 取得合法
项，再按 65% Common / 25% Uncommon / 10% Rare 抽 rarity，并在一次生成多个药水时
移除已选项。

当前错误包括：

- Common、Uncommon、Rare 各 16 项，实际各约 30.77%，应为 65 / 25 / 10；
- 实际还会抽到 4 个非普通 rarity 项：FoulPotion、GlowwaterPotion、
  PotionShapedRock、DeprecatedPotion；
- 商店三项有放回抽取，可能出现重复药水；
- DeprecatedPotion 的 `rarity=None`、usage 也不匹配，但当前可正常进入奖励和商店。

50,000 次初版探针因逐 seed 重初始化整局过慢，改为有界采样后结果：

- 常规奖励：2,000 次实际掉药水中，36 次 Deprecated、151 次非法 rarity；
- 商店：15,000 个槽位中，282 次 Deprecated、1,125 次非法 rarity；
- 5,000 个三项商店中，293 个含至少一对重复药水。

参考：

- `MegaCrit.Sts2.Core.Factories/PotionFactory.cs`
- `MegaCrit.Sts2.Core.Models.PotionPools/IroncladPotionPool.cs`
- `MegaCrit.Sts2.Core.Models.PotionPools/SharedPotionPool.cs`
- `MegaCrit.Sts2.Core.Models.Potions/DeprecatedPotion.cs`
- `MegaCrit.Sts2.Core.Entities.Merchant/MerchantInventory.cs`
- `MegaCrit.Sts2.Core.Rewards/PotionReward.cs`

注意：第七轮曾报告“精英 rare 只有约 6.1%”，该结论无效；旧探针每次重置 rarity
offset，没有模拟持久 pity 状态。新连续奖励测试约 108‰，与动态期望 10.9% 相符。
不要把该旧结论继续带入修复。

## 新问题 R8-02：战斗卡生成没有 `CanBeGeneratedInCombat`（P1）

官方 `CardFactory.FilterForCombat()` 同时过滤：

- `CanBeGeneratedInCombat`；
- Basic、Ancient、Event rarity；
- multiplayer constraint；
- 调用方指定的 CardPool。

当前 `CardDef` 没有 `CanBeGeneratedInCombat`，`BattleContext::random_card_of_type()`
和 `random_colorless_card()` 只过滤 rarity/UNPLAYABLE/MULTIPLAYER_ONLY，因此会生成：

- Feed；
- HandOfGreed；
- Alchemize。

2,000 seeds 的 4,000 次定向抽样中命中 118 次本应禁止的战斗生成卡。

当前 `random_card_of_type(type, true)` 还会把 Character 池和 Colorless 池合并。
官方下列接口只使用 `Character.CardPool`：

- Orobic Acid；
- Crossbow；
- Choices Paradox。

动态结果：

- Orobic Acid 在 2,000 次使用中生成 2,375 张 Colorless 卡，应为 0；
- Crossbow 在 2,000 次触发中生成 600 张 Colorless 卡，应为 0；
- Choices Paradox 2,000 / 2,000 次候选错误：当前只生成 3 张且可含 Colorless，
  参考生成 5 张不重复 Character 卡、全部附 Retain、然后三选一屏幕；
- Jack of All Trades 2,000 次升级牌使用中有 111 次生成自身或重复结果，参考必须
  从可战斗 Colorless 池去重并明确排除 JackOfAllTrades 自身；
- Vexing Puzzlebox 在 2,000 次触发中全部只生成 Attack，参考允许 Character 池任意
  类型；同时 2,000 次生成的牌都不是整场战斗免费，而是当前回合临时免费；
- Toolbox 2,000 / 2,000 次候选合同错误：当前把候选临时降为 0 费，且可能有重复
  或生成 Alchemize/HandOfGreed；参考只是从 3 张去重、合法、原价 Colorless 卡中选 1。

参考：

- `MegaCrit.Sts2.Core.Factories/CardFactory.cs`
- `MegaCrit.Sts2.Core.Models.Potions/OrobicAcid.cs`
- `MegaCrit.Sts2.Core.Models.Relics/Crossbow.cs`
- `MegaCrit.Sts2.Core.Models.Relics/ChoicesParadox.cs`
- `MegaCrit.Sts2.Core.Models.Cards/JackOfAllTrades.cs`
- `MegaCrit.Sts2.Core.Models.Relics/VexingPuzzlebox.cs`
- `MegaCrit.Sts2.Core.Models.Relics/Toolbox.cs`

## 新问题 R8-03：遭遇级怪物初始化没有进入 JSON/运行时（P1）

生成器把同一 Monster 在不同 encounter 中的初始状态采样进一个 `initial` 权重表，
但运行时 `spawn_at()` 对每只怪物独立抽初始状态，丢失 encounter 的协调约束。

2,000 seeds 动态失败数：

| 场景 | 参考约束 | 失败数 |
|---|---|---:|
| DecimillipedeElite 起手 | 三段分别是三种不同招式 | 1,557 |
| ChompersNormal 起手 | 第一只 Clamp，第二只 Screech | 1,501 |
| InkletsNormal 起手 | Jab, Whirlwind, Jab，仅中间 Whirlwind | 1,704 |
| PunchOff 起手 | 第一只 StrongPunch，第二只 Ready | 1,640 |
| PunchOff 初始 HP | MaxHp=55，两只 CurrentHp 各为 45..53 | 4,000 个个体 |
| ScrollsOfBitingNormal | 前三只三招轮换，第四只固定 MoreTeeth | 1,826 |
| ScrollsOfBitingWeak | 三只三招轮换 | 1,569 |
| TwoTailedRatsNormal | 三只三种不同起手 | 1,557 |
| TheKinBoss | 第一只 Follower 先 PowerDance，第二只 QuickSlash | 1,501 |

Decimillipede 还单独缺少 `AfterAddedToRoom()` 的生命处理。参考会把每段最大生命
向上取偶，并在 42..48 间调整到三段互不相同；2,000 seeds 中产生 2,571 个奇数最大
生命和 838 组重复最大生命。

CubexConstruct 的 `AfterAddedToRoom()` 固定获得 13 Block，当前 2,000 / 2,000 个
场景均为 0 Block。

PunchOff 的生成数据还把事件中的 CurrentHp 46..55 误当成普通 HP range，运行时
直接以 `hp=maxHp` 生成；参考要求两只 MaxHp 都是 55，并分别扣 2..10 点起始生命。

参考：

- `MegaCrit.Sts2.Core.Models.Encounters/DecimillipedeElite.cs`
- `MegaCrit.Sts2.Core.Models.Monsters/DecimillipedeSegment.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/ChompersNormal.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/InkletsNormal.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/PunchOffEventEncounter.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/ScrollsOfBitingNormal.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/ScrollsOfBitingWeak.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/TwoTailedRatsNormal.cs`
- `MegaCrit.Sts2.Core.Models.Encounters/TheKinBoss.cs`
- `MegaCrit.Sts2.Core.Models.Monsters/CubexConstruct.cs`

## 仍存在的已知核心缺陷

第七轮、第八轮和第 9 批探针中的以下问题仍复现，本轮没有修复：

- 9 个正常怪物初始 Power 和 5 个动态 Power 缺规则：Illusion、HighVoltage、
  Ravenous、Shriek、Skittish、Hatch、Plow、Soar、Flutter、Burrowed、
  SteamEruption、Surrounded 等；
- GasBomb 自爆后仍 alive；Guardbot 不给 Fabricator 15 Block；
- Noisebot、SoulFysh、TheInsatiable 随机插入 draw 被错误标记为已知顶部；
- TheInsatiable 没有 Sandpit 噬入结算；
- ThievingHopper 不删除被偷牌；
- Doormaker 第二次 Door 复活最大生命为 215，参考为 195；
- 若干遗物、BeltBuckle、SelfFormingClay、PaperCuts 等 hook 仍有错误；
- 事件合法性没有接入 `event_pool_for_act()`，encounter bag 和 relic grab bag/seen
  queue 仍不是参考语义；
- reward、shop、event/ancient 选项仍共用多个错误的池或选择动作近似；
- DualWield、MadScience、ToricToughness 等卡牌仍缺行为或状态模型；
- 公开观察仍遗漏大量可见/可推断状态，snapshot restore 只验证 header；
- 容量不足时部分购买、加牌和事件操作仍非原子；
- Ancient 遗物和 74 个带实际 `AfterObtained` 的遗物仍有大量 no-op 或近似实现。

第七轮报告仍是最完整的累计清单：
`D:\sts2_datacollection\sts2\docs\simulator-deep-audit-round7-2026-10-29.md`

## 正向结果

- 当前 C++ 规则行为在修正测试调用后 345 / 345 通过；
- 5000 seed 随机整局没有 error/cap，全部终止；
- 持久化遭遇矩阵和整局矩阵没有 failure；
- RNG 的 `.NET` 前缀、counter、Gaussian 规则已经通过新增回归；
- 战斗卡池的 Ancient/Event/Status/Token rarity 过滤已有回归并通过；
- 本轮没有发现新的 P0 崩溃或无限循环。

## 尚未覆盖和残余风险

本轮重点补齐了 C# Monster 文件中的非 JSON command、AfterAddedToRoom、encounter
初始化和 potion/card factory。仍未做到对真实客户端逐步 replay 的全轨迹差分。
特别是多人缩放、全部 289 relics 的组合顺序、完整 event graph、附魔/词条实体、
所有嵌套选择动作和 A8 全矩阵仍需要独立测试。

因此可以结论为“本轮新增搜索不再产生新的独立根因”，不能声称整个模拟器已经没有
问题。下一步应先修 P1 数据模型和初始化契约，再重跑本项目全部探针与 345 条规则回归。

## 可复现命令

```powershell
Set-Location 'D:\sts2_datacollection\sts2'

& '.\.scratch\deep-audit-round8-20261029\round10_findings.exe'
& '.\.scratch\deep-audit-round8-20261029\round10_potion_pool.exe'
& '.\.scratch\deep-audit-round8-20261029\round8_findings.exe'
& '.\.scratch\deep-audit-round8-20261029\round9_findings.exe'

& '.\.venv\Scripts\cmake.exe' --build 'simulator\build-mingw' --target sts2_rules_test -j 2
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```
