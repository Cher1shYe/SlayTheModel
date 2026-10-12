# G1.4a：临时费用与静态保留生命周期

2026-10-10。本批新增 Stomp／Stomp+ 与无色牌 Restlessness／Restlessness+，共 23 种卡牌，仍为 Ironclad、七种单敌、六家族、126 层。力量家族必含 Stomp，过牌家族必含 Restlessness；其他非基础家族允许组合抽样。G1 尚未整体完成。

## 依赖与信息边界

规则对照本地 `decompiled/MegaCrit.Sts2.Core.Models.Cards/Stomp.cs`、`Restlessness.cs`，实现对照 `cards/ironclad.py`、`cards/colorless.py`、`cards/base.py`、`core/combat.py`。没有改动原生引擎规则。

Stomp 基础费用 3，普通／升级伤害 12／15。每次攻击的 before-play hook 将所有区域的 Stomp 本回合费用减 1，最低 0；包括正在打出的自身，但支付使用出牌前费用，不追溯退费。当前内容不能生成或变形出 Stomp，所有副本从开战就在场，因此可以从公开的本回合攻击次数唯一推出手牌、未知抽牌组成、弃牌、消耗、待完成区域的费用。不读取隐藏牌堆来保存状态；`lifecycle.py` 负责推导与核对，其他临时改费来源明确拒绝。

Headbutt 暂停选择时，它的 before-play 已执行，因此计入降费；粒子续执行不能再次触发攻击。Armaments 升级保持当前临时覆盖，回合结束在所有区域清除覆盖并恢复费用。选牌候选含完整公开卡状态，手牌候选必须与手牌状态一致。

Restlessness 自带静态保留，离开手牌进入打出区域后若手牌为空，普通／升级版抽 2／3 张并获得 2／3 能量；有其他手牌时无效果。回合结束保留牌先留在手牌，再抽新牌，原有顺序保持。known_top 推进必须扣除保留牌数量，不能把保留牌当作新抽牌。实际抽入仍受十张手牌容量限制；抽空后的洗牌延续原生 RNG。

本批支持静态保留；临时赋予保留、其他费用变化、战斗费用、多选、X 费及其他生成／变形仍拒绝。不是任意可变卡状态的通用重建器；未来加入不同来源的逐实例费用变化时必须升级状态契约，不能继续套用“全体副本共享费用”的假设。

## 冻结版本与验证预算

- content `g1-lifecycle-v1`；information `lifecycle-information-v1`；encoder `az-lifecycle-encoder-v1`。
- 词表 47（含 PAD）、卡特征 24、numeric 1,220、动作 421（`combat-421-v1`），奖励 v3 和 network-only 晋级不变。
- 沿用完整 420 项弃牌顺序／已知堆顶编码，编号除数继续为 42（新增 token 可大于 1，不裁剪）；新增 29 项组成、升级、攻击次数及费用特征。retain 手特征包含本批静态关键字。仍为首版定长数值顺序表示，未实施序列网络或权重迁移。
- 新 Replay、模型独立初始化。train seed 空间为 `[15×2^27, 2^31)`，与旧 topdeck train 空间相邻不重叠，并保持原生有符号 32 位正 seed 范围；validation/test masters 为 180／278。边界坐标已测试。
- 双 seed 42／43 各 3 轮，每轮 126 场、16 更新、batch 64，训练与 search 8 simulations；network 256 场配对晋级、最终每 seed 150 场。先做两轮 smoke，不自动加轮。
- 历史源码已存 `output/az_g1_topdeck_v1_quick/source_completed.zip`，旧结果保持原样。

入口：

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_lifecycle.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --lifecycle --quick --smoke --iterations 3 --output output/az_g1_lifecycle_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --lifecycle --quick --iterations 3 --output output/az_g1_lifecycle_v1_quick --workers 8 --smoke-evidence output/az_g1_lifecycle_v1_smoke/smoke_report.json
```

## 验证状态

本批 147 项测试已通过：126 层完整战斗真实环境／粒子逐步对照，所有区域临时费用一致，临时费用与升级／回顶／消耗／洗牌交互，保留先于抽牌、五张保留后的容量、单卡奖励和非单卡无奖励；版本拒绝、错误状态拒绝、隐藏扰动搜索不变、分支隔离、串并行采样、Replay 恢复及 Learner 更新。完整回归 1,695 项及 8 个子测试通过（103.23 秒），另 98 项原生卡牌工厂／边界回归通过（0.40 秒），总计 1,793 项及 8 个子测试。日志为 `az_lifecycle_tests.txt`、`az_lifecycle_native_tests.txt`。两轮 smoke、双 seed 三轮、最终测试和收尾复算均已完成。


## 实际运行与成绩

两轮 smoke 通过：252 场、3,788 决策、8 更新，采样约 21.19 秒，11.89 场／秒。正式训练含最终测试实际约 301.74 秒（5 分 2 秒）；不含 smoke、开发和回归。

| seed | 完成轮数 | 采样 | 决策 | 更新 | 晋级次数 | 冠军 |
|---|---:|---:|---:|---:|---:|---|
| 42 | 3 | 378 | 6681 | 48 | 1 | candidate-2.pt |
| 43 | 3 | 378 | 6895 | 48 | 2 | candidate-1.pt |

合计 756 场、13,576 决策、96 更新；达到三轮即停止。network-only 规则未修改。

| seed／模式 | 初始胜率 → 最终胜率 | 最终效用 | 平均剩余 HP | 胜局 HP | 平均回合／决策 | p95 延迟 ms |
|---|---|---:|---:|---:|---|---:|
| 42 network | 76.7% → 80.0% | 0.5677 | 20.57 | 25.72 | 4.06／15.83 | 1.17 |
| 42 search | 30.0% → 31.3% | -0.3502 | 3.71 | 11.83 | 6.87／20.91 | 37.94 |
| 43 network | 0.0% → 74.0% | 0.4592 | 18.69 | 25.26 | 5.20／21.27 | 1.07 |
| 43 search | 0.7% → 22.0% | -0.5063 | 1.75 | 7.97 | 6.67／21.02 | 51.11 |

所有初始／最终测试的异常与非法动作为零；最终模型的两个模式均无超时。初始 seed 43 search 有 1/150 超时：`life-test-278-0-107`，消耗家族对 Shrinker，100 回合、258 决策，己方 HP 2、敌人 HP 39/39、效用 -0.2。保留真实记录，没有删去该局。

随机合法基线胜率 28.7%；seed 42 search 为 31.3%，seed 43 为 22.0%，且均远低于 network。seed 42 search 的配对增益检验未通过，seed 43 通过；search 不参与晋级否决。不从这些短程结果推断搜索算法已达到高质量。

network 的最终配对增益检验均通过：

| seed | 效用差 95% CI | 胜率差 95% CI |
|---|---|---|
| 42 | [0.040906, 0.084730] | [0.020000, 0.046667] |
| 43 | [1.433738, 1.478918] | [0.726667, 0.753333] |

这只是冻结的本批检验；seed 43 随机初始化 network 起点为 0%，两 seed 起点差异很大，不能把其巨大增幅解释为稳定的广泛泛化收益。测试为 150 个配方覆盖 126 层（102 层各 1 场、24 层各 2 场），两 seed 共用配方；没有留出完整家族，单例分层 bootstrap 无法估计层内变异。规则基线尚不支持该扩展池，未评估。

## 机制覆盖与弱项

以下来自训练 Replay 的决策输入与相邻决策观察，不能推断终局后未记录的机制事件：

| seed | 含降费 Stomp 的局 | 含保留特征的局 | 降费 Stomp 出牌数 | Restlessness 单卡出牌数 | 可见保留跨回合次数 |
|---|---:|---:|---:|---:|---:|
| 42 | 83 | 87 | 31 | 1 | 134 |
| 43 | 78 | 98 | 28 | 0 | 152 |

Restlessness 的单卡触发在短程训练中稀少；工程机制回归通过不代表策略已学会可靠安排该组合。本次不增加轮数、不按最终测试改采样。network 最弱遭遇仍是 Bygone Effigy（38.1%／23.8%）和 Byrdonis（57.1%／38.1%），各 seed、每个遭遇仅 21 场；其后 Cubex 为 85.7%／76.2%。总体增益也不意味着每组都改善，例如 seed 42 格挡家族从 81.0% 降到 71.4%，Mawler 从 95.2% 降到 90.5%。完整分层及 HP 档在 `report.json`。

## 收尾与下一步

`verify_az_continuous_results.py` 复算状态为 `artifact_and_statistics_checks_passed`：代码与 runner 摘要、模型哈希与加载、实际训练量、晋级链、Replay 哈希与标签、seed 隔离和原始最终统计均通过。该工具复用本项目评估实现，属于产物及统计复算；没有独立跨模型审查，也没有另跑模拟器复现最终对局。

证据：`az_lifecycle_acceptance.json`、`az_lifecycle_verification.json`，原始报告 `output/az_g1_lifecycle_v1_quick/report.json`。当前运行 complete，勿重复启动。工程通过、训练完成、学习增益通过；通用质量验收不作声明。

下一批优先接通 X 费与实际支付能量的公开语义，再继续临时赋予保留、多选等 G1 剩余项。G2 的多敌／Boss 尚未开放，不将当前单敌 Stomp 群攻标记视作多敌已支持。
