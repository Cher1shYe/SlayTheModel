# SlayTheModel

面向《杀戮尖塔 2》（*Slay the Spire 2*）的全知状态、无头战斗模拟与 MCTS 基线工程。

项目短期目标是实现一个可复现的全局 MCTS：游戏适配器负责读取并复制完整状态，局内搜索负责出牌、选目标和结束回合，局外搜索负责地图、奖励、商店、休息点与事件，最终由分层控制器完成整局决策。

项目的长期目标是训练一个杀戮尖塔2专用的神经网络，希望能适配各个版本。结合安东尼现在的更新频率和更新效率，目前想先在各个版本中跑通基本MCTS，再在不同版本下测试神经网络的可行性

> 当前仓库仍处于基础设施阶段。已经打通“读取战斗状态 → 抽象决策状态 → 生成合法动作 → 校验状态指纹 → 把动作送回游戏”的闭环；游戏内的 `first-legal` 只是联调策略，并不是 MCTS，也不代表模型强度。

## 当前实现

- 不依赖第三方包的通用 UCT/MCTS 核心；
- 针对 STS2 `v0.111.0` 固定的 ABI 探针与兼容性契约；
- 与游戏程序集解耦的状态、动作和 JSON 协议；
- 将局内战斗观察与金币等局外信息分开，避免战斗策略意外读取局外数据；
- 游戏内只读状态采集，可导出稳定决策点和原生校验和；
- 带状态指纹校验的动作桥，可执行出牌、选择目标和结束回合；
- 无头 smoke test 与采集文件检查工具；
- 可选的 `first-legal` 游戏内自动操作，用于验证整个闭环。

目前游戏内合法动作枚举以“出牌、选目标、结束回合”为主。药水与完整的分支决策协议尚未接入。单人 first-legal 已通过原生选牌接口自动处理动作内的手牌/网格选择，其他特殊交互仍需验证。另有显式启用的实验性 `mcts` 模式，使用独立原生 worker；`first-legal` 仍是独立联调策略。

## 环境要求

当前安装与启动流程已在以下环境验证：

- macOS；
- Steam 版《杀戮尖塔 2》；
- 游戏版本 `v0.111.0`；
- .NET SDK `9.0.306`。`global.json` 允许滚动到同一 SDK 的更新 feature band。

Windows x64 已通过本机 v0.111.0 的 Release 构建、搜索/协议 smoke 测试和 ABI 契约检查；游戏内加载和自动战斗仍需交互验证。

先确认 .NET：

```bash
dotnet --version
```

下面的 macOS 命令假设 Steam 和游戏安装在默认目录。如果游戏位于其他位置，构建时需要通过 `-p:Sts2ManagedDir=...` 指定包含 `sts2.dll`、`GodotSharp.dll` 和 `0Harmony.dll` 的目录。

## 编译与终端测试

在仓库根目录执行：

```bash
dotnet build smoke/SlayTheModel.Search.Smoke/SlayTheModel.Search.Smoke.csproj
dotnet run --project smoke/SlayTheModel.Search.Smoke/SlayTheModel.Search.Smoke.csproj

dotnet build smoke/SlayTheModel.Protocol.Smoke/SlayTheModel.Protocol.Smoke.csproj
dotnet run --project smoke/SlayTheModel.Protocol.Smoke/SlayTheModel.Protocol.Smoke.csproj
```

这些测试不需要启动游戏。它们验证通用搜索器、协议、状态哈希和决策信息隔离，但不会凭空创建一场真实 STS2 战斗。

读取本机游戏程序集的 ABI 信息时，工具只读取元数据，不加载或执行游戏代码：

```bash
dotnet run --project tools/Sts2.AbiProbe/Sts2.AbiProbe.csproj -- \
  --contract contracts/sts2-v0.111.0.json \
  --out artifacts/abi/sts2-current.json
```

## 编译并安装 Mod（macOS）

开始前请完全退出游戏。先构建 Release 版本：

```bash
dotnet build src/SlayTheModel.Sts2.ModAdapter/SlayTheModel.Sts2.ModAdapter.csproj -c Release
```

默认 Steam 路径下的安装命令：

```bash
STS2_MOD_DIR="$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/mods/SlayTheModelAdapter"

mkdir -p "$STS2_MOD_DIR"
cp src/SlayTheModel.Sts2.ModAdapter/bin/Release/net9.0/SlayTheModelAdapter.dll "$STS2_MOD_DIR/"
cp src/SlayTheModel.Sts2.ModAdapter/SlayTheModelAdapter.json "$STS2_MOD_DIR/"
```

安装目录最终只需要这两个文件：

```text
SlayTheModelAdapter/
├── SlayTheModelAdapter.dll
└── SlayTheModelAdapter.json
```

协议类型已经编译进主 DLL，不需要另外复制 `SlayTheModel.Sts2.Protocol.dll`。更新 Mod 时，退出游戏、重新构建并覆盖上述两个文件即可。

## macOS 启动方式一：只采集状态，不自动打牌

先启动 Steam 客户端，但不要从 Steam 启动游戏。确认没有已经运行的游戏进程，然后在仓库根目录执行：

```bash
SLAY_THE_MODEL_EXPORT_DIR="$PWD/artifacts/live-capture" \
SLAY_THE_MODEL_CAPTURE_HISTORY=1 \
SteamAppId=2868840 \
SteamGameId=2868840 \
"$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/Slay the Spire 2"
```

此模式下，Mod 只在稳定的玩家决策点读取和导出状态，不会替玩家出牌。终端应出现：

```text
[SlayTheModel] live policy disabled; set SLAY_THE_MODEL_LIVE_POLICY=first-legal to enable it
[SlayTheModel] omniscient combat capture adapter initialized
```

默认持续覆盖：

```text
artifacts/live-capture/latest-combat-decision.json
```

`SLAY_THE_MODEL_CAPTURE_HISTORY=1` 会额外保存每个不同决策点；不需要历史记录时，可以从启动命令中删除这一行。

## macOS 启动方式二：让联调策略自动接管战斗

同样需要先完全退出当前游戏，再用下面的命令启动新进程：

```bash
SLAY_THE_MODEL_LIVE_POLICY=first-legal \
SLAY_THE_MODEL_EXPORT_DIR="$PWD/artifacts/live-capture" \
SLAY_THE_MODEL_CAPTURE_HISTORY=1 \
SteamAppId=2868840 \
SteamGameId=2868840 \
"$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/Slay the Spire 2"
```

环境变量只会在游戏进程启动时读取，所以不能先从 Steam 启动游戏，再在另一个终端里设置变量。成功启用时，终端会打印：

```text
[SlayTheModel] LIVE CONTROL ENABLED policy=first-legal; the adapter will play cards and end turns automatically
```

之后仍然需要玩家手动操作主菜单、选择单人游戏、角色、初始选项、地图节点和奖励。当前适配器只在进入战斗并轮到玩家行动时接管；它不会自动开启新游戏，也不会处理地图与奖励页面。如果同时安装了 SpeedX 一类自动推进 Mod，战斗外的自动操作来自那些 Mod，而不是 SlayTheModel。

## Windows 操作说明

在仓库根目录用 PowerShell 5.1 或更高版本运行。安装 .NET 9 SDK（9.0.306 或更高的 9.0 feature band），先打开 Steam 客户端。脚本通过 Steam 注册表和 `libraryfolders.vdf` 查找游戏，支持其他磁盘的 Steam 库和带空格的路径。

```powershell
# 检查游戏路径、三个依赖程序集和 SDK
./scripts/windows.ps1 -Action Check
# 无需安装游戏的搜索与协议测试
./scripts/windows.ps1 -Action Test
# 核对 Windows v0.111.0 的程序集哈希、版本和必需接口
./scripts/windows.ps1 -Action Probe
# 完全退出游戏后，构建并安装 DLL 和 manifest
./scripts/windows.ps1 -Action Install
# 只采集状态
./scripts/windows.ps1 -Action Launch -CaptureHistory
# 或退出游戏后启用 first-legal 自动战斗
./scripts/windows.ps1 -Action Launch -Policy first-legal -CaptureHistory
```

只构建不安装时使用 `-Action Build`。自动发现失败时指定 `-GameDir 'D:\SteamLibrary\steamapps\common\Slay the Spire 2'`，也可设置 `STS2_GAME_DIR` 环境变量。非标准程序集位置可用 `-ManagedDir` 指定。直接使用 `dotnet build` 时，Windows 默认查找标准 Steam 目录，支持 `STS2_GAME_DIR` 或 `-p:Sts2ManagedDir=...`；其他 Steam 库请优先使用脚本。

脚本优先使用 `%LOCALAPPDATA%\SlayTheModel\dotnet\dotnet.exe`（若存在），否则使用 PATH 上的 `dotnet`。本机验证使用前者安装的 SDK 9.0.306。

启动默认输出到仓库的 `artifacts/live-capture`，可用 `-ExportDir` 修改。环境变量仅传给新启动的游戏，随后恢复当前 PowerShell 环境；默认 capture 模式会清除继承的自动操作设置。启动前需退出已有游戏，安装也会拒绝在游戏运行时覆盖 DLL。

首次启动如提示 Mod，请启用。当前自动操作仅支持单人战斗，主菜单、角色、地图、奖励和未实现的特殊选择仍需手动处理。环境变量不支持游戏运行时切换。

Windows ABI 契约位于 `contracts/sts2-v0.111.0-windows.json`，来源为本机 v0.111.0、commit `41cef1ea`；macOS 契约保持独立。Windows 已验证构建和静态 ABI，尚未验证游戏内战斗。ABI 通过不等同于完整运行时兼容性。

本机 Windows 日志位于 `%APPDATA%\SlayTheSpire2\logs\godot.log`。采集文件仍可用后文的 CaptureCheck 工具检查。

## 实验性 MCTS（Windows，v0.3.0）

已接入独立原生战斗 worker、入口重建与动作重放、首步 5 秒搜索、动作与动画期间以 500 毫秒时间片持续思考、搜索树复用，以及 F8 暂停／恢复。决策点只采用与实际完整状态指纹匹配的最新结果。首版仅面向单人铁甲战士，不使用药水，战斗外手动操作。

游戏右上角显示 MCTS 状态按钮：绿色开启、蓝色思考中、黄色暂停、灰色未开启或不支持。战斗中可点击暂停／恢复，悬停查看说明。

```powershell
./scripts/native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'
./scripts/windows.ps1 -Action Install
./scripts/windows.ps1 -Action Launch -Policy mcts -CaptureHistory
```

原生重放、后续选牌和跨进程状态校验已经通过；实际游戏窗口和广泛卡牌组合仍需验证。3 个固定遭遇测试中 MCTS 获胜 3/3，但不能据此推断整局强度。详见 [使用说明、测试结果与限制](docs/native-mcts-v0.3.0.md) 和 [设计方案](docs/combat-mcts-v1-plan.md)。

## 测试用策略：`first-legal`

这个名字表示“合法动作列表的第一项”，不是“画面中最左边的第一张牌”。每次决策时它会：

1. 枚举当前可出的卡牌及其合法目标；
2. 将结束回合排在其他动作之后；
3. 按玩家 ID、动作类型、卡牌内部 `CombatCardIndex` 和目标 ID 稳定排序；
4. 执行排序后的第一项；
5. 状态变化后重新枚举；没有可出的牌时结束回合。

动作内的原生选牌按候选列表顺序选取最低要求数量：响指选择第一张符合条件的手牌；洁净允许选 0 张，所以直接跳过可选消耗。选牌器只在当前自动动作执行期间生效，结束后恢复原有选择器，不接管战斗奖励。调度等待动作真正完成及队列清理，并在下一帧继续，避免选牌暂停被误判为完成而反复调度。发生执行异常时停用自动策略，避免持续重试。

它不会阅读卡牌文本、计算伤害或进行策略评估；这是一个确定性的端到端联调工具。

每次实际动作之前，终端都会出现类似日志：

```text
[SlayTheModel] live decision=0 action=play_card:0:target:2 fingerprint=0123456789ab
```

## 检查导出的决策文件

```bash
dotnet run --project tools/SlayTheModel.CaptureCheck -- \
  artifacts/live-capture/latest-combat-decision.json
```

主要接口：

- `CombatCaptureService.BuildSearchPoint(...)`：返回完整模拟器状态、过滤后的局内决策以及独立的局外观察；
- `CombatCaptureService.BuildDecisionPoint(...)`：只返回给战斗策略使用的观察与稳定合法动作列表；
- `CombatStepGuard.RequireExpectedState(...)`：拒绝针对旧状态生成的命令；
- `CombatActionExecutor.CreateGameAction(...)`：把协议动作转换为原生游戏动作，但不执行；
- `CombatActionExecutor.ExecuteAsync(...)`：把动作加入原生执行队列，并等待执行器恢复空闲。

## 常见问题

### 游戏启动了，但 Mod 没有输出

检查以下内容：

- 游戏是否在复制 DLL 后重新启动；
- `SlayTheModelAdapter.dll` 与 `SlayTheModelAdapter.json` 是否位于同一个 Mod 目录；
- 是否通过终端命令启动了这一份游戏；
- 当前游戏版本是否仍兼容 `v0.111.0` 的接口；
- 是否有其他 Mod 在启动阶段报错。排查时建议只保留本 Mod。

### Mod 读取状态，但不自动出牌

这是默认且更安全的行为。只有在启动游戏前设置了精确的 `SLAY_THE_MODEL_LIVE_POLICY=first-legal`，自动操作才会启用。

### 如何立即停止自动操作

退出游戏，然后不带 `SLAY_THE_MODEL_LIVE_POLICY` 重新启动。当前版本不会在游戏运行中动态切换策略。

### 游戏更新后构建或启动失败

本项目的已验证接口固定在 `v0.111.0`。游戏更新可能改变 ABI；先运行 ABI 探针并对照 `contracts/sts2-v0.111.0.json`，不要在未验证的新版本上假设动作桥仍然安全。

## 设计文档

- [基线设计与里程碑](docs/baseline-design.md)
- [STS2 v0.111.0 接口说明](docs/sts2-v0.111.0-abi.md)

本项目要求使用者自行拥有合法安装的游戏，仓库不分发游戏程序集或游戏资源。

## Combat Solver MCTS 后端（当前 Windows 集成）

当前分支把 Combat Solver 源码放在仓库内的 `combat/` 目录中。它只负责提供可复制的无头战斗模拟；出牌策略仍然是本项目自己的 `ReplayMcts`/UCT，Combat Solver 的 Beam Search 不会接管决策。

集成边界如下：

- `tools/Sts2.NativeWorker/CombatSolverReplayEnvironment.cs` 将 Combat Solver 的 root snapshot、fork 和动作展开适配为 MCTS 模拟环境；
- 游戏适配器负责捕获战斗 checkpoint、执行真实动作，并校验预测 continuation；
- 当前固定使用 Combat Solver commit `8826a333a6d48e05f0e368ee2db5d4a15092382e`；
- 只保证原版卡牌/敌人以及 Combat Solver 已登记适配的内容；药水不进入搜索；
- 不支持的动态选择或效果会显式报告错误，不会静默使用不一致的状态。

Combat Solver 的桥接源码位于 `combat/src/Api/NativeMctsSimulationApi.cs` 和 `combat/src/Search/CombatBeamSolver.NativeMcts.cs`。该目录保留独立仓库的原始未提交桥接修改，但主仓库提交会把源码作为普通文件纳入，而不是 Git submodule。

### Windows 构建与验证

在仓库根目录执行：

```powershell
& '.\scripts\native-worker.ps1' `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2' `
  -Mode verify
```

验证会重新构建 `combat/` 和 `tools/Sts2.NativeWorker`，并检查：原生 EndTurn 状态一致性、Purity 等选牌分支、IPC、连续思考和跨动作子树复用。性能基准使用：

```powershell
& '.\scripts\native-worker.ps1' `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2' `
  -Mode solver-mcts-benchmark
```

### Steam 已运行时启动 MCTS

安装会生成：

```text
D:\Steam\steamapps\common\Slay the Spire 2\mods\SlayTheModelAdapter\SlayTheModelAdapter.runtime.json
```

该文件保存 worker、项目、游戏包和导出目录。适配器优先读取进程环境变量，缺失时读取这个持久配置，因此不需要退出 Steam：

```powershell
& '.\scripts\windows.ps1' `
  -Action Install `
  -Policy mcts `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'

& '.\scripts\windows.ps1' `
  -Action Launch `
  -Policy mcts `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'
```

启动前只需要确保游戏进程已经退出；Steam 客户端可以继续运行。脚本通过 `steam.exe -applaunch 2868840` 启动游戏，游戏内 MCTS 仍使用独立 NativeWorker。不要同时启用 Combat Solver 自带的自动出牌控制器。
