# Observable AlphaZero 性能与 M5 实验

## 固定工作负载测量

本机 16 逻辑 CPU，Python 3.12.14，PyTorch 2.14.1+cpu；每个 worker 只启用 1 个 PyTorch CPU 线程。固定随机网络、manifest 的前 16 个 train 场景、master seed 42、每次非强制决策 64 simulations、完整战斗与默认 episode 上限。每组先冷采样，再使用同一持久进程池温采样。1/4/8 worker 共用完全相同任务。

| Workers | 温采样耗时(s) | Sims/s | Decisions/s | Episodes/s | 决策 p95(s) | 进程树峰值 RSS(GiB) | 启动(s) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 24.326 | 736.7 | 13.65 | 0.658 | 0.1103 | 0.569 | 2.372 |
| 4 | 7.385 | 2426.4 | 44.95 | 2.166 | 0.1018 | 1.426 | 2.715 |
| 8 | 5.301 | 3380.2 | 62.62 | 3.018 | 0.1287 | 2.545 | 3.413 |

每组同为 332 个决策、17,920 次模拟、16 胜，串并行及冷／温两遍的完整样本标签摘要一致。4/8 worker 温吞吐分别约为 1 worker 的 3.29/4.59 倍。冷采样分别为 24.806/8.238/5.570 秒，包含首次 checkpoint 加载；启动握手单独报告。

完整采样耗时包括场景创建、网络调用、信息粒子搜索、真实动作执行、结果序列化和 IPC。p95 是 worker 内单次搜索耗时，不包含进程池排队等待。RSS 是每 20ms 采样的父子进程 RSS 总和，会重复计算共享页；并非物理内存独占量或精确连续峰值。16 场属于短测，不能当作长期稳定吞吐或不同网络／场景的性能保证。异常直接使 benchmark 失败，不丢弃后计算加速。

原始结果：[az_m5_benchmark.json](az_m5_benchmark.json)。不能与旧 rollout MCTS 的数字直接作同等强度速度比较。

## 独立组件 profiling

单独 cProfile 一场 64-simulation 自对弈，不混入上表性能数据：

| 组件 | 次数 | 累积秒数 |
|---|---:|---:|
| 粒子采样／重建 | 832 | 0.710 |
| 粒子状态推进 | 1644 | 0.963 |
| 网络 predict | 743 | 0.259 |
| 合法 mask | 2421 | 0.245 |
| 真实环境 step（含继承调用） | 32 | 0.024 |
| clone_state | 0 | 0 |

累积时间含子调用且彼此重叠，不可相加。正式粒子构造直接重建世界，所以 clone_state 为零。约 50 KB 的任务／结果 pickle 往返约 0.00040 秒，此项仅测序列化，不冒充管道传输或调度耗时。另测 20 次 batch=256 的学习更新约 0.590 秒；不包含协调器每步原子 checkpoint 开销。详情与 loss 记录见 [az_m5_profile.json](az_m5_profile.json)。当前没有证据需要集中式 GPU 推理服务器。

## 三 seed 实验（已结束，500 场调整范围）

用户选定每 seed 先做 2 轮完整训练，保持原 manifest，未根据最终测试结果修改难度或门槛：

- Seeds 42、43、44；8 workers；每轮 256 场采样、64 simulations、200 次 batch=256 更新。
- 每轮 512 个固定验证场景，网络直接决策和 256-simulation 搜索分别比较；晋级仍使用搜索效用差的 10,000 次成对 bootstrap。
- 全部三个 seed 训练完成后冻结 checkpoint，然后各用 500 个独立 test 场景比较初始／最终网络与同预算搜索。2026-10-09 用户明确同意从 2,000 降为 500；调整时最终测试尚未开始，固定选取原 manifest 中前 500 个 test 配方，不根据结果挑选。原计划及修改记录保存在运行目录。
- 随机合法、公开规则基线在这 500 个 test 场景上运行。旧 MCTS 只作为独立标注的 oracle 参考，在预先指定的 16 个 validation 场景上运行，256 simulations、rollout depth 40；不与 500 场 observable 结果混排。
- 预先固定学习验收为三个 seed 各自的网络和搜索成对 CI 下界均 > 0；没有增益也输出完整报告，不追加训练或改测试集。

并行评估以全局场景索引派生搜索 seed，经测试与串行逐场结果一致。每个完成场景原子缓存；缓存键绑定代码摘要、模型文件摘要、配方、预算与 RNG 设置，恢复不会重复计算已完成场景，损坏缓存报错。初始与最终 checkpoint 相同的情形复用完全相同的评估记录，其配对差应为零。

以短测近似外推：256 场采样约 85 秒／轮；评估预算为采样的四倍，完整验证和最终测试预期为数小时，实际取决于决策数、强制动作、模型与机器负载。此为成本估算，不是完成时限。

运行目录 `output/az_m5_experiment/` 包含冻结计划、代码／launcher 摘要、各 seed 的状态／checkpoint、评估缓存和进度。`progress.json` 已为 complete，三组 state 均为 done，最终 `report.json` 已生成。2026-10-09 已完成原始逐场结果、checkpoint 哈希、配对统计和置信区间复算。调整后的实验已结束，学习验收未达标；原 spec 的每 seed 至少 2,000 场测试要求仍未满足。

```powershell
.venv-az/Scripts/python.exe scripts/benchmark_alphazero_combat.py --output output/az_m5_benchmark
.venv-az/Scripts/python.exe scripts/profile_alphazero_combat.py --output output/az_m5_profile
# 新建或中断后恢复同一冻结实验；不要与仍在运行的实例同时启动
.venv-az/Scripts/python.exe -u scripts/run_alphazero_experiment.py --output output/az_m5_experiment --test-count 500
```

性能阶段相关回归为 108 passed、30 subtests passed。后续完成的实验结果与文件核对见 [AZ_EXPERIMENT_RESULTS.md](AZ_EXPERIMENT_RESULTS.md)。
