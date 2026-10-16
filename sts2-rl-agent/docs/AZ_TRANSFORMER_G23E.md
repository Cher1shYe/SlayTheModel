# Transformer 扩展至 G2.3e

日期：2026-10-16。依据 `spec_1.md` 完成既有内容的机制、实体、动作、搜索与 Replay 接口扩展。本次没有启动 smoke、正式训练、晋级或最终保留集评估；微型优化器更新仅用于恢复契约测试。

## 范围和版本

| 项目 | 当前契约 |
|---|---|
| 内容 | `g2-boss-v1`，继承 G2.3e 全部既有机制；保留 starter 接口 |
| 奖励 | 原有 `finite-primary-phases-v6`，没有改分 |
| 课程 | `boss-search-course-v1`，没有修改配方、分层采样或 seed 划分 |
| 机制 | `g23e-mechanics-v2` |
| 网络 | `mechanic-entity-transformer-v2` |
| 实体 / 动作 | `public-entities-g23e-v3` / `dynamic-actions-v2` |
| Replay | `typed-entity-replay-v2` |
| 搜索 | `dynamic-key-puct-v1`，逐节点候选重建，沿用粒子与 PUCT 契约 |

明确支持 33 个基础卡牌 ID、63 个含升级的卡牌变体、10 种遭遇和 10 种怪物实体（包含召唤的 Eye）。完整逐项清单、结构化描述、六列支持矩阵与摘要见 `transformer_g23e_audit.json`。支持率分母仅为此冻结内容；不代表全游戏。旧的中间内容版本不自动转换为新实体 Replay。旧 MLP 和此前 Transformer schema 的 checkpoint 不可混装。

## 机制与公开状态

`expanded_mechanics.py` 明确登记原生工厂和效果函数对应的操作；校验每张牌的 effect_vars、关键词、费用及依赖。ID 用于注册查找和审计，不进入模型 embedding。支持有序效果、升级、X 费、多段、按格挡/消耗堆计伤、攻击次数降费、选择/随机消耗、升级手牌、置顶、生成、变形、保留与状态牌。

操作结构的约定：

- `condition` 描述该效果入口的条件；Restlessness 的 `hand_empty` 在整段效果开始时求值，不能在抽牌后重新判断能量效果。
- `damage_per_exhaust` 的 amount 为基础伤害，coefficient 为每张消耗牌增量；`hits_per_claw` 的 hits 为初始段数，coefficient 乘已完成 claw 次数，伤害 amount 不随次数增加。
- `stage` 划分有序程序段；`next_stage` 和 `random_branch` 引用程序段位置，后者 coefficient 是公开转移概率。位置不代表怪物 ID。
- Boss 的第 7 段是复活等待后的动作。`phase0/phase1` 均相对于该段入口阶段，`advance_phase` 在效果结束后生效。`clear_form_powers` 表示死亡时清理格挡、Strength、Vulnerable、Enrage 等非持久状态，保留该阶段原生死亡保留能力；后续阶段能力由有限形态规则切换。
- `finite_forms` 与复活段共同表达 100/200/300 HP；阶段三永久死亡。Illusion 表达清除 debuff、等待复活期间不可命中；Minion 不阻止主敌人死亡后的胜利。

实体编码包括临时费用、公开牌顶/底位置、待选择牌及对象、已选集合、支付记录摘要、攻击/完成出牌计数、敌人稳定槽位、主从关系、复活状态、当前意图及公开阶段、Boss claw 次数和剩余形态 HP。无序弃牌位置不作为数值特征，仍保留逐张引用供 Headbutt 使用。未知抽牌区按公开等价多重集合并。

这些摘要服务当前冻结机制：Stomp 从本回合攻击记录恢复，Slow 从已完成出牌数恢复；变形/生成/升级及牌顶底由既有公开历史审计。原始公开事件仍保存在审计记录中，供粒子重建和输入复算使用。模型不接收世界对象、环境 seed、隐藏 RNG、未知抽牌顺序或全局实例整数。

## 动态动作与搜索

动作类型包括 `end_turn`、`play`、`choose`、`choose_set`、`confirm_choice`。动作编码读取源实体、目标实体集合和选择集合；集合求和聚合保留基数、消除枚举顺序影响。动作分块后统一 softmax。

Purity 最多 9 个可选对象，完整子集空间最多 512，继续使用一次原子选择；没有新增选择微动作，也没有改变环境决策步数或奖励预算。单选、双敌目标及全体伤害都按当前状态建立 key 与原生执行索引的双向对应。4096 仅存在于既有引擎边界；网络、搜索树和策略标签没有固定 4096 输出。

每个搜索节点重新编码候选并按稳定 key 建边；重建复用原有 `BeliefSampler`，包含暂停选择续接、随机意图、Eye 复活、Boss 后续阶段。显式配置为 G2.3e + V6 + Transformer 档位 + 动态搜索才可使用，不静默降级到旧 MLP。

## Replay、恢复和长度

紧凑 Replay 保存机制枚举、数值、引用和 keyed 标签；公开审计中的合法动作保存稀疏索引。加载时重建 `InformationState` 和实体输入，验证摘要、标签和终局 V6 结算。复用逐场原子提交、FIFO、内存释放、有界 worker 与 checkpoint/RNG/optimizer 恢复。

由既有最大 100 回合 / 400 决策、20 张初始牌及生成/状态牌保守界，最多 2145 张牌；schema 上限 2161 实体、2146 动作、每实体 64 操作。超过边界报错并输出公开诊断，禁止截断。

长度测试包含 514 实体 / 512 单选候选的 XS 前向，以及 2161 实体的 schema/Replay 往返与超限拒绝。后者不是最大长度全档吞吐承诺。180 个训练配方的固定随机轨迹共 3039 个决策，观测到最多 26 实体、219 动作；紧凑特征 JSON 平均约 10.2 KB/决策，最大 28,178 字节，不含公开审计且未 gzip，不能等同总 Replay 内存。

## 参数和测试

五档均实际在 CPU 实例化计数：

| 档位 | 参数量 | FP32 参数+梯度+Adam 两状态基础字节 |
|---|---:|---:|
| XS | 1,059,554 | 16,952,864 |
| S | 5,671,522 | 90,744,352 |
| M | 16,221,154 | 259,538,464 |
| L | 41,372,514 | 661,960,224 |
| XL | 121,264,738 | 1,940,235,808 |

上述内存不含激活、输入、临时计算与并发进程。XS/S 检查真实混合长度批次与串行、分块一致性；M/L/XL 只完成实例化计数及既有 meta 形状检查。原 T0/T1、T2 报告保留为历史版本，不能用于当前参数量或 schema 的兼容判断。

运行命令（项目目录内）：

```powershell
.\.venv-az\Scripts\python.exe -m pytest tests/test_az_transformer.py tests/test_az_transformer_t2.py tests/test_az_transformer_g23e.py tests/test_az_boss_reconstruction.py tests/test_az_boss_natural_revival.py tests/test_az_boss_cards.py tests/test_az_choice_sets.py tests/test_az_morph.py tests/test_az_summon.py tests/test_az_collection_backpressure.py tests/test_az_resume.py -q
.\.venv-az\Scripts\python.exe scripts/audit_az_transformer_g23e.py
```

最终 **836 项测试通过（99.88 秒）**，原始结果见 `transformer_g23e_tests.txt`；审计脚本仅运行固定随机轨迹、编码和参数/推理检查。专项用训练配方做完整轨迹和粒子逐步一致性；复杂选择逐项执行，检查资源不重复支付；另有合成后续阶段、隐藏状态独立性、实体/候选重排、Replay 串并行一致、确定性下一次更新恢复、未知内容/版本与超限拒绝测试。

下一阶段仍需单独授权冻结资源与实验方案，再进行 T3 smoke、训练和独立质量验收。此次没有证明未见组合泛化、Boss 可解性或策略学习增益。
