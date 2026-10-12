# Mod 教程对战斗 AlphaZero 的实际帮助验证

日期：2026-10-09。仅新增本目录文件，未修改模拟器、训练代码或 spec.md。

## 结论

有实际帮助：以教程为检查清单，对照本地反编译 C#，再执行 Python 探针，发现两类可复现差异。教程还能帮助构造实机测试场景，并提醒 AutoSlay 的发行版限制。没有证据表明这些教程能直接提高 MCTS 每秒模拟次数。

验证边界：本次运行了 Python 模拟器，人工阅读了本地 C#，没有启动游戏、执行 C#、安装 Mod 或录制实机轨迹。因此下面的“预期”是本地源码推导值，不是实机测量值。没有确认本地反编译文件与当前安装游戏的构建完全一致。

## 实际运行结果

运行命令（仓库根目录，PowerShell）：

```powershell
.\.venv\Scripts\python.exe -B tutorial_validation/probe.py
```

结果见 `results.json`。探针成功运行，7 项中 4 项一致，3 项差异对应 2 类问题；退出码 0 仅表示探针执行及文件保护检查完成，不表示全部规则一致。

| 探针 | 本地 C# 推导 | Python 实际 | 结果 |
|---|---|---|---|
| 基础伤害 6、力量 3、无附魔 | 9 | 9 | 一致 |
| 基础伤害 6、Favored、无力量 | 12 | 12 | 一致 |
| 基础伤害 6、Favored、力量 3 | 15 | 18 | 差异 |
| 基础伤害 6、Corrupted、力量 3 | 12 | 13 | 差异 |
| AfterDamageGiven 监听顺序 | 玩家能力→玩家遗物→敌方能力 | 玩家能力→敌方能力→玩家遗物 | 差异 |
| 非致死、破格挡伤害 | block→hp→given→received | 相同 | 一致 |
| 致死、破格挡伤害 | block→hp→given，无 received | 相同 | 一致 |

这些是定向探针，不能把 4/7 解读成模拟器整体正确率。

### 发现 1：附魔倍率错误地放大了力量

本地 `decompiled/MegaCrit.Sts2.Core.Hooks/Hook.cs:1106` 的 `ModifyDamage` 先处理附魔，随后进入 `ModifyDamageInternal`（约 1902 行）处理力量等加算。因此 Favored 案例为 `6 × 2 + 3 = 15`；Corrupted 为 `6 × 1.5 + 3 = 12`。

`sts2_env/core/hooks.py:162` 的 `modify_damage` 先加力量，后乘附魔，分别得到 `(6+3) × 2 = 18` 和 `floor((6+3) × 1.5) = 13`。倍率分别由本地 `Models.Enchantments/Favored.cs` 和 `Corrupted.cs` 独立确认。

探针直接调用真实伤害计算函数，采用真实打击牌和力量能力；没有替换计算函数。Corrupted 自伤等完整出牌效果未纳入本探针。

对训练的意义：包含这些组合的训练场景会高估攻击收益，可能影响斩杀判断。无附魔起始牌组不直接触发这个已复现问题；不能因此断言当前 MVP 训练已受影响。

### 发现 2：监听者枚举顺序不同

本地 `decompiled/MegaCrit.Sts2.Core.Combat/CombatState.cs:264` 按生物逐个收集监听者：一个玩家的能力和遗物位于敌方能力之前。`Hook.cs:272` 的 `AfterDamageGiven` 使用该列表。

Python `sts2_env/core/hooks.py:1058` 先枚举所有生物能力，再枚举所有玩家遗物。独立记录器确认这一顺序差异。记录器仅放入临时战斗对象，没有改写现有类或函数。

对训练的意义：存在相互影响的监听效果时可能改变状态。此处证明的是调度顺序差异，尚未证明某个真实遗物与怪物能力组合会改变胜负；后续应寻找真实组合并录制实机轨迹。空遗物训练场景不直接触发本探针中的跨类别顺序问题。

### 已一致的部分

通过临时 Power 记录器执行实际 `apply_damage`，普通非致死与致死单目标伤害的几个关键回调顺序符合本地 `CreatureCmd.cs:255` 一带的逻辑。这个对照避免只寻找反例；没有覆盖伤害转移、复活或回调中再次造成伤害。

## 教程在其他方面的帮助

### 1. 控制台：构造可重复实机案例

[控制台教程](https://tutorials.sts2modding.com/docs/09-console-commands/)提供测试入口。已在本地 `decompiled/MegaCrit.Sts2.Core.DevConsole.ConsoleCommands/` 核实 `CardConsoleCmd`、`EnchantConsoleCmd`、`ApplyPowerConsoleCmd` 的参数：

```text
card <card-id> [pileName]
enchant <id> [amount] [hand-index]
power <id> <amount> <target-index>
```

下一次实机验证可以构造“无其他增减伤、无格挡目标、6 伤害打击、力量 3、Favored”场景，观察实际伤害是否为 15。必须确认卡牌/目标索引和 ID；本次没有把上述模板作为实机成功执行的命令。

### 2. AutoSlay：确认自动测试入口的限制

[启动参数教程](https://tutorials.sts2modding.com/docs/08-launch-arguments/)提示发行版限制。本地 `NGame.cs:404` 确实要求 `!IsReleaseGame()` 才进入 AutoSlay，而约 452 行的该方法返回 `true`。因此对这份源码，单加 `--autoslay` 不足以启用自动测试。

这能避免无效调试，但未验证教程补丁在已安装游戏上能运行。本次未创建或加载补丁。AutoSlay 入口本身也不能证明有适合 MCTS 的状态克隆、回滚或高速无头模拟。

### 3. Patch 与桥接：适合未来采集证据

[Patch 教程](https://tutorials.sts2modding.com/docs/10-patch/)可指导观测位置，但异步战斗方法的普通 Postfix 不一定代表 Task 已完成，采样应放在确实结算完成的边界。

项目已有 `sts2_env/parity/bridge_replay.py`、`bridge_replay_cli.py` 及 `sts2_env/bridge/`；相邻 `sts2-cli/agent/sts2_bridge.py` 也有完整响应日志选项。优先复用这些设施，先检查字段和格式是否兼容，不能假定 JSONL 日志可直接交给另一套 JSON 回放接口。当前没有必要为了这些教程整体迁移到 RitsuLib。

## 版本差异：教程不能直接作为规则真值

[触发顺序教程](https://tutorials.sts2modding.com/docs/12-hook-trigger-order/)声明基于 0.111，且经过 AI 整理。本次源码检查发现：教程提到的 `IterateCombatHookListeners` 名称不在本地 `Hook.cs` 中，`BadgeModels` 也不在本地 `CombatState.cs` 中。

这是资料与本地代码存在差异的证据，不足以单独判定哪一方有错，也不足以确定本地游戏版本。应记录游戏构建号、程序集哈希和反编译来源。本次结果已记录三个关键 C# 文件 SHA-256，供后续比较。

## 建议的后续顺序

1. 对齐安装游戏、反编译源码、模拟器的目标版本。
2. 实机复现 Favored + 力量，采集动作前后快照，独立确认数值。
3. 经授权修改正式代码时，把本探针转成相应回归测试并修正结算顺序；本次未修复。
4. 找一个真实遗物/能力交互案例确认监听顺序的实际影响，再决定统一调度的修改范围。
5. 每个扩展训练场景加入源码检查和少量实机轨迹验证，降低模型利用模拟器误差的风险。

本次探针运行前后对 `sts2_env`、`tests`、`scripts`、`configs`、`decompiled` 及 spec/依赖文件共 3590 个文件进行内容哈希比较，未发现变化。该保护检查覆盖所列文件，不宣称监控整个工作区。
