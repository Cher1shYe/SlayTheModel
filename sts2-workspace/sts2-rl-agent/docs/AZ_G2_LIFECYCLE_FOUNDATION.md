# G2.2a：召唤／复活的终局与奖励基础

日期：2026-10-11。此步交付原生终局修复与可测试的奖励契约；**尚未发布新的 AZ 内容、编码、模型或训练成绩**。G2.1 的全部历史结果保留。

## 原生规则审计与修复

审计本仓库 `decompiled` 中的 `CombatManager.cs`、`Creature.cs`、`MinionPower.cs`、`IllusionPower.cs`、`ReattachPower.cs`、`Fogmog.cs`、`EyeWithTeeth.cs`：

- `CombatManager.IsEnding` 检查存活的 **primary enemy**，然后检查真正阻止终局的钩子。MinionPower 将持有者标记为 secondary enemy。
- Fogmog 的首个行动召唤 EyeWithTeeth。Eye 为 6 HP，带 Illusion 与 Minion；被击倒后进入不可命中的复活行动，再恢复满血。Eye 存活或复活中都不阻止主怪死亡后的胜利。
- IllusionPower 没有 `ShouldStopCombatFromEnding` 覆盖；原 Python 实现自行添加的阻止钩子不符合参考。已移除，并通过通用 `owner_is_secondary_enemy` 属性和 `Creature.is_primary_enemy/is_secondary_enemy` 接入胜负判定。
- ReattachPower 同样没有该阻止钩子。全部节肢均已死亡时，应结束战斗，不能被其他节肢遗留的 `is_reviving` 标记拖住。已移除错误钩子；`do_reattach` 在没有其他存活节肢时不再复活。
- 其他真实的终局阻止钩子保留。此步没有宣称所有 Boss／死亡钩子均已完成审计。

定向测试在修复前真实复现 **3 项失败**：主怪死后小怪存活、主怪死后小怪复活中、全部节肢死亡。反复复活原槽位的对照测试原本通过。修复后均通过。

两个旧测试夹具仅放置小怪，却预期战斗继续，与原生胜利条件矛盾。现在分别加入 Fogmog／KinPriest 主怪，原有复活、攻击伤害与力量断言均保留。

## 冻结的奖励基础

实现：`sts2_env/az/enemy_lifecycle.py`。契约标识 `primary-roster-hp-v5` **仅在该基础模块使用**；尚未加入现有 `validate_reward` 接受列表，现有适配器／Replay／checkpoint 不会误用它。

每个敌人保存不可变的出生槽位、ID、primary 标记、初始／最大／当前 HP、是否召唤，以及 `alive/reviving/defeated/removed` 阶段。出生槽位仅追加，不因死亡压缩或重用，不是全局实例 ID，也不含未来随机数。

设 D 为开局全部 primary 的初始 HP 之和。每个 primary 的剩余义务 r 为：

- alive：当前 HP；治疗会撤回进度，超过初始 HP 的部分也参与总量抵扣。
- reviving：该敌人的初始 HP；临时击倒不当作永久完成。
- defeated：0；此阶段表示永久败北，禁止再次复活。

`d = clip(1 - sum(r) / D, 0, 1)`。所有 secondary，包括开局已有小怪和后续召唤，均不参与奖励分母或伤害进度。反复召唤、击杀、移除和复活小怪不会增加 d。这有意使小怪的战术价值经由最终胜负／玩家 HP 体现，而不是直接给予小怪伤害分。

过程奖励 0；终局沿用既有系数：win 为 `0.8 + 0.2*h`，timeout 为 `-0.2 + 0.4*d`，death 为 `-1 + 0.2*d`。只有所有 primary 已永久败北、没有原生终局阻止条件且玩家存活，才接受 win；真实胜负优先于超时。

范围限制：不支持召唤新的 primary、不支持 primary 身份替换／带血移除或最大 HP 变化。此类机制需另行分配固定义务，不能隐式扩张分母。账本可以保存超过当前 AZ 目标容量的历史死亡槽位，**不代表动作空间已支持这些槽位**。网络特征、原生目标索引与账本槽位映射仍待下步实现。

观察器必须根据已发生的公开事实区分“复活等待”和“永久败北”。例如所有节肢已死亡时，要按原生终局规则统一结算为 defeated，不能机械复制残留复活布尔值。此模块不替代原生胜负判定，也不声称仅靠 HP 足以重建 AI。

## 验证与下一步

定向验证覆盖原生 Fogmog 召唤／原槽位反复复活／主怪击杀结束、全部节肢击杀结束，以及奖励账本的反复召唤防刷、治疗／复活撤回进度、多主怪初始低血量、分支不可变、JSON 往返、版本拒绝及损坏记录拒绝。新增 36 项测试；定向 426 项通过。全量 `pytest tests -q`：**6,356 项通过、1 项跳过、30 个子测试通过**，用时 131.72 秒。证据见 `az_g2_lifecycle_acceptance.json`、`az_g2_lifecycle_tests.txt`；全量包含旧 AZ 场景、隐藏信息／粒子／串并行／恢复回归。没有独立外部模型审查。

下一步 G2.2b：将 Fogmog／Eye 的召唤、复活、随机公开行动约束，以及每次 3 张 Dazed 的敌方生成与虚无消耗，一起接入 InformationState、粒子、词表、编码、合法目标、Replay 和统一奖励函数。Dazed 的完整依赖及公开随机历史未接入前，不只开放怪物 ID。

本步没有新可训练内容，因此没有启动旧内容三轮实验来冒充新机制验证。新内容发布后，仍先两轮 smoke，再双 seed 各 3 轮，network 单独决定晋级。G2.1 的已查看测试不能用于下一版本最终验收；需冻结新的独立测试配方。原生源码已改变，不应使用当前源码直接续跑历史冻结目录；旧源码归档与结果保持原样。
