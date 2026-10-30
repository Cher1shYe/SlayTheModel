# 高速模拟器深度测试报告（仅报告，未修复）

基线：`a57a702`。工作目录：`D:\sts2_datacollection\sts2`。

本轮没有修改模拟器、训练器、生成表或现有测试。只新增本报告和 `.scratch/deep-audit-20261028/` 下的独立审计程序、输出及源文件哈希。`git diff --exit-code` 为 0。上轮未跟踪的 followup 报告保留原状。

## 结论与证据边界

**整局运行和状态复制比较稳定，但基础规则仍有多类错误，其中一处已捕获到数组越界写。现有 78 项测试不足以验收模拟器正确性。**

本报告合并列出 **20 类已运行复现的核心问题（D01–D20）**，另列已知评估问题、可达性未确认的内部状态问题和指标问题。多项断言可以属于同一个问题，不把失败断言数冒充独立 bug 数。

规则预期主要来自本地反编译代码：

`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`

下文的 C# 相对路径均相对于该目录。证据是“C# 规则阅读＋当前 C++ 运行结果”，**不是实际游戏客户端差分执行**。定向检查使用可控状态隔离结算，包括设置牌堆、HP、状态、遗物计数等；不是声称每个状态都已通过完整爬塔轨迹采集。对于尚未证实当前 A0 内容可达的 Intangible，单独列为 D22，不算入 20 类核心问题。

## 实际执行范围

| 检查 | 结果 | 能证明什么 |
| --- | --- | --- |
| 现有 pytest | 78 passed，12.26s | 当前已有回归全部通过 |
| 独立定向语义程序 | 36 项检查，32 项失败、4 项通过 | 针对疑点构造的检查；不是全内容错误率 |
| 按卡牌扫描 | 208 个非多人卡 ID × 5 seeds＝1040 场 | 混合基础牌组，含升级版本，检查合法动作、克隆转移、牌堆边界、UID 唯一等 |
| 按遭遇扫描 | 89 个生成遭遇 × 10 seeds＝890 场 | 包括数据表中的合同外遭遇，仅做引擎不变量检查 |
| 上述两种战斗扫描合计 | 1930 场、106067 步，0 不变量失败、0 步数截断 | 并不验证每张卡、每个怪物的语义正确 |
| 整局压力测试 | seeds 40000000–40000999，共1000局、250029步 | 约四分之一使用随机合法策略，其余使用现有启发式 |
| 快照恢复与重复动作 | 7248 次，0 分歧 | 当前构建内确定性与恢复自洽 |
| 整局终止 | 0 非法动作拒绝、0 无动作死锁、0 截断 | 这些已测策略和种子上的流程稳定性 |
| Beat Down 边界检测 | 捕获 index=10 越过 int[10] | 确认越界访问，定位 cards_colorless.cpp:314 |

整局混合策略的 72 胜不作为模型成绩，也不与其他种子/策略的胜率比较。

## D01 — 高优先级：Beat Down 在大弃牌堆中越界写数组

- 位置：`simulator/src/cards_colorless.cpp:311–314`。
- `picks` 只有 `MAX_HAND=10` 个元素，却遍历整个弃牌堆，把每张可打出的攻击牌下标写入 `picks[n++]`，没有上界检查。
- 复现：弃牌堆放 20 张 Strike，手牌 Beat Down，3 能量。该动作合法。以 GCC bounds instrumentation 重新编译原始 `cards_colorless.cpp`，其余链接现有引擎对象，捕获：`BOUNDS_FAILURE ... line=314 index=10`。
- 自定义检测处理器在写越界前退出，退出码 77；没有修改该源文件。这里证明的是越界访问，不冒称已观察到生产版本必然崩溃。生产版本存在栈破坏、错误结果或崩溃风险。

## D02 — 高优先级：临时力量/敏捷重复加成，并错误恢复

- 位置：`potions.cpp:161/177`，`battle.cpp:557/684/339`，`cards_ironclad.cpp:136`。
- Flex Potion 同时增加 strength 和 tempStrength；伤害公式又把两者相加。普通 Strike 应 `6+5=11`，实际 **16**。
- Speed Potion 同理，Defend 应 `5+5=10` 格挡，实际 **15**。
- Setup Strike 只增加 tempStrength，但回合结束从 strength 扣除它。起始力量 0，打出后到下一回合永久力量变为 **-2**，应恢复为 0。
- C# 依据：`Models.Potions/FlexPotion.cs`、`SpeedPotion.cs`、`Models.Powers/TemporaryStrengthPower.cs`、`Models.Cards/SetupStrike.cs`（实际目录名有 `MegaCrit.Sts2.Core.` 前缀）。临时增益先增加基础力量，结束时撤回，不能在计算时重复计入。

## D03 — 高优先级：能力牌被当作消耗，污染整个消耗体系

- 位置：`battle.cpp:82–86`、`:1350`。
- `card_exhausts` 对所有 Power 返回 true，最终走 `move_to_exhaust` 和消耗钩子。
- 复现：从零状态打出 Feel No Pain，消耗堆变为 **1**，立即得到 **3 格挡**；预期分别是 **0、0**，它不应触发自己的消耗效果。
- C# `MegaCrit.Sts2.Core.Models/CardModel.cs:1586` 对 Power 返回 `PileType.None`，`:1519` 移出战斗；只有真实消耗才调用 Exhaust。
- 影响：Feel No Pain、Dark Embrace、消耗计数、相关遗物与可选消耗牌组均被改变。

## D04 — 高优先级：未区分普通攻击/卡牌格挡与 Unpowered 效果

- 位置：`battle.cpp:683–701`、`:313`、`potions.cpp:72`。
- 5 敏捷＋Feel No Pain(3)，消耗一张牌后实际 **8 格挡**，应 **3**。非卡牌格挡也被套用了敏捷。
- The Bomb(40)，玩家力量10、怪物仍有易伤时，爆炸实际 **75**，应 **40**。
- Explosive Ampoule 对易伤目标实际 **15**，应 **10**。
- C# 依据：`Models.Powers/FeelNoPainPower.cs`、`TheBombPower.cs`、`Models.Potions/ExplosiveAmpoule.cs` 显式用 `ValueProp.Unpowered`；`StrengthPower`、`DexterityPower`、`VulnerablePower` 对适用伤害/格挡类别有条件检查。
- 这属于底层效果来源分类问题，不能只逐张修正数值。

## D05 — 高优先级：多张 The Bomb 被合并成一颗延迟炸弹

- 位置：`cards_colorless.cpp:270–273`、`battle.cpp:310–315`。
- 同一回合打两张未升级 The Bomb，应第三个回合结束各爆炸40，共 **80**。实际第三回合结束伤害 **0**，因为计时被加成6，伤害只保留一个字段。
- C# `Models.Powers/TheBombPower.cs` 明确 `IsInstanced => true`，每次应用有独立倒计时与伤害。

## D06 — 高优先级：Rupture 在敌方回合受伤也增长力量

- 位置：`battle.cpp:747`（`lose_hp` 路径也缺少完整来源/时序约束）。
- 给玩家 Rupture(1)，在敌方攻击阶段受10伤害，力量实际 **+1**，预期 **0**。
- C# `Models.Powers/RupturePower.cs` 限制 `CurrentSide == Owner.Side`，还对同一张牌导致的伤害延迟到牌打完后结算。当前简化改变力量增长与连击时序。

## D07 — 高优先级：满手时继续从抽牌堆抽牌并扔进弃牌堆

- 位置：`battle.cpp:420–444`、`:521–528`。
- 10张手牌、抽牌堆3张，调用抽3张。预期抽牌堆仍3、弃牌堆0；实际 **抽牌堆0、弃牌堆3**。
- C# `MegaCrit.Sts2.Core.Commands/CardPileCmd.cs:725` 的 Draw 在手牌满时直接返回/停止。
- 影响：抽牌、洗牌、Void 等抽到触发、手牌保留和循环构筑都会偏离。

## D08 — 高优先级：固有牌在起手五张之外额外发放

- 位置：`battle.cpp:240–251`。
- 20张牌组含1张 Dramatic Entrance，起手实际 **6张**，应 **5张且包含该固有牌**。
- C# `CombatManager.cs:376–384` 是把固有牌移到牌顶，抽牌数取 `max(正常抽数, 固有数量)` 并限制10；不是先拿固有再抽5。

## D09 — 高优先级：升级后的关键字变化全部丢失

- 位置：`tools/gen_cards.py:89` 仅输出 base flags；`cards.cpp:44` 的 `card_has` 不区分升级状态。
- 实测升级 Secret Technique 选完牌仍进入消耗堆（**1**，应 **0**）。
- C# `Models.Cards/SecretTechnique.cs` 的 OnUpgrade 删除 Exhaust。
- 数据中还存在 Discovery、Secret Weapon、Thinking Ahead 升级去除 Exhaust，Aggression/Juggling/Entropy 升级获得 Innate，Scrawl/Anointed 获得 Retain 等变化。此次逐个动态验证的是 Secret Technique；其他受影响项来自生成器和 variants 数据对照。

## D10 — 高优先级：Runic Pyramid/保留效果阻止了虚无牌消耗

- 位置：`battle.cpp:493–502`，retain 分支在 ethereal 前。
- Runic Pyramid＋手中 Dazed，结束手牌处理后消耗堆实际 **0**，应 **1**。
- C# `CombatManager.cs:783–790` 在后续清手/保留阶段前处理 Ethereal。当前模拟器可把本该消失的牌留住。

## D11 — 高优先级：本回合临时费用在弃牌/抽牌堆中不恢复

- 位置：`battle.cpp:232–237` 只重置保留在手牌中的费用；`:510` 丢弃保留 costForTurn，后续抽牌直接复用；`cards.cpp:26` 直接读取该字段。
- 将一张本回合临时0费 Strike 放进弃牌堆，结束回合并重新抽到，实际仍 **0费**，应恢复 **1费**。
- C# `CardEnergyCost.cs:111/167/173` 有结束回合与打出后失效清理；Discovery 用 `SetThisTurnOrUntilPlayed(0)`，Infernal Blade 用 `SetToFreeThisTurn()`。
- 影响：临时免费生成、自动打牌留下的费用等可能变成整场免费。

## D12 — 高优先级：Pen Nib 等跨战斗计数被清零/不回传

- 位置：`relics.cpp:228` 把每件遗物的 combat aux 清零；`run.cpp:330` 同步遗物仅复制 ID，不复制计数。
- 构造 Pen Nib 已累计9次攻击的战斗结束状态，结束并进入下一场后计数实际 **0**，应 **9**。
- C# `Models.Relics/PenNib.cs` 的 AttacksPlayed 为 `[SavedProperty]`，不是每场重置。
- 此次验证对象是 Pen Nib；其他跨战斗遗物计数需要逐个确认，不能把所有 aux 都不加区分地持久化或清空。

## D13 — 高优先级：部分群攻绕过遗物伤害修正

- 位置：`cards_ironclad.cpp:18` 的 hit_all 调用 attack_all；该路径没有 `relics_modify_damage`，与 attack_from_card 不同。
- Pen Nib 计数9时打 Thunderclap，实际伤害 **4**，应 **8**。
- C# PenNib 的伤害乘数适用于符合条件的攻击牌，不局限于单体牌。
- 同类直接走 attack_all/attack_monster 的牌应按调用路径审计；本轮不泛称所有群攻都有问题。

## D14 — 高优先级：自动打牌没有执行完整“打出一张牌”生命周期

- 位置：`battle.cpp:1355` 的 auto_play_random 绕过 play_card 中的计数及 after_card_played。
- 有 Rage(3) 时自动打出 Strike，攻击次数实际 **0**（应1），格挡 **0**（应3）。
- C# `Commands/CardCmd.cs:112` 的 AutoPlay 进入 OnPlayWrapper；`Models/CardModel.cs:1488/1506` 执行 Before/AfterCardPlayed。
- 影响：Mayhem、Beat Down、其他自动打牌与计数/遗物/能力组合。

## D15 — 高优先级：直接加格挡绕过获得格挡的钩子

- 位置：`potions.cpp:137` 使用 `player.block += 12`。
- 有 Juggernaut(5)，喝 Block Potion 后怪物实际损血 **0**，应 **5**。
- C# BlockPotion 通过 CreatureCmd.GainBlock；JuggernautPower.AfterBlockGained 不要求格挡来自卡牌。
- 与 D04 不同：D04 是错误套用数值修正，本项是完全跳过触发事件。

## D16 — 高优先级：Dark Shackles 绕过 Artifact

- 位置：`cards_colorless.cpp:105–112` 直接修改怪物力量和恢复字段。
- 目标有1层 Artifact 时打 Dark Shackles，实际力量 **-9**、Artifact仍 **1**；应力量 **0**、Artifact **0**。
- C# `Models.Powers/ArtifactPower.cs` 拦截可见 debuff，`DarkShacklesPower` 是负向 TemporaryStrengthPower。当前只在部分 apply_weak/apply_vulnerable 路径检查 Artifact。

## D17 — 高优先级：选牌候选被截断为最多10张

- 位置：`battle.h` PendingChoice.cards[MAX_HAND]；`battle.cpp:885/919`。
- 弃牌堆15张时 Headbutt 只给 **10个**候选；抽牌堆15张技能时 Secret Technique 也只给 **10个**候选，均应15。
- C# Headbutt/SecretTechnique 把满足条件的整个牌堆列表交给选择器。
- 影响：大牌组检索和回收的策略空间被缩小；这不是“手牌最多10张”的合法限制。

## D18 — 接口问题：非法 PLAY_CARD 返回成功但不执行

- 位置：`battle.cpp:1207–1211` 调用 void play_card 后总返回 true；费用/Choker 的拒绝发生在内部。
- 0能量打1费 Strike，`step` 返回 **true**；Velvet Choker 第7张也返回 **true**。预期返回 false。
- 只从 legal_actions 采样通常不触发，所以整局随机合法动作压力测试能通过；外部策略、过期动作或训练接口无法可靠发现拒绝，可能产生无动作进展或错误样本。

## D19 — 高优先级：隐藏信息重采样会洗掉玩家已知牌顶

- 位置：`battle.cpp:158` 无条件重排全部 draw。
- Headbutt 把已选 Bash 放到牌顶，玩家知道下一抽是 Bash。随后对20个随机种子重采样，**14次牌顶被换掉**，预期0次。
- 这使重采样搜索不再符合当前玩家信息：不仅去掉未知未来，也破坏了确定已知的信息。
- C# Headbutt 的 CardPilePosition.Top 是明确的玩家选择结果。需要记录已知信息约束；当前仅保留牌组组成不够。

## D20 — 高优先级：不同决策状态仍映射为相同网络输入

- 位置：`observe.cpp:119`、`:186`；CombatNet 输入见 `agent/nets.py:61`。
- 无遗物与有 Orichalcum 的相同战斗，其 combat observation 完全相同；上轮也已验证合法动作与所有动作特征相同，结束回合后受伤量不同。完整 run observation 有遗物，并不代表独立 combat observation 有。
- 选择状态只编码“是否有 pending”，没编码 ChoiceOp/ChoicePile。对同一候选 Strike 的“升级它”和“消耗它”，构造状态的观测完全相同；候选动作特征也不能表达操作目的。
- 这是可学习性问题，增加训练轮数无法让无记忆网络区分完全相同的输入。

## 其他确认项与未完成范围

### D21 — 既知评估问题：启发式仍是 oracle 前瞻

`agent/heuristics.py:85–88` clone 真实战斗后直接 rollout，没有隐藏信息重采样。heuristic 和 network_cards 都使用该战斗策略；不能与 search_resampled 直接解释为同等信息条件的实战对照。`deployment/evaluate.py:81` 只排除名字 search，连 oracle 的 search_value 都会标为 player_usable。此项是上轮结论的源码复核，不是此次重新跑1000模型对比。

### D22 — 内部状态已复现，但当前A0可达来源未确认：Intangible

受控状态赋予1层 Intangible 后结束敌方回合，实际仍1层，C# IntangiblePower.AfterTurnEnd 应减为0；调用 lose_hp(6) 实际掉6，参考的 HP lost cap 应限制为1。

当前未发现已实现的 A0 常规可达内容实际应用该状态，Apparition 等事件来源仍有未支持项。因此此项只证明内部能力实现不完整，**不宣称当前正常A0训练已经能够利用永久虚无**，也不列入D01–D20核心计数。

### D23 — 既知指标问题：self-play benchmark 仍把请求局数当完成局数

`deployment/benchmark_speed.py:129` 的 `_bench_selfplay` 返回 `completed_runs=runs`，没有依据 episode status 计数。真正发生截断/错误时会误报完成数。搜索基准的模拟计数问题已经修复，这一分支仍遗漏。

### 明确保留的内容缺口

29个事件仍排除、22个近似；部分附魔、事件遗物及真实选择未完整实现；真实客户端逐步轨迹验证仍为0。这些已在现有 coverage 中声明，不重复计为本轮新发现的隐蔽 bug。

## 复现材料与命令

目录：`D:\sts2_datacollection\sts2\.scratch\deep-audit-20261028`

- `probe.cpp` / `probe-results.txt`：36项定向检查和逐项 expected/actual。
- `bounds.cpp` / `bounds-results.txt`：原始卡牌源码边界插桩，Beat Down 越界证据；处理器用退出码77报告。
- `fuzz.cpp` / `fuzz-results.txt`：卡牌和遭遇扫描、克隆一致性与牌堆不变量。
- `run_fuzz.py` / `run-fuzz-results.txt`：1000局、7248次快照重复执行。
- `source-hashes.json`：本次关键源码和已编译 Python 扩展 SHA256。
- `reproduce.ps1`：重建独立探针并重跑；链接现有 build-mingw 对象，不覆盖项目的 exe/pyd。

PowerShell：

```powershell
Set-Location D:\sts2_datacollection\sts2
.\.venv\Scripts\python.exe -m pytest tests -q
& .\.scratch\deep-audit-20261028\reproduce.ps1
```

若以后引擎源码变化，需要先按项目正常流程构建，使 build-mingw 对象与源码一致，再运行探针。本次未修任何实现，也未把定向检查加入现有测试套件。

## 处理优先级（仅建议，未实施）

先处理 D01 内存越界；其次修通用结算层：临时属性、Power移出/Exhaust、Unpowered分类、抽牌/起手/费用/关键字、自动打牌钩子；再处理跨战斗计数、选择容量、搜索信息约束和观测。这样能覆盖整类错误，而不是只修已举例的单卡。

这些问题未解决前，模型可能稳定地学会当前程序，但其构筑价值、战斗顺序和搜索结果仍与参考规则存在系统性差异。
