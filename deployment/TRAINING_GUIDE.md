# 本地训练检查与使用说明

检查日期：2026-10-26。范围是 `D:\project\sts\sts-rl-agent`，不是 STS2 项目。

最终检查结果：上述 8 个并行入口在本地兼容副本上全部完成低预算冒烟，退出码均为 0，保存权重均为有限数值。日志和机器可读汇总位于 `deployment/training_audit_v3/summary.json`。自对弈产生 94 条样本，策略和价值权重都实际发生更新；本轮评测未超过起点，因此只检查了临时权重，没有新增 best checkpoint。这不是大规模稳定性或收敛验证。

## 启动方式

在 PowerShell 中执行：

```powershell
Set-Location D:\project\sts
# 先做一次小规模完整流程验证；输出目录必须不存在。
.\.venv\Scripts\python.exe -X utf8 deployment/train_local.py armg --smoke --out deployment/runs/armg_smoke_01

# ArmG：从零训练全部非战斗决策，战斗仍使用原生 MCTS。
.\.venv\Scripts\python.exe -X utf8 deployment/train_local.py armg --games 8000 --workers 4 --batch 32 --simulations 2000 --eval-every 400 --out deployment/runs/armg_8000_01

# BC：MCTS 生成战斗示范，再训练战斗策略。
.\.venv\Scripts\python.exe -X utf8 deployment/train_local.py bc --games 300 --epochs 8 --workers 4 --simulations 2000 --out deployment/runs/bc_300_01

# 价值函数：MCTS 生成战斗轨迹，战斗终局回报监督每个中间状态。
.\.venv\Scripts\python.exe -X utf8 deployment/train_local.py value --games 300 --epochs 15 --workers 4 --simulations 2000 --out deployment/runs/value_300_01
```

训练进度写入每个输出目录的 `train.log`；运行时另开 PowerShell 用 `Get-Content <完整日志路径> -Tail 20 -Wait` 查看。启动器退出时也会打印日志。

`--smoke` 固定为 2 局训练、2 个评测种子、2 workers、1 epoch/round、原生 MCTS 10 次模拟、PUCT 4 次模拟，覆盖命令行对应参数。它只能验证流程，不能证明效果。正式运行不加 `--smoke`，默认使用原项目 50 个评测种子。

## 各入口与目标

| pipeline | 学习内容 | 训练信号 | 起点 |
|---|---|---|---|
| armg | 所有非战斗决策 | 最终楼层 / 50，REINFORCE | 随机初始化 |
| arms | 仅奖励选卡 | 最终楼层 / 50，REINFORCE | 随机初始化 |
| bc | 战斗动作 MLP | MCTS 推荐动作，交叉熵 | 随机初始化 |
| attn | 战斗动作注意力网络 | MCTS 推荐动作，交叉熵 | 随机初始化 |
| value | 战斗状态价值 MLP | 战斗获胜指示 + 终局剩余 HP 比例，MSE | 随机初始化 |
| dagger | 战斗动作 MLP | 学生访问状态上的 MCTS 标签，聚合后重训 | 首轮 BC |
| rl | 战斗动作 MLP | 战斗获胜指示 + 终局剩余 HP 比例，REINFORCE | 发布的 BC 权重 |
| selfplay | 战斗策略与价值 | PUCT 访问分布 + 战斗终局回报 | 发布的 BC、价值、ArmG 权重 |

`attn` 使用与 `bc` 相同的参数形式。`rl` 使用与 `armg` 相同的参数形式。

DAgger 示例参数：`dagger --rounds 3 --games 150 --epochs 8 --workers 4`。
自对弈示例参数：`selfplay --rounds 12 --games 120 --epochs 4 --workers 4 --search-sims 100`。
这些是入口说明，不代表已经验证这些规模能提升成绩。selfplay 每轮有训练和评测，但没有完整可恢复的训练状态保存。

## 本地兼容处理

上游源码与发布权重保持不变。启动器把源文件、词表、种子及初始化权重复制到独立运行目录，在副本上：

1. 设置当前 `.pyd` 和源码搜索路径，显式使用 UTF-8。
2. 使用独立临时目录，避免多个训练共享同名临时权重。
3. 限制 OMP/MKL 每进程 1 线程，避免多进程叠加线程。
4. 将吞异常的战斗代码改为直接抛出异常。
5. BARRICADE 用 `has_status` 读取布尔状态，避免原生 `statusMap.at` 异常。
6. 拒绝把未结束战斗/整局作为正常样本或评测结果返回。
7. ArmS 的旧 dashboard `obs` 模块改为仅调用 `log_run` 时导入；并行训练不需要它。旧单进程 dashboard 入口仍不完整。

本机已补装 TensorBoard 2.21.0。PyTorch 是现有环境提供的 2.12.0+cpu；这些入口按 CPU 运行，没有完成 GPU 设备迁移。Python 使用 `.venv\Scripts\python.exe`。

## 结果位置与限制

每次输出目录包含源代码快照、`config.json`、`train.log`、`status.json`、训练曲线 `*track_local.jsonl`、`tb_armS/local` 和 `ckpts_local`。
注意目录根下也包含复制的发布权重；训练新输出以 `local` 标识，不能误把初始化权重当训练结果。

常规入口保存 `armG_model_local.pt`、`armS_model_local.pt` 或 `armB_model_local.pt`，并保存评测最佳 checkpoint。selfplay 只在超过初始最佳评测时写 `ckpts_local`；如果没有超过，更新后的临时策略和价值在 `tmp/sp_p.pt`、`tmp/sp_v.pt`，不是正式恢复 checkpoint。

所有入口都缺少完整的断点恢复机制：优化器、baseline、随机状态和 replay buffer 没有一起保存。不能用已有输出目录重复运行；启动器会拒绝覆盖。

战斗编码/动作区分不足、教师与学生观测差异仍然存在。价值训练日志中的 `val_mse` 实际是训练集 MSE；应以独立种子整局表现和价值排序能力判断效果。流程跑通不等于战斗网络已经解决此前的性能问题。

目前这里只做低预算冒烟；没有启动 8000 局等正式训练，也没有验证 Defect A20 分支、Steam 实机桥接或 STS2 的 PPO/GRPO 训练。
