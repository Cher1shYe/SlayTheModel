# STS1 RL / MCTS 工作区快照

此分支已按要求替换为 `D:\project\sts` 的当前代码快照（2026-10-26），不再包含原来的 STS2 工作区文件。旧内容保留在 Git 历史中。

## 内容

- `sts-rl-agent/`：Jialeiv/sts-rl-agent 源码、文档和发布权重。
- `simulator/`：本地修订后的 sts_lightspeed 源码，包含 Windows 兼容、战斗规则、状态快照以及定时 MCTS 接口。
- `deployment/`：训练启动器、自对弈、评测、数值稳定修复及 fast PUCT 优化。
- `deployment/results_puct_vs_mcts/`：等时间 PUCT vs 原生 MCTS 的配对评测结果（150 seeds）。
- `deployment/training_audit_v3/selfplay/`：训练驱动实际使用的兼容源码模板，不包含训练日志。
- `deployment/selfplay_6x40_s64/` 与 `deployment/selfplay_stable_s512_r1/`：仅包含启动器所需的历史源码、配置和指定初始化权重，不是完整实验结果。
- `SOURCE_MANIFEST.json`：复制的本地文件 SHA256 清单。

没有上传虚拟环境、编译产物、临时文件、训练日志、经验池，或当前仍在运行的 10 轮实验目录。

## 获取依赖

```bash
git clone --recurse-submodules --branch snapshot/sts2-workspace-20261012 https://github.com/Cher1shYe/SlayTheModel.git
```

两个 C++ 依赖作为固定版本 submodule 保存。已有克隆需执行 `git submodule update --init --recursive`。

当前实际验证环境为 Windows + Python 3.12 + CPU PyTorch。创建 `.venv`，安装 torch、numpy、tensorboard、cmake、ninja 后，可参考 `deployment/Rebuild.ps1` 编译模拟器；该脚本使用 Visual Studio 2026 Build Tools。Linux 需要重新编译扩展，并适配当前驱动使用的 `simulator/build312/Release` 搜索目录；本快照不宣称已完成 Linux/CUDA 部署验证。

## 训练

通用入口见 `deployment/TRAINING_GUIDE.md`。单次稳定训练入口：

```bash
python deployment/selfplay_compare.py --out deployment/runs/example --rounds 10 --games 40 --epochs 2 --sims 512 --workers 4 --stabilize --fast-puct
```

此命令默认从上游发布的策略/价值权重开始。`deployment/run_selfplay10.py` 则从附带的最近稳定实验第 1 轮权重热启动（优化器和经验池重新初始化）。输出目录必须不存在。它包含前后各 50 局评测、每轮 10 局监控，以及同次数/同耗时原生 MCTS 对照。

本地 PowerShell 的隐藏后台进程启动方式不包含在上述 Python 命令中；服务器应自行使用持久任务管理工具。

数值修复包括状态有限值验证与限幅、搜索价值限制到 0～2、raw-value Huber loss 与梯度裁剪。fast PUCT 保留这些保护，通过减少重复编码和张量构造加速；固定 16 状态测试中约加速 2.3 倍，根统计与动作一致。不是 GPU 推理版本。

## PUCT 对比同时间 MCTS：实验与结果（2026-10-26）

本节的实验目标是：**在相同墙钟预算下，让神经网络引导的 PUCT 搜索超过原生（随机 rollout）MCTS**。
最终在 150 个配对种子上达成：130 ms/决策时 **46.64 层 vs 41.26 层（配对 Δ=+5.38±0.69，t=7.77）**，
通关率 **43.3% vs 13.3%**（McNemar p≈4×10⁻¹⁰）。

### 指标与评测协议

- 层数 `floor`：一局结束时的楼层；`floor==51` 与"通关"（`GameOutcome.PLAYER_VICTORY`）完全一一对应。
- `battle_win` / `battle_hp`：战斗胜率 / 战斗结束时剩余血量比例。
- `ms/dec`、`sims/dec`：每次战斗决策的平均搜索耗时与模拟次数，用来确认两个方法确实同预算。
- 150 seeds = `sts-rl-agent/eval/eval_seeds_50.txt` 的 50 个固定种子 + 100 个随机种子（`random.Random(424242)`）。
- `deployment/final_bench.py` 把两种方法的同一 seed 相邻排队，在同一个进程池里交错跑，避免机器负载漂移造成的系统偏差；
  输出逐 seed 配对差、SE、t 值。
- 非战斗决策所有对比共用同一个冻结的 ArmG G128x128 策略，差异只来自战斗搜索。

### 最终配对结果（150 seeds，130 ms/决策）

| 配对比较 | 平均层数 | 配对 Δ | 通关率 |
|---|---|---|---|
| PUCT+greedy vs 原生 MCTS | 46.64 vs 41.26 | **+5.38 ± 0.69（t=7.77；88 胜/6 负/56 平）** | 43.3% vs 13.3%（p≈4×10⁻¹⁰） |
| 原生+greedy vs 原生（归因对照） | 45.37 vs 41.76 | +3.61 ± 0.65（t=5.51；81/10/59） | 40.7% vs 12.0% |
| PUCT+greedy vs 原生+greedy（同一搜索，只差根先验） | 46.51 vs 45.59 | +0.91 ± 0.41（t=2.24；25/9/116） | 42.0% vs 39.3%（n.s.） |

结果 JSON：`deployment/results_puct_vs_mcts/bench150_{puct_greedy,native_greedy,puct_vs_ngreedy}.json`。
两次原生存档的绝对值有约 0.5 层的批次差（41.26 / 41.76），配对比较不受影响。

### 方法

1. **把 PUCT 做进 C++ 原生搜索**（`simulator/{include,src}/sim/search/BattleScumSearcher2.*`）。
   原来的 PUCT 在 Python 里逐节点递归 + 神经网络前向，每次模拟约 50 µs，130 ms 只能跑 ~2.7k 次模拟；
   C++ 原生搜索每次模拟约 6 µs，同预算 25–30k 次。先把根节点换成 PUCT 选择：

   ```text
   根节点：  Q + c · P_a · sqrt(N) / (1 + n_a)        （Q 沿用原生 min-max 归一化）
   新根子节点：按 P_a 采样，而不是均匀随机
   其余节点：保持原生 UCB（explorationParameter = 3√2）
   ```

   `priorMode=1` 为"保留 log 调度、按先验分配探索"的变体，`priorMode=4` 为 UCB+先验加成；
   `annealCount=N0` 时 PUCT 项权重 `N0/(N0+N)` 随根访问数衰减回 UCB（先验管早期、多样性管后期）。

2. **expert-greedy rollout（决定性改动）**。原生搜索每次模拟从叶子开始随机走到战斗结束，
   "最佳线路"（`bestActionSequence.front()`）是在一堆乱打的线路里挑最好的。新增 `playoutGreedy`：

   ```text
   每步：按 Expert::getPlayOrdering 排序的第一张可打牌 → 没有牌可打则结束回合 → 药水最后
        ε 概率改走随机动作（ε=0.05，保多样性）
   ```

   成本几乎为零（仍在 6 µs/模拟量级），但让每条被评估的线路都是"会打"的线路。
   同一 130 ms 预算内模拟数反而从 ~26k 升到 ~30k（rollout 更短）。

3. **根先验**来自 armD round4 的 battle policy 网；每个决策一次批量前向（约 2 ms），从搜索预算中扣除，
   保证两个方法的总决策耗时相同。先验只作用于根节点——深层先验需要逐节点网络调用，成本不可接受。

### 实验清单（含负结果）

**A. Python 侧 PUCT（神经网络叶子）**

- 模拟数曲线（30 seeds）：256→33.40、512→36.47、1024→36.10；130 ms 定时（约 2704 sims）→32.4。
  **更多搜索反而更差**，说明瓶颈是价值网的偏差而不是搜索量。
- 512 sims、150 seeds：最强自对弈臂（armC r5）35.75 层，距原生 130 ms 的 40.9 仍差 5 层。
- 无效或有害的尝试：win 加权叶值、rollout 混合（8 seeds：比例 0/0.25/0.5/0.75 → 37.50/37.12/37.50/36.50）、
  forced playouts、c_puct 调整、多网 ensemble、价值网 net2net 加宽（256→512）、root-Q 选择、深度上限、
  森林/Q 池化、观测特征与遗物计数扩展、纯 rollout 叶（512 sims 只有 32.40 vs 神经 35.87）。
- soft 策略蒸馏失败的原因：PUCT 根访问数近似均匀，软目标接近均匀，策略被拉平；
  改用 one-hot native@8000 的 DAgger 之后纯策略从 ~23.5 提到 26.7 层（armQ r5/r6/r7），
  但作为根先验使用时 130 ms 结果不变（41.27 vs 41.27）。

**B. C++ 根先验 PUCT**

- 等模拟数（4000，15 seeds）：原生 36.53；PUCT c=1/3/6 → 35.73/37.67/39.93。
  但 150 seeds 配对复验只有 **+0.27±0.58**——15 seed 的优势是小样本噪声。
- 130 ms（15 seeds，不同批次）：c=3/6/10/16 → 38.93/41.53/41.27/41.87；原生 40.7–42.5。
- 先验消融：均匀先验 c=10 = 42.40（≈原生），学习先验 c=10 = 41.27；先验温度 0.5（更尖）= 39.33；
  armQ 先验 = 41.27。**先验在这一预算下几乎不提供信息**。
- 退火（N0=8000）15 seeds 拿到 43.13，但 50 seeds 配对只有 +0.32±0.91：仍是 parity。
- priorMode 1（先验调制 UCB）38.87、priorMode 4（UCB+先验）38.27、2/4 次独立重启 42.40/40.80
  （原生重启 38.80，说明重启对极值统计不利）。
- 价值类：绝对价值先验 38.93、play-plan 两拍 lookahead 37.60、GAZ completed-Q 选择 32.13、
  按访问数选择 35.53，而按"最佳线路"选择 40.73。**平均 Q 在本域严重失真**（收益重尾 + rollout 策略弱于实际搜索策略）。

**C. expert-greedy rollout（唯一带来大增益的改动）**

15 seeds、130 ms：原生 41.20 → 原生+greedy 48.87 → PUCT+greedy c=3/6 49.07/49.67（ε=0.05 时 49.73）。
150 seeds 配对见上表：+5.38（对原生）、+0.91（对同 rollout 的原生搜索，即纯先验贡献）。

### GAZ Play-to-Plan（Pirnay et al., ICLR 2023, arXiv 2306.04403）

论文方法是**训练**算法：学习 actor 与历史贪心策略 π_B 进行双人交替自博弈，
value 网改成比较型 `V(s,s') = E[sgn(r−r')]`（同一时间步下"我是否领先过去的自己"），
再用 GAZ 的 completed-Q 策略改进产生策略目标；测试时仍固定为玩家 1。

本轮做了三件相关的事，结论都是负的或不适配：

1. 直接实现 GAZ 的根动作选择 `argmax g_a + logπ_a + σ(Q̂_a)`（completed-Q 用先验加权均值填充）：
   130 ms 只有 **32.13 层**，比同搜索的 best-line 规则低 8.6 层。
   原因是每次模拟的叶子值来自随机 rollout，平均 Q 系统性低估、且与实际搜索策略不符。
2. 推理期零训练近似（维护一条贪心参考轨迹，用 `V(child) − V(ref@t)` 当根先验）：38.93 层，
   且参考策略前向 + 每个候选一次价值前向吃掉约 1/3 预算（22k vs 33k sims）。
3. 论文真正的比较型 value 需要改训练循环（双 actor 数据、配对 value 网），本轮未实现。

### 复现

```bash
# 编译（Linux 验证环境）
ninja -C simulator/build312/Release

# 150 seeds、130ms/决策、逐 seed 交错的配对基准
python deployment/final_bench.py --run deployment/runs_v2/armD --round 4 \
  --workers 24 --extra-seeds 100 --timed-ms 130 \
  --modes native_timed,puct_greedy_timed --cpuct 3 --playout-eps 0.05 \
  --out deployment/results_puct_vs_mcts/bench150_puct_greedy.json

# 归因：同 rollout 策略、去掉根先验
python deployment/final_bench.py ... --modes native_greedy_timed,puct_greedy_timed ...
```

新增/修改的 C++ 接口（`simulator/bindings/slaythespire.cpp`）：

```text
mcts_puct(bc, sims, priors, cPuct, anneal, priorMode)
mcts_puct_timed(bc, ms, priors, cPuct, anneal, priorMode)
mcts_stats_timed(bc, ms, priors, cPuct, anneal, priorMode, usePuct)   # 返回各根边的访问数/评估和
mcts_restarts_timed(bc, ms, priors, cPuct, anneal, priorMode, nRuns, usePuct)
mcts_ex_timed(bc, ms, priors, cPuct, anneal, priorMode, playoutMode, eps, usePuct)
rollout_native(bc, n)                                                # 原生启发式的 rollout 均值
```

Python 侧新增 `deployment/selfplay_v2.py` 的评测模式：
`puct_native[_timed]`、`gaz_timed`、`native_q_timed`、`puct_restarts_timed`、`native_restarts_timed`、
`puct_vprior_timed`、`playplan_timed`、`puct_refprior_timed`、`puct_greedy_timed`、`native_greedy_timed`，
以及 `deployment/final_bench.py`（配对基准）与 `deployment/rollout_eval.py`（单配置扫描）。

### 局限

- 只改了战斗内搜索；战斗外的策略固定为 ArmG，两个方法相同。
- greedy rollout 使用的是模拟器自带的 `Expert::getPlayOrdering` 领域先验，不是学出来的；
  它解释了 +5.38 中的 +3.61，学到的根先验只解释 +0.91。
- 定时比较在共享机器上执行，两台方法在同一任务内交错采样以抵消负载漂移；但绝对层数仍会随负载有约 0.5 层的批次差。
- 价值网没有进入最终方案：所有把它塞进搜索的尝试（叶值、根先验、比较值、完成 Q）都是负结果。
  若要继续提升网络部分，最可行的是用当前 46.6 层的搜索做 self-distillation（根访问数当策略目标），
  或者按 GAZ PTP 的方式改训练目标（比较型 value），而不是调温度或加宽网络。

## 来源与许可

- Agent：https://github.com/Jialeiv/sts-rl-agent ，源版本 `039c199933b7d3a2e5d8fde51ae77a9175e1031f`；许可见 `sts-rl-agent/LICENSE`。
- Simulator：https://github.com/gamerpuppy/sts_lightspeed ，基于 `7476a81954020087da31d41d16fddf475746ec2d` 加本地修改；许可见 `simulator/LICENSE.md`。
- JSON 与 pybind11 版本由根目录 `.gitmodules` 和 gitlink 固定，分别遵循上游许可。

历史文档可能包含本机绝对路径和旧实验描述，以当前源码、此 README 和配置为准。
