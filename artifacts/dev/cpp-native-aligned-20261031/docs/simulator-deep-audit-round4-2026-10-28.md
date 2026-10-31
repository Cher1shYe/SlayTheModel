# 高速模拟器第四轮独立审计（2026-10-28）

## 结论

当前第二、三轮修复确实能通过旧用例，但仍有规则错误。用当前工作区源码重新编译后，新增 30 项定向断言中 23 项失败、7 项通过；失败归并为下面 13 组问题/残余缺口。**23 不是独立 bug 数，也不是随机对局错误率；13 组也并非全部首次发现**：其中包含旧修复覆盖不完整，以及已明确记录的观察截断限制。

本轮只增加审计探针、结果和本报告，未修复生产代码。重点检查组合规则、嵌套出牌、事件粒度、跨回合状态以及观察可辨识性。预期值依据本地 C# 参考实现推导，尚未进行真实游戏客户端逐步差分。

## 路径和版本

- 项目：`D:\sts2_datacollection\sts2`
- HEAD：`a57a7029b69a85aee13bf38d41efa9597672fad6`；测试对象包含当前大量未提交修复，不能仅用 HEAD 复现。
- 权威规则参考根目录：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- 上一份修复声明：`D:\sts2_datacollection\sts2\docs\simulator-audit-round2-round3-fixes-2026-10-28.md`
- 本轮目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round4-20261028`
- 新探针：上述目录 `probe.cpp`；完整断言结果：`probe-results.txt`。
- 压测：上述目录 `matrix.cpp`、`matrix-results.txt`。
- 重新编译和复现脚本：上述目录 `reproduce.ps1`。
- 源码 SHA256：上述目录 `source-hashes.json`。审计结束复核，记录的源文件无变化。
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`

后文 C# 路径均相对此参考根目录；C++ 路径均相对此项目根目录。

## 验证结果与解释

| 检查 | 结果 |
|---|---:|
| 当前原生 rules_regression，新编译 | 153 / 153 通过 |
| 第二轮原始 probe，新编译 | 32 / 32 通过 |
| 第三轮原始 probe，新编译 | 41 / 41 通过 |
| 第四轮新 probe，新编译 | 30 项：23 失败，7 通过 |
| 全卡对组合，新种子 | 43,056 场，818,425 步，0 failure，0 capped |
| 遗物/药水矩阵，新种子 | 12,532 场，309,059 步，0 failure，0 capped |
| `.venv\Scripts\python.exe -m pytest tests -q` | 84 passed，12.35 秒 |

矩阵共 55,588 场、1,127,484 步，使用从第三轮复制后更换的种子起点 51001 / 61001。矩阵主要检测状态不变量及运行异常，**没有逐步 C# 语义 oracle**，所以不能以矩阵全绿反证下面的规则错误。

原生引擎重新以 `-O1 -fsanitize=bounds -fno-sanitize-recover=bounds` 编译独立对象，不使用旧对象；链接第三轮的自定义 bounds handler（工具链缺少标准 libubsan），未触发越界 handler。它不是完整 ASan/UBSan 检查；测试驱动自身未插桩。五份 stderr 文件均为空。

Python 测试使用当前已有 Python 扩展；本轮没有重新构建该扩展，其结果不能替代新编译 C++ 的证据。另曾执行无目录约束的 `pytest -q`，因误收集 vendored `simulator/pybind11/tests`，缺少 `pybind11_tests` 而中止；限定项目 `tests` 后全部通过。这是测试发现范围问题，不计入以下 13 组规则问题。

探针采用受控战斗状态（固定 seed 1234、Ceremonial Beast、较高生命/能量以隔离目标机制），部分通过直接设置 Power/计数器构造前置条件，部分实际出牌/喝药。属于最小规则单元复现，不代表已经取得对应完整爬塔轨迹。

## R4-01：Fiend Fire 消耗了触发抽牌后才进入手牌的卡（高）

- 前置：Dark Embrace 1；手牌 Fiend Fire + 2 张 Defend；抽牌堆 10 张 Strike。
- 预期：只消耗最初两张手牌和 Fiend Fire 自身，共 3 张；留下触发抽出的 3 张。
- 实测：消耗堆 13 张，手牌 0 张。额外抽来的牌不断进入 `while(handCount > 0)` 的消耗循环。
- 实现：`simulator/src/cards_ironclad.cpp:402`。
- 参考：`MegaCrit.Sts2.Core.Models.Cards\FiendFire.cs` 的 `OnPlay` 先 `Hand.Cards.ToList()` 拍快照，再消耗快照中的牌。
- 断言：`fiend_fire_only_initial_hand_exhausted`（3→13）、`fiend_fire_dark_embrace_retains_drawn`（3→0）。无 Dark Embrace 的对照通过。

## R4-02：Fiend Fire 多段攻击只首段吃 Vigor（高，旧多段修复不完整）

- 前置：Vigor 5，Fiend Fire 消耗两张卡。
- 预期 `(7+5)*2=24`；实测 `12+7=19`。
- 实现：`simulator/src/cards_ironclad.cpp:402` 循环单次 hit，攻击命令边界错误。
- 参考：`MegaCrit.Sts2.Core.Models.Cards\FiendFire.cs` 使用一个攻击命令的 `WithHitCount(cardCount)`；`MegaCrit.Sts2.Core.Models.Powers\VigorPower.cs` 按攻击命令消费。
- 断言：`fiend_fire_vigor_all_hits`。

## R4-03：Nostalgia 覆盖消耗、忽略层数，并错误归属嵌套出牌（高）

- Nostalgia 1 + Impervious：应消耗，消耗堆实测 0（预期 1）。
- Nostalgia 2 + 连续两张 Strike：应回顶两张，实际只有一张。
- Nostalgia 1 + Havoc 自动打出牌顶 Strike：应 Havoc 回顶、Strike 强制消耗；实际 Strike 未消耗且回顶，抢占外层卡效果。
- 实现：`simulator/src/battle.cpp:1573` 的回顶分支优先于消耗；`:1612` 仅使用布尔首牌标记；全局 `nostalgiaPending` 不能表达嵌套归属。
- 参考：`MegaCrit.Sts2.Core.Models.Powers\NostalgiaPower.cs` 仅修改原结果为 Discard 的卡，并比较 CardPlaysStarted 数量和 Amount；`MegaCrit.Sts2.Core.Models\CardModel.cs` 在执行卡牌效果前确定结果牌堆。`MegaCrit.Sts2.Core.Models.Cards\Havoc.cs` 对子卡设置 forceExhaust。
- 断言：`nostalgia_does_not_override_exhaust`、`nostalgia_two_stacks_two_cards`、`nostalgia_havoc_child_still_exhausts`、`nostalgia_returns_outer_first_card`。单层普通 Strike 对照通过。

## R4-04：Thrumming Hatchet 暂时离开正常牌堆，返回时保留过期临时费用（高）

- 普通打出后应在弃牌堆等待下回合召回，实际弃牌堆 0，只有内部返回队列。
- 本回合临时改为 0 费后打出，下回合应恢复 1 费，实际仍 0 费。
- 实现：`simulator/src/cards_colorless.cpp:282`、`simulator/src/battle.cpp:1562`；返回分支提前退出，且新回合费用恢复发生在队列回手之前。
- 参考：`MegaCrit.Sts2.Core.Models.Cards\ThrummingHatchet.cs` 的 OnPlay 只攻击，按正常流程进牌堆；BeforeHandDraw 根据上回合历史召回实际卡对象。
- 断言：`hatchet_available_in_discard_before_return`（1→0）、`hatchet_temporary_cost_restored_on_return`（1→0）。
- 影响：改变弃牌互动和费用；本轮仅动态验证这张返回卡，不把所有返回卡一概判错。

## R4-05：Hidden Gem 的持久 replay 被跨回合清空（高）

- 实际打出 Hidden Gem 给抽牌堆中的 Strike 增加 2 次 replay，再抽出并用 Runic Pyramid 留到下一回合。
- 预期 replay 仍为 2；实测 0。
- 实现：`simulator/src/battle.cpp:295` 每回合清除手牌 replay。
- 参考：`MegaCrit.Sts2.Core.Models.Cards\HiddenGem.cs` 修改 `BaseReplayCount`，不是本回合临时效果。
- 断言：`hidden_gem_replay_survives_retention`。

## R4-06：格挡倍率顺序、Unmovable 层数和 Vambrace 首卡范围错误（高）

- Dexterity 3 + Unmovable 1 + Defend：预期 `(5+3)*2=16`，实测 `5*2+3=13`。
- Unmovable 2 连续打出两张 Defend：预期 20 格挡，实测 15。
- Vambrace + Second Wind 消耗两张 Defend：首张产格挡卡的两次 5 格挡都应翻倍，总计 20；实测 15，只首次 gain_block 翻倍。
- 实现：`simulator/src/battle.cpp:886` 和格挡加法顺序；`simulator/src/relics.cpp:614` 首次获得格挡即消耗遗物标记。
- 参考：`MegaCrit.Sts2.Core.Hooks\Hook.cs` 先 ModifyBlockAdditive 后 ModifyBlockMultiplicative；`MegaCrit.Sts2.Core.Models.Powers\UnmovablePower.cs` 使用 Amount 和 CardPlay 历史；`MegaCrit.Sts2.Core.Models.Relics\Vambrace.cs` 在触发卡的 AfterCardPlayed 才结束效果。
- 断言：`unmovable_doubles_dexterity`、`unmovable_two_stacks`、`vambrace_entire_first_card`。无敏捷、单次 Unmovable 对照通过。

## R4-07：Flex Potion 漏触发 Ruined Helmet；上一份修复报告对此规则判断错误（高）

- Ruined Helmet 尚未使用时喝 Flex Potion：预期力量 10，回合结束扣去临时 5 后剩 5；实测 5，结束剩 0。
- 实现：临时力量直接修改数值，绕过 StrengthPower 收到力量的钩子。
- 参考链：`MegaCrit.Sts2.Core.Models.Powers\FlexPotionPower.cs` → `TemporaryStrengthPower.cs` 的 BeforeApplied → `PowerCmd.Apply<StrengthPower>(..., silent:true)` → `MegaCrit.Sts2.Core.Models.Relics\RuinedHelmet.cs`。
- 上份报告以“FlexPotionPower 不是 StrengthPower”为由排除此交互，遗漏了内部施加 StrengthPower 的调用。silent 是显示参数，不能据此跳过规则修正。
- 断言：`flex_strength_triggers_ruined_helmet`（10→5）、`flex_helmet_extra_strength_persists`（5→0）。普通 Strength Potion 触发 Helmet 的对照通过。

## R4-08：自动打出的 X 费牌未应用 Chemical X（高）

- 能量 3，Chemical X，自动打出未升级 Whirlwind：预期 5 次、25 伤害，实测 3 次、15。
- 实现：`simulator/src/battle.cpp:1468` 只在手动路径补 +2；`:1623` 自动路径缺失。
- 参考：`MegaCrit.Sts2.Core.Models.Relics\ChemicalX.cs` 的 ModifyXValue 不排除自动出牌；`MegaCrit.Sts2.Core.Models\CardModel.cs` 的 X 值解析。
- 断言：`chemical_x_applies_to_auto_x`；手动 Whirlwind 对照 25 通过。

## R4-09：Hand of Greed 绕过 Pen Nib 伤害修正（高，旧修复覆盖不完整）

- Pen Nib 计数为 9，打出 Hand of Greed：应 40 伤害，实测 20。
- 实现：`simulator/src/cards_colorless.cpp:359` 走 `attack_monster`，绕过带卡牌来源的遗物修正路径。
- 参考：`MegaCrit.Sts2.Core.Models.Cards\HandOfGreed.cs` 使用 FromCard；`MegaCrit.Sts2.Core.Models.Relics\PenNib.cs` 对相应攻击施加倍率。
- 断言：`pen_nib_colorless_hand_of_greed`。不能以铁卫/AOE 路径已修复推断无色卡路径正确。

## R4-10：The Gambit 把自伤算作攻击，并延迟死亡（高）

- The Gambit 生效后 Bloodletting 自伤，再完全格挡敌方伤害：应存活，实际回合结算死亡。
- The Gambit 生效后收到敌方 1 点未格挡攻击：应立即死亡，实际 outcome 仍为 UNDECIDED（0），预期 PLAYER_LOSS（2）。
- 实现：`simulator/src/battle.cpp:927` 普通 damage_player 也设置攻击伤害标记；`:450` 到敌方回合结束才杀死。
- 参考：`MegaCrit.Sts2.Core.Models.Powers\TheGambitPower.cs` 的 AfterDamageReceived 明确要求 `Props.IsPoweredAttack()` 且 UnblockedDamage > 0，然后立即移除能力、Kill。
- 断言：`gambit_not_triggered_by_self_damage`、`gambit_kills_immediately`。

## R4-11：第 9 个 Bomb 和第 9 张之后已知牌顶仍存在观察混叠（中，已知限制的新增实证）

- 两状态前 8 个 Bomb 一致、第 9 个倒计时分别为 3 和 1：公共观察完全相同；结束回合后怪物生命相差 40。
- 已知牌顶 10 张，交换第 9、10 张的不同身份：公共观察相同，丢失本应已知的顺序。
- 实现：`simulator/include/sts2/observe.h:42`，`PUB_KNOWN_TOP=8`、`PUB_BOMB_SLOTS=8`。
- 断言：`ninth_bomb_observable`、`ninth_tenth_known_top_order_observable` 失败；`ninth_bomb_changes_transition` 通过，证明被隐藏差异确实影响转移。
- 上份修复报告已经披露槽位上限。本轮不将其包装成全新 bug；若接受部分可观测训练，应明确此设计限制，不能宣称观察完整表达全部公开状态。

## R4-12：自动出牌绕过 Velvet Choker 六张限制（高）

- Choker 在场，cardsPlayedThisTurn=6，自动打出 Strike：应不执行攻击，实际造成 6 伤害。
- 实现：`simulator/src/battle.cpp:1623` 自动路径未执行与手动相符的出牌限制钩子。
- 参考：`MegaCrit.Sts2.Core.Commands\CardCmd.cs` 的 AutoPlay 在执行前调用 Hook.ShouldPlay；`MegaCrit.Sts2.Core.Models.Relics\VelvetChoker.cs` 的 ShouldPlay 接受 AutoPlayType，未豁免自动出牌。
- 断言：`auto_play_respects_choker_limit`；相同前置下手动出牌被拒绝的对照通过。

## R4-13：Strike Dummy 加法发生在 Weak 乘法之后（高）

- Strike 6 + Strike Dummy 3 + Weak：预期 `floor((6+3)*0.75)=6`；实际 `floor(6*0.75)+3=7`。
- 实现：`simulator/src/relics.cpp:557` 的 +3 在基础伤害计算/Weak 之后。
- 参考：`MegaCrit.Sts2.Core.Models.Relics\StrikeDummy.cs` 使用 ModifyDamageAdditive；`MegaCrit.Sts2.Core.Hooks\Hook.cs` 的伤害修正阶段。
- 断言：`strike_dummy_add_before_weak`。本轮只对 Strike Dummy 动态确认，不把其他加法遗物直接计为已复现问题。

## 复现与后续修复验收

PowerShell 执行：

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round4-20261028\reproduce.ps1'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

脚本依赖第二、三轮原探针，以及第三轮 `bounds_handler.cpp`，均位于项目 `.scratch` 对应目录。`.scratch` 通常被 Git 忽略，跨机器交接需一并复制。原生诊断探针的进程退出码可能为 0，即使断言失败；必须读取 `FAIL` 和 `SUMMARY failures=`，不能只看退出码。

修复优先级建议：先修消耗/牌堆目的地、自动出牌限制、死亡时机等改变合法轨迹的问题；再统一攻击/格挡修正的事件边界和运算顺序；随后处理跨回合持久属性和费用；最后明确观察上限策略。应把这些最小复现纳入正式回归，保留通过对照，不能只继续增加无规则 oracle 的随机场次。

本报告确认的是所列受控状态下的偏差；未据此断言其他所有卡、遗物、怪物或完整爬塔流程都已审计完毕。
