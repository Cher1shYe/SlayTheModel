# MCTS 吞吐差异：原始日志与调用链诊断

日期：2026-09-24
范围：只读代码检查、现有 JSONL 指标重算和方案。未启动新游戏、构建、训练、M4 或 self-play；没有新增源码插桩，未取得新的 CPU trace。

## 结论

不能把当前 MCTS 概括为“只有 30–100 simulations/s”。同一份本阶段普通战斗 pure MCTS 原始轨迹中，前两个决策约 98/125 次每秒，随后已达到 1000–2600 次每秒。问题更准确地定位为开局首秒与部分复杂选择边界低于门槛，且旧基准和新选择夹具的工作负载不同。

外部文件夹的具体路径没有提供；本次找到的是仓库中与“约 1000/s”相符的历史基准，不能冒充已检查另一外部实现。

## 直接证据

原始数据：
C:/Users/15808/Desktop/github/sts2/artifacts/alphazero/m5-terminal-20260924/ordinary-baseline-045.jsonl

该轨迹 seed=M4-FINAL-ORDINARY-045，mode=pure-mcts，maxSimulations=null，每决策预算1000ms，最终胜利。

| 用户可读决策序号（从1开始） | 完成模拟次数 | 决策 elapsedMilliseconds | 重算 simulations/s |
|---|---:|---:|---:|
| 1 | 99 | 1009.8199 | 98.04 |
| 2 | 125 | 1000.9946 | 124.88 |
| 3 | 435 | 1015.3489 | 428.42 |
| 4 | 818 | 1000.2983 | 817.76 |
| 6 | 1006 | 1000.7140 | 1005.28 |
| 10 | 1876 | 1006.8514 | 1863.23 |
| 12 | 2659 | 1000.1880 | 2658.50 |

后期还有更高数字，但终局附近状态更简单，不宜拿来代表一般吞吐。以上不是同一根的重复测量，无法分离 JIT、缓存、状态复杂度与剩余 rollout 长度的贡献。

历史记录：
C:/Users/15808/Desktop/github/sts2/docs/combat-solver-mcts-backend.md
记录 CULTISTS_NORMAL 中位914.89/s，FUZZY_WURM_CRAWLER_WEAK 1404.45/s，KAISER_CRAB_BOSS 1521.84/s。设置为 maxDepth=200、一次预热、每遭遇五次5秒样本。该历史 benchmark.json 当前未在 native-host 找到；这些是历史文档数字，不是本轮重新实测。

## 调用链核实

AlphaZero 目录主要负责训练/编排/审计。pure MCTS 导出和游戏 worker 都调用：
C:/Users/15808/Desktop/github/sts2/src/SlayTheModel.Search/ReplayMcts.cs
以及：
C:/Users/15808/Desktop/github/sts2/tools/Sts2.NativeWorker/CombatSolverReplayEnvironment.cs

不是 Python 在解释执行每次战斗模拟。ReplayMcts 每次恢复环境，走树、扩展，并继续 rollout 到终局或深度200才回传。PolicyValueMcts 到未展开节点调用网络后直接回传 value，所以两者 completed simulations 的计算工作量不同；tree 更快不能单独证明底层模拟器变快或模型更强。这个差异不能拿来解释“旧 pure vs 新 pure”的全部差距。

## 已确认的重复成本与未确认占比

### 1. 冷进程/测试口径不同

旧 RunAsync 先热身1秒，再运行5秒样本。
新性能 probe 为独立进程，ordinary 只测第一个父决策；PURITY/CASCADE 测首个父决策及其选择层。
编译和资源启动不在 decision elapsedMilliseconds 中，但首次搜索仍可能承担尚未物化的 JIT/缓存路径。
需要同一冻结根的冷/热对照；不能仅以该假设抹除首秒未达100/s。

### 2. 恢复 promoted root 实际重放父动作前缀

CombatSolverReplayEnvironment.RestoreAsync（100行附近）先 active.RestoreRoot，再逐条 active.Apply(promotedPrefix)。
NativeMctsSimulationSession.RestoreRoot（85行附近）释放 pending/transient，回到初始 root。
因此选择层每次 rollout 都可能重新执行父卡及外层选择，并重新生成相关分支；不是从一个已保存的当前选择状态直接恢复。
这是当前搜索根内部的重放，不是重新创建游戏房间。

### 3. 选择动作是急切物化分支

CombatBeamSolver.NativeMcts.NativeMctsExpand（59行附近）通过
WithCardChoiceCheckpoint(..., branches).ToArray()
先收集解析后的选择分支，再由 NativeMctsSimulationSession 按 choice prefix 分组。
复杂嵌套会把多条兄弟后继的模拟/Fork/快照成本记到单次 Apply；实际分支数必须记录，不能把4096的上限误称为每次都生成4096条。
Rollout 最终只选一个分支，不能据此认为之前其他分支没有被生成。

### 4. 描述动作附带查询副本与威胁预测

NativeMctsPreparedPublicActions（264行附近）建立查询 Replay 副本、计算卡牌 Damage，并调用 ProjectHpAfterThreat，之后释放查询副本。
纯 MCTS rollout 确实使用 Damage/IncomingDamage 等字段进行动作选择，因此不能简单删除这些计算；可核查同一不可变状态内的重复计算和缓存机会。
这些成本需要计时才能确定占比，不应先断言是最大热点。

### 5. 选择观测与诊断物化

新增 choice frame 包含完整公开观测；嵌套前缀一致性检查会 JsonSerializer.Serialize 两份 frame。
该路径也被 pure 模拟访问。它是相较旧代码值得测量的成本增量，但目前没有 CPU/分配 trace 证明其占主导。
应保留完整语义校验，优先考虑同一不可变对象的惰性物化和结构化比较，不移除保护。

### 6. 额外的导出验证

导出器在 SearchRootAsync 后调用 VerifyObservationRestorationAsync，再记录门禁 elapsedMilliseconds；其中包含 sibling replay/观测校验。
保存的 elapsed 通常仅比1000ms多几到几十ms。这种表面分母差异本身不足以解释约10倍差距。
游戏 pure worker 保留 UCT 子树；导出器每个父根/选择根新建树。旧5秒 benchmark 也重新建树，只预热运行时，不能将全部差异归因于子树复用。
发布、启动和最终JSONL写入不在这些per-decision指标中，不能把慢速误归因为每次ExportRelease。

## 指标缺陷：不影响 sims/s，但应在分析前修正

performance_report.py 第29行将 audit_probe 返回的轨迹总 priorCalls/valueCalls 填入每个决策。
cascade-tree 原始 decisionMetrics 是：
- 普通根364/364；
- 第一层217/217；
- 第二层161/161。
总数742被汇总表重复写到三行，不能拿这三行相加。
本轮仅报告，没有修改脚本。

现有 CombatSolverReplayEnvironment.Transitions 只统计 ApplyAsync，不统计 RestoreAsync 内 active.Apply 的前缀重放。
WorkerServer 将同一 transitions 增量同时填入 StateTransitions 和 SimulatorForks，后者不是真正 Fork 计数。
下一次分段 profile 不能直接把这些字段当完整物理转移/Fork数。

## 下一步：先测，再优化，不扩大M4

### P0：同根可比较基准和低开销分段指标

使用同一个冻结checkpoint、seed、牌组、RNG、rollout策略、maxDepth=200、同一程序集/硬件：
- 普通首根、PURITY选择根、CASCADE第二层；
- 分别报告冷首秒、同进程预热后的新树1秒、预热后的新树5秒；
- 有意测子树保留时另立一个变体，不能混入运行时预热；
- 旧 benchmark 入口与 exporter 在同一根比较；
- 固定已完成rollout数量用于成本对照，超时/未完成模拟另计；一秒墙钟验证仍保留，不用5秒平均替代。

低开销记录（先聚合，不逐节点写日志）：
searchActiveMs、decisionWallMs、restoreMs、prefixReplayMs、applyMs、
choiceExpandMs、describeMs、observationMs、hashMs、validationMs、waitMs、
completed/aborted simulations、selected/rollout/prefix transitions、
resolved branches、真实Fork数、allocated bytes、GC次数/暂停、终局比例和平均/最大rollout深度。
计时明确嵌套范围，避免重复加总；未完成分支也记账。
选择一个进程级采样工具补齐CPU栈/分配证据；没有工具时先用可关闭阶段聚合器，不能杜撰热点百分比。

### P1：按证据优化，保留语义与质量

若冷启动主导：
- 独立测试fixture预热与持久worker；真实评估的首决策时延仍记录。
- 不预先把评估根的搜索结果当作免费初始化。

若前缀重放/选择展开主导：
- 优先安全保存/恢复当前已提升根的分支独占快照或已有纯数据选择continuation；
- 不能缓存一个后来已释放的SimulationSnapshot引用。
- 必要时再把选择链改为逐层产生候选、只物化当前选中分支；这属于语义改动，须验证完整choice key前缀、RNG、顺序、候选、completedSelections及兄弟隔离。
- 不截断合法选择、不合并不同父选择身份。

若重复描述/分配主导：
- 同一不可变根内复用动作描述/观测，明确失效与所有权；
- 诊断字符串只在需要时物化，严格异常证据仍保留；
- 不以禁用合法性或恢复检查换吞吐。

每轮只改一个因素，固定种子与同完成次数A/B对账动作、奖励及状态哈希，再测一秒门禁。若观察到运行时漂移，用预先设计的交错对照，不靠挑最快样本证明收益。
不要先降低maxDepth、换更偏置rollout、加启发式、减少候选或把tree leaf评估次数冒充完整pure rollout。

### P2：完成目标边界后再扩展

普通/单层/嵌套根均通过目标性能且无语义退化，才扩大未见seed质量样本与M4。
tree能达100/s只是速度证据；现候选同seed死亡而pure获胜，质量问题仍单独处理。
不创建champion、不启动正式self-play。

## 本次性能分析变更清单

| 文件 | 类型 | 内容 | 行 |
|---|---|---|---|
| C:/Users/15808/Desktop/github/sts2/profile_output/mcts-throughput-diagnosis-20260924-210134.md | 新建 | 现有日志/代码诊断与下一步测量计划 | 全文 |

未修改任何源代码或原始产物，没有需要回滚的源码插桩。本报告是独立诊断产物。

