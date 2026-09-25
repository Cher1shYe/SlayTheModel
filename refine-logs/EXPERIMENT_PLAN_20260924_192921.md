# 从树内 MCTS 到受控自进化：实验计划

日期：2026-09-24
范围：规划与只读检查；未修改算法、门禁或启动任务。
目标：先证明新一代模型能可靠产生、审计、训练、导出和评估，再证明新模型值得替换当前部署模型。保留 1,970 参数，不自动扩大模型。

## 证据与当前阻塞

本次直接读取的证据：
- C:/Users/15808/Desktop/github/sts2/artifacts/alphazero/m4-regression-20260924/evalfull-3seeds-report.json
- C:/Users/15808/Desktop/github/sts2/alphazero-combat/src/azcombat/experiments.py
- C:/Users/15808/Desktop/github/sts2/alphazero-combat/src/azcombat/promotion.py
- C:/Users/15808/Desktop/github/sts2/alphazero-combat/src/azcombat/training.py
- C:/Users/15808/Desktop/github/sts2/alphazero-combat/src/azcombat/export.py
- C:/Users/15808/Desktop/github/sts2/tools/Sts2.NativeWorker/CombatSolverMctsBenchmark.cs

未重跑用户已报告的 37 项 Python 测试、C# 测试或发布。这里只把它们视为用户提供的已有结果。

已检查报告只覆盖 CULTISTS_NORMAL、3 seed、每决策最多 50 simulations / 1000 ms、最多 20 父决策：
- pure MCTS：win、win、unresolved。
- post-mcts-rerank：loss、loss、loss。
- policy-value-tree-v1：loss、loss、loss；prior/value 各 1731 次，fallback 0。
这证明本报告中网络参与了搜索，不证明网络改善了战斗表现，更不是长期胜率估计。

源码中仍有端到端接口阻塞，必须先修复而不是直接扩大评估：
1. experiments.checked_model 仍只接受 azcombat.onnx.v1，当前 export.py 输出 azcombat.onnx.v4。
2. promotion.audit_wave 与 audit_bootstrap 仍要求 azcombat.checkpoint.v1，training.py 已保存/加载 v3。
3. experiments.run_wave 清除所有 STS2_ALPHAZERO_* 和 STS2_MCTS_EXPORT_*，但只重新设置模型路径，不设置树内 search mode 或 max simulations；外部环境设置会被清掉。
4. 50 次上限加每决策至少 1000 ms 的配置，按当前门禁分母最多约 50 simulations/s，不能拿它证明 >=100/s。搜索活跃耗时与真实决策墙钟应分开记录，但不能更换既有门禁分母以制造通过。
5. 当前晋级矩阵要求至少 3 个未见 seed、至少 2 个登记 encounter，不等于覆盖全部 5 个登记 encounter。报告必须明确验证范围。

## 主张与所需证据

| 主张 | 最小证据 | 对应实验 |
|---|---|---|
| C1：树内网络路径与采集/训练/评估接口端到端一致 | 真正新 ABI 模型通过全链路；实际模式、调用计数、合法性、provenance 一致；负例被拒绝 | B1 |
| C2：迭代产生可接受的新候选，而非只让 loss 下降 | 未见 seed 上配对比较、预先冻结预算与晋级规则；退化时保留旧模型；至少一次完整受控迭代 | B2–B5 |

不主张：隐藏状态公平搜索已完成、现模型强于纯 MCTS、进化必然单调变强、全卡池支持、100/s 已由低 cap 试验证明。
本项目保持“全知模拟搜索 + 受限观测网络”；隐藏状态采样作为独立后续方向，不混入本轮收益。

## B1：修复评估入口与最小端到端验收（必须）

- 不改已验证动作身份或放宽 schema。
- 统一版本常量和严格加载接口：ONNX v4、features v4、observation schema 3、checkpoint v3；旧格式继续明确拒绝。
- 波次 CLI 显式接受并记录 candidate searchMode / maxSimulations。baseline 必须纯 MCTS，candidate 必须显式树内；manifest 和实际 provenance 必须一致。
- 回归测试覆盖最新合法模型、旧模型拒载、错哈希/缺字段、模式设置、环境污染清除、固定模拟上限、fallback 和失败诊断、强制夹具拒绝进入训练/晋级。
- 先跑 2 seed × 1 encounter × full/mid × baseline/candidate = 8 条短轨迹，只证明入口可靠；不作为晋级。
- 再分别跑 PURITY、Burning Pact、CASCADE/PREPARED 和死亡结算语义回归。必须真的到达相应节点，不按 fixture 名字计覆盖。
- 强制父动作的 regressionOnly 文件可用于语义测试，不能混入正式性能评分或训练。若希望正式矩阵采用另一种可重复起点，需要先登记合法起点协议，而不是移除 regressionOnly。
- 输入变化前不重复重跑已有通过测试；使用完整 ExportRelease，保存新运行目录和程序集实际加载来源。
- 通过标准：新的合法模型能经现有 orchestration 到达真实树内运行和审计；不依赖手写命令绕过波次接口。
- 失败解释：管线未闭环，与模型强弱无关；停止扩大数据量。

## B2：候选诊断与训练前基线（必须）

保持 1,970 参数和奖励定义，先比较纯 MCTS 与 tree；rerank 仅保留为已有诊断，不作为第三条长期生产分支。
- 从报告中的差异状态检查 value 校准、prior 分配、结束回合选择、终局 value 优先级和单人视角；测试通过不等于实战有效。
- 固定模拟上限的配对试验用于机制比较；另外以相同墙钟预算运行无低 cap 的性能/质量评估。
- 每个真实决策至少 1 秒；实际模拟次数必须记录。若墙钟截断导致未达 cap，报告实际次数，不能声称完成固定工作量。
- 记录 win/loss/unresolved/error、非法动作、fallback、玩家 HP 变化、奖励、选择深度、模拟速率和 prior/value 实际计数。
- 胜利样本 HP 单独列出，同时报告全体 outcome/reward；不要因只保留幸存样本使战损看起来变好。
- 不把 3 个 seed 的差异作为确定结论；但优先处理 tree 明显退化的诊断，不假设更多评估本身能改善模型。

## B3：未晋级 bootstrap 与 candidate-1（必须）

本项目允许未晋级 bootstrap，但不允许未经晋级就启动 champion selfplay。二者必须明确区分。

示例首轮，所有数字为建议预算而非已有结果：
1. 冻结训练、验证、开发评估和最终留出 seed 清单。
2. 用当前 ABI 下纯 MCTS 采集冷启动教师数据；已有数据只有通过当前严格审计才能使用。
3. 采集预算示例：20 个训练 seed × 5 个登记 encounter × 2 个起点 = 200 个基础战斗任务。按实际完整战斗和有效决策数计数，不以 JSONL 行数冒充独立战斗数。
4. 保留全部胜/负结果和失败日志；已知强制夹具隔离。unresolved 单独标记和统计；不要伪装成真实终局。首轮训练可预先限定完整终局轨迹，必须报告被排除数量及原因，不静默过滤。
5. 以真实搜索访问分布作为 policy target，以最终真实轨迹 reward 作为 value target；不拿网络自己的输出当作已实现改进的标签。
6. 保持参数量训练 candidate-1，按 seed 切分验证；先做少量 batch overfit/张量与 mask 检查，再看验证误差。生成全新的 checkpoint/ONNX/manifest，旧产物不覆盖。
7. 完成 Python–ONNX–Native 数值对账和 choice ABI 回归，再进入 paired evaluation。

如果使用未晋级 tree 候选采集，也必须标记 candidate bootstrap；当前候选失利较多，建议先获得可用纯 MCTS 教师数据，避免只重复一种失败轨迹。此建议不构成新的 fallback 策略。

经验回放补充：
- 当前 training.train 在续训时拒绝任何旧 train/validation seed，因此“新数据+历史训练数据混合”现在不能直接运行。
- 如果后续需要 replay buffer，应区分新生成 seed 的唯一性检查和显式登记的旧训练样本重用；验证/评估数据永不入训。先加入来源、去重和 lineage 测试，再启用历史回放，不能简单删除防泄漏检查。
- 采集探索可先用不同训练 seed；再单独验证合法动作范围内访问分布温度采样/根先验噪声。评估关闭这类探索，模式写入 provenance。不要把扩充探索当作已实现功能。

## B4：M4 配对评估与第一代 champion（必须）

冻结规则后再运行，不因结果不好临时改门槛。
- 相同 seed、encounter、起点、牌组和预算配对；同 seed 不能保证动作分歧后的 RNG 消耗一一相同，因此保留足够独立 seed。
- 按当前 SCENARIOS：ordinary 2 起点，PURITY 1，CASCADE 1，death 1，共 5 个场景/起点组合。
- 全登记覆盖的技术验收示例：3 seed × 5 encounters × 5 组合 × 2 policies = 150 次运行（75 对）。仍是技术门禁规模，不是统计上充分的胜率证据。
- 若首轮技术验收通过，再用预先选定的 20 个以上未见 seed 扩展普通战斗质量评估；实际数量由配对差异波动与精度目标决定，20 不是通用充分阈值。
- 第一代与纯 MCTS 配对；后续代数还必须与当前 champion 配对，并继续以纯 MCTS 为锚点。当前编排 evaluate 仅运行 baseline/candidate，需要先实现并测试 champion 对手路径，不能声称它已具备。
- 汇总按 encounter、start、scenario 分层。强制死亡/选牌语义测试不能主导部署胜率得分。
- 保持现有 fail-closed：缺覆盖、unknown/非法动作、异常、fallback、unresolved 或预算/性能证据不合格，不得用跳过样本方式晋级。
- 本轮性能门槛仍使用现行实际墙钟口径；另报 active-search 吞吐，不替换 >=100/s 合同。
- 已有门禁做原始胜局/奖励不退化检查；正式长期自动晋级还应增加冻结的配对不退化/改进判断和不确定性报告。按独立 seed 分组，不将同一战斗的数十行当成几十个独立胜率样本。
- 通过才允许明确操作冠军别名；否则保留候选作研究，继续纯 MCTS 或原 champion。没有冠军时不能假造一个来解锁 selfplay。

## B5：第一轮正式自进化与持续运行（首次成功后）

受控顺序：
champion-0 冻结采集新训练 seed
→ 审计 JSONL 和模型/代码版本
→ 训练 candidate-1
→ 导出并做 Native 对账
→ 候选/冠军/纯 MCTS 配对评估
→ 通过后原子更新 champion-1；不通过保持 champion-0
→ 下一批全新训练 seed。

前置工程工作：
- 明确 champion selfplay 波次的严格训练审计入口；现有 --bootstrap-wave 只接受 bootstrap manifest，不应改写 manifest mode 冒充 bootstrap。
- 实现一代有界编排、持久化状态、阶段完成标记、失败后恢复、固定采集模型哈希、训练数据版本清单。
- 区分训练探索模式和无探索评估模式。
- 独立终验 holdout 不参与调参，评估 seed 不能回流训练；跨代使用全局登记表，防止反复挑 seed。
- 当没有足够合格完整轨迹、数据验证失败或候选劣化时，停止当前阶段并保留诊断。
- 不并行共享 artifacts/native-host 的发布目录和 stdout/stderr；要并行必须先隔离 worker 工作目录/用户目录/日志。此计划不启动并行任务。
- 首先人工监督完整一轮，再连续运行 2–3 轮有界闭环；每轮可产生新候选，不保证每轮都产生更强 champion。

## 执行顺序与停止条件

| 阶段 | 第一步 | 继续条件 | 成本估计 |
|---|---|---|---|
| M0 | 修 ABI/模式/预算传递并新增负例测试 | 合法最新模型真走树内，旧/错产物被拒绝 | 本地 CPU 编译和短任务；未实测 |
| M1 | 8 条接口 smoke 与选择/死亡语义 | 严格审计通过且无污染 | 秒/决策 + 发布启动成本 |
| M2 | 200 个训练任务的预算示例，必要时先分小批 | 足够完整合法轨迹，各类有覆盖 | 假设平均 30 决策且每决策恰好 1 秒，仅决策部分约 6000 秒，约 1.7 小时 |
| M3 | 训练/ONNX 对账 + 第一轮小配对 | 新模型有效且未明显退化 | 训练先测小批；不承诺 GPU/CPU 总时长 |
| M4 | 150 次全矩阵技术验收 + 独立质量评估 | fail-closed 审计和预定质量标准通过 | 同假设下 150 次仅决策部分约 4500 秒，约 1.25 小时；完整预算可能更高 |
| M5 | 首轮 champion 采集—训练—评估—条件替换 | 全环可恢复、无数据泄漏、失败不改冠军 | 至少一个采集周期加训练和评估 |

以上是预算模型，不是性能预测；30 决策/战斗尚未测定，选择层也是决策，发布、启动、重同步、终局结算、超过 1 秒的搜索及失败均额外计入。
无需立即购置 GPU；先测本地实际采集时间与小网络训练时间，再决定是否扩容。
禁止通过增大预算掩盖模拟语义错误；轨迹 cap 可为完整战斗单独设定，须提前固定并明确记录。

## 本轮没有做的事

没有提交/推送；没有修改代码或放宽门禁；没有启动训练、评估、selfplay 或创建 champion。
仅生成计划和 TODO 跟踪表。
未比较外部新算法；不重构 hidden-state sampling，不增加模型参数。

## 方法参考

Silver 等，Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm，arXiv:1712.01815。
此计划只借鉴“搜索生成 policy/真实结果标签—训练—再搜索”的循环；冠军晋级策略是本项目自己的安全部署设计，不宣称等同原始 AlphaZero 全部训练规则。

## 验收清单

- [ ] 波次与审计接受当前 ABI，并严格拒绝旧版本
- [ ] baseline/candidate 实际模式和预算匹配 manifest
- [ ] 选择/死亡/恢复回归、合法性、fallback 可独立审计
- [ ] 当前未晋级候选的退化原因已诊断
- [ ] 数据 lineage 与训练/验证/评估隔离
- [ ] candidate bootstrap 不等于 champion selfplay
- [ ] 首轮真实完整终局数据、训练、ONNX 对账完成
- [ ] 同预算候选/纯 MCTS 配对评估通过
- [ ] 100/s 性能验证不使用 50 次/秒人为上限
- [ ] 后续代数有 candidate/champion 对比与保留旧模型逻辑
- [ ] 一代有界运行可恢复后才启用连续自进化

