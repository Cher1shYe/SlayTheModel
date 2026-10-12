# G1.3b：Armaments 战斗内升级

本批增加 Armaments／Armaments+，卡池 19→20，继续七遭遇、六家族、126 层。普通版选择一张未升级手牌；升级版升级全部未升级手牌。零候选不产生选择，单候选按引擎自动完成，多候选保持真实显示顺序。

## 公开变化记录与选择

新增不可变 CardUpgrade：公开决策序号、手牌位置、变化前后 token 和来源 Armaments 版本。记录由已公开的手牌、动作和选择推导，不读取真实隐藏牌序或私有 continuation。

库存按公开生成／升级事件的时间顺序重建：生成增加一张，升级扣除原 token 并增加升级 token，总数不变。升级后的 Anger 可继续生成 Anger+。验证拒绝没有公开来源的副本／升级、重复位置、越界决策和不合法的升级结果。

Armaments 的选择候选仅包含未升级手牌，候选索引与手牌索引可能不同。粒子按公开引用绑定候选，在假想世界构建升级回调和出牌续执行，不复制真实 resolver。选择前的费用、格挡不会重复结算。

## 内容与版本

- content：`g1-upgrades-v1`；information：`upgrades-information-v1`；encoder：`az-upgrades-encoder-v1`。
- 卡词表 41、卡特征 24、numeric 334、动作 115。Reward v3 与 network-only 晋级保持。
- 格挡与消耗家族强制包含 Armaments；消耗家族同时包含 Anger、True Grit、Burning Pact、Ashen Strike，覆盖升级／生成／消耗交互。
- 初始牌组仍为 6–20 张、每 ID 最多 5 张；战斗生成不按此截断。
- train seed 偏移 6×2^28，validation/test master seed 178/276，新目录与 Replay，独立初始化模型，无旧权重迁移。
- 升级按原生工厂结果更新费用与效果；本批尚未开放临时费用，所以不把费用覆盖与升级的任意组合宣称为已支持。

## 快速验证配置

保持用户要求：两轮小规模 smoke 后，seed 42、43 各 3 轮。正式每轮 126 场、16 更新、batch 64、训练和 search 8 simulations；network 晋级仍为 256 场配对验证，最终测试每 seed 150 场。达到三轮停止，不为通过检验加轮。此配置用于机制验证，不是通用质量验收。

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_upgrades.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --upgrades --quick --smoke --iterations 3 --output output/az_g1_upgrades_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --upgrades --quick --iterations 3 --output output/az_g1_upgrades_v1_quick --workers 8 --smoke-evidence output/az_g1_upgrades_v1_smoke/smoke_report.json
```

不要重复启动已完成或正在运行的目录。完整结果以运行目录 report.json 为准。

## 验证范围与未完成项

新增 133 项测试：126 组合完整战斗真实环境／粒子逐步对照及抽牌组成对照；混合升级／未升级候选的索引映射；Body Slam 升级为零费；选择不重复获得格挡；全手牌升级后 Anger+ 生成；零／单候选自动处理；隐藏状态扰动下搜索不变；兄弟粒子与全局卡 ID 隔离；错误来源拒绝；串并行采样、Replay 恢复和 Learner 更新。

G1 整体尚未完成。下一机制为 Headbutt 的弃牌选择与已知抽牌堆顶；临时费用／保留、X 费、任意变形和其他生成机制继续明确拒绝。旧实验产物保留，前一批源代码额外归档在其运行目录 source_completed.zip。

## 完成结果（2026-10-10）

回归 **1,395 项、8 个子测试**通过。两轮 smoke 完成 252 场、3,595 决策和 8 次更新。双 seed 各 3 轮及最终测试完成，正式运行含最终测试 **249.2 秒（约 4 分 9 秒）**，不含开发、回归和 smoke。实际训练合计 **756 场、13,580 决策、96 更新**。没有追加轮数。

| seed | 轮数 | 训练场数／决策／更新 | 冠军 | 晋级次数 |
|---|---|---|---|---|
| 42 | 3 | 378／6791／48 | candidate-2.pt | 2 |
| 43 | 3 | 378／6789／48 | candidate-0.pt | 1 |

| seed | 模式 | 初始→最终胜率 | 最终效用 | 平均剩余 HP | 胜局 HP | 死亡率 | 超时率 | 平均回合／决策 | p95 决策耗时(ms) |
|---|---|---|---|---|---|---|---|---|---|
| 42 | network | 63.3% → 79.3% | 0.5508 | 19.79 | 24.94 | 20.7% | 0.0% | 4.01／15.27 | 1.105 |
| 42 | search | 10.0% → 39.3% | -0.2034 | 5.86 | 14.90 | 60.7% | 0.0% | 6.35／19.19 | 62.096 |
| 43 | network | 78.0% → 80.0% | 0.5653 | 19.57 | 24.46 | 20.0% | 0.0% | 4.19／15.26 | 1.188 |
| 43 | search | 18.7% → 32.7% | -0.3306 | 3.59 | 10.94 | 66.7% | 0.7% | 7.56／22.09 | 31.293 |

双 seed network 均通过本批冻结的增益检验，随机合法基线胜率 30.0%。初始／最终模型与随机基线测试的异常、非法动作均为零。seed 43 最终 search 有 1/150 场达到 100 回合上限：`up-test-276-0-21`，cycle 家族对 Shrinker Beetle，264 决策，最终己方 HP 3、敌方 HP 28/40，效用 -0.08；计入胜率分母且不算胜利。

8-simulation search 明显低于同模型 network，仅为观测指标，不参与晋级否决；不能与历史 256-simulation 成绩直接比较，也不据此声称搜索更优。

| seed | network 效用差 95% CI | network 胜率差 95% CI |
|---|---|---|
| 42 | [0.2873, 0.3143] | [15.3%, 16.7%] |
| 43 | [0.0270, 0.0519] | [1.3%, 2.7%] |

每 seed 测试 150 场覆盖 126 层（102 层单样本、24 层双样本），两个 seed 共用测试配方，未留出整类构筑。分层 bootstrap 无法估计单样本层的配方变异，因此区间不能外推为广泛组合置信度。本批用于机制与训练链路验证，不是通用质量验收；跨批卡池、配方和模型初始化不同，不能将分数变化归因于新机制。

最终 network 较弱遭遇（描述统计）：
- seed 42：setup_bygone_effigy_elite 23.8%（21 场）；setup_byrdonis_elite 61.9%（21 场）。
- seed 43：setup_bygone_effigy_elite 28.6%（21 场）；setup_byrdonis_elite 47.6%（21 场）。

训练 Replay 中的升级证据：`{"42": {"episodes_with_observed_upgrades": 109, "max_observed_upgrade_count": 7}, "43": {"episodes_with_observed_upgrades": 105, "max_observed_upgrade_count": 7}}`。仅统计后续决策输入已观察到的升级，不推断终局最后一步的事件数量。

收尾复算通过：模型哈希、实际训练量、验证晋级链、Replay 哈希及奖励标签、seed 划分、最终逐场统计与分层结果已核对。该检查复用现有评价实现，未重新执行模拟器，也不是独立跨模型审查。

- [验收记录](az_upgrades_acceptance.json)
- [复算证据](az_upgrades_verification.json)
- [原始报告](../output/az_g1_upgrades_v1_quick/report.json)
- [冻结模型及哈希](../output/az_g1_upgrades_v1_quick/frozen_final_models.json)

```powershell
.venv-az/Scripts/python.exe scripts/verify_az_continuous_results.py --directory output/az_g1_upgrades_v1_quick --output docs/az_upgrades_verification.json
```

下一批：Headbutt 的弃牌选择与已知抽牌堆顶，仍按三轮快速验证。
