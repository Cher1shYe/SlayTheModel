# G2.1：多敌、稳定目标、群攻与固定名册奖励

日期：2026-10-11。工程回归、两轮 smoke、双 seed 各三轮、最终测试、产物统计复算和超时诊断均已完成；双 seed network 学习增益通过。G2.1 本批完成，尚不宣称 G2 全量完成。

## 本批范围与依赖审计

在 G1.5 的 30 种 ID（28 种初始牌、2 种生成 token，均含升级）之上接入原生 `setup_nibbits_normal`。保留七种单敌遭遇，共八种遭遇、六种构筑家族、三个 HP 档、144 个分层。双 Nibbit 使用 40/60/80 玩家开局 HP，敌方各 42–46 HP。没有额外增加卡牌 ID；用现有 Thunderclap、Whirlwind、Stomp、力量与易伤组合检验多目标机制。

本地规则参考：`decompiled/MegaCrit.Sts2.Core.Models.Encounters/NibbitsNormal.cs`、`...Models.Monsters/Nibbit.cs`、`...Models.Cards/Thunderclap.cs`、`...Models.Cards/Whirlwind.cs`，以及 `sts2_env/encounters/act1.py`、`monsters/act1_weak.py`、`core/combat.py`、`gym_env/action_space.py`。前排从 Slice（6 伤害、5 格挡）开始，后排从 Hiss（力量 +2）开始，随后各自循环；同伴死亡不重设存活者周期。native Nibbit 的 Slice 只暴露攻击图标，新观察根据 Nibbit 独有的公开 6 伤害意图补足 `ATTACK_DEFEND`，不读取私有状态机 ID。上述是本批规则审计，不代表原游戏所有机制已对齐。

| 环节 | 契约 |
|---|---|
| 内容 | `g2-multi-v1`；固定名册 1–2 敌；多敌仅双 Nibbit |
| 信息 | `multi-information-v1`；逐槽血量、初始 HP、格挡、能力、公开意图和已完成行动历史 |
| 动作 | `combat-multi512-v3`；512 容量，出牌目标仍为原生槽位，Purity 保留完整集合动作 |
| 编码 | `az-multi-encoder-v1`；numeric 1804，卡特征 24，词表 61 |
| 奖励 | `fixed-roster-hp-v4`；全敌聚合、完整逐敌 HP 元数据、新 Replay 隔离 |
| 初始化 | 独立随机模型；未迁移旧权重 |

原生敌人列表在死亡后保留对象位置；死亡时引擎将 `escaped=True` 作为逻辑移除标记。新边界接受零血死亡标记，拒绝带血逃跑，不压缩死亡槽位。逐目标动作掩码仍使用原始索引。拒绝新增／删去／重排／替换名册、复活和最大血量变化。信息与粒子容量当前为 2，超过容量明确拒绝，不将动作层原有 5 个目标位误称为已支持 5 敌。

Headbutt 的伤害可击杀一个敌人而战斗继续；公开记忆保存原目标，粒子在选牌续接中绑定相同死亡槽位。Reave 击杀非最后一敌仍生成 Soul；击杀最后一敌遵守原生终局短路，不虚构生成事件。Whirlwind 消耗 X 一次，多次攻击逐目标结算并跳过死亡槽位。Thunderclap 先伤害，后给仍可击中的敌人易伤。

每个完整敌方回合只为当时存活者追加公开动作。如果玩家在敌方执行顺序中途死亡，保留回合前的历史，避免为未执行的后排虚构行动；终局信息不再重建搜索粒子。G1 的生成、升级、变形、抽牌前后缀、生命周期和完整集合选择继续使用原契约。

## 奖励冻结

设固定初始名册为 R：`E0 = sum(initial_hp[i])`，`Ef = sum(max(0, final_hp[i]))`，`h = clip(player_final_hp/player_initial_hp,0,1)`，`d = clip((E0-Ef)/E0,0,1)`。系数保持原约定：win 为 `0.8+0.2h`，time_limit 为 `-0.2+0.4d`，death 为 `-1+0.2d`；过程奖励零。

整组敌人全部败北才可胜利；单只死亡不是终局。分母使用每只敌人的初始 HP，允许它与最大 HP 不同。记录每个固定槽位的 monster ID、initial/final/max HP，适配器、搜索、Replay、评估、复算均验证逐敌记录与总量一致。净掉血只在终局支付一次，恢复血量会降低进度，重复伤害不会累计刷分。此版本没有召唤或复活语义；这些机制必须在下一批另行冻结奖励，不能默认把新怪加入分母。

## 配置与验证预算

配置 `configs/az_g2_multi_v1/`，清单 `data/az/g2_multi_v1_manifest.json`，入口 `scripts/prepare_az_multi.py`。训练 seed 42/43，每 seed 3 轮，每轮 144 场、16 次更新、batch 64、8 simulations。晋级固定 256 场配对验证，仅 network 作门槛；search 同为 8 simulations，仅观测。两轮 smoke 为 seed 42、每轮 144 场、4 次更新、4 simulations。最终每 seed 150 场，覆盖 144 层（138 层 1 场、6 层 2 场）。样本很稀疏，不将分层 bootstrap 称为广泛组合不确定性的保证。

训练环境 seed 区间 `[14*2^27,15*2^27)`，master <128；本批验证／测试 master 为 184/282，使用既有 split offset 规则，与本批训练不相交。这个训练数值区间与历史 topdeck 版本部分复用，但内容版本、模型和 Replay 全部隔离；本批最终测试与历史批次不同。仍是同构筑家族评估，没有留出整个家族，不声称组合泛化。

```powershell
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --multi --quick --smoke --iterations 3 --output output/az_g2_multi_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --multi --quick --iterations 3 --output output/az_g2_multi_v1_quick --workers 8 --smoke-evidence output/az_g2_multi_v1_smoke/smoke_report.json
```

回归包括 144 层完整战斗的逐决策真实／粒子对照、隐藏顺序与 RNG 扰动、分支与 ID 隔离、串并行 Replay／训练一致性、前后排死亡后目标稳定、群攻多段及易伤时序、致死 Headbutt 续接、Reave 非最终／最终击杀差异、奖励总量／初始 HP／净伤害／伪造记录、终局优先于预算上限和旧版本拒绝。

完整适用回归 **2,524 项及 8 个子测试通过，171.14 秒**，其中新增专项 160 项。最初回归发现新增逐敌记录的 tuple／JSON list 差异导致缓存返回不一致，修复为统一 JSON 列表并补了双敌缓存往返测试；修复前日志保留在 `output/az_multi_regression_before_cache_fix.txt`，最终回归为 `docs/az_multi_tests.txt`。此前专项还修正了死亡时的原生 `escaped` 标志解释；没有修改原生战斗／卡牌实现。对比五个历史主要版本，encoder schema 完全一致。

两轮 smoke 通过：288 场、4,367 决策、8 更新；采样 28.134 秒，约 155.223 决策／秒。根据 smoke 线性估计正式训练和轮间验证 4.86 分钟，不含最终测试；实际耗时和模型效果以正式报告为准。smoke 使用 144 场验证，不满足正式 256 场晋级资格，零晋级不能解释为失败。

## 验收结果

正式入口 `output/az_g2_multi_v1_quick/report.json`，已完成，无需重启。两 seed 各完成 3 轮、432 场、48 更新；均晋级两次，最终模型均为各自目录中的 `candidate-1.pt`，第三轮均未晋级。实际共 **864 场、14,671 决策、96 更新**。正式运行含最终测试 **399.12 秒（6 分 39 秒）**；不含开发、回归、smoke、收尾复算和定向复现。

| seed／模式 | 初始 → 最终胜率 | 最终平均效用 | 平均 HP／胜局 HP | p95 决策延迟 | 超时 |
|---|---|---:|---:|---:|---:|
| 42 network | 0.0% → **77.3%（116/150）** | 0.51554 | 20.71／26.78 | 3.24 ms | 0 |
| 43 network | 68.7% → **83.3%（125/150）** | 0.62407 | 21.77／26.12 | 1.66 ms | 0 |
| 42 search，8 simulations | 3.3% → 27.3%（41/150） | -0.42454 | 3.71／13.56 | 53.53 ms | 0 |
| 43 search，8 simulations | 14.0% → 40.7%（61/150） | -0.16961 | 6.87／16.89 | 56.72 ms | 1（0.67%） |

随机合法基线胜率 40.7%、平均效用 -0.16944、平均 HP 7.36，无超时。规则基线不兼容扩展牌池，未伪造评估。search 明显弱于 network；seed 42 search 低于随机基线，seed 43 search 胜率与随机相同，不能以对弱初始化的增益宣称高质量搜索。

双 seed 的 network 最终配对门槛均通过，学习增益 `passed`：seed 42 效用差 CI95 `[1.48448,1.50890]`，胜率差 CI95 `[0.76667,0.78000]`；seed 43 分别为 `[0.25021,0.29464]`、`[0.13333,0.16000]`。两种子共享冻结测试配方，138 个单样本分层使区间偏窄；这些区间是冻结分层重采样规则下的结果，不代表广泛未知组合不确定性。seed 42 随机初始化为零胜率，不能把其大幅增益当作通用能力证据，也不直接比较不同批次的总分。

network 最终遭遇分组（胜场／场数）：

| 遭遇 | seed 42 | seed 43 |
|---|---:|---:|
| Shrinker Beetle | 21/21 | 20/21 |
| Fuzzy Wurm Crawler | 19/21 | 21/21 |
| 单 Nibbit | 16/18 | 16/18 |
| 双 Nibbit | **14/18** | **16/18** |
| Bygone Effigy | 7/18 | 7/18 |
| Byrdonis | 7/18 | 11/18 |
| Cubex Construct | 15/18 | 17/18 |
| Mawler | 17/18 | 17/18 |

双 Nibbit 的低预算 search 最终仅 0/18、4/18，目标／群攻机制正确不等于 search 已学好。精英仍是 network 弱项。家族／血量／完整分层结果保留于原始 `test-*-*.json` 和汇总报告。

训练实际机制证据：108 场双怪、1,964 次双怪决策；前排死亡而后排存活的公开决策 141 次，向该后排出牌 40 次。双怪目标出牌前排 365 次、后排 360 次；双怪群攻 42 次，其中 Whirlwind 系列 30 次、Stomp 系列 11 次、Thunderclap+ 1 次。双怪 Headbutt 选择 23 次，其中后排目标 12 次。167 次 Purity 集合提交全部在下一公开决策退出选择。实际训练的群攻覆盖不均，Thunderclap 两升级分支的完整交互依赖定向测试，不能宣称训练覆盖了所有组合。

**超时诊断**：训练和全部正式验证均无超时，所有初始测试及最终 network 均无超时。仅 seed 43 最终 search 的 `multi-test-282-0-139`（单 Mawler、exhaust 家族）在 308 决策／100 回合超时，玩家剩 1 HP，敌方剩 36/72 HP，效用 0。按冻结 checkpoint、相同场景索引与搜索 seed 精确复现：第 41 次决策时所有攻击牌已被消耗，最终活跃牌仅 Burning Pact 与 Defend Ironclad+，之后通过抽牌／防御维持存活；Purity 仅选择一次，耗尽 Anger+ 后正常退出。没有选择／取消循环。保留真实策略僵持，不强制判胜、不删除超时、不追加训练。原始逐动作证据为 `docs/az_multi_timeout_diagnostic.json`，复现入口 `scripts/diagnose_az_multi_timeout.py`。该测试案例现已用于诊断；若据此迭代，下批必须使用新的独立最终测试。

所有正式验证及初始／最终测试异常、非法动作均为零。`scripts/verify_az_continuous_results.py` 复算版本、模型／源码／runner 哈希、Replay 标签、逐敌 HP 聚合、晋级链、实际训练量及最终统计，通过 `artifact_and_statistics_checks_passed`，结果为 `docs/az_multi_verification.json`。机制与超时汇总为 `docs/az_multi_mechanism_evidence.json`，入口 `scripts/analyze_az_multi.py`；验收索引为 `docs/az_multi_acceptance.json`，完成源码快照为 `output/az_g2_multi_v1_quick/source_completed.zip`。复算使用项目评估代码，不是独立跨模型审查，也不重跑全部最终模拟；仅上述单例另外复现。

## 后续

G2.1 只覆盖固定正常多敌。下一批处理召唤／复活及对应奖励语义，再接阶段切换和 Boss；敌方状态牌与复杂随机 AI 也仍有缺项。G1 随机生成、任意变形、逐卡临时保留等未覆盖项继续保留；G3 遗物／药水、G4 全角色与内容闭合、G5 迁移／规模学习、G6 未见组合质量验收均未完成。
