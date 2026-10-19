# 原生 C# MCTS 价值叶子（2026-10-19）

## 配置与语义

通用原生后端 `native-generic-collection-v1` 支持现有 ALL runner 的 `search.leaf_mode`／`--leaf-mode` 和 `search.value_mix`／`--value-mix`。默认仍为 `heuristic`，未启动正式训练。

| 模式 | 非终局估值 | 搜索推进 |
|---|---|---|
| `heuristic` | 现有 C# 手写评分 | 保留原 rollout 至终局或截断的行为 |
| `learned` | 同一采集模型的价值头 `V(s)` | 展开后在第一个完整决策叶子估值，不再做整场 rollout |
| `mixed` | `(1 - value_mix) × H(s) + value_mix × V(s)` | 与 learned 使用相同叶子边界 |

`value_mix` 是学习价值的权重，必须在 [0,1] 内。混合权重为 0/1 时对应同一叶子上的纯 H/V；`mixed=0` 与旧 heuristic 的 rollout 长度不同，不能声称两者完整搜索必然一致。所有模式的终局均优先使用原生真实胜负／HP 奖励，不调用价值网络，不混合终局奖励。单人任务不做双方视角的价值符号翻转。

当前保持真实根的网络策略先验、树内均匀先验；本次接入的是模拟叶子的价值，并非树内每个节点的策略网络。预算仍为毫秒，网络通信、编码和推理计入搜索预算。超时回复会被读完以保持通信对应关系，但不回传到访问次数；没有有效模拟时显式失败。非有限或超出 [-1,1] 的价值、未知模式、非法混合权重均失败。

## 分支状态及安全边界

`NativeMctsValueObservation` 从 `NativeMctsSimulationSession` 当前完整预测分支导出特征。生命、格挡、能量、牌堆、升级、费用、Power、金币、怪物意图来自模拟器、预测卡牌及分支 AI；动态目标类型使用模拟器的目标查询。意图伤害使用分支预测与镜像修正，不调用真实怪物的动态伤害委托。

价值推理仍使用现有驻留 Python 服务及同一个 checkpoint；只计算状态编码和值头，不伪造合法动作。动作 Key、隐藏抽牌顺序和 RNG 不进入网络。模型参数结构与原通用 Transformer 保持兼容。

挂起选择不是稳定价值叶子，搜索先完成选择再估值。每个普通真实根均对账真实／预测编码实体；每次叶子查询检查分支 continuation 不变，搜索前后检查真实根不变。搜索中新到达的终局不调用价值投影。当前价值投影明确拒绝同伴／球及多个独立攻击意图组；不能把这次小范围验证扩写为全部角色和机制支持。

同时修正了合法选择覆盖检查：C# 搜索会合并完全等价的重复卡牌实例，覆盖按完整语义状态键的多重集合核对，而非按卡名或选项序号；导出及实际执行仍保留选定实例和执行顺序。

## 数据、诊断及恢复

heuristic 保留 `root-prior-uniform-tree-rollout-v1`；learned/mixed 使用 `root-prior-uniform-tree-leaf-v1`。模式和混合权重写入作业、轨迹、来源摘要及回放兼容性；不同搜索配置不能悄悄复用旧缓存。旧 heuristic 轨迹仍可读取，旧 v1/v2 非通用后端行为保留。

每个决策记录 `valueCalls`、`valueSum`、`heuristicSum`、`evaluatedValueSum`、`leafBackups`、`terminalBackups`、`meanBackupDepth`。估值调用数包含在截止前发出、截止后才返回的调用；实际回传数只计有效模拟，`leafBackups + terminalBackups == simulations`。因此不能把 valueCalls 当作模拟次数。

学习者／冠军机制不变，仍采集最新学习者、独立验证决定冠军；完成整场的原子缓存与逐更新优化器／RNG 恢复保留。原生进程按单场有界启动，防止多场共享一个 120 秒进程预算造成额外失败。

## 有界验收

下列是单场工程检查示例，不是正式训练命令：

```powershell
.\.venv-az\Scripts\python.exe scripts/check_native_generic.py --out output/native_value_smoke --leaf-mode mixed --value-mix 0.5 --episodes 1 --skip-validation
```

本轮仅使用小规模工程场景和故障注入验证接线；不据此判断哪种模式更强。实际验收结果如下。

## 验收结果

130 项 Python 测试通过（129 项适配／旧路径回归及故障注入，另 1 项录制混合价值算术与权重隔离检查），C# ReplaySearch smoke 通过。C# 合同直接验证三模式能改变搜索选择、混合值精确回传、终局绕过网络、选牌完成后才估值、NaN 和超时回复被拒绝。

原生工程检查使用同一初始化权重及两份固定训练侧配方，每模式两场；另对 8 个冻结验证配方做纯网络验证与分支编码对账。共 14 场、223 个真实决策，零契约拒绝。下面仅证明实际接线生效；时间预算会使模拟数受机器负载影响，不用于强度或吞吐排名。

| 模式 | 轨迹行 | 完成模拟 | 叶子价值调用 | 非终局有效回传 | 终局回传 |
|---|---:|---:|---:|---:|---:|
| heuristic | 33 | 21,183 | 0 | 7 | 21,176 |
| learned | 67 | 16,743 | 10,773 | 10,745 | 5,998 |
| mixed，权重 0.5 | 32 | 13,065 | 6,329 | 6,309 | 6,756 |

混合样本通过两步工程更新，loss 有限；从第一步恢复后权重及更新历史与连续执行完全一致，冠军未改。实际缓存续跑复用全部 10 场，18 个缓存／checkpoint／日志文件内容及时间戳未变化。学习价值模式的 ALL runner 故障注入同时证明：第二轮采集使用最新学习者，更新中断后不重复采集，切换模式恢复被拒绝，未晋级时保留冠军。

产物：`output/native_leaf_heuristic_a_20261019/`、`output/native_leaf_learned_d_20261019/`、`output/native_leaf_mixed_a_20261019/`。混合目录的 `first-run-report.json` 保存工程更新记录，`resume-check.json` 保存续跑断言，`three-mode-audit.json` 汇总三模式。录制轨迹夹具位于 `tests/fixtures/native_leaf_{learned,mixed}_v1.json.gz`。没有启动正式训练或打开测试集。
