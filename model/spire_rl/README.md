# spire_rl：局外策略网络与在线 PPO 训练

铁甲 A0 单人：网络负责局外选择（选路、选牌、火堆、商店、事件），战斗交给固定的 C++ 隐藏信息 MCTS，在线 PPO 训练。最初按 `docs/st-dt-training-handoff-20261110.md`（v3）实现，之后按两轮训练的诊断逐批修改。
本文记录**实际实现了什么**、**与设计文档不同的地方**、**旧框架的问题**，以及**在训练机器上怎么跑**。项目整体状态与交接见仓库根 `AGENTS.md`。

**当前状态（2026-11-15）**

- 已跑完的训练：第一轮 `main-a0-s1`（6,001 局）、第二轮 `main-a0-s2`（10,000 局，验证约 22–23 层）、第四轮三段 `small-a0-d1` 至 `d3`（`small` 预设，7,769 局，验证 22.2 → 29.2 层后停在 28.5–29.3）。第三轮启动后因 C++ 事件异常崩溃，未继续。
- 第四轮停住的原因：旧的分叉损失没有上限，把策略推成几乎完全确定。2026-11-14 改了分叉损失、分叉复用、KL 超限退回和学习率；2026-11-15 做了缺口 1 的离线测试（否定，不接入）、关掉选牌分叉、改了 menu_loop 截断的计法、加了分叉参数检查，并补齐 KL 回滚：恢复最近一次检查合格的权重和优化器状态。见第 8 节及 [第四轮诊断](../../docs/claude-run4-diagnosis-20261114.md)。
- **这些改动都没有在 GPU 上跑过。接下来怎么跑见第 2.5 节“现在要做的”**：从 `runs/distill-small.pt` 重新开始，目录 `runs/small-b-d1`；不用重新编译，不用重新蒸馏。
- C++ 模拟器是 ruleset **v8**。v7 的检查点（第二轮权重）在 v8 上不能加载，第二轮的归档仍可读。
- 本机 CPU 72 项测试通过（含 KL 回滚回归）；此前用 tiny 预设跑通过 4 次更新的端到端训练。

第 2.2–2.4 节的命令和说明最初为第一轮（0.2B、从零训练）而写，仍然可用；第四轮按第 2.5 节操作。

## 1. 目录

| 文件 | 作用 |
| --- | --- |
| `spire_rl/config.py` | 全部超参数（一个可序列化的 `RunConfig`）；预设 `small`/`main`/`large-1b`/`large-0.7b`/`tiny` |
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
| `tests/` | 文档第 9 节要求的验证 + 2026-11-10/11/12 各批回归（53 项） |
| `spire_rl/pretrain.py` | 从归档离线预训练 critic（价值先验） |
| `spire_rl/distill.py` | 从归档把已有策略离线蒸馏进另一个预设（同时训练 critic），输出普通检查点 |

C++ 侧新增（在 `artifacts/dev/cpp-native-aligned-20261031/simulator/`）：
`include/sts2/macro_obs.h`、`src/macro_obs.cpp`，以及 `bindings.cpp` 里的 `RunContext.macro_observation()`、`RunContext.play_combat_mcts()`、`sts2_sim.macro_vocab()`。没有改任何游戏规则。

## 2. 在训练机器上运行

### 2.1 准备

1. 当前源码分支为 `v111_SF1`，第三轮代码已提交为 `44ac1bc`；第四轮准备的改动提交前在工作区。`artifacts/` 的新增源码需按上传清单强制添加，不能强制添加整目录。训练输出 `runs/` 当前未被根 `.gitignore` 忽略，提交前单独检查；见根 `AGENTS.md`。
2. 在 WSL2 激活已有 `conda activate slay`，用**训练时要用的那个 Python** 构建模拟器（扩展模块与平台、Python 版本绑定）。以下从项目根目录执行：
   ```sh
   CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
   ```
   若从 Mac 拷贝了整个目录，先移走 `validation/obj` 的旧平台缓存。Windows 原生训练尚未适配：除 C++ 构建外，Python 的 `tools.py` 还依赖 Unix `resource`；当前使用 WSL2/Linux。
   模块不在默认位置时设 `STS2_SIM_DIR=<含 sts2_sim*.so 的目录>`。
3. 在项目根目录安装：`python -m pip install -e "model/spire_rl[tensorboard,test]"`。已有兼容依赖可复用；项目的 `torch>=2.1` 最低声明本身不保证 5090 支持，需确认实际安装的 CUDA 构建能运行 GPU/BF16。

### 2.2 命令（统一在项目根目录下）

下列命令是第一轮（`main`，从零训练）的写法，保留作参考；**第四轮按第 2.5 节**。所有 `runs/...` 均相对于执行命令时的工作目录。

```sh
python -m pytest -q model/spire_rl/tests              # 53 项测试，CPU 即可
python -m spire_rl params --preset large-1b           # 参数量与 16 字节/参数 估算
python -m spire_rl check --preset main --device cuda --out check-main.json
python -m spire_rl check --preset large-1b --device cuda --out check-1b.json
python -m spire_rl smoke --run-dir runs/smoke --device cpu  # 极小端到端闭环

# M3 短测：只跑 10 个采样-更新周期，看仪表盘的每局秒数与 ETA（短测目录用完可删）
python -m spire_rl train --preset main --device cuda --run-dir runs/main-probe --stop-after-updates 10
# 第一轮的启动配置；新实验需使用新目录
python -u -m spire_rl train --preset main --device cuda --num-envs 8 --microbatch 4 --episodes 10000 --seed 1 --run-dir runs/main-a0-s1

# 冻结后在 1000 个测试种子上评估，两档成对比较
python -m spire_rl eval --checkpoint runs/main-a0-s1/best.pt --split test --device cuda --out test-main.json
# 大档实验尚未启动；以下只在对应权重实际存在后使用
python -m spire_rl eval --checkpoint runs/1b-s1/best.pt --split test --device cuda --out test-1b.json
python -m spire_rl compare test-main.json test-1b.json
```

`eval` 默认和训练一样按概率采样；加 `--greedy` 则每步取概率最高的动作。`compare` 输出同种子配对的通关差（McNemar）和**层数差**（`floor_diff_a_minus_b`、它的标准误、各自到第二幕的比例和截断数）。

常用参数：`--num-envs`（并行环境数，默认 8，按 CPU 核数调）、`--microbatch`（只影响显存）、`--seed`（训练随机性：初始化、采样、搜索种子；**不决定游戏种子**，游戏种子由 `--train-seed-base` 或检查点接续决定）、`--init-checkpoint`（载入权重继续，优化器重建，必须用新 run 目录）、`--max-hours`、`--alpha`（整轮固定一个进度权重）、`--fork-rest/--fork-map/--fork-card/--fork-seeds/--fork-coef/--fork-replay`（成对分叉）、`--lr`。完整列表：`python -m spire_rl train --help`。

没有 `--ascension`，也不能精确断点续跑（检查点只存权重）；`docs/configs/` 下的配置 JSON 是导出记录，CLI 不会读取。默认按局数切换奖励档位，门槛不满足时停留在当前档继续训练（`--gate-policy hold`）。

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

训练时在另一个 WSL 终端中（把 `<run>` 换成当前的 run 目录名）：

```sh
conda activate slay
tensorboard --logdir /mnt/c/Users/yebohou/SlayTheModel/runs/<run>/tensorboard --host 127.0.0.1 --port 6006
```

在远程 Windows 浏览器打开 `http://localhost:6006`。强度优先看 `val/win_rate`，早期辅以 `val/reach_act2`、`val/reach_act3`、`val/floor_mean`；训练奖励会随 α 改变，不能单凭奖励或 loss 判断强弱。初始 200 局验证完成前可能暂无曲线；有 `[val @0]` 后仍无数据应检查日志目录。`check` 不生成训练曲线。

### 2.4 输出文件与磁盘

| 文件 | 内容 | `small` | 0.2B | 1B |
| --- | --- | ---: | ---: | ---: |
| `best.pt` | 验证成绩最好的权重（含 critic），只在刷新最佳时覆盖 | 约 0.09 GB | 0.9 GB | 3.7 GB |
| `last.pt` | 最近一次验证后 / 训练结束时的权重（含 critic），每次覆盖 | 约 0.09 GB | 0.9 GB | 3.7 GB |
| `archive/rollout_*.npz` | 轨迹归档，每轮一个压缩文件 | 第二轮 1 万局共 0.25 GB；带分叉记录后略大 | 同左 | 同左 |

每个 run 目录只有这两个模型文件，不会随训练变多。训练结束后，学习曲线全部在 `metrics.jsonl`/`metrics.csv`/`eval.csv`/`dashboard.html` 里，不依赖任何模型文件。启动时检查检查点所需磁盘（不含归档），不够就拒绝；同一目录已有训练记录时拒绝启动，避免混写。归档可以在 `RunConfig.archive_trajectories` 关掉（会失去离线分析和蒸馏的数据）。

`best.pt` 不是最后模型：验证胜率更高时更新，胜率相同时比平均层数（2026-11-11 起）。`last.pt` 在每次验证后和训练结束时写入（正常结束、`--max-hours` 到点、报错退出、按一次 Ctrl+C）；直接关窗口或 `kill` 时不会保存。可用 `train --init-checkpoint` 载入权重、新建优化器继续训练。

### 2.5 小网络、按工作日分段（第四轮 2026-11-11 起；11-14、11-15 改动后从蒸馏结果重新开始）

#### 现在要做的（2026-11-15 起：第四轮跑完三段后的重新开始）

第四轮三段（`small-a0-d1` 至 `d3`）的诊断见 [docs/claude-run4-diagnosis-20261114.md](../../docs/claude-run4-diagnosis-20261114.md)。那三段的检查点（包括 d1 的 `best.pt`）都已经被旧的分叉损失推到几乎完全确定，**不要接着它们训练**，从蒸馏结果 `runs/distill-small.pt` 重新开始。**不用重新编译 C++，不用重新蒸馏。**

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel

# 0) 确认蒸馏结果还在（没有就按下面“从头做一遍”重新蒸馏）
ls -la runs/distill-small.pt

# 1) 同步代码后跑一次测试，确认文件没漏（应显示 72 passed）
#    要同步的文件：model/spire_rl/spire_rl/ 下的 config.py ppo.py rollout.py train.py __main__.py，
#    以及 model/spire_rl/tests/test_spire_rl.py
python -m pytest -q model/spire_rl/tests

# 2) 第一天。--max-hours 填“当天能挂的小时数减去约 20 分钟”。目录名换成 small-b-*，旧的 small-a0-* 不用动
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-b-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0 --fork-seeds 2 --fork-coef 2

# 3) 第二天起只改两处（第三天是 d3 接 d2/last.pt，依此类推）
#    --run-dir runs/small-b-d2 --init-checkpoint runs/small-b-d1/last.pt
```

启动后终端开头应出现这几行，对不上就先停下来：

- `training game seeds continue at 2000000`（第一段；之后每段接着上一段的数）。
- `[val @0] win ... floor 22.x act2 0.4x`：蒸馏结果的成绩，和第四轮开头一样。第二段起的 `[val @0]` 是上一段 `last.pt` 的成绩。
- 应收集到 72 项测试；数量不符先核对文件是否同步全，有失败则看具体报错。`--run-dir` 里已经有一次训练的记录（`metrics.jsonl`）时会直接报错，换一个新目录名。

和第四轮相比，指令只改了一处：`--fork-card 0`（关掉选牌分叉，原因见第 8 节 2026-11-15 条）。其余变化在代码默认值里：学习率 3e-5（会随 KL 拦停自动下调）、分叉损失有上限、每次更新复用最近 4 轮的分叉、KL 超限时退回、在网格里反复取消被截断的局按“到此结束”计。训练种子仍从 2,000,000 起，和第四轮 d1 是同一批游戏种子，曲线可以直接对照。

启动后看（都在 `metrics.jsonl` 里）：

- `[val @0]` 应在 22 层左右、接近一半到第二幕（与第四轮开头相同）。
- `target_passes`：多数更新应在 1 以上（第四轮是 0.4）。长期低于 1 时学习率会自己降，看 `lr`。
- `sampled_kl_final`：最终保留策略在固定样本上的 KL 应有限且不超过 0.015（默认阈值）；`kl_rollback_steps` 表示本次撤销了多少步，可能多于 1。`optimizer_steps`、`target_passes`、`fork_targets_seen` 只计保留的步骤；损失和梯度统计仍含被撤销的尝试。
- `fork_option_logp_min`：应保持在约 −12 以上（第四轮从 −19 一路到 −5,000）。这是“策略有没有被推死”的直接读数。
- `rest_heal_rate_full_hp` 不应钉在 1.000；`rest_heal_rate_hp_below_50` 应保持较高。
- `fork_rest_taken_was_best`、`fork_map_taken_was_best` 上升（结合 `fork_decisive` 的数量看）。`fork_card` 应为 0。
- 速度：`seconds_per_episode` 应明显低于第四轮的 4.4–4.7 秒（选牌分叉约占全部模拟器战斗的 40%）。
- `menu_loops`：第四轮 d2、d3 各约 1% 的局；现在这种局按“到此结束”计，应逐渐减少。
- 成绩：第四轮开头约 300 局就到了 26–28 层（靠把策略变尖）。这次学习率低，会慢一些；到 2,000–3,000 局时应回到 28–29 层，之后看能否超过 29.3。

结束与中断：

- 到点自己停，保存 `<run 目录>/last.pt`。
- 提前停：按**一次** Ctrl+C，等它打印 `saved to .../last.pt` 再关窗口。直接关窗口或 `kill` 不会保存。
- 中途报错：退出前同样会保存 `last.pt` 并打印 `saved to ...`。把报错内容带回来；修好后从那个 `last.pt` 用一个新的 `--run-dir` 接着跑。

每天带回：当天 run 目录下的 `metrics.jsonl`、`eval.jsonl` 和终端输出；归档（`archive/`）能带就带，这次的诊断主要靠它。

#### 从头做一遍（换机器、C++ 又改了、或需要重新蒸馏时）

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
# C++ 改了（ruleset v8），必须重新编译，然后确认版本
CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"     # native-41cef1ea-port-v8
python -m pytest -q model/spire_rl/tests                                    # 72 项

# 1) 一次性：把第二轮末尾的策略蒸馏进 small 预设（只读归档，不需要第二轮的权重）
python -m spire_rl distill --archive runs/main-a0-s2/archive --out runs/distill-small.pt --preset small --device cuda

# 2) 每个工作日一段。--max-hours 设为“能挂的小时数减去约 20 分钟”
python -u -m spire_rl train --device cuda --num-envs 8 --seed 4 --episodes 100000 --max-hours 7 \
  --run-dir runs/small-b-d1 --init-checkpoint runs/distill-small.pt \
  --alpha 0.5 --fork-rest 0.3 --fork-map 0.05 --fork-card 0 --fork-seeds 2 --fork-coef 2
# 第二天起只改两处：--run-dir runs/small-b-d2 --init-checkpoint runs/small-b-d1/last.pt
```

- `distill` 的输出里看留出数据的 `kl_estimate`（学生与第二轮策略的差距，越小越好）和 `top1`；`critic_ev` 是 critic 对实际后续层数/进幕的留出解释方差。
- 第一段启动后的 `[val @0]` 就是蒸馏结果的成绩，对照第二轮末尾（约 22 层、约一半到第二幕）。明显偏低说明蒸馏损失大，先不要继续训练。
- 用 `--init-checkpoint` 时网络形状和每档默认超参取自检查点，`--preset` 被忽略；训练种子从检查点记录的 `next_train_seed` 接着用（蒸馏检查点从 2,000,000 起），不会重复第一、二轮的 1,000,000–1,009,999。
- `--max-hours` 到点后不再开始新一轮采样，保存 `last.pt` 后正常退出；实际会多出当前这一轮采样和更新的时间。`--episodes` 设大，让时间而不是局数决定何时停。
- 每段的 run 目录约占：两个检查点共约 0.2 GB，归档每 1 万局约 0.3 GB。不需要的旧 run（包括崩溃的 `runs/main-a0-s3`，约 1.8 GB）可以手动删除。
- **中途要停**：按一次 Ctrl+C，等它打印 `saved to .../last.pt` 再关窗口（要等正在跑的几场战斗结束，通常几秒到几十秒）。报错退出时也会同样保存。直接关窗口或 `kill` 不会保存，只剩上次验证时的 `last.pt`。
- 每天结束后最好带回该 run 目录下的 `metrics.jsonl`、`eval.jsonl` 和终端输出（都是小文本文件），判断要用的数字都在里面。
- `small` 预设在 GPU 上用 FP32（`--bf16` 可改回 BF16）。改 FP32 后的速度没有实测：对照第一次启动的 `s/ep`（第 7 次更新时 4.66 秒/局），明显变慢再考虑 `--bf16`。`metrics.jsonl` 的 `recompute_max_abs` 在 FP32 下应在 1e-4 以下。
- 分叉的开销看 `metrics.jsonl` 的 `fork_branch_combats`（分支里的战斗数）与 `combats_mean × rollout_episodes`（主线战斗数）之比。第四轮带选牌分叉时约 2.3 倍；关掉选牌分叉后按第四轮的构成估计约 1 倍（未实测）。太慢就调低 `--fork-rest`。

#### 取最大评估（可选，训练之外单独跑）

```sh
# 同一个检查点、同一批 200 个验证种子：取最大 vs 按概率采样。单独跑时每次几分钟；不要和训练同时跑（抢 CPU）
python -m spire_rl eval --checkpoint runs/small-a0-d1/last.pt --device cuda --greedy --out runs/eval-d1-greedy.json
python -m spire_rl eval --checkpoint runs/small-a0-d1/last.pt --device cuda          --out runs/eval-d1-sampled.json
python -m spire_rl compare runs/eval-d1-greedy.json runs/eval-d1-sampled.json
```

- 看 `compare` 输出的 `floor_diff_a_minus_b`（取最大减采样的平均层数差）和 `floor_diff_standard_error`：差超过两倍标准误才算有差别。`a_reach_act2 / b_reach_act2` 是各自到第二幕的比例。通关数现在只有 0–1 个，`mcnemar_exact_p` 暂时没有参考价值。
- 先看 `a_truncations`（取最大那一侧被截断的局数）。取最大的策略没有随机性，可能在某个菜单里反复点同一个动作，这种局会以 `menu_loop` 或 `macro step cap` 截断，层数被低估。截断多于几局时，层数差不能直接用，把 `eval` 输出里的 `truncation_reasons` 带回来。
- 用途：区分“策略本身的水平”和“按概率采样时乱点造成的损失”（第二轮末尾奖励界面有 11.9% 的次数没拿完就走）。取最大明显更高，说明损失主要来自采样；差不多，说明问题在策略本身。它只是测量，不改变训练。

### 2.6 统一网络（2026-11-16 起，[设计文档](../../docs/claude-unified-net-design-20261116.md)）

和上面的 PPO 训练是两条独立的线，输出都在 `runs/unified/`，不碰 `small-b-*`。**C++ 加了接口，必须先重新编译**（ruleset 不变，仍是 v8，旧检查点照常可用）。

**要带到训练机上的东西**
- 代码：`model/spire_rl/` 整个目录（含 `unified_gpu.sh` 和 `tests/`），以及 C++ 副本 `artifacts/dev/cpp-native-aligned-20261031/simulator/` 下的 `bindings/bindings.cpp`、`include/sts2/search.h`、`src/mcts.cpp`、`include/sts2/combat_obs.h`、`src/combat_obs.cpp`、`include/sts2/net_search.h`、`src/net_search.cpp`。
- 两个数据文件（不进 git），放到训练机的 `runs/unified/`：`value_pretrain.pt`（本机在归档上预训练的价值头，10 MB）和 `evalset.pkl.gz`（188 场固定战斗，1 MB）。本机打包在 `artifacts/analysis/claude-unified-20261116/to_gpu/`。
- 训练机上应已有：`runs/small-b-d1/last.pt`（局外选择用）和 `runs/small-b-d1/archive`、`runs/small-a0-d{1,2,3}/archive`（训练时保持局外价值）。缺哪个归档就用 `MACRO_RUNS=small-b-d1` 只列有的。

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID, sim.NetSearch)"     # native-41cef1ea-port-v8
python -m pytest -q model/spire_rl/tests                                                # 全部应通过
nvidia-smi                                                                              # 确认没有别的训练在占 GPU
bash model/spire_rl/unified_gpu.sh 2>&1 | tee -a runs/unified/all.log
```

`unified_gpu.sh` 按顺序做三步，每一步做完就跳过，所以**中途停了（Ctrl+C 或关窗口）再跑同一条命令就接着做**：
1. **教师数据**：MCTS 按 256/512/1024 打完整局（局外选择由 `small-b-d1` 做），默认 2,000 局，并行数默认等于 CPU 线程数（`ENVS=16` 可改）。主要吃 CPU。进度在 `runs/unified/teacher/progress.json`。
2. **训练第 0 代**（GPU）：从 `value_pretrain.pt` 出发，模仿教师的出牌、学每幕结果，4 遍。输出 `runs/unified/gen0.pt`。
3. **成对评估**：188 场上比 MCTS 两档、网络单独出牌、网络 + 搜索的两种数值尺度（`norm256`、`rate256`，预算 256/512/1024）。结果 `runs/unified/eval/summary_gen0.json` 和 `runs/unified/eval_gen0.log`。

`GENS=1`（或更大）会在第 3 步后接着做自我对弈：上一代网络 + 搜索打完整局（`SP_MODE=norm` 或 `rate`，看第 3 步谁好），新一代在教师数据 + 自我对弈数据上从上一代接着训练，然后再评估。第一次先不开，等第 3 步的结果带回来再定。`MAX_HOURS=6` 可以让长步骤到点停下（停下的步骤以退出码 3 结束，脚本不会往下走；再跑同一条命令就接着做）。

带回来：`runs/unified/*.log`、`runs/unified/eval/summary_gen*.json`、`gen0.pt` 和 `gen0.pt.json`（10 MB）。数据目录 `teacher/` 能带就带（2,000 局约 50 MB）。

可单独用的命令（都在 `model/spire_rl` 下，`--device cuda`）：`python -m spire_rl.unified_run gen|eval ...`、`python -m spire_rl.unified_train ...`、`python -m spire_rl.unified_pretrain ...`（可用 `--init` 在 GPU 上接着预训练），参数见各文件开头。数据解码在后台进程里做（`--workers`，Linux 默认 CPU 数减 2，最多 8）；WSL 里如果报共享内存不足（`bus error` / `shm`），加 `--workers 0`。

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
| `small` | 256 / 2 ISAB / 8 头 / 16 诱导点 | 512 × 4 层，8 头，**8 步** | 19,619,592（critic `CRITIC_LITE` 1,922,312） | 32 | 3e-5（第四轮用 1e-4，每次更新约 7 步就被 KL 拦停） |
| `main` | 512 / 2 ISAB / 8 头 / 32 诱导点 | 1024 × 14 层，16 头 | 201,271,813 | 4 | 1e-4 |
| `large-1b` | 同上 | 1536 × 32 层，24 头 | 932,618,757 | 1 | 3e-5 |
| `large-0.7b` | 同上 | 1536 × 24 层，24 头 | 705,966,597 | 1 | 3e-5 |

参数量统计全部唯一参数（嵌入、ST、历史主干、动作/价值/辅助头）。`main` 与两个大档是 2026-11-10 之前的实测值（`small` 一行是当前代码的实测值）；分组头与三分量价值头约增加 0.8M（`main` 仍在 0.19–0.21B 测试范围内）。

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
- 截断（宏观步数上限 600，或模拟器截断）用末状态 V 自举一次，trace 为 0。同一网格连续 64 个决策的 `menu_loop` 截断从 2026-11-15 起不自举，按“到此结束”计（`RunConfig.menu_loop_bootstrap=False`）。网格保护不代选、不代确认、不删选项。第一轮的上限是 3000，Sea Glass 循环三次各占当批 57–64% 样本。

### 4.4 训练流程

- **KL 提前停止**：当前小批在本步更新前检查（默认限值 0.04）；固定 512 个样本每 8 步及结束时检查（默认限值 0.015）。超限或非有限时停止；开启 `kl_rollback` 时恢复最近一次固定样本检查合格的权重与优化器状态，并按保留的数据遍数调整学习率（`lr_adapt_*`）。起点也验证，最终实际测量保留策略；固定样本上的限制不等于全部状态的精确 KL 保证。见第 8 节。
- **门槛不满足的默认行为是停下**（`gate_policy="stop"`，文档"停下诊断"）；`hold` 是可选项。
- **只保存最佳权重（用户 2026-11-09 要求）**：原 v3 的最新恢复点 + 最佳 + 里程碑要求已被简化。`best.pt` 保存权重、配置、指纹和部分进度，不含优化器/RNG；**不能断点续跑，也没有权重继续训练入口**，重新执行 `train` 会随机初始化。各验证点胜率持续写入 `eval.jsonl`，正常结束导出 `eval.csv`。α=0 档持续到预算结束，预算在启动时用 `--episodes` 定好。
- **身份校验范围**：加载时比较检查点格式、ruleset、宏观观察版本/维度/词表、场景阶段数与动作类型数。run 的 `config.json` 记录二进制 SHA，但权重加载没有强制比较源码/二进制 SHA，也未重新验证保存的配置指纹；不能将此等同于原 v3 的完整绑定要求或旧 ArmG 的身份校验。
- **采样随机流按局独立**：每局用 (采样种子, 局号) 派生自己的随机流，结果不依赖线程完成顺序。验证用固定采样种子，同一模型两次验证结果一致（有测试）。
- **轨迹归档**：文档第 8 节要求保存原始公开实体、候选、动作、旧概率/价值、奖励分项、终止分类、行为版本；每轮写一个 `archive/rollout_*.npz`，窗口按索引重建，不重复存前缀。归档从不回灌 PPO。
- 激活重计算只在 CUDA 上启用；BF16 只在 CUDA 上启用，CPU 一律 FP32。

### 4.5 文档中其他地方的说明

- 文档链接的旧奖励 JSON（`docs/configs/st-dt-reward-review-20261110.json`）在仓库里不存在。新配置由代码导出：`docs/configs/spire-rl-{main,large-1b,large-0.7b}.json`（`python -m spire_rl config --preset ...` 可重新生成）。
- 没有实现课程学习、长度分桶、KV cache。模拟器和环境接口有 A0–A10 基础，实体输入含进阶，但全部预设为 A0，没有 `--ascension`，也没有新框架 A10 专项训练验收。11 月 10 日讨论的逐级升阶、低难度复习、与表现联动的奖励衰减均未实施；讨论数值不属于当前配置。

### 4.6 训练缺口与后续研究（除缺口 1 的离线测试外尚未实现）

四个缺口：对具体敌人与候选牌的价值评估、幕内与跨幕的信用分配、后期样本覆盖、选牌与战斗能力的衔接。论文思路与实验备忘见[训练缺口文档第 2.1 节](../../docs/claude-training-gaps-and-mcts-plan-20261110.md#21-四个训练缺口论文思路与后续实验)，包括 UVFA／TDM、RUDDER、FeUdal Networks、Expert Iteration、纯策略 STS2，以及 MuZero／DreamerV3 的适用边界。

候选顺序为分析本轮带回的数据 → 固定局外策略，对照当前 MCTS、纯战斗网络及同网络＋小预算搜索 → 经整局验证后，让抓牌分叉与局外训练适应同一战斗器。保留 PPO 和网络直接出牌的目标；共享编码器、回报重分配及多跨度价值均需单独验证，起点课程仍暂不采用。

2026-11-15 的进展：

- 第一个缺口里“用分叉结果训练按选项打分的头”已在第四轮数据上离线测过，结论是否定的，没有接入（第 8 节 2026-11-15 条）。
- 讨论过、没有实现也没有验证的替代做法：选牌时把每张候选牌加进牌组，直接去打一批战斗（本幕 Boss、精英、普通怪，可加后面几幕的敌人），用掉血和死亡率作标签监督训练选牌的打分头。先要确认模拟器能直接开指定的战斗，再在本机离线检验标签是否可靠。用户还没有决定做。
- Zero-Search STS2 预印本（arXiv 2611.12088v1）读了全文：一个 6.6M 的无历史实体 Transformer 同时打战斗和做局外选择，不搜索，普通 PPO，铁甲训练了 16.6 亿个决策。它强在训练量（约 6 万局/小时，我们约 800 局/小时）。要点和可参考之处记在根 `AGENTS.md` 第 2.4 节。

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
| 2026-11-15（共 63 项） | 新增：`menu_loop` 截断在两种设置下的回报和分叉分支处理；分叉种子数、选项数超出范围时报错。tiny 预设端到端训练 4 次更新（火堆 + 地图分叉、无选牌分叉）：分叉、分叉复用、学习率调整、概率重算检查（约 1e-7）都正常。用第四轮 d1 的检查点核对过推荐命令解析出的配置：学习率 3e-5、选牌分叉概率 0、FP32、`menu_loop_bootstrap=False` |
| 2026-11-15 KL 回滚补齐（共 72 项） | 本机 CPU 完整测试 72 passed；新增默认 8 步检查、末尾不足周期、小批拦停、Adam/AMSGrad 状态与恢复后下一步一致、非有限值及不合格起点回归。未在 GPU 上验证 |
| 5090 上 `main` 初始评估（用户 2026-11-10 反馈） | `[val @0]`：0/200 通关、平均 11.0 层、约 1% 到第二幕；只有训练前 GPU 推理评估证据，尚未收到更新日志、显存/吞吐报告和学习后成绩 |

## 7. 训练机器上要先确认的事

1. `check --preset large-1b`：看 `fits_with_3gib_headroom`。不够先试 `--microbatch 1`（默认已是 1），再不行用 `large-0.7b`。
2. 短训练 10 个周期后看仪表盘的"每局秒数"与 ETA（已含更新、验证、保存）。文档的一天目标需要 ≤ 8.64 秒/局。10 个周期里只有开头一次验证，之后每 2000 局还有一次 200 局验证，正式训练的平均值会略高。本机（4 核 Mac CPU、tiny 模型）随机策略约 2 秒/局，但后期局更长、Boss 搜索更贵，必须实测。环境数应接近 CPU 核数。
3. 若 KL 每次都在第一轮就提前停止，或熵很快塌缩，记录下来再调，不要只增加更新次数（文档 5.3）。

### 7.1 每次训练结果拉回后的固定检查（2026-11-16 起）

`small-b-d1` 的诊断发现：训练过程一切正常，但局外策略完全不看血量。这个问题只看训练曲线发现不了，所以每次结果拉回后都要单独测（[诊断文档](../../docs/claude-runb-diagnosis-20261116.md) 第 3 节；脚本在 `artifacts/analysis/claude-runb-20261115/`）：

1. **反事实敏感度**（`cf_probe.py`、`cf_critic.py`）：同一个决策，只把血量改成 20% 或 100%，其余不变，比较策略的选择概率和价值头的输出。火堆决策的回血概率在低血时必须明显变高；价值头的输出也必须随血量变。`small-b-d1` 的结果：概率平均只变 0.03%，回血概率 0.828 → 0.828，这就算不合格。
2. **线性探针**（`rest_probe.py` + `linprobe.py`）：从决策向量线性读出血量比例，按文件留出算 R²。`small-b-d1` 只有 0.10–0.12，说明血量在到达决策头之前就丢了。
3. **对照分叉标签**（`rest.py`）：各血量档的回血率与火堆分叉给出的“该不该回血”是否同方向。

以后的价值头（包括设计中的“本幕 Boss 价值”）照此测：只改血量（以及药水数），看预测是否单调变化、变化量是否和分叉或成对实验的结论量级相当。战斗网络把玩家数值直接送进两个头，同样要测。

不看血量的原因目前是**较强怀疑，没有逐项分开验证**：(a) 整局回报里，血量带来的那点好处被运气淹没，梯度只推整体偏好；(b) 结构上血量只是约 80 个实体中的一行，经过汇聚和历史 Transformer 后到决策头时已基本读不出（探针 R² 0.12）。两者互相加强。要分开，可以做两件事：把 `fit_rest.py` 跑满 4 遍；再做一个血量直接送进决策头的对照。

## 8. 修订记录

**2026-11-16 深夜（Claude：统一网络第 3–5 步的代码与训练机适配，用户要求当天带到训练机）**

- **价值头预训练**（`unified_pretrain.py`，本机 CPU，用户要求跑完 1 遍就停）：4 段归档（small-b-d1、small-a0-d1–d3）约 1.9 万局，每个决策抽 30%，2,660 步。结果在 `artifacts/analysis/claude-unified-20261116/value_pretrain.pt(.json)`。按种子留出：
  - q₀ 的 AUC：第一幕 Boss 前一层 0.77、2–4 层 0.76、幕开头 0.65；第二幕 0.71 / 0.72 / 0.67；第三幕 0.86 / 0.81 / 0.81（样本少）。比离线小 MLP（0.86 / 0.83）低，只训了一遍。
  - **血量起作用**：血量 +10% 使预测的通过率高 2–4.5 个百分点（第一幕 Boss 前 +2.1，第二幕 +4.5），−10% 低 2.8–5.2 个百分点，与离线测试（+4.2）同一量级。对照：第 0 遍随机初始化时约为 0。
- **教师数据**（本机）：300 局，种子从 7,100,000 起，MCTS 256/512/1024，50 个 part 文件（10 MB），平均 19 秒一局，峰值内存 0.58 GB。
- **C++ 本机重编**：`normalize_q`、`eval_terminal_wins` 两个选项进入构建（ruleset 不变）。扩展 SHA-256 `c6697ca5…`（`validation/build.json`）。编译时先链接到临时文件再改名替换，正在运行的进程不受影响。默认参数下与旧构建逐项一致（`test_net_search_defaults_reproduce_the_previous_build`）。
- **GPU 适配**：
  - `unified_play.py` 重写成 `CombatBatch`：所有在打的战斗每轮各推进一次模拟，叶子攒成一批送网络（GPU 或 CPU）；`play_batch`（固定快照评估）和 `CombatServer`（自我对弈：各局在自己的线程里进战斗后交给一个服务线程，所有战斗共享一批网络调用）都用它。记录的根访问次数按合法动作顺序对齐。
  - `unified_pretrain.py`、`unified_train.py`：`--device`、`--workers`（数据解码在 DataLoader 后台进程里做）、`--max-hours`、`--init`；`unified_train` 改为按 part 文件流式读取，数据不必全部放进内存。CUDA 上开 TF32。到点停下以退出码 3 结束。归档路径两台机器都能找到（`runs/training-review/<run>` 或 `runs/<run>`）。
  - `unified_run.py`（新）：`gen`（教师 MCTS 或网络 + 搜索自我对弈，整局，每 8 局写一个 part，`progress.json` 记录进度，`--episodes` 是目录的总目标，同一命令可续跑）、`eval`（188 场成对评估，MCTS 结果跨代共用）。
  - `unified_gpu.sh`（新）：训练机一条命令跑完 教师数据 → 第 0 代训练 → 评估（可选自我对弈若干代），每步做完就跳过。见第 2.6 节。
  - `rollout.Collector.collect` 加了 `on_episode` 回调（默认不用，PPO 训练不受影响）。
- **修了一个错**：`unified_obs.combat_obs` 遇到“已经打赢”的搜索叶子（没有候选）会报错；之前的冒烟测试没有走到。
- 测试：`tests/test_unified_play.py`（6 项：批量与逐场一致、两种数值尺度下记录的访问次数与动作对齐并能打包读回、训练数据按种子留出不重不漏、教师和自我对弈两种 `gen` 写出数据并能续跑）；`test_unified.py` 的“赢局交给调用方”测试改为从 MCTS 打赢的局面前两步开始（原来的局面随机搜索打不赢，测不到），并更正了期望（根节点展开占一次模拟，48 次模拟的根访问合计 47，旧构建也是如此）。本机完整测试 **98 passed**。
- 本机用小规模参数把 `unified_gpu.sh` 从头跑通一遍（CPU，2 局教师、1 代自我对弈、4 场评估），再跑一次确认各步都跳过。**CUDA 没有实测**：本机没有可用 GPU，设备相关的代码是逐处检查的。
- 局外选择在这一步仍由 `small-b-d1` 的局外策略做（只为了产生真实的牌组和遭遇），统一网络的局外策略（PPO）是后面的步骤。

**2026-11-16 晚（Claude：统一网络第 1、2 步，[设计文档](../../docs/claude-unified-net-design-20261116.md)）**

- `spire_rl/unified_obs.py`：局内局外同一套实体观察，在 Python 里由现有两个 C++ 观察拼成，**不改 C++、不改规则**。
  - 局外：原样使用 `macro_observation()`，所以训练归档里存的宏观观察可以直接转换。
  - 战斗中：`macro_observation()` 的局外部分（全局行、牌组、遗物、地图及连边、Boss 等；局外的药水实体去掉，战斗有自己的），后面接 `entity_observation()`。
  - 实体类型：局外 0–12、战斗 13–25；数值行补齐到 96 维。候选类型：局外动作 0–31、战斗动作 32–36。
  - 战斗中，局外部分在整场战斗里保持不变：全局实体里随战斗变化的列（血量比例、血量、最大血量、药水数）清零；直接送进输出头的全局行用战斗中玩家的当前值补上。
- `spire_rl/unified_net.py`：约 2.5M 参数。
  - 两部分：局外上下文编码器（地图连边上做一次消息传递，再接 3 层 Transformer），战斗部分 2 层解码器（战斗实体之间互相注意，并注意局外上下文；外加一个摘要位）。没有位置编码。
  - 全局行和战斗玩家行直接送进输出头。
  - 输出头：候选打分；q（本幕、下一幕、再下一幕的通过概率，不打折）；战斗辅助输出。
  - `combine()` 按 r = (1, 1, 3)、w = (0.2, 0.5) 合成决策价值 U。
  - 局外上下文在一场战斗里只算一次，供所有搜索叶子复用（`encode_context` + `forward(ctx=...)`，测试确认与完整计算一致）。本机单核每个叶子的耗时约是纯战斗网络的 1.4–1.7 倍；不复用时是 5–6 倍。
- `tests/test_unified.py`（9 项），覆盖：
  - 局外与宏观观察一致；
  - 战斗中的布局、补上的全局行，以及候选与合法动作对应；
  - 重抽隐藏状态后观察不变；
  - 搜索叶子与直接观察一致；
  - 实体打乱后输出不变（局内局外都测）；
  - 批量与逐个一致，全局行的梯度能直达输出头；
  - `combine` 的数值；
  - 复用上下文与完整计算一致。
- 本机完整测试 89 passed。
- 策略头第一版是所有候选一起做 softmax，没有沿用局外网络“先选动作组再选目标”的分解，有问题再加。

**2026-11-16（Claude：战斗网络实验的基础设施；C++ 只新增接口，规则与 ruleset 不变）**

- 背景：修复后一轮 `small-b-d1` 成绩 25.6 层，诊断发现局外策略不看血量（[诊断文档](../../docs/claude-runb-diagnosis-20261116.md)）。用户决定换结构，先试“战斗网络 + 少量搜索”能否胜过现在的随机走子 MCTS，预算按用户给的普通 256 / 精英 512 / Boss 1024。
- C++（`artifacts/dev/cpp-native-aligned-20261031/simulator/`，新增文件 `include/sts2/combat_obs.h`、`src/combat_obs.cpp`、`include/sts2/net_search.h`、`src/net_search.cpp`）：
  - **按实体组织的公开战斗观察** `BattleContext.entity_observation()`（`COMBAT_OBS_VERSION=1`，每个实体 96 维）：玩家、遭遇、双方能力、手牌、抽牌堆（已知顶部带位置，其余按 `card_canonical_less` 排序）、弃牌堆、消耗堆、待选牌、正在打出的牌、怪物、药水、遗物；候选与 `legal_actions()` 顺序一致，指向牌/药水/待选牌实体和目标怪物。是 `public_combat_observation` 的子集，不含 UID 与隐藏顺序；只覆盖铁甲（其他角色的球、Osty、星不编码）。
  - **可续跑的 PUCT 搜索** `NetSearch`：每次模拟在根重抽隐藏状态，节点按公开观察和可见动作特征区分（与现有 MCTS 相同）；先验和叶子估值由调用方提供，`net_search_advance` / `net_search_provide` 一次处理多场战斗、批量送网络。没有随机走子；终局值 `combat_value()` = 输 0、赢 0.4 + 0.6 ×（血量 + 4 × 药水）/ 最大血量。只有一个合法动作的非根节点直接展开、不调用网络。多线程推进时每个线程 64 MiB 栈（`BattleContext` 有几百 KB）。
  - `MctsResult.rootVisits` 与 `BattleContext.mcts_root()`：现有 MCTS 的根访问次数（只导出，不影响选择；测试确认与 `mcts()` 选同一动作）。`RunContext.combat_is_elite`、`BattleContext.potion_count` / `combat_value()`。
- Python：`spire_rl/combat_net.py`（战斗网络：实体 Transformer 3 层、宽 128，约 1.4M 参数；玩家数值行直接进两个头）；`spire_rl/combat_play.py`（随机走子 MCTS 带记录、批量网络搜索、只用网络三种打法，从 `RunContext.snapshot()` 成对评估）；`env.py` 增加可选的 `MacroEnv.combat_hook`（默认 None，行为不变）。实验脚本在 `artifacts/analysis/claude-combat-net-20261116/`。
- 新测试 `tests/test_combat_net.py`（8 项）：观察形状与候选对应、**重抽隐藏状态后观察完全不变**、`mcts_root` 与 `mcts` 一致、搜索的批量与逐个结果一致、网络前向与三种打法可复现。
- 观察到：现有 MCTS 在第一幕普通战斗 256 次模拟时，根的 12 个动作访问次数为 20–22，几乎平均；它的访问分布不适合当策略标签，第 0 代改为学它实际选的动作。
- **续（2026-11-16 下午，Claude 接手）**：
  - 上一任的后台任务在会话结束时全部停了，续跑：第 0 代数据补到 300 局（游戏种子 7,000,000 起；局外由 `small-b-d1/last.pt` 按概率选；战斗用随机走子 MCTS，普通 256、精英 512、Boss 1024），共 50 个文件、48,642 个决策、4,038 场战斗（普通 3,173、精英 464、Boss 401）。另采了自我对弈用的存档集 `spset.pkl.gz`（种子 9,000,000 起，350 场，与评估集分开）。
  - **内存 bug（已修）**：`train_net.py` 读数据时直接对 `np.load` 的结果切片，每次都解压整个数组，切片还拖住整份数组，每个决策约占 5 MB；两个训练进程并行时本机 8 GB 内存耗尽。改为每个文件只解压一次、每个决策复制自己的一段：3 万个决策加载 532 MB、2 秒。
  - 测试文件：本机的 `tests/test_spire_rl.py` 早于 Codex 11-15 的改动，缺他加的回归测试；已换成训练机上的版本（只多不少）。**本机完整测试 80 passed**（72 + 战斗网络 8 项）。注意 `test_combat_net.py` 需要重新编译的 C++（新接口 `entity_observation`、`NetSearch` 等）；训练机没重编之前不要同步这个文件，否则会失败，训练框架本身仍是 72 项。
  - 临时网络（只用前 31 个文件、约 3 万个决策，3 遍）：“学实际选的动作”和“动作与访问分布各一半”两种标签，选择命中率 43.7% / 44.3%，价值解释方差全部 0.77 / 0.79、Boss 0.42 / 0.49，差别不大，后续用“各一半”。
  - **188 场固定战斗的成对对照**（评估集 `evalset.pkl.gz`，所有打法从同一个存档开始；死亡率，括号里是胜局掉血占最大生命的比例；对照用的是临时网络）：

    | 打法 | 普通（73） | 精英（42） | Boss（73） |
    | --- | --- | --- | --- |
    | MCTS 128/128/512（训练用） | 0%（14.9%） | 11.9%（39.8%） | 38.4%（60.2%） |
    | MCTS 256/512/1024 | 0%（12.9%） | 7.1%（33.4%） | 43.8%（55.8%） |
    | 网络直接出牌 | 1.4%（17.8%） | 9.5%（40.4%） | 61.6%（67.6%） |
    | 网络 + 搜索 64/128/256 | 0%（16.3%） | 7.1%（37.3%） | 47.9%（56.2%） |

    成对差（± 标准误）：MCTS 翻倍搜索在 Boss 上死亡率 +5.5 ± 4.3 个百分点，没有改善；网络加搜索比网络单独 Boss 死亡率 −13.7 ± 4.1；网络加搜索比 MCTS 128 档 Boss 死亡率 +9.6 ± 4.4（更差），比 256 档 +4.1 ± 4.1（不显著）。网络单独 188 场 6 秒，网络加搜索 806 秒（单核），两档 MCTS 各约 436 秒（2 线程）。
  - 还没做：用完整 300 局数据训练第 0 代网络、256/512/1024 档的网络加搜索、自我对弈迭代。用户 2026-11-16 决定这批跑完后暂停，先讨论“本幕 Boss 价值头”的设计。

**2026-11-15（Codex：KL 回滚恢复已验证状态及 Adam，补默认 8 步检查的回归）**

- 原实现每 8 步检查一次，却只保存最后一步前的权重；更早已超限时，退一步仍不合格。旧代码在真实测试观察上的反例：限值 0.0003，默认 8 步检查、保留小批保护时，回滚后仍为 0.000399；更新结束不足一个检查周期也能复现。
- 现在更新开始先验证固定样本；只有周期检查合格才更新安全快照。小批、周期或末尾检查超限时，恢复最近合格的参数与完整优化器状态（包括 Adam 动量和计步），清空残留梯度，恢复相应的保留步数、样本数与分叉数。回滚可能撤销多步，新增 `kl_rollback_steps`。
- `sampled_kl` 临时使用评估模式并恢复原模式；NaN/Inf 不能作为合格状态。最终 KL 始终实测，起点或恢复后无法确认合格则报错。`kl_rollback=False` 仍保留只早停、不恢复的对照行为。
- 回归覆盖默认每 8 步检查、每步检查、小批触发、末尾不足周期、已有 Adam/AMSGrad 状态的恢复及下一步结果一致、非有限检查值与不合格起点。**本机 CPU 完整测试 72 passed**，见第 6 节。
- 只在合格检查点备份，快照留在内存，不增加磁盘检查点；`small` 的权重加 Adam 快照约 0.24 GB（估算，替换快照时短暂峰值更高）。**尚未在 GPU 上验证速度和显存**。推荐训练命令不变；同步清单仍为原来的 6 个源码/测试文件。

**2026-11-15（缺口 1 离线测试：结论否定，不接入；选牌分叉建议关闭；menu_loop 截断不再加估计；分叉参数范围检查）**

- **按选项打分的价值头（缺口 1）**：在第四轮全部 18,597 个分叉上离线测试，冻结 d1 `best.pt` 的查询向量和候选向量，岭回归 / MLP 预测各选项的回报，按游戏种子 5 折交叉验证。与真实值的相关：火堆 0.27 / 0.23（现在用的两套平均 0.61，只用血量 0.35）；选牌 0.04 / 0.03（两套平均 0.53；只用卡牌 ID 也只有 0.04）；地图 0.23 / 0.20（两套平均 0.87）。按比例混进分叉结果，只有火堆混 25% 时略好（0.225 → 0.240），其余变差。**不接入网络。** 详细数字和局限见 [诊断文档第 7 节](../../docs/claude-run4-diagnosis-20261114.md#7-缺口-1按选项打分的价值头的离线测试2026-11-15)；脚本在 `artifacts/analysis/claude-run4-20261114/optval_*.py`。
- **选牌分叉建议关闭**（推荐命令改成 `--fork-card 0`；代码默认值本来就是 0）。选牌分叉占分叉里战斗的 58%（约占全部模拟器战斗的 40%），但上面连卡牌 ID 都学不出规律，第四轮策略与选牌分叉的吻合三段都等于随机。
- **menu_loop 截断不再加 critic 对后续的估计**（`RunConfig.menu_loop_bootstrap=False`，`rollout.py`）。第四轮在网格预览里反复取消（约 95% 是“取消预览”）而被截断的局，训练时按其他截断一样加上 critic 对剩余局面的估计，等于反复取消没有代价；验证时这局就停在那一层。d1–d3 各有 1、24、21 局，平均停在第 9–17 层。现在按“到此结束”计（和在那一层死亡一样）；分叉分支里遇到同样的截断也一样处理（`stop_reason="menu_loop"`）。设为 True 可恢复旧做法。
- **分叉参数范围检查**：`ForkConfig` 要求 `seeds` 在 1–8、`max_options` 在 2–8。分支的编号按“选项 × 8 + 种子”编，超过 8 会让两个分支用同一个编号，`collate` 会把它们的历史混在一起而不报错。
- 测试 60 → 63 项（menu_loop 两种设置、参数范围）。另在本机用 tiny 预设跑通了 4 次更新的端到端训练（火堆 + 地图分叉、无选牌分叉）。
- 审计范围：`ppo.py`、`rollout.py`、`env.py`、`data.py`、`train.py`、`model.py`、`checkpoint.py`，除上面两处外没有发现问题。

**2026-11-14（第四轮三段的诊断；分叉损失改为有上限、分叉复用、KL 超限退回、学习率随拦停调整）**

第四轮（`small-a0-d1` 至 `d3`，7,769 局）的数据和诊断见 [docs/claude-run4-diagnosis-20261114.md](../../docs/claude-run4-diagnosis-20261114.md)。要点：验证从 22.2 层到 29.2 层的涨幅都在第一段，而且训练数据里前约 300 局就完成了（不再丢下金币遗物、不再丢药水、火堆一律回血）；之后两段半停在 28.5–29.3 层。

原因（按确定程度）：

- **已确认：分叉损失没有上限。** 原写法是 `−优势 × log P(选项)`，对分数的推力是常数，选项的概率已经多小都照推。在检查点上直接量到的火堆 log P(升级)：−19（2,002 局）→ −38 → −168 → −539（7,769 局），所有血量下相同；选牌、地图分叉里被比下去的选项到 −5,000 左右。d3 末分叉项的梯度范数约是 PPO 项的 70 倍，熵奖励小两个量级。
- **较强怀疑：策略饱和后 PPO 失效。** 88% 的多选决策概率超过 0.99，主线样本的梯度趋近于零，也不再采到别的选项；只剩分叉项在推，偶尔把别处的决策整个翻掉（单个小批的 KL 到过 28），每次更新约 7 步（满额 57 步）就被拦停，每批样本只用 0.4 遍，分叉只有 47% 进过梯度。
- **已确认是因素之一：学习率 1e-4 偏大。** 预热到 1e-5–4e-5 时每次更新走满 3 遍，到 1e-4 后很快降到 8 步以内；但饱和以后 1e-5 也会被拦停。
- **已确认：分叉标签噪声大。** 两套种子的均值的可靠度：地图 0.76、火堆 0.37、选牌 0.28。策略的选择和分叉结果的吻合程度三段都没有上升。
- **已确认：PPO 的优势大部分是通关的运气。** 通关项占回报方差约 70%，critic 预测不了；critic 对层数的解释方差已到 0.25–0.36。这一项没有改（通关奖励权重是用户定的）。

改动：

- **分叉损失**（`ppo.py` 的 `fork_target`、`fork_reference`，`ForkConfig.target_scale / adv_clip / prob_floor`）：每次更新开始时用当前策略算出每个分叉决策的目标分布，目标 ∝ max(当前概率, 0.01) × exp(归一后的优势，限幅 ±3)，损失是目标到策略的 KL（只在被比较的选项之间）。推力与选项的概率成正比，达到目标后为零；被推到 0.01 以下的选项会被拉回。同一个测量连续重复时，选项的对数概率停在 log 0.01 − 6 ≈ −10.6，不再一直往下。`fork_loss` 的含义随之变成“每个分叉决策的 KL”（≥ 0），和以前的数值不可比。
- **分叉复用**（`ForkConfig.replay_rollouts=4`，`--fork-replay`）：每次更新同时用最近 4 轮的分叉决策，优势沿用当时的测量，目标按当前策略重算。分叉样本不再搭在 PPO 小批上，而是每步单独取一份（一遍数据正好走完一遍分叉池）；`--fork-coef` 的含义不变（一个分叉决策相当于几个普通样本）。
- **KL 超限退回**（`PPOConfig.kl_rollback`）：本次实现为每步保存权重、超限时退最后一步；后来发现默认每 8 步检查时仍可能保留越界状态，已由 2026-11-15 Codex 修复改为恢复最近检查合格的参数和优化器，见本节首条。
- **学习率**：`small` 预设 1e-4 → 3e-5。一次更新不到一遍数据就被拦停，之后的学习率乘 0.7（不低于基础值的 0.1 倍）；走满全部遍数乘 1.1（不超过基础值）；系数存在检查点的 `progress.lr_adapt` 里，下一段接着用（`train.py` 的 `adapt_lr`，`PPOConfig.lr_adapt_*`）。只调策略的学习率，critic 不变。
- **新监控**：`fork_option_logp_min`（各分叉决策里最低的选项对数概率的中位数，更新前量）、`fork_pool`、`kl_rollback`、`sampled_kl_final`、`lr_adapt_next`。
- `ppo_update` 的参数 `fork_coef` 换成 `fork`（`ForkConfig`）和 `fork_pool`。旧检查点可以照常加载（新字段取默认值）；配置指纹会变。

没有改：通关奖励权重、优势限幅、火堆分叉只跑两场战斗（对升级不利，见诊断 4.6）、奖励界面的熵奖励、分叉的种子数。

验证（本机 CPU）：

- 60 项测试通过（新增 7 项：目标分布的性质、分叉损失收敛到上限而不是一直推、分叉池包含更早的轮、KL 超限退回与不退回的对照、保留下来的策略在限值以内、学习率随拦停调整并跨段接续）。
- 在第四轮的真实数据上跑一次新的更新（d1 `best.pt` 和它采的第 67 轮，3e-5）：裁剪前梯度范数 23（旧损失下含选牌分叉的小批是 500 以上），第 9 个小批越界后退回，保留下来的策略在固定样本上的 KL 为 0.004。这个检查点本身已经饱和，只能说明新代码在真实网络和数据上能跑、不再被分叉项主导。
- 按正式命令的配置（`small`、同样的分叉和 α 参数，缩小每轮决策数和战斗搜索量，随机初始化，3e-5 不预热）跑三次更新再接一段：每次更新走满 3 遍，固定样本上的 KL 0.0001–0.0004，没有拦停；分叉池 5 → 10 → 17（逐轮累积），`fork_loss` 0.19–0.30，`fork_option_logp_min` 约 −1.1；第二段从 `last.pt` 接续正常。每次更新只有 9 步（正式配置是 57 步），所以这只说明流程通，不说明 3e-5 在正式配置下合适。
- **没有在 GPU 上跑过，也没有在蒸馏出来的策略上验证过**（本机没有 `runs/distill-small.pt`）。学习率 3e-5 和分叉目标的三个参数都是按分析定的初值。

**2026-11-15（文档：研究缺口与候选实验）**

补充第 4.6 节及缺口文档的论文摘要、来源与实验顺序，并在根交接说明中增加入口；修正“根先验等效于更多搜索”和“Boss 搜索无收益”的过强表述。仅整理讨论，未修改训练实现或配置；新增链接、文档结构及差异检查通过。

**2026-11-12（第四轮首次启动：概率重算检查被 BF16 舍入触发；加固；`eval --greedy`）**

现象：训练机上 `small` + 分叉跑到第 7 次更新（240 局）后报 `log-probability recompute mismatch 0.05343 > 0.05` 退出。这项检查在每次更新前，用没改过的权重把 64 个决策的对数概率重算一遍，和采样时存下的值比较，用来发现“更新时看到的输入和采样时不一样”。

原因（已确认是数值舍入，不是数据错位）：

- BF16 只有 8 位有效数字，分数在 8–16 之间时只能按 1/16 一档存。同一个决策，采样时和别的决策拼成一批（平均约 1.5 个），重算时是 64 个一批，中间结果的舍入不同，最后的对数概率就差出一到两档。
- 这个差一直存在：第一轮 137 次更新、第二轮 233 次更新的 `recompute_max_abs` 平均约 0.009–0.010，最大 0.023 和 0.031；限值 0.05 当时只是没被碰到。这一次策略在 7 次更新里变尖得很快（熵 0.82 → 0.51），分数变大，舍入的档也跟着变大，就越过了 0.05。
- 本机复现（`small` 随机初始化、把输出头调尖、CPU 上的 BF16，第二轮归档里的真实局面，同一批决策分别按 1–3 个一批和 64 个一批前向）：FP32 下两者完全相同；BF16 下被选动作的差平均 0.002–0.008，每 64 个里的最大值 0.02–0.08，随策略变尖而变大。
- 分叉路径没有错位：新增测试在 FP32 下带分叉采样后逐个重算，误差 < 1e-4；故意改掉一步历史动作则能测出差别。

改动：

- **输出头固定用 FP32**（`model.py`：候选打分、动作组打分、价值头、辅助头；主干仍按配置用 BF16）。同样的复现里，被选动作的差平均降到 0.001–0.002（原来的 1/3 左右），但每 64 个里的最大值仍有 0.01–0.07（主干的 BF16 舍入还在）。
- **`small` 预设默认 FP32**（`PPOConfig.bf16=False`）：差别归零，检查保持原来的 0.05。0.02B 的网络用 FP32 预计不会明显变慢，**但没有在 GPU 上实测**；`train --bf16 / --no-bf16` 可以按次覆盖。
- **BF16 下的限值单独设为 0.25**（`recompute_tolerance_bf16`），FP32 仍是 0.05。依据：BF16 的舍入差在 0.03–0.08 是正常水平，对 PPO 的影响很小（比率误差几个百分点，裁剪范围是 20%）；真正的输入错位应由 FP32 下的测试精确发现。
- **同日加固（为了减少来回）**：
  - 报错或 Ctrl+C 退出时也保存 `last.pt`（最后一次更新后的权重，`progress.final=false`、`progress.stopped` 记原因），然后照常报错。权重里有非有限数、或一次更新都没做完时不覆盖。之前异常退出最多丢掉上次验证以来的约 2,000 局。
  - 有对局被记为失败时，终端打印数量和原因（之前只写进归档）。
  - 本机长跑检查：`tiny` 网络带分叉连续 40 次更新（510 局，critic 回放队列滚动过 12 轮，9 次验证，40 个归档）无异常；按正式命令的配置（`small`、同样的分叉和 α 参数，只缩小每轮决策数和战斗搜索量）跑两次更新 → 第三轮采样中途 Ctrl+C → 保存 → 第二段从 `last.pt` 接续，种子接续正确。
  - 复查过的其他项：第一、二轮 16,001 局里记为失败的对局是 0；回放队列 12 轮约占 0.8 GB 内存；一个局面的实体数平均 88、最多 200，FP32 下显存估计够用（未实测，看 `gpu_peak_gib`）。
  - 仍然防不住的情况：C++ 里的死循环或段错误（两轮训练没出现过）；FP32 在 GPU 上的速度。
- **同日新增 `eval --greedy`**（之前提过、当时未定的做法之一）：`evaluate(greedy=True)` 每步取概率最高的动作，游戏种子和战斗搜索种子与采样评估相同；结果里记 `greedy` 和 `conditions.sampling`。`compare` 增加同种子配对的层数差及标准误、到第二幕比例、截断数（通关只有 0–1 个时 McNemar 没有分辨力）。训练和训练中的验证不变，仍按概率采样。**没有在训练好的策略上跑过**：本机没有权重，只在随机初始化的小网络上验证了“取的确实是概率最高的动作”和命令行流程；训练好的策略取最大时会不会卡在菜单里，要看第一次的 `truncations`。
- 这次崩溃没有保存进度（当时异常退出不保存，`small-a0-d1/last.pt` 是第 0 局验证时存的，等于蒸馏结果），损失约 240 局。重新启动：原命令不变，换一个新的 `--run-dir`（或先删掉旧目录），仍从 `runs/distill-small.pt` 开始。**不需要重新编译 C++，不需要重新蒸馏。**
- 本机 CPU：53 项测试通过（新增 8 项：带分叉的采样重算一致、BF16 下输出头为 FP32（旧代码上该测试失败）、限值与 `--bf16` 开关、报错与 Ctrl+C 时保存、坏权重不覆盖、取最大评估与命令行、配对层数差）；`smoke` 通过。
- 这次启动里看到的其他数字：`[val @0]` 22.1 层、0.46 到第二幕、1/200 通关（蒸馏接上了第二轮末尾的水平）；7 次更新里每轮约 30–39 局的平均层数从 20.5 到 27–30（每轮局数少，波动大，还不能当结论）；熵下降很快，下一次启动要看 `entropy_group` 和火堆回血率有没有被推到 0 或 1。

**2026-11-11（第四轮准备：小网络、蒸馏、逐张卡牌分叉；尚未在 GPU 上运行）**

起因：第三轮（0.2B、接着第二轮）在训练机第 7 次更新时因 C++ 事件异常崩溃；用户的 GPU 只能按工作日分段使用；第二轮约 90% 的墙钟花在 0.2B 网络上（更新 7.6 小时、推理 3.0 小时，共 11.7 小时）。用户决定换小网络并保留 8 步历史。

- **C++（ruleset v8）**：The Future of Potions 对原生 Event / Token 稀有度的药水（Foul、Glowwater、Potion Shaped Rock）抽到 Power 类型时抛 `reward pool is too small`。原因、修复和验证见 `artifacts/dev/cpp-native-aligned-20261031/validation/future-potions-fix-20261111/README.md`。v7 的检查点在 v8 上不能加载，第二轮归档仍可读。
- **环境**：`rc.step` / 战斗驱动抛出的 C++ 异常现在记为该局的 `FAILURE`（原因写入归档与 `failure_reasons`），不再让整轮退出；单轮失败数超过 `max(2, 2%)` 时训练仍会报错停止。
- **`small` 预设**：Set Transformer 256 宽 × 2 ISAB，历史 Transformer 512 宽 × 4 层、**8 步**，约 0.02B；`lr=1e-4`、`microbatch=32`、不做激活检查点。配套 critic `CRITIC_LITE`（约 1.9M，4 步历史，dropout 0.1）。依据：第一轮模仿测试中 32 步、8 步、无历史没有可测差别；第二轮 19.6M critic 在刚训练过的批上解释方差 >0.95，对新数据只有 0.06–0.17。**学习率是未经验证的初值**，看 `target_passes` 和 `kl_stop_reason` 调（`--lr`）。
- **`distill`**：对归档里策略实际采样的动作做最大似然（收敛到该策略的概率，不需要教师权重），默认用最后 60 个归档文件，最后 6 个留出；同一遍里用真实后续事件从随机初始化训练 critic。保存留出交叉熵最低的一轮，格式与普通检查点相同。报告含 `teacher_nll`（教师自身的交叉熵，来自归档的 `logp`）与 `kl_estimate = nll - teacher_nll`。
- **卡牌分叉**（`--fork-card`）：选项改为每一张可拿的牌加跳过（之前只比较“拿/跳过”两组）；分支默认跑到**本幕结束**（打完本幕 Boss 进入下一幕，或本局结束），回报只计分支内真实发生的层数、进幕和通关，不加 critic 估计（`ForkConfig.card_to_act_end / card_bootstrap / card_max_decisions`）。火堆与地图分叉的范围不变（2 场战斗 / 40 个决策 / 换幕）。
- **分叉不用 critic 的通关估计**（`ForkConfig.bootstrap_win=False`）：第二轮末尾通关头的解释方差 −0.04、取值 −0.04–0.35，而它的权重是 1.0（α=0.5 时一层只有 0.005）。分支里真实的通关照常计 5 分。归档的 `bootstrap_comps` 记录的是实际用于回报的值，重算公式不变。
- **分叉优势按界面分别归一**（火堆、地图、卡牌各自除以本轮该界面的标准差）；地图分叉在被选动作不是移动时不再触发（约 0.5% 的地图决策是用药水）。
- **训练种子**：检查点 `progress.next_train_seed` 记录下一个未用的游戏种子，`train --init-checkpoint` 默认从它开始；也可用 `--train-seed-base` 指定；训练种子与验证/测试种子重叠时报错。第一、二轮都用了 1,000,000 起的同一批种子（同一种子两轮最终层数相关 0.27，打乱后 −0.03）。
- **学习率预热**（`PPOConfig.lr_warmup_steps`，`small` 默认 150，其他预设 0）：每段训练都重建 Adam，它最初几步对每个权重的步长约等于学习率而与梯度大小无关；策略与 critic 的学习率因此从 10% 线性升到 100%。`metrics.jsonl` 新增 `lr`。
- **`--max-hours`**、`--lr`；`best.pt` 在胜率相同时比平均层数；`pretrain`/`distill` 读归档时重排局编号（多 run 合并不再冲突）；有分叉时工作线程数 = min(CPU 核数, 2 × 环境数)，不影响结果。
- 新监控：`fork_branch_decisions`、`fork_branch_combats`、`fork_rest/map/card_taken_was_best`。`max_active_branches` 默认 48→96；超过上限时跳过哪些分叉取决于线程时序（主线对局不受影响）。
- 本机 CPU：45 项测试通过（新增：small 预设规模、逐张卡牌分叉与通关估计、幕末停止（脚本化环境）、按界面归一、异常转失败、药水事件回归、时间预算与种子接续、蒸馏后继续训练、学习率预热）；CLI 端到端冒烟（蒸馏 → 带分叉训练 → 到点保存 → 第二段接续）。**GPU 上的速度、显存、蒸馏质量和训练效果均未验证。**
- 未做：0.2B 网络上的“截短历史”对照评估（用户决定不做）；起点课程；战斗网络。
- **已知但本轮未处理的行为问题**（第二轮最后 757 局，训练时的采样动作）：奖励界面还有东西可拿时 11.9% 的次数直接离开，金币被留下 18.9%、遗物 9.9%、卡牌奖励没打开 15.3%；能丢药水时 21.5% 丢掉。这些决策几乎没有回报信号，熵奖励和按概率采样让“离开”“丢药”一直保留一到两成概率。本轮的分叉只在火堆、地图、卡牌奖励上做，不覆盖奖励界面。待定的两个做法：验证时取概率最高的动作（`collect(greedy=True)` 已有，CLI 未暴露）；奖励界面去掉或减小熵奖励。
- **后期战斗上限**（本机实验，`artifacts/analysis/claude-combat-ceiling-20261111/`）：第二幕普通战斗把搜索加到 16 倍，死亡率约 12% → 4–7%、掉血约少 5 个百分点；第二幕 Boss 19 场，死亡率 81.6% → 73.7%，差别不显著。第二幕的墙主要不在搜索次数上。详表见根 `AGENTS.md` 第 2.3 节末尾。

**第三轮启动前补充（Codex，小范围修复）**
- 本轮离线训练只读取 `runs/main-a0-s2/archive`；跨 run 合并的局编号问题未在本次处理。
- 归档升级为 `spire_rl.archive/3`，仍可读 /1、/2。每个 `archive/rollout_*.npz` 内的 `forks_json`（UTF-8 JSON 的 uint8 数组）保存根局索引/决策、候选索引与动作组、每组搜索/采样种子、分支累计事件、critic 的 `bootstrap_comps`、总回报、停止/失败原因和步数/战斗数；不保存分支完整轨迹。`read_rollout()` 恢复到 `ep.info["forks"]`，仍不作为额外 PPO 对局。
- 归档 meta 保留行为更新编号，并补入 `fork_config`、`value_scale`、`value_weights`。单个分支回报可由 `(events + bootstrap_comps * value_scale) @ value_weights` 重算；终局分支不 bootstrap。PPO 分叉标签仍按原来的回报去均值、整批标准差归一，不改训练算法。
- 离线 critic 把训练前权重作为 epoch 0 纳入选择，按原有“留出层数 EV + 进幕 EV”合计严格提高才替换（零方差项省略，非有限候选不选）。报告增加 `best_epoch`、`best_heldout_ev`、`improved`；若未改善，输出 prior 保留初始权重。
- `fork_branches` 统计实际启动的选项数 × 种子数，含失败分叉；`fork_taken_was_best` 只统计有唯一最优选项的完整分叉，无有效样本时为 NaN。新增 `fork_decisive` 和 `fork_tie_rate`；并列最优按 `rtol=1e-6, atol=1e-8` 判断，监控时一起看样本量和平局率。
- 本机 CPU：35 项测试通过，含分叉归档及回报重算、旧格式兼容、critic 退步/持平/非有限/先升后降时的权重选择、分支计数和平局统计。修正旧确定性测试按线程完成顺序错配对局的问题，改按局编号与决策位置比较。未验证 GPU，未启动正式训练。

**2026-11-11（第三轮：接着第二轮训练 + 价值先验 + 成对分叉）**
- `train --init-checkpoint <best/last.pt>`：从已有权重继续（只载权重，优化器重建，新 run 目录；网络形状取自该检查点）。`--critic-prior` 载入离线预训练的 critic。来源写入 run 的 `config.json`。
- `pretrain-critic`：用归档的真实后续事件（层数、进幕、通关）离线训练 critic；按文件分块读取，最后若干文件留出评估，保存留出 EV 最好的一轮及 `.json` 报告。
- critic 回放：每次更新的 critic 训练还抽取最近 `critic_replay_rollouts=12` 轮的数据（比例 `critic_replay_ratio=1.0`），`value_epochs` 4→2，总量与之前相近。
- 成对分叉（`RunConfig.fork`，默认关闭；`--fork-rest/--fork-map/--fork-card/--fork-seeds/--fork-coef`）：在火堆、地图（、卡牌奖励）按概率复制状态，各选项在相同搜索种子与采样流下前进到幕变化、2 场战斗或 40 个决策，剩余部分用 critic 估计；选项回报去均值并按本轮标准差归一，作为额外策略损失（火堆/卡牌按动作组，地图按具体路线）。分叉步不进入 PPO 数据；被选动作始终是选项 0。
- `--alpha`：整轮固定一个进度权重（单档，无档位切换）。
- 新监控：`forks`、`forks_complete`、`fork_rest/map/card`、`fork_return_spread`、`fork_taken_was_best`、`fork_rest_heal_better`、`fork_loss`、`fork_targets_seen`、`critic_targets`，以及火堆按血量的行为 `rest_heal_rate_hp_below_50`、`rest_heal_rate_full_hp`。
- 测试 28 项。

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
