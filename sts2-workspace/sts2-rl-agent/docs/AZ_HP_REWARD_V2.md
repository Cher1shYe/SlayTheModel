# 40 HP 与血量奖励实验

2026-10-09 按用户要求提高难度，改为 2 个训练 seed、每 seed 500 场最终测试。历史 80 HP / win-loss-v1 的实验、checkpoint 和报告保持不变；spec.md v0.2 定义本次新要求。

## 配置与奖励

- Ironclad 初始血量 **40/80**，原 starter 牌组与 Shrinker 遭遇，无药水和遗物。
- Seeds **42、43**，各 **2 轮**；每轮 256 场采样、200 次更新、512 场晋级验证；最终测试 **500 场**。
- 训练 64 simulations／决策，评估 256；8 workers；全新随机初始化的 v2 网络。
- 新 manifest：`data/az/hp_v2_manifest.json`。train seeds 40000–40255，validation 50000–50511，test 60000–60499，与旧实验和本次 pilot 不重叠。

奖励版本 `win-first-hp-v2`：过程中 0，终局一次结算，gamma=1。

```text
胜利：z = 0.8 + 0.2 × clip(己方剩余血量 / 本场初始血量, 0, 1)
死亡或超时：z = -1 + 0.2 × clip(敌方净掉血 / 敌方初始血量, 0, 1)
```

例如 40 HP 开局、20 HP 获胜，z=0.9；未胜但打掉敌人一半血量，z=-0.9。未胜保留负基线，使任何单场胜利始终高于未胜；未胜局之间对敌伤害更多则分数更高。超时与死亡分别记录，相同敌方净伤害得到相同效用；异常不产生奖励。当前范围无治疗或复活，敌方初始血量等于其最大血量。

有限权重的标量期望不是严格的胜率字典序优化。晋级另外要求胜率差的成对 CI 下界 >0，或所有配对场景的胜／未胜结果逐场相同；同时效用差 CI 下界 >0。分别报告胜率差和效用差，v2 不再将效用差除以 2。

## 难度扫描

使用全新 pilot seeds 30000–30063，每个血量运行 64 场，未查看新 test 集。预先固定选择规则：规则策略胜率 ≥75%，随机策略胜率 10%–85%，优先最接近 50%，并列选更低 HP。

| 初始 HP | 随机策略 | 规则策略 | 初始网络 42 | 初始网络 43 |
|---:|---:|---:|---:|---:|
| 10 | 0% | 84.4% | 1.6% | 0% |
| 15 | 3.1% | 85.9% | 6.3% | 1.6% |
| 20 | 7.8% | 85.9% | 23.4% | 4.7% |
| 30 | 35.9% | 100% | 54.7% | 14.1% |
| **40** | **54.7%** | **100%** | **84.4%** | **37.5%** |
| 50 | 75.0% | 100% | 95.3% | 51.6% |
| 60 | 89.1% | 100% | 98.4% | 59.4% |

选中 40 HP。64 场 pilot 只服务于难度选择，不代表正式学习结论；规则策略仍满胜率，说明范围有限。原始记录：[az_hp_v2_difficulty.json](az_hp_v2_difficulty.json)。

## 实现与验证

真实环境和搜索粒子调用同一个终局奖励函数；InformationState 携带初始血量与奖励版本，重建／推进时保留。新编码器 numeric 为 62 维，含公开的初始血量。网络、checkpoint、worker、replay、恢复和评估显式校验奖励版本；旧 schema/v1 数据不会自动迁移。Replay 保存可复算 z 的血量原始量，不重标历史数据。

完整相关回归 120 passed、30 subtests passed。最后的小修后，HP reward／experiment／replay 相关 21 项再通过。两轮 v2 smoke 输出在 `output/az_hp_v2_acceptance/`；小验证集不会晋级。新增测试覆盖奖励单调性、环境与粒子终局一致、版本隔离、v2 更新恢复一致，以及“效用上升但胜率下降”时拒绝晋级。

正式实验 `output/az_hp_v2_experiment/` 已完成，两组 seed 均完成两轮并晋级到 candidate-1.pt。逐场数据、冻结 checkpoint 与配对置信区间已复核，当前限定范围的工程和学习验收均通过。结果及保血差距见 [AZ_HP_V2_RESULTS.md](AZ_HP_V2_RESULTS.md)。旧 v1 未达标报告保持不变。

```powershell
# 仅在进程已经退出时恢复；不要与运行中的实例并发启动
.venv-az/Scripts/python.exe -u scripts/run_alphazero_experiment.py
# 实验完成后核对原始行和配对统计
.venv-az/Scripts/python.exe scripts/verify_alphazero_results.py --directory output/az_hp_v2_experiment --output docs/az_hp_v2_verification.json
```
