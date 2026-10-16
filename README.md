# SlayTheModel

面向《杀戮尖塔 2》（*Slay the Spire 2*）的全知状态、无头战斗模拟与 MCTS 基线工程。

项目短期目标是实现一个可复现的全局 MCTS：游戏适配器负责读取并复制完整状态，局内搜索负责出牌、选目标和结束回合，局外搜索负责地图、奖励、商店、休息点与事件，最终由分层控制器完成整局决策。

项目的长期目标是训练一个杀戮尖塔2专用的神经网络，希望能适配各个版本。结合安东尼现在的更新频率和更新效率，目前想先在各个版本中跑通基本MCTS，再在不同版本下测试神经网络的可行性

## 开发进度（2026-09-28）

- 新增局外决策系统，将局内出牌与地图、奖励、事件、商店、休息点和宝箱等局外操作分离；
- 完成第一版局内、局外 `first-legal`，已经能够作为确定性的整局自动化基线；
- 接入 Combat Solver 无头模拟后端，由独立 NativeWorker 为本项目的 ReplayMcts/UCT 提供可复制战斗状态；
- 打通“读取状态 → 抽象决策状态 → 生成合法动作 → 执行动作 → 等待游戏同步 → 继续决策”的局内外闭环。
- 完成 SpireFormer 第一版离线训练工程：统一局内/局外轨迹，提供 Tiny、Small、Medium、Large 四档模型、BF16、DDP、checkpoint/resume 与版本化 tensor shard。
- 新增独立的人类整局轨迹采集 Mod：同时记录局内、局外决策，区分 no-SL、SL 与未知信息模式，按局生成可恢复、带哈希链的本地 JSONL，并在终局派生紧凑事件视图；当前不上传数据。

> 当前仓库仍处于早期开发阶段。`first-legal` 主要用于接口联调和大规模自动化测试，不是 MCTS，也不代表最终模型强度。

## 当前实现

- 不依赖第三方包的通用 UCT/MCTS 核心；
- 针对 STS2 `v0.111.0` 固定的 ABI 探针与兼容性契约；
- 与游戏程序集解耦的状态、动作和 JSON 协议；
- 将局内可见状态与完整跑局上下文分开；金币因会影响战斗效果，也进入局内观察；
- 游戏内只读状态采集，可导出稳定决策点和原生校验和；
- 带状态指纹校验的动作桥，可执行出牌、选择目标和结束回合；
- 无头 smoke test 与采集文件检查工具；
- 第一版局内与局外 `first-legal` 自动操作，用于验证整局控制闭环并运行自动化基线；
- [SpireFormer](model/spireformer/README.md) 离线模型与训练栈，以及先 live、后 headless 的[训练数据 v1 规划](docs/spireformer-training-data-v1-plan.md)。
- 与自动操作解耦的 `SlayTheModelDataCollector`，用于采集人类整局轨迹；使用方式和格式见[人类整局轨迹采集 Mod v0.1](docs/human-data-collector-v0.1.md)。

目前游戏内合法动作枚举以“出牌、选目标、结束回合”为主。药水与完整的分支决策协议尚未接入。单人 first-legal 已通过原生选牌接口自动处理动作内的手牌/网格选择，其他特殊交互仍需验证。另有显式启用的实验性 `mcts` 模式，使用独立原生 worker 和 Combat Solver 模拟后端；`first-legal` 仍是独立联调策略。SpireFormer 当前能够离线训练，但尚未接入游戏实时策略参数；`RunMode=train` 仍只是 Mod 侧的预留入口。

## Spire Codex 公开回放归档

2026-10-10 曾从 Spire Codex 公开接口归档 14,848 个回放 hash，其中 14,794 份可解析；`v1.2.1` 录制模组的回放有 2,575 份。应用户要求，现已删除其他回放、下载缓存和早期样本，**只保留 166 份严格候选**，放在 Git 忽略目录 `artifacts/reference/spire-codex/bulk/v1.2.1/<角色>/`。筛选条件：五原版角色、录制模组 `v1.2.1`、游戏 `v0.111.0`、已加载模组恰为 `BaseLib` 和 `SpireCodex`、录制状态 `complete`、标准单人、无 modifiers、回放头开局 `reloads=0`。五角色数量为铁甲 31、静默 37、故障 25、亡灵契约师 57、储君 16。

总清单在 `bulk/v1.2.1/manifest.jsonl`；按角色清单在 `bulk/v1.2.1/filtered/strict-by-character/<角色>/manifest.jsonl`；`bulk/summary.json` 记录筛选标准和来源总量。每条清单的 `archive_path` 指向保留的回放，并记录 SHA-256。回放可能含 `draw_order` 等隐藏未来信息；这些文件仍须审计局中读档、决策覆盖与 no-SL 语义，不能直接当本项目训练 JSONL。历史下载脚本仍保留，但会拒绝向这个已精简的目录重新下载；如需重新归档，必须显式指定其他 `--output`。

`python3 scripts/convert-spire-codex-replays.py` 会把这 166 局转换到忽略目录 `artifacts/reference/spire-codex/reconstructed-v1/`。2026-10-11 全量结果为 56,160 个动作步骤。7,537 个局外步骤里有 7,341 个候选与选择结构完整；保守排除 238 个无法证明连续性的恢复段后，安全 BC 索引保留 4,603 步。严格语料均为 `v0.111.0` 无 modifier 标准局；header 未直接记录的初始金币按原生规则恢复为 99，并由 134 个后续可逆金币锚点逐局验证。48,623 个战斗步骤已去除隐藏顺序并重建公开状态，排除恢复段后有 24,856 个可进入后续原生顺序重放。战斗原日志不含输入时完整合法动作集合，因此转换器明确禁止它们直接进入 BC。输出逐局保存源/结果 SHA-256，并递归核对 seed、RNG、未来抽牌顺序、时间、本地化文本和原生实例 ID 均未泄漏。

原生 `v0.111.0` worker 已完成五个角色各一场完整首战，并另对铁甲样本 `a8d7ab6d08211e91` 从正常新局开始连续重放首战、原生战后奖励和第二战；共 93 个战斗决策，每个输入边界都重新投影真实 observation、完整合法动作和实际动作，7 场战斗均到达原生胜利。连续样本的首战 11 步、第二战 12 步全部一致，期间原生领取 12 金币和 `DEXTERITY_POTION` 并跳过卡牌。实验同时证明仅恢复 RNG counter 不能代表完整 RNG 状态，后续战斗必须顺序保留原生状态。结束回合日志只用于驱动重放，训练 observation 来自执行前的原生投影。内部计划含 seed/RNG/抽牌顺序，但报告以 SHA-256 绑定计划，训练 loader 只输出 policy 可见字段。

`python3 scripts/assemble-spire-codex-dataset.py --native-replays artifacts/reference/spire-codex/native-replay-pilot` 已把 4,603 个安全局外步骤和上述 93 个战斗步骤接入 SpireFormer tensor shard v2：train 126 局/3,788 步，val 17 局/497 步，test 17 局/411 步；三个 split 均含五角色且 episode 不重叠。当前忽略目录 `artifacts/reference/spire-codex/tensor-bc-v3/` 约 881 MB，dataset ID `afecb42485a472e6f97ce8d6baa08650`，使用 512 词上限和 FP16 缓存，训练和评估时提升为 FP32。所有 shard 已做哈希重读；Tiny 已完成一次 CPU 优化器更新，evaluator 对 val/test 都确认 `episode_split_verified=true`。本轮还修正 evaluator 未提升 FP16 shard 输入而导致 Set Transformer dtype 不一致的问题。RTG 仍为零占位、value target 缺失；扩大后续战斗覆盖仍需顺序重放此前所有会消耗 RNG 的战斗和局外结果。格式、边界与验证记录见 [重建格式 v1](docs/spire-codex-conversion-v1.md)。

## 原生 Headless 终端

新增可交互的原生整局宿主 `tools/Sts2.HeadlessHost`，界面使用终端，卡名默认中英双语。它加载本地 STS2 `v0.111.0` 的原生逻辑与场景，以 `--headless` 运行；地图、战斗、事件、商店、奖励和选牌走原生入口。

```bash
# macOS Apple Silicon，在仓库根目录
./scripts/headless-macos.sh
```

```powershell
# Windows PowerShell，在仓库根目录
.\scripts\headless-windows.ps1
```

需要 .NET 9 SDK、Python 3.10+ 和匹配版本的本地游戏。输入菜单编号操作，`s` 刷新，`deck/draw/discard` 查牌，`q` 退出。运行使用独立测试 profile。启动参数、实现边界和验证状态见[终端说明](docs/headless-terminal-v0.1.md)及[事件覆盖表](docs/headless-event-coverage-v0.111.0.md)。同一原生测试局已用 `scripts/headless-long-path-smoke.py` 从第 1 层连续走到第 17 层首领败局，覆盖战斗、单/双选牌事件、休息点和宝箱；快速地图转场的旧页面输入竞态仍待修复，详见终端说明。该宿主尚未接入训练轨迹 writer 或模型推理。训练所需的高速整局 runner 有独立的[性能验证门槛](docs/headless-performance-gate-v0.1.md)：无完整界面的原生战斗基准，以及历史固定种子到第 7 层败局、商店购卡/删牌、休息回血和宝箱遗物分支已跑通。默认高速探针按游戏规则规范化种子、生成与终端宿主相同的隔离 profile 解锁状态，并在 TestMode 中启用正常游戏的发现顺序规则；同种子涅奥、地图、首战 8 个决策点的可见抽牌、战后奖励候选、首个自然问号事件 `SPIRALING_WHIRLPOOL` 的 `Observe` / `Drink` 结果及下一场 `CORPSE_SLUGS_WEAK` 入口已对齐。显式设置 `STS2_PROBE_LONG_PATH=1` 后，规范化种子的无场景探针也已连续到第 17 层瀑布巨兽败局；第 14 层满药水槽时，探针合法跳过新药水，验证原有药水不变、奖励集合完成；TestMode 自动领奖在跳过前仍记一次日志错误，探针保留 warning。进一步由 agent 控制原生终端宿主打完同种子的一局并记录 244 个动作，在高速探针重放后，16 次地图移动、169 个战斗动作及第 17 层败局终点通过状态核对；重复基础牌的跨进程身份需要按该轨迹消歧。原始终端轨迹不是训练 JSONL。通用入口现可接受任意规范化种子，已检查的 20 个种子全部以 `error=null` 完成原生终局并覆盖 20 种非涅奥事件；第 4 个种子打赢第一幕 `VANTOM_BOSS`，经原生 `EnterNextAct()` 和第二幕 `MapRoom` 进入第 18 层首战后败北，全程保持 `gameSceneLoaded=false`。可重复选项事件 `ABYSSAL_BATHS` 的退出循环也已修复。人类 journal 重放入口已将现存 A0 胜局 `1ddd1912...` 从涅奥连续重放到第三幕第 45 层商店的 step 700，覆盖 21 场战斗、事件、商店、休息点、宝箱和两次跨幕；输出 `verifiedThroughGlobalStep=700`、`gapBoundaryVerified=true`、`error=null`、`gameSceneLoaded=false`。源 journal 在 step 701 有商店采集 gap，探针在核对该步 observation 后停止，不猜测缺失动作。另一条无 gap A0 败局 `32a382...` 的 228 个决策已全部重放，第 14 层原生败局终点通过，`terminalOutcomeVerified=true`。第三条 A0 胜局 `2d9fc925...` 已连续核验 step 0–494，并在 step 495 的药水缺口前停止；其中 Crystal Sphere 的三次翻格、棋盘物品位置、30 金币、满槽药水取消和退出流程均与原生状态一致。当前仍缺完整胜局终点和实际训练吞吐量。

2026-10-14 新增的两条连续 A0 败局也已在同一无场景入口完整复跑两次。`a09f25fa...` 的 233 个决策全部对齐，包含 156 个战斗决策、77 个局外决策、9 场战斗和一次合法取消，最终在第 17 层 `WATERFALL_GIANT_BOSS` 死亡；`d9c27368...` 的 226 个决策全部对齐，包含 156 个战斗决策、70 个局外决策和 9 场战斗，最终在第 17 层 `SOUL_FYSH_BOSS` 死亡。两局最近重复计时分别约 1.39 秒和 1.05 秒，均为 `terminalOutcomeVerified=true`、`error=null`、`gameSceneLoaded=false`。源日志没有附玩家 progress；探针以第一局已确证的遭遇历史恢复第二局的原生发现顺序，并明确把该输入写入报告。两份日志的 `information_mode=unknown`、`no_sl_expected=false`，重放成功本身不把它们升级成 no-SL 训练数据。

## SpireFormer 运行规则

当前首版奖励为 `whole-run-act-v1`：三幕胜利分别 +1/+2/+3，非 Boss 战按净 HP
变化比例结算，每幕 Boss 前统计当前升级牌与遗物，第三幕另加血量比例，败北
追加 −10。奖励在训练转换阶段从只读 JSONL 中离线计算；以后调整现有 HP、牌组、
遗物、幕数和胜负公式只需重建 tensor，不必重新采集。现有 6 局 no-SL 日志已重建
4,021 个安全步骤（train 2,738 / val 781 / test 502）；训练集含 3 胜 1 负，新采集器的精确边界作为更强
审计证据保留，不进入模型特征。三个 unknown 来源的日志仍因信息模式/来源证据排除。
Tiny 分幕 RTG 试验已训练 1,000 步；真实 RTG 条件下整局隔离 val/test top-1 为
49.68%/53.98%，但相对零 RTG 只高约 0.51/0.20 个百分点，尚未证明稳定条件控制。
完整规则、命令和实机验证边界见 [分幕奖励说明](docs/spireformer-act-reward-v1.md)。

SpireFormer 是独立的 Python/PyTorch 工程，目录位于 `model/spireformer`。它不随 .NET Mod 构建，也不通过 `scripts/macos.sh` 或 `scripts/windows.ps1` 启动。当前没有预训练权重，下面的 smoke test 只验证模型能否在目标硬件上完成数值有限的前向或反向计算，以及实际峰值显存；它不能代表策略已经会打牌。

建议使用 Python 3.11 或 3.12，并先按照 [PyTorch 官方安装选择器](https://pytorch.org/get-started/locally/)安装支持 RTX 5090 的 CUDA 版本。不要为了满足本项目依赖而手动降级到旧 CUDA wheel。

Windows PowerShell：

```powershell
cd model\spireformer
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# 先按 PyTorch 官网给出的命令安装 CUDA 版 torch，再安装本项目
python -m pip install -e ".[test]"
```

macOS / Linux：

```bash
cd model/spireformer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
# 5090 机器先按 PyTorch 官网给出的命令安装 CUDA 版 torch
python -m pip install -e '.[test]'
```

先确认 Python 看到的确实是 5090，并且支持 BF16：

```bash
nvidia-smi
python -c "import torch; print('torch=', torch.__version__); print('cuda=', torch.version.cuda); print('device=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else None); print('bf16=', torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False)"
```

然后运行基础测试并查看四档模型的精确参数量：

```bash
pytest -q
spireformer presets
```

5090 建议按照从小到大的顺序测试。前向推理不会创建梯度；单步训练只执行 forward、loss 和 backward，不创建 AdamW 状态，因此它用于验证计算图，不等价于完整训练显存：

```bash
spireformer smoke --preset tiny --device cuda --precision bf16 --mode train
spireformer smoke --preset small --device cuda --precision bf16 --mode train
spireformer smoke --preset medium --device cuda --precision bf16 --mode train
spireformer smoke --preset large --device cuda --precision bf16 --mode inference
```

命令成功时会输出 JSON，其中应满足 `finite=true`、`device` 为 `cuda:0`，并包含输出形状、耗时与 CUDA 峰值显存。出现 OOM 时先记录失败的 preset 和峰值，再减小 `--batch-size`、`--steps`、`--entities` 或 `--actions`；不要据此修改模型默认结构。

真正训练使用 `spireformer train --dataset ...`，要求输入版本化 tensor shard。人类 live 采集器提供原始 JSONL；`spireformer assemble` 默认生成 BC-only shard，也可用 `--reward-scheme whole-run-hp-safe-v1` 为完整、经审计的 no-SL 整局生成 HP 与终局胜负条件下的真实 RTG。磁盘 schema 仍为 v2；value target 仍缺失，训练使用 `--value-weight 0`。已有 Tiny 的 200 步 CPU checkpoint 属于旧 BC-only 模式。游戏内 `spireformer` policy 尚未接入。方案、命令与指标见[SpireFormer README](model/spireformer/README.md#整局-hp-rtg-模式)。5090 工作重点仍是模型执行、BF16、显存边界和环境兼容性。Large 约 2.04B 参数，当前 AdamW + DDP 路径需要 FSDP、ZeRO 或 offload。

**整局 HP RTG 首轮产物已作废。**旧胜局 `433d5532920444a1afac0716251e12c4` 的 global step 270 在选牌动作后出现 `potion_count_delta=-1`，但没有独立的局外用药或弃药决策。新局 `ec731...` 的 step 79/608 也出现药水减少被领奖励/继续动作吸收，证实仅靠事件链和原采集器的 `value_target_valid=true` 仍会漏掉局外操作。此前由 `433d...` 胜局与 `32a...` 败局组装的 `artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1`，及基于它训练的 `artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1` **不得继续用于正式训练、续训或评估**。两局组装、Small CPU/FP32 20 步和训练集事后 top-1 52.91% 仅保留为旧代码链路曾运行的历史记录，不是可靠的数据或策略证据。`32a...` 未见同类药水减量，但单独只有一局败局，不能代替胜败数据集。

2026-10-02 最新三局 `2085af58...`、`1ddd1912...`、`2d9fc925...` 均为 no-SL 铁甲胜局，JSONL 哈希链完整；可分别提取 922、781、502 个 BC-only 步骤。但三局都有显式缺口，均不能用于整局 HP RTG：`2085...` 有 3 次重叠的局外药水操作，`2d9...` 有 1 次购买遗物期间的弃药，`1ddd...` 有 1 次商店购买点击未匹配合法动作。后者前后金币、牌组、遗物和药水未变化，但旧日志没有目标与原生返回值，不能事后判定为无效点击。Rewards 顶层的独立弃药在两局中各成功结构化一次；局外用药和重叠操作尚无成功实机样本。旧 JSONL 不回填。

当前工作树继续提供有限的局外药水结构化支持。Rewards 顶层且药水栏、持有槽和合法集可核对的独立操作已得到上述两次实机证据；本轮又为快速重叠点击增加受控边界：若有未结父动作，它必须唯一且已被原生接受；同时须没有选择器、执行器空闲、原生动作队列为空，并能核对顶部 Rewards 或商店页面及药水栏。满足这些条件时，药水点击可先结算父步，再冻结下一独立决策并绑定同一个原生 `GameAction`。其余情况保留 `coverage_gap`，记录分项阻挡原因，不生成该动作的 BC 标签。商店未匹配购买延后核对原生 `Task<bool>`：只有点击和结果两个边界都稳定、没有其他待处理操作、明确返回 `false` 且状态和库存不变，才作为诊断而非缺口；成功或无法核实的点击仍记缺口。新重叠边界和商店结果处理尚未安装或实机验证。原始旧局、作废 shard 和 checkpoint 保持原样；转换器仍拒收不完整整局 RTG。

## 人类整局数据采集

采集器是独立 Mod，不依赖 MCTS 或 `first-legal`，也不会控制游戏。玩家手动完成单人跑局时，它把局内出牌、药水、结束回合和局外路线、事件、奖励、商店、休息点、选牌等操作写到同一个 episode；游戏结算后，文件从 `.jsonl.partial` 原子发布为 `.jsonl`。当前没有上传功能。

原始 `episodes/*.jsonl` 继续作为审计与训练的唯一事实源。发布完成后会自动在 `episodes/_compact/*.compact.jsonl` 生成便于阅读和分析的派生事件流：合法动作和选择标签仍逐步保留，重复 observation/context 改用经过逐步还原核验的差量，重复的手动输入证据改为步骤引用。当前 6 份历史实机日志离线回填后合计减少 81.1%；自动生成尚待下一局实机验证。格式与边界见[采集器说明](docs/human-data-collector-v0.1.md#紧凑事件视图)。

每局 JSONL 首行记录采集时间、角色、进阶、原生开局时间、种子，以及可取得时的 Steam 昵称和 Steam ID。身份与种子只作本地溯源和复现信息，不进入训练观察或模型输入。

新发布的文件名使用 `SteamID_角色_A进阶_UTC时间戳_episodeID.jsonl`，便于按玩家和跑局查找；Steam 不可用时用明确占位。末尾 episode ID 防止同一时间的跑局撞名，临时 `.partial` 文件仍按 episode ID 保存以便恢复。历史 UUID 文件保留原名且仍可读取。

macOS 快速开始：

```bash
./scripts/collector-macos.sh --action test
./scripts/collector-macos.sh --action install \
  --dataset-dir "$PWD/artifacts/human-dataset" --information-mode no-sl
./scripts/collector-macos.sh --action launch \
  --dataset-dir "$PWD/artifacts/human-dataset" --information-mode no-sl
```

Windows PowerShell 快速开始（在仓库根目录执行；先完全退出游戏并打开 Steam 客户端）：

```powershell
.\scripts\collector-windows.ps1 -Action Check
.\scripts\collector-windows.ps1 -Action Test
.\scripts\collector-windows.ps1 -Action Install -InformationMode no-sl
.\scripts\collector-windows.ps1 -Action Launch -InformationMode no-sl
```

Windows 脚本需要 PowerShell 5.1 或更高版本、.NET 9 SDK 和 Steam 版 STS2 `v0.111.0`。`Check` 检查游戏与依赖路径，`Test` 运行采集器 smoke test，`Install` 构建并安装独立 Mod，`Launch` 通过 Steam 启动游戏；首次进入游戏时如提示 Mod，请启用 `SlayTheModelDataCollector`。默认数据目录是仓库的 `artifacts/human-dataset`：进行中的局保存在 `episodes/_open/*.jsonl.partial`，结算后发布到 `episodes/*.jsonl`，紧凑视图写到 `episodes/_compact/*.compact.jsonl`。要改用其他目录，请在 `Install` 和 `Launch` 两条命令中都加 `-DatasetDir 'D:\sts2-human-dataset'`；找不到游戏时两条命令也可加 `-GameDir 'D:\SteamLibrary\steamapps\common\Slay the Spire 2'`。Windows 游戏内采集尚未实测。

不主动回档的跑局使用 `no-sl`；允许主动读档回退时，把安装和启动命令中的模式都改为 `sl`；不确定时改为 `auto`，不要把未知数据误标为 no-SL。若同时安装自动控制 Adapter，采集人类示范时应将其局内和局外策略都设为 `manual`。2026-10-15 新增可选的逐动作来源桥：同时更新 Adapter 与 DataCollector 后，实际自动提交记录 `native-mcts`/`first-legal`，MCTS 的原生 checkpoint 教师身份单独审计；没有来源证据的自动化域仍为 `observed-automation`。隔离原生进程已验证两张防御、头槌和弃牌选择的 4 组 journal 事件全部保留明确 MCTS 来源且无 gap；可见整局仍待实机验收。完整的配置、目录结构、恢复语义和 v0.1 覆盖边界见[采集器说明](docs/human-data-collector-v0.1.md)。

分幕奖励训练前可用 `python scripts/audit-act-reward-data.py artifacts/human-dataset/episodes --allow-policy native-mcts` 检查原始日志。当前 6 局 no-SL 旧日志可由通用事实离线重建奖励，合计 4,021 个安全步骤；最新 `f0006360…` 铁甲 A0 胜局有 562 个决策，但模式为 unknown、策略来源证据不足且有两处选牌 gap，因此仍不可训练。改变已记录事实上的奖励公式不需要重录；补采只用于取得旧日志没有的事实或合格的 no-SL/MCTS 来源证据。规则和接入见[分幕奖励说明](docs/spireformer-act-reward-v1.md)。

手动战斗训练步骤以**原生点击入口瞬间的游戏内部状态**为准：手牌、抽牌堆和弃牌堆按当时内部集合记录，合法动作从同一状态构造；抽牌动画是否已经把牌画到手上不作为采集门槛。这样 live 与未来 headless 使用同一观察语义。已排队的同一张卡不会重复进入合法动作；实际选择仍须匹配本次手动入口提交的同一个 `GameAction`。当前 live collector 产出的战斗 observation v5 为每张内部 Hand 卡从原生 `CardModel` 计算当前能量、星星与 X 费用；普通手牌的 `display.description=null`、`dynamic_values=[]`，不扫描 UI holder 或记录卡面动画进度。选择器候选的 `display` 仍保留原来的可见卡面语义。泛协议投影和当前 headless writer 仍允许 v5 手卡 `display=null`；未来 headless runner 须提供等价费用投影。新边界尚未安装或实机验证。

采集器现在写 `whole-run-v2` 奖励：成功动作在下一个可靠决策边界、排队的下一条原生手动动作开始执行前或终局边界结算。早期 `whole-run-v1` 文件保留为原始审计记录；其 reward 不可当作新版的整局回报目标。离线转换器的 HP RTG 模式使用其中经核验的 `hp_delta`、终局胜负和决策时生命值；不训练独立价值函数。

训练转换器按事件哈希链、动作提交、原生执行结果及后到的缺口筛选逐步标签，并按 episode ID 隔离训练/验证/测试；原始 JSONL 不改写。默认 BC-only 模式的 `return_to_go=0` 仍是占位。新增的 `whole-run-hp-safe-v1` 令 `H₀` 为开局最大生命、`q(H)=clip(H/(0.5H₀),0,1)`，每次真实生命变化记 `0.2×Δq`，终局胜利加 `1`、败北加 `0`，折扣 `γ=1`。每步 RTG 以该决策实际观察到的生命值计算：`terminal+0.2×(q(H_final)−q(H_decision))`。这样超过初始最大生命一半时不再为回血加分，也不单独奖励前两幕离幕高血量。value target 仍关闭。首轮两局 RTG 命令和 BC-only 四局 allowlist 均为历史记录，见[SpireFormer README](model/spireformer/README.md#从人类-jsonl-到训练-shard)；前者已作废，后者原始文件目前不在数据目录。旧版压缩药水槽位即使索引在观察中存在，也可能指向另一瓶药；转换器会对照同一步 run context 中完整的槽号与模型 ID，发现不一致便排除该步。使用其他旧局前仍应查看逐局排除报告，不能只凭 `value_target_valid=true` 放行。

先前实机文件 `9ecfc38a6d1545a6afbf08c1576e0e1f.jsonl` 为胜利，共 5065 条事件，序号和 SHA-256 链完整；873 个已提交动作都有执行结果，870 个成功动作都有 reward，611 次原始手动输入都有原生结果。80 次快速点击成功冻结 `queued_legal_set`，临时生成卡的 `Index` 选择也有成功关联。整局仍有 35 个采集缺口，因此是 `incomplete`、`value_target_valid=false`：14 次卡牌奖励的 `SACRIFICE` 替代选项、7 次回合开始阶段的快速出牌，以及 7 次 Gambling Chip 多选和它们对应的 7 次未结构化原生回执。旧 JSONL 保持不变；细节见[采集器说明](docs/human-data-collector-v0.1.md)。

此前一局已在同一目录发布为 Steam ID、角色、进阶、UTC 开局时间和 episode ID 命名的正式文件（episode ID `39445f716b8d4dc591ed9700ee8be3db`）。该局胜利，832 个提交动作都有执行结果，但还有 5 次 `manual_combat_action_during_pending` 快速输入缺口，整局仍为 `incomplete`、`value_target_valid=false`。

此前针对回合开始阶段的点击增加了专用 `Start` 候选冻结，旧版按原生 `CanPlay`/目标、药水可用性和结束回合按钮状态记录点击时合法动作，再与提交的同一 `GameAction` 匹配。旧版额外要求 UI holder 与内部 Hand 完全对应，导致动画期间的真实快速出牌可能被拒绝；当前本地改动已取消这个 UI 门槛，`Start` 与普通 `Play` 都按点击时内部状态冻结观察和候选；`Start` 只列内部 `CanPlay` 卡与可用药水，不列 EndTurn。v0.111.0 的正常 `Start` 阶段结束回合按钮尚未启用；若异常收到 `Start` EndTurn，按不在合法集记 gap。旧轨迹仍按当时旧规则解释：此前一局（episode ID `435800f8166e4d6ca309ce2ad251fc94`）已实机记录 4 次 `Start` 出牌，均形成独立决策、执行结果和奖励；全局 730 个决策配对完整、无 `coverage_gap`，终局胜利且 `value_target_valid=true`。新边界尚待实机验证，旧 JSONL 不会回填。

此前 `36df5d1b...` 跑局有 4747 行，事件哈希链和 835 个 decision/action/result 配对完整，终局胜利；但 20 个缺口使整局 value target 无效。其中 17 个是原生单卡 `Index` 回执与已冻结选择器 ID 晚绑定造成的误报，另有 1 次快速输入与 1 组多卡选择的真实缺口。该局首次验证了战斗观察 v2 的金币、充能球容量和敌意图，也暴露普通 `Play` 所选卡缺少界面 `display`。随后修复了被点击卡的可见节点核对与选择器关联，并将战斗观察升至 v3。旧 JSONL 保持原样。

先前一局（episode ID `59261c11694548228f801a8e6ea7970d`）有 4842 行，事件序号与 SHA-256 链完整；857 组 decision/action/result/reward、585 组手动输入/结果全部配对。482 次实际出牌的所选卡均有 `display` 和说明；8 次 `Start` 输入（含 2 次用药）成功结构化，3 次原生单卡 `Index` 回执均关联成功。战斗与局外观察中的 v3 遗物展示字段分别覆盖 6663/6663 和 2549/2549 个遗物实例。该局胜利，但 3 个局外选择缺口（开局卡包、事件选 2 张牌、事件移除 3 张牌）使 `completeness=incomplete`、`value_target_valid=false`。原始 JSONL 保持不变。

先前一局（episode ID `fcbb45909a9044f6b696695c35439b54`）有 4200 行，事件序号与 SHA-256 链完整；750 个 decision、749 组提交/执行结果、747 个成功结果的 reward，另有 2 个正常取消。491 次手动输入都有原生结果。该局胜利，但 5 个缺口使 `completeness=incomplete`、`value_target_valid=false`：1 次回合开始时无法冻结可见候选的快速出牌，1 次局外二张选牌的原生 `Index` 回执误判，以及 3 次尚未覆盖的 Crystal Sphere 事件小游戏交互。二张选牌已记录候选和 decision，但因回执误判没有可用动作标签；工作树现接受 `Index` 与 `Indexes`，修复后尚未实机验证。404 次已提交出牌的所选卡均有 `display` 和说明；战斗遗物 5048/5048、局外遗物 2179/2179 个实例有展示字段。原始 JSONL 保持不变。

先前一局（episode ID `dd28da34ecaf4dcda4c0abbcf5ae3bf9`）有 1590 行，279 组 decision/action/result/reward 和 199 组手动输入/结果全部配对。两次 `Start` 快速出牌及一次开局卡包选择成功结构化；161 次已提交出牌的所选卡有 `display` 和说明。该局战败，唯一缺口是 Gambler's Brew 触发的战斗内多选：原生记录选了 4 张，但采集时的旧代码没有为该子选择提供完整合法集合和动作标签。父药水步骤虽有结果与奖励，其完整转移不能作为可靠监督。整局为 `completeness=incomplete`、`value_target_valid=false`。本局没有再次触发局外二张选牌或 Crystal Sphere，故不能用它验证修复或认为这些路径已解决；原始 JSONL 保持不变。

随后一局（episode ID `4b3d120ce918402c936238fef818ab46`）有 2822 行、501 组完整的 decision/action/result/reward 和 335 组手动输入/结果；无 coverage gap，终局 defeat，采集器标为 `complete`、`value_target_valid=true`。但语义审计发现 359 个战斗决策中 116 个药水观察槽号被压缩，106 个合法动作集合含无法由观察槽号正确寻址的药水动作，4 次实际用药（global step 207、412、495、499）直接选中了观察中缺失的槽。本局 24 次战斗选牌全为单选，未验证新的 Gambler's Brew 多选路径。修复版从原生 `PotionSlots` 保留真实槽位并校验动作引用，已由后一局实机验证。旧 JSONL 不改写；同一步 `context.run_context.potions` 保有正确槽号，训练转换器必须先核对并修正特征或过滤受影响步骤，不能只凭 `value_target_valid=true` 判断观察正确。

只读历史审计可运行 `python3 scripts/audit-collector-potions.py`；退出码 `2` 表示发现错位或无法核对，`--json` 可列出完整 global step。对当前 17 份正式文件的复核发现，7 份的 748 个战斗决策在观察与同一步 run context 的药水槽号/模型 ID 上不一致；其中 706 个决策的合法用药动作受影响，16 个实选用药动作受影响，0 个无法核对。真实药水槽号非连续本身不是错误：另一些新局保留了稀疏槽位且两处观察一致。脚本和 BC-only 转换器均不修改原始哈希链；转换器逐步过滤上述不一致，使用旧局前仍应查看排除报告。

当前工作树把局内和局外多卡统一为“候选牌列表 + 一个合法选择模板 + 提交时的真实集合”：局外 observation v5 的 `card_selection_options` 保存候选，局内 `active_choice.cards` 保存候选；`action_submitted.selected_action` 保存具体选中卡。20 张选 3 张也只需 20 个候选 token 和一个模板，不再枚举 1350 个组合。单卡与卡包路径保留原有语义；局内多选继续核对人工确认、selector Task 和 `CombatCard` 回执，局外多选继续核对原生候选、点击、最终确认、Task 和回执。`TO_TRANSFORM` 的 `NDeckTransformSelectScreen` 现从原生 `CardSelectCmd` 过滤列表/选择器 `_cards` 取得候选与 min/max，不要求动画中的 UI holder 可见；新路径已通过 build、collector smoke 和独立 Harmony ABI 检查，尚未实机验证。旧 `4be...` 和 `4177...` 的变牌缺口不能回填。旧枚举版的涅奥之怒与 `PURITY` 有实机证据，新模板版及 Gambler's Brew 手牌多选尚未实机验证；历史 JSONL 不回写。局内观察 v5 的普通手牌费用取内部 `CardModel`；选择器展示、敌人意图与遗物展示仍按各自原有的可见性规则保存。详见[采集器说明](docs/human-data-collector-v0.1.md)与[训练数据契约](docs/spireformer-training-data-v1-plan.md)。

最新铁甲胜局的 97 次烤面包手套单卡选择都记录了候选和所选牌，且所选原生卡 ID 与游戏回执逐次一致；旧采集器未把回执关联到选择器，故仍有缺口、整局 value 无效。当前本地修复从内部 Hand 按原生筛选条件冻结手牌选择候选；`CombatCard` 回执的原生 choice ID 缺失时，只在同一战斗和父动作下存在唯一未绑定选择、有人类输入证据、选择器 Task 已完成且所选卡与回执完全一致时关联。同一父动作出现后续选择器时，旧选择不再参与该兜底，包括新选择器未能冻结的情况；原生 ID 预留被 guard 忽略会留下只读诊断。`active_choice.choice_id` 可能是合成的协议标识，不能直接用作原生执行 ID。候选卡面的 UI `display` 仍为可选展示字段。新代码尚未安装或实机验证，旧 JSONL 不回填。

战斗内选牌的候选卡现在还可记录选择时可见卡面的说明与费用，按原生卡对象身份核对；未取得唯一可见节点时保持 `display=null`，训练转换器应保留缺失掩码。该展示补充尚待实机验证。

未来的 headless runner 可通过游戏无关的 `HeadlessEpisodeRecorder` 写入同一 `CollectorStore`、`EpisodeSession` 和 JSONL journal；`source=headless` 只表明来源，不改变观察、模板动作、具体集合或奖励事件契约。战斗多选应由 headless 的 `CardSelectCmd` 构造同样的协议状态；Crystal Sphere 应由自身公开小游戏状态构造同一协议。runner 本身尚未实现；当前 assembler 可生成 BC-only shard，也可在完整可审计的整局上生成 HP RTG shard。

先前一局（episode ID `8adb3d74082043b4943d53f0199eb22a`）正式发布 2915 行，事件链与决策配对可回放；530 个决策中 529 个有提交与执行结果，525 个成功结果有奖励，294 次手动输入全部配对。终局 win、无回档，但 6 个显式缺口使 `completeness=incomplete`、`value_target_valid=false`：涅奥之怒一次空集多选缺人工确认凭证、商店一次原生购买未匹配、Crystal Sphere 三次格子点击，以及买到“木札”后在 20 张候选中选 3 张附魔的专用界面未结构化。本局 13 次其他涅奥之怒多选已与原生回执配对；没有使用赌徒特酿。药水稀疏槽位出现于 28 个战斗决策，观察、合法动作与同一步 run context 均一致，4 次实际用药也能正确寻址。旧 JSONL 不回写。

“木札”缺口不是候选数量超限：原生界面是 `NDeckEnchantSelectScreen`，旧局外多选只接受普通选牌界面，因而在类型检查处拒绝；这个界面实际允许选 1–3 张，20 个候选可形成 1350 个合法集合。旧日志保留了 `DeckCard` 三个索引，但没有点击前结构化合法集。当前工作树为原生附魔页建立通用选择路径：核对界面可见标题、说明、图标、候选卡对象、人工点击及确认、选择器 Task 和原生 `DeckCard` 回执，单卡和多卡均写一个 `ChooseCardSet`。只有界面能直接辨认的强度整数才进入上下文；实际可见文案会保留，隐藏的原生数值标为 `unobserved`。该通用化路径通过离线构建，但尚未安装或实机验证。Crystal Sphere 在这份旧文件中的三次点击也只能保持缺口；后续代码的支持范围见[采集器说明](docs/human-data-collector-v0.1.md)。

后一局 `f86be9b6ec89451c9a6c87e1558e8e5f` 的 1792 行和 320 组决策/动作/结果/奖励均完整，217 次手动输入也全部配对；唯一缺口是浸水抄写室事件的 `PRICKLY_SPONGE`：12 张候选里原生回执选了 2 张 `Steady` 附魔牌，但旧安装版未记录选择前合法集，故败局仍为 `value_target_valid=false`。这次不是木札；本地工作树现补上 `Steady` 的可见效果核对及同一附魔网格路径。该局使用的游戏 DLL 与随后本地的新构建不同，更新后的附魔选择仍需实机触发验证；旧 JSONL 不改写。

先前一局 `ea59b2a19b2d44d99f5e4620df632e33` 有 2382 行、428 组完整的决策/提交/执行结果；425 个成功结果有奖励，3 个正常取消无需奖励。274 次手动输入全部配对，事件链完整、无 coverage gap，终局 defeat，`completeness=complete`、`value_target_valid=true`。药水槽位审计无错位，210 次所选出牌有 `display`；该局安装版包含上轮附魔与水晶球修复，但没有触发对应页面。另在 queued 输入的 global step 204，已提交的卡 11 仍被旧代码列为合法动作，尽管这次所选是卡 14；原始文件保留，训练转换需重建或排除这一步。本地代码已过滤同一卡牌的重复候选，尚未安装实测。

再后一局 `24b023e841e44bb5a2dde5239e999fa2` 有 3859 行、687 组完整的决策/提交/执行结果；684 个成功结果有奖励，3 个取消无奖励，463 次手动输入均有结果。终局 win，但 4 个缺口令 `completeness=incomplete`、`value_target_valid=false`：两次 `Start` 快速连点的第二张牌无法核对点击时可见手牌，另外两次是旧版附魔白名单拒绝 `Sharp` 和 `Momentum` 的选牌。已安装的排队动作合法集修复得到实机证据：54 个带 pending 的决策无重复排队卡。4 次 `PURITY` 手牌多选均有原生回执。新通用附魔代码只在本地构建，旧 JSONL 原样保留。

先前一局 `ba8f9848c0804175b3c6e64f2fc03747` 有 2987 行、532 组 decision/submission/result 配对，2 个缺口使败局的 `value_target_valid=false`。其中第二次 `Start` 快速出牌在第一张点击约 184 毫秒后发生，两次原生出牌都成功；旧采集器因内部 Hand 比 UI holder 多一张而未能结构化第二次点击。后续状态出现从 Draw 到 Hand 的 `SLIMED`，但没有该点击时的完整快照，不能断言它就是差异牌。原始文件不回填。

近期三份亡灵契约师数据已通过只读事件链审计：`f64f...` 是主动放弃的 6 步短局，可保留成功步骤作 BC 候选；`148a...` 是胜利局，5787 行、1015 个决策中 1014 个成功，另一次取消动作不入 BC，0 个 coverage gap；新增 `4be...` 败局有 1954 行、341 个决策中 339 个成功动作、2 次取消，局外 `TO_TRANSFORM` 的 15 张候选无法冻结，形成 1 个 gap。新局的 265 个战斗决策药水槽号审计均无错位，339 个 BC 步可用首轮特征词表编码，适合作独立同角色动作模仿测试；它的 `value_target_valid=false`，不能作整局价值或多卡选择验证。当前 BC-only 转换不生成整局 value 标签。更多逐步字段检查见[采集器说明](docs/human-data-collector-v0.1.md)。

## 启动配置接口

运行目的、局内算法和局外算法是三个互相独立的配置维度：

| 配置 | 当前值 | 含义 |
|---|---|---|
| `RunMode` | `play`、`train` | 运行游戏或训练；`train` 已预留，但训练器尚未接入 |
| `CombatPolicy` | `manual`、`first-legal`、`mcts` | 玩家手动、局内联调策略或局内 MCTS |
| `OutsideCombatPolicy` | `manual`、`first-legal` | 局外手动，或在地图、事件、休息点、奖励、商店、宝箱及原生选择界面执行第一个合法选项 |

macOS 启动脚本使用 `--run-mode`、`--combat-policy` 和 `--outside-combat-policy`；Windows 对应使用 `-RunMode`、`-CombatPolicy` 和 `-OutsideCombatPolicy`。底层稳定环境变量分别为：

```text
SLAY_THE_MODEL_RUN_MODE
SLAY_THE_MODEL_COMBAT_POLICY
SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY
```

默认配置是 `play / manual / manual`，即保持状态采集，但不自动操作。旧的 `-Policy` 参数和 `SLAY_THE_MODEL_LIVE_POLICY` 环境变量暂时兼容，后续新代码应使用上面的显式接口。无效配置会安全退回到手动操作。

Mod 通过两层配置读取启动参数：`RuntimeConfiguration` 先读取当前游戏进程的环境变量，若对应值不存在，再读取 Mod 目录中的 `SlayTheModelAdapter.runtime.json`；`AdapterConfiguration` 随后把字符串统一解析成上表的三组枚举。Windows 安装脚本会写入该 JSON，解决 Steam 已经运行时不一定继承临时 PowerShell 环境的问题。局内、局外控制器只接收解析后的 `AdapterConfiguration`，不会各自解释环境变量。

## 环境要求

当前安装与启动流程已在以下环境验证：

- macOS；
- Steam 版《杀戮尖塔 2》；
- 游戏版本 `v0.111.0`；
- 构建 MCTS NativeWorker 时，需要安装 Steam Workshop 中的 STS2-RitsuLib（Workshop ID `3747602295`）；
- macOS 的 NativeWorker 打包脚本使用系统 `jq` 合并 MegaDot 自包含运行时与 worker 依赖清单；
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
./scripts/macos.sh --action test
```

该命令依次运行 Search、Protocol、Outside、Action、ReplaySearch 和 Collector 六组 smoke 测试，不需要启动游戏。它们验证通用搜索器、局内/局外协议、状态哈希、配置解析、动作完成、决策信息隔离，以及采集文件的落盘、恢复和防篡改规则，但不会凭空创建一场真实 STS2 战斗。

读取本机游戏程序集的 ABI 信息时，工具只读取元数据，不加载或执行游戏代码：

```bash
dotnet run --project tools/Sts2.AbiProbe/Sts2.AbiProbe.csproj -- \
  --contract contracts/sts2-v0.111.0.json \
  --out artifacts/abi/sts2-current.json
```

## 编译并安装 Mod（macOS）

开始前请完全退出游戏。推荐直接使用统一脚本：

```bash
./scripts/macos.sh --action check
./scripts/macos.sh --action test
./scripts/macos.sh --action install
```

手动构建 Release 版本也可以：

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

macOS 安装目录最终只需要这两个文件：

```text
SlayTheModelAdapter/
├── SlayTheModelAdapter.dll
└── SlayTheModelAdapter.json
```

协议类型已经编译进主 DLL，不需要另外复制 `SlayTheModel.Sts2.Protocol.dll`。更新 Mod 时，退出游戏、重新构建并覆盖上述两个文件即可。

Windows 安装脚本还会在同一目录生成 `SlayTheModelAdapter.runtime.json`。它只保存本机启动配置和路径，不包含模型或游戏数据，也不应作为另一台电脑的通用配置提交。

## macOS 启动方式一：只采集状态，不自动打牌

先启动 Steam 客户端，但不要从 Steam 启动游戏。确认没有已经运行的游戏进程，然后在仓库根目录执行：

```bash
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy manual --outside-combat-policy manual --capture-history
```

对应的底层环境变量启动方式为：

```bash
SLAY_THE_MODEL_EXPORT_DIR="$PWD/artifacts/live-capture" \
SLAY_THE_MODEL_CAPTURE_HISTORY=1 \
SLAY_THE_MODEL_RUN_MODE=play \
SLAY_THE_MODEL_COMBAT_POLICY=manual \
SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY=manual \
SteamAppId=2868840 \
SteamGameId=2868840 \
"$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/MacOS/Slay the Spire 2"
```

此模式下，Mod 只在稳定的玩家决策点读取和导出状态，不会替玩家出牌。终端应出现：

```text
[SlayTheModel] configuration run_mode=play combat_policy=manual outside_combat_policy=manual
[SlayTheModel] omniscient combat capture adapter initialized
```

默认持续覆盖：

```text
artifacts/live-capture/latest-combat-decision.json
```

`SLAY_THE_MODEL_CAPTURE_HISTORY=1` 会额外保存每个不同决策点；不需要历史记录时，可以从启动命令中删除这一行。

## macOS 启动方式二：让联调策略自动接管

同样需要先完全退出当前游戏，再用下面的命令启动新进程：

```bash
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy first-legal --outside-combat-policy manual --capture-history
```

对应的底层环境变量启动方式为：

```bash
SLAY_THE_MODEL_RUN_MODE=play \
SLAY_THE_MODEL_COMBAT_POLICY=first-legal \
SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY=manual \
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

上面的命令只接管战斗。若要同时启用局外 `first-legal`，使用：

```bash
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy first-legal --outside-combat-policy first-legal --capture-history
```

局外策略通过游戏原生控件选取第一个合法选项，不使用屏幕坐标。它会处理地图、事件、休息点、奖励、商店、宝箱以及这些操作打开的卡牌/遗物选择界面；药水栏满时跳过药水奖励。商店当前只尝试删牌，优先删除打击，其次删除防御，再按卡牌 ID 删除最小项；付不起删牌费用时直接离开。主菜单、单人游戏、角色选择等开局流程仍需手动完成，当前只面向单人模式。

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
# 只采集状态，局内外均由玩家操作
./scripts/windows.ps1 -Action Launch -RunMode play -CombatPolicy manual -OutsideCombatPolicy manual -CaptureHistory
# 或退出游戏后启用局内、局外 first-legal
./scripts/windows.ps1 -Action Launch -RunMode play -CombatPolicy first-legal -OutsideCombatPolicy first-legal -CaptureHistory
```

只构建不安装时使用 `-Action Build`。自动发现失败时指定 `-GameDir 'D:\SteamLibrary\steamapps\common\Slay the Spire 2'`，也可设置 `STS2_GAME_DIR` 环境变量。非标准程序集位置可用 `-ManagedDir` 指定。直接使用 `dotnet build` 时，Windows 默认查找标准 Steam 目录，支持 `STS2_GAME_DIR` 或 `-p:Sts2ManagedDir=...`；其他 Steam 库请优先使用脚本。

脚本优先使用 `%LOCALAPPDATA%\SlayTheModel\dotnet\dotnet.exe`（若存在），否则使用 PATH 上的 `dotnet`。本机验证使用前者安装的 SDK 9.0.306。

启动默认输出到仓库的 `artifacts/live-capture`，可用 `-ExportDir` 修改。环境变量仅传给新启动的游戏，随后恢复当前 PowerShell 环境；默认 capture 模式会清除继承的自动操作设置。启动前需退出已有游戏，安装也会拒绝在游戏运行时覆盖 DLL。

首次启动如提示 Mod，请启用。自动操作仅支持单人模式，主菜单和角色选择仍需手动处理；部分特殊事件还需要进一步游戏内验证。环境变量不支持游戏运行时切换。

Windows ABI 契约位于 `contracts/sts2-v0.111.0-windows.json`，来源为本机 v0.111.0、commit `41cef1ea`；macOS 契约保持独立。Windows 已验证构建和静态 ABI，尚未验证游戏内战斗。ABI 通过不等同于完整运行时兼容性。

本机 Windows 日志位于 `%APPDATA%\SlayTheSpire2\logs\godot.log`。采集文件仍可用后文的 CaptureCheck 工具检查。

## 实验性 MCTS（Windows / macOS ARM64，v0.3.0）

已接入独立原生战斗 worker、入口重建与动作重放、首步 5 秒搜索、动作与动画期间以 500 毫秒时间片持续思考、搜索树复用，以及 F8 暂停／恢复。决策点只采用与实际完整状态指纹匹配的最新结果。首版仅面向单人铁甲战士且不使用药水；局外既可以保持 `manual`，也可以独立启用 `first-legal`。

游戏右上角显示 MCTS 状态按钮：绿色开启、蓝色思考中、黄色暂停、灰色未开启或不支持。战斗中可点击暂停／恢复，悬停查看说明。

```powershell
./scripts/native-worker.ps1 -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'
./scripts/windows.ps1 -Action Install
./scripts/windows.ps1 -Action Launch -RunMode play -CombatPolicy mcts -OutsideCombatPolicy manual -CaptureHistory
```

macOS ARM64：

```bash
./scripts/native-worker-macos.sh --mode verify
./scripts/macos.sh --action install
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy mcts --outside-combat-policy manual --capture-history
```

脚本默认在 Steam 的标准 Workshop 目录查找 RitsuLib。如果 Workshop 位于其他 Steam 库，使用：

```bash
./scripts/native-worker-macos.sh --mode verify \
  --ritsu-lib-root "/实际路径/steamapps/workshop/content/2868840/3747602295"
```

Windows 和 macOS ARM64 的原生重放、后续选牌和跨进程状态校验已经通过；实际游戏窗口和广泛卡牌组合仍需验证。3 个固定遭遇测试中 MCTS 获胜 3/3，但不能据此推断整局强度。详见 [使用说明、测试结果与限制](docs/native-mcts-v0.3.0.md) 和 [设计方案](docs/combat-mcts-v1-plan.md)。

## 测试用策略：`first-legal`

### 局内

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

### 局外

局外 `first-legal` 只在一局已经开始后工作。适配器先把当前局外状态和当前已支持界面的全部合法动作投影成不含 Godot 节点的稳定协议，再由策略返回完整的 `OutsideCombatActionDescriptor`，最后由私有原生绑定执行对应控件。`action_id` 是该动作在当前状态指纹下的唯一标识，不是策略的全部返回值。事件会跳过锁定、禁用或已经选择过的选项；奖励和其他选牌操作完成后，控制器会等待界面稳定，再选择第一个合法路线节点，避免选卡与地图并行出现时发生同步卡死。

商店采用一个暂定的确定性特例：只使用删牌服务，优先删除打击，其次删除防御，如果两者都不存在则删除卡牌 ID 最小的一张；金币不足时跳过商店。除该特例外，它不评估路线、卡牌、遗物或商店价值，只负责提供第一版可复现的整局自动化基线。

`choice_context` 使通用界面不会被错认为同一个决策：`context_id`、`state_token`、`phase`、选择数上下限和已选数量可以区分删牌、升级、预览确认以及小游戏的不同阶段。`state_token` 只导出稳定状态的 SHA-256 标识，不导出本地化正文。

当前同步的 `first-legal` 只是快速基线，决策不做阻塞式推理。未来的慢神经网络或远程模型必须通过异步 worker 接入，不能在 Godot 主线程的帧回调中等待。

## 检查导出的决策文件

```bash
dotnet run --project tools/SlayTheModel.CaptureCheck -- \
  artifacts/live-capture/latest-combat-decision.json

# 也可检查局外决策或带策略选择的样本
dotnet run --project tools/SlayTheModel.CaptureCheck -- \
  artifacts/live-capture/latest-outside-sample.json

# 检查动作是否观察到状态变化，或由原生事务确认成功/取消/失败/超时
dotnet run --project tools/SlayTheModel.CaptureCheck -- \
  artifacts/live-capture/latest-outside-result.json
```

启用 `--outside-combat-policy first-legal` 后，每次实际选择都会更新
`latest-outside-decision.json`、`latest-outside-sample.json` 和动作完成后的
`latest-outside-result.json`。再启用
`--capture-history`，控制器会额外写入不可变的逐条 JSON 样本，并把样本追加到
`outside-trajectory.jsonl`；该 JSONL 是跨局、跨进程追加的数据集，通过 `episode_id`
区分不同游戏，不应把整个文件当成单独一局。每条 `OutsideCombatDecisionSample` 都有独立的 `schema_version`，并包含同一决策点的完整局外观察、合法动作、策略名称、状态指纹和实际选择的动作 ID，可直接作为之后模仿学习或轨迹整理的输入。
执行结果另存到 `outside-results.jsonl`。正常运行时每个 `request_id` 只有一条终态结果；强制退出或进程崩溃可能使结果缺失。训练预处理应以样本为左表按 `request_id` 左连接结果，只保留 `observed_transition` 或 `applied` 等成功结果；缺失、`cancelled`、`failed` 和 `timed_out` 不得当成成功训练样本。
观察包含楼层、房间、玩家 HP/金币、牌组、遗物、药水以及已知地图拓扑；隐藏 RNG、
Godot 路径、运行时实例 ID 和原生存档不会进入策略接口。

主要接口：

- `CombatCaptureService.BuildSearchPoint(...)`：返回完整模拟器状态、过滤后的局内决策以及独立的局外观察；
- `CombatCaptureService.BuildDecisionPoint(...)`：只返回给战斗策略使用的观察与稳定合法动作列表；
- `CombatStepGuard.RequireExpectedState(...)`：拒绝针对旧状态生成的命令；
- `CombatActionExecutor.CreateGameAction(...)`：把协议动作转换为原生游戏动作，但不执行；
- `CombatActionExecutor.ExecuteAsync(...)`：把动作加入原生执行队列，并等待执行器恢复空闲；
- `OutsideCombatCaptureService.BuildDecisionPoint(...)`：把原生局外状态和合法动作投影为稳定决策点；
- `IOutsideCombatPolicy.SelectAction(...)`：局外策略只接收协议数据并返回完整的 `OutsideCombatActionDescriptor`；
- `OutsideCombatStepGuard.RequireCurrentAction(...)`：拒绝过期指纹或当前界面不存在的动作；
- `OutsideCombatDecisionSample`：供训练与数据采集使用的可序列化“观察—动作”样本；
- `OutsideCombatExecutionResult`：记录观察到状态变化、原生确认成功、取消、失败或超时。

完整的数据边界、版本规则和采集文件见 [局外决策接口 v1](docs/outside-combat-interface-v1.md)。

## 常见问题

### 游戏启动了，但 Mod 没有输出

检查以下内容：

- 游戏是否在复制 DLL 后重新启动；
- `SlayTheModelAdapter.dll` 与 `SlayTheModelAdapter.json` 是否位于同一个 Mod 目录；
- 是否通过终端命令启动了这一份游戏；
- 当前游戏版本是否仍兼容 `v0.111.0` 的接口；
- 是否有其他 Mod 在启动阶段报错。排查时建议只保留本 Mod。

### Mod 读取状态，但不自动出牌

这是默认且更安全的行为。只有在启动游戏前设置了精确的 `SLAY_THE_MODEL_COMBAT_POLICY=first-legal` 或 `mcts`，相应的局内自动操作才会启用。

### 如何立即停止自动操作

退出游戏，然后使用 `SLAY_THE_MODEL_COMBAT_POLICY=manual` 重新启动。当前版本不会在游戏运行中动态切换策略。

### 游戏更新后构建或启动失败

本项目的已验证接口固定在 `v0.111.0`。游戏更新可能改变 ABI；先运行 ABI 探针并对照 `contracts/sts2-v0.111.0.json`，不要在未验证的新版本上假设动作桥仍然安全。

## 设计文档

- [基线设计与里程碑](docs/baseline-design.md)
- [STS2 v0.111.0 接口说明](docs/sts2-v0.111.0-abi.md)

本项目要求使用者自行拥有合法安装的游戏，仓库不分发游戏程序集或游戏资源。

## Combat Solver MCTS 后端（Windows / macOS ARM64）

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

脚本默认从游戏所在 Steam 库的 `steamapps\workshop` 目录查找 RitsuLib。如果 Workshop 位于其他库，额外传入 `-RitsuLibRoot 'D:\其他库\steamapps\workshop\content\2868840\3747602295'`，或设置 `STS2_RITSULIB_DIR`。

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

该文件保存三类运行模式以及 worker、项目、游戏包和导出目录。适配器优先读取进程环境变量，缺失时读取这个持久配置，因此不需要退出 Steam：

```powershell
& '.\scripts\windows.ps1' `
  -Action Install `
  -RunMode play `
  -CombatPolicy mcts `
  -OutsideCombatPolicy manual `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'

& '.\scripts\windows.ps1' `
  -Action Launch `
  -RunMode play `
  -CombatPolicy mcts `
  -OutsideCombatPolicy manual `
  -GameDir 'D:\Steam\steamapps\common\Slay the Spire 2'
```

启动前只需要确保游戏进程已经退出；Steam 客户端可以继续运行。脚本通过 `steam.exe -applaunch 2868840` 启动游戏，游戏内 MCTS 仍使用独立 NativeWorker。不要同时启用 Combat Solver 自带的自动出牌控制器。

更详细的桥接关系、状态推进方式和已知限制见 [Combat Solver MCTS 后端说明](docs/combat-solver-mcts-backend.md)。
