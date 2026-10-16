# G1.3a：Anger 生成机制与三轮快速验证

## 本批机制

新增 Anger／Anger+，卡池 18→19。每次未结束战斗的 Anger 出牌向弃牌堆生成同升级副本；若这次出牌已经结束战斗，引擎不把副本加入战斗，不追加生成事件。通过终局专项用例检查该边界。

`CardGeneration` 记录公开决策序号、来源 token、结果 token、目标牌堆和机制版本 `anger-copy-v1`。记录从已观察动作和公开终局结果推导，不读取真实未知抽牌堆或 RNG。每个事件必须按决策递增并满足审计的副本规则；不能凭空增加卡牌。

守恒改为“初始牌组＋公开生成副本＝手牌＋未知抽牌组成＋弃牌＋消耗＋待完成卡牌＋已消耗能力牌”。6–20 张和每 ID 最多 5 张只约束初始牌组，不截断战斗中生成的牌。现有单次动作最多生成一张，受 400 决策上限约束；网络的总数量特征统计完整守恒库存，包括已消耗能力牌。

消耗家族强制包含 Ashen Strike、True Grit、Burning Pact、Anger，验证生成、抽取、消耗、消耗收益的组合；其他非基础家族也可抽取 Anger。仍是七种单敌、六家族、126 层。

## 新版本与边界

- content：`g1-generated-v1`，information：`generated-information-v1`，encoder：`az-generated-encoder-v1`。
- 卡词表 39、卡特征 24、numeric 301，动作 115；Reward v3 和 network-only 晋级保持。
- train seed 偏移 5×2^28，validation/test master seed 177/275，与旧运行隔离。
- 新目录、新 Replay、独立初始化模型；未实现旧权重迁移。
- 仅开放 Anger 的静态副本生成；任意随机生成、临时属性复制、动态升级、已知牌序、X 费尚未开放。G1 整体未完成。

## 验证证据

本批完整回归 1,262 项、8 个子测试通过（54.09 秒），日志 `az_generated_tests.txt`。包含 126 组合整局逐步环境／粒子对照，真实抽牌组成与守恒推断对照，超过 20 张／超过 5 个生成副本，致死攻击无入场副本，隐藏扰动搜索不变与全局 ID 隔离，串并行采样一致，Replay 恢复、Learner 更新和版本拒绝。

## 快速实验契约

按用户最新要求，默认轮数改为 3，新增 `--quick` 入口。两轮 smoke 为每轮 126 场、4 次更新、4 simulations；随后 seed 42、43 各 3 轮，每轮 126 场、16 次更新、batch 64、8 simulations。search 验证与测试为 8 simulations，不与旧 256-simulation 成绩混称。

network 仍在每轮 256 场验证上按原门槛决定晋级；最终仍各 150 场，初始／最终 network、search 使用相同配方。报告 purpose=`quick_mechanism_verification`，quality_acceptance=`not_claimed_quick_verification`。即便检验通过也不等于通用质量验收；不通过也不加轮。

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_generated.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --generated --quick --smoke --iterations 3 --output output/az_g1_generated_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --generated --quick --iterations 3 --output output/az_g1_generated_v1_quick --workers 8 --smoke-evidence output/az_g1_generated_v1_smoke/smoke_report.json
```

只在确认没有同目录协调器时执行；已完成运行不要重跑。当前状态以相应 progress.json 为准，最终报告为 `output/az_g1_generated_v1_quick/report.json`。

## 前一批真实状态

G1.2 十轮运行实际中断：seed 42 完成 4 轮，seed 43 完成 3 轮后停在第 4 轮验证。未见存活同目录进程、最终报告或 error.json；原因不明，不推断为已完成。中断状态和原源码归档见旧目录 `interruption_snapshot.json`、`source_at_interruption.zip`；原模型、Replay 和已完成验证保留，不补跑十轮。

## 完成结果

双 seed 各 3 轮和最终测试均完成。正式运行从 plan 写入到最终报告约 **218.1 秒（3.64 分钟）**，包含训练与最终测试，不包含开发、回归与 smoke。两轮 smoke 已完成 252 场、3,270 决策和 8 次更新。

正式训练实际合计 **756 场、13,126 决策、96 次更新**；每 seed 378 场、48 更新、晋级 2 次，最终模型均为各自 candidate-1.pt。没有加轮。

| seed | 模式 | 初始→最终胜率 | 最终效用 | 平均剩余 HP | 胜局 HP | 死亡率 | 超时率 | 平均回合/决策 | p95 决策耗时(ms) |
|---|---|---|---|---|---|---|---|---|---|
| 42 | network | 6.0% → 76.0% | 0.4924 | 19.23 | 25.30 | 24.0% | 0.0% | 3.93/13.47 | 0.916 |
| 42 | search | 8.0% → 30.7% | -0.3565 | 3.84 | 12.52 | 69.3% | 0.0% | 5.94/16.47 | 58.389 |
| 43 | network | 1.3% → 81.3% | 0.5853 | 21.32 | 26.21 | 18.7% | 0.0% | 4.05/15.36 | 1.007 |
| 43 | search | 3.3% → 38.7% | -0.2104 | 5.47 | 14.14 | 61.3% | 0.0% | 7.14/22.59 | 30.999 |

初始／最终模型与随机基线的异常和非法动作均为零。随机合法基线胜率 30.7%。双 seed network 均通过本批冻结的效用／胜率配对检验；这不是通用策略验收。8-simulation search 只有 30.7% / 38.7%，显著低于同模型 network，如实保留，不能宣传搜索更优，也不与旧 256-simulation 成绩直接比较。

| seed | network 效用差 95% CI | network 胜率差 95% CI |
|---|---|---|
| 42 | [1.2557, 1.3248] | [68.0%, 72.0%] |
| 43 | [1.4860, 1.5524] | [78.0%, 82.0%] |

每 seed 测试 150 场覆盖 126 层（102 层单样本、24 层双样本），两个 seed 共用配方，没有留出整类家族。分层 bootstrap 无法估计单样本层的配方变异，不将这些区间外推为广泛组合置信度。各版本卡池、数据、模型初始化不同，不能用本批与旧批均值直接归因新机制改善。

最终 network 较弱遭遇（描述统计，不作多重比较显著性声明）：

- seed 42：setup_bygone_effigy_elite 28.6%（21 场）；setup_byrdonis_elite 47.6%（21 场）。
- seed 43：setup_bygone_effigy_elite 33.3%（21 场）；setup_byrdonis_elite 71.4%（21 场）。

训练 Replay 中确实观察到生成机制：{"42": {"episodes_with_observed_generated_cards": 74, "max_observed_generated_count": 5}, "43": {"episodes_with_observed_generated_cards": 84, "max_observed_generated_count": 9}}。该统计仅统计决策输入中已出现的生成副本，不推断终局最后一步的生成量。

原始指标、家族／遭遇／HP／联合分层及逐场数据保留在运行目录。收尾复算已核对模型哈希、实际更新数、Replay 完整性、seed 划分、晋级链与统计；复算使用现有评价实现，未重复执行模拟器，也没有独立跨模型审查。

- [机器可读验收](az_generated_acceptance.json)
- [复算证据](az_generated_verification.json)
- [完整原始报告](../output/az_g1_generated_v1_quick/report.json)
- [冻结模型路径与哈希](../output/az_g1_generated_v1_quick/frozen_final_models.json)

复算命令：

```powershell
.venv-az/Scripts/python.exe scripts/verify_az_continuous_results.py --directory output/az_g1_generated_v1_quick --output docs/az_generated_verification.json
```

下一步建议继续 Armaments 的战斗内升级／变化记录，仍采用三轮快速验证。若使用本次最终分组结果调整课程，下批最终验收须换新的隔离测试集。
