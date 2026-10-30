# STS2 高速模拟器第十二轮累计深度审计

日期：2026-10-29

## 结论

当前模拟器已经具备吞吐型 rollout 的基本工程能力，但还不能作为“与参考客户端等价”的高保真训练环境。

本轮继续执行了生产树构建、隔离快照重建、5,000 局随机整局压力测试、865,536 次分支克隆、现有累计探针、C# 静态交叉检查、Python 绑定输入测试和 schema 一致性检查。结果分为两部分：

- 工程稳定性较好：5,000 局、324,827 步随机整局没有新的状态不变量、合法动作失败、空动作状态或驱动错误；规则回归为 355/355。
- 规则正确性仍有系统性缺口：新确认 17 个实例化 Power 没有独立状态、Python 参数可截断别名成合法动作、生产 `.pyd` 与当前源码不一致；旧的种子、随机、进阶、怪物、奖励、遗物、事件、商店和观察问题继续复现。

因此当前版本可以用于速度、搜索和训练管线开发，但用它训练“拟真 STS2 策略”仍会引入大量错误标签。

本报告没有修改生产源码。生产树不可直接构建时，所有 C++ 动态探针均使用隔离快照：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\simulator_snapshot`

快照相对生产源码只补了 `simulator/src/monsters.cpp` 缺失的
`#include "sts2/relics.h"`，其余核心源码哈希一致。

## 路径与测试对象

- 项目：`D:\sts2_datacollection\sts2`
- STS1 参考：`D:\sts2_datacollection\sts1`
- STS2 C# 反编译：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- Python 参考：`D:\project\sts2_compactformer\sts2-rl-agent\sts2_env`
- 探针目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029`
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`
- 正式规则测试：`D:\sts2_datacollection\sts2\simulator\tests\rules_regression.cpp`
- Python 测试：`D:\sts2_datacollection\sts2\tests`
- 上一轮综合报告：`D:\sts2_datacollection\sts2\docs\simulator-deep-audit-round8-2026-10-29.md`

## 工程基线

| 检查 | 结果 |
|---|---:|
| 生产 `sts2_sim` / `sts2_rules_test` 重建 | 失败 |
| 隔离快照规则测试 | 355 / 355 PASS |
| 生产扩展直接运行 Python 测试 | 81 passed, 2 failed, 1 skipped |
| 隔离快照扩展运行 Python 测试 | 82 passed, 2 failed |
| 5,000 seed 随机整局 | 0 finding |
| 随机整局步数 | 324,827 |
| 分支克隆比较 | 865,536 |
| 地图结构 fuzz | 3,000 + 3,000，0 failure |
| benchmark run 1000 | 72.9 runs/s，win_rate 0，avg_floor 10.9 |

生产构建当前失败点：

```text
simulator/src/monsters.cpp:533
error: 'relics_monster_died' was not declared in this scope
```

源码和隔离快照的 `monsters.cpp` 都有该调用，但生产文件缺少：

```cpp
#include "sts2/relics.h"
```

这是 P0 构建阻断。当前生产 `.pyd` 时间为 `2026-10-29 05:45:42`，而 `battle.cpp` 为 `07:06:32`、`monsters.cpp` 为 `07:14:52`，绿色 Python 测试运行的是旧二进制，不能证明当前 C++ 源码可构建。

两个 Python 失败仍是固定 seed 273/443 的必胜断言：

- `test_full_run_completes_and_wins`
- `test_jsonl_trajectory_and_batch`

这些断言已不能维护。应改为可验证的终止、资源边界、动作合法性和 schema 性质，或重新选择并解释测试 seed。

## 本轮新增高优先级问题

### P0：快照恢复仍是 header-only memcpy

`RunContext::restore()` 只检查 magic、version、size，然后把整块状态 `memcpy` 到对象，不校验任何 enum、计数、HP、gold、牌堆/药水/遗物索引、pending choice 或 battle 状态。

`round14_snapshot_matrix.py` 当前结果：

```text
fields=139 cases=311 accepted=301 rejected=0 crashes=9 timeouts=1
```

典型崩溃输入：

- `deckCount=INT_MAX`
- `potionCount=INT_MAX`
- `relicCount=INT_MAX`
- `battleDrawCount=INT_MAX`
- `battleDiscardCount=INT_MAX`
- `battleExhaustCount=INT_MAX`
- `battlePotionCount=INT_MAX`
- `battleRelicCount=INT_MAX`
- `pendingCount=INT_MAX`

`offeredCount=INT_MAX` 超时。另有 `seed=-1`、负 HP、负 gold、非法 card id、负 map count 等 301 个非法快照被接受并可继续 observation/action。

快照是训练服务的输入边界，这不仅是测试健壮性问题，也是可导致进程崩溃和越界读取的 P0。

探针：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round14_snapshot_matrix.py`

### P1：Python 绑定把越界参数截断成合法动作

`simulator/bindings/bindings.cpp::make_action()` 直接执行：

```cpp
a.hand = static_cast<std::uint8_t>(hand);
a.target = static_cast<std::uint8_t>(target);
a.uid = static_cast<std::uint16_t>(uid);
```

因此传入越界值会回绕，而不是报错。实测合法动作 `(PLAY_CARD, hand=0, target=0, uid=0)` 被改写成：

```text
(PLAY_CARD, hand=256, target=256, uid=65536)
```

当前结果：

```text
action_features_alias=1 expected=0
invalid_action_accepted=1 expected=0
```

`BattleContext.step`、`RunContext.step_combat`、`action_features` 和
`combat_action_features` 都受同一问题影响。外部策略服务、JSON API 或错误模型输出可绕过动作校验并执行另一张牌。

探针：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round16_binding_aliasing.py`

结果：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round16-binding-aliasing-results.txt`

### P1：生产扩展、源码、快照和 README 的 schema 不一致

当前实测：

| 对象 | PUBLIC_OBS_DIM | PUBLIC_COMBAT_OBS_DIM | obs/action version |
|---|---:|---:|---:|
| 生产 `.pyd` | 17815 | 10378 | 7 / 6 |
| 当前源码/隔离快照 | 17835 | 10398 | 7 / 6 |
| README | 17805 | 10368 | 7 / 6 |

schema 向量的维度已经改变，但版本仍是 7。参数 shape 校验最终能拒绝错误 shape 的 checkpoint，但版本元数据没有表达 layout 变化，文档和测试也不会发现该差异。当前测试仅断言版本 `>=`，没有锁定精确值或维度。

探针：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round16_build_schema_contract.py`

结果：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round16-build-schema-results.txt`

### P1：实例化 Power 没有每实例状态

C# 中共有 19 个 `IsInstanced => true`：

```text
Automation, Covered, Flanking, Grapple, Guarded, Heist, Knockdown,
MagicBomb, Monologue, Nightmare, Orbit, Panache, RollingBoulder,
Sandpit, Swipe, TagTeam, TheBomb, Thievery, ToricToughness
```

当前 C++ 只有 Automation 和 The Bomb 有专用实例数组；其余 17 个仍使用 scalar/slot 合并。可执行反例：

| 检查 | 参考 | 当前 |
|---|---:|---:|
| 两个 Rolling Boulder 两回合总伤害 | 30 | 25 |
| 九个 Automation 抽满 10 张后的总能量 | 9 | 8 |
| Covered 下 10 点 powered attack 伤害 | 0 | 10 |
| 两个 Grapple 对 Intangible 目标的总伤害 | 2 | 1 |

Automation 还存在硬上限 8；C# 没有规则上限。The Bomb 的 `MAX_PILE=160` 也是存储上限，注释声称“无规则上限”，模型层尚未真正表达。

探针与结果：

- `round16_power_instances.cpp`
- `round16-power-instances-results.txt`
- `round16_power_instance_audit.py`

### P1：双牌、Toric、Stomp、Luminesce 仍错误

`round16_card_contracts.cpp` 当前结果：

```text
toric_toughness_restores_cleared_block expected=5 actual=0
dual_wield_starts_filtered_hand_choice expected=1 actual=0
stomp_in_hand_discounts_after_two_attacks expected=1 actual=3
luminesce_grants_five_energy expected=5 actual=3
```

正向对照通过：

- Clash 在混合手牌时不可打；
- Pacts End 在消耗不足时不可打；
- Dramatic Entrance 的 11 伤害和 Exhaust；
- Ultimate Defend 的 11 格挡；
- Ultimate Strike 的 14 伤害；
- Luminesce 自身会 Exhaust。

结果文件：

`D:\sts2_datacollection\sts2\.scratch\deep-audit-round8-20261029\round16-card-contracts-results.txt`

## 仍复现的系统性规则问题

### 种子和随机语义

- 整数 master seed 没有按 C# 字符串 seed 的 deterministic hash 派生。
- seed 123 的 C# run RNG seed 为 1816791482，当前首个 `UP_FRONT` 样本、初始地图均不同。
- 共享事件 RNG 无条件加入 player id；2,000/2,000 样本不一致。
- 多页事件每页重建 `event_rng()`，counter 不延续。
- event bag 未在抽取前应用 `event_allowed_now()`。
- Wongo 在无金币、StoneOfAllTime 在无药水、Unrest 在满血时仍进入候选池。
- encounter weak/normal/elite bag 不是 GrabBag 语义；act 1 有 310、act 2/3 各 500 个额外 weak 样本，normal 重复 500/500。

探针：

- `round14_seed_derivation.exe`
- `round14_event_rng.exe`
- `round15_event_contracts.exe`
- `round11_encounter_bag_audit.exe`

### 进阶 A0–A10

`round14_ascension_runtime.exe` 中 A0–A10 的初始结果完全相同：

```text
gold=99 slots=3 deck=10 bane=0 elites=5 axe_one_two=5
```

缺失：

- A1 精英数量；
- A2 Ancient 回复；
- A3 初始金币；
- A4 药水槽；
- A5 Ascender's Bane；
- A6 休息节点数量；
- A7 奖励赔率/升级率；
- A9 敌人伤害；
- A10 双 Boss。

A0/A7 的 300 次卡奖励 hash 完全相同，A7 没有效果。A9 的多个 runtime 伤害仍使用 A0 表。

### 怪物 AI、初始化和 Power

- 67 个 weighted random 分支中 66 个字段不一致，65 个 weight/cooldown 写反。
- AXEBOT 500/500 只选 `ONE_TWO`。
- 13 个正常怪物初始 Power 和 5 个动态 Power 仍缺规则：HighVoltage、Ravenous、Shriek、Skittish、Hatch、Plow、Soar、Flutter、Burrowed、SteamEruption 等。
- Illusion 的致命伤害不进入 revive；Surprise 死亡不召唤；ToughEgg 不孵化。
- GremlinMerc 不偷金币。
- PaperCuts 最大生命损失不触发 SelfFormingClay。
- ThievingHopper 不删除被偷牌。
- Doormaker/Door 二次复活最大生命仍为 215，参考为 195。
- Rocket/Crusher BackAttack 仍是 1.0 倍，参考为 1.5 倍。
- Noisebot/Insatiable 随机插牌被错误标成已知牌顶。
- TheInsatiable Sandpit 最终不杀玩家。
- BeltBuckle 在药水数量变化时的激活/停用错误。

### 奖励、商店和遗物

- Boss 战后没有 Boss relic choice。
- 精英遗物自动入袋，没有选择阶段。
- 药水奖励自动入袋。
- BowlerHat 只影响战斗金币，不影响全部金币获得。
- 100,000 个商店中 1,428 个商店出现重复遗物；首例 seed 56。
- 商店 3 个遗物槽独立有放回抽取。
- relic pool 没有完整 `IsAllowed()` 楼层门控；20,000 次中 2,385 次抽到禁用遗物。
- BloodSoakedRose 不加 Enthralled。
- PumpkinCandle 跨章节永久给能量。
- GoldenCompass 不重生成 Golden Path 地图。
- BlackStar 不给第二份精英遗物，LavaRock 不给两个 act 1 Boss relic，DreamCatcher 不加入休息卡奖励。
- GlassEye、SeaGlass、Claws 仍错误。
- 静态检查中 15 个普通遗物没有非 event 运行引用；74 个有实际 `AfterObtained` 的遗物里仍有大量 event/Ancient 近似。

### 药水与事件路径

`round12_potion_paths.exe` 仍失败：

```text
cauldron_waits_for_five_choices_ooc_count expected=0 actual=405
lost_coffer_waits_for_rewards_deck expected=0 actual=500
lost_coffer_waits_for_rewards_potion expected=0 actual=500
alchemical_coffer_duplicate_sets expected=0 actual=58
delicate_frond_fills_belt expected=0 actual=237
```

事件仍有：

- Wongo Ticket 多次发奖；
- Lucky Fysh、BookOfFiveRings 不在统一加牌 hook 上；
- Aroma 可变换出 Status/Curse；
- 事件卡、附魔、bundle、nested choice 大量以升级/简化选择代替；
- 容量满时仍返回成功并扣资源/静默丢弃。

### 卡牌和遗物 hook

已确认仍复现：

- Guilty 五场战斗后不删除；
- Enthralled 不阻止手中其他牌；
- Luminesce 给 3 能量，应为 5/6；
- DualWield 完全不开始选择；
- MadScience 没有类型/rider 数据模型；
- ToricToughness 不恢复已清空格挡；
- Stomp 已在手时不动态降费；
- event/relic add-card 绕过统一 hook；
- 15 个共享普通遗物未列入 `relic_implemented()`；静态交叉检查仍发现 EVENT/Ancient 遗物存在 `relics.cpp` 外行为或 `AfterObtained` 映射缺口。

### 公开观察

`round11_observation_collisions.exe` 仍为 21/21 FAIL。观察向量无法区分：

- Toric Toughness 待恢复格挡；
- Surrounded、本回合未格挡伤害、本战斗未格挡攻击伤害；
- monster offBalance/stunned/slow/tempStrengthLoss/nemesis/combatEndBlocker；
- card bonusDamage/etherealThisCombat/retainThisCombat；
- active play replay 进度；
- rewardIsBoss、TeaSet、MawBank、SilverCrucible、nextCombatDazed/Energy；
- 当前 skillsLocked 状态与其动作变化。

`round15_observation_contracts.cpp` 进一步确认：

- public run deck 不保留具体卡实例升级身份；
- 已知牌顶顺序不可观察；
- 可见卡 `bonusDamage` 不编码；
- 战斗内实际 `battle.gold` 不进入 public run observation。

隐藏 draw/discard 顺序未泄漏，这是正确对照。

## 有效但需要修正的探针

`round11_a8_intent_audit.py` 的文件名和输出标签有误导性。它实际比较的是 A9
`DeadlyEnemies` 伤害与 JSON，却把列名称为 `expected_A8`。A8 在设计上只对应
`ToughEnemies` HP；A9 才对应 `DeadlyEnemies` 伤害。不要把该脚本的 181/182
失败直接当作 A8 数据错误，但它仍说明 A9 伤害表覆盖需重写并重命名。

## 正向结果

- 5,000 局随机整局、324,827 步、865,536 次分支克隆均无不变量失败。
- 地图结构 fuzz 3,000 + 3,000 次无失败。
- 正式规则测试在隔离快照中为 355/355 PASS。
- 548 次卡牌和 208 次药水“可执行/选择不悬挂”矩阵为 0 failure。
- `round10_findings.exe` 的 21 项工厂、初始化和战斗卡池回归全部 PASS。
- 相同 seed 在三种不同预填充内存下生成完全相同的 31,780-byte snapshot。
- 合法终止、动作合法性和 UID 唯一性在 5,000 局长跑中稳定。
- 当前吞吐约 72.9 runs/s，约 1.7 us/step，基础性能可用于大规模 rollout。

这些正向结果说明“工程骨架稳定”，不能抵消上面的语义误差。

## 建议修复顺序

1. 补齐 `monsters.cpp` 的 `relics.h` include，恢复生产全量构建，并强制用当前源码重建 `.pyd`。
2. 给 `restore()` 增加逐字段验证、索引/计数边界、enum 白名单、pending/battle 一致性校验和可选 checksum；非法快照必须原子拒绝。
3. 在 Python binding 转换前验证 `hand/target/uid/type` 原始整数范围；禁止静默回绕。
4. 提升 schema version，修正 README；测试锁定精确维度、版本和二进制新鲜度。
5. 修复 master seed 派生、共享 event RNG、GrabBag 和 A0–A10。
6. 把 19 个实例化 Power 改为每实例对象或显式实例数组，优先 RollingBoulder、Automation、Panache、Grapple、Covered、ToricToughness。
7. 统一 reward/shop/relic/event/add-card/change-pile hook，消除自动入袋和重复抽取。
8. 扩展 observation 到已经影响动作或未来的可见状态，并同步 bump checkpoint schema。
9. 最后补真实客户端逐步 replay 差分。

## 可复现命令

```powershell
Set-Location 'D:\sts2_datacollection\sts2'

& '.\.venv\Scripts\cmake.exe' --build 'simulator\build-mingw' `
  --target sts2_sim sts2_rules_test

.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe .scratch\deep-audit-round8-20261029\run_tests_snapshot.py

& '.\.scratch\deep-audit-round8-20261029\round16_power_instances.exe'
& '.\.scratch\deep-audit-round8-20261029\round16_card_contracts.exe'
.\.venv\Scripts\python.exe .scratch\deep-audit-round8-20261029\round16_binding_aliasing.py
.\.venv\Scripts\python.exe .scratch\deep-audit-round8-20261029\round16_build_schema_contract.py
.\.venv\Scripts\python.exe .scratch\deep-audit-round8-20261029\round14_snapshot_matrix.py

& '.\.scratch\deep-audit-round8-20261029\round14_seed_derivation.exe'
& '.\.scratch\deep-audit-round8-20261029\round14_ascension_runtime.exe'
& '.\.scratch\deep-audit-round8-20261029\round15_event_contracts.exe'
& '.\.scratch\deep-audit-round8-20261029\round15_relic_contracts.exe'
& '.\.scratch\deep-audit-round8-20261029\round15_reward_contracts.exe'
& '.\.scratch\deep-audit-round8-20261029\round13_monster_ai.exe'
& '.\.scratch\deep-audit-round8-20261029\round11_observation_collisions.exe'

& '.\.scratch\deep-audit-round8-20261029\round16_5000_invariants.exe'
```

## 覆盖边界

“当前没有新增探针再产生新的工程性根因”不等于“绝对没有未知规则差异”。以下仍未被完整证明：

- 没有真实客户端逐步 replay 差分；
- 没有覆盖多人缩放和多玩家目标选择；
- 没有覆盖所有账号解锁状态下的 Underdocks 替换语义；
- 没有穷举全部遗物组合、事件图、附魔和 bundle/nested choice；
- 没有完整 ASan/UBSan；本机工具链缺少 `libubsan`，本轮只能使用 C++ 不变量、`-ftrapv`、地图 fuzz、畸形快照和边界矩阵；
- 没有证明数值、奖励和 AI 与当前游戏补丁逐 seed 等价。

在这些条件下，工程稳定性测试已出现边际收敛，但规则等价测试没有收敛；应先修上面的 P0/P1，再用同一批探针做回归。
