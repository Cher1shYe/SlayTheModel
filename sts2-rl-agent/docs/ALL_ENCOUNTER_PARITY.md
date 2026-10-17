# 全遭遇 MCTS 公开状态一致性扫描

日期：2026-10-18。范围：act1–act4 原生战斗遭遇 **81 个**；内容版本 `ironclad-colorless-all-v6`。

## 方法

`scripts/audit_all_encounter_parity.py` 对每个遭遇：

1. 用 `ObservableCombatAdapter` 构造真实世界与公共信息状态；
2. 每一步按当前合法动作均匀采样一个动作；
3. 用 `BeliefSampler` 重建粒子，并按公开牌面/随机流对齐（对齐只用于 parity oracle，真实搜索不做）；
4. 粒子与真实世界执行同一动作，逐字段比较 `InformationState`。

8 步或提前终局计为通过；不训练、不读最终留出集、不写权重。原始结果：`docs/all_encounter_parity.json`。

## 结果

| 状态 | 数量 | 说明 |
|---|---:|---|
| 通过 | **76** | 8 步（或终局前）逐步一致 |
| 采样差异 | 2 | 召唤槽位的构造随机流不可见（fabricator/ovicopter），粒子只能采样；槽位出现后即为公开状态 |
| 专用契约 | 1 | `setup_test_subject_boss` 三形态走 `boss_phases`，不进入通用判据 |
| 待处理 | **2** | 见下表，逐条记录原因 |

## 待处理遭遇与原因

| 类别 | 遭遇 | 首个差异／错误 | 说明 |
|---|---|---|---|
| 回合侧 | knowledge_demon_boss | Not a public player decision | 战斗开始时 Boss 以“问题”形式让玩家从两张**生成诅咒牌**中选一张；该选择没有可见牌堆来源，需要新的公开选项契约 |
| 意图唯一性 | lagavulin_matriarch_boss | Intent does not identify one move | 睡眠/眩晕后可见意图无法唯一确定下一招（AI 内部选择，公开信息不足） |

这些遭遇**仍显式拒绝接入**（构建或观测阶段报错），不会静默通过；下一步按类别逐个补齐公开契约。

补充：`docs/all_encounter_robustness.json` 对 76 个通过遭遇各用两套固定卡组做 6 步随机合法动作探测，**76 个全部稳定**（包括此前被排除的 `setup_globe_head_normal`：战斗开始阶段的状态事件已进入初始公开历史）；P3 生成器准入 = parity ∩ robustness = **76**。

## 本轮已修复

- Kaiser Crab 的 `SURROUNDED.facing` 进入公开能力簿记（玩家朝向是可见的），Crusher/Rocket 的背击伤害倍率在粒子中一致。
- 被击倒（STUNNED）与幻象复活（REVIVE_MOVE，HEAL 意图）纳入公开招式/意图状态，可打断并恢复脚本；`spawned` 槽位以生成时的最大 HP 作为初始 HP。
- Summon 槽位的 SANDPIT 恢复目标玩家，FRANTIC_ESCAPE 的公开费用增长与 Dampen 降级事件闭合库存。
- fogmog / living fog / the obscura / the insatiable 由此转为 parity 通过。
- 玩家 SHRINK 的观测与粒子恢复（功率顺序一致）。
- 死亡/逃跑槽位不再获得公开出招；召唤槽位 append-only 的初始 HP、`spawned` 后缀与奖励账本。
- V7 终局风险入参（`incoming_risk`）修复。
- 继承状态牌 `TOXIC`/`INFECTION`/`BECKON`/`FRANTIC_ESCAPE` 的描述与构造；`execution` 恢复统一走状态牌工厂。
- 卡牌 affliction 公开状态扩展：`hexed`（追加 ethereal）、`smog`（`_smoggy`）、FRANTIC_ESCAPE 的公开费用增长；VITAL_SPARK 每回合触发计数进入敌人能力簿记（prisms 由此通过）。
- 召唤槽位的构造随机流不可见时改为“采样差异”，不再计为失败。
- **affliction → `card_state_change` 公开事件**：`CardInstance.afflict/clear_affliction` 现在写入可见日志，`public_state_blob` 含 `affliction`；queen（ChainsOfBinding bound + 计数/已触发状态）、knights（hexed）、living fog（smog）、vine shambler（entangled）、the insatiable（FRANTIC_ESCAPE 费用增长）由此转通过。
- 玩家能力簿记补充 `CHAINS_OF_BINDING` 的 `_bound_cards_this_turn` 与 `_bound_card_played`。
- **有符号临时状态**：`DEXTERITY`/`SETUP_STRIKE` 允许负值（TENDER 类临时减益），`TENDER._cards_played_this_turn` 进入公开簿记；hunter killer、lost&amp;forgotten 转通过。
- **被偷牌的公开事件**：`Thieving Hopper` 偷牌时写入 `("steal", 牌面, 回合)`，公开库存与已知位置随之更新；洗牌事件以原生规则为准重置位置，thieving hopper 转通过。

## 复现

```powershell
.\.venv-az\Scripts\python.exe scripts\audit_all_encounter_parity.py
```

输出逐遭遇状态与 `docs/all_encounter_parity.json` 汇总。

