# T4：自然后期课程、组合顺序诊断与留出冻结

日期：2026-10-17。**本次实现与诊断完成，未启动新训练；未宣称新的 network 效用增益。**

## 交付

| 项目 | 版本 / 工件 | 状态 |
|---|---|---|
| 自然后期课程 | `natural-late-course-v1` / `configs/az_transformer_t4_v1/natural_course.json` | 8 个真实晚期起点，完整合法前缀可恢复 |
| 后期采集格式 | `natural-late-suffix-v1` / `natural_course.py` | 采集、校验、采样及实体 learner 数据接口已实现；与旧 Replay 隔离 |
| 配方与留出 | `transformer-t4-combinations-v1` / `protocol.json` | 48 train / 256 validation / 24 未见组合 / 24 未见 ID |
| 搜索诊断 | `combo_diagnostic.py` / `docs/transformer_t4_preparation.json` | 两种顺序反事实；uniform 和两份冻结冠军，预算 8/32/128 |
| 验收入口 | `t4_protocol.network_gate` | 256 场整场 network V7 效用，复用 utility-only 门槛 |

这是当前已支持机制上的 T4 工程切片，不是全内容扩展或通用质量验收。未运行新留出集战斗；未用其结果挑选配方、超参或 checkpoint。

## 1. 自然后期课程

输入是上次审计发布的 4 条完整 train 见证。三条产生晚期起点，另一条只作为完整来源审计保留。共导出：第二形态 3、第三形态 2、Burn 手牌 2、Purity 状态牌选择 1。所有来源都从第一形态自然开始，没有强制击杀、编辑 HP、重排隐藏牌堆或篡改阶段。

每项保存原配方、来源内容摘要、完整动作 key 前缀、公开状态/历史、原始 limits、课程版本、奖励和用途。`restore` 重新实例化原始配方并逐步执行前缀；状态必须与快照完全一致且未终局，才返回可继续运行的 `ObservableCombatAdapter`。公开搜索仍只接收 `InformationState`。

重要语义：

- value 标签仍是 **原始整场 V7 终局效用**，H0 为原配方初始 HP；不会把晚期 HP 偷换成 H0。搜索 rollout 的 H0 仍按既有 V7 使用搜索根 HP。
- 原始累计回合与决策预算保留，不给晚期起点额外 400 步。后缀同时保存局部 `step_index` 和整场 `absolute_step`。
- `sample_entry` 固定为先均匀选来源轨迹，再均匀选不同前缀状态；同一状态的多个分类标签不会放大采样权重。采样可由外部 RNG 精确复现。
- `collect_suffix(entry, decide, model_version)` 使用外部动态策略生成完整后缀；记录编码、公开状态、动作 key、访问分布与 z。`validate_suffix` 重新回放并核对全量标签、动作、终局和预算。
- `training_rows(records, course, protocol)` 只接纳冻结课程中的后缀，检查组合/ID 隔离后提供现有 `Learner.update_entities` 所需字段。已有 T3 Replay 会拒绝这种独立后缀格式。
- 后缀评估一律标记 `late-diagnostic-only`，不能冒充从第一形态开始的 network 主指标。未来运行编排中的整场/后期混合比例、样本预算、落盘调度仍需在启动前冻结；本次未改写旧 T3 runner 或恢复旧实验。

课程内容摘要：`4c842565548869c8e72ba289ef3dcd161bbe3e511708dfc67a04e21609730887`。

## 2. 组合顺序与搜索诊断

两个反事实都来自同一条已确认能自然获胜的训练见证，重放相同前缀后分叉，且使用稳定动作 key 重新定位移动后的手牌；没有固定动作编号假设。

| 合法组合 | 正序伤害 | 反序伤害 | 两步结束后的其他关键状态 |
|---|---:|---:|---|
| Armaments+ → Body Slam+ | 5 | 0 | 两者均为 5 格挡、80 HP |
| Iron Wave+ → Body Slam+ | 14 | 7 | 两者均为 7 格挡、80 HP |

Armaments 正序两步 cutoff 效用 −0.103789，高于反序 −0.111289；Iron Wave 正序 +0.013398，高于反序 +0.002898。它们是局部搜索打分，不是整场 network 效用，也不能用来宣称模型晋级。

在第一组起点上固定搜索 seed 1729、原 `dynamic-risk-puct-v2`、不加训练噪声：

| prior | 8 simulations | 32 simulations | 128 simulations |
|---|---|---|---|
| uniform | Shrug，最大深度 1 | Armaments，深度 2 | Shrug，深度 3 |
| 冻结 seed 42 | Shrug，深度 1 | Shrug，深度 2 | Shrug，深度 3 |
| 冻结 seed 43 | **零格挡 Body Slam**，深度 2 | Shrug，深度 2 | Shrug，深度 3 |

uniform 与 seed 42 的 8 次模拟全部在深度 1 截断；seed 43 为 6/8 次。增加预算能让这个案例改变推荐并到达组合后续状态，但没有做整场效用预算比较，不能据此选定 32/128 为新训练预算。也不能因为另一个格挡抽牌动作被选择，就说搜索应当总选 Armaments。

证据保留每个根动作的 prior、visits、Q、每次模拟深度和 cutoff 结果。公开根状态前后摘要保持一致。未修改原搜索、奖励或模型参数；只新增独立诊断接口。

## 3. 合法配方与泛化留出

冻结范围是两类合法构筑（block / strength）、三种遭遇（Shrinker、Bygone Effigy、TestSubject）、HP 40/80，使用当前审计过的机制描述和配方验证器。训练组合按六种计数变体的前四种组成，后两种进入组合留出；验证使用训练组合但环境种子独立，补齐到原有 256 场配对口径。所有配方的 ID 和环境 seed 跨集合唯一。

组合签名只取 **遭遇＋排序后的卡牌 ID、升级与数量**；改 HP、seed、牌组顺序或 scenario 名称不能伪装成新组合。未见组合的签名不得出现在 train、validation 或自然后期来源配方中，其基础 ID 必须全部在 train 中出现。

完整 ID 留出选择 **BLUDGEON**：基础版与升级版都禁止进入 train/validation/自然后期状态。该卡仅使用已由 Strike 等训练卡描述的伤害原语；不同数值、费用是留出的参数变化，未引入未知机制。当前生成器中的派生卡只会来自已支持的既有机制，晚期公开牌堆也逐项检查 heldout ID。

这是未来**全新模型初始化、隔离 Replay**的协议。旧 V7 已见过 BLUDGEON，禁止作为这项 ID 泛化实验的初始化；本轮使用旧权重的搜索诊断仅针对已知训练见证，不能充当 ID 留出结果。未知机制仍显式拒绝，单独测试，不计入普通质量分数。

冻结协议摘要：`30a9c9f95927c70236a10c153fff7df183f8642f601e1cc211b2b5b7dd4434af`。准备脚本拒绝覆盖内容不同的既有冻结文件；改协议需新版本。256 个环境样本仍来自有限组合，不能当作 256 个独立构筑，也不构成通用质量样本量依据。

## 4. network 效用验收

`network_gate` 只接受冻结的 256 个 validation scenario 的配对整场结果，拒绝 search、后期快照、错误集合与缺失结果，调用既有 V7 严格终局事实校验和 `utility-only-v1` 晋级规则：network 平均效用差 bootstrap 95% 下界 > 0，并保持完整性/非法动作检查。胜率不参与否决或平局裁决。

本轮没有训练新的候选网络，因此 **network 学习增益状态是未评估，而非通过**。旧 Boss −1 的结论仍有效。未见组合与 ID 分组结果必须独立报告；后续独立质量研究还需按组合族/训练 seed 处理样本相关性，不把先导晋级 bootstrap 当作通用质量证明。

## 5. 校验与复现

必要测试 **822 passed，82.67 秒**，见 `docs/transformer_t4_tests.txt`；其中新增课程契约 19 项。覆盖自然恢复、篡改拒绝、后缀与旧 Replay 隔离、learner 批处理输入、可重复采样、组合和完整 ID 泄漏、未知机制拒绝，以及真实顺序反事实和搜索复现。既有 Boss 自然复活、粒子对齐、状态牌、Transformer 和 V7 奖励测试一并回归。

独立证据校验检查来源文件 SHA-256、课程重导出、冻结配方再生成、8 个起点恢复、两组组合反事实、uniform 的 8/32/128 搜索结果及代码版本绑定。脚本结果在 `docs/transformer_t4_verification.txt`。

```powershell
.\.venv-az\Scripts\python.exe scripts/prepare_az_t4.py
.\.venv-az\Scripts\python.exe scripts/verify_az_t4.py
.\.venv-az\Scripts\python.exe -m pytest -q tests/test_az_t4_course.py
```

准备脚本完整重跑需保留本地 V7 两份冻结冠军；独立校验与课程恢复只需仓库内见证。源码新增后 code digest 已变化，旧 T3 配置不可当作同版本恢复入口。

## 后续边界

本次交付了课程 API、采样/后缀数据接口、组合顺序证据和先导留出协议。启动训练前仍需把新 runner 的整场/后期混合比例、完整 Replay 存储策略、预算和预注册比较写入新版本配置；后续完整质量评价与更多机制族扩展属于 T4/T5 剩余工作。未经用户授权，不开始新 smoke、正式训练或扩大模型档位。
