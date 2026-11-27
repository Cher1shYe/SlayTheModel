# 训练手册（5090 / A100）

2026-11-26 起用这一份。命令都可以直接复制。看不懂或者结果和这里写的不一样，就停下来，把输出发回来。

---

## 现在要做的事（按顺序，一次做一步）

| 步 | 机器 | 做什么 | 大约多久 |
|---|---|---|---|
| 1 | 5090 | 更新代码、编译、测试 | 15 分钟 |
| 2 | 5090 | 测速：四种网络大小各测一次 | 30 分钟 |
| 3 | 5090 | 小网络（small）从零训练 | 12 小时 |
| 4 | 5090 | 大网络（large）从零训练 | 12 小时 |
| 5 | 5090 | 两个网络各评估一次 | 各 0.5–1 小时 |
| 6 | A100 | 测速，然后正式训练 | 测速半小时以内 |

每一步做完，把“要发回来的东西”发回来。看过结果再走下一步。第 6 步用哪种网络、跑多久，看完第 3–5 步再定。

---

## 每次开始前（两台机器都一样）

```sh
conda activate slay                               # A100 上换成那边的环境名
cd /mnt/c/Users/yebohou/SlayTheModel              # A100 上换成那边的仓库路径
```

---

## 第 1 步：更新代码、编译、测试（5090）

```sh
git pull                                          # 或者你们平常的同步方式
CXX=g++ python sim/build.py --test
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"
python -m pytest -q train/tests
```

**正常的样子：**
- 编译最后一行是 `65/65 test programs passed`
- 版本号是 `native-41cef1ea-port-v31`
- 测试是 `106 passed`（有 GPU 时）或 `105 passed, 1 skipped`

**不正常：** 有任何 FAILED，或版本号不对 → 停下，把输出发回来。
（例外：只有 `native_step3_events` 报 `-11` 可以继续，同时也发回来。）

**清理硬盘：** 旧的训练目录不再用了，可以删掉省空间（删前确认里面没有你想留的东西）：

```sh
rm -rf runs/5090-train4 runs/bench-micro
```

**建议（只要做一次）：** Windows 里 NVIDIA 控制面板 → 管理 3D 设置 → “CUDA - Sysmem Fallback Policy” 选 “Prefer No Sysmem Fallback”。这样显存不够会直接报错，不会悄悄变慢几倍（第三轮就是这样变慢的）。

---

## 第 2 步：测速（5090）

一行命令，自动把四种大小各测一遍：

```sh
for s in large medium small tiny; do python -m spire_rl.ppo --run runs/bench --size $s --machine 5090 --bench; done 2>&1 | tee bench-5090.txt
```

- 只测速，不训练，不存检查点。
- 测的时候开着任务管理器 → 性能 → GPU，看“共享 GPU 内存”有没有涨。

**要发回来的东西：** `bench-5090.txt`，以及“共享 GPU 内存有没有涨”。

---

## 第 3 步：小网络训练 12 小时（5090）

```sh
python -m spire_rl.ppo --run runs/5090-small --size small --machine 5090 --hours 11.5
```

- `--hours 11.5`：跑满 11.5 小时后，在当前这次更新做完时自动存盘退出，总共不会超过 12 小时。
- **中途要停：** 按一次 Ctrl-C，等它自己存完退出（大网络可能要十几分钟）。不要连按，不要直接关窗口。
- **断了想接着跑：** 原样再运行同一条命令，会从上次存盘的地方继续。`--run` 和 `--size` 必须和第一次一模一样。
- 看进度：另开一个窗口运行 `tail -f runs/5090-small/log.jsonl`，每次更新多一行。

**要发回来的东西：** `runs/5090-small/log.jsonl` 和 `runs/5090-small/sessions.jsonl`。如果崩溃了，再加上终端最后几十行。

---

## 第 4 步：大网络训练 12 小时（5090）

```sh
python -m spire_rl.ppo --run runs/5090-large --size large --machine 5090 --hours 11.5
```

用法和第 3 步一样。**要发回来的东西：** `runs/5090-large/log.jsonl` 和 `sessions.jsonl`。

---

## 第 5 步：评估（5090）

```sh
python -m spire_rl.evaluate --checkpoint runs/5090-small/ema.pt --workers 6
python -m spire_rl.evaluate --checkpoint runs/5090-large/ema.pt --workers 6
```

- 每个打 1,000 个固定种子，打印胜率、平均层数、到第二 / 三幕的局数。
- 结果同时存成 `ema.pt` 旁边的一个 JSON 文件。

**要发回来的东西：** 两次打印出来的结果。

---

## 第 6 步：A100

**第一次在 A100 上：**

```sh
nproc                                             # 能用几个 CPU
nvidia-smi --query-gpu=name,memory.total --format=csv   # 显卡型号和显存
pip install -e train                              # 只第一次需要
CXX=g++ python sim/build.py --test --jobs 8
python -m pytest -q train/tests
```

**测速**（把 `small` 换成第 3–5 步之后定下的那个大小）：

```sh
python -m spire_rl.ppo --run runs/bench --size small --machine a100 --bench 2>&1 | tee bench-a100.txt
```

**要发回来的东西：** `nproc` 和 `nvidia-smi` 的输出，以及 `bench-a100.txt`。看过测速再决定跑多久。

**训练**（第 6 步的测速看过以后再开始）：

```sh
python -m spire_rl.ppo --run runs/a100-small --size small --machine a100 --hours 11.5
```

- 如果 A100 是按作业限时的，`--hours` 要比作业时限少 1 小时左右。
- **从 5090 接着跑：** 把 5090 上整个 `runs/5090-small` 文件夹拷到 A100 的 `runs/` 下面，然后用 `--run runs/5090-small`、同样的 `--size` 启动即可。两边代码必须是同一个版本（第 1 步那个版本号相同）。

---

## 日志里看什么（`log.jsonl` 每次更新一行）

只看这几项就够了：

| 字段 | 意思 | 正常 | 要报告 |
|---|---|---|---|
| `floor_mean` | 平均打到第几层 | 慢慢往上涨 | 连续很多次一直往下掉 |
| `learn_s` | 这次训练花了几秒 | 每次差不多 | 越来越慢，或忽快忽慢 |
| `gpu_memory_gib.peak_reserved` | 显存最高用了多少 GB | 5090 上小于 21；A100 上小于显存总量 | 超过就是显存不够（见下面的问题表） |
| `entropy` | 策略有多随机 | 从约 1.6 慢慢降 | 突然掉到 0.3 以下 |
| `kl_stop` | 这次更新是不是被提前叫停 | 基本都是 false | 经常是 true |
| `value_ev_macro` | 价值函数对选牌、选路这类决策预测得准不准（1 最好） | 慢慢升到 0 以上 | 一直在 0 附近 |
| `reasons` | 每局是怎么结束的 | 只有 `died`，以后会有 `won` | 出现 `error` 或 `no_actions` |

---

## 出了问题怎么办

| 现象 | 怎么做 |
|---|---|
| 报 `out of memory` / OOM | 加上 `--micro 64`，用同样的命令重新运行（会从存盘处接着跑，不影响训练结果） |
| `peak_reserved` 超过显存总量，或者任务管理器里共享 GPU 内存在涨 | 同上，加 `--micro 64` |
| 报 `network config ... differs from the arguments` | `--size` 和这个目录第一次启动时不一样。看目录里的 `sessions.jsonl`，改回原来的 `--size` |
| 报 `observation version differs` | 代码版本改过，这个目录不能接着用。换一个新的 `--run` 目录 |
| 其他报错，或者程序卡住不动 | 按一次 Ctrl-C，把终端最后几十行发回来 |

---

## 附录：参数说明

**两个预设（一般只需要改这两个）：**

| `--size` | 网络 | 参数量 | 学习率 |
|---|---|---|---|
| `large` | 宽 768，12+12 层 | 218M | 3e-5（第 1–3 轮用的就是它） |
| `medium` | 宽 512，8+8 层 | 69M | 4.5e-5 |
| `small` | 宽 384，6+6 层 | 32M | 6e-5 |
| `tiny` | 宽 256，4+4 层 | 11M | 9e-5 |

学习率按宽度反比放大（3e-5 × 768 / 宽度）。这是常用的经验做法，没有专门调过。

| `--machine` | 采样进程 × 每进程局数 | `--micro` | `--micro-tokens` |
|---|---|---|---|
| `5090` | 6 × 16 | 128 | 16000 |
| `a100` | （CPU 数 − 2）× 32 | 256 | 32000 |

- `--machine` 里的设置只影响速度和显存，不影响训练结果。中途改了也可以接着跑。
- `--size` 决定网络本身，同一个目录里不能改。
- 命令里直接写的参数会覆盖预设，比如 `--size small --micro 64`。

**其他常用参数：**

| 参数 | 默认 | 说明 |
|---|---|---|
| `--run` | 必填 | 训练目录。存检查点（`latest.pt`、`ema.pt`）、日志（`log.jsonl`）和启动记录（`sessions.jsonl`） |
| `--hours` | 0（不限） | 这次启动跑多久后存盘退出 |
| `--workers` / `--games` | 见预设 | 采样进程数 / 每个进程同时开几局 |
| `--micro` | 见预设 | 训练时一次往显卡里送几行。只影响显存和速度 |
| `--micro-tokens` | 见预设 | 局面大时自动少放几行，防止后期显存不够 |
| `--ent-updates` | 3000 | 熵系数从 0.01 降到 0.001 用多少次更新。对比实验两边保持一样 |
| `--practice` | 0.4 | 练习战（只打单场战斗）占的局数比例 |
| `--bench` | — | 只测速 |

完整列表：`python -m spire_rl.ppo --help`。

**存盘：** 每 30 分钟和退出时覆盖保存，只有两份文件。

| 网络 | `latest.pt`（含优化器） | `ema.pt` |
|---|---|---|
| large | 约 3.5 GB | 约 0.9 GB |
| small | 约 0.5 GB | 约 0.13 GB |
