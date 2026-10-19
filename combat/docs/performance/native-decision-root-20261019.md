# 原生 MCTS 决策点快照复用（2026-10-19）

## 变更与所有权

NativeMctsSimulationSession 新增 CommitDecisionRoot：只有完成选择链的稳定预测状态可以成为下一次 RestoreRoot 的根。保存绝对 actionCount，保留最初捕获的奖励敌人集合和 frozen root；当前快照从 transient/persistent 集合移交给 root，其他快照释放。分支仍通过既有 Fork 隔离。未完成选择返回 false，worker 保留最近稳定根之后的 promotedPrefix；不复制挂起事务、不重新捕获 live 状态。

CombatSolverReplayEnvironment.Promote 成功提交后清空已执行前缀。reuseDecisionRoot 默认开启；关闭仅用于旧完整历史重放基准。未改预算、先验、价值模型或严格校验。原生异常依旧失败。

## 正确性证据

隔离副本构建成功。seed2000228 的18动作、seed37005 的8动作、seed2000291 的14动作使用 verifyDecisionRoot=true：每次 rollout Restore/Apply 都与完整历史重放参考比较完整 NativeMctsState（含合法动作）、ContinuationStateText 和 EnemyDamageFraction。实机特征、后继与终点严格校验继续启用。三个场景通过，覆盖生成牌费用历史、跨回合、普通/自动选牌、终局取消选择。

Python 五套回归测试103 passed，耗时56.46秒：test_native_feature_regression、test_az_native_generic、test_native_collection_cache、test_az_native_backend、test_az_native_leaf。没有把参考双跑耗时作为性能结果。

## 250ms 串行 ABBA

相同二进制切换 reuseDecisionRoot，A完整重放/B复用；顺序 A1、B1、B2、A2，每组运行上述三个固定场景。checkpoint=initial.pt，SHA256=012b363254bbb79f8e6d08e7f06d84d8c2581f21df661b15c2c75047c7622dc4；XS、CPU推理、mixed=0.5、预算250ms。benchmarkReplay 先正常搜索并记录 searchAction，再执行固定 diagnosticActions，使两组下一决策点一致。产物格式 native-diagnostic-replay-v1，不作为训练样本。

比较脚本断言两组每步 observation、实际动作、自动选择数、终局与HP相同，最终完整 continuation 相同，featureParity/successorParity 均为 true。排除唯一合法动作的强制步，34个搜索决策点，每组重复两次共68次计时。

| 场景 | A平均模拟次数 | B平均模拟次数 | A每决策平均深度 | B每决策平均深度 |
| --- | ---: | ---: | ---: | ---: |
| 历史/生成费用 | 27.79 | 53.79 | 2.257 | 2.344 |
| 终局选牌 | 36.14 | 66.29 | 2.540 | 2.637 |
| 回合选择器 | 24.62 | 61.27 | 2.088 | 2.215 |
| 总体 | 28.29 | 59.22 | 2.250 | 2.355 |

总体模拟次数2.09倍，但中位数仅26→36，增益不均匀，不能把均值当作每个决策保证值。平均恢复/重放94.66→5.12ms；Apply49.09→88.27ms；叶评估106.95→155.93ms。后两项是每决策总量，因完成更多模拟而增加，不表示单次变慢。当前主要耗时转到叶评估（约61%）和前向模拟（约35%）；叶评估包含编码/通信/CPU推理，未测试GPU收益。

深度是本决策点到完成回传的动作边数，包含选择边，不是回合数或最大深度。按决策等权仅提升约4.7%；按全部模拟加权反而2.297→2.168，因为浅终局分支可以更频繁完成。不能声称搜索深度翻倍、胜率提升或策略改善。本实验为单个无头worker，不能外推4 worker并发吞吐或可见Steam性能。实际平均计时254.57→254.65ms，250ms为请求预算，存在同步操作/截止处理超时余量，两组口径相同。

## 产物与复现

相对于工作区 Python 仓库，控制目录为 `output/az_native_ic138_w4_20261019_174426.control/`：

- `benchmark_decision_root.py verify --build`：隔离源码构建及历史场景参考对照，成功产物 `decision-root-benchmark/verify2/`。
- `compare_decision_root.py verify`：终局与选择器参考对照，产物 `verify-terminal/`、`verify-selector/`。
- `compare_decision_root.py benchmark clean`：最终串行计时，产物 `clean-{a1,b1,b2,a2}-{history,terminal,selector}/`，每项保存 job.json、worker.log、replay.json。
- `summarize_decision_root.py`：严格校验固定轨迹并写 `decision-root-benchmark/summary.json`。

脚本使用本地既有配置/fixture和固定路径；重新运行需使用新输出前缀（目录存在会失败），并对应调整汇总前缀。首轮不带 clean 的计时与pytest有重叠，已全部排除。最终 clean 轮没有并发pytest或训练任务。

本轮只在 `decision-root-benchmark/source/` 构建隔离原生DLL，未覆盖共享 artifacts。原训练的基线、296场训练缓存、验证缓存、initial.pt、update-000-0064.pt和state.json均保留；没有迁移identity或重启训练。实际训练在本轮测试前已因候选验证 batch-00051 root mismatch 退出，进度102/296，pending保留64次更新后的断点。该错误不属于本优化的通过结论；旧迁移脚本假设pending为空，不能直接用于此状态。
