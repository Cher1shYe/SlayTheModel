> **当前状态（2026-11-09）：** C++ 原生规则对齐已推进到第三步之后（下文第 4 节）。AGENTS.md 旧版缺口表 A–F 已全部实现或核实。第三步及之后的改动**只按反编译源码移植，没有用 DLL 实测**，实测由他人负责。原生规则这一阶段已收尾。**之后用户要求进入网络设计**：按 `docs/st-dt-training-handoff-20261110.md`（v3）新写了局外策略网络与在线 PPO 训练框架 `model/spire_rl/`（见第 8 节），训练由用户在另一台 GPU 机器上跑。所有改动均未提交、未推送。
>
> 详细记录（按时间）：第二部分 `artifacts/dev/cpp-native-aligned-20261031/validation/round4-step2-resume-20261108/README.md`；第三步至第六步 `artifacts/dev/cpp-native-aligned-20261031/validation/round4-step3-events-20261108/README.md`。第七步（给网络加的 C++ 接口）记在同一个 README 末尾。网络与训练的设计、改动记录和命令见 `model/spire_rl/README.md`。旧 ArmG 网络不再沿用。本地清理背景见 [本地清理与交接说明](docs/local-cleanup-20261108.md)。

# SlayTheModel：当前任务与交接

更新：2026-11-09。此文件是用户要求给下一个 AI 的交接记录。
重点是**保留 C++ 模拟器的速度，把单人规则对齐到原生高速探针使用的游戏版本**（以铁甲战士为主）。
继续工作前先核对实际文件；历史结果只代表当时注明的版本和覆盖范围。

## 1. 用户目标与工作约定

- 当前任务（2026-11-09 起）：局外策略网络与训练框架 `model/spire_rl/`。训练不在本机跑，由用户拉到 GPU 机器上跑；本机只做代码、测试和 CPU 冒烟。参数预算 ≤1.5B，最好 1B，主模型 0.2B；sweet spot 约 8000–20000 局（未验证）。设计里不够简洁的地方可以改，但要在 `model/spire_rl/README.md` 第 4 节记下改了什么。
- 仍然**不要改旧的 ArmG / `agent/` 网络代码 / `scripts/armg_live_worker.py`**，也不要改 `model/spireformer/`（保留作历史参考）。本机 torch 的 OMP 冲突不修，运行时按命令加 `KMP_DUPLICATE_LIB_OK=TRUE`；开发副本里依赖 torch 的旧测试失败属预期。
- 游戏规则改动仍按下文原生对齐的约定做；网络需要的 C++ 接口只能新增，不能借机改规则。
- 用户选择保留同学的 C++ 模拟器并修正规则；不要换成纯原生执行、重写整套引擎，或通过删掉真实决策来提速。
- 主要范围是铁甲战士单人。另外四个角色的牌池和机制已在第二部分接入（见第 4 节），但不承诺其整局流程完整；跨角色生牌会影响铁甲。多人机制不在支持范围内。
- 保留玩家真实选择：选牌、跳过奖励、药槽满时换药等不能用随机选择、自动领取或静默丢弃替代。只有原生本身直接完成的选择（候选数 ≤ 必选数）才自动完成。
- 未获明确指令时，不提交、推送、合并分支、部署或发布模组。用户通常自己提交，需要时提供命令和 commit message。
- 不覆盖用户原始权重、不可变参考副本或旧证据（原生样例结果、旧轮次报告）。不改原生样例结果去迁就模拟器。
- 进度要随时记录到当前步骤的 README 进度日志里；每一批改动都要跑测试。

## 2. 真正工作的目录：不要改错副本

以下路径相对本仓库根目录：

| 用途 | 路径 |
| --- | --- |
| **当前可编辑 C++ 对齐副本** | `artifacts/dev/cpp-native-aligned-20261031/` |
| 原生高速探针/执行参照 | `artifacts/dev/rtg-probe-20261027/` |
| 目标原生反编译源码 | `artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/` |
| 不可变 C++ 基线 | `artifacts/reference/alphazero-be401e8/` |
| 初始原生比较记录 | `artifacts/reference/alphazero-be401e8-review/` |
| 用户原始权重（不要覆盖） | `artifacts/reference/armg-live-20261031/latest.pt` |

- 开发副本基线：`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`（`origin/alphazero`）。
- **原生探针与 C++ 模拟器是两个不同的执行实现。** 一方测试通过不代表另一方已等价。
- 根 `.gitignore` 忽略 `artifacts/`：已提交过的文件改动 git 能看到，**新建的文件看不到**，必须按清单强制添加。当前完整清单是 `docs/native-port-upload-paths-20261109.txt`（1815 条，含全部新文件和改过的已提交文件，不含编译产物和第三方库杂项；旧清单 `docs/native-port-step2-upload-paths.txt` 已过时）。上传命令（由用户执行）：

  ```sh
  git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-upload-paths-20261109.txt
  git add model/spire_rl docs/configs docs/st-dt-training-handoff-20261110.md docs/local-cleanup-20261108.md
  git diff --cached --stat
  git commit -m "native port steps 3-7 + spire_rl macro policy and PPO training framework"
  ```

  以后新增文件时，要把路径补进清单，再用 `git add --dry-run` 演练确认。
- 本机游戏安装路径：`/Users/yebohou/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources`。
- 11 月 3 日已删除原生 fixture 宿主/缓存，本机目前无法生成新的 DLL 样例。旧样例结果仍在副本根目录的 `native-*-fixtures/` 中，并被 C++ 测试使用。
- 测试通过 `simulator/tests/port_root.h` 在运行时定位这些样例：先看环境变量 `STS2_PORT_ROOT`，再从当前目录往上找。所以换机器或换目录后，在副本根目录下运行即可；在别处运行时设置 `STS2_PORT_ROOT`。换机器后要先重新构建一次。

## 3. 版本与当前接口

目标是本机原生 **`v0.111.0 / 41cef1ea`**，DLL SHA-256：
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`

当前开发副本（`PORT_SOURCE.json` 已同步）：

- ruleset `native-41cef1ea-port-v6`；公开观察 v15、动作 v14、快照 v10、ArmG 特征 6。旧权重和旧快照会被明确拒绝，没有迁移适配。
- `CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽）；卡牌特征 631 维、动作特征 727 维；公开观察 75988 维、公开战斗观察 49252 维。
- 卡牌奖励最多 4 个选项（`MAX_REWARD_CARD_CHOICES`，因 Lasting Candy）。
- v15 布局在第三到五步中多次扩展，一直未冻结、未用于训练，因此没有每次都升版本号。下次正式使用前应确认版本号与布局一致。
- 账号进度：`NativeProgressContext` 含角色解锁掩码、事件 epoch、Neow/Orobas/Darv/Underdocks 开关、遭遇发现记录、`aeonglassSeen`、`wongoPoints`、`revealedEpochs`（57 个 epoch 的 64 位掩码，位序见 `sts2_sim.native_epoch_names()`）。默认全部解锁；这些字段相互独立，接入存档时需逐项填写。
- `PORT_STATUS.md` 是第四轮第一部分的历史总览，未随后续步骤更新；以两份 README 为准。

## 4. 已完成内容：避免重做

更早的轮次（详见各自 validation 目录和 `docs/`）：种子/哈希/RNG 对齐、抽洗牌规则、手动选牌、牌实例状态、596 个原生卡牌模型数据导出、大量卡牌/遗物/事件效果修复、Crimson Mantle/Inferno 自伤累计、降级费用恢复、Touch of Orobas 等。

**第二部分（2026-11-08）**：
- 接入静默猎手、故障机器人、亡灵契约师、储君的牌池与专属机制。前三个与原生样例差分均 0 失败；储君没有原生样例，只按源码实现。
- 遗物真实选择与持续状态，均有原生样例并通过：Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher、Dusty Tome、Toy Box（蜡制）、Small/Large Capsule、Bone Tea、Fake Venerable Tea Set、Byrdpip/鸟蛋。
- 物理药槽空位模型；Delicate Frond、Alchemical Coffer。

**第三步：缺失事件（2026-11-09）**：
- 34 个缺失的原生事件全部实现，包括小游戏（Crystal Sphere、Tinker Time/Mad Science、Trial、Endless Conveyor）、专用战斗（Lantern Key、War Historian Repy、Battleworn Dummy、Fake Merchant、Punch Off）、TheLegendsWereTrue（Spoils Map 沙漏地图与 600 金任务）、ByrdonisNest。仅剩非原生的占位 `AROMA_PLACEHOLDER`。
- 事件池按原生声明顺序与 epoch 过滤；事件战斗按原生给房间奖励；新增多种附魔（Slither、Perfect Fit、Corrupted、Soul's Power、Sharp 等）。
- **Aeonglass Boss**：作为第三幕 Boss 接入（怪物与遭遇 ID 追加在末尾），并修正 Glory Boss 池与发现顺序。
- **普通地图生成与原生逐点一致**：用探针录制的 6 张原生地图对照，6/6 一致（`map-parity/compare_maps.py`）。

**第四步：旧缺口表收尾（2026-11-09）**：
- Prismatic Gem / Dingy Rug 按原生扩大卡牌奖励池；Splash 改用其他已解锁角色的攻击牌。
- 商店补全 5 件禁售遗物；Welcome to Wongo's 改为原生取遗物方式，补上积分与徽章；修正神秘票的发放时机。
- 账号 epoch 内容过滤：表格由 `tools/gen_epoch_unlocks.py` 从原生源码生成，覆盖卡牌、遗物、药水。
- 卡牌费用修改改为原生的逐条叠加：Snecko、Frantic Escape、各种"免费"。
- 玩家死亡后清空能力；必选且候选数 ≤ 必选数的选择一律直接完成；Dark Shackles 改为独立能力；补上 Royalties。
- 房间生成时机（C++ 进幕才生成，原生开局一次生成）：按源码推断结果相同，未改代码。配套的 24 局测试只是 **C++ 内部**两种方式的比较（血量设为 30000 以走到第三幕），不是与原生的对照。

**第五步：继续原生对齐（2026-11-09）**：
- 引擎里所有"本回合改费"都改为原生修正栈：Enlightenment、Stomp、Mummified Hand（四级候选）等，已无直接改写基础费用的代码。
- 新增 Imbued 附魔与 Electric Shrymp 选牌；修正开局抽牌堆中 Imbued/固有牌的顺序。
- 变牌（Primal Force、Entropy、战斗内变化）产生新的卡牌实体。
- 所有卡牌奖励都经过原生的选项钩子（Glitter、Silken Tress、Wing Charm、蛋类、Silver Crucible、Lava Lamp），并实现了 Lasting Candy。

**第六步：外部审阅收尾（2026-11-09）**：
- 修正旧代码遗留的基础稀有度蓝牌阈值（应为 < 稀有率 + 蓝牌率，低进阶蓝牌 37%，原来是 34%）。共两处：Lost Coffer 一类奖励，以及非战斗选牌网格。
- 测试换机器可用（`port_root.h`）；上传清单补全；开发副本内的 `AGENTS.md` 改为指向本文件。

**当前验证结果**：
- C++：36 个程序全部通过，其中 `native_step3_events` 1990 项。
- Python：167 项通过；其余 10 失败 + 34 错误均因缺 torch 或缺 cmake 的 `rules_test`。
- 1000 局贪心冒烟：0 异常、0 截断，150–170 局/秒（多次运行有波动）。这只是引擎吞吐，不代表模型水平。
- 普通地图 6/6 与原生一致。
- **尚无完整同种子、同进度、同决策的整局原生逐步对照。**

## 5. 已知剩余事项

- **DLL 实测 / 原生整局对照**：第三步起的全部改动只按源码移植，没有原生样例；原生对照由他人负责，尚未开始。出现差异时，以 DLL 结果为准修 C++，不改样例结果。
- C++ `double` 与原生 `decimal` 的取整边界；固定牌堆、遗物容量的边界。
- `after_hand_drawn` 把回合开始和自动出牌阶段合在一起：Mayhem（能力）在原生中排在遗物之前，C++ 排在之后，只影响非铁甲组合。
- `nextTurnEnergy` / `nextTurnDraw` 观察字段恒为 0（没有写入方），属于占位。
- 多人专用内容（如 Massive Scroll）只保证单人不可达，未按多人实现。
- 旧网络侧：`scripts/armg_live_worker.py` 手工拼接的观察仍是旧布局；实机桥接的选牌网格与 UI 执行未实测。新网络 `spire_rl` 目前只接 C++ 模拟器，没有接实机。

## 6. 工作方式

- 先读目标原生源码，逐行对照；不要用其他游戏版本的描述冒充目标规则。重要或不确定的交互，有条件时用实际目标 DLL 的受控样例核验。
- 先核对现状再动手：AGENTS.md 和审计记录可能过期，旧缺口可能早已修好。
- 新增 ID 一律追加在末尾，不复用 Grapple 槽，不重排旧 ID；同时恢复原生的候选顺序（编号顺序不一定等于抽取顺序）。生成的表要改生成器（`simulator/tools/gen_*.py`），并重新生成文件。
- 新增状态必须覆盖 clone、快照校验、公开观察和 Python 绑定。隐藏的随机顺序不能泄漏到观察里。
- 不改变原有行为的修复（例如只在持有某遗物时走新路径）优先；改变随机序列的修复要在记录里写明。
- 重点验证：结果、候选身份与顺序、RNG 消耗次数、选择的暂停与恢复、奖励跳过、伤害与复活、满槽行为。
- 每批修完：跑 C++ 全部程序、Python（torch 桩）、1000 局冒烟、地图对照，再写进 README。不要把"不崩溃"或元数据一致写成完整原生等价。

## 7. 本机复现入口

Python 环境：`~/micromamba/envs/sts2/bin/python`（3.11，conda-forge）。`/opt/anaconda3` 已不存在。torch 能装但 `import torch` 会因 OMP 冲突崩溃，按用户要求不处理。

以下命令的工作目录是 `artifacts/dev/cpp-native-aligned-20261031/`：

```sh
PY=~/micromamba/envs/sts2/bin/python
D=validation/round4-step3-events-20261108
$PY validation/build_local.py                    # 构建全部 C++ 测试、bench 和 Python 扩展（换机器后先跑一次）
$PY $D/run_cpp_tests.py                          # 36 个 C++ 程序，会重写 $D/cpp-tests.json
./validation/native_step3_events                 # 第三至五步的事件/规则测试
PYTHONPATH=$PWD/$D/python-no-torch/torch-stub $PY -m pytest -q -p no:cacheprovider --continue-on-collection-errors tests/
./validation/bench run 1000                      # 整局贪心冒烟
$PY $D/map-parity/compare_maps.py                # 普通地图与原生录制地图对照
$PY simulator/tools/gen_epoch_unlocks.py ../../native-source/v0.111.0/MegaCrit/sts2/Core   # 重新生成 epoch 表
```

构建使用 Apple clang 和 Python 3.11，复用对象文件，回归断言保持开启。本机未用 cmake 入口，也未验证 Windows 构建。新一轮工作建议新建 validation 目录保存日志，保留旧证据。

## 8. 局外策略网络与训练（`model/spire_rl/`）

完整说明（结构、与设计文档的全部差异、旧框架问题、训练机器上的命令、可视化）在 `model/spire_rl/README.md`。要点：

- 网络 SpireNet：实体 Set Transformer（含地图连边消息传递）+ 因果历史 Transformer（32 个决策点 × (g,z,a,r)）+ 候选对实体的交叉注意力与指针打分 + 线性价值头 + 3 个辅助头。预设 `main` 201,271,813 参数，`large-1b` 932,618,757，`large-0.7b` 705,966,597。
- 环境：一次转移 = 一次真实局外选择；战斗由 C++ `play_combat_mcts` 跑完（隐藏信息重采样，普通/精英 128 次、Boss 512 次）；只有一个合法动作的界面直接执行。观察来自新接口 `RunContext.macro_observation()`（`MACRO_OBS_VERSION=1`），可见性与公开观察相同。
- 训练：同步 PPO，奖励与 α/熵档位、门槛、验证（200 种子，每 2000 局）、测试（1000 种子）、检查点绑定模拟器身份，全部按 v3 文档；配置导出在 `docs/configs/spire-rl-*.json`。
- 可视化：每个 run 目录的 `dashboard.html`（按训练局数画图，标出档位切换与 sweet spot）、`metrics.jsonl`/`metrics.csv`（每次更新一行）、`eval.csv`、可选 TensorBoard。
- 保存：按用户要求只存验证最佳的 `best.pt`（仅权重），**不能断点续跑**，中断后换新目录重跑。
- 验证现状：18 项测试（含 CPU 上的 BF16 前向/反向）、tiny 端到端冒烟、0.2B 原尺寸 CPU 单步更新都通过。外部审阅指出的 BF16 类型冲突、ETA 漏算已修（见 `model/spire_rl/README.md` 第 8 节）。**GPU 显存、吞吐、一天 1 万局都未实测**，要在训练机器上先跑 `python -m spire_rl check` 和 10 个周期的短训练。
- 本机命令（在 `model/spire_rl` 下）：

  ```sh
  PY=~/micromamba/envs/sts2/bin/python
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=. $PY -m spire_rl smoke --run-dir <临时目录> --device cpu
  ```

- 训练机器要先用训练用的 Python 重新构建 `sts2_sim`（`validation/build_local.py`，Linux 设 `CXX=g++`；Windows 只能走 CMake，未验证），模块不在默认位置时设 `STS2_SIM_DIR`。
- 提交时：`model/spire_rl/` 和 `docs/configs/` 不在 `.gitignore` 内，正常 `git add`；两个新的 C++ 文件在上传清单里（1815 条）。
