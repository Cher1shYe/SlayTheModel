# 战士／无色卡随机配方原生验收（2026-10-19）

结论：当前不适合直接启动全卡池自进化。74 个开局通过不等于整场可用；固定抽样的 8 场完整战斗采集尝试只有 1 场通过，7 场明确失败。失败数据未进入回放。

## 范围与方法

- 从当前游戏 `ModelDb` 按 `IroncladCardPool` / `ColorlessCardPool` 导出 155 个卡牌 ID，不使用 Python 逐卡实现白名单。
- 从现有 ALL 协议提取 76 种遭遇。当前原生目录缺少 `TOADPOLES_NORMAL`、`DOORMAKER_BOSS`，未擅自替换。
- 其余 74 种遭遇各生成一个固定随机种子的 10 张卡组，允许重复，HP 为 40/60/80。种子 `19070000+i`，完整配方落盘。
- 随机卡组覆盖 153 个基础卡 ID；`ETERNAL_ARMOR`、`GOLD_AXE` 未抽中。没有覆盖升级组合或遗物组合。
- 开局实际调用原生重置、模拟器捕获、合法动作导出、Transformer 策略编码，以及分支／原生价值输入一致性校验。74 个实际卡组均与配方多重集完全一致。该模式不执行战斗动作，也不生成训练样本。
- 开局通过后用随机种子 1907 固定抽取 8 场，尝试打到胜利／死亡；无失败替补。抽样卡组包含 63 个不同卡牌 ID。
- 使用新初始化的通用 XS 模型，CPU 单线程，`mixed`、`value_mix=0.5`、每决策 250 ms。40 回合／100 决策为完整战斗保护上限，截断不收为完整样本。
- 不更新参数，不评估或替换冠军，不启动正式训练，不打开旧测试集。此次结果不是模型强弱评估。

## 实际结果

| 检查 | 结果 |
|---|---|
| 原生开局、动作、编码、价值输入 | 74/74 通过 |
| 原生实际卡组与配方 | 74/74 一致 |
| 完整采集尝试 | 1/8 完成，7/8 失败 |
| 合格回放 | 1 场、11 个决策 |
| 通用协议及价值网络回归 | 42 项通过 |

唯一完成的 `SOUL_NEXUS_ELITE`（seed 19070058）在第 3 回合死亡，最终 HP 0，终局奖励 -1；11 个决策通过状态、合法动作、后继、访问分布及奖励校验。死亡是有效终局，不是采集失败。

## 失败与修复顺序

| 类别 | 配方／seed | 直接证据 |
|---|---|---|
| 动态费用的价值输入不一致（3 场） | GLOBE_HEAD_NORMAL / 19070022；OWL_MAGISTRATE_NORMAL / 19070038；OVERGROWTH_CRAWLERS / 19070037 | `STOMP` 的基础 DTO `EnergyCost` 在分支为 null，原生为 2 或 1；补充 `native.cost` 相同。分支投影当前写死 null，需匹配原生序列化语义。 |
| 出牌合法性不一致（2 场） | LIVING_FOG_NORMAL / 19070030；SEAPUNK_WEAK / 19070046 | 模拟器列出 `BELIEVE_IN_YOU`，但原生 `card.CanPlay()` 为 false。具体条件仍需定位，不能直接认定整张卡或整类遭遇不支持。 |
| 怪物实体顺序不一致（1 场） | THE_OBSCURA_NORMAL / 19070064 | 同一实体位置在分支为 PARAFRIGHT、原生为 THE_OBSCURA。原生导出按 CombatId 排序，分支目前按敌人列表顺序；需统一身份和顺序，并验证召唤后目标映射。 |
| 搜索动作链异常（1 场） | SLIMES_WEAK / 19070052 | `SearchNode.MaterializeActions` 抛“搜索节点动作链长度不一致”，发生于 `PublishCandidateFailure`，可能遮蔽更早的候选失败，需先保留原始失败上下文。 |

优先修复两项明确的投影问题，再修复合法性与动作链；使用以上固定配方做回归，并增加新种子检查。不要通过关闭一致性检查、静默丢弃候选或仅排除失败遭遇来宣布全卡池可训练。7/8 是这批有限样本的失败比例，不是全分布失败率。

## 产物与复现

目录：`output/native_scope_audit_20261019/`。

- `catalog.json`：原生卡池与遭遇目录。
- `protocol.json`：本次独立冻结的配方协议，仅作为审计元数据，未运行其中的验证集。
- `recipes.json`、`collection-plan.json`：74 个开局及 8 个完整采集尝试的配方。
- `report.json`、`audit-summary.json`：完整结果及首个失败信息。
- `preflight/*/root.json`：原生开局观测；各目录 `worker.log` 保留日志。
- `collection/*/worker.log`：7 个失败的完整堆栈，以及成功场次日志。
- `replay/`：仅含成功的 11 个决策。
- `progress.json`：已完成；`tests.log`：42 项测试结果。

新增 `scripts/audit_native_scope.py` 执行有限审计。先用 `collection-pilot` 原生入口和 `{"format":"native-generic-collection-v1","catalogOutput":"<绝对路径>/catalog.json"}` 导出目录并构建 worker，再运行 `python scripts/audit_native_scope.py <新输出目录>`。脚本使用刚构建的 worker；不得在审计过程中更换源码或二进制。原生新增 `preflightOnly` 只检查开局，不进入普通训练回放路径。

本次目录导出的首次 job 缺少路由 `format`，在采集前失败；补齐 job 后成功。该启动配置错误独立保留在 `catalog.log`，不计入上面的战斗失败。
