# G2.3b2：TestSubject Boss 完整训练接入

2026-10-15 补充：后续自然完整战斗诊断发现复活死亡标记、状态牌升级账本和 Burn 保留前缀三项覆盖缺口，已在 [G2.3c](AZ_G2_BOSS_CURRICULUM.md) 修复并补测。本报告记录原冻结版本的实际结果，不将其有限阶段覆盖解释为后续阶段全部正确；旧模型及原始结果保留。

日期：2026-10-13。接续 G2.3a 的公开阶段与奖励基础、G2.3b1 的原生敌人重建及容量组件。本批新增独立内容 `g2-boss-v1`，接通真实环境、公开观察、搜索粒子、生成账本、编码、Replay、评估与训练入口。工程完成、训练完成及策略质量分别验收，最终结果见文末。

## 内容与版本

保留上一批九种遭遇，新增 `setup_test_subject_boss`；六家族、十遭遇、180 个家族／遭遇／HP 层。初始卡池仍为 28 个 ID，生成牌为 GiantRock、Soul、Dazed、Burn、Wound，共 33 个 ID，词表含 PAD 共 64。Burn／Wound 只能生成，没有伪造升级版本。仍为 Ironclad、ascension 0；Reave 是受控跨职业机制测试。

信息版本 `boss-information-v1`；编码 `az-boss-encoder-v1`，numeric 7026、卡特征 24；动作 `combat-boss4096-v1`。2145 牌容量上界覆盖最多 100 回合／400 决策下的增长；已知堆顶、堆底与弃牌顺序均扩展，单选候选不截断。Purity 保留原子集合动作，确认不被误记为敌方回合。

原生规则参考与容量证明沿用 [阶段基础](AZ_G2_BOSS_PHASE_FOUNDATION.md) 和 [重建组件](AZ_G2_BOSS_RECONSTRUCTION.md)。本批没有扩大到其他 Boss、任意召唤、遗物、药水、其他角色或所有 G1 机制。

## 公开状态、生成及终局

- TestSubject 三阶段固定 100／200／300 HP。公开击倒、复活及已完成行动决定阶段、递增爪击次数与 Nemesis／Intangible；快照包含公开 HP、格挡和能力，不包含原局对象、私有 AI 日志或未来 RNG。
- 搜索从快照创建独立原生状态机，恢复自己的闭包计数与能力生命周期；源状态和兄弟分支保持隔离。每一步通过统一适配器更新阶段事件与牌堆守恒。
- 第二阶段 Wound 按实际未格挡命中数登记；公开计算考虑 Burn 先消耗格挡、力量和易伤。第三阶段 Growl 每次生成三张 Burn，账本与已完成 Growl 次数交叉检查。终局中断的敌方回合不编造完成事件。
- 玩家被爪击击杀时，原生 AI 可能已推进下一次意图次数但该回合没有完整结束。终局快照验证公开 HP／能力与奖励，不要求它具备可继续行动的意图；非终局继续严格验证意图。
- 奖励 `finite-primary-phases-v6` 已注册。Boss 固定预算 600 HP，复活不刷新分母，治疗撤回进度。其他九种遭遇复用 V5 主怪预算语义，但使用 V6 版本隔离。环境、搜索、Replay、评估和晋级复算统一调用奖励函数。
- 旧 schema 不变，旧内容拒绝 Boss 状态与 V6；新旧 checkpoint／Replay 不能直接混用。本批从独立随机网络初始化，没有宣称权重迁移。

## 机制覆盖矩阵

| 代表机制 | 引擎／公开状态 | 粒子／编码／动作 | Replay／评估 | 回归边界 |
|---|---|---|---|---|
| 主怪两次复活、最终死亡 | 稳定槽位、公开事件 | 独立原生闭包、阶段特征 | V6 固定三阶段预算 | 受控三阶段测试；自然训练到达率另列 |
| 递增爪击与 Wound | 未格挡命中生成 | 状态牌与牌堆守恒 | 生成后观察可重载 | 第二阶段完整适配器轨迹 |
| Burn、Nemesis／Intangible | 伤害与回合交替 | 生命周期恢复 | 统一终局复算 | 第三阶段完整适配器轨迹 |
| 状态牌与选择／已知牌序 | 原生状态牌工厂 | Purity、单选末位、堆顶／堆底 | 编码与网络更新 | 2145 为保守容量上界，不是训练已观测数量 |
| 旧九种遭遇 | 保留原规则 | 新 schema 下逐场对照 | V6 内复用主怪预算 | 180 层整体逐步一致性 |

## 验证与冻结配置

配置 `configs/az_g2_boss_v1/`，清单 `data/az/g2_boss_v1_manifest.json`。训练环境 seed 偏移 `7*2^27`；validation master 186，test master 284。本批实际训练／验证／测试共 1516 条配方，环境 seed 不重叠，与 157 份历史运行清单也无重叠（`az_boss_seed_isolation.json`）；不声称所有旧版本所有可能参数均全域隔离。

16 份保存 schema 与当前实现逐项一致（`az_boss_legacy_schema_check.json`）。全量回归 6831 passed、1 skipped、30 subtests passed；随后新增三项隔离／评估／隐藏信息测试，最终 Boss 集成文件 197 passed，相关阶段／重建／并行评估 106 passed，晋级／恢复兼容回归 79 passed。日志分别为 `az_boss_tests.txt`、`az_boss_integration_tests.txt`、`az_boss_final_contract_tests.txt`、`az_boss_evaluation_contract_tests.txt`。

新增集成测试覆盖 180 个分层场景逐步原局／粒子一致性、第二和第三阶段完整轨迹、隐藏牌序／RNG 扰动下的固定搜索、串行／spawn、Replay 重载、网络更新、版本拒绝、V6 评估复算与数据隔离。机制测试通过不意味着训练策略已经到达所有阶段。

冻结预算：两轮 smoke，seed 42，每轮 180 场、4 更新、4 simulations；正式 seed 42／43 各三轮，每轮 180 场、16 更新、batch 64、8 simulations。正式晋级使用 256 场配对验证，只有 network 决定晋级，search 仅观察。最终每 seed 初始／最终模型、network／search 各 180 场，另有随机合法基线。独立测试在两 seed 最终模型共同冻结后才执行。

训练入口：`scripts/run_alphazero_continuous.py --boss --quick --iterations 3`，正式运行需提供同源码 smoke 证据。只读复算 `scripts/verify_az_continuous_results.py`；机制统计 `scripts/analyze_az_boss.py`。运行由 Codex 直接启动和核查，没有外部模型／CLI 观察委派或定时任务。

## 最终验收

两轮 smoke 通过：360 场、8 更新，未访问最终测试。正式 seed 42／43 各三轮、540 场、48 更新，共 1080 场、18413 决策、96 更新；分别晋级 1／2 次，最终冠军为 `seed-42/candidate-0.pt`、`seed-43/candidate-1.pt`。正式运行含最终测试 943.999 秒，约 15 分 44 秒，不含前置 smoke 和只读复算。

| 模式 | seed 42 初始 → 最终胜率 | seed 43 初始 → 最终胜率 |
|---|---|---|
| network | 70.6% → 77.2% | 48.3% → 72.2% |
| search | 15.6% → 31.7% | 9.4% → 36.1% |

每项测试 180 场，恰好覆盖全部 180 层；两个 seed 共用测试配方。随机合法基线 29.4%。network 双 seed 的冻结配对学习增益通过；search 单列观察，不参与晋级。单层仅一场，区间不能证明广泛组合质量。新内容与初始化、隔离测试均不同，不把跨版本总分比较当作因果结论。

**Boss 策略尚未达标**：最终两个 seed、两种模式的 TestSubject 子组均为 0/18 胜。108 场 Boss 训练中，seed 42 没有到达第二阶段；seed 43 仅 1 场到达第二阶段；均没有到达第三阶段。训练中没有观测到 Burn／Wound 在手决策。三阶段机制依赖受控规则回归验证，不能据此宣称网络已学会后续阶段。

训练零超时；32 组验证／初始与最终测试合计 7584 条评估记录，零超时、零异常、零非法动作。这里包含重复冠军评估／缓存记录，不表示 7584 场独立新对局。200 次 Purity 提交均观测到退出。Dazed 在手决策共 1008 次，保留了旧召唤机制覆盖。

结果入口 `output/az_g2_boss_v1_quick/report.json`；冻结模型及哈希 `frozen_final_models.json`；完整家族／遭遇／HP 分层结果位于各 `test-*-*.json`。机制证据 `docs/az_boss_mechanism_evidence.json`。原始记录只读复算状态见 `docs/az_boss_verification.json`，汇总见 `docs/az_boss_acceptance.json`；复算不等于独立重新模拟全部战斗。

下一步优先补齐 Boss 后续阶段可达的训练／验证覆盖，并检查现有牌组分布的能力限制；不能仅追加本批轮数或放宽晋级、奖励和终局条件。后续若依据本批测试调整内容或课程，须使用新的隔离最终测试。G1／G2 全量、G3 遗物药水以及通用高质量策略仍未完成。本批结束，不自动启动下一批。


只读复算已通过：`artifact_and_statistics_checks_passed`，模型／源码哈希、Replay 标签、六次晋级决定及最终统计一致。工程和本批学习增益通过，Boss 策略与通用质量未通过。
