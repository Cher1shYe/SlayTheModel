# G1.4c：消除多选往返动作

2026-10-10。用户要求解决 G1.4b 的超时、反复选择问题。工程回归、两轮 smoke、双 seed 各三轮训练、最终测试和产物统计复算均完成。本批最终测试没有超时；双 seed 学习增益通过。G1 整体和通用质量验收仍未完成。

## 原因与修复

G1.4b 的一个既有验证样本 `sel-validation-181-0-102` 已记录在 `az_selection_timeout_diagnostic.json`：400 次决策中 395 次停留于 Purity 选择阶段，网络不断选择／取消候选 0，确认一直合法但概率略低。每次点击都消耗决策预算；浅层 PUCT 和训练目标也包含这些可逆点击。该证据说明策略循环，不是原生引擎无法确认。

本批将 Purity 的 AZ 动作改为**完整最终集合**。动作整数的第 i 位表示候选 i 是否最终被消耗，0 表示空集跳过。AI 在同一次决策内选定集合，适配器先取消不属于目标的选中项、再选择缺少项、最后确认一次。搜索粒子和真实适配器共用执行函数。回放记录的是同一个宏动作，搜索目标和纯网络评估也是同一语义。

这不依赖超时阈值、历史访问次数、奖励惩罚或强制选牌规则；所有合法最终集合都保留。原生引擎的选中／取消／确认接口不改动。对于已有部分选中状态，也可取消全部或换成任何合法集合。重复卡牌按候选位置区分，实际消耗顺序仍由原生引擎按候选顺序确定。

Purity 从最多 10 张手牌打出后，最多剩 9 个候选。普通版至多选 3 张，有 130 个合法集合；升级版至多选 5 张，有 382 个。固定 9 位编号需要 512 个输出槽；超出审计容量直接拒绝，不截断。普通出牌和其他单选仍使用旧编号，单选弃牌候选仍覆盖最多 420 张。

## 版本和兼容性

- 内容：`g1-selection-v2`；仍为 26 种卡牌、7 种单敌、6 家族、126 层。
- 信息／编码：`selection-information-v2`／`az-selection-encoder-v2`。
- 动作：`combat-set512-v2`，512 槽；numeric 仍为 1268，卡词表 53，卡特征 24。
- 奖励：`win-timeout-hp-v3` 不变。晋级只看 network，search 仅观测。
- 400 次决策上限不变，但现在一次多选提交计为一个决策，不能把与旧点击动作的决策数差异解释为纯策略学习提升。
- 新模型独立初始化，不加载旧 421 输出头；新旧 checkpoint／Replay 根据 schema 和内容版本拒绝混用。
- 旧内容、旧动作语义和旧 schema 保留；旧源码已归档到 `output/az_g1_selection_v1_quick/source_completed.zip`。
- train seed 空间 `[9*2^27,10*2^27)`；新 validation/test master 为 182／280。旧测试已用于发现问题，故本批使用新隔离测试。旧验证样本仅用于修复回归。

## 验证

`tests/test_az_choice_sets.py` 包括：不同候选数的全部合法集合映射、满手两种升级状态全部集合的原生结算与粒子对齐、已有选中集合的取消替换、旧循环验证样本一次完成、隐藏状态与真实回调隔离、旧 checkpoint 拒绝、seed 空间、126 层完整战斗逐步粒子对齐、串并行 Replay 与学习更新。历史 G1.4b 逐次切换测试继续保留。

定向测试：151 项通过，12.94 秒。全量 AZ 与适用原生回归：2,112 项测试及 8 个子测试通过，138.29 秒，日志见 `az_choice_sets_tests.txt`。既有 G1 各批冻结 encoder schema 与当前计算结果逐一一致。

运行入口：

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_choice_sets.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --choice-sets --quick --smoke --iterations 3 --output output/az_g1_selection_v2_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --choice-sets --quick --iterations 3 --output output/az_g1_selection_v2_quick --workers 8 --smoke-evidence output/az_g1_selection_v2_smoke/smoke_report.json
.venv-az/Scripts/python.exe scripts/verify_az_continuous_results.py --directory output/az_g1_selection_v2_quick --output docs/az_choice_sets_verification.json
```

两轮 smoke 后双 seed 各 3 轮，不因无增益加轮。每轮 126 场、16 更新，训练／search 为 8 simulations；network 晋级 256 场配对验证，最终测试每 seed 150 场。工程修复不等于已经学会最优消耗组合，也不保证其他原因的战斗超时消失。

## 已完成运行

两轮 smoke 通过：252 场、3,463 次决策、8 更新，采样 22.24 秒；估计正式训练 4.41 分钟、不含最终测试。正式运行实际含最终测试约 **300.03 秒（5 分钟）**，不含实现、回归、smoke 和复算。所有运行已结束，不重复启动。

| seed | 轮数 | 训练场数 | 决策 | 更新 | 晋级次数 | 最终模型 |
|---|---:|---:|---:|---:|---:|---|
| 42 | 3 | 378 | 6,427 | 48 | 3 | candidate-2.pt |
| 43 | 3 | 378 | 6,513 | 48 | 2 | candidate-2.pt |

合计 756 场、12,940 次决策、96 更新。两个 Replay 的训练超时均为零。Purity 完整集合决策为 73／77 次，每次下一条观察都已退出选牌阶段，共 **150/150 次一次提交完成**；未通过静默删除失败回合得出结论。seed 42 的选牌数量覆盖 0..5，seed 43 覆盖 0..4。详细计数见 `az_choice_sets_mechanism_evidence.json`。

### 最终测试

每行 150 场；network 无搜索，search 为 8 simulations。两个 seed 共用该版本的固定测试配方。

| seed／模式 | 初始胜率 | 最终胜率 | 最终超时率 | 平均决策 | 最终平均效用 |
|---|---:|---:|---:|---:|---:|
| 42 network | 7.3% | 75.3%（113/150） | 0 | 17.44 | 0.4842 |
| 43 network | 74.7% | 80.7%（121/150） | 0 | 15.09 | 0.5789 |
| 42 search | 1.3% | 40.0%（60/150） | 0 | 16.85 | -0.1864 |
| 43 search | 19.3% | 43.3%（65/150） | 0 | 18.97 | -0.1254 |

初始和最终、两 seed、两模式全部测试均为 **0 异常、0 非法动作、0 超时**。最终 network 单场最多 41／34 次决策，search 为 36／38。随机合法基线胜率 34.7%；旧规则基线不支持该内容。search 不参与晋级。

network 配对效用差 95% 区间为 seed 42 `[1.22618, 1.31405]`、seed 43 `[0.11016, 0.13416]`；胜率差区间分别为 `[0.65333, 0.70667]`、`[0.05333, 0.06667]`。两者均满足该版本冻结检验，`learning_gain=passed`。

### 中途真实超时及结论边界

seed 42 第一轮候选在 `set-validation-182-0-84` 出现过一场 100 回合、318 决策的超时。只出现 1 次 Purity 且正常结束；其余主要是普通回合，模型长期优先防御而没有结束战斗。完整复现及模型摘要见 `az_choice_sets_timeout_diagnostic.json`。这个模型下一轮作为冠军复评时同一案例再次出现，不能计作两个独立失败案例。该 seed 后两轮候选及最终模型验证没有超时，seed 43 各轮候选也没有超时。

本批解决的是**可逆选择点击造成的策略循环**；最终测试也未见其他超时，但不据此保证所有未来构筑都不会僵持。没有改奖励、放宽门槛、删除超时结果、添加强制判胜或超过三轮。宏动作、输出头和初始化均变化，且本批换了隔离测试，旧版 19.3%／16.7% 与本批 0 的差异是历史结果对照，不是同模型同样本的严格因果消融。

126 层只有 150 场（102 层单样本、24 层双样本），分层 bootstrap 不能估计单样本层内部方差，也没有留出整类构筑。少量训练通过不等于通用战斗质量达成。

复算器检查 checkpoint／代码／运行器摘要、晋级链、Replay 与标签、seed 空间及原始统计，结果为 `artifact_and_statistics_checks_passed`，见 `az_choice_sets_verification.json`。该工具复用项目评估统计实现，不是独立跨模型审查；最终模拟未重复执行，仅上述既有验证超时做了定向复现。

当前可继续 G1 其他生成／变形／已知堆底的合并批次；保持新机制两轮 smoke、各 seed 三轮快速验证约定。
