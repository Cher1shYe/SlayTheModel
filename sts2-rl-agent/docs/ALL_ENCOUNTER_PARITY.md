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
| 通过 | **65** | 8 步（或终局前）逐步一致 |
| 采样差异 | 2 | 召唤槽位的构造随机流不可见（fabricator/ovicopter），粒子只能采样；槽位出现后即为公开状态 |
| 专用契约 | 1 | `setup_test_subject_boss` 三形态走 `boss_phases`，不进入通用判据 |
| 待处理 | **13** | 见下表，逐条记录原因 |

## 待处理遭遇与原因

| 类别 | 遭遇 | 首个差异／错误 | 说明 |
|---|---|---|---|
| 卡牌状态事件 | knights_elite、living_fog_normal、queen_boss、the_insatiable_boss、vine_shambler_normal | Visible card states exceed public inventory | 战斗内 affliction（hexed/smog/bound）改变牌面（关键词/可用性）时，引擎可见日志没有记录 `card_state_change`，公开账本无法闭合 |
| 临时负值状态 | hunter_killer_normal、the_lost_and_forgotten_normal | Invalid basic status | TENDER 类能力产生临时负敏捷/力量，需要允许有符号的基础状态并记录恢复时点 |
| 粒子根状态 | fogmog_normal、the_obscura_normal | Particle 未复现根状态 | 召唤 Eye／形态切换后的根状态重建差异 |
| 回合侧 | knowledge_demon_boss | Not a public player decision | 敌方侧决策/额外行动未纳入公开回合契约 |
| 意图唯一性 | lagavulin_matriarch_boss | Intent does not identify one move | 睡眠/唤醒形态的可见意图无法唯一确定招式 |
| 洗牌 | thieving_hopper_weak | Shuffle with nonempty public draw pile | 敌方洗牌/塞牌违反当前公开位置假设 |
| Boss 修正 | kaiser_crab_boss | player_hp/history | Crusher/Rocket 的 BACK_ATTACK + CRAB_RAGE 伤害修正 |

这些遭遇**仍显式拒绝接入**（构建或观测阶段报错），不会静默通过；下一步按类别逐个补齐公开契约。

## 本轮已修复

- 玩家 SHRINK 的观测与粒子恢复（功率顺序一致）。
- 死亡/逃跑槽位不再获得公开出招；召唤槽位 append-only 的初始 HP、`spawned` 后缀与奖励账本。
- V7 终局风险入参（`incoming_risk`）修复。
- 继承状态牌 `TOXIC`/`INFECTION`/`BECKON`/`FRANTIC_ESCAPE` 的描述与构造；`execution` 恢复统一走状态牌工厂。
- 卡牌 affliction 公开状态扩展：`hexed`（追加 ethereal）、`smog`（`_smoggy`）、FRANTIC_ESCAPE 的公开费用增长；VITAL_SPARK 每回合触发计数进入敌人能力簿记（prisms 由此通过）。
- 召唤槽位的构造随机流不可见时改为“采样差异”，不再计为失败。

## 复现

```powershell
.\.venv-az\Scripts\python.exe scripts\audit_all_encounter_parity.py
```

输出逐遭遇状态与 `docs/all_encounter_parity.json` 汇总。
