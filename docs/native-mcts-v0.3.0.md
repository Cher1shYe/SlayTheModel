# 原生战斗 MCTS v0.3.0 实验版

本版已实现 Windows 和 macOS ARM64 上的隔离原生模拟、限时 UCT、搜索树复用和可选的游戏内控制入口。它是可试用原型，不是全卡牌兼容或整局通关版本。

## 本机直接试用

本机已经构建 worker 并安装 Mod。打开 Steam，完全退出已有游戏，在 PowerShell 执行：

```powershell
cd C:\Users\15808\Desktop\github\sts2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows.ps1 -Action Launch -RunMode play -CombatPolicy mcts -OutsideCombatPolicy manual -CaptureHistory
```

macOS ARM64 首次使用：

```bash
./scripts/native-worker-macos.sh --mode verify
./scripts/macos.sh --action install
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy mcts --outside-combat-policy manual --capture-history
```

选择单人铁甲战士，进入一场新战斗。其他玩法 Mod 不在验证范围内。战斗外仍手动操作，不要在自动搜索期间使用药水。当前 `first-legal` 模式仍可独立使用。

- 首次搜索约 5 秒；提交动作后立即预测下一决策状态，并在动作、动画和敌方回合期间以 500 毫秒时间片持续扩展匹配子树。到达决策点时使用状态指纹完全匹配的最新结果。
- F8 暂停／恢复。暂停停止提交新动作，已提交动作继续结算；待选择的卡牌通过原生网格界面交还玩家。
- 右上角小按钮显示 MCTS 的实际状态：绿色开启／待命、蓝色思考中、黄色暂停、灰色未开启或当前战斗不支持。战斗中点击按钮也可暂停／恢复，与 F8 共用同一逻辑。悬停查看说明；未通过 `-CombatPolicy mcts` 启动时只显示状态，不能点击启用。
- 恢复、实际局面改变或树不匹配时，重新搜索 5 秒。手动出牌和选牌会记录进重放前缀。
- 无法重建实际状态、未支持的动作或持续模拟异常会暂停，日志保留原因；不会绕过状态校验直接执行猜测动作。
- 对中途加载的战斗，如果没有捕获到有效入口，可能无法搜索；进入新战斗重试。
- 目前 F8 为固定键位；复杂选择 UI 和实际窗口中的暂停／恢复尚需交互验证。

搜索日志与请求保存在仓库 `artifacts/live-capture/search/`。游戏日志位于 `%APPDATA%\SlayTheSpire2\logs\godot.log`。日志中应出现 `[SlayTheModel] MCTS simulations=... retained=... ms=... rebuilt=...`。如果出现 `MCTS paused`，检查同目录 worker 日志及错误原因。

## 可重复构建和检查

```powershell
./scripts/windows.ps1 -Action Test
./scripts/native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'
./scripts/windows.ps1 -Action Install
```

worker 构建需要 .NET 9 SDK，并通过 NuGet 获取 Godot.NET.Sdk 4.5.1。脚本只接受契约中的 Windows v0.111.0 程序集哈希。引擎可执行文件和依赖从本机合法安装复制到被 Git 忽略的 `artifacts/native-host`；原生资源包只读加载，仓库不分发游戏二进制。

macOS 脚本固定校验 ARM64 v0.111.0 程序集，并复用游戏附带的自包含 .NET runtime、依赖清单和 MegaDot 可执行文件，不额外下载或混用另一套运行时。

独立 worker 使用最小 Godot 项目和 `SlayTheModelWorker` 用户数据目录，不启动游戏主场景、不初始化 Steam、不开启游戏存档写入。使用原生 TestMode 和 NonInteractiveMode 跳过表现。GodotSharp 必须使用游戏附带的定制版本；仅使用同版本 NuGet DLL 不足以保证 MegaDot 的原生 ABI 匹配。

运行小样本对比：

```powershell
./scripts/native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2' -Mode benchmark -TimeoutSeconds 600
```

原始输出在 `artifacts/native-host/benchmark.json`，标准输出及错误分别在同目录 `stdout.txt`、`stderr.txt`。启动脚本带进程超时回收；实时子进程还会在父进程退出后结束。

## 本次验证结果

通过的检查：

1. 搜索、协议、动作完成与限时重放搜索四组 smoke 测试；覆盖树复用、状态不匹配拒绝、调用者取消、超时未完成 rollout 不计为有效结果。
2. 相同种子原生重建及相同动作重放的完整原生状态指纹一致。
3. 序列化战斗入口恢复后，初始状态和单步结果与原始后台战斗一致。
4. 洁净对 4 个候选暴露全部 15 个“选 0～3 张”的组合，选择后状态可重放，不同选择分支互不污染；武装必选升级可完成。
5. 真实子进程搜索不改变父进程战斗状态；父进程执行返回动作后，下一次请求复用匹配子树。
6. 本机 Release Mod 构建及安装成功。

以下为冻结 rollout 配置后，3 个新种子在同一 `CULTISTS_NORMAL` 遭遇中的结果。铁甲初始牌组、进阶 0、入场 80 HP，无药水，结束 HP 包含战斗结束时的原生回血。此表不是完整实战验收。

| 策略 | 种子 1 | 种子 2 | 种子 3 | 获胜 |
|---|---:|---:|---:|---:|
| first-legal | 42 HP | 战败 | 15 HP | 2/3 |
| 防御优先启发式 | 战败 | 战败 | 战败 | 0/3 |
| 攻击优先启发式 | 48 HP | 27 HP | 43 HP | 3/3 |
| MCTS | 48 HP | 73 HP | 49 HP | 3/3 |

MCTS 和攻击优先基线共同获胜的 3 场，平均净掉血分别为 23.3 和 40.7。MCTS 和 first-legal 共同获胜的 2 场，平均净掉血分别为 31.5 和 51.5。防御优先基线没有共同获胜样本，不计算其获胜掉血均值。

3 次首步搜索平均 5013 ms；54 次后续搜索平均 1009 ms、最大 1015 ms。首步平均完成约 86 次模拟，后续平均约 19 次。时间为搜索阶段，入口重建、通信和游戏动画需另计；不同运行的限时搜索结果可能不同。

原始逐决策记录及硬件、哈希、配置见 [native-mcts-v0.3.0.json](benchmarks/native-mcts-v0.3.0.json)。这 3 个样本不足以给出统计意义上的强度结论。

## 实现与限制

- 状态复制采用“序列化战斗入口 + 动作／选择前缀重放”。没有手写伤害模拟或浅复制原生单例。恢复使用版本固定的初始化接口，包括少量反射调用，因此游戏更新后必须重新验证。
- 每次搜索只回传完成 rollout 的统计，动作结束后以完整原生包哈希验证。达到 200 动作深度上限的 rollout 作为未解决状态计分，不伪装成获胜。
- 效用为战败 -1、未解决 -0.5、获胜 `0.5 + atan((结束HP - 入场HP)/20)/pi`。获胜效用始终高于战败，且随净掉血减少而增加。
- 原先单一防御优先 rollout 在持续成长的敌人面前表现差。当前 rollout 每步混合防御优先和攻击优先规则；这是启发式，不是通用斩杀证明。额外保留攻击优先基线以避免只对比很弱的策略。
- 原生 `ICardSelector` 路径下的手牌／网格选择可搜索；特殊按钮、额外目标、不同选牌顺序导致不同效果的排列、其他角色、事件嵌套战斗和其他 Mod 尚未完整验证。不能据此宣称所有后续动作已支持。
- 后台 TestMode 验证和进程间对齐已经完成；游戏实际窗口中的状态一致性、F8 手动接管以及广泛卡牌／遗物组合仍需验证。实时入口是显式启用的实验模式，遇到偏差会停止提交动作。
- 重放耗时随战斗前缀增长，这是目前性能瓶颈。下一阶段优先扩大真实战斗对齐样本，再考虑更快的快照恢复与并行，避免用错误的快照换取搜索速度。
