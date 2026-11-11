# SlayTheModel：交接说明

更新：2026-11-11（Claude 第三轮代码完成后，用户休息前）。本文件是**接手的唯一入口**：先读第 0–2 节了解现状，再按需查后面的约定、路径和命令。源码、日志与本文不一致时，以源码和原始日志为准，并更新本文。

---

## 0. 一分钟了解现状

**项目目标**：保留同学的 C++ 杀戮尖塔 2 模拟器（对齐原生 `v0.111.0 / 41cef1ea`），训练一个**局外策略网络**（选路、选牌、火堆、商店、事件等），铁甲战士、A0、单人。战斗由固定的 C++ 隐藏信息 MCTS 打（普通/精英 128 次、Boss 512 次），网络不管战斗。网络与训练框架在 `model/spire_rl/`（PPO，从零在线训练）。

**进度**：

| 阶段 | 状态 |
| --- | --- |
| 第一轮 `main-a0-s1` | 已完成（6,001 局，因旧门槛提前停）。诊断：[docs/claude-run1-diagnosis-and-fix-plan-20261110.md](docs/claude-run1-diagnosis-and-fix-plan-20261110.md) |
| P0 修复 + 第二批改动 | 已实施、已用于第二轮：NoSL 信息隔离（C++ ruleset v7）、网络去掉训练条件输入、按动作组的策略头、菜单循环保护、独立 critic、KL 早停改法、`last.pt` |
| 第二轮 `main-a0-s2` | 已完成（10,000 局，11.7 小时）。诊断：[docs/claude-run2-diagnosis-20261111.md](docs/claude-run2-diagnosis-20261111.md)；同学的交接：[docs/claude-run2-review.md](docs/claude-run2-review.md) |
| **第三轮** | **代码已写好、尚未在 GPU 上跑，尚未提交。** Codex 按用户要求补了分叉归档、critic 初始权重保底、分叉统计，CPU 35 项测试通过；本轮只读 s2。见第 2.3 节和模块 README 第 8 节 |
| 下一步 | 用户白天与同学商量是否跑第三轮；可能换别的模型接手。**未经用户指示不要启动、停止或修改远端训练** |

**验证成绩**（固定 200 个验证种子，随机采样评估）：

| 版本 | 平均层数 | 到第二幕 | 到第三幕 | 通关 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 0 局（随机初始化） | 10.96 | 1% | 0% | 0/200 |
| 第一轮 6,001 局 | 20.81 | 34% | 3% | 0/200 |
| 第二轮 8,021 局（`best.pt`） | 23.36 | 53% | 8.5% | 1/200 |
| 第二轮 10,000 局（`last.pt`） | 22.03 | 49.5% | 7% | 0/200 |

两轮之间模拟器和训练配置都变了，不是单因素对照；0/200 与 1/200 的差别不显著。

---

## 1. 接手第一步

1. 先看用户最新的话；本文件第 0–2 节；然后 [第二轮诊断](docs/claude-run2-diagnosis-20261111.md) 第 3–5 节和 `model/spire_rl/README.md` 第 8 节（修订记录）。
2. `git status`：远端与本地最后的提交都是 `50d72a6`。**此后全部工作（P0 修复、第二批、第三轮、所有诊断文档）都在工作区里未提交**，见第 7 节。第二轮在训练机上用的代码与当前工作区一致（第二轮 `config.json` 的配置指纹 `6f7cdf5dc22aa79b` 与当时代码重算一致），只是第三轮又在此基础上加了功能。
3. 看是否已经有第三轮输出（训练机上 `runs/main-a0-s3/`）。训练机上的权重（`best.pt`/`last.pt`）**不在这台 Mac 上**。
4. 第一、二轮的原始数据已拷到本机：`runs/training-review/main-a0-s1/`、`runs/training-review/main-a0-s2/`（含完整 `archive/`）。训练机上第二轮目录预计是 `runs/main-a0-s2/`。

---

## 2. 训练线

### 2.1 已确认的问题（两轮数据）

- **价值函数（critic）在线学不起来**。第一轮共享主干的价值头解释方差（EV）全程 ≤ 0。第二轮独立 19.6M critic：对实际后续层数，留出 EV 只有约 0.05–0.09。同族网络离线监督训练可到约 0.29；仅用层数、血量、幕的线性回归约 0.23–0.34。在线 critic 每次只在最新一批（约 2,300 个决策）上训练，表现为“拟合这一批、忘掉上一批”。
- **结果大部分是运气**：即使离线，最好的预测也只解释约三分之一的方差。单个决策从整局回报里分到的信号很弱，PPO 只学到“不依赖局面的整体偏好”。
- **火堆决策与血量无关**：第一轮约 1,000 局后不再回血（低血也 0/419）；第二轮几乎总回血，满血时（0.88）甚至比 HP<30%（0.78）还爱睡。受控分叉（第一轮 50 个第一幕 Boss 前火堆、同种子比较）：把升级改成回血，Boss 通过率 40%→61%（16 好 1 差）；Boss 搜索 512→2048 只到 48%。
- **路线偏向避战**：第一轮精英选择率 44%→0.7%。到第二幕的局里，第一幕打过 2 个及以上精英的到第三幕比例 17%，没打的 7%（相关，非因果）。
- **后期样本极少**：两轮合计 16,001 局，约 5,000 局到第二幕，548 局到第三幕，23 局通关。
- **网络结构本身能学**：模仿测试（用第一轮后期策略的选择作监督标签）中，约 5M 的同族网络平稳学到第一轮策略的 85%；32 步、8 步、无历史三者差别在噪声内，即 0.2B 中占大头的历史 Transformer 对复现该策略没有可测帮助，且 32 步历史让每个决策重算 32 个历史局面（第一轮推理占墙钟 48%）。
- **战斗器是上限之一**：第一幕 Boss 前满血也约三分之一过不去；第二幕大量死在普通战斗。

### 2.2 当前训练框架要点（`model/spire_rl/`，细节见模块 README）

- **网络 SpireNet**：实体 Set Transformer（地图连边消息传递）→ 因果历史 Transformer（最近 32 个决策，每步 g/z/a/r 四个 token；g 不含奖励档位，r 只含事件计数：新完成层数、新进幕、通关）→ 候选指针打分。策略 = P(动作组) × P(组内目标)，“取消已选网格牌”单独成组。预设 `main` 约 0.202B；独立 critic `CRITIC_SMALL` 约 19.6M，输出未来层数/50、未来进幕/2、通关概率三分量，任意 α 下线性组合成标量价值。
- **环境**：一次转移 = 一次真实局外选择；只有一个合法动作的界面自动执行；战斗由 `RunContext.play_combat_mcts()` 跑完；观察来自 `RunContext.macro_observation()`（宏观观察 v2，候选 5 维）。同一网格连续 64 个决策以 `menu_loop` 截断，单局上限 600 个决策；不代选、不代确认。
- **奖励**：`r_raw = 5×通关 + α×(0.05×新完成层 + 0.5×新进第二/三幕)`，训练值除以 5，γ=1、GAE λ=0.99。默认按 2k/4k/6k 局 α 从 1/0.5/0.2 降到 0，门槛不满足时默认 `hold`（继续训练）；第三轮可用 `--alpha` 固定单档。
- **PPO**：策略 lr 3e-5，最多 3 遍；KL 早停每 8 步在固定 512 个样本上测（>0.015 停），单小批 >0.04 也停；组熵额外奖励 0.01。critic lr 1e-4，每次更新 2 遍（当前批 + 最近 12 轮的回放各一份）。
- **保存**：`best.pt`（验证胜率严格提高时）和 `last.pt`（每次验证后、训练结束时），都含 critic，只存权重（不能精确断点续跑）。检查点格式 `spire_rl/3`；归档格式 `spire_rl.archive/3`（增加分叉审计记录，仍可读 /1、/2）。
- **监控**：每个 run 目录有 `metrics.jsonl`（每次更新一行）、`eval.jsonl`、`eval/val_ep*.json`、`dashboard.html`、`archive/rollout_*.npz`、可选 TensorBoard。重点字段：`value_ev_floors`、`rest_heal_rate_full_hp`、`rest_heal_rate_hp_below_50`、`entropy_group`、`target_passes`、`kl_stop_reason`、`menu_loops`，第三轮再加分叉相关字段（见 2.3）。

### 2.3 第三轮（已实现，未训练）

用户的选择：**保持端到端**（不做从中后期局面开始的起点课程），**接着第二轮模型继续训练**，用**离线价值先验**，加**成对分叉降噪**，增加训练量。实现：

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| 接着第二轮训练 | `train --init-checkpoint <last.pt>` | 载入策略与 critic 权重，网络形状取自该检查点；优化器重建；必须用新 run 目录。来源写入 `config.json` |
| 价值先验 | `pretrain-critic` → `train --critic-prior` | 本轮只读 s2；用真实后续事件训练 critic，最后 8 个文件留出评估。保存按层数+进幕 EV 合计最佳的权重（含训练前 epoch 0），报告含 `best_epoch`、`improved` |
| critic 回放 | `PPOConfig.critic_replay_rollouts=12` | 每次更新的 critic 训练混入最近 12 轮的数据 |
| 成对分叉 | `--fork-rest/--fork-map/--fork-card/--fork-seeds/--fork-coef` | `RunConfig.fork`。在火堆/地图/卡牌奖励按概率复制状态，各选项在**相同搜索种子与采样流**下前进到幕变化、2 场战斗或 40 个决策，剩余由 critic 估计；选项回报去均值、按本轮标准差归一，作为额外策略损失（火堆/卡牌按动作组，地图按具体路线）。分叉步不进 PPO 数据；被选动作总是选项 0 |
| 固定奖励档 | `--alpha 0.5` | 整轮单档，无切换。分叉需要短期可测的进度信号 |

本机验证：测试 28 项通过；分叉对主线对局无影响（同决策数、同层数），结果与线程时序无关；`pretrain-critic` 在 3 个真实第二轮归档文件上跑通（随机初始化 critic，2 个文件 1 遍后留出 EV 0.30）。**GPU 显存、耗时、实际效果均未验证。** 估计分叉使每局耗时增加 25–35%，1 万局约 14–16 小时（第二轮 11.7 小时）。

训练机命令（C++ 自第二轮后未改，不需重新编译；先把工作区代码同步过去）：

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
python -m pytest -q model/spire_rl/tests            # 当前为 35 项；无 GPU 且 CPU 不支持 BF16 时该项跳过

# 1) 价值先验（看输出里 held-out EV：floors 应明显高于 before）
python -m spire_rl pretrain-critic --archive runs/main-a0-s2/archive --init-checkpoint runs/main-a0-s2/last.pt \
  --out runs/critic-prior-s2.pt --epochs 2 --device cuda

# 2) 第三轮
python -u -m spire_rl train --preset main --device cuda --num-envs 8 --microbatch 4 --episodes 10000 --seed 3 \
  --run-dir runs/main-a0-s3 --init-checkpoint runs/main-a0-s2/last.pt --critic-prior runs/critic-prior-s2.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-seeds 2 --fork-coef 2
```

启动后先确认：`[val @0]` 接近第二轮末尾（约 22 层、约一半到第二幕）——说明接着训练成功；前几次更新后 `metrics.jsonl` 里 `forks_complete > 0`。时间不够可改 `--episodes 7000`。

验收（与第二轮最后 2,000 局比较）：`rest_heal_rate_full_hp` 明显下降且 `rest_heal_rate_hp_below_50` 保持较高；`fork_taken_was_best`（只统计唯一最优）结合 `fork_decisive` 样本数、`fork_tie_rate` 判断；在线 `value_ev_floors ≥ 0.25`；验证集到第二/三幕率与通关数。多项同时改动，结果不能归因到单项。

### 2.4 讨论过、但未采用或未实现

| 方向 | 状态 |
| --- | --- |
| 起点课程（从模型自己打到的第二/三幕开头开始训练） | 用户认为不够端到端，**暂不采用** |
| 奖励去掉每层奖励、只奖励打过 Boss 与通关 | 建议过，未采用 |
| 奖励遗物数量 | 用户放弃。若以后要做，建议基于势函数（持有遗物给奖励、结束时扣回），避免诱导钻空子 |
| 小策略网络（5–20M、短历史） | 模仿测试支持；第三轮因要接着 0.2B 权重而未采用。适合作为下一轮对照 |
| Decision Transformer（回报条件监督） | 骨架（因果历史 Transformer）还在，但去掉了目标回报输入与监督训练。因结果高度依赖运气、通关样本只有 23 个，**不建议作主方法**；可做“筛选后模仿”初始化 |
| 战斗网络（先验或叶子价值）+ MCTS | 未实现。第一幕 Boss 上 4 倍搜索只 +8 个百分点，建议先测后期战斗上限，再比较叶子价值与根先验 |
| 接入真实游戏 | 未实现。仓库有 10 月的旧 ArmG 实机接入（`src/SlayTheModel.Sts2.ModAdapter`、`scripts/armg_live_worker.py`，近似观察，只覆盖选牌/选路，未整局验收）。新网络需要模组导出完整公开状态、在 C++ 中重建 `RunContext` 再调用同一 `macro_observation`，并覆盖全部界面的动作映射。建议先做只显示建议的影子模式 |
| A10、自动升阶课程、精确断点续跑 | 未实现；CLI 没有 `--ascension` |

---

## 3. 代码与证据地图（相对仓库根）

| 内容 | 路径 |
| --- | --- |
| 训练包 | `model/spire_rl/spire_rl/`：`config.py` 全部超参与预设；`model.py` 网络；`data.py` 批构建与动作分组；`env.py` 宏观环境、奖励、菜单循环保护、`fork()`；`rollout.py` 并行采样、分叉；`ppo.py` GAE、PPO、critic 训练、分叉损失；`train.py` 训练循环、热启动；`pretrain.py` 离线 critic；`checkpoint.py`；`archive.py`；`metrics.py`/`dashboard.py`；`tools.py` 资源与环境检查；`__main__.py` CLI |
| 训练包说明与修订记录 | `model/spire_rl/README.md`（第 8 节按日期记录每批改动） |
| 导出配置（仅说明用，CLI 不读） | `docs/configs/spire-rl-{main,large-1b,large-0.7b}.json` |
| C++ 模拟器（唯一可编辑副本） | `artifacts/dev/cpp-native-aligned-20261031/`；宏观观察与战斗驱动 `simulator/src/macro_obs.cpp`；MCTS `simulator/src/mcts.cpp`；隐藏信息重采样 `simulator/src/battle.cpp` 的 `resample_hidden`；卡牌公开键 `simulator/include/sts2/common.h` 的 `card_public_key`/`card_canonical_less` |
| 训练原始数据 | `runs/training-review/main-a0-s{1,2}/`（未被 git 忽略，**不要提交**） |
| 第一轮分析（Codex） | `artifacts/analysis/main-a0-s1-20261110/`（`trajectory_decisions.npz` 等） |
| 第一轮分析（Claude） | `artifacts/analysis/claude-run1-20261110/`：`a1–a14.py` 统计、`boss_exp.py` 受控分叉、`bc_test.py` 模仿测试、`seaglass/` G3 快照检查 |
| 第二轮分析（同学） | `artifacts/analysis/main-a0-s2-review/`。注意其 `component_rtg` 列不是原始层数单位 |
| 第二轮分析（Claude） | `artifacts/analysis/claude-run2-20261111/`：`rest_pass.py`/`rest_an.py` 火堆、`critic_an2.py` critic、`value_test.py` 离线价值测试 |
| NoSL 修复证据 | 副本内 `validation/nosl-fix-20261110/README.md`（修复前审计 `validation/nosl-audit-20261110/` 保留未动） |

`artifacts/` 整体被 git 忽略（见第 7 节）。

---

## 4. 版本与身份

- 目标原生：`v0.111.0 / 41cef1ea`，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- C++：ruleset **`native-41cef1ea-port-v7`**（2026-11-10 NoSL 修复；第一轮用的是 v6）；公开观察 v15（布局未变）、动作 v14、快照 v10、ArmG 特征 6；**宏观观察 `MACRO_OBS_VERSION=2`**（候选 5 维，第 5 维为“取消已选网格牌”）。`PORT_SOURCE.json` 与副本 `agent/engine_identity.py` 已同步。
- `CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽）；卡牌奖励最多 4 选项（Lasting Candy）。
- `spire_rl` 检查点 `spire_rl/3`；`checkpoint.load` 校验格式和 `sim.identity()`（ruleset、宏观观察版本/维度/词表、阶段数、动作类型数），不校验二进制 SHA。critic 先验格式 `spire_rl.critic/1`，载入时校验 identity。
- 改变规则、观察或候选语义时：更新相应身份，并用新 run 目录做新实验；旧归档在新版本上不保证可逐步重放。

---

## 5. 用户约定（必须遵守）

- **不提交、推送、合并、发布**，除非用户明确要求；用户通常自己提交，需要时给命令和提交说明。
- **不启动、停止、重置用户正在运行的实验**；训练在用户的 GPU 机器上进行，本机只做代码、分析和 CPU 冒烟。
- **保留玩家真实选择**：选牌、跳过、确认、药槽满时换药等不能用随机、自动领取或静默丢弃替代；只有原生本身直接完成的选择（候选数 ≤ 必选数）才自动完成。菜单循环只能截断，不能代选。
- **不改**旧 ArmG / `agent/` 网络代码 / `scripts/armg_live_worker.py` / `model/spireformer/`（历史参考）。
- 保留同学的 C++ 模拟器并修正规则；不换成纯原生执行、不重写引擎、不靠删掉真实决策提速。网络需要的 C++ 接口只能新增，不能借机改规则。
- 不覆盖用户原始权重（`artifacts/reference/armg-live-20261031/latest.pt`）、不可变参考副本、旧证据和原生样例结果；新证据放新目录。
- 范围是铁甲单人。其余四角色牌池/机制已接入但不承诺整局完整；跨角色生牌会影响铁甲；多人机制不支持。
- 每批改动都跑测试，并在相应 README 记录；不要把“不崩溃”或元数据一致写成原生等价。
- 本机 torch 有 OpenMP 冲突：按命令临时设 `KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`，不改全局环境。多线程 torch 在本机会崩（`pthread_mutex_init failed`），用单线程。
- 用户偏好：端到端训练、让模型自己摸索策略；对 Transformer 先验 + MCTS、价值先验感兴趣。分析要基于原始数据，区分已确认、较强怀疑与证据不足。

---

## 6. 机器与命令

### 6.1 这台 Mac（仓库 `~/Workspace/SlayTheModel`）

- Python：`~/micromamba/envs/sts2/bin/python`（3.11.18）。**没有** `/opt/anaconda3`（另一台 Mac 才有，旧文档里的该路径不适用于此机）。
- 4 核、8 GB 内存：大批量数据分析或训练要分块，注意交换内存。
- C++ 构建：默认 Xcode 入口需要接受许可（不要代用户接受），改用 Command Line Tools 包装脚本，方法见副本 `validation/nosl-fix-20261110/README.md` 的“复现”节。
- 常用：

  ```sh
  PY=~/micromamba/envs/sts2/bin/python
  cd model/spire_rl
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
  KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m spire_rl smoke --run-dir <临时目录> --device cpu
  ```

- 本机 `sts2_sim` 扩展是 v7 新构建（SHA 见 NoSL 证据 README）。训练期 WSL 轨迹在本机重放时约 22% 会中途分叉（跨平台浮点差异），精确重放应在同一平台做。

### 6.2 用户的训练机（Windows `LegionB` + WSL2）

- RTX 5090（用户报 24 GB），Conda `slay`，Python 3.12.0，仓库 `/mnt/c/Users/yebohou/SlayTheModel`；`spire_rl` 以 `pip install -e` 安装（拉代码即生效）。第二轮 GPU 峰值约 5.8 GiB。
- C++ 改动后需在训练机重编：`CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py`，然后确认 `sts2_sim.ENGINE_RULESET_ID` 与 `MACRO_OBS_VERSION`。
- 该机 CPU 不支持 BF16 反向（oneDNN `avx2_vnni_2`），BF16 测试有 GPU 时在 GPU 上跑，否则跳过；训练不受影响。
- 训练命令见 2.3；TensorBoard：`tensorboard --logdir runs/<run>/tensorboard --host 127.0.0.1 --port 6006`。
- Windows 原生（非 WSL）训练未适配（`tools.py` 依赖 Unix `resource`）。

---

## 7. 提交与上传

- 根 `.gitignore` 忽略 `artifacts/`：已提交文件的改动 git 能看到，**新建文件看不到**，要按清单强制添加。清单 `docs/native-port-upload-paths-20261109.txt`（1864 条，含 NoSL 修复证据文本；不含编译产物、可执行文件、`obj/`）。**不要 `git add -f artifacts/` 整目录**，不要把原生安装备份、训练输出、权重、分析目录加入源码提交。
- **`runs/` 没有被忽略**，提交前必须排除；不要用 `git add -A`。
- 自 `50d72a6` 以来未提交的内容：`AGENTS.md`；`docs/` 下的诊断与交接文档（`claude-run1-diagnosis-and-fix-plan-20261110.md`、`claude-run2-diagnosis-20261111.md`、`claude-run2-review.md`、`claude-training-gaps-and-mcts-plan-20261110.md`、`mcts-nosl-audit-20261110.md`）、`docs/configs/`、`docs/native-port-upload-paths-20261109.txt`、`docs/st-dt-training-handoff-20261110.md`；`model/spire_rl/`（含新文件 `spire_rl/pretrain.py`）；C++ 副本中已跟踪文件的修改（`simulator/` 源码与头文件、`bindings.cpp`、`PORT_SOURCE.json`、`agent/engine_identity.py`、副本 `AGENTS.md`、`validation/build.json`）以及清单中的新证据文件。
- 参考命令（由用户执行）：

  ```sh
  git add AGENTS.md docs/*.md docs/configs docs/native-port-upload-paths-20261109.txt model/spire_rl
  git add -u artifacts/dev/cpp-native-aligned-20261031
  git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-upload-paths-20261109.txt
  git diff --cached --stat        # 确认没有 runs/、权重、归档
  git commit -m "spire_rl rounds 2-3: NoSL fix (ruleset v7), stage-free inputs, grouped policy, separate critic, critic prior, paired forks, warm start"
  ```

---

## 8. 模拟器（原生对齐）线

这条线目前不是重点，但规则约定仍有效。

**已完成（避免重做）**：种子/哈希/RNG 对齐、抽洗牌、手动选牌、牌实例状态、596 个原生卡牌数据导出；另外四个角色的牌池与机制（静默、故障机器人、亡灵契约师与原生样例差分 0 失败，储君只按源码）；遗物真实选择与持续状态（Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher 等，均有原生样例）；物理药槽空位；34 个缺失事件（含小游戏与专用战斗）；Aeonglass Boss；普通地图与 6 张原生录制地图逐点一致；epoch 内容过滤（生成器 `simulator/tools/gen_epoch_unlocks.py`）；原生费用修正栈；卡牌奖励选项钩子与 Lasting Candy；**2026-11-10 NoSL 修复**（重采样按全部卡牌字段规范化、公开排序补齐字段、`orbRng` 接入运行级 CombatOrbs 流）。详细记录：副本 `validation/round4-step2-resume-20261108/README.md`、`validation/round4-step3-events-20261108/README.md`、`validation/nosl-fix-20261110/README.md`。

**最近一次完整回归（2026-11-10，ruleset v7，本机）**：C++ 36 个程序全部通过；NoSL 原审计 15 项与新增 20 项 0 失败；Python（torch 桩）167 通过、10 失败、34 错误，失败集合与此前逐项相同（缺 torch/cmake 等环境原因）；1000 局贪心冒烟 0 异常、结果与上轮相同；地图 6/6。

**剩余事项**：
- 第三步起新增规则缺目标 DLL 的执行验证；尚无同种子、同进度、同决策的整局原生对照。11 月 3 日删过部分 fixture 宿主/缓存，恢复前不能生成新样例；旧样例结果在副本 `native-*-fixtures/`。出现差异以 DLL 为准改 C++，不改样例。
- NoSL 检查尚未在 Linux/WSL 上运行；CombatOrbs 映射未经 DLL 实测；怪物内部字段与所有已知顶牌来源未穷尽审计。
- C++ `double` 与原生 `decimal` 的取整边界；固定牌堆、遗物容量边界。
- `after_hand_drawn` 中 Mayhem 与遗物先后与原生不同（只影响非铁甲组合）。
- `nextTurnEnergy` / `nextTurnDraw` 观察字段恒为 0（占位）。
- 多人专用内容只保证单人不可达。

**工作方式**：先读目标原生源码（`artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/`）逐行对照；新 ID 一律追加在末尾，不复用 Grapple 槽；生成的表改生成器再重新生成；新增状态覆盖 clone、快照校验、公开观察和 Python 绑定，隐藏随机顺序不能泄漏到观察；改变随机序列的修复要写明。每批修完跑：C++ 全部程序、Python（torch 桩）、1000 局冒烟、地图对照；运行器会重写所在目录的结果，新一轮先复制运行器到新 validation 目录。

**关键路径**：

| 用途 | 路径 |
| --- | --- |
| 可编辑 C++ 副本 | `artifacts/dev/cpp-native-aligned-20261031/` |
| 原生高速探针（另一套执行实现，测试通过不代表 C++ 等价） | `artifacts/dev/rtg-probe-20261027/` |
| 目标原生反编译源码 | `artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/` |
| 不可变 C++ 基线 / 初始比较记录 | `artifacts/reference/alphazero-be401e8/`、`artifacts/reference/alphazero-be401e8-review/` |
| 固定原生安装备份（**不可清理，仅本机**，复核 `verify.py`） | `artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/` |
| 本机 Steam 安装 | `~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources` |

C++ 测试通过 `simulator/tests/port_root.h` 定位样例（先看 `STS2_PORT_ROOT`，再从当前目录向上找）；换机器先重新构建。

---

## 9. 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/claude-run2-diagnosis-20261111.md](docs/claude-run2-diagnosis-20261111.md) | **最新**：第二轮诊断、方向判断、第三轮实现与验收 |
| [docs/claude-run2-review.md](docs/claude-run2-review.md) | 同学（Codex）对第二轮的交接 |
| [docs/claude-run1-diagnosis-and-fix-plan-20261110.md](docs/claude-run1-diagnosis-and-fix-plan-20261110.md) | 第一轮诊断、P0 修复、受控 Boss 分叉、模仿测试（第 11 节） |
| [docs/claude-training-gaps-and-mcts-plan-20261110.md](docs/claude-training-gaps-and-mcts-plan-20261110.md) | Codex 对第一轮的分析与建议（G1–G11） |
| [docs/mcts-nosl-audit-20261110.md](docs/mcts-nosl-audit-20261110.md) | NoSL 修复前的审计 |
| `model/spire_rl/README.md` | 训练包实现、与设计的差异、命令、逐批修订记录 |
| [docs/st-dt-training-handoff-20261110.md](docs/st-dt-training-handoff-20261110.md) | 最初的 ST-DT（v3）设计；设计不等于实现 |
| [docs/local-cleanup-20261108.md](docs/local-cleanup-20261108.md) | 本地清理背景 |
