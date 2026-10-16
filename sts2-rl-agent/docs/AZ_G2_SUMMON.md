# G2.2b：Fogmog／Eye 召唤复活与 Dazed

日期：2026-10-12。新增内容 `g2-summon-v1`。接续 G2.2a 的终局修复和防刷奖励基础，完成真实环境、公开观察、粒子、编码、动作、Replay、评估和运行入口接入。最终测试与学习结论以下方验收产物为准。

## 内容和依赖

保留 G2.1 的八种遭遇，新增原生 `setup_fogmog_normal`。仍为 Ironclad、ascension 0、六个构筑家族；共九遭遇、162 个家族／遭遇／HP 层。卡池仍为 28 个初始 ID，另有 GiantRock、Soul、Dazed 三个仅生成 ID，共 31 个 ID。Dazed 只有普通 token，不能升级；词表含 PAD 共 62。

- Fogmog 首回合召唤 6 HP Eye；Eye 下一敌方回合开始行动。Fogmog 的 Swipe 有伤害加力量，分支为原生加权随机选择，公开行动序列和当前意图确定当前可见阶段；未来分支独立采样。
- Eye 每次 Distract 向弃牌堆添加 3 张 Dazed。受击倒后留在槽位 1，不能被命中，下次行动恢复满血并恢复 Distract。主怪死亡即可胜利，小怪不扩大终局伤害预算。
- Dazed 不可出牌、不可升级、带虚无，回合末即使 Equilibrium 存在也会消耗。Purity、Burning Pact、Armaments、Headbutt、已知堆顶和重洗等组合均按真实规则处理；Armaments 选到 Dazed 是原生无升级效果，不制造 `DAZED+` 或提前登记升级。
- 初始名册与已召唤对象分别保持稳定身份；追加只允许 Fogmog→Eye。同槽替换、交换、删除、未审计复活／新增对象均拒绝。

本批不代表任意召唤、主怪复活、Boss 阶段或所有 G1 机制已支持。Reave 仍是受控跨角色卡牌测试，不代表完整 Necrobinder。

## 原生参考和修复

参考本地反编译 `Fogmog.cs`、`EyeWithTeeth.cs`、`Dazed.cs`、`IllusionPower.cs`、`MinionPower.cs`、`MonsterMoveStateMachine.cs`，以及对应 Python 实现。保留 G2.2a 的主怪／小怪终局修复。

本步修复另一处原生转换差异：C# 的 `StateLog` 在选择行动时写入，Python 在行动完成时写入。Illusion 的复活后继不能直接取 Python `state_log[-1]`，否则刚复活又被击倒时会把上次 REVIVE 作为后继，造成持续复活。现在取被打断的当前行动；Eye 的粒子后继固定回到其公开 Distract 行动。连续三次击倒／复活及之后实际生成 Dazed 均有真实环境／粒子对照。

## 公开信息、版本和奖励

信息版本 `summon-information-v1`，编码 `az-summon-encoder-v1`，numeric 2738、卡特征 24、动作 `combat-summon1024-v4`。所有活跃／死亡／复活槽位的 HP、能力、意图、主次身份和已发生行动分别编码。只由可见意图和公开历史推断 Fogmog 状态，不读取真实 AI 私有日志或未来 RNG。粒子恢复自己的状态机和随机流，保留分支隔离。

生成事件新增严格整数 `count`：Anger／Reave 为 1，Eye Distract 为 3；带计数的事件与逐敌已执行行动对应，并参与牌堆守恒。仅完整敌方回合记录行动；Fogmog 在 Eye 行动前击杀玩家时，不编造 Eye 行动或 Dazed 生成。

容量按保守上界 20 初始牌＋最多 400 Anger 副本＋最多 100×3 Dazed，提升为 720。已知堆顶、堆底和弃牌顺序全部扩展，不能截断 Headbutt 候选。动作 1024 容纳完整单选候选；Purity 仍是最多九候选的原子集合动作，512 以上编号在该选择中不合法。

奖励 `primary-roster-hp-v5` 已注册，环境、搜索、Replay、评估统一调用 G2.2a 的不可变生命周期账本：仅初始 primary HP 构成分母，召唤小怪与反复击倒不累计进度，过程奖励为零，终局系数保持不变。新增完整逐敌生命周期记录；JSON 重载不改变奖励。旧内容继续使用原有奖励／schema，拒绝直接加载不兼容 checkpoint。

## 冻结划分和验证预算

配置 `configs/az_g2_summon_v1/`；清单 `data/az/g2_summon_v1_manifest.json`。

- 训练 seed 42、43；环境 seed 偏移 `5*2^27`。本次实际训练、验证和测试不重叠，也与上一批实际清单不重叠；不声称与所有历史版本所有可能配置均全域隔离。
- 固定 validation master 185，256 场；test master 283，180 场。最终覆盖全部 162 层，其中 144 层一场、18 层两场；两个训练 seed 共用配方。这是同家族快速验证，区间不代表广泛组合泛化不确定性。
- 两轮 smoke：seed 42，每轮 162 场、4 次更新、4 simulations。
- 正式：每 seed 三轮，每轮 162 场、16 次更新、batch 64，采样／search 为 8 simulations。总训练预算 972 场、96 更新；实际数值从产物读取。
- 仅 network 的 256 场配对效用／胜率门槛决定晋级；search 为观测。无增益也停止于三轮，不追加轮数。

工程回归日志 `docs/az_summon_tests.txt`。开发期的一次并行测试因主进程与新子进程加载了不同 schema 而被兼容性检查拒绝，原日志保留在 `output/az_summon_development_before_schema_freeze.txt`；随后停止源码修改再运行全量回归。历史 expanded-v3、G1.5、G2.1 的保存 schema 与当前对应实现逐项比较一致。

## 实验观察流程和产物

实验启动时沿用了当时的外部观察入口，观察包装器曾因返回文本不符合 JSON 格式而失败，训练子进程继续完成。用户随后更新根目录 AGENTS.md：现在由 Codex 直接核查进程与产物，不再委派外部模型或 CLI 观察；`.handoffs/` 仅保留为历史记录。观察器失败不等于训练失败，完成结论以下列实际产物为依据。

最终入口：`output/az_g2_summon_v1_quick/report.json`，复算 `docs/az_summon_verification.json`，机制与超时证据 `docs/az_summon_mechanism_evidence.json`，汇总验收 `docs/az_summon_acceptance.json`。尚未生成的产物不等于完成。复算程序重算原始记录、哈希与统计，不是独立重新模拟全部最终战斗。

后续按 spec 推进主怪复活／阶段切换与 Boss 的完整依赖；本批的成绩不等于全 G2 或通用策略质量达成。

## 最终验收（2026-10-12）

冻结源码后的全量回归：6,532 passed、1 skipped、30 subtests passed，253.61 秒。两轮 smoke 通过，实际 324 场、8 更新，没有查看最终测试。

正式 seed 42／43 各三轮、486 场、48 更新，各晋级两次，最终均为 candidate-1.pt；合计 972 场、17,104 决策、96 更新。正式运行含最终测试耗时 741.76 秒（约 12 分 22 秒，不含前置 smoke、后续复算与观察器等待）。

| 策略 | seed 42 初始 → 最终胜率 | seed 43 初始 → 最终胜率 |
|---|---|---|
| network | 50.6% → 77.8% | 38.9% → 80.6% |
| search（8 simulations，仅观察） | 8.9% → 52.8% | 6.7% → 46.1% |

每项最终测试 180 场，随机合法基线 36.1%。network 双 seed 学习增益通过；晋级仍只依据 network。search 仍明显弱于 network，不据此宣称高质量搜索或通用能力。

机制证据：108 场 Fogmog 训练均观测到召唤，其中 95 场观测到复活，合计 531 个 Eye 复活中决策、922 个 Dazed 在手决策、1,086 张已观测生成 Dazed。190 次 Purity 提交均观测到退出，没有重复选择迹象。训练零超时；32 组验证／初始与最终评估合计 7,584 场，零超时、零异常、零非法动作。该结果仅适用于本批记录，不是任意未来对局不会超时的保证。

原始产物与统计复算状态为 `artifact_and_statistics_checks_passed`。汇总验收已写入 `docs/az_summon_acceptance.json`，工程、训练与本批学习增益分别通过。G2 全量和通用高质量策略仍未完成；下一步为主怪复活／阶段切换与 Boss 的依赖审计和代表内容接入，不自动开启下一批实验。
