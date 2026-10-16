# G1.3c：Headbutt 弃牌选择与已知堆顶

2026-10-10。本批在 Armaments 和 Anger 之上加入 Headbutt／Headbutt+，共 21 种卡牌，七种单敌遭遇、六个家族、126 层。过牌与消耗家族强制包含 Headbutt。

## 信息与续执行

保留公开弃牌顺序，选择候选逐项对应原生引擎弃牌位置，不合并相同卡、不截断候选。零候选没有选择，单候选由原生引擎自动回顶；多候选进入选择阶段。

Headbutt 先造成伤害，再等待选择。粒子根据公开的待完成卡牌重建回顶回调、单敌目标和 after-play 续执行；选择时不重复扣费或伤害，不读取真实 `_pending_play` 或 resolver 闭包。

公开历史维护按抽取顺序排列的 known_top。每次回顶将选中 token 放到前端；抽牌按可见手牌变化计算实际抽取数，消费已知前缀，并核对可见抽入牌与该前缀一致。手牌容量限制、Burning Pact 自动／显式消耗、回合抽牌和抽空后洗牌均纳入处理。终局没有后续决策，清空位置知识，避免推断引擎终局短路后未发生的动作。

粒子从总抽牌组成中移出已知前缀，只随机排列未知部分，再将前缀放回。生产观察不读取真实抽牌堆、未来 RNG 或私有 AI 日志；测试中读取真实牌序仅用于对照。

## 容量与版本

- content：`g1-topdeck-v1`；information：`topdeck-information-v1`；encoder：`az-topdeck-encoder-v1`。
- action：`combat-421-v1`。普通出牌沿用原生编号；选择阶段 1–420 对应原生候选位置，0 沿用确认／跳过语义，本批单选不能跳过。旧内容仍使用 `combat-115-v1`。
- 420 上界来自最多 20 张初始牌与最多 400 次决策、每次 Anger 至多生成一张。本版本明确拒绝超过 400 的决策预算及超容量选择，不依赖引擎旧掩码的截断。
- 卡词表 43（含 PAD）、卡特征 24、手牌槽 10、numeric 1,191、动作 421。新增定长的公开弃牌顺序和已知前缀 token 数值编码（词表编号 / 42，PAD=0），保留顺序与完整容量；没有编码未知牌序。它是首版顺序表示，尚非可变长序列网络。
- 新模型、Replay 和 checkpoint 显式记录新动作版本并拒绝旧版本混用；奖励仍为 v3、晋级仍为 network-only。
- train seed 偏移 7×2^28，validation/test master seed 179/277。新模型独立初始化，尚未实施跨版本迁移。

## 快速验证

保持每 seed 3 轮：每轮 126 场、16 次更新、batch 64、训练／search 8 simulations。network 晋级继续使用 256 场配对验证；最终测试每 seed 150 场。两轮 smoke 先行，正式达到三轮停止，不为通过检验加轮。

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_topdeck.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --topdeck --quick --smoke --iterations 3 --output output/az_g1_topdeck_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --topdeck --quick --iterations 3 --output output/az_g1_topdeck_v1_quick --workers 8 --smoke-evidence output/az_g1_topdeck_v1_smoke/smoke_report.json
```

本批新增 140 项测试：126 组合完整战斗与粒子逐步对照；候选顺序、零／单候选、连续回顶、抽牌／洗牌、Burning Pact 自动与选择、容量限制、123 候选不截断、升级／生成交互、击杀终局、隐藏状态扰动、兄弟粒子与卡 ID 隔离、串并行采样、Replay 恢复和 Learner 更新。

G1 整体未完成。临时费用／保留、X 费、其他生成与任意变形、已知堆底和其他选牌仍未开放。后续优先推进临时费用与保留生命周期；每项须经过观察、粒子、编码及交互验收。前一批源码已保存在 `output/az_g1_upgrades_v1_quick/source_completed.zip`。

## 完成结果

回归 **1,548 项、8 个子测试**通过，两轮 smoke 完成 **252 场、3,900 决策、8 更新**。双 seed 各 3 轮及最终测试完成，正式运行含最终测试 **296.4 秒（约 4 分 56 秒）**，不含实现、回归和 smoke。实际训练合计 **756 场、13,234 决策、96 更新**，没有加轮。

| seed | 轮数 | 场数／决策／更新 | 冠军 | 晋级次数 |
|---|---|---|---|---|
| 42 | 3 | 378／6555／48 | candidate-0.pt | 1 |
| 43 | 3 | 378／6679／48 | candidate-1.pt | 1 |

| seed | 模式 | 初始→最终胜率 | 最终效用 | 平均剩余 HP | 胜局 HP | 死亡率 | 超时率 | 平均回合／决策 | p95 决策耗时(ms) |
|---|---|---|---|---|---|---|---|---|---|
| 42 | network | 47.3% → 78.7% | 0.5435 | 20.82 | 26.47 | 21.3% | 0.0% | 4.28／16.34 | 1.336 |
| 42 | search | 9.3% → 26.0% | -0.4426 | 3.29 | 12.64 | 74.0% | 0.0% | 7.43／22.18 | 38.397 |
| 43 | network | 76.7% → 80.0% | 0.5658 | 20.90 | 26.12 | 20.0% | 0.0% | 4.28／16.20 | 1.767 |
| 43 | search | 16.7% → 22.7% | -0.4973 | 3.05 | 13.44 | 77.3% | 0.0% | 6.97／21.36 | 45.222 |

初始／最终模型与随机合法基线的测试异常、非法动作和超时均为零。双 seed network 均通过冻结的最终增益检验。随机合法基线为 **35.3%**；8-simulation search 为 **26.0% / 22.7%**，低于同模型 network，也低于随机基线。search 的快速低预算成绩如实保留，仅作观测，不影响 network 晋级；本批没有通过加轮或提高预算掩盖该弱项。

| seed | network 效用差 95% CI | network 胜率差 95% CI |
|---|---|---|
| 42 | [0.5537, 0.6243] | [29.3%, 33.3%] |
| 43 | [0.0260, 0.0958] | [1.3%, 5.3%] |

最终 network 较弱遭遇（描述统计）：

- seed 42：setup_bygone_effigy_elite 23.8%（21 场）；setup_byrdonis_elite 52.4%（21 场）。
- seed 43：setup_bygone_effigy_elite 33.3%（21 场）；setup_byrdonis_elite 47.6%（21 场）。

训练 Replay 的新机制证据：

| seed | 出现已知堆顶的场数 | 最长已知前缀 | 出现 Headbutt 选择的场数 | 最大候选数 |
|---|---|---|---|---|
| 42 | 76 | 2 | 66 | 13 |
| 43 | 84 | 2 | 65 | 11 |

以上是决策输入的观察统计，不推断终局最后一步事件；123 候选与其他边界另外由机制测试覆盖。

每 seed 最终测试 150 场、126 层（102 层单样本、24 层双样本），两个 seed 共用配方，没有留出整类家族。分层 bootstrap 不能估计单样本层的配方变异，区间不代表广泛组合置信度。各版本卡池、配方和模型初始化不同，不将跨版本分数差归因于新机制。本批是机制与训练链路验证，不是通用策略质量验收。

收尾复算通过：模型哈希与加载、实际训练量、验证晋级链、Replay 哈希／标签、seed 隔离、最终逐场统计及分层已核对。复算使用现有评价实现，没有重跑模拟器，也没有独立跨模型审查。

- [验收记录](az_topdeck_acceptance.json)
- [复算证据](az_topdeck_verification.json)
- [原始报告](../output/az_g1_topdeck_v1_quick/report.json)
- [冻结模型及哈希](../output/az_g1_topdeck_v1_quick/frozen_final_models.json)

```powershell
.venv-az/Scripts/python.exe scripts/verify_az_continuous_results.py --directory output/az_g1_topdeck_v1_quick --output docs/az_topdeck_verification.json
```
