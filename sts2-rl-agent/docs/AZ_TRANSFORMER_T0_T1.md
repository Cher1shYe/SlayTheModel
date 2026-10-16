# spec_1 首个实施切片：T0 / T1

日期：2026-10-16。范围为 `spec_1.md` 第 11 节指定的首个最小可审计切片。
已实现 starter/Shrinker 的公开实体编码及 Transformer 核心；**不是全部 T0–T5 完成，也不是 G2.3e 全内容接入或策略质量通过**。
旧 MLP、奖励、课程、协调器和旧实验记录未修改。没有启动自对弈、smoke 或正式训练。

## 接口和版本

- `mechanic_registry.py`：经源码核对的 Strike、Defend、Bash，有序效果，Shrinker 公开行动周期，以及 Shrink/Vulnerable 的触发描述。没有内容 ID embedding，也没有文本效果执行器。
- `entity_encoder.py`：只接受 `InformationState`。全局、玩家、敌人、手牌实例和公开无序牌堆计数组；归属通过引用解析。手牌位置有语义，无序区域序号仅作引用，不进入数值输入。公开持久信息使用当前回合、敌人已行动次数、当前能力、已用决策数及预算等充分统计。
- `action_candidates.py`：动态 key、源/目标引用和原生执行编号映射；每次按当前状态重建并核对整个合法动作集合。网络中没有固定总动作分类层。
- `transformer_network.py`：局部有序机制 token 编码、Pre-LN/GELU/4d FFN、共享动作 cross-attention、统一合法 softmax、tanh 价值。动作不互相 attention；支持分块和混合长度 padding。没有推理缓存，避免训练权重更新后的缓存污染。
- `model_factory.py`：五档配置，原子 checkpoint，严格架构/config/schema/参数量校验。保存机制和内容版本、搜索禁用、夹具划分版本、代码摘要。当前恢复仅为权重恢复；optimizer/Replay/协调器恢复属于 T2。

完整 schema、配置、机制摘要、代码摘要和参数计数保存在 `transformer_t0_t1_audit.json`。机制的 `odd_enemy_turn` / `even_enemy_turn` 对应从零开始的已完成敌方回合数：0 首次施加 Shrink，1/3/... Chomp，2/4/... Stomp。原语语义及倍率已冻结；改变语义需更新注册表/schema。

Shrink 对 powered attack 乘 0.7，最终伤害向下取整；本切片固定 -1 表示持续到施加者死亡。Vulnerable 对 incoming powered attack 乘 1.5，敌方回合结束减一。仅在此范围内通过动态能力数值和所属实体的机制描述表达，不声称实现通用触发器 DSL。

## 支持与拒绝矩阵

| 范围 | engine | observation | action | network | belief/search | tests |
|---|---|---|---|---|---|---|
| 未升级 Strike/Defend/Bash | 已有 | 已有 | 新 key 映射已核对 | 已接入 | 旧粒子可用，新动态搜索未接入 | 行为、梯度与契约 |
| Shrinker、Shrink、Vulnerable | 已有 | 已有 | 已核对 | 已接入 | 同上 | 周期、倍率与持续时间 |
| G1/G2 扩展内容、升级、生成、复杂选择、Boss | 旧系统部分已有 | 旧系统部分已有 | 新接口拒绝 | 未接入 | 未接入 | 拒绝版本测试 |
| 未知卡/原语、悬空引用、重复 key、溢出 | 不宣称支持 | 明确失败 | 明确失败 | 明确失败 | 不自动回退 | 拒绝契约 |

本切片支持 3 个卡牌 ID、1 种遭遇；目标全集内容清单尚未冻结，**不报告全游戏支持率 100%**。内容仅限 `shrinker-starter-v1`、`az-combat-v1`、`win-loss-v1`，所有其他内容/奖励版本拒绝。network-only 是显式模式，不能直接拿该模型给旧 `plan_observable` 或旧训练器使用。

长度证明：starter 固定 10 张牌，无生成和消耗；每张最多产生一个实体，无序同类牌可合并；加全局/玩家/敌人，共最多 13 token。每张手牌至多一个合法目标，加结束回合，共最多 11 动作。局部效果最多 8，当前敌人周期加 Vulnerable 最多 5。超过长度不截断；公开编码失败保存到 `output/az_transformer_errors/`，仅含传入的公开信息。

CPU 为当前开发验证目标，XS 默认；S 为之后正式训练的候选。生产部署硬件和延迟 SLO 尚未冻结，不据本次单样本时序推导上线性能。

## 参数和资源

| 档位 | 精确参数数 | FP32 参数/梯度/Adam 基础字节（16×参数） | 验证 |
|---|---:|---:|---|
| XS | 1,029,666 | 16,474,656 | 真实 CPU 混合长度前后向及更新 |
| S | 5,587,234 | 89,395,744 | 真实 CPU 混合长度前后向及更新 |
| M | 16,049,698 | 256,795,168 | CPU 实例化/计数，meta 形状 |
| L | 41,081,122 | 657,297,952 | CPU 实例化/计数，meta 形状 |
| XL | 120,635,170 | 1,930,162,720 | CPU 实例化/计数，meta 形状 |

参数表应以同目录 JSON 的最新重跑结果为准。均在规格规划范围内。基础字节不含激活、输入、allocator、worker 或额外优化器临时张量。

`audit_az_transformer.py` 对 XS/S 各运行 128/256/512 token × 32/128/512 动作的九个合成梯度点，batch=1、CPU 单线程、FP32、动作分块32。这些输入有意绕过游戏 schema 上限，仅测网络扩展成本，不能当成已支持的长游戏状态。报告逐点输入张量字节、进程 RSS 和前后向时间；进程峰值是整个审计的累计峰值，不能归因于某一个模型。未测 GPU、并发采集、Replay、训练吞吐或 p95 SLO。

## 验证和复跑

在仓库根目录运行：

```powershell
.\.venv-az\Scripts\python.exe -m pytest tests/test_az_transformer.py tests/test_az_information.py -q
.\.venv-az\Scripts\python.exe scripts/audit_az_transformer.py
```

测试包括隐藏 RNG/牌序/实例 ID 不变性、无序实体/动作重排、分块梯度等价、混合长度与逐样本等价、非法/padding 零概率、原生动作执行对应、机制伤害、有限 loss/梯度/真实 Adam 更新、权重恢复、旧 MLP 加载及双向拒绝、错误诊断保存。公开状态夹具为固定 seed 的前三回合公开投影，已查看，只能用于契约测试，不能作为未见质量测试。

本次执行结果：上述两份测试文件合计 **19 passed（4.90s）**，包括新增 10 项及原公开信息 9 项。XS/S 合成前后向共 18 个测量点均为有限 loss 和梯度。测试更新是固定夹具上的一次 Adam 契约检查，不是自对弈训练或质量实验。

## 下一步

1. 完成 T0 剩余的 G2.3e 目标全集机制依赖审计和部署 SLO 冻结，并逐批扩大实体表达。不能把 starter 切片当作 180 场课程接入完成。
2. T2：紧凑 Replay、按 action_key 标签持久化、逐节点动态搜索、优化器及协调器恢复、内存/传输与串并行审计；复用现有协调器和结果工件契约。
3. 用户明确要求实验后，按 T3 冻结隔离配置并执行 XS 检查、S 两轮 smoke、双 seed 各三轮；不自动启动。
4. T4/T5 的复杂选择、组合留出、档位比较和质量实验仍未实施。
