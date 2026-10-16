# 原生 Headless 终端 v0.1

本版用终端游玩 STS2 `v0.111.0`。后端加载本地正版游戏的程序集、资源包和原生场景，以 Godot `--headless` 运行。终端展示当前状态并提交原生操作，卡牌默认显示中文名和英文名。

## 启动

需要本地 STS2 `v0.111.0`、.NET 9 SDK、Python 3.10 或更高版本。Python 客户端只使用标准库。启动脚本先构建并准备独立宿主，等待原生初始化，再打开终端操作菜单。

macOS Apple Silicon，在仓库根目录：

```bash
./scripts/headless-macos.sh
```

Windows PowerShell，在仓库根目录：

```powershell
.\scripts\headless-windows.ps1
```

游戏位于其他磁盘时使用 macOS 的 `--game-app '/path/SlayTheSpire2.app'` 或 Windows 的 `-GameDir 'D:\SteamLibrary\steamapps\common\Slay the Spire 2'`。脚本核对 `contracts/sts2-v0.111.0.json` 中的原生 DLL 哈希，版本不符时停止。

想单独运行宿主、选择角色或进阶，可以开两个终端：

```bash
# 终端一，保持运行
./scripts/headless-macos.sh --server-only

# 终端二
python3 scripts/headless-play.py --new --character IRONCLAD --ascension 0 --language zhs
```

Windows 宿主对应 `-ServerOnly`，Python 命令使用已安装的 `python`。角色标识为 `IRONCLAD`、`SILENT`、`REGENT`、`NECROBINDER`、`DEFECT`；`--seed` 可指定原生种子，`--language eng` 切换英文。

macOS 一条命令带角色参数的写法：

```bash
./scripts/headless-macos.sh -- --character IRONCLAD --ascension 0 --language zhs
```

## 终端操作

- 输入菜单编号执行操作。战斗菜单列出出牌与目标、结束回合；药水先打开菜单，再使用/弃置及选择目标。
- 选牌逐张切换，再选原生“确认”；升级、附魔、变化的预览/返回继续遵循原生流程。
- `deck`、`draw`、`discard`、`exhaust` 查看牌组和牌堆集合；抽牌堆不展示抽取顺序。
- `s` 刷新，`h` 查看帮助，`q` 退出。默认启动脚本会结束它创建的宿主子进程。
- 菜单随状态更新，过期编号会被拒绝并刷新，不会自动重发旧操作。
- 进行中的测试局不能被 `new` 覆盖；需退出并重启宿主。当前未提供继续上局的终端入口。

地图显示公开节点与连线；普通事件显示当前选项；商店显示实际价格和商品说明；水晶球显示工具、可点击格、已揭示碎片与物品。详细接入范围和逐事件验证状态见[事件覆盖表](headless-event-coverage-v0.111.0.md)。

## 原生逻辑与界面边界

完整原生场景树保留在独立进程中，负责事件、异步选牌、战斗、奖励和转场。当前最高层界面由游戏的 `ActiveScreenContext` 判断。选牌回调、商店 `OnSelected`、水晶球格子回调等继续执行原生方法，不复制一套奖励或 RNG 逻辑。快速地图转场仍有旧页面短暂暴露的竞态，见下方长路径验证；自动客户端应等待新房间稳定，宿主侧仍需加入转场输入栅栏。

这是关闭图形窗口的整局宿主，仍需要游戏资源和原生场景、动画及异步任务。宿主初始化原生音频，因此终端游玩时仍可能听到游戏声音。它用于验证整局操作接口，尚不是高速自博弈模拟器；无完整界面战斗的实测速率和下一道整局性能门槛见[性能验证](headless-performance-gate-v0.1.md)。

运行文件和日志位于 `artifacts/headless/`。宿主使用独立的 `SlayTheModelHeadless` 用户目录和关闭 Steam 的原生启动选项；不会安装 Mod。测试 profile 解锁游戏内容并关闭首次操作教学，便于验证全部角色和事件。

macOS 存档目录为 `~/Library/Application Support/SlayTheModelHeadless`，Windows 为 `%APPDATA%\SlayTheModelHeadless`。这是独立的新 profile；原生首次跑局的遭遇与问号房规则仍生效，同种子不保证与已有多年进度的 Steam profile 得到相同路线内容。终端宿主和默认无 `NGame` 高速探针现都按游戏规则规范化输入种子，并使用同样的 epoch 解锁配置；两者的 profile 目录彼此独立。固定种子的涅奥、地图、首战 8 个决策点的可见抽牌、战后奖励候选、第一个自然问号事件 `SPIRALING_WHIRLPOOL` 两条选项结果及下一战斗入口已对齐；其他动作、事件和后续战斗的逐步等价性尚未验证，具体对照见[性能验证](headless-performance-gate-v0.1.md#同种子原生场景对照2026-10-08)。

## 程序接口与训练

终端使用仅绑定 `127.0.0.1:18777` 的 JSON 传输，没有网页或前端依赖：

- `GET /api/health`：初始化完成后可用。
- `GET /api/state`：最新公开状态、菜单和 `revision`。
- `POST /api/new`：`character`、`ascension`、`seed`、`language`。
- `POST /api/action`：当前 `revision` 和 `actionId`。

所有原生对象访问与操作都调度回 Godot 主线程；传输层只持有 JSON。接口不输出隐藏 RNG、未揭示格子内容或抽牌顺序。

这里的 JSON 是终端交互状态，**尚未接入整局训练 JSONL writer，也未接 SpireFormer 推理**。后续数据录制应复用 `HeadlessEpisodeRecorder` 和已定义的 decision → action → execution → reward 契约，不能把终端请求日志直接当作可训练标签。

## 验证

终端客户端的契约与显示测试：

```bash
python3 smoke/headless-play-client-smoke.py
```

2026-10-07，macOS ARM64 已通过原生进程＋真实终端客户端验证：

- 铁甲新局、涅奥奖励、完整地图展示和前往节点；开局奖励金币从 99 变为 249。
- 第一场 `NIBBIT` 战斗：痛击造成 8 伤害并施加易伤，后续打击造成 9 伤害；正确扣能量、结束回合、敌方行动及洗牌抽牌。
- 击杀敌人后燃烧之血使 HP 从 62 回到 68；卡牌奖励拿取成功，牌组从 10 张变为 11 张。
- 领取无色药水，战后弹窗按原生规则仅允许弃置；弃置后药水库存清空。
- 过期菜单返回 409，终端刷新且不重放旧动作。

上述实跑之后补了启动空状态保护、抽牌/地图切换的等待、费用展示、重复菜单去除，以及音频总线、完整资源预加载、原生脚本缓存和随机幕选择初始化。2026-10-08 又从新进程通过本机 API 对照固定种子的涅奥、第一地图节点及首战 8 个决策点，可见抽牌逐步一致。2026-10-09 同样用自动 API 脚本从两次新局分别领取相同战后奖励、进入自然 `SPIRALING_WHIRLPOOL`，验证 `Observe` 的 9 张附魔候选与一张 Strike 获得 `SPIRAL`，以及 `Drink` 的 HP 75→80；两分支与无 `NGame` 探针的最终牌组、HP、金币、遗物、药水一致。两边随后都进入 `(2,3)` 的 `CORPSE_SLUGS_WEAK`，敌人初始 HP 27/26、玩家状态与牌组一致。**最终版本仍未完整复跑人工终端客户端**，其他特殊事件与 Windows 也尚未运行验证。

### 2026-10-09 连续长路径

在 macOS ARM64 的独立宿主，用 `scripts/headless-long-path-smoke.py` 通过同一 loopback API 操作铁甲战士、进阶 0、输入种子 `STM-WHOLE-RUN-SPEED-1`。脚本仅按当前公开菜单采取简单动作，地图优先休息/宝箱/问号，战斗打可用牌并结束回合，战后普通奖励均跳过；它不是训练策略。一次连续原生测试局经过第 1–17 层，含 9 场战斗（最后一场为瀑布巨兽首领）、螺旋漩涡单卡选择、满屋芝士双卡选择、4 个休息点和 1 个宝箱及遗物领取，最后 HP 0，宿主返回 `status=finished, screen=defeat`。期间重启过测试脚本以修正双选牌策略，但**未重启宿主或测试局**；总轨迹 209 次接受的 API 动作，其中 24 次是旧脚本在双选牌界面来回切换同一张牌，另有一次状态版本过期的 409，经刷新后继续。宿主日志无 `HEADLESS_ACTION_FAILED` 或 `HEADLESS_CAPTURE_FAILED`。逐步原始记录在忽略文件 `artifacts/headless/long-path-trace.jsonl`。

复跑时启动新的独立宿主，再执行：

```bash
./scripts/headless-macos.sh --server-only
python3 scripts/headless-long-path-smoke.py --new --seed STM-WHOLE-RUN-SPEED-1
```

第一次不带转场等待的自动尝试暴露了一个**仍未修复的输入竞态**：提交首个地图节点后，接口曾短暂返回上一间涅奥房的“继续”，快速点击它使第 2 层地图出现而首战未发生。最终长路径脚本在每次地图提交后等待 2.5 秒，并要求状态版本稳定后再操作，因此该轨迹没有跳房。测试结束后对宿主发送 Ctrl-C，Godot 在退出清理阶段仍输出 `Unreferenced static string` 和 `libc++abi: terminating`；此错误发生在原生败局状态返回之后，退出流程也尚需修复。这个长路径证明终端宿主可一路操作到原生败局；它不证明快速连续输入安全、跨幕转场、胜局、其他种子/角色，或整局吞吐量。

### 2026-10-09 录制决策并在高速探针重放

另起一个独立原生终端测试局，`scripts/headless-agent-run.py` 按公开菜单状态选择并提交动作，保存 `artifacts/headless/agent-run-trace.jsonl`。原生终端在第 17 层瀑布巨兽败局结束，HP 0；244 个接受的动作及每次动作前公开状态均已保存。`WholeRunSpeedProbe.RecordedReplay.cs` 在无 `NGame` 场景的原生 worker 中按该轨迹重放，通过 169 个战斗动作和 16 次地图移动的状态核对，最终同样第 17 层 HP 0 原生败北。这验证此种子和此动作序列下的终端宿主与高速探针对齐，具体比较字段、重复 Defend 身份消歧和复跑命令见[高速探针验证](headless-performance-gate-v0.1.md)。该终端 JSONL 仅供原生行为对照，尚未接入训练 writer。

指定接口测试场景的命令（会显示测试标记，使用原生开发房间入口，不是自然整局训练数据）：

```bash
./scripts/headless-macos.sh --test-scenario crystal-sphere
./scripts/headless-macos.sh --test-scenario merchant
./scripts/headless-macos.sh --test-scenario fake-merchant
./scripts/headless-macos.sh --test-scenario transform
```

Windows 对应 `-TestScenario crystal-sphere`。其他支持项：`trial`、`upgrade`、`enchant`、`treasure`、`rest`、`event:EXACT_EVENT_ID`。普通游玩不传此参数。逐事件和逐分支的验证边界见事件覆盖表。
