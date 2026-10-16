# T3 专用运行编排与 smoke 证据

日期：2026-10-16。交付运行和审计代码；**本轮没有启动真实 smoke、正式训练或最终测试**，没有生成真实 smoke 通过证据。

## 入口与固定协议

`scripts/run_az_transformer_t3.py` 复用现有 Coordinator、Collector、EntityReplayBuffer、checkpoint 工厂和评估函数，不修改训练目标或奖励。准备方案更新为 `transformer-t3-preparation-v3`，仍使用 `configs/az_transformer_t3_v1`；仅更新启动前的准备版本，不迁移已运行任务。

- smoke：S 独立随机初始化，seed 42 两轮；180 场/轮、4 更新、batch 32、microbatch 8、4 simulations、256 场配对验证。
- formal：两个 S 独立随机初始化，seed 42/43 各三轮；轮间交错执行，180 场/轮、16 更新、batch 64、microbatch 8、8 simulations、256 场配对验证。
- CPU，2 workers，各 1 thread。沿用原子提交、有界采集和非活跃 Replay 内存释放。没有默认增加轮数、切换模型档位、自动缩减有效 batch 或转用历史 MLP 冠军。
- 晋级策略 `network-utility-v1` / 门槛 `utility-only-v1`。network 实际 V6 终局效用差的配对 bootstrap 95% 下界 > 0 才晋级；胜率不否决效用提升，search 不决定晋级。

## smoke 证据不是一个 passed 字段

正式运行在创建 Coordinator、模型或 Collector 前调用 `verify_smoke`，重新检查：

1. 准备目录全部配置、manifest 和各轮配方摘要与当前冻结方案一致；绑定代码、schema、运行脚本、准备脚本以及 Python/Torch/NumPy 版本。
2. smoke 确实为两轮完成，固定 S 配置、独立初始化、未发生记录的异常；不接受最终测试已访问的 evidence。
3. 恰好 360 个已提交训练 episode，逐场读取压缩 Replay、校验摘要、公开输入、动态标签和 V6 终局结算，检查场景/轮次/job 与使用的冠军版本。
4. 每轮候选更新次数完整且历史数值有限；训练边界与候选权重一致，optimizer 状态有限，最后一次训练绑定正确 Replay manifest。
5. 从每轮 256 场 network/search 原始结果重新计算分层摘要和效用门槛；验证配方、版本和完整性，复算冠军选择链与 checkpoint 哈希。
6. 比对 evidence 中的底层工件摘要、资源与阶段耗时记录；拒绝缺失、修改、过期、失败或其他环境的证据。

这检查工件自洽性和完成契约，不把工程 smoke 称为学习增益。即使 smoke 零晋级，也可以工程通过；异常、非法动作、缺失工件或错误复算不能通过。

## 恢复与失败

run.json、模型冻结和结果文件按内容冻结；已存在文件不同则拒绝覆盖。外层 RunLock 和每 seed Coordinator 锁防止并发写入，所有句柄在退出时关闭。

进程被直接终止、尚未留下错误标记时，可从既有 Coordinator 的原子边界恢复；已完成轮不重复训练，已有评估缓存复用。捕获到异常（含中断）会记录 error.json 并标记失败轮，停止且不发放证据；失败目录保留，修复后应使用新目录。此规则避免把经历错误的 smoke 冒充完整干净运行。

完成的 smoke 再调用入口只复核工件并返回既有证据。完成的正式运行可重新复算最终评估和结果；不能更换冻结的冠军或配方。运行目录、准备目录和来源 smoke 目录必须彼此隔离。

## 最终评估顺序

两个 seed 的全部轮次完成且训练工件审计通过后，先原子冻结 `frozen_final_models.json` 中双方初始/冠军路径及哈希，然后才生成 master 287 的 216 个最终配方并写入 `test-manifest.json`。

对每个 seed 的初始模型与最终冠军分别运行 network/search，保存原始配对结果、摘要、分层指标和效用差门槛。最终 `learning_gain` 要求两个 seed 的 **network** 效用差均通过；search 只观察。`engineering` 与 `learning_gain` 分开记录，通用质量验收固定标为 `not_claimed`。该集合是既有分布的新环境种子，不是未见组合/ID 质量证据；小分层 bootstrap 不据此宣称通用统计显著性。

## 工件与资源

- `run.json`：完整运行绑定和来源 smoke evidence 哈希。
- `progress.json`、`timings.json`：seed、轮次、阶段与实际阶段耗时。
- `resources.json`：累积活跃运行时间、200 ms 采样的进程树 RSS 峰值；共享页可能重复计入，不等同显存/精确瞬时峰值。恢复时保留已有峰值和累计时间。
- `smoke_evidence.json`：只在真实两轮通过底层审计后生成，包含训练决策数与活跃时间吞吐（包含验证和审计开销，不是纯采集速度）。
- 每 seed 审计：逐轮晋级、network/search 门槛、决策数、最大实体/动作数、Boss 阶段、timeout episode 列表及工件哈希。timeout 保留原始 Replay，正常计入效用。
- `frozen_final_models.json`、`test-<seed>-<mode>.json`、`report.json`：联合冠军冻结与最终评估结果。

## 用法（仅供之后明确授权实验时执行）

```powershell
# 只加载并校验已有 smoke 工件，不采集或训练
.\.venv-az\Scripts\python.exe scripts/run_az_transformer_t3.py verify-smoke --smoke-evidence output/T3-smoke/smoke_evidence.json

# 以下两条会启动实验；本次没有执行
.\.venv-az\Scripts\python.exe scripts/run_az_transformer_t3.py smoke --output output/T3-smoke --start-experiment
.\.venv-az\Scripts\python.exe scripts/run_az_transformer_t3.py formal --output output/T3-formal --smoke-evidence output/T3-smoke/smoke_evidence.json --start-experiment
```

没有默认运行模式；smoke/formal 缺少 `--start-experiment` 或 output 即退出。正式运行不能跳过证据复核。`--help` 和 `verify-smoke` 不启动实验。

## 测试边界

`tests/test_az_transformer_t3_runner.py` 使用假的 Coordinator/Collector 测试编排，使用明确标注的合成工件隔离测试审计器；真实模型/Replay/恢复行为由 T2、G2.3e 等微型契约测试覆盖。专项测试不算一次真实 S smoke，也不能作为正式训练所需 evidence。

覆盖无参数不启动、缺少证据拒绝、代码/runtime/资源/工件篡改、更新缺失、错误冠军、采集/有效 batch 预算不符、失败停止、部分轮恢复、完成后幂等、双 seed 交错、联合冻结在前、最终配方生成在后、network 效用门槛及 search 不参与验收。

完整回归 **318 项通过，71.77 秒**，原始结果见 `transformer_t3_runner_tests.txt`。命令：

```powershell
.\.venv-az\Scripts\python.exe -m pytest tests/test_az_transformer_t3_runner.py tests/test_az_transformer_t3_preparation.py tests/test_az_network_utility_gate.py tests/test_az_transformer_t2.py tests/test_az_transformer_g23e.py tests/test_az_resume.py tests/test_az_collection_backpressure.py -q
```
