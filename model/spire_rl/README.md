# spire_rl：局外策略网络与在线 PPO 训练

2026-11-10 状态补充。按 `docs/st-dt-training-handoff-20261110.md`（v3）实现，并按用户后续要求简化保存：铁甲 A0 单人，网络负责局外选择，战斗交给固定的 C++ 隐藏信息 MCTS，从随机初始化开始在线 PPO。
本文记录**实际实现了什么**、**与设计文档不同的地方**、**旧框架的问题**，以及**在训练机器上怎么跑**。

> 状态：代码、测试、端到端 CPU 冒烟、0.2B 原尺寸的 CPU 前向/反向/优化/保存都已跑通。
> 用户已在 5090 / WSL2 / Conda `slay`（Python 3.12.0）启动 `main`、A0、10,000 局预算，并反馈初始验证：`[val @0] win 0.000 (0/200) floor 11.0 act2 0.01`。这是训练前基线；尚未收到 `[upd 1]`、GPU 资源报告或学习后的验证成绩，不代表 GPU 反向更新、训练吞吐或“一天一万局”已验证。
> 此次实验从项目根目录启动，实际输出为 `/mnt/c/Users/yebohou/SlayTheModel/runs/main-a0-s1/`。接手先查现有日志，不重复启动；最后收到的反馈不是远端实时进程状态。完整交接见根 `AGENTS.md` 第 0、7 节。
>
> **2026-11-10 第一轮之后的 P0 修改（本 README 已按新代码更新）**：网络输入去掉奖励档位与 α 加权奖励；价值头改为三分量；策略头按动作组分解；网格循环保护；新监控项。依据与新方案见 [`docs/claude-run1-diagnosis-and-fix-plan-20261110.md`](../../docs/claude-run1-diagnosis-and-fix-plan-20261110.md)。旧 `best.pt`（格式 `spire_rl/2`）不能加载到新结构；C++ 也已改动（ruleset v7、宏观观察 v2），训练机需重新构建 `sts2_sim`。

## 1. 目录

| 文件 | 作用 |
| --- | --- |
| `spire_rl/config.py` | 全部超参数（一个可序列化的 `RunConfig`）；预设 `main`/`large-1b`/`large-0.7b`/`tiny` |
| `spire_rl/sim.py` | 定位并加载 C++ 模块 `sts2_sim`；`identity()` 是检查点绑定的模拟器身份 |
| `spire_rl/env.py` | 宏观环境：一次转移 = 一次真实局外选择；奖励记账；辅助标签 |
| `spire_rl/model.py` | SpireNet：实体 Set Transformer + 因果历史 Transformer + 候选指针打分 + 价值/辅助头 |
| `spire_rl/data.py` | `Episode` 与 `collate`（按目标时刻组历史窗口，批内去重状态） |
| `spire_rl/ppo.py` | GAE、PPO 更新、概率重算核对 |
| `spire_rl/rollout.py` | 多线程环境 + GPU 批量推理的采样器 |
| `spire_rl/train.py` | 同步闭环：采样 → GAE → 更新 → 记录 → 验证 → 保存；奖励档位与门槛 |
| `spire_rl/checkpoint.py` | 只存最佳权重 `best.pt`（绑定模拟器身份，不兼容就拒绝；读取一律先到 CPU） |
| `spire_rl/metrics.py`、`dashboard.py` | 按步记录（JSONL、可选 TensorBoard）与静态 HTML 仪表盘 |
| `spire_rl/archive.py` | 轨迹归档（与 PPO buffer 分开，供以后离线/DT 实验） |
| `spire_rl/tools.py` | 环境检查、GPU 显存/耗时检查、磁盘规划、两档成对比较 |
| `tests/` | 文档第 9 节要求的验证 + 2026-11-10 P0 与第二批回归（26 项） |

C++ 侧新增（在 `artifacts/dev/cpp-native-aligned-20261031/simulator/`）：
`include/sts2/macro_obs.h`、`src/macro_obs.cpp`，以及 `bindings.cpp` 里的 `RunContext.macro_observation()`、`RunContext.play_combat_mcts()`、`sts2_sim.macro_vocab()`。没有改任何游戏规则。

## 2. 在训练机器上运行

### 2.1 准备

1. 当前源码分支为 `v111_SF1`，前轮实现已提交为 `50d72a6`。`artifacts/` 的新增源码需按上传清单强制添加，不能强制添加整目录。训练输出 `runs/` 当前未被根 `.gitignore` 忽略，提交前单独检查；见根 `AGENTS.md`。
2. 在 WSL2 激活已有 `conda activate slay`，用**训练时要用的那个 Python** 构建模拟器（扩展模块与平台、Python 版本绑定）。以下从项目根目录执行：
   ```sh
   CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
   ```
   若从 Mac 拷贝了整个目录，先移走 `validation/obj` 的旧平台缓存。Windows 原生训练尚未适配：除 C++ 构建外，Python 的 `tools.py` 还依赖 Unix `resource`；当前使用 WSL2/Linux。
   模块不在默认位置时设 `STS2_SIM_DIR=<含 sts2_sim*.so 的目录>`。
3. 在项目根目录安装：`python -m pip install -e "model/spire_rl[tensorboard,test]"`。已有兼容依赖可复用；项目的 `torch>=2.1` 最低声明本身不保证 5090 支持，需确认实际安装的 CUDA 构建能运行 GPU/BF16。

### 2.2 命令（统一在项目根目录下）

下列 `train` 是新实验启动参考；用户已启动 `main-a0-s1`，尚未反馈后续日志，不要重复启动同一个实验。所有 `runs/...` 均相对于执行命令时的工作目录。

```sh
python -m pytest -q model/spire_rl/tests              # 18 项测试，CPU 即可
python -m spire_rl params --preset large-1b           # 参数量与 16 字节/参数 估算
python -m spire_rl check --preset main --device cuda --out check-main.json
python -m spire_rl check --preset large-1b --device cuda --out check-1b.json
python -m spire_rl smoke --run-dir runs/smoke --device cpu  # 极小端到端闭环

# M3 短测：只跑 10 个采样-更新周期，看仪表盘的每局秒数与 ETA（短测目录用完可删）
python -m spire_rl train --preset main --device cuda --run-dir runs/main-probe --stop-after-updates 10
# 本次正式实验的启动配置；新实验需使用新目录，当前没有断点恢复或加载权重继续训练入口
python -u -m spire_rl train --preset main --device cuda --num-envs 8 --microbatch 4 --episodes 10000 --seed 1 --run-dir runs/main-a0-s1

# 冻结后在 1000 个测试种子上评估，两档成对比较
python -m spire_rl eval --checkpoint runs/main-a0-s1/best.pt --split test --device cuda --out test-main.json
# 大档实验尚未启动；以下只在对应权重实际存在后使用
python -m spire_rl eval --checkpoint runs/1b-s1/best.pt --split test --device cuda --out test-1b.json
python -m spire_rl compare test-main.json test-1b.json
```

常用参数：`--num-envs`（并行环境数，默认 8，按 CPU 核数调）、`--microbatch`（只影响显存）、`--seed`（训练随机种子，复验用 3 个）、`--gate-policy hold`（门槛不满足时停留在当前档而不是停下）。

当前没有 `--ascension`、`--resume` 或加载已有权重开始训练的参数；配置 JSON 是导出记录，CLI 不会读取它们。默认学习门槛未满足时会提前停止，10,000 局是预算上限。

### 2.3 可视化（按步数）

每个 run 目录里：

| 文件 | 内容 |
| --- | --- |
| `dashboard.html` | 自包含网页，每次更新后重写，浏览器每 120 秒自动刷新；不需要联网或服务器 |
| `metrics.jsonl`、`metrics.csv` | 每次 PPO 更新一行（约 40 个指标，含每局原始奖励 `reward_raw_mean`、平均楼层 `floor_mean`）；CSV 在训练结束时导出 |
| `eval.jsonl`、`eval.csv`、`eval/val_ep*.json` | 每次验证一行；详细文件含每个种子的结果 |
| `tensorboard/` | 装了 tensorboard 时自动写，`tensorboard --logdir runs` |

横轴统一是**已启动的训练局数**（文档的预算单位），同时记录 `updates`、`transitions`。仪表盘分三组：

- 结果：胜率（训练 + 200 个固定验证种子的散点，含 95% Wilson 区间）、平均楼层、到达第二/三幕比例、原始奖励；
- 学习：熵、KL、clip 比例、价值损失、策略损失、三个辅助损失、梯度范数；
- 资源：每局秒数（从开始到现在的全部墙钟 ÷ 已启动局数，含更新、验证、保存）、各阶段墙钟（环境+MCTS／推理／更新）、GPU 峰值显存。ETA 用同一个每局秒数推算。

图上竖线是奖励档位切换（标出新的 α），浅色带是 sweet spot 8k–20k（标注为先验估计，尚未验证）。`python -m spire_rl dashboard --run-dir <dir>` 可以离线重画。

当前远端实验在另一个 WSL 终端中使用：

```sh
conda activate slay
tensorboard --logdir /mnt/c/Users/yebohou/SlayTheModel/runs/main-a0-s1/tensorboard --host 127.0.0.1 --port 6006
```

在远程 Windows 浏览器打开 `http://localhost:6006`。强度优先看 `val/win_rate`，早期辅以 `val/reach_act2`、`val/reach_act3`、`val/floor_mean`；训练奖励会随 α 改变，不能单凭奖励或 loss 判断强弱。初始 200 局验证完成前可能暂无曲线；有 `[val @0]` 后仍无数据应检查日志目录。`check` 不生成训练曲线。

### 2.4 输出文件与磁盘

| 文件 | 内容 | 0.2B 大小 | 1B 大小 |
| --- | --- | ---: | ---: |
| `best.pt` | 验证胜率最高的权重（并列保留更早的），只在验证刷新最佳时覆盖；这是唯一的模型文件 | 0.8 GB | 3.7 GB |
| `archive/rollout_*.npz` | 轨迹归档，每轮一个压缩文件 | 待实测 | 同左 |

训练结束后，学习曲线全部在 `metrics.jsonl`/`metrics.csv`/`eval.csv`/`dashboard.html` 里，不依赖任何模型文件。启动时检查 `best.pt` 所需磁盘（不含归档），不够就拒绝；同一目录已有训练记录时拒绝启动，避免混写。归档可以在 `RunConfig.archive_trajectories` 关掉。

`best.pt` 不是最后模型：只在验证胜率严格提高时更新，一直零胜时可能仍是初始权重。当前没有 `last.pt`，没有保存的最后权重在进程结束后无法取回。已讨论以后保存 best + last、加载权重并新建优化器继续训练，但这些功能尚未实现。

## 3. 网络

```
当前公开实体 ─► 嵌入(kind, id, 数值) ─► 地图连边消息传递×2 ─► ISAB×2 ─► 实体表示 E_t
                                                                  └─► PMA ─► 局面摘要 z_t
历史 token (g_i, z_i, a_i, r_i)×32 ─► 因果 Transformer (Pre-LN) ─► 读 z_t 位置 ─► h_t
   g = 任务 + 界面阶段（无奖励档位）；r = 该步发生的 [新完成层数, 新进幕数, 胜利]（无 α）
当前候选(类型, 数值, 指向的实体) ─► 对本状态 E_t 交叉注意力 ─► c_k
组内分数 s_k = 打分器(h_t, c_k)（点积 + MLP）
组分数 u_g = 打分器(h_t, 组嵌入_g)，组 = 动作类型（“取消已选网格牌”单独一组）
log π(k) = log softmax_g(u)[组(k)] + log softmax_{组内}(s)[k]   （type_factorized=False 时退回单层 softmax）
h_t ─► 线性价值头，3 个输出：未来层数/50、未来进幕数/2、胜率；V_α = 加权和；h_t ─► 3 个辅助 logit
```

| 预设 | ST | 历史网络 | 参数量（实测） | microbatch | lr |
| --- | --- | --- | ---: | ---: | ---: |
| `main` | 512 / 2 ISAB / 8 头 / 32 诱导点 | 1024 × 14 层，16 头 | 201,271,813 | 4 | 1e-4 |
| `large-1b` | 同上 | 1536 × 32 层，24 头 | 932,618,757 | 1 | 3e-5 |
| `large-0.7b` | 同上 | 1536 × 24 层，24 头 | 705,966,597 | 1 | 3e-5 |

参数量统计全部唯一参数（嵌入、ST、历史主干、动作/价值/辅助头）。表中是 2026-11-10 之前的实测值；分组头与三分量价值头约增加 0.8M（`main` 仍在 0.19–0.21B 测试范围内）。

**观察（C++ `macro_observation`，版本 2；v2 只在候选上加了第 5 维“取消”标记）**：每个可见对象一个实体 token：全局、场景上下文、牌组每张牌（重复牌各自保留，无位置编码）、遗物、药水槽（含空位）、地图节点（+ 连边数组）、Boss、商店/奖励中的牌/遗物/药水、奖励项、事件选项、水晶球格子。每个实体 = 类别、ID（按类别分表嵌入）、80 维归一化数值。归一化写在 C++ 里，由 `MACRO_OBS_VERSION` 绑定进检查点。
可见性与公开观察一致：未打开的卡牌奖励只显示为一个奖励槽，不暴露其中的牌；未揭开的水晶球格子 ID 为 0；商店/奖励内容只在对应界面出现。不输入种子、RNG、隐藏牌序。

**候选**：每个合法动作 = 类型 + 5 维数值（价格、买不起、序号、有指针、是否为取消已选网格牌）+ 最多两个实体指针（例如 选路→地图节点，买牌→商店牌，删牌/升级→牌组里那一张，事件选项→选项与其遗物）。网络只给本次请求的候选打分，执行时用 C++ 保存的原始动作描述符。

## 4. 与设计文档的差异（全部改动记录）

### 4.1 新写了包，没有在 `model/spireformer` 上改

文档建议复用 `spireformer` 的编码器和动态候选逻辑。核对后发现问题较多（见第 5 节），改造量接近重写，而且旧代码以监督学习为中心。新包约 2,600 行，职责单一；`spireformer` 原样保留作历史参考，没有改动。

### 4.2 结构上的补充或解释

| 项 | 文档 | 实现 | 理由 |
| --- | --- | --- | --- |
| 地图关系 | "边 token 或关系注意力偏置" | ST 之前对地图连边做 2 轮父/子均值消息传递 | 节点重排时连边同步重排；比给每个注意力头加偏置简单 |
| 候选打分 | "共享候选打分器" | 点积 + MLP([q, c, q·c]) | 点积给出初始可用的相似度，MLP 处理非线性；末层初始化很小，初始策略接近均匀（实测偏差 < 3e-4） |
| 历史 g token | 任务、阶段、奖励档位 | 阶段 = 界面×是否选牌网格（18 种）；**2026-11-10 起不再输入奖励档位** | 任务只有 WIN_RUN，编码成常量嵌入；档位输入会让验证/部署用到未训练的条件（G2） |
| r token | 已获奖励 | [新楼层数, 新幕数, 胜利]（2026-11-10 前还含 r_train） | 只记发生的事件，不含随 α 变化的数值；只用于此前步，目标步的 a、r 被 mask |
| 位置 | — | 窗口内位置 + 绝对决策序号（截到 512） | 区分开局与后期 |

### 4.3 环境与奖励

- **只有一个合法候选的界面直接执行，不算转移**（例如唯一的"继续"）。文档说"每次真实选择"；这些不是选择，记录它们只会稀释 PPO 样本。计数在 `forced_steps`。
- 楼层奖励：房间完成（回到地图界面或胜利）才记，按"已领取的最大完成楼层"单调去重；死在战斗中的那层不算；开局到第一次决策前的进度不补发。幕奖励按最大幕单调去重。
- 战斗：`play_combat_mcts` 在 C++ 内跑完整场战斗（释放 GIL，多环境并行），隐藏信息重采样模式，每次只执行第一步再重搜；搜索种子 = 局的搜索种子 + 104729×战斗序号，与游戏 RNG 独立。普通/精英 128 次、Boss 512 次。
- 工程失败（`FAILURE`）不进入 PPO，单独计数；单轮失败超过 max(2, 2%) 时训练直接报错停下，不靠丢样本继续。
- 截断（宏观步数上限 600、同一网格连续 64 个决策的 `menu_loop`，或模拟器截断）用末状态 V 自举一次，trace 为 0。网格保护不代选、不代确认、不删选项。第一轮的上限是 3000，Sea Glass 循环三次各占当批 57–64% 样本。

### 4.4 训练流程

- **KL 提前停止**：一次优化步后 approx KL > 1.5 × 目标（0.015）就结束本轮更新（文档只说"按 KL 提前结束"）。
- **门槛不满足的默认行为是停下**（`gate_policy="stop"`，文档"停下诊断"）；`hold` 是可选项。
- **只保存最佳权重（用户 2026-11-09 要求）**：原 v3 的最新恢复点 + 最佳 + 里程碑要求已被简化。`best.pt` 保存权重、配置、指纹和部分进度，不含优化器/RNG；**不能断点续跑，也没有权重继续训练入口**，重新执行 `train` 会随机初始化。各验证点胜率持续写入 `eval.jsonl`，正常结束导出 `eval.csv`。α=0 档持续到预算结束，预算在启动时用 `--episodes` 定好。
- **身份校验范围**：加载时比较检查点格式、ruleset、宏观观察版本/维度/词表、场景阶段数与动作类型数。run 的 `config.json` 记录二进制 SHA，但权重加载没有强制比较源码/二进制 SHA，也未重新验证保存的配置指纹；不能将此等同于原 v3 的完整绑定要求或旧 ArmG 的身份校验。
- **采样随机流按局独立**：每局用 (采样种子, 局号) 派生自己的随机流，结果不依赖线程完成顺序。验证用固定采样种子，同一模型两次验证结果一致（有测试）。
- **轨迹归档**：文档第 8 节要求保存原始公开实体、候选、动作、旧概率/价值、奖励分项、终止分类、行为版本；每轮写一个 `archive/rollout_*.npz`，窗口按索引重建，不重复存前缀。归档从不回灌 PPO。
- 激活重计算只在 CUDA 上启用；BF16 只在 CUDA 上启用，CPU 一律 FP32。

### 4.5 文档中其他地方的说明

- 文档链接的旧奖励 JSON（`docs/configs/st-dt-reward-review-20261110.json`）在仓库里不存在。新配置由代码导出：`docs/configs/spire-rl-{main,large-1b,large-0.7b}.json`（`python -m spire_rl config --preset ...` 可重新生成）。
- 没有实现课程学习、长度分桶、KV cache。模拟器和环境接口有 A0–A10 基础，实体输入含进阶，但全部预设为 A0，没有 `--ascension`，也没有新框架 A10 专项训练验收。11 月 10 日讨论的逐级升阶、低难度复习、与表现联动的奖励衰减均未实施；讨论数值不属于当前配置。

## 5. 旧框架（`model/spireformer`）的问题

1. MAB 先用 `nn.Linear` 投影 Q/K/V，再交给 `nn.MultiheadAttention`，后者内部又有一套 in_proj，投影重复，参数量也因此偏离估算。
2. Post-LN；文档要求 Pre-LN，深层（32 层）下 Post-LN 更难训。
3. 时序网络要前向两次：策略带 RTG，价值把 RTG 置零后再跑一遍。新实现 Actor/Critic 共用一次前向，不输入 RTG。
4. 价值头用 Tanh 截断；文档要求线性。
5. 只有监督损失，没有宏观环境、PPO、rollout、评测、检查点续跑和可视化。
6. 实体特征是扁平拼接，不能让候选直接指向具体实体（具体那张牌、那个节点）。

## 6. 已做的验证

| 项 | 结果 |
| --- | --- |
| 2026-11-10 P0 回归（6 项新增，共 24 项） | 模拟器常量一致；同一历史在不同档位/α 下标注时网络输出逐位相同（G2）；分组策略为归一化的联合概率且初始在各组间均匀；分量 GAE 与组合价值上的标量 GAE 相等；“取消”单独成组且兼容 v1 观察；网格无限切换以 `menu_loop` 截断且不代做选择（G3） |
| `pytest`（18 项） | 全部通过：三档参数量；非法/padding 概率为 0；padding 不影响有效输出；实体重排不变、候选重排同步；未来不影响过去且过去会影响；冻结参数概率重算一致；GAE 终止/截断；奖励公式（α=0 正常失败为 0、胜利为 5）；辅助标签屏蔽；microbatch 累积梯度与整批一致；不兼容检查点拒绝；BF16 前向/反向；训练表横轴为累计局数且只留 `best.pt`；环境只记录真实选择、楼层不重复计；未打开的卡牌奖励不泄漏；验证可复现；归档往返一致；成对比较 |
| `smoke`（tiny，CPU） | 采样、更新、验证、最佳权重、归档、CSV 表、仪表盘全部生成；横轴为累计局数 |
| BF16 | CPU 上用 BF16 自动混合精度做前向与反向（GPU 默认路径的同类数值类型） |
| `main` 原尺寸 CPU | 0.201B 参数，一次前向/反向/AdamW/保存成功（当时保存的是含优化器的完整文件 2.42 GB；现在只存权重，约 0.8 GB） |
| 随机策略基线 | 随机局外选择 + MCTS 战斗，200 个验证种子：平均到第 11.1 层，1% 到第二幕，0 胜（tiny 模型初始化时的验证结果） |
| 5090 上 `main` 初始评估（用户 2026-11-10 反馈） | `[val @0]`：0/200 通关、平均 11.0 层、约 1% 到第二幕；只有训练前 GPU 推理评估证据，尚未收到更新日志、显存/吞吐报告和学习后成绩 |

## 7. 训练机器上要先确认的事

1. `check --preset large-1b`：看 `fits_with_3gib_headroom`。不够先试 `--microbatch 1`（默认已是 1），再不行用 `large-0.7b`。
2. 短训练 10 个周期后看仪表盘的"每局秒数"与 ETA（已含更新、验证、保存）。文档的一天目标需要 ≤ 8.64 秒/局。10 个周期里只有开头一次验证，之后每 2000 局还有一次 200 局验证，正式训练的平均值会略高。本机（4 核 Mac CPU、tiny 模型）随机策略约 2 秒/局，但后期局更长、Boss 搜索更贵，必须实测。环境数应接近 CPU 核数。
3. 若 KL 每次都在第一轮就提前停止，或熵很快塌缩，记录下来再调，不要只增加更新次数（文档 5.3）。

## 8. 修订记录

**2026-11-10（第二批，第二轮训练用）**
- 独立 critic（`CRITIC_SMALL`，约 19.6M，`critic=None` 退回共享价值头），每次更新后 `value_epochs=4` 遍纯价值训练（`critic_lr=1e-4`）。
- KL 早停改为每 `kl_check_every=8` 步在固定 `kl_check_targets=512` 个样本上测；单小批超过 `kl_hard_mult=4` 倍也停；记录 `kl_stop_reason`、`sampled_kl_last`。策略 `lr` 1e-4→3e-5，`epochs` 4→3（上限）。
- `gate_policy` 默认改为 `hold`；新增 `last.pt`（每次验证后与结束时写入，含 critic）；磁盘规划按 best + last + 临时文件。
- 测试 26 项。

**2026-11-10（第一轮诊断后的 P0 修改）**
- G2：去掉档位嵌入与历史 r_train；价值头改为三分量（未来层数、进幕、胜率），任意 α 下组合；GAE 按分量计算。评估结果记录 `conditions`。检查点格式 `spire_rl/3`，归档格式 `spire_rl.archive/2`（增加 `value_comps`，仍可读 /1）。
- G3：分组策略头（`ModelConfig.type_factorized`，默认开）与组熵奖励（`PPOConfig.type_entropy_coef=0.01`）；网格循环保护（`max_grid_steps=64`）；单局上限 3000→600。
- 新监控：`value_ev`（及分量）、`value_pred_std`、`return_std`、`entropy_group`、`approx_kl_max`、`target_passes`、`menu_loops`、截断原因。`epochs` 仍是“进入过的 epoch 数”，实际遍数看 `target_passes`。
- 依赖 C++ 改动：ruleset `native-41cef1ea-port-v7`、宏观观察 v2（见 `artifacts/dev/cpp-native-aligned-20261031/validation/nosl-fix-20261110/README.md`）。学习率、KL 方式、网络规模、critic 结构等 P1 建议**未实施**。

**2026-11-10（仅交接文档更新）**
- 补充 `v111_SF1`、WSL2/Conda 环境、实际输出目录和用户反馈的 GPU 初始基线；纠正“从未在 GPU 运行”的过期描述，保留尚无更新/性能证据的边界。
- 明确 A10/课程、last 权重和继续训练入口未实现；区分当前 best-only 保存、实际身份校验与原 v3 设计。
- 统一运行示例到项目根目录，补充原生 Windows 限制和监控路径。本次未改变训练代码、配置或正在运行的实验。

**2026-11-09（外部审阅 + 用户要求）**
- 修 BF16 类型冲突：自动混合精度下地图消息（BF16）与 FP32 缓冲区相加报错，GPU 默认路径会在第一次前向就失败。消息改为按缓冲区类型累加；新增 CPU BF16 前向/反向测试（修复前可复现报错）。
- 修 ETA 低估：每局秒数原来在保存与验证之前计算；现在 = 从开始到现在的全部墙钟 ÷ 已启动局数，验证与保存之后再记录。
- 修训练表横轴：每行的 `episodes` 被本轮采样的完成局数覆盖（应为累计局数），仪表盘横轴因此错误。本轮局数改名为 `rollout_episodes`；新增测试。
- 保存策略简化为只存 `best.pt`（权重），去掉每次更新的 `latest.pt` 和每次验证的 `weights_ep*.pt`，也去掉了 `--resume`。GPU 续跑时随机数状态被搬上 GPU 的问题随之消失；读取检查点一律先到 CPU。
- 训练结束时导出 `metrics.csv`、`eval.csv`；仪表盘训练表加入每局原始奖励列。
