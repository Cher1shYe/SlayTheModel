# Ironclad RL 审计修复、PPO 与奖励（2026-11-05）

对应 `D:\sts2_datacollection\reports\ironclad-rl-audit-20261104\REPORT.md` 的 8 项已复现问题。
本目录记录修复位置、测试、训练配置和身份；目标 DLL `9cb4f1ad…` 不在本机，本地
`0861bfa1…` 不冒充目标参照，所以**本批不宣称目标原生差分等价**。

## 1. 审计问题修复

| # | 审计问题 | 修复位置 | 回归 |
| --- | --- | --- | --- |
| 1 | CrystalSphere 泄露未揭开物品 | `simulator/src/observe.cpp`（`public_observation` 只在 `revealed` 时写类型/坐标） | `test_audit_rl_fixes.py::test_crystal_sphere_hides_items_until_revealed` |
| 2 | 遗物选卡网格候选不可见（Hefty Tablet / Lead Paperweight / Sea Glass） | `observe.cpp`、`bindings.cpp::card_grid_cards`、`observe.h::RUN_CARD_GRID_N=15`、`agent/armg.py` | `test_relic_card_grids_expose_their_candidates`（3 种网格 × 绑定/观察/动作特征） |
| 3 | 药槽空位使动作特征错位 | `bindings.cpp::potion_slot_ids`、`agent/armg.py` 用物理槽 | `test_potion_holes_keep_physical_slot_indices` |
| 4 | Pounce 的 FREE_SKILL 未作用于合法动作/费用/消耗 | `simulator/src/battle.cpp`（`legal_actions` 与出牌路径） | `audit_rl_regressions.cpp::check_free_skill`、`test_free_skill_drives_legality_cost_and_consumption` |
| 5 | 卡牌状态输入混叠（费用到期/当回合保留/Sly） | `common.h::card_public_key`、`observe.cpp::push_card_instance/card_features`（+7 字段） | `audit_rl_regressions.cpp::check_card_state_distinguishes` |
| 6 | 局外牌组缺少 MadScience 变体 | `observe.cpp`（局外牌组改用 `push_card_instance`） | `check_madscience_variant` |
| 7 | 隐藏重采样依赖原始秘密顺序 | `battle.cpp::resample_hidden` 用 `card_public_key` | `check_hidden_resample_public_key`（200 个种子 × 交换） |
| 8 | 启发式返回非法事件/休息动作 | `agent/heuristics.py::run_policy` 所有分支经 `pick()` 过滤 | `test_heuristic_only_returns_legal_actions_across_seeds`、`test_miniature_tent_second_rest_is_rejected_not_offered_twice` |

审计“训练目标与证据边界”第三节的覆盖率统计错误也已修：`scripts/content_inventory.py`
原来的 `a & b | c` 优先级使每张卡都算“已测试”。已改为分别与 C++/Python 测试集求交，
修正后 596 张卡中 **368 张无自动化测试引用**（此前声称 0）。旧证据文件
`docs/content-inventory-20261104.*` 未覆盖，修正结果写入本目录
`content-inventory-20261104.*`（`CONTENT_INVENTORY_OUT` 环境变量控制输出目录）。

供观察用：`simulator/include/sts2/observe.h` 的 `PUBLIC_OBS_VERSION = 20`、
`PUB_CARD_INSTANCE_FEAT = 24`、`RUN_CARD_GRID_N = 15`；`agent/armg.py`
`ARMG_FEATURE_VERSION = 9`（v8 的附魔三元组偏移写错，落在新增的 Sly/Retain 字段上；
v9 把偏移固定为 `ENCHANT_FEATURE_OFFSET = CARD_COUNT + 25`）。

## 2. 训练内容配置

`RunContentProfile.SINGLE_PLAYER_TRAINING`（`simulator/include/sts2/run.h`）：

- 事件袋在洗牌**之前**排除 `CRYSTAL_SPHERE`（`run.cpp::roll_act_rooms`），不是抽到后跳过。
- 多人卡在全部生成入口（奖励、商店、事件、变牌、战斗内生成、遗物生成）已被
  `CF_MULTIPLAYER_ONLY` 拒绝；`agent/content_profile.py` 在每次 step 后断言。
- 原始内容与开关保留：`ORIGINAL` 仍是默认，`PORT_SOURCE.json` 记录两种配置。
- 该配置**改变原始内容分布**（少一个事件、少 37 张多人卡），不能称“未修改原生内容”。

`test_content_filtering.py` 覆盖 25 个种子 × 奖励/商店/变牌/网格/牌组入口，并断言
原始配置仍能抽到 CrystalSphere。

## 3. 奖励

`agent/run_reward.py`：

```
R = Σ_i [(L_i × i) / 20 + (i / 10) × E_i] + Σ_{k=1..B} k/2 + 0.05U + 0.02D + mean_Elo/600
```

- 规范示例 L1=10, L2=5, E1=2, E2=1, B=1, U=1, D=1, mean_Elo=1500 → **4.47**，测试逐项断言。
- U/D 只记在 `REST_UPGRADE` / `REMOVE_CARD` 动作本身；事件或遗物带来的升级/删牌不计。
- 只有正常结束（胜或死）计算奖励；`error`/`truncated` 的 `total_reward=None`，
  不进入 PPO，也不伪装成正常结束。
- 每条轨迹的 transition 增量之和 == 终局奖励（`TrajectoryRecorder.finish` 校验）。

**Elo 快照身份**：`D:/sts2_datacollection/sts2/runs/armg_spire_wr50_prior_20261030/data`,
`cards.json` SHA-256 `478581112e7a83ef…`，manifest SHA-256 `e667b082ed6d9c95…`，
322 行（无升级行）。匹配规则：标题转大写下划线、撇号删除、其余标点作分隔、
折叠连续下划线、去掉尾部 `_CARD`。322 个卡片 ID 匹配，274 个无数据；
无数据的按规则给 1150 并单独计数（`deck_elo_missing`），**不当 0**。
Strike/Defend/Bash 固定 1150；升级牌用基础牌数据；多人/CURSE/STATUS/TOKEN/EVENT/
Corruption/Break/GRAPPLE 同时从分子和分母排除；排除后为空 = 0。

## 4. PPO

`agent/armg_ppo.py`：actor-critic（actor = `ArmGScorer`，独立 critic），
旧策略概率、clip(ε=0.2) 目标、GAE(γ=1, λ=0.95)、价值损失(0.5)、熵(0.01)、
梯度裁剪(0.5)、精确 KL 早停(1.5×0.02)。强制决策保留在价值轨迹但不训练 actor。
更新前校验 rollout 与当前策略 KL ≤ 1e-5，过期 rollout 直接报错（`test_stale_rollout_is_refused…`）。

**信息边界**：actor 的输入是 `public_observation`（无抽牌顺序、未来 RNG、隐藏牌堆内容）。
战斗控制器是**独立**的、不是 PPO 训练的：`greedy`（玩家可见贪心展开）、
`mcts-resampled`（隐藏状态重采样）、`mcts-oracle`（**使用完整模拟器状态与未来 RNG**，
记录在 `settings.battle_controller_info`，不得称为“只用玩家可见信息的战斗策略”）。
本批训练使用 `mcts-oracle`，所以整体结果**不能**宣称是纯玩家可见信息策略的表现。

## 5. 验收运行

见 `results.md`（构建/CTest/pytest/冒烟/训练/评估的命令与原始输出路径）。

收尾核验（2026-11-05 下午，针对本目录早先记录的过期证据）：

- 参考配置训练已跑满 1024 局（`D:/sts2_rl_runs/ppo_a10_ref_20261105/`，最后一行为
  games=1024）。过程中进程池被外部终止两次（`BrokenProcessPool`），均以
  `--resume` 恢复；每批结束才写 checkpoint，重跑的批次从恢复的父 RNG 重新生成同一种子，
  指标文件 32…1024 无重复、无缺口。首批判重现（同种子、16 worker）得到与原始行完全
  相同的指标，说明批次可复现。
- 小规模可恢复 PPO 在最终 feature v9 代码上重跑并续跑（`D:/sts2_rl_runs/resumable_v9/`，
  80 → 160 局，`progress.games`、优化器与三路 RNG 状态均恢复）。
- 修正评估路径的奖励定义：`deployment/evaluate_armg.py` 之前没有传 `DeckElo`，
  评估里的 `total_reward` 少算 Elo 项并把 `deck_elo_bonus` 显示为 0（与“缺失不得当 0”
  冲突）。现在评估与训练使用同一 Elo 快照，`elo_snapshot` 身份写入评估配置；
  `test_armg_evaluation.py` 断言 `deck_elo` 传入两臂。最终评估重跑结果见 `results.md`。

## 6. 未完成 / 边界

- **目标原生差分**：目标 DLL `9cb4f1ad…` 不在本机，本批只做 C++ 回归、绑定回归、
  确定性/快照一致性，**不宣称**与目标原生逐步等价。
- **CrystalSphere 事件本身**按用户指示未修复；训练/评估通过内容配置绕开它，
  原始配置仍可到达。
- **Celestial/Defect 等其它角色**未在本轮范围；内容过滤只排除多人卡与 CrystalSphere。
- 参考配置训练使用的是 `mcts-oracle` 战斗控制器（完整状态 + 未来 RNG），
  因此**整体结果不是纯玩家可见信息策略的成绩**；只有局外 actor 的信息边界是公开观察。
- 本批 1024 局训练是“按参考配置跑通”的证据，样本量远不足以宣称性能提升；
  早期训练曲线（层数/奖励上升）也受同一 `mcts-oracle` 控制器影响，不能归因于 PPO。
- `simulator/tests/audit_rl_regressions.cpp` 与 Python 回归覆盖的是审计复现场景，
  不是全状态空间证明。
- **参考训练的进程池中断**：1024 局不是一次不间断进程跑完的。两次
  `BrokenProcessPool`（约 games 736 之后）由 `--resume` 恢复；没有把异常局写入训练，
  但“训练全程无中断”这一说法不成立，报告里应这样写。首批判可复现，崩溃原因未定位，
  未在训练代码里加自动重试。
- **评估使用的 checkpoint**：最终评估用 `latest.pt`（games=1024）。`best.pt` 停在
  games=768，因为 1024 局的验证批有 1/16 截断，而 best 选择要求验证批全部正常结束。
