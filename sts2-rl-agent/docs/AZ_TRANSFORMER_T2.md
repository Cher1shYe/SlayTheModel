# Transformer T2：Replay、动态搜索和恢复

日期：2026-10-16。实现范围延续 T0/T1 的 starter 三卡与 Shrinker 白名单，奖励仍为 `win-loss-v1`。本次完成该范围内的 T2 工程接入；没有运行 S smoke、正式训练、冠军选型或独立质量测试。G2.3e 全内容及 180 场课程仍需机制表达扩展，不能由此报告视作已接通。

## 实现

### 动态搜索

`dynamic_search.py` 实现 `dynamic-key-puct-v1`：每个公开信息节点重新构造候选 key 表，节点边以 key 索引，粒子每一步通过当前节点的映射调用原引擎。根节点与后续节点不需要相同候选数或 key。复用既有 `ActionEdge`、`OutcomeNode` 和 `BeliefSampler`，保留逐模拟独立根粒子、沿路径复用粒子、全程恢复卡牌 ID 分配器的边界。

排序后的稳定 key 决定 tie-break 与 Dirichlet 噪声对应关系，因此候选枚举重排不改变搜索结果。零访问 Q 从 0 开始；最终访问数打平时以 prior 和稳定 key 决定，不冒称与旧编号 tie-break 完全相同。本次搜索语义有独立版本，不把新旧访问标签直接混用。

当前逐棵树执行，未增加异步跨树批处理或共享推理缓存。模型本身已有混合长度 batch；训练使用稳定长度排序和动态 padding。并行采集任务保留现有确定性 seed 派生与有界提交窗口。

### Replay

`EntityReplayBuffer` 继承现有 `ReplayBuffer` 的 FIFO 整场容量、原子 manifest 提交点、幂等重复提交、分层采样和内存释放。旧类只增加可覆盖的读写/摘要方法，既有 JSON Replay 行为保持。

新版本 `typed-entity-replay-v1` 保存：

- 实体数值为显式 little-endian float64 字节编码，机制/实体类别及关系引用紧凑存储；保留精确公开投影，训练时转为 float32。
- 策略、访问数与执行动作以动态 key 存储，不展开 115/4096 维动作数组。
- 逐决策公开审计投影及摘要；派生的旧 legal mask 不持久化，重建时从公开手牌/费用还原。
- 完整终态公开信息与原奖励结算，逐场 gzip 压缩写入；重载复验版本、摘要、公开投影重建特征和标签。

非训练 split、不完整场、错误动作/标签、冲突重复、未知版本、损坏文件和容量不足明确报错。写入场文件后、manifest 提交前中断只留下不活跃孤立文件，恢复不会把它视为已提交。采样保持原家庭→场→决策采样语义，没有通过排除长场或改采样概率节省内存。

当前审计投影与训练特征同场压缩存放，以摘要关联；尚未把长期原始审计归档到独立冷存储。小夹具测量不能证明大规模 Replay 的生产内存上限。

### 训练与恢复

通过 `model_io.py` 在协调器/worker 边界明确分派 MLP 与 Transformer；旧 MLP 专用 checkpoint loader 仍拒绝 Transformer。Transformer checkpoint 保存精确架构、schema、机制/内容/奖励/搜索版本、运行配置和参数量。

复用 `Learner`、`Coordinator.save_training/restore_training`、`CollectionJob`、`Collector` 和配对评估/晋级规则。恢复包括模型、AdamW 状态、更新计数、NumPy/Torch/Python RNG、Replay manifest 哈希、代码和 Torch 版本。下一批采样及下一次更新有精确等价测试；Replay 更改后拒绝恢复。

`microbatch_size` 只影响训练内存，每个状态权重仍为 1/有效 batch，梯度累积后裁剪一次、更新一次。学习率与 AdamW 沿用既有默认。OOM 不被吞掉，也不自行缩小有效 batch。没有旧 Replay 自动转换或 MLP 蒸馏。

原训练入口 `scripts/train_alphazero_combat.py` 可读取新增 `TrainingConfig.model_tier` 和 `microbatch_size`。默认仍为旧 MLP；选择 Transformer 必须同时显式设置 `search_version="dynamic-key-puct-v1"`，且内容/奖励符合 starter 白名单。不提供可误启动正式实验的本次运行配置。

## 工程验证

完整命令及输出见 `transformer_t2_tests.txt`。测试范围：

最终结果：**62 passed in 29.99s**，8 份测试文件全部通过。其中新增 T2 测试 10 项。

- T1 编码/动态策略/五档模型契约，隐藏 RNG 与牌序不变性；旧公开状态回归。
- 不同节点拥有不同动作数量与 key；候选枚举重排不改变策略标签；粒子与原环境隔离。
- 原生动作与奖励对齐，完整自然战斗终局入库，超时短夹具保留并标记 `time_limit`。
- 紧凑存储往返、审计重建、FIFO 淘汰、内存释放后重载、幂等提交、manifest 中断与损坏拒绝。
- microbatch 梯度等价、下一批及下一次 AdamW 更新精确恢复、Replay 变更拒绝恢复。
- 串行/多进程采集标签一致；串行/并行评估及缓存一致；现有协调器 collect/train/evaluate/finalize 的小夹具恢复闭环。
- 旧 MLP Replay、恢复、搜索版本、并行评估与采集背压回归。

测试中的少量更新及限步场景仅为用户授权的工程验证，结果不用于质量结论。没有运行实验脚本、三轮训练或定时任务。

## 资源实测

`scripts/audit_az_transformer_t2.py` 的固定夹具：XS、CPU 单线程、四个环境决策、每步两次搜索模拟、一个 batch4/microbatch2 更新。原始结果在 `transformer_t2_audit.json`，包含当前 schema 与代码摘要。

本次一场压缩数据 2,264 字节，平均 **566 字节/决策**（包括公开审计和终态，未把共享 manifest/checkpoint 摊入）。载入约 2.50 ms，采样四条约 0.18 ms，四条状态的一次更新约 28.54 ms。这是一次极小夹具测量，不能外推正式吞吐、峰值 Replay 内存或部署延迟。进程 RSS/峰值另列，包含 Torch、模型和 allocator；释放 Python Replay 对象不保证操作系统 RSS 立即降低。

## 支持状态与下一步

starter 三卡/Shrinker 的 engine、observation、action、network、belief/search、Replay、update/resume 均有本次行为测试。未知内容继续拒绝。T1 文档与审计文件保留为原阶段记录；T2 schema 摘要因显式启用动态搜索而变化，原 T1 权重需重新初始化，不能静默忽略摘要差异加载。

下一步先扩大 G2.3e 对齐内容的机制覆盖并冻结目标配方/资源配置，再按用户单独授权开展 T3。当前不能直接在新模型上运行旧 Boss 180 场课程，也不宣称通用质量验收通过。
