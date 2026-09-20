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

目前游戏内合法动作枚举以“出牌、选目标、结束回合”为主。药水以及卡牌执行过程中的弃牌、发现等异步选择还没有完整接入。MCTS 核心也尚未替换游戏内的 `first-legal` 联调策略。

## 环境要求

当前安装与启动流程已在以下环境验证：

- macOS；
- Steam 版《杀戮尖塔 2》；
- 游戏版本 `v0.111.0`；
- .NET SDK `9.0.306`。`global.json` 允许滚动到同一 SDK 的更新 feature band。

Windows 操作说明根据当前游戏目录结构整理，但尚未在 Windows 机器上实际测试。遇到问题请在 Issue 中附上游戏版本、安装路径和完整日志。

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

## Windows 操作说明（未经测试）

> **注意：以下流程尚未经过 Windows 实机验证。** 路径和启动方式可能随 Steam 库位置、游戏版本或 Mod 加载器变化。建议先备份存档，并优先使用测试存档验证。

以下命令需要在 **PowerShell** 中执行。先在 Steam 中右键游戏，选择“属性 → 已安装文件 → 浏览”，找到包含 `SlayTheSpire2.exe` 的游戏根目录。默认目录通常是：

```text
C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2
```

如果 Steam 库位于其他磁盘，请修改下面的 `$GameDir`：

```powershell
$GameDir = "C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2"
$ManagedDir = Join-Path $GameDir "data_sts2_windows_x86_64"

Test-Path (Join-Path $GameDir "SlayTheSpire2.exe")
Test-Path (Join-Path $ManagedDir "sts2.dll")
```

两个 `Test-Path` 都应返回 `True`。完全退出游戏后，在仓库根目录构建 Mod：

```powershell
dotnet build src/SlayTheModel.Sts2.ModAdapter/SlayTheModel.Sts2.ModAdapter.csproj `
  -c Release `
  "-p:Sts2ManagedDir=$ManagedDir"
```

安装到游戏根目录下的 `mods` 文件夹：

```powershell
$ModDir = Join-Path $GameDir "mods\SlayTheModelAdapter"

New-Item -ItemType Directory -Force -Path $ModDir | Out-Null
Copy-Item "src\SlayTheModel.Sts2.ModAdapter\bin\Release\net9.0\SlayTheModelAdapter.dll" `
  -Destination $ModDir -Force
Copy-Item "src\SlayTheModel.Sts2.ModAdapter\SlayTheModelAdapter.json" `
  -Destination $ModDir -Force
```

只采集状态、不自动打牌：

```powershell
$env:SLAY_THE_MODEL_EXPORT_DIR = Join-Path (Get-Location) "artifacts\live-capture"
$env:SLAY_THE_MODEL_CAPTURE_HISTORY = "1"
$env:SteamAppId = "2868840"
$env:SteamGameId = "2868840"
Remove-Item Env:SLAY_THE_MODEL_LIVE_POLICY -ErrorAction SilentlyContinue

& (Join-Path $GameDir "SlayTheSpire2.exe")
```

启用 `first-legal` 自动战斗联调策略：

```powershell
$env:SLAY_THE_MODEL_LIVE_POLICY = "first-legal"
$env:SLAY_THE_MODEL_EXPORT_DIR = Join-Path (Get-Location) "artifacts\live-capture"
$env:SLAY_THE_MODEL_CAPTURE_HISTORY = "1"
$env:SteamAppId = "2868840"
$env:SteamGameId = "2868840"

& (Join-Path $GameDir "SlayTheSpire2.exe")
```

如果游戏首次启动时询问是否加载 Mod，请选择启用 Mod 的启动方式。与 macOS 一样，当前适配器只接管战斗，主菜单、角色、地图和奖励仍需手动操作。

Windows 日志通常位于：

```text
%APPDATA%\Godot\app_userdata\Slay the Spire 2\logs\godot.log
```

## 测试用策略：`first-legal`

这个名字表示“合法动作列表的第一项”，不是“画面中最左边的第一张牌”。每次决策时它会：

1. 枚举当前可出的卡牌及其合法目标；
2. 将结束回合排在其他动作之后；
3. 按玩家 ID、动作类型、卡牌内部 `CombatCardIndex` 和目标 ID 稳定排序；
4. 执行排序后的第一项；
5. 状态变化后重新枚举；没有可出的牌时结束回合。

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
