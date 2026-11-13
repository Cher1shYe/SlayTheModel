# SlayTheModel：交接说明

更新：2026-11-12（Claude：第四轮首次启动被精度检查拦停、已修复之后）。本文件是**接手的唯一入口**：先读第 0–2 节了解现状，再按需查后面的约定、路径和命令。源码、日志与本文不一致时，以源码和原始日志为准，并更新本文。

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
| **第四轮** | 代码**尚未提交**：C++ 崩溃修复（ruleset v8）、`small` 预设（约 0.02B、8 步历史）、离线蒸馏、逐张卡牌分叉、按工作日分段训练。见第 2.3 节和模块 README 第 2.5、8 节 |
| 第四轮首次启动（2026-11-12，`runs/small-a0-d1`） | 蒸馏成功：`[val @0]` 22.1 层 / 0.46 到第二幕 / 1 通关。跑了 7 次更新（240 局，约 4.7 秒/局；每轮平均层数 20.5 → 27–30，样本少、不算结论；熵 0.82 → 0.51），第 8 次更新前被概率重算检查拦停（0.053 > 0.05）。**原因是 BF16 舍入，已修**（`small` 改 FP32、输出头固定 FP32、BF16 限值 0.25），同时加固：报错或 Ctrl+C 退出也保存 `last.pt`；新增 `eval --greedy`。本机 53 项测试通过，**修复后尚未在 GPU 上重跑**。见 2.1 最后一条和模块 README 第 8 节第一条 |
| 下一步 | 用户把修复同步到训练机，按第 2.3 节“现在要做的”重新启动第一段（原指令不变，先把旧的 `runs/small-a0-d1` 改名；不用重编、不用重新蒸馏）。**未经用户指示不要启动、停止或修改远端训练** |

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
2. `git status`：远端与本地最后的提交都是 `44ac1bc`（第三轮代码，分支 `v111_SF1`）。**第四轮准备的全部改动在工作区里未提交**，见第 7 节。`ForkConfig` 增加了字段，所以用当前代码重算的配置指纹与第二轮 `config.json` 里的 `6f7cdf5dc22aa79b` 不再相同。
3. 训练机上可能有崩溃的第三轮目录 `runs/main-a0-s3/`（约 1.8 GB 检查点，可删）和 `runs/critic-prior-s2.pt`；还有第四轮的 `runs/distill-small.pt`（蒸馏结果，继续用）和被拦停的 `runs/small-a0-d1/`（其中 `last.pt` 等于蒸馏结果；重新启动前改名为 `runs/small-a0-d1-crashed`，其中的 `metrics.jsonl` 还没带回本机）。训练机上的权重**不在这台 Mac 上**；第二轮的 `best.pt`/`last.pt` 是 ruleset v7 的，v8 构建会拒绝加载。
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

### 2.2 当前训练框架要点（`model/spire_rl/`，细节见模块 README）

- **网络 SpireNet**：实体 Set Transformer（地图连边消息传递）→ 因果历史 Transformer（最近 N 个决策，每步 g/z/a/r 四个 token；g 不含奖励档位，r 只含事件计数：新完成层数、新进幕、通关）→ 候选指针打分。策略 = P(动作组) × P(组内目标)，“取消已选网格牌”单独成组。预设 `main` 约 0.202B、32 步历史（其中历史 Transformer 约 176M），配 critic `CRITIC_SMALL` 约 19.6M；预设 `small` 约 0.02B、8 步历史，配 `CRITIC_LITE` 约 1.9M。critic 输出未来层数/50、未来进幕/2、通关概率三分量，任意 α 下线性组合成标量价值。
- **环境**：一次转移 = 一次真实局外选择；只有一个合法动作的界面自动执行；战斗由 `RunContext.play_combat_mcts()` 跑完；观察来自 `RunContext.macro_observation()`（宏观观察 v2，候选 5 维）。同一网格连续 64 个决策以 `menu_loop` 截断，单局上限 600 个决策；不代选、不代确认。
- **奖励**：`r_raw = 5×通关 + α×(0.05×新完成层 + 0.5×新进第二/三幕)`，训练值除以 5，γ=1、GAE λ=0.99。默认按 2k/4k/6k 局 α 从 1/0.5/0.2 降到 0，门槛不满足时默认 `hold`（继续训练）；第三轮可用 `--alpha` 固定单档。
- **PPO**：策略 lr 3e-5（`small` 预设 1e-4，另有 150 步学习率预热），最多 3 遍；KL 早停每 8 步在固定 512 个样本上测（>0.015 停），单小批 >0.04 也停；组熵额外奖励 0.01。critic lr 1e-4，每次更新 2 遍（当前批 + 最近 12 轮的回放各一份）。
- **保存**：`best.pt`（验证胜率更高，或胜率相同而平均层数更高时）和 `last.pt`（每次验证后、训练正常结束或 `--max-hours` 到点时），都含 critic，只存权重（不能精确断点续跑）。报错或按一次 Ctrl+C 退出时也保存 `last.pt`（`progress.final=false`；权重含非有限数或还没做过更新时不覆盖）；直接关窗口或 `kill` 不保存。检查点格式 `spire_rl/3`，`progress.next_train_seed` 记录下一个未用的训练种子；归档格式 `spire_rl.archive/3`（增加分叉审计记录，仍可读 /1、/2）。
- **监控**：每个 run 目录有 `metrics.jsonl`（每次更新一行）、`eval.jsonl`、`eval/val_ep*.json`、`dashboard.html`、`archive/rollout_*.npz`、可选 TensorBoard。重点字段：`value_ev_floors`、`rest_heal_rate_full_hp`、`rest_heal_rate_hp_below_50`、`entropy_group`、`target_passes`、`kl_stop_reason`、`menu_loops`，第三轮再加分叉相关字段（见 2.3）。

### 2.3 第四轮方案（已实现；2026-11-12 首次启动跑了 7 次更新，精度问题修复后尚未重跑）

用户 2026-11-11/12 的决定：GPU 只能在用户工作时间分段使用，所以**换小网络**；历史**保留 8 步**（用户直接拍板，不做“截短历史”的对照评估）；保持端到端；分叉是主要的信号来源；通关奖励的权重保持最大，只是分叉里不使用 critic 对通关的估计；训练中途丢进度可以接受；检查点不要多存。

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| 小网络 | 预设 `small` | Set Transformer 256 × 2 ISAB，历史 512 × 4 层、8 步，约 0.02B；`lr=1e-4`（未验证的初值）、`microbatch=32`、学习率预热 150 步、**FP32**（`--bf16` 可改回，FP32 的速度未实测）。critic `CRITIC_LITE` 约 1.9M、dropout 0.1 |
| 离线蒸馏 | `distill --archive <归档> --out <ckpt> --preset small` | 对归档里策略采样的动作做最大似然，同时从随机初始化训练 critic；默认最后 60 个文件、留出 6 个；输出普通检查点。报告 `kl_estimate`（与教师策略的差距）、`top1`、`critic_ev` |
| 逐张卡牌分叉 | `--fork-card <概率>` | 选项 = 每张可拿的牌 + 跳过；分支跑到本幕结束（或本局结束），回报只计真实事件，不加 critic 估计 |
| 火堆/地图分叉 | `--fork-rest/--fork-map` | 与第三轮相同（2 场战斗 / 40 个决策 / 换幕，其余由 critic 估计），但不再使用 critic 的通关分量；各界面的优势分别归一 |
| 分段训练 | `--max-hours H` + `--init-checkpoint <上一段>/last.pt` | 到点后不再开始新一轮采样，保存 `last.pt` 正常退出。训练种子按检查点的 `next_train_seed` 接续（蒸馏检查点从 2,000,000 起） |
| 异常不再终止整轮 | `env.py` | C++ 异常记为该局 `FAILURE`（终端会打印数量和原因）；单轮失败超过 `max(2, 2%)` 仍会停，停之前保存 `last.pt` |
| 取最大评估 | `eval --greedy`，再用 `compare` | 每步取概率最高的动作，种子与采样评估相同；`compare` 给同种子配对的层数差和标准误。只是测量，训练和训练中的验证仍按概率采样。**未在训练好的策略上跑过** |
| 其他 | | `--lr`、`--bf16/--no-bf16`、`--train-seed-base`；`best.pt` 胜率相同时比平均层数；第三轮的 `--init-checkpoint`、`pretrain-critic`、critic 回放、`--alpha` 仍可用 |

**现在要做的（2026-11-12 起）**：训练机上已经编译过 v8、已经蒸馏出 `runs/distill-small.pt`，所以**不用重新编译，不用重新蒸馏**，训练指令和首次启动时相同。首次启动的 `runs/small-a0-d1/last.pt` 是第 0 局验证时存的，等于蒸馏结果，仍从 `runs/distill-small.pt` 开始。

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
python -m pytest -q model/spire_rl/tests            # 同步代码后确认：53 passed
mv runs/small-a0-d1 runs/small-a0-d1-crashed        # 挪开首次启动的目录（不要删，metrics.jsonl 要带回来）
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-a0-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0.05 --fork-seeds 2 --fork-coef 2
# 第二天起只改：--run-dir runs/small-a0-d2 --init-checkpoint runs/small-a0-d1/last.pt（第三天 d3 接 d2，依此类推）
```

- 要同步到训练机的文件：`model/spire_rl/spire_rl/` 下的 `model.py`、`config.py`、`train.py`、`rollout.py`、`tools.py`、`__main__.py`，以及 `model/spire_rl/tests/test_spire_rl.py`。
- 启动后看：`[val @0]` 约 22 层、接近一半到第二幕；第 8 次更新能过去；速度对照首次启动的 4.66 秒/局，明显变慢则下次加 `--bf16`。
- 到点自己停并保存 `last.pt`。提前停按一次 Ctrl+C，等打印 `saved to .../last.pt`；直接关窗口不保存。中途报错也会先保存 `last.pt`，修好后从它用新的 `--run-dir` 接着跑。
- 每天带回当天 run 目录的 `metrics.jsonl`、`eval.jsonl` 和终端输出；第一次带上 `runs/small-a0-d1-crashed/metrics.jsonl`。
- 详细步骤见模块 README 第 2.5 节。

从头做一遍的命令（换机器、C++ 又改了、或需要重新蒸馏时；**C++ 改过就必须先重新编译**）：

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"      # native-41cef1ea-port-v8
python -m pytest -q model/spire_rl/tests                                     # 53 项

# 1) 一次性蒸馏（只读第二轮归档）
python -m spire_rl distill --archive runs/main-a0-s2/archive --out runs/distill-small.pt --preset small --device cuda

# 2) 每个工作日一段；--max-hours 设为能挂的小时数减去约 20 分钟
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-a0-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0.05 --fork-seeds 2 --fork-coef 2
# 第二天起只改：--run-dir runs/small-a0-d2 --init-checkpoint runs/small-a0-d1/last.pt
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
- 前几次更新 `forks_complete > 0`、`fork_card > 0`；`target_passes` 不应长期低于 0.5（否则 `--lr` 调低）。
- `recompute_max_abs`（`metrics.jsonl`）：FP32 下应在 1e-4 以下；明显更大说明更新看到的输入和采样时不一样，是真问题。
- 速度：`seconds_per_episode`（首次启动、BF16 时第 7 次更新为 4.66 秒/局，改 FP32 后明显变慢再考虑 `--bf16`），以及分叉开销 `fork_branch_combats` 对主线战斗数（`combats_mean × rollout_episodes`）的比例。粗估 `--fork-card 0.05` 时模拟器工作量约为无分叉的 3 倍、0.1 时约 5 倍（**未实测**）；太慢就调低 `--fork-card`。

验收（与第二轮最后 2,000 局、以及第一段的 `[val @0]` 比较）：验证集平均层数、到第二/三幕率、通关数；`rest_heal_rate_full_hp` 下降且 `rest_heal_rate_hp_below_50` 保持较高；`fork_card_taken_was_best`、`fork_rest_taken_was_best` 结合 `fork_decisive` 与 `fork_tie_rate` 看是否上升。多项同时改动，结果不能归因到单项。

已知局限（已向用户说明）：逐张卡牌分叉针对的是**幕内**的选牌（第 3 层选的牌对上本幕 Boss）；跨幕的长程影响只能随着到后期的局变多而逐步改善。分叉损失没有 PPO 那样的裁剪，只靠 KL 早停限幅，要看 `entropy_group` 和火堆回血率是否被推到 0 或 1。每段重建优化器（已加学习率预热）。

**后期战斗上限（本机实验，`artifacts/analysis/claude-combat-ceiling-20261111/`）**：重放第二轮后期（rollout 170–233）到过第二幕的对局，在第二幕及以后的战斗开打前复制状态，同一场分别用 1 倍（现配置）、4 倍、16 倍搜索各打 2 个搜索种子。

| 战斗 | 场数 | 死亡率 1× / 4× / 16× | 掉血（占最大生命）1× / 4× / 16× | 16× 对 1× 的成对差 |
| --- | ---: | --- | --- | --- |
| 普通与精英（由多选一的地图决策进入，`results.jsonl`） | 106 | 12.3% / 9.4% / 7.1% | 15.3% / 12.6% / 10.6% | 死亡率 −5.2 个百分点（标准误 1.8），掉血 −4.7（1.0） |
| 普通（含被迫进入的，`results_v2.jsonl` 前 30 局） | 65 | 12.3% / 3.8% / 6.2% | 17.6% / 13.9% / 12.4% | 死亡率 −6.2（3.4），掉血 −5.3（1.2） |
| **第二幕 Boss**（`results_v2.jsonl`） | 19 | 81.6% / 78.9% / 73.7% | 68.0% / 66.8% / 64.1% | 死亡率 −7.9（8.8），不显著 |

读法：普通战斗里加搜索量有稳定的小幅收益（一幕约 8 场，会累积）；**第二幕 Boss 在现有牌组下八成打不过，16 倍搜索也基本不变**（满血进场的也多数失败）。所以第二幕的墙主要不在搜索次数上，而在牌组强度或搜索对局面的评估（随机模拟）上，这个实验分不开后两者。对后续的含义：选牌这条线（逐张卡牌分叉对上本幕 Boss）是对症的；战斗网络如果只做根先验（等效于更多搜索），对 Boss 的帮助预计有限，叶子价值更值得先试。局限：Boss 只有 19 场、全部来自第二轮策略的牌组；每个文件里约 10% 的对局在本机重放中途分叉而被截断；精英样本只有 5–6 场。v1 脚本只在地图决策处取样，抓不到 Boss（Boss 房是唯一出口，不是决策），v2 改为在战斗开始处取样。

### 2.4 讨论过、但未采用或未实现

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
| Decision Transformer（回报条件监督） | 骨架（因果历史 Transformer）还在，但去掉了目标回报输入与监督训练。因结果高度依赖运气、通关样本只有 23 个，**不建议作主方法**；可做“筛选后模仿”初始化 |
| 战斗网络（先验或叶子价值）+ MCTS | 未实现，**用户希望做**（最初 ST+DT 思路的来源：Transformer 给先验，MCTS 辅助搜索；打牌与选牌的模型衔接）。C++ 搜索已有先验接口（`search.h` 的 `mcts_priors` 根先验、`MctsPriorFn` 按深度的节点先验），但训练用的 `play_combat_mcts` 没接，叶子仍是随机模拟。建议顺序：先跑通第四轮；“后期战斗上限”实验（2.3 末尾）显示普通战斗加搜索量有小幅稳定收益、第二幕 Boss 几乎没有，所以只做根先验预计不够，叶子价值更值得先试；战斗网络与选牌网络共用实体编码器，战斗价值可作为牌组评估信号。只能看公开信息（NoSL） |
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
| 训练原始数据 | `runs/training-review/main-a0-s{1,2}/`（未被 git 忽略，**不要提交**） |
| 第一轮分析（Codex） | `artifacts/analysis/main-a0-s1-20261110/`（`trajectory_decisions.npz` 等） |
| 第一轮分析（Claude） | `artifacts/analysis/claude-run1-20261110/`：`a1–a14.py` 统计、`boss_exp.py` 受控分叉、`bc_test.py` 模仿测试、`seaglass/` G3 快照检查 |
| 第二轮分析（同学） | `artifacts/analysis/main-a0-s2-review/`。注意其 `component_rtg` 列不是原始层数单位 |
| 第二轮分析（Claude） | `artifacts/analysis/claude-run2-20261111/`：`rest_pass.py`/`rest_an.py` 火堆、`critic_an2.py` critic、`value_test.py` 离线价值测试 |
| NoSL 修复证据 | 副本内 `validation/nosl-fix-20261110/README.md`（修复前审计 `validation/nosl-audit-20261110/` 保留未动） |
| The Future of Potions 修复证据（v8） | 副本内 `validation/future-potions-fix-20261111/README.md` |
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
- C++ 改动后需在训练机重编：`CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py`，然后确认 `sts2_sim.ENGINE_RULESET_ID` 与 `MACRO_OBS_VERSION`。**当前需要重编到 v8**（训练机上还是 v7）。
- 该机 CPU 不支持 BF16 反向（oneDNN `avx2_vnni_2`），BF16 测试有 GPU 时在 GPU 上跑，否则跳过；训练不受影响。
- 训练命令见 2.3；TensorBoard：`tensorboard --logdir runs/<run>/tensorboard --host 127.0.0.1 --port 6006`。
- Windows 原生（非 WSL）训练未适配（`tools.py` 依赖 Unix `resource`）。

---

## 7. 提交与上传

- 根 `.gitignore` 忽略 `artifacts/`：已提交文件的改动 git 能看到，**新建文件看不到**，要按清单强制添加。清单 `docs/native-port-upload-paths-20261109.txt`（1864 条，含 NoSL 修复证据文本；不含编译产物、可执行文件、`obj/`）。**不要 `git add -f artifacts/` 整目录**，不要把原生安装备份、训练输出、权重、分析目录加入源码提交。
- **`runs/` 没有被忽略**，提交前必须排除；不要用 `git add -A`。
- `44ac1bc` 已包含第三轮及之前的全部工作。此后未提交的内容（第四轮准备）：`AGENTS.md`；`docs/native-port-upload-paths-20261109.txt`（新增 44 条，共 1908 条）；`model/spire_rl/`（含新文件 `spire_rl/distill.py`）；C++ 副本中已跟踪文件的修改（`simulator/src/events.cpp`、`simulator/bindings/bindings.cpp`、`PORT_SOURCE.json`、`agent/engine_identity.py`、副本 `AGENTS.md`、`validation/build.json`）以及清单中的新证据目录 `validation/future-potions-fix-20261111/`。`artifacts/analysis/` 下的实验脚本与结果不在清单里（不提交）。
- 参考命令（由用户执行）：

  ```sh
  git add AGENTS.md docs/native-port-upload-paths-20261109.txt model/spire_rl
  git add -u artifacts/dev/cpp-native-aligned-20261031
  git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-upload-paths-20261109.txt
  git diff --cached --stat        # 确认没有 runs/、权重、归档
  git commit -m "Round 4 prep: Future of Potions fix (ruleset v8), small preset, offline distillation, per-card forks to act end, time-budgeted segments"
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
| [docs/claude-run2-diagnosis-20261111.md](docs/claude-run2-diagnosis-20261111.md) | **最新**：第二轮诊断、方向判断、第三轮实现与验收 |
| [docs/claude-run2-review.md](docs/claude-run2-review.md) | 同学（Codex）对第二轮的交接 |
| [docs/claude-run1-diagnosis-and-fix-plan-20261110.md](docs/claude-run1-diagnosis-and-fix-plan-20261110.md) | 第一轮诊断、P0 修复、受控 Boss 分叉、模仿测试（第 11 节） |
| [docs/claude-training-gaps-and-mcts-plan-20261110.md](docs/claude-training-gaps-and-mcts-plan-20261110.md) | Codex 对第一轮的分析与建议（G1–G11） |
| [docs/mcts-nosl-audit-20261110.md](docs/mcts-nosl-audit-20261110.md) | NoSL 修复前的审计 |
| `model/spire_rl/README.md` | 训练包实现、与设计的差异、命令、逐批修订记录 |
| [docs/st-dt-training-handoff-20261110.md](docs/st-dt-training-handoff-20261110.md) | 最初的 ST-DT（v3）设计；设计不等于实现 |
| [docs/local-cleanup-20261108.md](docs/local-cleanup-20261108.md) | 本地清理背景 |
