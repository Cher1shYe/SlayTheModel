# SlayTheModel：交接说明

更新：2026-11-16 晚（Claude：战斗网络实验续跑和第一批对照；“本幕 Boss 价值头”设计讨论；每次结果拉回后的固定检查。早些时候：small-b-d1 诊断，策略不看血量；原生对照未完成）。本文件是**接手的唯一入口**：先读第 0–2 节了解现状，再按需查后面的约定、路径和命令。源码、日志与本文不一致时，以源码和原始日志为准，并更新本文。

研究讨论（含 2026-11-15 的论文阅读和“战斗里试牌”的想法）见第 2.4 节及[训练缺口文档第 2.1 节](docs/claude-training-gaps-and-mcts-plan-20261110.md#21-四个训练缺口论文思路与后续实验)

---

## 0. 一分钟了解现状

**项目目标**：保留同学的 C++ 杀戮尖塔 2 模拟器（对齐原生 `v0.111.0 / 41cef1ea`），训练一个**局外策略网络**（选路、选牌、火堆、商店、事件等），铁甲战士、A0、单人。战斗由固定的 C++ 隐藏信息 MCTS 打（普通/精英 128 次、Boss 512 次），网络不管战斗。网络与训练框架在 `model/spire_rl/`（PPO 在线训练）。

**进度**：

| 阶段 | 状态 |
| --- | --- |
| 第一轮 `main-a0-s1` | 已完成（6,001 局，因旧门槛提前停）。诊断：[docs/claude-run1-diagnosis-and-fix-plan-20261110.md](docs/claude-run1-diagnosis-and-fix-plan-20261110.md) |
| P0 修复 + 第二批改动 | 已实施、已用于第二轮：NoSL 信息隔离（C++ ruleset v7）、网络去掉训练条件输入、按动作组的策略头、菜单循环保护、独立 critic、KL 早停改法、`last.pt` |
| 第二轮 `main-a0-s2` | 已完成（10,000 局，11.7 小时）。诊断：[docs/claude-run2-diagnosis-20261111.md](docs/claude-run2-diagnosis-20261111.md)；同学的交接：[docs/claude-run2-review.md](docs/claude-run2-review.md) |
| 第三轮（0.2B 接着第二轮 + 价值先验 + 分叉） | 代码已提交（`44ac1bc`）。用户在训练机启动过一次，**第 7 次更新（223 局）时因 C++ 事件异常崩溃，未继续**。已知：`[val @0]` 22.0 层 / 0.49 到第二幕（接续成功）；价值先验留出 EV 层数 0.17、进幕 0.08；带分叉约 6 秒/局；前 6 次更新在线 `vEV` 在 −0.22–0.17 之间。已被第四轮方案取代 |
| **第四轮** | 代码已提交（`e4f87ed`、`574b997`）：C++ 崩溃修复（ruleset v8）、`small` 预设（约 0.02B、8 步历史）、离线蒸馏、逐张卡牌分叉、按工作日分段训练。见第 2.3 节和模块 README 第 2.5、8 节 |
| 第四轮首次启动（2026-11-12，`runs/small-a0-d1`） | 蒸馏成功：`[val @0]` 22.1 层 / 0.46 到第二幕 / 1 通关。跑了 7 次更新（240 局，约 4.7 秒/局；每轮平均层数 20.5 → 27–30，样本少、不算结论；熵 0.82 → 0.51），第 8 次更新前被概率重算检查拦停（0.053 > 0.05）。**原因是 BF16 舍入，已修**（`small` 改 FP32、输出头固定 FP32、BF16 限值 0.25），同时加固：报错或 Ctrl+C 退出也保存 `last.pt`；新增 `eval --greedy`。修复后重跑即下一行的三段。见 2.1 和模块 README 第 8 节 2026-11-12 条 |
| 第四轮三段（2026-11-12/13，`small-a0-d1` 至 `d3`，共 7,769 局，约 9.7 小时） | 已完成，数据在本机 `runs/training-review/small-a0-d{1,2,3}/`。验证 22.2 → 29.2 层（3,039 局），之后停在 28.5–29.3；训练数据里涨幅在前约 300 局就完成（不再丢下金币遗物、不再丢药水、火堆一律回血），d3 训练平均层数比 d2 低 1.15 层。**原因：旧的分叉损失没有上限，把策略推成几乎完全确定**（火堆 log P(升级) −19 → −539，所有血量相同），每次更新约 7 步就被 KL 拦停。诊断：[docs/claude-run4-diagnosis-20261114.md](docs/claude-run4-diagnosis-20261114.md) |
| 2026-11-14 的修复 | 代码**尚未提交**、**尚未在 GPU 上运行**：分叉损失改为有上限的形式、每次更新复用最近 4 轮的分叉、KL 超限时回滚、`small` 学习率 1e-4 → 3e-5 并随拦停自动调整。原回滚仅撤销最后一步，已由下述 11-15 修复补齐。见第 2.3 节和模块 README 第 8 节 |
| 2026-11-15 缺口 1 与审计 | 用户要求做缺口 1（按选项打分的价值头）并检查潜在 bug。离线测试结论**否定、不接入**：在第四轮 18,597 个分叉上，打分头对没见过的局的预测与真实值的相关，火堆 0.27、选牌 0.04、地图 0.23，都远低于现在用的两套种子平均（0.61 / 0.53 / 0.87）；选牌连“只用卡牌 ID”也只有 0.04。选牌分叉约占全部模拟器战斗的 40%，所以下一轮**关掉选牌分叉**（`--fork-card 0`）。审计改了两处：menu_loop 截断不再加 critic 对后续的估计；分叉的种子数、选项数加范围检查。代码**尚未提交**，本机 63 项测试通过。见诊断文档第 7 节、模块 README 第 8 节 2026-11-15 条 |
| 2026-11-15 KL 回滚补齐（Codex） | 默认每 8 步检查时，原实现退一步仍可能超限；现改为恢复最近一次固定样本 KL 检查合格的**权重和完整优化器状态**，同步恢复保留步数与样本计数，最后重新测量。新增默认检查间隔、末尾不足周期、Adam 状态及非有限值回归。**本机 CPU 72 项测试通过**，尚未在 GPU 上验证，见模块 README 第 8 节首条 |
| 修复后一轮 `small-b-d1`（同学在训练机上跑，11,148 局，10 小时） | 已带回本机 `runs/training-review/small-b-d1/`。**训练过程正常、成绩不行**：验证 22.2 → 25.6 层（约 4,000 局后不再涨），低于第四轮 29 层。最重要的发现：**策略网络不看血量**（窗口内血量改 20%/100%，选择概率平均只变 0.03%；全局行清零只变 0.1–0.2%；决策向量里血量线性可读 R² 约 0.12），12,787 个火堆分叉明确说低血该回血，策略回血率在各血量下都一样。PPO 只学到整体偏好。Boss 死亡率（到达者中）：第 17 层 31%、第 33 层 51%、第 48 层 90%。`config.json` 里选牌分叉概率实际是 0.01。诊断：[docs/claude-runb-diagnosis-20261116.md](docs/claude-runb-diagnosis-20261116.md) |
| 原生 DLL 对照（2026-11-16 开了个头） | 上一任在本机装了 .NET SDK 9.0.321（`artifacts/tools/dotnet-sdk`，约 600 MB），用保留的 v0.111.0 DLL 编译并启动过无界面宿主（`artifacts/dev/cpp-native-aligned-20261031/validation/native-whole-run-20261115/`，`run_host.sh`，存档目录 `~/Library/Application Support/SlayTheModelParity`）。开局状态读取时 JSON 解析失败，**还没有任何对照结果**；正在核对的是种子 `PARITY0001` 下模拟器给的先古遗物选项（PreciseScissors / BoomingConch / SilverCrucible）。用户决定先做训练分析，这条暂停 |
| 战斗网络实验（2026-11-16，本机） | 上一任写了按实体的战斗观察、批量网络搜索 `NetSearch`、约 1.4M 的战斗网络（C++ 只加接口，ruleset 不变，本机已重编）。续跑完成：第 0 代数据 300 局（48,642 个决策，MCTS 256/512/1024）、188 场固定对照集。**临时网络**（3 万个决策）的成对对照：普通、精英与 MCTS 相近；Boss 死亡率 网络单独 61.6%、网络 + 搜索 64/128/256 47.9%、MCTS 128 档 38.4%、256 档 43.8%（MCTS 翻倍搜索在 Boss 上没有改善）。**完整数据的第 0 代训练、256/512/1024 档网络搜索、自我对弈都还没做**，用户要求先暂停。见模块 README 第 8 节 2026-11-16 条 |
| 设计讨论：本幕 Boss 价值头（2026-11-16） | 用户认同：从每个局面（含普通战斗中）加一个价值输出，预测本幕 Boss 能否打过，局内出牌、留药与局外选择都按它打分；整局价值约等于各幕通过率相乘，用下一幕开头的预测往回接。已向用户说明的问题：离 Boss 远的地方信号弱，标签宜用时序差分与最终 0/1 混合；搜索里数值差太小，建议用它算血量和药水的“汇率”再给本场结果加权；**战斗观察目前没有幕、层、本幕 Boss、地图**，统一网络必须加；后期样本少；换幕回血已核对：A0 下每幕第一个房间（先古事件）把血回满，打完 Boss 剩多少血对下一幕没有影响。**离线测试已做**（`artifacts/analysis/claude-bossval-20261116/README.md`）：44.8 万个样本，按种子留出；小 MLP 在 Boss 前最后一层 AUC 0.86（第一幕）/ 0.83（第二幕），能解释约三分之一的不确定性；到幕开头 AUC 0.68 / 0.74，只解释约一成。牌组是主要预测因素（只用数值 AUC 0.72）。血量 +10% 使通过率高 4.2 个百分点（Boss 前），到幕开头为 1.3，与第一轮受控实验同一量级（约 7）。第三幕样本少，结果不稳。结论：可以做，但幕开头要靠时序差分往回接。**网络结构尚未实现** |
| 统一网络设计（2026-11-16） | 写成 [docs/claude-unified-net-design-20261116.md](docs/claude-unified-net-design-20261116.md)。用户已定：一个网络、实体集合、无历史、本幕 Boss 价值、跨幕打折只在决策时用（w₁ = 0.2、w₂ = 0.5 起步，按门槛升到 1）、先做 A0。第 7 节已由用户拍板（r₃ = 3；搜索尺度两种都做后比较；局外先 PPO、火堆和拿牌再试往前看一步；局外从零、价值头先在归档上预训练；预算 256/512/1024）。**第 1、2 步已完成**：`unified_obs.py`、`unified_net.py`（约 2.5M）。**第 3–5 步的代码已完成并适配 GPU**（11-16 深夜）：价值头在本机归档上预训练一遍（`artifacts/analysis/claude-unified-20261116/value_pretrain.pt`；Boss 前一层 AUC 0.77 / 0.71，血量 ±10% 使预测通过率变 2–5 个百分点）；本机 300 局 MCTS 教师数据；C++ 加了树内归一化和“赢局交给网络估值”两个选项（ruleset 不变，本机已重编）；训练机一条命令 `bash model/spire_rl/unified_gpu.sh`（教师数据 → 第 0 代 → 188 场评估，可续跑；模块 README 第 2.6 节）。本机 98 passed，脚本小规模跑通，**CUDA 未实测**。下一步：用户把代码和 `to_gpu/` 两个文件带到训练机跑，结果带回后比较 |
| 下一步 | 用户认为现在“MCTS 全权负责战斗”对 NoSL 不行、选牌与打牌解耦也不对，**最终要换网络结构**，并借鉴前几轮的失败。诊断文档第 5 节列了换结构的要求，第 6 节是建议的步骤（先单独训练战斗网络并与 MCTS 成对比较，再做局内外统一的无历史单网络，最后把网络接进 MCTS）。**待用户决定**。`small-b`/`small-a0` 的检查点只用于分析。**未经用户指示不要启动、停止或修改远端训练** |

**验证成绩**（固定 200 个验证种子，随机采样评估）：

| 版本 | 平均层数 | 到第二幕 | 到第三幕 | 通关 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 0 局（随机初始化） | 10.96 | 1% | 0% | 0/200 |
| 第一轮 6,001 局 | 20.81 | 34% | 3% | 0/200 |
| 第二轮 8,021 局（`best.pt`） | 23.36 | 53% | 8.5% | 1/200 |
| 第二轮 10,000 局（`last.pt`） | 22.03 | 49.5% | 7% | 0/200 |
| 第四轮 0 局（从第二轮蒸馏出的 `small`） | 22.25 | 46.5% | 8% | 1/200 |
| 第四轮 3,039 局（d1 `last.pt`） | 29.16 | 72% | 22.5% | 5/200 |
| 第四轮 7,360 局（d3 `best.pt`） | 29.28 | 75% | 26.5% | 4/200 |
| 修复后一轮 10,022 局（small-b-d1 `last.pt` 前的最后一次验证） | 25.56 | 59% | 14.5% | 2/200 |

各轮之间模拟器和训练配置都变了，不是单因素对照；0/200 与 1/200 的差别不显著。第四轮平均层数的标准误约 0.85，3,039 局之后的几次验证（28.5–29.3）之间没有可分辨的差别。

---

## 1. 接手第一步

1. 先看用户最新的话；本文件第 0–2 节；然后 [第四轮诊断](docs/claude-run4-diagnosis-20261114.md)、[第二轮诊断](docs/claude-run2-diagnosis-20261111.md) 第 3–5 节和 `model/spire_rl/README.md` 第 8 节（修订记录）。
2. `git status`：最后的提交是 `574b997`（第四轮代码，分支 `v111_SF1`）。**2026-11-14、11-15 的修复和文档在工作区里未提交**，见第 7 节。`ForkConfig`、`PPOConfig` 又增加了字段，旧检查点可以照常加载（新字段取默认值），但用当前代码重算的配置指纹与以前各轮 `config.json` 里的不再相同。
3. 训练机上可能有崩溃的第三轮目录 `runs/main-a0-s3/`（约 1.8 GB 检查点，可删）和 `runs/critic-prior-s2.pt`；第四轮的 `runs/distill-small.pt`（蒸馏结果，**下一轮从它开始，本机没有这个文件**）和 `runs/small-a0-d1` 至 `d3`（已带回本机，含归档和 `best.pt`/`last.pt`；这些检查点已饱和，只用于分析）。第二轮的 `best.pt`/`last.pt` 是 ruleset v7 的，v8 构建会拒绝加载。
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
- **战斗器是上限之一**：第一幕 Boss 前满血也约三分之一过不去；第二幕大量死在普通战斗。后期战斗的搜索量对照见下面“后期战斗上限”。
- **时间花在网络上，不在模拟器上**（第二轮 11.7 小时）：PPO 与 critic 更新 7.6 小时，采样时的推理 3.0 小时，其余约 1.2 小时；战斗 MCTS 合计 19.7 线程小时，8 线程并行折合约 2.5 小时。采样时平均每次前向只有约 1.5 个决策。
- **19.6M 的 critic 在背当前批**：第二轮末尾 critic 训练最后一遍的损失约 0.002（常数预测约 0.06，相当于批内解释方差 >0.95），而同一批训练前只有 0.06–0.17。
- **critic 的通关分量是噪声**：第二轮最后 20 轮里通关头解释方差 −0.04，预测标准差 0.010、范围 −0.04–0.35；它在标量价值里的权重是 1.0（α=0.5 时一层 0.005、进幕 0.05）。
- **第一、二轮用的是同一批游戏种子**（两轮 `seed` 都是 1，`train_seed_base` 都是 1,000,000；一轮内每局种子不同）。同一种子两轮的最终层数相关 0.27（后 3,000 个种子 0.15，打乱后 −0.03）。
- **白拿的东西会被放弃**（第二轮最后 20 轮、757 局，训练时的采样动作；脚本 `artifacts/analysis/claude-run2-20261111/pickup_an.py`）：奖励界面还有东西可拿时 11.9% 的次数直接离开；金币被留下 1,356 次（占 18.9%）、遗物 159 次（9.9%）、卡牌奖励没打开 1,143 次（15.3%）；能丢药水的 5,407 次里丢了 1,164 次（21.5%），战斗外能用药的 481 次里用了 222 次。打开卡牌奖励后的跳过率 7.5%，正常。原因判断：这些决策几乎收不到回报信号，熵奖励和按概率采样使“离开”“丢药”长期保留一到两成概率；训练和验证都按概率采样，所以这是实际损失（金币、遗物变少），也压低了验证成绩。**第四轮的分叉不覆盖奖励界面**，这个问题没有处理。
- **战斗里的出牌没有逐手审计**。总体证据只有搜索量对照（见“后期战斗上限”）：普通战斗 16 倍搜索比现配置少掉约三分之一的血，说明现在的搜索会吃一部分可避免的战损；“有斩杀却没斩杀”的回合数没有统计。
- **第四轮首次启动被拦停的原因**：BF16 只有 8 位有效数字，同一个决策在采样时（约 1.5 个一批）和更新前重算时（64 个一批）算出的对数概率会差出一到两档舍入。第一、二轮这个差最大 0.023 / 0.031，一直在 0.05 的限值以内；这次策略变尖得快，到了 0.053。本机用 CPU BF16 复现了同样的量级，FP32 下为 0；带分叉采样的重算在 FP32 下精确一致（不是数据错位）。已改：`small` 预设用 FP32，输出头在所有预设下固定 FP32，BF16 的限值单独设为 0.25。
- **第三轮崩溃的原因**：C++ 的 The Future of Potions 事件对原生 Event / Token 稀有度的药水处理错误，抽到 Power 类型时抛异常（本机可复现：这三种药水各 68/200）。已修（ruleset v8）。
- **第四轮停在 29 层左右的原因**（三段 7,769 局；详见 [诊断文档](docs/claude-run4-diagnosis-20261114.md)）：
  - 已确认：旧的分叉损失 `−优势 × log P(选项)` 对分数的推力是常数，不随概率变小而减弱。检查点上量到的火堆 log P(升级)：−19（2,002 局）→ −38 → −168 → −539（7,769 局），所有血量下相同；选牌、地图分叉里被比下去的选项到约 −5,000。d3 末分叉项的梯度约是 PPO 项的 70 倍。
  - 较强怀疑：饱和后（88% 的多选决策概率 >0.99，动作组的熵 0.0001）主线样本的梯度趋近于零、不再探索，只剩分叉项偶尔把个别决策整个翻掉（单个小批 KL 到过 28）；每次更新约 7 步（满额 57）被拦停，每批样本用 0.4 遍，分叉只有 47% 进过梯度（分叉占模拟器战斗量约 70%）。
  - 已确认是因素之一：学习率 1e-4 偏大（预热到 1e-5–4e-5 时能走满 3 遍；第二轮 3e-5 平均 1.5 遍）。饱和以后 1e-5 也会被拦停。
  - 已确认：分叉标签噪声大。两套种子均值的可靠度：地图 0.76、火堆 0.37、选牌 0.28（选牌分叉近一半是“有的分支死了有的没死”）。策略的选择与分叉结果的吻合程度三段都没上升（选牌等于随机）。
  - 已确认：火堆分叉本身说血量 90% 以下回血明显更好（分支死亡率低 6–22 个百分点），满血时升级略好（低 1.7 个百分点）；策略满血也 100% 回血。火堆分支只跑两场战斗，对升级不利（较强怀疑，未改）。
  - 已确认：通关项占回报方差约 70%，critic 预测不了；有通关的批里，通关局占 7% 的样本、78% 的优势方差。critic 对层数的解释方差已到 0.25–0.36（接近离线上限）。通关奖励权重是用户定的，未改。
  - 第四轮解决了的：白拿的东西不再放弃（离开 9.3% → 0、丢药 19% → 0）。新出现的：打开卡牌奖励后从不跳过、从不升级；d2、d3 各有约 1% 的局因反复取消网格预览被 `menu_loop` 截断。
  - 战斗这堵墙没变：到第一幕 Boss 的约 25% 死在那，第二幕 Boss 约 45%，第三幕 Boss 约 70%，三处合计约一半的死亡。
- **缺口 1（按选项打分的价值头）离线测试**（2026-11-15；[诊断文档第 7 节](docs/claude-run4-diagnosis-20261114.md#7-缺口-1按选项打分的价值头的离线测试2026-11-15)）：已确认在第四轮数据上它不能代替分叉结果；选牌在本幕之内的影响小到四千多个分叉也测不出规律（只用卡牌 ID 的相关 0.04，40% 的选牌分叉所有选项结果相同），而选牌分叉约占全部模拟器战斗的 40%。火堆的规律主要是血量（只用血量 0.35）。

### 2.2 当前训练框架要点（`model/spire_rl/`，细节见模块 README）

- **网络 SpireNet**：实体 Set Transformer（地图连边消息传递）→ 因果历史 Transformer（最近 N 个决策，每步 g/z/a/r 四个 token；g 不含奖励档位，r 只含事件计数：新完成层数、新进幕、通关）→ 候选指针打分。策略 = P(动作组) × P(组内目标)，“取消已选网格牌”单独成组。预设 `main` 约 0.202B、32 步历史（其中历史 Transformer 约 176M），配 critic `CRITIC_SMALL` 约 19.6M；预设 `small` 约 0.02B、8 步历史，配 `CRITIC_LITE` 约 1.9M。critic 输出未来层数/50、未来进幕/2、通关概率三分量，任意 α 下线性组合成标量价值。
- **环境**：一次转移 = 一次真实局外选择；只有一个合法动作的界面自动执行；战斗由 `RunContext.play_combat_mcts()` 跑完；观察来自 `RunContext.macro_observation()`（宏观观察 v2，候选 5 维）。同一网格连续 64 个决策以 `menu_loop` 截断，单局上限 600 个决策；不代选、不代确认。`menu_loop` 截断按“到此结束”计，不加 critic 对后续的估计（2026-11-15 起，`RunConfig.menu_loop_bootstrap=False`；其他截断仍加）。
- **奖励**：`r_raw = 5×通关 + α×(0.05×新完成层 + 0.5×新进第二/三幕)`，训练值除以 5，γ=1、GAE λ=0.99。默认按 2k/4k/6k 局 α 从 1/0.5/0.2 降到 0，门槛不满足时默认 `hold`（继续训练）；第三轮可用 `--alpha` 固定单档。
- **PPO**：策略 lr 3e-5（`small` 预设也是 3e-5，另有 150 步学习率预热），最多 3 遍；KL 检查：每步前向时量当前小批（>0.04 停），每 8 步和更新结束时在固定 512 个样本上量（>0.015 停）；非有限值也停。`kl_rollback` 恢复最近一次固定样本检查合格的权重和优化器状态，可能撤销多步；更新开始也先验证，回滚后重新实测，不能确认合格则报错。限制针对固定样本估计，不是全部状态的精确 KL。一次更新不到一遍就被拦停，之后策略学习率乘 0.7（下限为基础值的 0.1 倍），走满全部遍数乘 1.1（上限为基础值），系数存在检查点的 `progress.lr_adapt` 里跨段接续。组熵额外奖励 0.01。critic lr 1e-4，每次更新 2 遍（当前批 + 最近 12 轮的回放各一份）。
- **分叉损失**（2026-11-14 起）：每次更新开始时按当前策略给每个分叉决策算目标分布，目标 ∝ max(当前概率, 0.01) × exp(归一后的优势，限幅 ±3)，损失是目标到策略的 KL（只在被比较的选项之间）；每次更新同时用最近 4 轮的分叉决策（`ForkConfig.replay_rollouts`，`--fork-replay`）。同一个测量连续重复时，选项的对数概率停在约 −10.6。
- **保存**：`best.pt`（验证胜率更高，或胜率相同而平均层数更高时）和 `last.pt`（每次验证后、训练正常结束或 `--max-hours` 到点时），都含 critic，只存权重（不能精确断点续跑）。报错或按一次 Ctrl+C 退出时也保存 `last.pt`（`progress.final=false`；权重含非有限数或还没做过更新时不覆盖）；直接关窗口或 `kill` 不保存。检查点格式 `spire_rl/3`，`progress.next_train_seed` 记录下一个未用的训练种子；归档格式 `spire_rl.archive/3`（增加分叉审计记录，仍可读 /1、/2）。
- **每次结果拉回后的固定检查**（2026-11-16 起，用户要求）：只改血量的反事实敏感度、决策向量的血量探针、与火堆分叉方向对照。见模块 README 第 7.1 节。
- **监控**：每个 run 目录有 `metrics.jsonl`（每次更新一行）、`eval.jsonl`、`eval/val_ep*.json`、`dashboard.html`、`archive/rollout_*.npz`、可选 TensorBoard。重点字段：`value_ev_floors`、`rest_heal_rate_full_hp`、`rest_heal_rate_hp_below_50`、`entropy_group`、`target_passes`、`kl_stop_reason`、`menu_loops`，第三轮再加分叉相关字段（见 2.3）；2026-11-14 再加 `fork_option_logp_min`（策略有没有被推死的直接读数）、`fork_pool`、`kl_rollback`、`sampled_kl_final`、`lr_adapt_next`。`fork_loss` 的含义变成每个分叉决策的 KL（≥ 0），与第四轮的数值不可比。

### 2.3 第四轮方案与 2026-11-14、11-15 的修复（第四轮跑了三段；修复后尚未在 GPU 上运行）

用户 2026-11-11/12 的决定：GPU 只能在用户工作时间分段使用，所以**换小网络**；历史**保留 8 步**（用户直接拍板，不做“截短历史”的对照评估）；保持端到端；分叉是主要的信号来源；通关奖励的权重保持最大，只是分叉里不使用 critic 对通关的估计；训练中途丢进度可以接受；检查点不要多存。

用户 2026-11-14/15 的决定：试 11-14 的修复；加大 Boss 战搜索量“没什么用”，不做；做缺口 1 并检查潜在 bug（已做，缺口 1 否定）；然后再跑一轮，不行就推翻现在的网络。

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| 小网络 | 预设 `small` | Set Transformer 256 × 2 ISAB，历史 512 × 4 层、8 步，约 0.02B；`lr=3e-5`（第四轮是 1e-4；会随 KL 拦停自动下调）、`microbatch=32`、学习率预热 150 步、**FP32**（`--bf16` 可改回，FP32 的速度未实测）。critic `CRITIC_LITE` 约 1.9M、dropout 0.1 |
| 离线蒸馏 | `distill --archive <归档> --out <ckpt> --preset small` | 对归档里策略采样的动作做最大似然，同时从随机初始化训练 critic；默认最后 60 个文件、留出 6 个；输出普通检查点。报告 `kl_estimate`（与教师策略的差距）、`top1`、`critic_ev` |
| 逐张卡牌分叉 | `--fork-card <概率>` | 选项 = 每张可拿的牌 + 跳过；分支跑到本幕结束（或本局结束），回报只计真实事件，不加 critic 估计。**下一轮关闭**（`--fork-card 0`）：约占全部模拟器战斗的 40%，而结果学不出规律（诊断文档第 7 节） |
| 火堆/地图分叉 | `--fork-rest/--fork-map` | 与第三轮相同（2 场战斗 / 40 个决策 / 换幕，其余由 critic 估计），但不再使用 critic 的通关分量；各界面的优势分别归一。`--fork-seeds` 只能是 1–8（超出会报错） |
| 分段训练 | `--max-hours H` + `--init-checkpoint <上一段>/last.pt` | 到点后不再开始新一轮采样，保存 `last.pt` 正常退出。训练种子按检查点的 `next_train_seed` 接续（蒸馏检查点从 2,000,000 起） |
| 异常不再终止整轮 | `env.py` | C++ 异常记为该局 `FAILURE`（终端会打印数量和原因）；单轮失败超过 `max(2, 2%)` 仍会停，停之前保存 `last.pt` |
| 取最大评估 | `eval --greedy`，再用 `compare` | 每步取概率最高的动作，种子与采样评估相同；`compare` 给同种子配对的层数差和标准误。只是测量，训练和训练中的验证仍按概率采样。**未在训练好的策略上跑过** |
| 其他 | | `--lr`、`--bf16/--no-bf16`、`--train-seed-base`；`best.pt` 胜率相同时比平均层数；第三轮的 `--init-checkpoint`、`pretrain-critic`、critic 回放、`--alpha` 仍可用 |

**现在要做的（2026-11-15 起）**：从蒸馏结果重新开始，目录名换成 `small-b-*`。训练机上已经编译过 v8、已经有 `runs/distill-small.pt`，所以**不用重新编译，不用重新蒸馏**。`small-a0-d1` 至 `d3` 的检查点（包括 d1 的 `best.pt`）已饱和，不要接着它们训练。

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
python -m pytest -q model/spire_rl/tests            # 同步代码后确认：72 passed（本机另有战斗网络与统一网络的测试，共 98；训练机未重编 C++ 前不要同步 test_combat_net.py、test_unified*.py）
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-b-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0 --fork-seeds 2 --fork-coef 2
# 第二天起只改：--run-dir runs/small-b-d2 --init-checkpoint runs/small-b-d1/last.pt（第三天 d3 接 d2，依此类推）
```

- 要同步到训练机的文件：`model/spire_rl/spire_rl/` 下的 `config.py`、`ppo.py`、`rollout.py`、`train.py`、`__main__.py`，以及 `model/spire_rl/tests/test_spire_rl.py`。
- 指令与第四轮相比只改了 `--fork-card 0`（选牌分叉关闭，原因见诊断文档第 7 节）；其余变化在代码默认值里（学习率、分叉损失、分叉复用、KL 退回、menu_loop 截断按“到此结束”计）。训练种子仍从 2,000,000 起，和第四轮 d1 是同一批游戏种子，曲线可直接对照。
- 启动后看：`[val @0]` 约 22 层；`target_passes` 多数在 1 以上（第四轮 0.4）；`fork_option_logp_min` 保持在约 −12 以上（第四轮 −19 到 −5,000）；`rest_heal_rate_full_hp` 不钉在 1.000 而 `rest_heal_rate_hp_below_50` 保持较高；`fork_card` 为 0，`seconds_per_episode` 明显低于第四轮的 4.4–4.7 秒。
- 成绩：第四轮约 300 局就到 26–28 层（靠把策略变尖）；这次学习率低，会慢一些。到 2,000–3,000 局应回到 28–29 层，之后看能否超过 29.3。训练过程正常而成绩仍停在 29 层左右时，按诊断文档第 6 节转向战斗网络和网络结构本身（按选项打分的价值头已离线测过，否定，见诊断文档第 7 节）。
- 到点自己停并保存 `last.pt`。提前停按一次 Ctrl+C，等打印 `saved to .../last.pt`；直接关窗口不保存。中途报错也会先保存 `last.pt`，修好后从它用新的 `--run-dir` 接着跑。
- 每天带回当天 run 目录的 `metrics.jsonl`、`eval.jsonl` 和终端输出；归档 `archive/` 能带就带（这次的诊断主要靠它）。
- 2026-11-15 在本机用第四轮 d1 的检查点核对过这条命令解析出的配置：学习率 3e-5、选牌分叉概率 0、FP32、`menu_loop_bootstrap=False`。
- 详细步骤见模块 README 第 2.5 节。

从头做一遍的命令（换机器、C++ 又改了、或需要重新蒸馏时；**C++ 改过就必须先重新编译**）：

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"      # native-41cef1ea-port-v8
python -m pytest -q model/spire_rl/tests                                     # 72 项

# 1) 一次性蒸馏（只读第二轮归档）
python -m spire_rl distill --archive runs/main-a0-s2/archive --out runs/distill-small.pt --preset small --device cuda

# 2) 每个工作日一段；--max-hours 设为能挂的小时数减去约 20 分钟
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-b-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0 --fork-seeds 2 --fork-coef 2
# 第二天起只改：--run-dir runs/small-b-d2 --init-checkpoint runs/small-b-d1/last.pt
```

取最大评估（可选，单独跑，不要和训练同时）：

```sh
python -m spire_rl eval --checkpoint runs/small-a0-d1/last.pt --device cuda --greedy --out runs/eval-d1-greedy.json
python -m spire_rl eval --checkpoint runs/small-a0-d1/last.pt --device cuda          --out runs/eval-d1-sampled.json
python -m spire_rl compare runs/eval-d1-greedy.json runs/eval-d1-sampled.json
```

读 `floor_diff_a_minus_b`（取最大减采样的平均层数差）和它的标准误；先确认 `a_truncations` 很小（取最大的策略可能在菜单里反复点同一个动作而被截断，层数会被低估）。

启动后先确认：

- `distill` 输出的留出 `kl_estimate` 随轮数下降；第一段的 `[val @0]` 应接近第二轮末尾（约 22 层、约一半到第二幕）。明显偏低说明蒸馏损失大，先停下来看。
- 前几次更新 `forks_complete > 0`、`fork_card` 为 0；`target_passes` 多数应在 1 以上（低于 1 时学习率会自动下调，看 `lr`；第四轮长期 0.4）。
- `recompute_max_abs`（`metrics.jsonl`）：FP32 下应在 1e-4 以下；明显更大说明更新看到的输入和采样时不一样，是真问题。
- 速度：`seconds_per_episode`（第四轮 FP32 实测约 4.4–4.7 秒/局），以及分叉开销 `fork_branch_combats` 对主线战斗数（`combats_mean × rollout_episodes`）的比例（第四轮带选牌分叉实测约 2.3 倍；关掉后按第四轮的构成估计约 1 倍，未实测）；太慢就调低 `--fork-rest`。

验收（与第二轮最后 2,000 局、以及第一段的 `[val @0]` 比较）：验证集平均层数、到第二/三幕率、通关数；`rest_heal_rate_full_hp` 下降且 `rest_heal_rate_hp_below_50` 保持较高；`fork_rest_taken_was_best`、`fork_map_taken_was_best` 结合 `fork_decisive` 与 `fork_tie_rate` 看是否上升。多项同时改动，结果不能归因到单项。

已知局限（已向用户说明）：选牌分叉关闭后，选牌只靠 PPO 的整局回报学，信号弱而且慢（第四轮的选牌分叉也没有带来可测的改进）；跨幕的长程影响只能随着到后期的局变多而逐步改善。第四轮的分叉损失没有上限，把策略推到了几乎完全确定（见 2.1），2026-11-14 已改；新损失的三个参数（`target_scale=1`、`adv_clip=3`、`prob_floor=0.01`）和学习率 3e-5 是按分析定的初值，没有在 GPU 上验证；11-15 的改动（menu_loop 截断的计法、关闭选牌分叉后的速度）同样没有在 GPU 上验证。火堆分叉只跑两场战斗，对升级不利，未改。每段重建优化器（已加学习率预热）。

**后期战斗上限（本机实验，`artifacts/analysis/claude-combat-ceiling-20261111/`）**：重放第二轮后期（rollout 170–233）到过第二幕的对局，在第二幕及以后的战斗开打前复制状态，同一场分别用 1 倍（现配置）、4 倍、16 倍搜索各打 2 个搜索种子。

| 战斗 | 场数 | 死亡率 1× / 4× / 16× | 掉血（占最大生命）1× / 4× / 16× | 16× 对 1× 的成对差 |
| --- | ---: | --- | --- | --- |
| 普通与精英（由多选一的地图决策进入，`results.jsonl`） | 106 | 12.3% / 9.4% / 7.1% | 15.3% / 12.6% / 10.6% | 死亡率 −5.2 个百分点（标准误 1.8），掉血 −4.7（1.0） |
| 普通（含被迫进入的，`results_v2.jsonl` 前 30 局） | 65 | 12.3% / 3.8% / 6.2% | 17.6% / 13.9% / 12.4% | 死亡率 −6.2（3.4），掉血 −5.3（1.2） |
| **第二幕 Boss**（`results_v2.jsonl`） | 19 | 81.6% / 78.9% / 73.7% | 68.0% / 66.8% / 64.1% | 死亡率 −7.9（8.8），不显著 |

读法：普通战斗里增加搜索量有明确的小幅收益（一幕约 8 场，会累积）；第二幕 Boss 在现有牌组下死亡率很高，但只有 19 场，16 倍搜索的收益仍不确定，不能据此认定更多搜索无用，也不能区分牌组强度、搜索评估和预算的影响。逐张卡牌分叉与战斗策略／价值网络都值得验证；根先验会改变搜索分配，不等同于增加模拟次数，叶子价值更有效也只是待验证假设。局限：样本全部来自第二轮策略的牌组；每个文件里约 10% 的对局在本机重放中途分叉而被截断；精英样本只有 5–6 场。v1 脚本只在地图决策处取样，抓不到 Boss（Boss 房是唯一出口，不是决策），v2 改为在战斗开始处取样。

### 2.4 讨论过、但未采用或未实现

**讨论备忘：**四个缺口为对手与候选牌的条件价值、幕内与跨幕信用分配、后期样本覆盖、选牌与战斗能力衔接。论文思路、来源及候选实验集中在[训练缺口文档第 2.1 节](docs/claude-training-gaps-and-mcts-plan-20261110.md#21-四个训练缺口论文思路与后续实验)。建议保留 PPO，先分析带回的数据，再比较“当前 MCTS／纯战斗网络／同网络＋小预算搜索”；抓牌分叉与实际执行使用同一战斗器。此处只记录方向，没有实施新训练方案。

| 方向 | 状态 |
| --- | --- |
| 起点课程（从模型自己打到的第二/三幕开头开始训练） | 用户认为不够端到端，**暂不采用** |
| 奖励去掉每层奖励、只奖励打过 Boss 与通关 | 建议过，未采用 |
| 奖励遗物数量 | 用户放弃。若以后要做，建议基于势函数（持有遗物给奖励、结束时扣回），避免诱导钻空子 |
| 小策略网络（5–20M、短历史） | **第四轮已采用**（`small` 预设，约 0.02B、8 步历史），用蒸馏接上第二轮的策略 |
| 在 0.2B 模型上截短历史做对照评估（32/8/1 步） | 建议过；用户决定不做，直接用 8 步 |
| 验证时取概率最高的动作（`eval --greedy`） | **2026-11-12 已实现**（用户同意），见 2.3。只是单独的测量命令；训练中的验证和 `best.pt` 的选择仍按概率采样，没有改。结果出来后再决定要不要让训练中的验证也报一份取最大的成绩 |
| 奖励界面去掉或减小熵奖励 | 已向用户提出，**待定、未实现**。目的是不让没有信号的“白拿”决策被推向随机。不违反“不代选”的约定，选择仍由模型做 |
| 战斗出牌审计（有斩杀机会却没斩杀的回合数） | 未做；建议和战斗网络一起做 |
| 按选项打分的价值头（缺口 1，用分叉结果监督） | **2026-11-15 离线测过，否定，不接入**（诊断文档第 7 节）。局限：用的是冻结的、已饱和策略的特征；选牌上不经过网络的“只用卡牌 ID”也学不出规律，所以不像是特征的问题 |
| Decision Transformer（回报条件监督） | 骨架（因果历史 Transformer）还在，但去掉了目标回报输入与监督训练。因结果高度依赖运气、通关样本只有 23 个，**不建议作主方法**；可做“筛选后模仿”初始化 |
| 战斗网络（策略＋价值）与可选 MCTS | 未实现，**用户希望打通战斗与选牌，并保留网络直接出牌的目标**。`search.h` 已有 `mcts_priors` 根先验、`MctsPriorFn` 节点先验和 `MctsValueFn` 叶子价值回调，但当前 `play_combat_mcts` 未接入。先对照纯网络与搜索增强，再决定在线搜索预算；固定一版战斗器采集局外与抓牌分叉数据，升级后重新适应。共享实体编码器可另作对照。仅用公开信息（NoSL），注意统一搜索评分并验证吞吐；详见上述讨论备忘 |
| 加大 Boss 战的搜索量（512 → 2048） | 2026-11-14 提过先做一次成对评估；用户认为没什么用，**不做** |
| 战斗里试牌（选牌的另一种训练办法，不走 PPO） | 2026-11-15 和用户讨论过，**用户还没有决定做，没有实现也没有验证**。做法：选牌时把每张候选牌加进牌组，各自去打一批战斗（本幕 Boss、精英、普通怪），用掉血和死亡率作标签，监督训练选牌的打分头。长程分三层：测试里加后面几幕的敌人（牌组冻结，测不出与以后的牌的配合）；让分支先正常打一段，再对那时的牌组做同样的测试；训练“牌组对某个敌人掉多少血”的预测器，把价值一步步往回传。局限：偏向眼前有用的牌；测的是牌在现有战斗器手里的表现。建议先在本机离线检验（同一张牌测两批战斗结果是否一致、近处和远处的战斗给出的排名差多少），前提是确认模拟器能直接开指定的战斗。与已否定的缺口 1 不同：那次的标签是“走了几层”，这里是战斗掉血 |
| 降低通关奖励在学习信号里的占比 | 2026-11-15 作为选项提过（通关项占回报方差约 70%）。权重是用户定的，**未改** |
| Zero-Search STS2 预印本（arXiv 2611.12088v1，PDF 在仓库根目录，未跟踪，**不要提交**） | 2026-11-15 读了全文，只是讨论，没有改动。做法：一个 6.6M 的实体 Transformer（6 层、宽 256、无历史窗口）同时打战斗和做局外选择，不搜索；普通 PPO（每次 65,536 个样本、2 遍）；奖励每层 0.01、精英 0.02、Boss 0.1、通关 1、死亡 −0.1，加血量势函数；一半的局从自己到过的状态重启。铁甲 A0 89.8%、A10 15.6%。**强在训练量**：铁甲 16.6 亿个决策；它自己从头训 5,000 万个决策的对照组在 A0 只有 3–13%（Regent、Silent）。吞吐约 6 万局/小时（256 个模拟器进程，战斗不搜索），我们约 800 局/小时。重启课程在它自己的对照里只对一个角色有效（Regent +3.6 个百分点，Silent 无差别）。互换实验：局外策略与自己的战斗器配套，换成别人的战斗器胜率大跌；“它的局外 + 别人的搜索战斗”是 Regent 上最强的组合。条件不同（v0.107.1、自动拿金币、观察含敌人下一招的内部 ID），不能直接比。可参考：战斗也由网络直接打以换取吞吐（与已列的战斗网络方向一致）、EMA 权重加取最大评估、无历史的单网络结构、死亡惩罚与 Boss／精英奖励（奖励由用户定） |
| 接入真实游戏 | 未实现。仓库有 10 月的旧 ArmG 实机接入（`src/SlayTheModel.Sts2.ModAdapter`、`scripts/armg_live_worker.py`，近似观察，只覆盖选牌/选路，未整局验收）。新网络需要模组导出完整公开状态、在 C++ 中重建 `RunContext` 再调用同一 `macro_observation`，并覆盖全部界面的动作映射。建议先做只显示建议的影子模式 |
| A10、自动升阶课程、精确断点续跑 | 未实现；CLI 没有 `--ascension` |

---

## 3. 代码与证据地图（相对仓库根）

| 内容 | 路径 |
| --- | --- |
| 训练包 | `model/spire_rl/spire_rl/`：`config.py` 全部超参与预设；`model.py` 网络；`data.py` 批构建与动作分组；`env.py` 宏观环境、奖励、菜单循环保护、`fork()`；`rollout.py` 并行采样、分叉；`ppo.py` GAE、PPO、critic 训练、分叉损失；`train.py` 训练循环、热启动；`pretrain.py` 离线 critic；`distill.py` 离线策略蒸馏；`checkpoint.py`；`archive.py`；`metrics.py`/`dashboard.py`；`tools.py` 资源与环境检查；`__main__.py` CLI |
| 训练包说明与修订记录 | `model/spire_rl/README.md`（第 8 节按日期记录每批改动） |
| 导出配置（仅说明用，CLI 不读） | `docs/configs/spire-rl-{main,large-1b,large-0.7b}.json` |
| C++ 模拟器（唯一可编辑副本） | `artifacts/dev/cpp-native-aligned-20261031/`；宏观观察与战斗驱动 `simulator/src/macro_obs.cpp`；MCTS `simulator/src/mcts.cpp`；隐藏信息重采样 `simulator/src/battle.cpp` 的 `resample_hidden`；卡牌公开键 `simulator/include/sts2/common.h` 的 `card_public_key`/`card_canonical_less` |
| 训练原始数据 | `runs/training-review/main-a0-s{1,2}/`、`runs/training-review/small-a0-d{1,2,3}/`（未被 git 忽略，**不要提交**） |
| 第一轮分析（Codex） | `artifacts/analysis/main-a0-s1-20261110/`（`trajectory_decisions.npz` 等） |
| 第一轮分析（Claude） | `artifacts/analysis/claude-run1-20261110/`：`a1–a14.py` 统计、`boss_exp.py` 受控分叉、`bc_test.py` 模仿测试、`seaglass/` G3 快照检查 |
| 第二轮分析（同学） | `artifacts/analysis/main-a0-s2-review/`。注意其 `component_rtg` 列不是原始层数单位 |
| 第二轮分析（Claude） | `artifacts/analysis/claude-run2-20261111/`：`rest_pass.py`/`rest_an.py` 火堆、`critic_an2.py` critic、`value_test.py` 离线价值测试 |
| NoSL 修复证据 | 副本内 `validation/nosl-fix-20261110/README.md`（修复前审计 `validation/nosl-audit-20261110/` 保留未动） |
| The Future of Potions 修复证据（v8） | 副本内 `validation/future-potions-fix-20261111/README.md` |
| 第四轮分析（Claude） | `artifacts/analysis/claude-run4-20261114/`：`extract.py`（从归档抽表）、`an1–an3.py`（优势与回报方差、分叉可靠度、行为与死亡楼层）、`grad_exp.py`（检查点上的对数概率和各损失项梯度）、`grad_*.log`；缺口 1 离线测试 `optval_extract.py`（抽冻结特征）、`optval_fit.py`（打分头与噪声上限对比）、`optval_cardid.py`（只用卡牌 ID 的对照），结果在 `optval/`（`feat_*.pkl` 约 160 MB） |
| 修复后一轮分析（Claude） | `artifacts/analysis/claude-runb-20261115/`：`extract.py`（第四轮脚本加了运行名参数）、`behav.py` 行为与死亡楼层对照、`rest.py` 火堆分叉标签、`cf_probe.py`/`cf_critic.py` 反事实敏感度、`rest_probe.py`+`linprobe.py` 决策向量探针、`rest_baseline.py`、`fit_rest.py` 只用火堆分叉的监督训练测试 |
| 后期战斗上限实验（Claude） | `artifacts/analysis/claude-combat-ceiling-20261111/`：`ceiling.py`（重放第二轮后期对局，在第二幕及以后的战斗前复制状态，用 1/4/16 倍搜索各打一遍）、`report.py`、`results*.jsonl`、`report*.txt` |

`artifacts/` 整体被 git 忽略（见第 7 节）。

---

## 4. 版本与身份

- 目标原生：`v0.111.0 / 41cef1ea`，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- C++：ruleset **`native-41cef1ea-port-v8`**（2026-11-11 The Future of Potions 修复；第二轮与第三轮那次启动用的是 v7，第一轮 v6）；公开观察 v15（布局未变）、动作 v14、快照 v10、ArmG 特征 6；**宏观观察 `MACRO_OBS_VERSION=2`**（候选 5 维，第 5 维为“取消已选网格牌”）。`PORT_SOURCE.json` 与副本 `agent/engine_identity.py` 已同步。
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
- 用户偏好：端到端训练、让模型自己摸索策略；希望最终是“Transformer 给先验、MCTS 辅助搜索”，并让打牌与选牌的模型衔接。分析要基于原始数据，区分已确认、较强怀疑与证据不足。
- 训练机是同学的，GPU **只能在用户工作时间挂着用**，用户不清楚那台机器的 CPU 核数等细节（只知道 RTX 5090 24G）。方案要能按工作日分段、到点正常退出；中途丢一些进度可以接受；不要多存检查点（怕占满硬盘）。
- 用户不熟悉实现细节，希望直接给建议和判断；解释时用平实的话，先说结论。

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

- 本机 `sts2_sim` 扩展是 v8 新构建（SHA 见 `validation/future-potions-fix-20261111/README.md`）。训练期 WSL 轨迹在本机重放时约 22% 会中途分叉（跨平台浮点差异），精确重放应在同一平台做。

### 6.2 用户的训练机（Windows `LegionB` + WSL2）

- RTX 5090（用户报 24 GB），Conda `slay`，Python 3.12.0，仓库 `/mnt/c/Users/yebohou/SlayTheModel`；`spire_rl` 以 `pip install -e` 安装（拉代码即生效）。第二轮 GPU 峰值约 5.8 GiB。
- C++ 改动后需在训练机重编：`CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py`，然后确认 `sts2_sim.ENGINE_RULESET_ID` 与 `MACRO_OBS_VERSION`。训练机已是 v8（第四轮 `config.json` 记录的 ruleset 为 `native-41cef1ea-port-v8`）；2026-11-14、11-15 的修复不涉及 C++，不用重编。
- 该机 CPU 不支持 BF16 反向（oneDNN `avx2_vnni_2`），BF16 测试有 GPU 时在 GPU 上跑，否则跳过；训练不受影响。
- 训练命令见 2.3；TensorBoard：`tensorboard --logdir runs/<run>/tensorboard --host 127.0.0.1 --port 6006`。
- Windows 原生（非 WSL）训练未适配（`tools.py` 依赖 Unix `resource`）。

---

## 7. 提交与上传

- 根 `.gitignore` 忽略 `artifacts/`：已提交文件的改动 git 能看到，**新建文件看不到**，要按清单强制添加。清单 `docs/native-port-upload-paths-20261109.txt`（1912 条，含 NoSL 修复证据文本，2026-11-16 补了战斗观察与 NetSearch 的 4 个新文件；不含编译产物、可执行文件、`obj/`）。**不要 `git add -f artifacts/` 整目录**，不要把原生安装备份、训练输出、权重、分析目录加入源码提交。
- **`runs/` 没有被忽略**，提交前必须排除；不要用 `git add -A`。
- `574b997` 已包含第四轮及之前的全部工作。此后未提交的内容（2026-11-14、11-15）：`AGENTS.md`；`docs/claude-run4-diagnosis-20261114.md`（新文件）；`docs/claude-training-gaps-and-mcts-plan-20261110.md`（同学补充的第 2.1 节）；`model/spire_rl/`（`README.md`、`spire_rl/config.py`、`ppo.py`、`rollout.py`、`train.py`、`__main__.py`、`tests/test_spire_rl.py`）。C++ 副本没有改动。**2026-11-16 又增加**：`docs/claude-runb-diagnosis-20261116.md`（新文件）；`model/spire_rl/spire_rl/combat_net.py`、`combat_play.py`、`unified_obs.py`、`unified_net.py`、`unified_data.py`、`unified_pretrain.py`、`unified_train.py`、`unified_play.py`、`unified_run.py`、`model/spire_rl/unified_gpu.sh`、`tests/test_combat_net.py`、`tests/test_unified.py`、`tests/test_unified_play.py`（新文件）、`docs/claude-unified-net-design-20261116.md`（新文件）和 `env.py`、`rollout.py`；C++ 副本的 `simulator/bindings/bindings.cpp`、`include/sts2/search.h`、`src/mcts.cpp`、`validation/build.json`（已跟踪，git 能看到），以及**新文件** `include/sts2/combat_obs.h`、`src/combat_obs.cpp`、`include/sts2/net_search.h`、`src/net_search.cpp`。后四个在被忽略的 `artifacts/` 下，提交时要逐个 `git add -f`，并补进上传清单。`artifacts/analysis/` 下的实验脚本与结果不在清单里（不提交）；`runs/` 不提交；根目录的 `2611.12088v1.pdf`（同学发来的论文）不提交。
- 参考命令（由用户执行）：

  ```sh
  git add AGENTS.md docs/claude-run4-diagnosis-20261114.md docs/claude-training-gaps-and-mcts-plan-20261110.md model/spire_rl
  git diff --cached --stat        # 确认没有 runs/、权重、归档
  git commit -m "Run 4 diagnosis: bounded fork loss, fork replay, KL rollback, adaptive policy lr; gap-1 test, menu-loop fix"
  ```

---

## 8. 模拟器（原生对齐）线

这条线目前不是重点，但规则约定仍有效。

**已完成（避免重做）**：种子/哈希/RNG 对齐、抽洗牌、手动选牌、牌实例状态、596 个原生卡牌数据导出；另外四个角色的牌池与机制（静默、故障机器人、亡灵契约师与原生样例差分 0 失败，储君只按源码）；遗物真实选择与持续状态（Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher 等，均有原生样例）；物理药槽空位；34 个缺失事件（含小游戏与专用战斗）；Aeonglass Boss；普通地图与 6 张原生录制地图逐点一致；epoch 内容过滤（生成器 `simulator/tools/gen_epoch_unlocks.py`）；原生费用修正栈；卡牌奖励选项钩子与 Lasting Candy；**2026-11-10 NoSL 修复**（重采样按全部卡牌字段规范化、公开排序补齐字段、`orbRng` 接入运行级 CombatOrbs 流）；**2026-11-11 The Future of Potions**（Event / Token 稀有度药水的卡牌稀有度与类型，ruleset v8）。详细记录：副本 `validation/round4-step2-resume-20261108/README.md`、`validation/round4-step3-events-20261108/README.md`、`validation/nosl-fix-20261110/README.md`、`validation/future-potions-fix-20261111/README.md`。

**最近一次完整回归（2026-11-11，ruleset v8，本机）**：C++ 36 个程序全部通过；Python（torch 桩）167 通过、10 失败、34 错误，失败集合与 v7 记录逐项相同（缺 torch/cmake 等环境原因）；1000 局贪心冒烟 0 异常、层数/战斗数/步数与 v7 记录相同；地图 6/6；药水事件探针 6 种药水 × 300 种子 0 异常。NoSL 探针（15 + 20 项）是 v7 时的结果，本次未重跑。

**剩余事项**：
- 第三步起新增规则缺目标 DLL 的执行验证；尚无同种子、同进度、同决策的整局原生对照。11 月 3 日删过部分 fixture 宿主/缓存，恢复前不能生成新样例；旧样例结果在副本 `native-*-fixtures/`。出现差异以 DLL 为准改 C++，不改样例。
- NoSL 检查尚未在 Linux/WSL 上运行；CombatOrbs 映射未经 DLL 实测；怪物内部字段与所有已知顶牌来源未穷尽审计。
- C++ `double` 与原生 `decimal` 的取整边界；固定牌堆、遗物容量边界。
- `after_hand_drawn` 中 Mayhem 与遗物先后与原生不同（只影响非铁甲组合）。
- `nextTurnEnergy` / `nextTurnDraw` 观察字段恒为 0（占位）。
- 多人专用内容只保证单人不可达。
- 药水表（`gen_potions.py`）把原生 Event / Token / None 稀有度都写成 `SPECIAL`；目前只在 The Future of Potions 里按原生还原。其他按药水稀有度分支的规则若要区分这三种，需要同样处理或改生成器。
- 训练 1.6 万局后才暴露出一个会抛异常的事件分支，说明事件里还可能有类似的少见分支；现在这类异常只会让单局失败并记录原因（`failure_reasons`），看到新的原因要回来修。

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
| [docs/claude-unified-net-design-20261116.md](docs/claude-unified-net-design-20261116.md) | **最新**：统一网络设计（局内局外一个网络、本幕 Boss 价值、跨幕权重 w、检查与验收、开工前待拍板的 5 件事、分步实施） |
| [docs/claude-runb-diagnosis-20261116.md](docs/claude-runb-diagnosis-20261116.md) | 修复后一轮的诊断、策略不看血量的证据、换结构的要求与建议步骤 |
| [docs/claude-run4-diagnosis-20261114.md](docs/claude-run4-diagnosis-20261114.md) | 第四轮三段的诊断、2026-11-14 的修复、下一轮的判断标准（第 6 节）、缺口 1 的离线测试（第 7 节） |
| [docs/claude-run2-diagnosis-20261111.md](docs/claude-run2-diagnosis-20261111.md) | 第二轮诊断、方向判断、第三轮实现与验收 |
| [docs/claude-run2-review.md](docs/claude-run2-review.md) | 同学（Codex）对第二轮的交接 |
| [docs/claude-run1-diagnosis-and-fix-plan-20261110.md](docs/claude-run1-diagnosis-and-fix-plan-20261110.md) | 第一轮诊断、P0 修复、受控 Boss 分叉、模仿测试（第 11 节） |
| [docs/claude-training-gaps-and-mcts-plan-20261110.md](docs/claude-training-gaps-and-mcts-plan-20261110.md) | 第一轮分析与建议（G1–G11）；第 2.1 节为 2026-11-15 补充的四个训练缺口、论文思路与候选实验 |
| [docs/mcts-nosl-audit-20261110.md](docs/mcts-nosl-audit-20261110.md) | NoSL 修复前的审计 |
| `model/spire_rl/README.md` | 训练包实现、与设计的差异、命令、逐批修订记录 |
| [docs/st-dt-training-handoff-20261110.md](docs/st-dt-training-handoff-20261110.md) | 最初的 ST-DT（v3）设计；设计不等于实现 |
| [docs/local-cleanup-20261108.md](docs/local-cleanup-20261108.md) | 本地清理背景 |
