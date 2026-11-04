# 第十批：事件收尾与遭遇计划（2026-11-04）

规则目标为原生 v0.111.0 / `41cef1ea`（DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`）。该 DLL
不在本机；按用户 2026-11-04 指示，不再要求与它严格对照，也不把它作为本批验收
条件。因此所有规则证据均为反编译源码核对 + C++ 回归 + 确定性/快照一致性，
不宣称目标 DLL 差分；本地反编译快照 `0861bfa1…` 不冒充目标参照。

## 本批完成

1. **TinkerTime / MadScience**（`simulator/src/events.cpp`、`cards_colorless.cpp`、
   `common.h`）：页面选项、Attack/Skill/Power 二选一、每类三条 Rider 二选一、
   `CardType` 与 `RiderEffect` 存入卡实例；Sapping/Choking/Energized/Wisdom/
   Chaos 执行、Violence 三段攻击、Expertise/Curious/Improvement 能力、
   Curious 降低 Power 费用、Improvement 战斗结束升级、升级获得 Innate。
2. **FakeMerchant**（`events.cpp`、`run.cpp`）：九个假遗物 `UnstableShuffle`
   后取 6 个，价格 `round(50 * Shops.NextFloat(0.85,1.15))`（ToEven），购买
   按固定价格并获得遗物，FoulPotion 触发 `FakeMerchantEventEncounter`
   （300 金币 + Rug + 未售条目 ExtraRewards）。
3. **CrystalSphere**（`events.cpp`、`run.cpp`、`observe.*`）：11×11 雾格、
   15 件物品放置、初始 24 格揭开/97 格隐藏、Small/Big 工具、3/6 次占卜、
   UncoverFuture 费用与金币、PaymentPlan 加 Debt、按揭开顺序构建奖励。
4. **FishingRod**（`relics.cpp`）：按原生 `Encounter.RoomType == Monster`
   统计，事件战斗计入第三次升级（Elite/Boss 不计）。
5. **遭遇计划**（`run.cpp`、`tests/rules_regression.cpp`）：确认
   `ActModel.GenerateRooms` 在 `Rng.UpFront` 上按 事件洗牌 → weak bag →
   regular bag → elite bag → `Boss = NextItem(AllBossEncounters)` → Ancient
   的顺序生成，`NextNormalEncounter` 用 `visited % Count` 回绕。删除
   `begin_combat(INVALID)` 的 MonsterAi 随机回退；非法调用现在抛
   `std::invalid_argument`，避免静默消费无关流。
6. **绑定补全**（`bindings.cpp`）：导出 `REST_HATCH`、`REST_COOK`、
   `CRYSTAL_DIVINE`，`step` 的上界改为 `CRYSTAL_DIVINE`。
7. **策略兼容**（`agent/heuristics.py`）：CrystalSphere 网格页没有
   `EVENT_CHOICE` 时选择网格动作，不再硬编码事件选项 0。

## 事件清单

66 项：**64 IMPLEMENTED / 0 APPROXIMATE / 2 UNSUPPORTED**。
剩余两项均不可在原生单机流程到达：

- `AROMA_PLACEHOLDER`：无原生类；
- `WAR_HISTORIAN_REPY`：原生 `IsAllowed=false`。

## 身份

- RULESET_ID `native-41cef1ea-port-v8`
- `PUBLIC_OBS_VERSION=17`，`PUBLIC_OBS_DIM=69977`
- `ACTION_SCHEMA_VERSION=15`，`ACTION_FEAT_DIM=718`
- `PUBLIC_COMBAT_OBS_DIM=44284`
- 快照版本 12（字段与校验：FakeMerchant 库存/价格/已售、CrystalSphere
  网格/物品/揭开顺序/占卜次数）
- ArmG feature v6

旧 checkpoint 只能按匹配版本加载；v17/v15/v12 与旧 v16/v14/v11 不兼容，
`load_checkpoint`/`restore` 会拒绝。

## 验证命令与结果

- clean 重建：`build-clean-20261104r.txt`（`ninja -t clean && ninja`，exit 0）
- CTest：`ctest-final-20261104r2.txt`，33/33 通过
- `rules_test.exe`：`rules-regression-final-20261104r.txt`，
  **SUMMARY checks=1053 failures=0**
- pytest（artifact 根，`-rs`）：`pytest-final-20261104r.txt`，
  **363 passed / 16 skipped / 0 failed**。16 项跳过均为缺少真实站点快照、
  历史 checkpoint/runs 或 `STS2_PRIOR_PYD`（`*_floor_schedule`、`*_puct_prior_rl`、
  `test_evaluate_*`），与本批规则改动无关。
- 1000 局多种子整局冒烟：`benchmark-runs-1000-final-20261104r.txt`，
  连续三次 `runs=1000 completed=1000 truncated=0 errors=0`；
  65.8 / 70.3 / 128.4 局/秒（同机负载噪声），战斗 2.4–4.4 µs/步；
  三次 `combats=5587`、`86,622` 步完全一致，平均层数 9.6。与第九批
  77.2 局/秒 / 3.9 µs/步相比无规则性回退，差异落在既有 51–108 局/秒噪声带。

## 已知限制

- 目标 DLL 不在本机；按用户指示不做同种子原生 vs C++ 长路径/受控差分，
  也不宣称已完成目标差分。替代证据为反编译逐条核对、1053 项 C++ 规则回归、
  33 项 CTest、363 项 pytest、1000 局多种子冒烟与快照/确定性一致性。
- CrystalSphere 的 `PopulateItems` 失败重试路径未建模；按 51/121 占用格计算
  在原生实现中不可达。
- CrystalSphere 多个金币奖励合并进 `pendingGoldReward`（UI 呈现层差异，
  净结果一致）。
- MadScience 的 RiderEffect 未编码进卡牌特征；CrystalSphere 动作没有专属
  动作特征（仍可通过动作类型/索引区分）。
- `FakeMerchant`/`CrystalSphere` 观察块已加入公开观察；ArmG 原生桥不投影
  这两个事件的载荷，扩展向量对应位置保持显式 0。
