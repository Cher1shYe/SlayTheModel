# 高速整局 runner：性能验证门槛

当前可玩的终端宿主加载完整原生 `NGame` 场景，通过界面节点识别和执行一部分操作，并保留动画、音频和轮询。它用于核对原生交互，不能用终端响应时间估算未来自博弈吞吐量。

## 已测：无完整界面的原生战斗

`tools/Sts2.NativeWorker/NativeThroughputBenchmark.cs` 通过现有 `NativeSession`、原生动作队列和选牌回调连续打完固定 `CULTISTS_NORMAL` 遭遇。worker 运行于 Godot `--headless`、`TestMode` 与 `NonInteractiveMode`，不加载 `NGame` 主场景；先跑一个热身种子，再用三个固定种子和 `attack-first` 策略计时。每场的 `actionsMs` 只含原生动作提交至下一决策点的时间，`resetMs` 单列。

2026-10-08 macOS ARM64 实测：

| 种子 | 决策数 | 动作总耗时 | 决策/秒 | 单步中位数 | 单步 p95 |
|---|---:|---:|---:|---:|---:|
| `STM-THROUGHPUT-1` | 24 | 41.46 ms | 578.9 | 0.84 ms | 4.91 ms |
| `STM-THROUGHPUT-2` | 20 | 26.53 ms | 753.9 | 0.76 ms | 5.67 ms |
| `STM-THROUGHPUT-3` | 19 | 33.13 ms | 573.5 | 0.70 ms | 5.27 ms |

三场都按原生规则胜利并到达终局。这个结果证明在该固定战斗中，**原生战斗结算可以脱离完整界面等待高速运行**。它没有计入进程启动、策略推理、JSON 投影、采集落盘、地图/事件/商店/奖励和多进程调度；它也不是整局每秒局数的预测。此前 Combat Solver 的 rollout/s 是另一种模拟指标，不能与这里的原生决策/秒直接相加或比较。

复跑（使用已安装的 STS2 `v0.111.0`，不会启动 Steam）：

```bash
./scripts/native-worker-macos.sh --mode native-throughput --timeout-seconds 120
```

Windows 对应 `scripts/native-worker.ps1 -GameDir <game-dir> -Mode native-throughput`。原始结果写在被 Git 忽略的 `artifacts/native-host/native-throughput.json`。

## 已测：无完整界面的固定种子最小跑局路径

以下直到“同种子原生场景对照”为止的路径和耗时，均为历史未规范化种子夹具；现在须显式使用 `--mode whole-run-speed-probe-legacy` 复跑，输出到 `whole-run-speed-probe-legacy.json`。默认 `whole-run-speed-probe` 已改用游戏的 `SeedHelper.CanonicalizeSeed`，其结果单列在下节。

`WholeRunSpeedProbe` 在同一个无 `NGame` 进程里依次调用原生开局、涅奥选项、地图移动、战斗动作、战后奖励和下一次地图移动。涅奥使用 `EventOption.Chosen()`，以 `CardSelectCmd.PushSelector` 返回游戏给出的原生候选卡；`PRECISE_SCISSORS` 确实把牌组从 10 张减为 9 张并加入遗物。战斗进入 `SHRINKER_BEETLE_WEAK`，按合法动作打完 9 个决策，胜利时 HP 为 79。普通游戏由 `NCombatUi` 在胜利动画后调用 `CombatRoom.OfferRoomEndRewards()`；无界面探针在战斗完成的同一原生边界显式调用它，由 TestMode 选择并结算原生奖励。牌组随后 9→10、金币 99→116、药水 0→1，最后进入下一地图节点的 `EventRoom`。没有直接修改这些结果。

2026-10-08 macOS ARM64 同一固定种子多次运行均到达下一节点，输出 `gameSceneLoaded=false`、`error=null`。一次阶段计时：创建 run 16.5 ms、设置 run 22.6 ms、进入第一幕 207.4 ms、涅奥选项及删牌 6.9 ms、移动至战斗 76.4 ms、战斗 88.8 ms、奖励 20.5 ms、下一地图节点 5.0 ms；**整段墙钟 452.5 ms**。后续扩展探针多次运行到该节点约 424–468 ms。整段计时从探针开始创建 run 到下一节点进入为止，包含探针的阶段记录与反射诊断；不含 worker 进程启动、构建、终端传输、模型推理、协议投影或 JSONL 落盘。历史结果现在单独写入被 Git 忽略的 `artifacts/native-host/whole-run-speed-probe-legacy.json`。

该自然路线的下一节点是 `AROMA_OF_CHAOS`。探针随后选择事件的 `LET_GO`，原生 `FromDeckForTransformation` 接收一个 `STRIKE_IRONCLAD`；事件完成后所选卡实例离开牌组，随机生成的 `TREMBLE` 进入牌组，总数仍为 10 张。这为无完整界面的**单卡变形**提供实测证据。

## 已测：固定种子自然败局

同一探针继续沿自然地图运行，在 `NIBBITS_WEAK` 战斗中用 9 个决策获胜，HP 降至 67；原生奖励使牌组 10→11、金币 116→133、药水 1→2。随后 `MORPHIC_GROVE` 的 `GROUP` 选项经原生选择器提交两张对象身份不同的 `STRIKE_IRONCLAD`，两张旧卡均离开牌组，生成 `JUGGLING` 和 `SWORD_BOOMERANG`，牌组仍为 11 张，金币 133→0。`SELF_HELP_BOOK` 的 `READ_THE_BACK` 又通过原生选择器为一张 `STRIKE_IRONCLAD` 加上 `SHARP` 附魔；牌组中附魔卡数量 0→1。这些检查分别覆盖双卡变形和单卡附魔，未直接改动牌组或金币。

自然路线进入第 7 层 `BYGONE_EFFIGY_ELITE`，攻击优先策略进行 21 个战斗决策后 HP 降至 0。原生状态为 `CombatManager.IsInProgress=false`、`RunManager.IsGameOver=true`，最终输出 `natural-run-defeat`、`gameSceneLoaded=false`、`error=null`。三次从创建 run 到该终局的墙钟分别为 **491.5/531.3/485.7 ms**；它包含上述三个战斗、事件、原生奖励和地图推进，不含 worker 启动、构建、协议投影、模型推理、JSONL 落盘及多进程调度。`RunManager.IsInProgress` 此时仍为 true，因此终局判断以 `IsGameOver` 和战斗结束状态为准。

这是一条固定种子、固定首个地图子节点、首个可选事件选项、选择器最少选牌数和攻击优先策略的**短败局**。它证明这条路径可以不用 `NGame` 跑到原生败局边界；尚未证明可泛化的整局 runner、完整胜局、其他种子/角色或真实训练吞吐量。

## 同种子原生场景对照（2026-10-08）

**种子入口、首战初始状态及同动作下的首战抽牌已对齐，尚未证明整局逐步等价。**在同一台机器、同一 `v0.111.0` 程序集上，游戏的 `SeedHelper.CanonicalizeSeed` 会把输入 `STM-WHOLE-RUN-SPEED-1` 中的字母 `O` 改为数字 `0`，得到 `STM-WH0LE-RUN-SPEED-1`。默认高速探针与终端宿主一样先规范化，再用该值生成 act 随机流和 `RunState`；输出记录 `inputSeed`、实际 `seed` 和 `seedHandling=native-canonicalized`。旧未规范化路径只在显式 `whole-run-speed-probe-legacy` 模式下运行，历史涅奥 `PRECISE_SCISSORS / ARCANE_SCROLL / NEOWS_BONES`、首战 `SHRINKER_BEETLE_WEAK` 和对应耗时不能解释为玩家输入同一种子后的结果。

默认探针现在可按规范化种子完成涅奥、首战、原生奖励与下一地图节点，输出 `canonical-prefix-complete`、`error=null`；修复后的本次用时约 407 ms，不含进程启动和构建。在完整场景宿主中同样输入该种子、同角色铁甲战士、进阶 0、选择第一个涅奥选项和第一张地图节点：两边涅奥选项顺序一致，第一幕地图的 **65 个节点类型与 77 条连线逐项一致**，涅奥第一选项均得到 `SCROLL_BOXES` 和相同的 13 张牌。两边首战均为 `TOADPOLES_WEAK`，两只 `TOADPOLE` 初始 HP 均为 25/21，玩家初始 HP 均为 80。沿旧探针所选路径的下一节点是战斗，故默认规范化路线在此停止；旧 `AROMA_OF_CHAOS`、第 7 层败局和 shop/rest 的断言仅留在显式历史夹具中。

差异定位在玩家解锁状态：探针原来把 `UnlockState.all` 交给 `Player.CreateForNewRun`，完整场景宿主的 `NGame.StartNewSingleplayerRun` 则调用 `SaveManager.GenerateUnlockStateFromProgress()`。这会影响原生房间/遭遇生成，单独对齐种子仍不够。默认探针现在先像宿主一样在隔离 profile 中 reveal 全部 epoch，再从该 profile 生成玩家解锁状态。后续长路径又定位到一项 TestMode 差异：`RunManager.ShouldApplyTutorialModifications` 在 TestMode 下默认跳过原生发现顺序调整，导致原先探针首领为 `LAGAVULIN_MATRIARCH_BOSS`，完整场景宿主为 `WATERFALL_GIANT_BOSS`。默认规范化探针现设置游戏自带的 `ForceDiscoveryOrderModifications=true`，让 `ActModel.ApplyDiscoveryOrderModifications` 按正常游戏规则运行；显式 legacy 夹具保持旧规则。探针仍开启 `TestMode` / `NonInteractiveMode`，直接调用 `RunManager` 而不加载 `NGame`。用户的 Steam profile 可能有不同解锁与历史，不能把此隔离 profile 的结果直接等同于该 profile 的同种子跑局。

### 首战同动作抽牌对照

设置 `STS2_PROBE_TRACE_DRAWS=1` 时，`WholeRunSpeedProbe` 记录首战每个决策前的回合、玩家 HP/能量、存活敌人、手牌和 draw/discard/exhaust/play 各堆的无序 model ID 集合，以及所选动作的卡牌类型和目标；普通速度测量不生成逐决策轨迹。`scripts/check-headless-draw-parity.py` 用终端宿主的本机 API，从同输入种子开局，选涅奥第一项、第一组卡牌包及地图最左节点，再按探针记录的动作逐步提交；每步等待完整场景进入稳定决策状态后比较。重复卡按相同 model ID 选择，不把进程内随机对象 ID 当作跨进程身份。

2026-10-08 macOS ARM64 从全新测试局自动复跑：首战共 8 个决策点，`BASH`、`STRIKE_IRONCLAD`、结束回合、两张 `STRIKE_IRONCLAD`、`DEFEND_IRONCLAD`、结束回合、`BLUDGEON` 的动作类型与目标一致；每一步的手牌及各牌堆集合、回合、能量、玩家 HP 和存活敌人 HP 全部一致。第 3 回合的手牌发生在洗牌后，仍一致。两边首战胜利后玩家均为 75 HP，完整场景进入原生奖励页。宿主还会短暂保留 0 HP 敌人的动画节点；比较器按存活敌人核对，不把该节点当成战斗状态差异。结果在被 Git 忽略的 `artifacts/headless/first-combat-draw-parity.json`，`matchedDecisions=expectedDecisions=8`，`terminal.matches=true`。

复跑时先生成探针轨迹，再另开终端保持宿主运行，最后在第三个终端执行对照脚本：

```bash
# 终端一：生成探针轨迹
STS2_PROBE_TRACE_DRAWS=1 ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 120
# 终端二：保持原生场景宿主运行
./scripts/headless-macos.sh --server-only
# 终端三：提交相同动作并比较
python3 scripts/check-headless-draw-parity.py
```

这证明该种子、该 profile 解锁配置和这组动作下的可见抽牌结果一致；牌堆按无序集合比较，没有读取或比较未来隐藏抽牌顺序，也没有验证其他动作、种子或角色。

### 同种子战后奖励与首个问号事件（2026-10-09）

第一场 `TOADPOLES_WEAK` 胜利后，两边都出现 10 金币、Fire Potion 和同一组卡牌奖励候选：`SWORD_BOOMERANG / BLOOD_WALL / POMMEL_STRIKE`。按同一顺序领取金币、药水并选第一张卡后，两边都是 HP 75、金币 109、牌组 14 张且持有 Fire Potion。从首战节点 `(0,1)` 沿原生连线选择问号节点 `(1,2)`，两边都生成 `SPIRALING_WHIRLPOOL`，选项顺序均为 `Observe / Drink`。

从各自的新测试局分别验证了两个互斥分支；两次都先重放并核对相同的 8 个战斗决策：

- `Observe`：两边的原生附魔选择器都提供 5 张 Strike 和 4 张 Defend，选一张 Strike 并确认后，牌组内恰有一张 `STRIKE_IRONCLAD` 获得 `ENCHANTMENT.SPIRAL`；HP 75、金币 109、14 张牌、遗物及药水集合逐项一致。
- `Drink`：无子选择器；两边 HP 75→80，金币 109，牌组、遗物及药水集合不变。

两条分支结束后都沿原生连线 `(1,2)→(2,3)` 进入 `CORPSE_SLUGS_WEAK`；两只 `CORPSE_SLUG` 初始 HP 27/26，玩家 HP、金币与牌组明细也一致。对照脚本使用完整场景宿主的真实奖励按钮、地图节点、事件按钮、附魔确认及事件结束后的 `Proceed`，不用开发传送入口。它检查事件 model ID、选项标题、卡牌奖励与附魔候选集合、选择后的牌组 model ID/升级/附魔、HP、金币、遗物、药水及下一遭遇入口。结果分别在忽略文件 `artifacts/headless/event-parity-observe.json` 和 `event-parity-drink.json`，均为 `matchedDecisions=8`、`eventRoute.matches=true`、`nextRoom.matches=true`。重复的基础牌按卡牌类型与最终状态对照，没有跨进程匹配随机对象 ID。

复跑时每个分支使用新启动的宿主；先生成对应探针文件，再另开终端运行 `./scripts/headless-macos.sh --server-only` 并保持宿主运行，最后调用对照脚本。完成 `Observe` 后停止宿主，再为 `Drink` 启动新宿主：

```bash
STS2_PROBE_ROUTE=event STS2_PROBE_TRACE_DRAWS=1 ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 120
python3 scripts/check-headless-draw-parity.py --probe-json artifacts/native-host/whole-run-speed-probe-event.json --compare-event --output artifacts/headless/event-parity-observe.json

STS2_PROBE_ROUTE=event STS2_PROBE_EVENT_OPTION=1 STS2_PROBE_TRACE_DRAWS=1 ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 120
python3 scripts/check-headless-draw-parity.py --probe-json artifacts/native-host/whole-run-speed-probe-event-1.json --compare-event --output artifacts/headless/event-parity-drink.json
```

这只验证了这一种子、这一条自然路线上的首个问号事件、两个分支和下一遭遇的入口；第二场战斗的逐决策抽牌、其他事件与整局 RNG 连续性仍需逐项核对。

## 已测：规范化种子的无场景长路径（2026-10-09）

`STS2_PROBE_LONG_PATH=1` 在上述 `event` 前缀之后，继续由同一个 `WholeRunSpeedProbe` 进程处理自然生成的房间。它按公开地图节点类型优先休息点、宝箱、商店、问号、普通战斗，再到精英和首领；战斗仍为简单的攻击优先策略，事件取当前第一项，休息点有伤时回血，宝箱按原生奖励结果领第一件遗物。无 `NGame` 场景或 UI 按钮，仍通过原生 `RunManager`、战斗动作、事件 `Chosen()`、休息点 synchronizer、宝箱 synchronizer 和 `RelicCmd.Obtain` 推进。每次地图移动检查原生指针和楼层，未用传送或直接改 HP/金币/牌组。

macOS ARM64、规范化后的种子 `STM-WH0LE-RUN-SPEED-1` 实际经过第 1–17 层：首战 8 个决策；之后 8 场战斗共 122 个决策，含第 17 层 `WATERFALL_GIANT_BOSS`；经过“螺旋漩涡”、第 13 层 `TEA_MASTER`、4 个休息点和第 10 层宝箱。最终 `RunManager.IsGameOver=true`、HP 0、`gameSceneLoaded=false`、`error=null`，输出 `long-path-natural-defeat`。修正发现顺序规则后的最近复跑从创建 run 到死亡的探针内计时 **788.9 ms**，不含构建、进程启动、输出序列化、协议投影、训练 writer、模型或调度；固定种子及简单策略的单次耗时不能作为整局吞吐量估计。结果在忽略文件 `artifacts/native-host/whole-run-speed-probe-event-long.json`。

第 14 层战后，原生 TestMode 自动领取金钱和卡牌时，药水槽已满，新药水不能领取。此时跳过新药水是合法选择。探针只在剩余奖励全为药水且槽位确实全满时调用普通界面“跳过剩余奖励”对应的 `RewardsSetSynchronizer.SkipLocalRewardsSet()`，并核对原生奖励集合已完成、原有三瓶药水的槽位和种类逐项不变；结果记录 `skippedRewards=["PotionReward"]`，其他未完成奖励会使探针失败。因此，这条固定路径的奖励处理和原生败局终点**通过了状态语义验证**。另有一项日志问题：探针执行跳过前，`RewardsSet.Offer()` 的内部 `TaskHelper` 已记录 `The RewardsSet is not complete after rewards were selected!`，所以输出保留顶层 `warnings` 和 `complete-with-warnings` 标记。该标记说明 TestMode 自动领奖的日志不干净，不表示拿错药水、丢失旧药水或奖励集合未结算。

复跑（新的独立 worker 进程）：

```bash
STS2_PROBE_ROUTE=event STS2_PROBE_LONG_PATH=1 ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --no-restore --timeout-seconds 120
```

未设置 `STS2_PROBE_LONG_PATH` 的默认事件前缀已复跑，仍输出 `canonical-prefix-complete`、`error=null`。这条自动长路径与终端宿主采用不同的战后奖励和后续事件决策；同动作整局对照见下文。该阶段尚未验证跨幕胜局和其他种子，后续通用入口结果见下一节。

## 已测：任意规范化种子的通用入口（2026-10-14）

`STS2_PROBE_GENERIC=1` 现在会在涅奥原生选项完成后直接进入同一个无场景房间循环，不再依赖固定首战、固定问号事件或 `event` 前缀。输入种子由 `STS2_PROBE_SEED` 指定并继续经过 `SeedHelper.CanonicalizeSeed`；每个种子写入独立的 `whole-run-speed-probe-generic-<seed>.json`。循环原生处理战斗、事件、休息点、宝箱和合法离开商店，地图路线仍使用公开节点类型的固定优先级。没有加载 `NGame`，也没有直接修改 HP、金币、牌组或地图位置。

通用循环新增幕末处理：当前地图没有子节点且还有下一幕时调用原生 `RunManager.EnterNextAct()`，最后一幕完成时调用 `RunManager.WinRun()`；胜利和失败都作为合法终局写入 `long-path-native-terminal`。第 4 个种子现已真实打赢第一幕首领并经 `EnterNextAct()` 进入第二幕；新幕原生落在 `MapRoom` 且 `CurrentMapPoint=null`，循环从 `run.Map.StartingMapPoint` 取得第一组合法连接后继续推进。`WinRun()` 仍只有编译覆盖，尚无运行时胜局证据。

macOS ARM64 代表性实测：

| 输入种子 | 到达楼层 | 房间覆盖 | 终局 | 探针内时间 |
|---|---:|---|---|---:|
| `STM-WHOLE-RUN-SPEED-1` | 17 | 17 房间、16 次移动；含战斗、事件、休息、宝箱、商店 | `WATERFALL_GIANT_BOSS` 败北 | 662.1 ms |
| `STM-WHOLE-RUN-SPEED-2` | 17 | 7 战斗、4 事件、3 商店、2 休息、1 宝箱 | `WATERFALL_GIANT_BOSS` 败北 | 1151.0 ms |
| `STM-WHOLE-RUN-SPEED-3` | 11 | 7 战斗、3 事件、1 宝箱；事件触发单卡选择 | `BYRDONIS_ELITE` 败北 | 844.8 ms |
| `STM-WHOLE-RUN-SPEED-4` | 18 | 第一幕 17 层、原生跨幕、第二幕 `MapRoom` 和首战 | 打赢 `VANTOM_BOSS`，在 `EXOSKELETONS_WEAK` 败北 | 1468.9 ms |

随后已连续检查 `STM-WHOLE-RUN-SPEED-{1..20}`：20/20 输出均为 `error=null`、`gameSceneLoaded=false`，终局分布在第 7–18 层，其中第 4 个种子产生一条 `fromActIndex=0, toActIndex=1` 的原生转幕记录。自然路线共覆盖 20 种非涅奥事件，包括单卡/多卡选择、变形、附魔和可重复选项。第 9 个种子最初暴露 `ABYSSAL_BATHS` 的 `LINGER` 会生成新的同名选项，旧“总选第一个”策略因此循环；事件策略现优先选择本事件中使用次数较少的合法选项，并保留 32 步失控保护。复跑按 `IMMERSE → LINGER → EXIT_BATHS` 原生结束事件并继续到第 8 层终局；第 13 个种子也再次通过该事件。原 `STS2_PROBE_ROUTE=event STS2_PROBE_LONG_PATH=1` 路径复跑到同一第 17 层败局，保持兼容。脚本的 `--skip-build` 现在仍会重新打包刚完成的 DLL，避免执行旧的 staged worker；默认构建限制为单 MSBuild 节点并关闭 node reuse，规避本机共享构建节点无错误卡住的问题。

通用战斗另有显式实验开关 `STS2_PROBE_USE_POTIONS=1`。它按采集器相同的原生 `CanUseOrRemovePotions`、`PassesCustomUsabilityCheck`、`TargetType` 和 `IsValidTarget` 规则生成药水动作，再交给 `CombatActionExecutor` 执行；第 4 个种子已真实消费三瓶药水并完成药水触发的选牌。当前“半血以下按槽位使用”规则仍使该种子退回第一幕败北，因此默认保持关闭，输出单独写入 `*-potions.json`。这证明药水执行管线可用，不证明该启发式策略更强。

复跑任意种子：

```bash
STS2_PROBE_GENERIC=1 STS2_PROBE_SEED=STM-WHOLE-RUN-SPEED-2 \
  ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 180
```

上述结果验证了 20 个种子的原生房间推进、失败终局、可重复事件退出以及一次真实跨幕。除第一个种子的既有对照外，其他种子尚未与完整场景逐决策对齐；商店购买策略和最终胜利也未验证。

## 已测：终端败局决策在高速探针重放（2026-10-09）

使用原生 `Sts2.HeadlessHost` 的独立测试 profile，从输入种子 `STM-WHOLE-RUN-SPEED-1`、铁甲战士、进阶 0 开新局；`scripts/headless-agent-run.py` 只读取终端宿主的 `/api/state` 公共状态，从当前可用动作中选择并提交。脚本是这次由 agent 编写和控制的简单游戏策略，不是 SpireFormer，也不是人工逐键输入。它在第 17 层 `WATERFALL_GIANT_BOSS` 败北，原生终态 `screen=defeat`、HP 0、金币 213。`artifacts/headless/agent-run-trace.jsonl` 逐条保存了 **244 个被接受的动作**及动作前完整公开状态：包括 16 次地图移动、127 次出牌、40 次结束回合、2 次战斗中用药和其他事件、奖励、休息点等操作。中途策略曾弃掉一瓶 Fire Potion，并在第 9 层跳过整组战后奖励；这些动作按原记录重放，没有修饰轨迹。该文件是终端 API 决策记录，不符合训练 journal 的 episode/hash/reward 语义，不能直接用作 BC 或 RTG 数据。

`WholeRunSpeedProbe.RecordedReplay.cs` 在另一个没有 `NGame` 场景的原生 worker 中，从相同规范化种子和隔离 profile 解锁状态开局，按记录的地图连接和动作执行。它使用原生战斗动作、事件 `Chosen()` 与选牌器、休息点、宝箱及战后奖励同步器；在第 9 层记录为整组跳过时临时关闭 TestMode 自动领奖并调用原生 `SkipLocalRewardsSet()`。重放在每次地图移动前核对楼层、HP、金币、牌组及升级/附魔、遗物和药水；在 **169 个战斗动作**前另核对能量、格挡、手牌与各牌堆的无序卡牌集合、存活敌人的 HP/格挡。最终全部 **16 次地图移动和 169 个战斗动作**通过，探针同样第 17 层 HP 0 原生败北，`gameSceneLoaded=false`、`error=null`。结果在 `artifacts/native-host/whole-run-speed-probe-recorded-replay.json`；最近一次探针内计时 **817.3 ms**，不含进程启动、构建和终端跑局时间，也不能据此推断完整训练吞吐量。

跨进程的卡牌对象 ID 是随机生成的，不能按 ID 对应。第 11 层 `SPIRALING_WHIRLPOOL` 对一张 `DEFEND_IRONCLAD` 附魔时，四张相同基础 Defend 在当时公开状态中无法区分；这次重放根据后续可见状态，将选中的原生候选固定为索引 1（`STS2_PROBE_REPLAY_DEFEND_ORDINAL=1`）。其他候选索引在后续战斗出现状态不一致。这是这条已知轨迹的身份消歧，不是通用的确定性身份映射，也不能证明隐藏牌序或所有 RNG 内部状态一致。其他种子、其他选择器和完整胜局仍需验证。

复跑已保存的终端轨迹：

```bash
STS2_PROBE_REPLAY_DEFEND_ORDINAL=1 STS2_PROBE_REPLAY_TRACE="$PWD/artifacts/headless/agent-run-trace.jsonl" ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --no-restore --timeout-seconds 120
```

## 已测：人类 A0 胜局 journal 前缀重放（2026-10-14）

历史记录中无 gap 的 A0 胜局 `435800f8166e4d6ca309ce2ad251fc94` 原始 JSONL 已不在当前硬盘；本轮改用仍保留的铁甲 A0 胜局 `1ddd1912ef634cbeb9d331f52b79cf24`。后者是 48 层胜局，但在第 701 步有一次商店购买点击未匹配，因此只能作为重放调试轨迹，不能恢复成严格整局 RTG 样本。

新增的 `STS2_PROBE_COLLECTOR_REPLAY=<jsonl>` 从原 journal 读取种子、涅奥选择、卡包、地图、奖励和战斗动作。在独立 worker 中，原生 `SeedHelper` 规范化种子，原生 `RunManager` 创建新局，原生选择同步器提交 `SCROLL_BOXES` 的第二组卡包；不加载 `NGame`。仅构造全解锁隔离档时，首战会生成不同遭遇。设置 `STS2_PROBE_PROGRESS_SAVE=<progress.save>` 后，worker 只读反序列化玩家进度到自己的内存，首战自然恢复为记录中的 `SHRINKER_BEETLE_WEAK`。这说明同一种子还需要相同的发现与遭遇历史；探针没有修改玩家存档，也没有强制替换遭遇。

当前入口已连续重放这份 journal 的全部无缺口前缀：从 step 0 的涅奥选择开始，经两次原生 `EnterNextAct()` 进入第三幕，到第 45 层商店完成 step 700 的 `RED_MASK` 购买；随后只核对 step 701 缺口 decision 的 observation，并在执行未知购买前停止。输出为 `verifiedThroughGlobalStep=700`、`firstGapStep=701`、`gapBoundaryVerified=true`、`error=null`、`gameSceneLoaded=false`。两次完整复跑都得到相同边界，探针内计时约 1.83–1.98 秒。

这段前缀覆盖 44 次地图移动、21 场原生战斗、20 组战后奖励、两次跨幕、8 次休息点锻造、3 个宝箱、多个商店购买/删牌，以及 `DENSE_VEGETATION`、`AMALGAMATOR`、`BATTLEWORN_DUMMY` 等事件和集合选择。结果统计 `matchedCombatDecisions=497`、`matchedOutsideDecisions=203`。journal 在缺口前另有 3 个明确的 `cancelled` 结果：两次满药水槽领取返回 false，以及 step 537 在上一张致命牌仍排队时提交、随后由原生取消的战斗输入；探针按执行结果保留其无副作用语义，不把取消动作当成成功动作。

为保持原生 RNG 顺序，TestMode 商店现在补回正常游戏会消耗的三次药水价格随机数；事件战斗结束后则调用原生父事件恢复入口，因此“战损木偶”Setting 2 的两张随机升级仍由游戏的 `EventModel.Resume` 产生。无场景模式仅替代依赖 UI/震动/音频才能继续的外壳，牌组变化、奖励、购买、选牌、跨幕和事件结算仍调用原生命令并在下一记录边界核对 HP、金币、牌组、遗物和药水。

live journal 记录的是玩家点击瞬间；它允许上一张牌仍在 Play/pending，或回合开始第 5 张牌仍在抽牌动画时继续点击。高速执行器会立即结算这些原生动作，因此中间若干点击边界的 Hand/Play/能量并非逐字节相同。当前核验在每场战斗首个决策做完整边界比较，之后要求记录动作按卡牌身份与目标映射后仍为原生合法动作，并在战斗结束后要求局外状态重新完全一致。`497` 表示未被原生取消的战斗动作都按顺序合法执行且 21 场战斗最终重新汇合，不表示每个动画中间态全部相同。

复跑：

```bash
STS2_PROBE_PROGRESS_SAVE="/path/to/profile/saves/progress.save" \
STS2_PROBE_COLLECTOR_REPLAY="$PWD/artifacts/human-dataset/episodes/76561198812751539_IRONCLAD_A0_20261002T151050000Z_1ddd1912ef634cbeb9d331f52b79cf24.jsonl" \
  ./scripts/native-worker-macos.sh --mode whole-run-speed-probe --skip-build --timeout-seconds 120
```

这个入口明确标记为 `continuous-prefix-before-first-gap`。它没有猜测 step 701 的购买对象，也没有继续重放 gap 后的 step 702–786，因此仍未验证这份源记录的最终胜局，更不能把它恢复成无缺口训练轨迹；它也没有把 journal 的动画中间态改写成训练状态。

同一入口又完整重放无 coverage gap 的 A0 败局 `32a3822509ec4c9fa8d00017103daee6`。这局涅奥选择 `GOLDEN_PEARL`，没有卡包子界面；入口因此不再假设开局一定是 `SCROLL_BOXES + card_bundle_choice`，而是按下一条真实 observation 决定是否安装卡包选择器。228/228 个记录决策全部消费完毕，覆盖 13 次地图移动、9 场战斗、8 组奖励、3 个事件、2 次锻造和 1 个宝箱；最后在第 14 层 `BYGONE_EFFIGY_ELITE` 按原记录死亡。两次完整复跑均为 `verifiedThroughGlobalStep=227`、`matchedCombatDecisions=167`、`matchedOutsideDecisions=61`、`recordedOutcome=defeat`、`terminalOutcomeVerified=true`、`error=null`、`gameSceneLoaded=false`，探针内计时约 0.83–0.84 秒。结果保存在忽略文件 `artifacts/native-host/whole-run-speed-probe-collector-replay-32a38225.json`。

第三条铁甲 A0 胜局 `2d9fc925402f440eaba2c30e5c214966` 也已重放到自身缺口前。它的两个 `coverage_gap` 事件都没有顶层步号：一个是无法单独定位的手动弃药标记，另一个通过 `related_decision_id` 明确关联 step 495 的买遗物动作。入口现在会综合顶层步号、`invalidated_global_step`、失效 decision 列表及 decision ID 关联来定位边界，不再假设 gap 总有整数 `global_step`。本局因此从 step 0 连续执行到 step 494，并在执行 step 495 前核对 HP、最大生命、金币、层数、牌组、遗物和每个药水槽；三次严格复跑均为 `verifiedThroughGlobalStep=494`、`firstGapStep=495`、`gapBoundaryVerified=true`、`matchedCombatDecisions=270`、`matchedOutsideDecisions=225`、`error=null`、`gameSceneLoaded=false`，探针内计时约 2.05–3.18 秒。报告保存在忽略文件 `artifacts/native-host/whole-run-speed-probe-collector-replay-2d9fc925.json`。

这条前缀首次给高速探针提供了真实 Crystal Sphere 证据。step 459 选择 `UNCOVER_FUTURE` 后，探针截获原生 `CrystalSphereMinigame`，直接调用其公开工具、悬停和翻格入口；step 460–462 的三次大工具点击逐步核对全部 121 个格子的隐藏/高亮状态、已揭示物品类别和图标路径。原生结果产生 30 金币与 `FIRE_POTION`；记录中的满槽领取在 step 464 返回取消，随后 step 465 跳过剩余药水，step 466 的完成棋盘与事件结束状态一致。普通战后奖励中的 `discard_potion` 也改为按记录顺序调用原生 `PotionCmd.Discard`，因此 step 403–405 的“满槽领取失败、丢弃旧药水、再次领取”能够准确恢复；局外边界现在始终核对稀疏槽号和药水种类。

这次长路径还修正了两类跨进程身份映射：战斗中途召唤新敌人后，目标按怪物 model 与同类序号对应，不再依赖原生列表顺序；点击动画导致记录牌堆与高速结算牌堆暂时不同的选牌，则按候选的 model、升级、附魔和同类序号在原生候选中解析。三条回归轨迹 `1ddd1912...`、`32a38225...`、`2d9fc925...` 均在加入严格药水核对后重新通过。`2d9...` 的 step 495 之后仍包含缺失的人工弃药，探针没有猜测这次操作，也没有把该胜局恢复为完整 RTG 样本。

## 已测：两条连续新败局完整重放（2026-10-14）

同一 Steam 账号随后产生的 `a09f25fa7c8a451389be2eea0068be92` 与 `d9c27368c2f9467ca04bcc7869400dec` 均为铁甲 A0、无 reload、无 coverage gap 的第 17 层败局。第一局 233/233 个提交决策全部消费，其中 156 个战斗、77 个局外、1 个 `cancelled`；9 场战斗后在 `WATERFALL_GIANT_BOSS` 死亡。两次复跑均为 `verifiedThroughGlobalStep=232`、`terminalOutcomeVerified=true`、`error=null`、`gameSceneLoaded=false`，计时约 1.49 秒与 1.39 秒。报告位于忽略文件 `artifacts/native-host/whole-run-speed-probe-collector-replay-a09f25fa.json`。

该局还补充了 `SILVER_CRUCIBLE` 的空宝箱证据：第一次 `TreasureRoom` 的 `DoNormalRewards()` 与 `DoExtraRewardsIfNeeded()` 没有生成遗物，记录中的 `open_chest → proceed` 由原生房间完成；探针不再假设每个宝箱都必须领取遗物。第二个宝箱正常生成并领取 `TUNGSTEN_ROD`。

第二局 226/226 个决策全部消费，其中 156 个战斗、70 个局外；9 场战斗后在 `SOUL_FYSH_BOSS` 死亡。两次复跑均为 `verifiedThroughGlobalStep=225`、`terminalOutcomeVerified=true`、`error=null`、`gameSceneLoaded=false`，计时约 1.10 秒与 1.05 秒。报告位于忽略文件 `artifacts/native-host/whole-run-speed-probe-collector-replay-d9c27368.json`。

这两份 journal 没有附源玩家 `progress.save`。零局隔离档在第一局第 4 个问号房发生 `SUNKEN_TREASURY`/普通怪分叉，因为原生 `UnknownMapPointOdds` 会在 `UnlockState.NumberOfRuns == 0` 时对前三个问号房应用教学顺序；用 `STS2_PROBE_COLLECTOR_PRIOR_RUNS=1` 保持相同原生 RNG 后整局自然对齐。第二局最初也只在首领入口分叉成已见过的 `WATERFALL_GIANT_BOSS`；将第一局已经确证见过的 9 个 encounter 通过 `STS2_PROBE_COLLECTOR_SEEN_ENCOUNTERS` 输入原生 `UnlockState` 后，发现顺序自然生成记录中的 `SOUL_FYSH_BOSS`，没有直接替换房间或首领。报告保存 `priorRunsOverride`、`seenEncounterOverrides` 与最终 `nativeUnlockNumberOfRuns`，因此这项恢复条件可审计。若能取得源 `progress.save`，仍应优先使用 `STS2_PROBE_PROGRESS_SAVE`。

两份源日志都声明 `information_mode=unknown`、`no_sl_expected=false`。本次结果证明其动作序列可由匹配解锁历史的原生无场景管线重现；它不证明观察满足 no-SL 训练语义，也没有把日志改写成训练样本。

## 已测：同一种子的商店、休息点与宝箱分支

探针现在记录开局生成的可达地图，并能用 `STS2_PROBE_ROUTE=shop|rest` 选择另一条自然路线。两条分支从涅奥出发，都先按地图连接完成五场原生战斗及原生奖励，抵达第 7 层时 HP 为 39；没有跳层或直接改玩家状态。

- `shop`：进入原生 `MerchantRoom`，金币 175。最便宜的可购卡经 `MerchantEntry.OnTryPurchaseWrapper` 返回成功，金币 175→137、牌组 14→15；删牌服务经 `MerchantCardRemovalEntry.OnTryPurchaseWrapper` 和原生选择器返回成功，金币 137→62、牌组 15→14，选中的卡对象离开牌组。该购买方法在无 `NRun` 时不会调用 UI 的 `NMerchantInventory.OnCardRemovalUsed`；探针按该回调实际调用的原生 `MerchantCardRemovalEntry.SetUsed()` 标记服务已使用、售罄。药水槽当时 3/3 已满，原生药水购买返回 `false`，金币和药水不变。之后自然移动进入第 8 层精英战房间。
- `rest`：进入原生 `RestSiteRoom`，按游戏按钮实际使用的 `RestSiteSynchronizer.ChooseLocalOption` 选回血，HP 39→63，原生选项索引被记录；继续移动、打赢 `FOGMOG_NORMAL`、领取原生奖励，在第二个休息点再次回血 57→80。之后进入第 10 层宝箱 `TreasureRoom`。`DoNormalRewards()` 与 `DoExtraRewardsIfNeeded()` 生成候选遗物 `BEATING_REMNANT`；`PickRelicLocally(0)` 经过原生动作队列触发 `RelicsAwarded`，其结果指定获奖玩家和遗物。普通 UI 会消费该事件并调用 `RelicCmd.Obtain`；无界面探针按同一结果调用此原生命令，角色遗物数 2→3，随后进入下一地图战斗节点且保留遗物。

复跑命令如下，结果分别写入被 Git 忽略的 `artifacts/native-host/whole-run-speed-probe-legacy-shop.json` 与 `whole-run-speed-probe-legacy-rest.json`：

```bash
STS2_PROBE_ROUTE=shop ./scripts/native-worker-macos.sh --mode whole-run-speed-probe-legacy --timeout-seconds 120
STS2_PROBE_ROUTE=rest ./scripts/native-worker-macos.sh --mode whole-run-speed-probe-legacy --timeout-seconds 120
```

这两条分支验证了固定种子的房间入口与上述具体事务。商店有空药水槽时的购买、遗物购买、休息点锻造、宝箱多人抢夺及首领/胜局仍未验证；这些结果尚未接入终端、协议投影、共享 JSONL writer 或模型推理。

```bash
./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 120
./scripts/native-worker-macos.sh --mode whole-run-speed-probe-legacy --timeout-seconds 120 # 仅复跑历史夹具
```

## 下一道门槛

下一步需要用一条原始 journal 本身无 gap 的胜局验证最终终点，或提高简单策略的生存能力，让 `WinRun` 获得真实运行证据；再对照更多种子和其他角色的完整场景决策。随后记录胜败整局时间分布，并计入协议投影、共享 JSONL writer、模型推理和多进程调度。终端宿主继续用作人工操作与原生行为对照。遇到由界面回调推进的页面应找到并调用相同的原生逻辑入口、核对结果，不能跳过页面或伪造奖励。
