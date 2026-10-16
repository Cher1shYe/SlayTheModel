# G1.2：手牌消耗选择接入

2026-10-09。工程接入与两轮 smoke 完成；正式双 seed 各十轮已启动，最终测试尚未开始。训练实时状态另见运行目录。本批不代表 G1 整体完成。

最新核查：本运行没有完成，seed 42 完成 4 轮，seed 43 完成 3 轮后停在下一轮验证；无最终报告、无存活同目录协调器。已保存中断状态和源码，不重启十轮。下文启动段落为历史快照。

## 已接通的内容

新增 True Grit 和 Burning Pact，均支持普通／升级版，卡池 16→18；仍为 Ironclad、ascension 0、七种单敌遭遇、六家族／126 层。消耗家族现在强制包含 Ashen Strike、True Grit、Burning Pact，其余非基础家族允许抽取新卡。

True Grit 普通版使用独立粒子 RNG 随机消耗；升级版进入手牌单选。Burning Pact 在单选消耗之后抽 2／3 张。零／单候选由原生引擎自动结算，多候选才产生选择动作。原生能力、消耗收益、力量、Slow、Artifact 等仍使用现有引擎。

选择阶段动作 0 的语义是确认／跳过，动作 1+i 选择候选 i；本批两种单选均必选，因此 0 不合法。选择也计入智能体决策上限；用尽决策预算是战斗 time_limit，不把搜索预算当成超时。

## 公开信息与重建

公开状态保存不可变手牌状态、候选顺序／索引、限制、已选集合、公开 play pile 中的待完成卡牌。观察不读取真实 `_pending_play`、resolver 闭包、未来 RNG、未知抽牌顺序或 AI 日志。

粒子从公开待完成卡牌确定有限的续执行机制，在假想世界创建新回调及引擎 continuation。费用和格挡已在选择前结算，重建不再结算；消耗、抽牌、完成出牌和 after-play 钩子按原引擎顺序执行。历史把“已开始的出牌”与“仍待完成的出牌”区分，重建 Slow 计数时排除待完成卡牌，选择动作不额外增加出牌次数。

单张卡状态 capture/restore 已用于 G1 观察／粒子；本批注册静态字段策略，临时费用、保留、生成牌及变化牌仍不开放。不能因为通用表示接口支持这些字段就声称所有生命周期已经接入。

## 冻结契约

- content：`g1-choices-v1`；information：`g1-information-v1`；encoder：`az-g1-encoder-v1`。
- 卡词表 37，手牌特征 24，numeric 286，动作 115。候选仅来自手牌，最多 10；其他来源或超容量明确拒绝。
- 奖励仍为 `win-timeout-hp-v3`；晋级仍为 `network-only-v1`，search 为观测。
- train seed 偏移 3×2^28，validation/test master seed 176/274，与 expanded-v3 隔离。
- configs：`configs/az_g1_choices_v1/`；配方：`data/az/g1_choices_v1_manifest.json`。
- 新模型独立初始化，未进行权重迁移；拒绝旧 schema checkpoint／Replay 混入新运行。

## 验证

完整回归 1,132 项、8 个子测试通过。最后仅调整 G1 不可变类型检查与假想牌组引用，之后重新通过 178 项 G1 测试。日志分别为 `az_g1_integration_tests.txt` 和 `az_g1_final_targeted_tests.txt`。

覆盖 126 个组合完整随机战斗的逐步真实／粒子一致性（测试中显式对齐隐藏随机条件，仅用于引擎对照）；选择根节点改变真实隐藏牌序、RNG、私有 AI 日志／续执行对象后，公开状态及固定搜索访问分布相同；真实世界和兄弟粒子隔离；选择阶段超时；旧版本拒绝；串并行采样逐行一致；Replay 恢复与 Learner 有限更新。

测试通过只证明本批审计范围，没有穷尽所有卡牌／能力组合。

## 运行

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_g1.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --g1 --smoke --iterations 10 --output output/az_g1_choices_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --g1 --iterations 10 --output output/az_g1_choices_v1 --workers 8 --smoke-evidence output/az_g1_choices_v1_smoke/smoke_report.json
```

这些是冻结入口，不要重复启动正在运行或已完成的目录。两轮 smoke 通过且代码摘要一致后才允许正式训练。正式训练各 seed 10 轮，保留 256 场采样／200 更新／256 场验证，训练／验证搜索 64／256。两个最终模型共同冻结后才进行各 150 场测试，原始报告路径 `output/az_g1_choices_v1/report.json`。

后续先收尾本批结果，再继续 G1 的战斗内升级、生成来源账本、已知牌序、临时费用／保留和 X 费。不得与依赖同一源码的在途训练混改源代码。

## 本次验收与启动快照

两轮 smoke 通过：252 场、4,459 次决策、8 次更新，其中 56 场实际出现选牌，共 114 次选择决策。没有运行最终测试。吞吐粗略外推正式双 seed 十轮约 5.13 小时，不含最终测试，非完成时间承诺。Windows 原子写入冲突均已通过重试恢复。

正式运行启动器 PID 75032；启动快照 `{"iteration": 0, "phase": "collect", "seed": 42, "stage": "training"}`。这是快照，不保证进程持续存活。机器可读证据见 `az_g1_choices_acceptance.json`；实时看 `output/az_g1_choices_v1/progress.json`，最终结果看 `report.json`。源码在本批在途训练期间冻结。
