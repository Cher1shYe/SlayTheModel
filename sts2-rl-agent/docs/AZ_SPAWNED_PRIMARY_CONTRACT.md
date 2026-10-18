# 当前实现状态（2026-10-18）

下文为历史设计提案。用户已授权本轮训练准备修复，现已实现 `initial-primary-budget-v6`，详见 [训练准备报告](AZ_TRAINING_READINESS.md) 和 [运行手册](AZ_ALL_XS_RUNBOOK.md)。旧 v5 仍保持拒绝语义；新 all-content 契约显式版本化。逃跑作为 removed 结算，不额外赚取伤害进度；初始主敌与追加槽位在世界、粒子、搜索和 Replay 使用同一预算。Hex、Ringing、原生复活、同回合召唤出招与超出五个出生槽位的动作也已补齐。本次未启动正式训练。

---

# 召唤 primary 的生命周期契约 v6：设计提案

状态：**提案，未实现**。当前冻结契约仍为 `primary-roster-hp-v5`；本文件只描述需要用户/规格确认的设计与迁移步骤，不修改代码、不启动实验。

## 1. 问题

`setup_gremlin_merc_normal` 与 `setup_axebots_normal` 会在战斗中途追加**没有 Minion 力量**的召唤物。公开账本按“无 Minion 即 primary”把它们记成 `primary=True, spawned=True`，而 v5 的 `EnemyLife.validate` 明确拒绝该组合（`tests/test_az_enemy_lifecycle.py::test_invalid_or_unsupported_states_rejected[spawned]`）。于是 MCTS 的 cutoff 估值在 `summon.ledger_from_slots` 处抛出“Primary summons/removal need a separate budget contract”，整个配方被拒绝。

实测的原生行为（Gremlin Leader）：

- 初始名单 3 个（`GREMLIN_MERC`、`SNEAKY_GREMLIN`、`FAT_GREMLIN`）；
- 战斗中途追加的 Gremlin 出现在 slot 3/4，`spawned=True`；
- 领袖死亡时战斗立即结束，**仍存活的召唤物不阻止胜利**；
- 因此“胜利口径 = 初始名单全灭”，而“预算/分母 = 初始 primary 的 HP”。

## 2. v6 语义

`EnemyLife` 字段不变，含义拆开：

| 字段 | 含义 |
|---|---|
| `primary` | 公开的“无 Minion 力量”，用于**胜利判定**（是否还有未击败的敌人） |
| `spawned` | 不在初始名单中，用于**奖励预算**（不进入分母/初始义务） |

规则：

1. **预算**：`damage_progress` 与 `primary_summary` 只统计 `primary and not spawned` 的行；召唤物既不稀释也不抬高预算。
2. **胜利**：`reason == "win"` 时只要求 `primary and not spawned` 全部 `defeated`；召唤物在领袖死亡后随战斗消失。
3. **Cutoff/None**：没有终止原因的价值估计必须要求**整份名单**（含召唤物）都 `defeated`，避免把“还有活敌人”的局面误判为胜利。
4. **账本校验**：允许 `primary and spawned`；仍拒绝 `primary and phase == "removed"`；要求至少一个**初始** primary。
5. **世界侧账本**：`roster_ledger(world, initial_hp, initial_count)` 用 `slot >= initial_count` 标记 spawned；adapter 传 `len(self.initial_roster)`。这修复了此前原型中“世界侧账本永远 spawned=False”导致的口径冲突。
6. **信息侧账本**：`roster_rows`/`ledger_from_slots` 使用槽位自带的 `spawned` 与“无 Minion 即 primary”。

版本：`primary-roster-hp-v5` → **`primary-roster-hp-v6`**；旧内容（EXPANSION/SUMMON）继续使用 v5，不迁移。

## 3. 兼容性与迁移

- 只影响 all-content 中“召唤了非 Minion 敌人”的战斗；这些战斗目前的终端奖励把召唤物计入预算（世界侧账本 spawned=False），v6 会改变其数值 → **在正式训练开始前**完成迁移，否则训练证据的奖励口径会在中途变化。
- 冻结协议/生成器准入不变（遭遇集合与配方不受影响），但 `docs/all_xs_policy_diagnostic.json` 等奖励相关证据需在 v6 后重跑。
- `docs/AZ_ALL_XS_STATUS.md` 的 reward 字段需加入契约版本。

## 4. 测试计划

单元：

- `EnemyLedger` 接受 `primary+spawned`、序列化往返、拒绝 `primary+removed`；
- `damage_progress`/`primary_summary` 不含 spawned；
- `terminal_reward("win")` 在“初始 primary 全灭、召唤物存活”时给出胜利值；
- `terminal_reward(None/"time_limit")` 在召唤物存活时**不**判胜（继续给 shaped 值）。

集成：

- `gremlin_merc` 0031/0036、`axebots` 0037 在 MCTS-8 下不再被拒绝；
- 完整验证集 64/64、0 拒绝；
- parity 76 不变、鲁棒性 76/76 不变（准入不变）；
- 标准回归通过（当前基线 1206 项通过 / 1 xfail）。

## 5. 备选：维持 v5

不做迁移则保留 3 个显式的搜索拒绝；训练采集会记录并跳过这些配方（约占 64 个验证配方的 5%）。网络侧评估不受影响（64/64）。

## 6. 另一个独立边界：Hexed 粒子恢复

`knights_elite` 的 MCTS 拒绝与 v6 无关：粒子恢复没有把“Hex 力量移除”的清除事件应用到已进入消耗堆的卡牌，导致可见 `hexed` 状态多于库存。修复方向（不改契约）：

1. `power_memory.restore` 重建 HexPower 时，把当前所有 `hexed` 卡牌补入其私有跟踪列表；
2. 同时确认清除事件写入 history 的路径与粒子重放顺序一致（原型在此出现 `Changed card state absent`）。

## 7. 需要确认

- 是否批准 v6 生命周期契约与奖励重冻（并接受这些战斗的奖励数值变化）？
- 若批准，是否在同一批次内完成 Hexed 恢复修复（两者互不影响，可分开提交）？
