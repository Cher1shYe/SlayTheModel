# SlayTheModel：当前任务与交接

> **2026-11-10 Claude 诊断与 P0 修复（最新）：** 已按 `runs/main-a0-s1/` 实际数据完成诊断并实施三个 P0（G1 NoSL、G2 输入错位、G3 菜单循环），新方案见 [第一轮诊断与修复方案](docs/claude-run1-diagnosis-and-fix-plan-20261110.md)。要点：critic 全程未学起来（在线解释方差 ≤ 0）；回血与多选“确认”两类稀有动作被学没；137 次更新只有 1,591 步 Adam。C++ 现为 ruleset `native-41cef1ea-port-v7`、宏观观察 v2（证据 `artifacts/dev/cpp-native-aligned-20261031/validation/nosl-fix-20261110/`）；`spire_rl` 检查点格式 `spire_rl/3`。**训练机必须重新构建 `sts2_sim` 并使用新 run 目录。** 同日应用户要求又实施了第二批：独立 19.6M critic、在固定样本上测 KL 的早停与 lr 3e-5、默认 gate hold、`last.pt`；用户准备用它在 GPU 上跑第二轮 10,000 局（建议目录 `runs/main-a0-s2`）。网络规模对照与战斗先验仍未实施。未提交、未推送。
>
> **2026-11-10 较早的训练交接：** 已收回 `main-a0-s1` 的 6,001 局日志和 137 个完整局外轨迹文件。用户要求 Claude **优先依据 `runs/main-a0-s1/` 的实际数据独立诊断，再给新修复方案；Codex 文档供参考，仅 G1 NoSL、G2 评估条件错位、G3 Sea Glass 菜单循环三个 P0 必做。** Transformer 先验＋MCTS 是用户偏好的候选方向，具体结构、规模、预算和其余 P1 改动由证据决定。先读 [训练缺口与诊断交接](docs/claude-training-gaps-and-mcts-plan-20261110.md)，其中的新证据覆盖下文和旧文档中“仅收到 val@0”等早期记录。**本次仅整理文档，新战斗网络与各项修复尚未实施。**

更新：2026-11-10。重点是保留 C++ 模拟器速度，核验铁甲单人规则，并训练新的局外策略网络。本文区分本地核验、用户反馈和讨论方案；接手时先核对实际文件与最新日志。

## 0. 接手先读：当前运行状态

| 项目 | 截至本次交接的状态 |
| --- | --- |
| 分支与提交 | `v111_SF1`；本地 HEAD 和远程跟踪引用 `origin/v111_SF1` 均为 `50d72a6`（模拟器更新及 ST-DT PPO 框架）。本次补充的交接文档尚未提交、推送；本次没有联网刷新远端引用。 |
| C++ 规则 | 旧缺口表已按后续记录实现或核实；第三步起主要是源码移植，**尚未完成对应 DLL 执行验证和完整原生整局对照**。不能写成“全部原生等价”。 |
| NoSL 信息隔离 | **2026-11-10 已修复（ruleset v7）**：原审计 15 项 0 失败（修复前 7 失败），新增 20 项检查 0 失败，C++ 36 程序通过。修复前审计见 [NoSL 审计](docs/mcts-nosl-audit-20261110.md)，修复证据在副本 `validation/nosl-fix-20261110/`。未做 DLL 实测；第一轮训练（v6）是在未修复的战斗器上跑的。 |
| 新网络 | `model/spire_rl/` 已实现 ST + 因果历史 Transformer + 在线 PPO；从零探索，学习局外选择，战斗由固定 C++ MCTS 执行。2026-11-10 P0 后：无档位输入、三分量价值头、按动作组分解的策略头、网格循环保护（细节见模块 README 第 8 节）。旧 ArmG / `model/spireformer/` 不再作为当前训练入口。 |
| 远端实验 | 用户在 RTX 5090（用户报 24GB）、Windows + WSL2 上启动 `main`（约 0.2B）、铁甲 A0、seed 1、10,000 局预算；Conda 环境 `slay`，Python 3.12.0。完整启动记录见第 7 节。 |
| 第一轮结果 | 6,001 局后因 gate（7 个获胜种子 < 10）停在第 2 档；3.04 小时；验证 0→2,034→4,033→6,001 局：平均 10.96→17.97→20.03→20.81 层，到第二幕 1%→34%，胜 0/1/0。日志与归档已收回到本机 `runs/main-a0-s1/`；本机没有 `best.pt`。 |
| 已收到的 GPU 证据（启动时） | 用户贴出 `[val @0] win 0.000 (0/200) floor 11.0 act2 0.01`。这是**训练前基线**，证明该次模拟器加载和 GPU 推理评估已运行；尚未收到 `[upd 1]`、资源检查报告或后续胜率，不能宣称 GPU 反向更新、吞吐或训练成功已验证。 |
| 实际输出目录 | WSL 项目根目录下 `runs/main-a0-s1/`，绝对路径 `/mnt/c/Users/yebohou/SlayTheModel/runs/main-a0-s1/`；不是 `model/spire_rl/runs/`。训练日志未同步到本机；用户当时表示继续训练，本记录不是远端实时进程状态。 |
| 尚未实现 | A10 的命令行训练/评估配置、自动升阶课程、`last.pt`、加载已有权重继续训练、完整断点恢复。此前只讨论了这些方案，不要当作已交付功能。 |
| 原生版本保全 | 已在 Mac 本地独立备份 `v0.111.0 / 41cef1ea` 完整安装并核对 440 个文件。原 DLL 没丢；部分 fixture 宿主/缓存曾删除，尚未重建。见第 2 节。 |

**接下来的工作边界：** 远端先核对新的更新日志和验证曲线；本地已完成固定原生版本保全，若继续原生差分工作，先恢复隔离 fixture 宿主再生成新的对照证据。课程、继续训练和保存策略属于待实施方案，本次只补交接文档，未修改训练代码或运行实验。不要为接手而重复启动、重置或更改用户正在运行的实验。

**阅读顺序与冲突处理：** 用户最新明确指令优先；本文件记录最新状态与约定，`model/spire_rl/README.md` 记录实际实现和命令，`docs/st-dt-training-handoff-20261110.md` 保留 v3 设计及状态注记。设计要求不等于实现或验收结果，源码、报告与文档不一致时先核验并记录，不能只凭设计宣称完成。

详细历史：第二部分见 `artifacts/dev/cpp-native-aligned-20261031/validation/round4-step2-resume-20261108/README.md`；第三至六步见 `validation/round4-step3-events-20261108/README.md`（位于同一 C++ 副本，第七步网络接口记在末尾）。清理背景见 [本地清理与交接说明](docs/local-cleanup-20261108.md)。旧“第二部分 WIP”仅为历史断点。

## 1. 用户目标与工作约定

- 当前路线：局外策略网络与训练框架 `model/spire_rl/`；大规模训练由用户在另一台 GPU 机器执行，本机做代码、验证与 CPU 冒烟。首轮先 0.2B，后续约 0.93B 需通过资源检查，备用约 0.7B；1.5B/2B 不在本轮配置中。8000–20000 局的 sweet spot 尚未验证。实现与设计有差异时在模块 README 第 4 节说明。
- 仍然**不要改旧的 ArmG / `agent/` 网络代码 / `scripts/armg_live_worker.py`**，也不要改 `model/spireformer/`（保留作历史参考）。本机历史 OMP 冲突按临时环境变量绕过，不修改全局环境。旧环境缺依赖的历史失败不代表当前测试可以忽略失败；新结果需据实际错误判断。
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
| 固定原生安装备份（不可清理，本机独有） | `artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/` |
| 当前局外训练包 | `model/spire_rl/` |

- 开发副本基线：`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`（`origin/alphazero`）。
- **原生探针与 C++ 模拟器是两个不同的执行实现。** 一方测试通过不代表另一方已等价。
- 根 `.gitignore` 忽略 `artifacts/`：已提交过的文件改动 git 能看到，**新建的文件看不到**，必须按清单强制添加。当前完整清单是 `docs/native-port-upload-paths-20261109.txt`（2026-11-10 追加 NoSL 修复证据后为 1864 条；原 1815 条，含全部新文件和改过的已提交文件，不含编译产物和第三方库杂项；旧清单 `docs/native-port-step2-upload-paths.txt` 已过时）。上传命令（由用户执行）：

  ```sh
  git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-upload-paths-20261109.txt
  git add AGENTS.md model/spire_rl docs/configs docs/st-dt-training-handoff-20261110.md docs/local-cleanup-20261108.md
  git diff --cached --stat
  git commit -m "native port steps 3-7 + spire_rl macro policy and PPO training framework"
  ```

  以上是源码上传参考，不是本次已执行操作；`50d72a6` 已包含前轮实现。以后新增源码时补充清单并先演练，按本次实际改动填写提交说明。**不要 `git add -f artifacts/` 整目录上传，也不要把原生安装备份、训练输出或权重加入源码清单。** 当前 `runs/` 未被根 `.gitignore` 忽略，训练机器提交前尤其需要检查，避免 `git add -A` 把输出全部加入。
- 本机游戏安装路径：`/Users/yebohou/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources`。
- 11 月 3 日删除过部分原生 fixture 宿主/缓存。原 DLL 仍在 Steam 安装、参考宿主和新备份中；恢复对应宿主前不要宣称已能生成新样例。旧样例结果仍在副本根目录的 `native-*-fixtures/` 中，并被 C++ 测试使用。
- **2026-11-10 保全证据：** 上表备份中的 `SlayTheSpire2.app` 是完整 macOS 安装快照，含 ARM64/x86_64 运行依赖、PCK 和当时已安装的模组，不是 Windows 安装包或无模组的纯净安装。440 个文件的 SHA-256 与复制前后的原安装一致，ARM64 `sts2.dll` 与第 3 节目标哈希一致；版本、Steam depot/manifest、模组清单和逐文件指纹见备份内 `manifest.json`，复核命令为 `python3 artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/verify.py`。逻辑大小约 2.24 GiB，以写时复制独立于 Steam 安装；本次未启动游戏、未重建 fixture。**这不是可再生缓存，清理必须保留；文件受 Git 忽略，仅在本机，拉仓库不会得到这份安装。**
- 测试通过 `simulator/tests/port_root.h` 在运行时定位这些样例：先看环境变量 `STS2_PORT_ROOT`，再从当前目录往上找。所以换机器或换目录后，在副本根目录下运行即可；在别处运行时设置 `STS2_PORT_ROOT`。换机器后要先重新构建一次。

## 3. 版本与当前接口

目标是本机原生 **`v0.111.0 / 41cef1ea`**，DLL SHA-256：
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`

当前开发副本（`PORT_SOURCE.json` 已同步）：

- ruleset `native-41cef1ea-port-v7`（2026-11-10 NoSL 修复；v6 为第一轮训练所用）；公开观察 v15（布局未变）、动作 v14、快照 v10、ArmG 特征 6；宏观观察 `MACRO_OBS_VERSION=2`（候选 5 维）。旧 ArmG 权重/引擎快照需按各自身份校验，尚无迁移适配；新 `spire_rl` 的权重校验范围见第 8 节，不能混同两套机制。
- `CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽）；卡牌特征 631 维、动作特征 727 维；公开观察 75988 维、公开战斗观察 49252 维。
- 卡牌奖励最多 4 个选项（`MAX_REWARD_CARD_CHOICES`，因 Lasting Candy）。
- v15 布局在第三到五步尚未用于训练时多次扩展，因此当时没有每次升版本号。当前新实验使用另一个 `MACRO_OBS_VERSION=1` 实体接口；已有实验启动后，继续改变规则、观察或候选语义必须更新相应身份并使用新实验，不能借历史“未冻结”说明静默修改布局。
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

**截至 2026-11-09 的规则验证记录（本次文档更新未重跑）**：
- C++：36 个程序全部通过，其中 `native_step3_events` 1990 项。
- Python：167 项通过；按该轮记录，其余 10 失败 + 34 错误归因为缺 torch 或缺 cmake 的 `rules_test`。这是当时环境的结果，不是当前机器测试应失败的保证。
- 1000 局贪心冒烟：0 异常、0 截断，150–170 局/秒（多次运行有波动）。这只是引擎吞吐，不代表模型水平。
- 普通地图 6/6 与原生一致。
- **尚无完整同种子、同进度、同决策的整局原生逐步对照。**

## 5. 已知剩余事项

- **NoSL / MCTS 隐藏信息隔离：** 2026-11-10 已修复，见副本 `validation/nosl-fix-20261110/README.md`（修复前证据 `validation/nosl-audit-20261110/` 保留未动）。剩余：Linux/WSL 上运行同一组检查、`CombatOrbs` 映射的 DLL 实测、未穷尽的怪物内部字段与已知顶牌来源审计。
- **DLL 实测 / 原生整局对照**：第三步起新增规则尚缺对应原生执行证据。历史曾安排由他人实测，当前没有收到完成报告；本地已保全固定版本，但恢复 fixture 宿主和新一轮差分尚未执行。出现差异时，以 DLL 结果为准修 C++，不改样例结果。
- C++ `double` 与原生 `decimal` 的取整边界；固定牌堆、遗物容量的边界。
- `after_hand_drawn` 把回合开始和自动出牌阶段合在一起：Mayhem（能力）在原生中排在遗物之前，C++ 排在之后，只影响非铁甲组合。
- `nextTurnEnergy` / `nextTurnDraw` 观察字段恒为 0（没有写入方），属于占位。
- 多人专用内容（如 Massive Scroll）只保证单人不可达，未按多人实现。
- 旧网络侧：`scripts/armg_live_worker.py` 手工拼接的观察仍是旧布局；实机桥接的选牌网格与 UI 执行未实测。新网络 `spire_rl` 目前只接 C++ 模拟器，没有接实机。
- **A10 / 课程（讨论，未实现）：** 模拟器接受 A0–A10，宏观观察已含进阶等级，环境会传入配置值；但全部现有预设为 A0，CLI 没有 `--ascension`，没有新框架的 A10 专项验收。讨论方向是按验证表现逐级升阶、保留低一阶复习、最终集中 A10，并使奖励衰减跟随学习表现。70/20/10 采样和 20%/5% 升阶门槛仅为讨论初值，未成为当前实验配置；原 v3 的按楼层截断课程也是历史备选。
- **保存 / 继续训练（讨论，未实现）：** 当前没有 `last.pt`、加载权重开始新训练的入口或完整恢复功能。已讨论以后保存 best + last，并支持重新初始化优化器的权重继续训练；这与精确断点续训不同，尚未改代码。不要臆造 `--resume`、`--init-checkpoint` 等已可用参数。

## 6. 工作方式

- 先读目标原生源码，逐行对照；不要用其他游戏版本的描述冒充目标规则。重要或不确定的交互，有条件时用实际目标 DLL 的受控样例核验。
- 先核对现状再动手：AGENTS.md 和审计记录可能过期，旧缺口可能早已修好。
- 新增 ID 一律追加在末尾，不复用 Grapple 槽，不重排旧 ID；同时恢复原生的候选顺序（编号顺序不一定等于抽取顺序）。生成的表要改生成器（`simulator/tools/gen_*.py`），并重新生成文件。
- 新增状态必须覆盖 clone、快照校验、公开观察和 Python 绑定。隐藏的随机顺序不能泄漏到观察里。
- 不改变原有行为的修复（例如只在持有某遗物时走新路径）优先；改变随机序列的修复要在记录里写明。
- 重点验证：结果、候选身份与顺序、RNG 消耗次数、选择的暂停与恢复、奖励跳过、伤害与复活、满槽行为。
- 每批修完：跑 C++ 全部程序、Python（torch 桩）、1000 局冒烟、地图对照，再写进 README。不要把"不崩溃"或元数据一致写成完整原生等价。

## 7. 两台机器与复现入口

### 7.1 Mac 开发机

2026-11-10 本地检查：`/opt/anaconda3/bin/python` 存在，版本为 **3.11.7**；此前文档中的 `~/micromamba/envs/sts2/bin/python` 在此机不存在。**同日另一台 Mac（仓库在 `~/Workspace/SlayTheModel`）情况相反**：没有 `/opt/anaconda3`，使用 `~/micromamba/envs/sts2/bin/python`（3.11.18）；默认 Xcode 入口需接受许可，构建用 Command Line Tools 包装脚本（见副本 `validation/nosl-fix-20261110/README.md`）。按实际机器选择解释器。涉及 torch 的已有本地验证使用临时 `KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`；不修改全局环境。不要把另一台机器的解释器路径照搬到这里。

以下为历史复现入口，工作目录是 `artifacts/dev/cpp-native-aligned-20261031/`。其中运行器会重写旧汇总；开展新一轮验证时先复制/调整运行器，将输出写到新 validation 目录，保留历史证据。

```sh
PY=/opt/anaconda3/bin/python
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

### 7.2 用户的 5090 训练机（WSL2）

Windows 主机 `LegionB`，通过 WSL2 使用 Conda `slay`（Python 3.12.0），仓库为 `/mnt/c/Users/yebohou/SlayTheModel`。硬件与环境信息来自用户反馈；未取得 CPU/RAM、CUDA/PyTorch 版本和 GPU 峰值报告。用户此前遇到 `No module named 'sts2_sim'`；扩展应在此环境重新构建，Mac/Python 3.11 的二进制不能复用。随后反馈的 `[val @0]` 说明该次模块已成功加载。

以下是**用户已经执行的启动记录，不是要求接手者再启动一次**：

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
python -u -m spire_rl train --preset main --device cuda --num-envs 8 --microbatch 4 --episodes 10000 --seed 1 --run-dir runs/main-a0-s1
```

已收到输出：

```text
checkpoint disk plan: {'best_checkpoint_gb': 0.81, 'needed_gb': 1.6, 'free_gb': 198.5}
[val @0] win 0.000 (0/200) floor 11.0 act2 0.01
```

磁盘规划不是显存测量；`val @0` 是参数更新前基线。下次先取实际 `metrics.jsonl` / `eval.jsonl` / 更新日志判断进度，不能把这两行外推成训练完成。TensorBoard 在另一个 WSL 终端运行：

```sh
conda activate slay
tensorboard --logdir /mnt/c/Users/yebohou/SlayTheModel/runs/main-a0-s1/tensorboard --host 127.0.0.1 --port 6006
```

用远程 Windows 浏览器打开 `http://localhost:6006`。主要看 `val/win_rate`、`val/reach_act2` / `val/reach_act3`、`val/floor_mean`；训练耗时与显存看 `train/seconds_per_episode`、`train/eta_hours`、`train/gpu_peak_gib`。验证每约 2000 局更新，CSV 在训练正常结束时导出。训练刚启动且尚未完成初始验证时没有曲线属预期；已有 `[val @0]` 后仍无曲线先检查日志目录。

## 8. 局外策略网络与训练（`model/spire_rl/`）

完整说明（结构、与设计文档的全部差异、旧框架问题、训练机器上的命令、可视化）在 `model/spire_rl/README.md`。要点：

- 网络 SpireNet：实体 Set Transformer（含地图连边消息传递）+ 因果历史 Transformer（32 个决策点 × (g,z,a,r)）+ 候选对实体的交叉注意力与指针打分 + 线性价值头 + 3 个辅助头。预设 `main` 201,271,813 参数，`large-1b` 932,618,757，`large-0.7b` 705,966,597（2026-11-10 前的计数）。2026-11-10 P0 后：g token 不含奖励档位、r token 只含事件计数；价值头输出未来层数/进幕/胜率三分量；策略 = P(动作组)×P(组内目标)（`type_factorized`）；同一网格 64 个决策后 `menu_loop` 截断，单局上限 600。
- 环境：一次转移 = 一次真实局外选择；战斗由 C++ `play_combat_mcts` 跑完（隐藏信息重采样，普通/精英 128 次、Boss 512 次）；只有一个合法动作的界面直接执行。观察来自新接口 `RunContext.macro_observation()`（`MACRO_OBS_VERSION=1`），可见性与公开观察相同。
- 训练：铁甲 A0、同步 PPO，无预训练数据。配置在 `spire_rl/config.py`，导出说明在 `docs/configs/spire-rl-*.json`；CLI 并不直接读取这些 JSON。验证使用 200 种子，每约 2000 局进行一次；冻结后用独立 1000 种子测试。实现与 v3 的差异以模块 README 为准。
- 奖励：原始通关 +5，进度为 α ×（完成新层 +0.05、进入第二/三幕各 +0.5），训练值除以 5。当前 α 按约 2k/4k/6k 启动次数从 1/0.5/0.2 降至 0；第二档要求至少 1 局到第二幕，纯通关档要求至少 10 个不同训练种子族通关。默认 `gate_policy=stop`，未达门槛会提前停止；`hold` 是显式可选项。该奖励课程不是 A0→A10 难度课程。
- 可视化：每个 run 目录的 `dashboard.html`（按训练局数画图，标出档位切换与 sweet spot）、`metrics.jsonl`/`metrics.csv`（每次更新一行）、`eval.csv`、可选 TensorBoard。
- 保存：仅 `best.pt`，包含权重、配置、配置指纹和部分进度信息，不含优化器/RNG 完整状态；**不能断点续跑，也没有加载已有权重继续训练的 CLI**。当前重新执行 `train` 会随机初始化。只在验证胜率严格提高时覆盖，并列保留较早模型；一直零胜时可能仍是初始权重，不是“最后模型”。
- 新包身份保护的实际范围：`checkpoint.load` 校验格式及 `sim.identity()` 的 ruleset、宏观观察版本/维度/词表、场景阶段数和动作类型数。二进制 SHA 写入 run 的 `config.json` 供追踪，**没有在加载权重时强制比较源码/二进制 SHA 或重新校验配置指纹**；不要把旧 ArmG 身份绑定或 v3 的更严格设计当作这里已经实现。
- 验证现状：本地 18 项测试（含 CPU BF16 前向/反向）、tiny 闭环、0.2B 原尺寸 CPU 单步更新已有通过记录；BF16 类型冲突、ETA 漏算和横轴覆盖问题已修。GPU 方面仅收到第 0 节的初始评估输出；反向更新、峰值显存、吞吐、一天 1 万局以及学习后的胜率尚缺报告。已有远端实验先取日志，不为补短测而擅自中断重开。
- 本机命令（在 `model/spire_rl` 下）：

  ```sh
  PY=/opt/anaconda3/bin/python
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m spire_rl smoke --run-dir <临时目录> --device cpu
  ```

- 训练机器用同一 Python 重新构建 `sts2_sim`（WSL2/Linux 使用 `CXX=g++ python validation/build_local.py`）；若整目录从 Mac 拷来，先移走 `validation/obj` 的旧平台缓存。模块不在默认位置时设 `STS2_SIM_DIR`。Windows 原生训练未适配：除扩展构建外，新包 `tools.py` 还依赖 Unix 的 `resource`，仅编译出 `.pyd` 不等于可训练。
- 提交时：`model/spire_rl/` 和 `docs/configs/` 不在 `.gitignore` 内，正常 `git add`；两个新的 C++ 文件在上传清单里（1815 条）。
