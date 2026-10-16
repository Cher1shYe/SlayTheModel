# M6 第一批：三种 weak 遭遇

本批扩展为 Shrinker Beetle、Fuzzy Wurm Crawler 和 Nibbit 三种单敌人战斗。机制支持与两轮 smoke 已通过，正式实验已完成并通过产物／统计核验；双 seed 学习增益验收未通过。升级牌、牌组变体、选牌、药水、遗物和多敌人战斗尚未开放，不能称整个 M6 已完成。

## 机制审核

依据本仓库 `sts2_env/encounters/act1.py`、`sts2_env/monsters/act1_weak.py` 和引擎规则，固定 ascension 0：

| 遭遇 | 敌人 HP | 行动循环 | 新增机制 |
|---|---:|---|---|
| setup_shrinker_beetle_weak | 38–40 | Shrink → Chomp 7 → Stomp 13 → Chomp… | 原支持：Shrink、Bash 的 Vulnerable |
| setup_fuzzy_wurm_crawler_weak | 55–57 | First Acid Goop 4 → Inhale → Acid Goop 4 → First Acid Goop… | 每次 Inhale 永久力量 +7，攻击计入力量 |
| setup_nibbits_weak | 42–46 | Butt 12 → Slice 6 +自身格挡 5 → Hiss → Butt… | Hiss 永久力量 +2，格挡按引擎生命周期处理 |

`setup_nibbits_weak` 在本模拟器实际创建一只 `is_alone=True` 的 Nibbit，固定从 Butt 开始。没有替换它的敌人数；普通多只 Nibbits 遭遇不在本次范围。

这两种新增怪不生成 Slimed 或其他状态牌，不引入抽牌之外的新卡牌随机事件。随机性仍包括初始 HP、抽牌／弃牌重洗；HP 已公开后按公开数值重建，未来 RNG 用独立搜索源采样。AI 行动循环固定，无需读取私有 AI 日志；Nibbit 的起手条件由已限定的单敌人场景决定。以上是模拟器范围审核，并非本轮新增的实机规则一致性认证。

## 公开信息与版本

- 内容版本：`three-weak-starter-v1`。
- 信息版本：`three-weak-information-v1`。
- 编码版本：`az-three-weak-encoder-v1`，numeric **73 维**，原 v2 为 62 维。
- 新特征：三种怪物 one-hot、敌方力量、Buff 意图、六种新增行动的公开历史计数。本场初始 HP 仍保留。
- 意图中的伤害数值是引擎 intent 的基础值；力量另有显式特征，不能将 Acid Goop 的基础 4 误读为力量增长后的实际伤害。

观察器仅读当前公开意图和能力层数，公共历史由真实动作推进；粒子从历史重建 AI 阶段并恢复力量、格挡、Vulnerable 与牌堆组成。一条模拟路径内保留同一假设牌序和随机源，shuffle／monster_ai 等 RNG 别名继续指向同一流。

旧 Shrinker v1/v2 checkpoint 和 schema 仍可按旧内容版本加载。新模型、Replay 和场景必须显式绑定新版本，旧模型不会自动扩维或零填新增特征。未知怪物、牌、能力或多敌人场景继续 fail fast。

## 分层采样和评估

新清单 `data/az/m6_manifest.json` 使用 40/80 HP 开局，总共 662 个场景：train 256、validation 256、test 150。环境 seed 使用 80000/81000/82000、90000/91000/92000、100000/101000/102000 三组新编号段，均不与旧实验或 pilot 重叠。

按牌组家族与遭遇确定性轮换选取场景：验证三层为 86/85/85，测试为 50/50/50；每轮 256 个采样任务也按遭遇平衡。Replay 在家族／遭遇层、episode、决策之间分层抽样，避免长局吞没分布。成对 bootstrap 在各遭遇层内重采样，保持各层场数。总体验收门槛保持胜负优先及正效用增益，另外保存逐遭遇指标，不能用总平均隐藏某个遭遇退化。

## 验证结果

新测试覆盖三遭遇共 18 场完整游戏的逐步重建对照、真实力量增伤、Nibbit 格挡、隐藏牌序/RNG/私有 AI 日志置换后的搜索标签一致、搜索不改变卡牌 allocator、单进程与多进程标签一致、schema/checkpoint/replay 隔离和分层数量。

完整相关回归 **129 passed、30 subtests passed**。最终信息版本更新后，M6／并行评估／实验测试共 13 项再通过。最终两轮 smoke 保存于 `output/az_m6_acceptance/`：每轮 6 场采样、每遭遇 2 场；验证也每遭遇 2 场。小验证集不具备正式晋级资格。早期同配置 smoke 的 Fuzzy Wurm 出现死亡，原始结果保留，没有降低难度来制造全胜。

## 正式实验

已完成 `output/az_m6_experiment/`：seeds 42、43，各两轮，每轮 256 场采样和 200 次更新；Reward v2，训练 64 simulations，评估 256；每轮 256 场晋级验证，每 seed 总计 150 场最终测试。两组最终模型冻结后才运行新 test 集。新 73 维网络随机初始化，未把旧权重静默迁移。

当前状态为 complete，learning_acceptance 为 not_met。seed 42 两轮均晋级；seed 43 两轮均未晋级，最终模型保持 initial.pt。日志为 `output/az_m6_experiment.stdout.log`；进度为运行目录下 `progress.json` 和各 seed 的 `state.json`。

```powershell
# 仅在实例已退出时恢复，不能与现有运行并发执行
.venv-az/Scripts/python.exe -u scripts/run_alphazero_experiment.py --output output/az_m6_experiment --manifest data/az/m6_manifest.json --content-version three-weak-starter-v1
# 完成后核对结果
.venv-az/Scripts/python.exe scripts/verify_alphazero_results.py --directory output/az_m6_experiment --output docs/az_m6_verification.json
```

## 正式验收结果（2026-10-09）

共完成 1,024 场训练采样、800 次参数更新。每种模式、每个 seed 的测试均为 150 场，三遭遇各 50 场。

| seed | 模式 | 初始胜率 → 最终胜率 | 最终平均剩余 HP | 增益验收 |
|---|---|---|---:|---|
| 42 | 纯网络 | 84% → 100% | 29.767 | 通过 |
| 42 | 搜索 | 86% → 100% | 26.867 | 通过 |
| 43 | 纯网络 | 100% → 100% | 27.213 | 未通过，最终模型未改变 |
| 43 | 搜索 | 100% → 100% | 26.253 | 未通过，最终模型未改变 |

seed 42 胜率增益的 95% 成对分层 bootstrap 区间分别为 [10.67, 22.00]、[8.67, 19.33] 个百分点；两个模式在三种遭遇分别也达到 100% 最终胜率。seed 43 各遭遇初始与最终结果相同，不能称其训练提升。随机基线 60% 胜率；规则基线 100%、平均剩余 HP 29.86。16 场 oracle 仅为独立列出的有特权验证参考，不与 150 场测试混作同一比较。

### seed 43 晋级失败诊断

256 场验证中，初始模型与两轮候选在两种模式全部获胜；晋级失败来自搜索的保血表现，而非胜率门槛。

| 轮次 | 纯网络平均 HP（初始 → 候选） | 搜索平均 HP（初始 → 候选） | 搜索效用差 95% CI |
|---|---|---|---|
| 1 | 27.281 → 28.793 | 26.734 → 25.934 | [-0.009492, 0.001504] |
| 2 | 27.281 → 28.793 | 26.734 → 24.695 | [-0.015977, -0.004492] |

两轮纯网络效用增益区间都严格为正，但搜索未通过；第二轮搜索退化的区间完全为负。联合晋级要求两个模式均通过，因此保留初始模型符合原规则。当前证据定位到搜索保血问题，尚未证明其算法根因。

下一步先用训练／验证场景诊断搜索动作、叶节点价值校准及终局奖励回传，再决定修复；不放宽门槛或用已查看的最终测试挑参数。若调参，需冻结新的测试集后再做下一次正式验收。牌组、选牌、药水／遗物扩展仍待逐项实现。

核验文件：`az_m6_verification.json`；完整结果：`az_m6_results.json`；验证诊断：`az_m6_promotion_diagnostics.json`。本轮复算场景配对、终局奖励、bootstrap、模型冻结及产物一致性，没有重新运行模拟器，也没有独立跨模型审查。两组训练 seed 共享同一组测试场景，不能视为两个独立测试场景集合。日志中的两次 Windows 原子替换冲突均经一次重试恢复，无记录的正式运行错误。
