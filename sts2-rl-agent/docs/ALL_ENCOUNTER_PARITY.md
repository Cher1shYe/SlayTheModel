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
| 通过 | **64** | 8 步（或终局前）逐步一致 |
| 专用契约 | 1 | `setup_test_subject_boss` 三形态走 `boss_phases`，不进入通用判据 |
| 待处理 | **16** | 见下表，逐条记录原因 |

## 待处理遭遇与原因

| 类别 | 遭遇 | 首个差异／错误 | 说明 |
|---|---|---|---|
| 卡牌关键词变异 | knights_elite | Unaudited card mutation: keywords | 战斗内新增/移除关键词（如 Bound 类）需要公开关键词状态契约 |
| 战斗内卡牌变量 | living_fog_normal | Unaudited combat variable | 敌方给牌写入未批准的 `combat_vars` |
| 战斗内卡牌变量 | the_insatiable_boss | Unaudited combat variable | 同上（Feast/Fruit 类生成物） |
| 卡牌库存 | queen_boss | Visible card states exceed public inventory | 发牌/收回时的公开状态变更事件缺失 |
| 卡牌库存 | vine_shambler_normal | Visible card states exceed public inventory | 缠绕/生长产生的牌面状态变化未入公开账本 |
| 基础状态 | hunter_killer_normal | Invalid basic status | TENDER（每张牌 -1 力量/敏捷，回合末恢复）产生负值临时状态 |
| 基础状态 | the_lost_and_forgotten_normal | Invalid basic status | 同类临时负值状态 |
| 召唤/槽位 | fabricator_normal | enemies 不一致 | 制造出的 minion 槽位属性恢复差异 |
| 召唤/槽位 | ovicopter_normal | enemies 不一致 | 孵化 minion 槽位差异 |
| 能量 | infested_prisms_elite | energy 不一致 | 敌方能量/费用交互（棱镜） |
| Boss 修正 | kaiser_crab_boss | player_hp/history | Crusher/Rocket 的 BACK_ATTACK + CRAB_RAGE 伤害修正 |
| 粒子重建 | fogmog_normal | particle != root | 召唤 Eye 后的根状态重建差异 |
| 粒子重建 | the_obscura_normal | particle != root | 形态/隐藏切换后的重建差异 |
| 回合侧 | knowledge_demon_boss | Not a public player decision | 敌方侧决策/额外行动未纳入公开回合契约 |
| 意图唯一性 | lagavulin_matriarch_boss | Intent does not identify one move | 睡眠/唤醒形态的可见意图无法唯一确定招式 |
| 洗牌 | thieving_hopper_weak | Shuffle with nonempty public draw pile | 敌方洗牌/塞牌违反当前公开位置假设 |

这些遭遇**仍显式拒绝接入**（构建或观测阶段报错），不会静默通过；下一步按类别逐个补齐公开契约。

## 复现

```powershell
.\.venv-az\Scripts\python.exe scripts\audit_all_encounter_parity.py
```

输出逐遭遇状态与 `docs/all_encounter_parity.json` 汇总。
