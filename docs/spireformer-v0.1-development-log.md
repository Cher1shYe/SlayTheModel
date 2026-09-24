# SpireFormer v0.1 开发日志

日期：2026-09-24  
状态：第一版模型核心完成，游戏 worker/tensorizer 尚未接入

## 1. 这一版要解决什么

已有 MCTS 能在局内搜索，但它速度较慢，难以承担大规模整局自博弈；单独训练“局内模型”和“局外模型”又会在药水、生命、金币等跨战斗资源上产生目标冲突。因此 v0.1 的目标不是再造两个策略，而是建立一个统一模型：

```text
无序状态实体 ── Set Transformer ──┐
                                   ├─ 整局因果历史 ─ Decision Transformer
上一动作 + RTG + 全局 timestep ────┘
                                                │
当前合法动作集合 ── 实体交叉注意力 ─────────────┤
                                                ├─ 动态 policy logits
无 RTG 的同一历史 ──────────────────────────────┘
                                                └─ state value
```

统一轨迹可以自然表达：在普通战斗少掉几点血但保存药水，可能让后面的精英战和整局终局回报更高。这个权衡不再需要两个模型通过手写规则协调。

## 2. 参考实现调研

### Set Transformer

- 论文：https://arxiv.org/abs/1810.00825
- 官方代码：https://github.com/juho-lee/set_transformer
- 本次固定查看的 revision：`73432c640ac78140496d6738416c54d32c686d65`
- 上游核心是 `MAB / SAB / ISAB / PMA`，输入约定为 `[B,N,D]`，原代码没有本项目需要的 padding mask。

### Decision Transformer

- 论文：https://arxiv.org/abs/2106.01345
- 官方代码：https://github.com/kzl/decision-transformer
- 本次固定查看的 revision：`e2d82e68f330c00f763507b3b01d774740bee53f`
- 上游按 `(return-to-go, state, action)` 交错成因果序列；Gym 版本主要面向固定维度连续动作，不能直接表示杀戮尖塔动态变化的合法动作集合。

实现没有直接复制旧依赖栈。Set 模块改成现代 batch-first PyTorch 并加入严格 mask；时序模块使用 `torch.nn.TransformerEncoder`，不依赖旧版 `transformers/GPT2`。版权与 revision 记录在 `model/spireformer/THIRD_PARTY_NOTICES.md`。

## 3. SpireFormer v0.1 的结构

### 3.1 Set Encoder

每个决策点先被 tensorizer 表示成实体集合 `[N,F_entity]`。集合维度没有位置编码：交换抽牌堆卡牌、弃牌堆卡牌、遗物或候选节点的输入顺序，不应改变状态摘要。

实现组件：

- `MAB`：支持 query/key 双 mask 的多头注意力；
- `SAB`：小集合的完整自注意力；
- `ISAB`：用 inducing points 把大集合复杂度降为 `O(NM)`；
- `PMA`：用 learned seed 得到置换不变的状态摘要；
- `SetEncoder.forward_with_entities`：一次计算同时返回逐实体表示与 pooled state，避免重复跑 encoder。

全 padding 集合经过特殊处理，不会触发 all-masked softmax 的 NaN。公开 batch 用 `True=valid`，PyTorch padding mask 用 `True=padding`，转换只在模型边界发生。

### 3.2 Causal trajectory encoder

时序核心输入：

- 当前 set state embedding；
- 上一步实际执行的动作 embedding；
- 期望 return-to-go；
- 跨局内/局外单调递增的 global timestep；
- step validity mask。

`previous_action[t] = a_(t-1)` 会被移动到上一组的 A 槽，因此 `S_t` 能看见导致它的动作，同时因果 mask 保证更早决策看不到未来状态、动作或 RTG。

第一版沿用标准 `(R,S,A)` 表示的窗口边界取舍：如果训练窗口从一局中间硬截断，窗口第一个状态之前的动作不会进入序列。数据采样应多带一个历史 step，或在后续版本加入显式 prefix token。

### 3.3 一个模型处理局内与局外

`domain_ids` 只有两个值：`combat` 与 `outside_combat`。域 embedding 加入状态和动作表示，但底层参数全部共享。药水可以同时出现在状态实体里，并在可用时作为动态合法动作；其长期收益由同一个整局 return 监督。

### 3.4 动态合法动作评分

没有固定的 `Linear(D, num_all_cards)`。每个决策点由现有协议先枚举合法动作 `[A,F_action]`，再执行：

1. 动作 query 对当前实体表示做 cross-attention；
2. 时序 state context 与每个 action embedding 做 scaled dot product；
3. 额外 MLP 读取 `state / action / state*action` 交互；
4. 非法或 padding 动作强制设为 `-inf`。

因此动作列表重排时，logits 应按同样方式重排；新增卡、事件或地图节点不会改变输出层宽度。动作 ordinal、`action_id` 与 `state_fingerprint` 只用于输出映射和 stale-state 校验，默认不能作为特征，避免模型退化成“永远选第一个”。

### 3.5 Policy 与 value

Policy 可以学习两类目标：

- 成功执行动作的 one-hot 行为克隆目标；
- MCTS 根节点 visits 的软分布。

Value 使用 Smooth L1 回归归一化整局结果。一个容易遗漏的泄漏是：Decision Transformer 已经输入目标 RTG，如果直接从该 context 预测同一个 return，模型可以复制答案。v0.1 的 value path 因此复用同一 temporal core，但把 RTG 全部置零后再计算；这会增加一次 temporal forward，换取清楚、可测试的训练语义，后续再基于 profiling 优化。

## 4. 代码清单

- `model/spireformer/spireformer/set_transformer.py`：masked Set Transformer；
- `model/spireformer/spireformer/decision_transformer.py`：因果 `(R,S,A)` 时序主干；
- `model/spireformer/spireformer/model.py`：统一模型与动态动作头；
- `model/spireformer/spireformer/batch.py`：训练/推理 tensor 协议；
- `model/spireformer/spireformer/trajectory.py`：变长轨迹 collator；
- `model/spireformer/spireformer/losses.py`：hard/soft policy、value、entropy loss；
- `model/spireformer/spireformer/manifest.py`：checkpoint/tensor shard 兼容性 manifest；
- `model/spireformer/tests/`：集合置换、时序因果、动态动作、padding 与 loss 测试。

## 5. 与现有工程接口的关系

模型以后应消费过滤后的 `CombatDecisionPoint` 和 `OutsideCombatDecisionPoint`，不应消费 `NativeMctsRequest`。后者包含 checkpoint、replay prefix 与原生模拟状态，会破坏 no-SL 信息边界并让 Python worker 与 Godot 内部强耦合。

C# → Python 的下一层建议使用常驻异步 worker：请求携带原始 decision JSON、有界历史、target RTG、request ID 和 deadline；响应只返回动作槽位、logits、value 与模型 revision。C# 仍持有原始合法动作对象，并在执行前核对：

1. 响应中的 decision index / fingerprint 没有过期；
2. selected index 在当前合法动作范围内；
3. 冗余 action ID 或 descriptor digest 与该槽一致；
4. logits 数量正确且所有有效值有限。

模型永远不直接构造 Godot 原生动作。

## 6. 已确认的数据缺口

这版暂不伪造不存在的信息。真正开始训练前，协议仍需补：

- 战斗观察中的敌人 intent；
- 卡牌升级、附魔和动态变量；
- combat 与 outside 共用的 episode ID / global timestep；
- combat 成功执行记录、战斗/整局 terminal outcome；
- MCTS 根节点每个合法动作的 visits；
- MCTS 内部的二阶段选牌/选目标要升级成正式合法动作协议；
- 词表、归一化统计、tensorizer/reward version。

原始 JSON/JSONL 应作为长期 source of truth；`.pt` 或 Parquet 只做可重建 cache，并必须保存 `tensorizer_version + vocabulary_hash + reward_version`。

## 7. 测试准则

v0.1 的验收重点不是“随机权重是否会打牌”，而是结构语义：

- 实体重排不改变输出；
- 动作重排只重排对应 logits；
- 修改未来状态/动作/RTG 不改变过去输出；
- padding 内容不影响有效 step；
- 非法动作始终为 `-inf` 且不会被选择；
- value 不随输入 RTG 改变；
- 混合 combat/outside 的 batch 能 forward/backward；
- 软 MCTS target、one-hot target 和缺失 value label 都能正确 mask；
- manifest JSON round-trip 与 digest 稳定。

## 8. 本次验证结果

验证环境：Python 3.11.7、PyTorch 2.9.1、pytest 8.4.1、macOS CPU。5090/CUDA 尚未在这台机器上实测。

```text
34 passed
mypy: passed
black --check: passed
python compileall: passed (Python 3.14.6 syntax check)
git diff --check: passed
```

34 项包括 9 项 Set Transformer、10 项 Decision Transformer 和 15 项端到端/训练契约测试。集成测试实际发现并修复了非法动作 `-inf` 在 soft policy/entropy 反向传播中造成 NaN、空监督 batch 中 `0 * -inf` 造成 NaN、padding sentinel 越界以及 value target 非有限等问题。

参考配置 `entity_feature_dim=48, action_feature_dim=32, model_dim=128` 共 2,882,818 个可训练参数；这只是 v0.1 的容量基线，不是最终规模结论。

## 9. 下一阶段

1. 给现有 C# 协议补齐 episode/transition/terminal 事件与关键观察字段；
2. 定义稳定词表和 feature manifest，完成 golden JSON → tensor 测试；
3. 为 MCTS 输出 root visits，形成第一批 policy distillation 数据；
4. 实现常驻 Python inference worker，再开放 `spireformer` 启动策略；
5. 先让 tiny dataset 过拟合，再做整局离线训练和 headless 自博弈。

这一顺序保持现有局内/局外决策协议不变，同时让之后的无头模拟器、真人轨迹、MCTS 轨迹都能复用同一个模型输入层。
