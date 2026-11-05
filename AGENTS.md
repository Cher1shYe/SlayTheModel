> **2026-11-04 第十批：TinkerTime / FakeMerchant / CrystalSphere 收尾与遭遇计划。** 事件清单 **64 IMPLEMENTED / 0 APPROXIMATE / 2 UNSUPPORTED**（AromaPlaceholder 无原生类、WarHistorianRepy 原生不可达）。实现 TinkerTime 全流程（类型/Rider 二选一、MadScience 动态卡型与战斗效果、Curious 降费、Improvement 战斗结束升级）、FakeMerchant（库存/价格/购买/FoulPotion 300 金币战斗与 ExtraRewards）、CrystalSphere（雾格、物品放置、Small/Big、3/6 占卜、奖励顺序）、FishingRod 事件战斗计数。遭遇计划确认走 `Rng.UpFront` 且 `visited % Count` 回绕；删除 `begin_combat(INVALID)` 的 MonsterAi 回退（改抛异常），新增 6 项回归。绑定导出 `REST_HATCH`/`REST_COOK`/`CRYSTAL_DIVINE`；策略支持 CrystalSphere 网格页。身份 ruleset `native-41cef1ea-port-v8`、观察 v17（69977）、动作 v15（718）、快照 v12、ArmG feature v6。clean 重建；CTest 33/33；rules **1053/0**；pytest 363 passed / 16 skipped；1000 局冒烟三次 0 异常/0 截断（65.8–128.4 局/秒、2.4–4.4 µs/步，三次 combats/steps 一致）。目标 DLL `9cb4f1ad…` 不在本机；按用户 2026-11-04 指示不以其严格对照作为验收条件，不宣称目标差分；本地 `0861bfa1…` 不冒充目标参照。证据 `validation/step2-events-rng-20261104/`。

> **2026-11-04 第九批：遗物抽取来源审计（商店过滤 + Wongos FeaturedItem）。** 核对全部 15 处原生 `PullNextRelicFromFront/Back` 调用点。新增 `relic_allowed_in_shops`（AmethystAubergine/BowlerHat/LuckyFysh/OldCoin/TheCourier 五个 `IsAllowedInShops=false`）并给 `pull_relic` 增加 `shopsOnly`：商店后排与 Wongos 前排都按原生过滤，被过滤的前排遗物保留在队列中。`WelcomeToWongos` 事件开始时以显式 Rare（零 Rewards 抽取）从玩家稀有队列前排取 FeaturedItem 并移出共享袋，购买直接获得；Bargain Bin 改为显式 Common 前排 + 商店过滤。其余 12 处调用点与原生一致。当前源码 clean 完整重建（`build-clean-20261104q.txt`）；CTest 33/33；rules **840 项检查 0 失败**（+7 项 Wongos/商店回归）；monster audit 0 失败；pytest 363 passed / 16 skipped；1000 局冒烟 0 异常/0 截断（77.2 局/秒、3.9 µs/步）。复核后 TABLET_OF_TRUTH、LOST_WISP、SAPPHIRE_SEED、WELLSPRING 提升为 IMPLEMENTED（逐页费用/致命分支/事件 RNG 金币/诅咒+遗物/药水池顺序与移除加诅咒均有回归），事件清单 **47 IMPLEMENTED / 14 APPROXIMATE / 5 UNSUPPORTED**。目标 DLL `9cb4f1ad…` 仍缺失，整局原生差分阻塞；本地 `0861bfa1…` 不冒充目标参照。证据 `validation/step2-monster-hp-20261104/`（`*-final-20261104q.txt`）。

> **2026-11-04 第八批：遭遇名单重新盘点。** 反编译比对修正 6 个确定性 roster（Axebot×1、Exoskeleton 4/3、Slumbering Beetle 3 只、Tunneler=Chomper(ScreamFirst)+Tunneler、GremlinMerc 仅 Merc）；GremlinMerc 的 Sneaky/Fat 改由 SurprisePower 死亡生成并转移金币；6 个随机遭遇改为重放原生 NextItem/NextBool（SlimesWeak 采用 small1,medium,small2 顺序）。完整重建；CTest 33/33；rules 833/0；monster audit 0 失败；pytest 363/16；1000 局冒烟 0 异常/0 截断（47.4 局/秒、6.8 µs/步）。证据 `validation/step2-monster-hp-20261104/`（`*-final-20261104j.txt`、`encounter-roster-audit*.txt`）。目标 DLL `9cb4f1ad…` 仍缺失。

> **2026-11-04 第七批：怪物初始 HP 与遭遇 RNG。** 反编译提取 106/109 个怪物的 Min/MaxInitialHp（23 个范围更新），初始 HP 改从 `RunState.Rng.Niche` 抽取并排除同侧重复 MaxHp（原生 `SetUniqueMonsterHpValue` 两遍算法）。遭遇随机改用原生一次性 `Rng(seed + TotalFloor + hash(Id.Entry))`：roster、Decimillipede/Scrolls/TwoTailedRats/CorpseSlugs 关联起始、PunchOff 扣血均迁移；单 roster 不再消耗抽取；修正 Decimillipede 起始映射与 CorpseSlugs 轮转。clean 完整重建；CTest 33/33；rules_regression **833 项检查 0 失败**；pytest 363 passed / 16 skipped；1000 局冒烟 0 异常/0 截断（本次负载 52.5 局/秒、5.7 µs/步，同机噪声 51–108）。事件清单仍 43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED。仍近似：roster 权重非原生 NextItem 重放、bag 耗尽回退用 MonsterAi、MONSTERS_REFERENCE.md 未重生成。目标 DLL `9cb4f1ad…` 仍缺失，整局差分阻塞。证据 `validation/step2-monster-hp-20261104/`（clean 重建 `build-clean-20261104h.txt`，测试 `*-final-20261104i.txt`）。

> **2026-11-04 第六批：Orobas 锁定选项。** 远古选项 INVALID 遗物槽改为不可选；Orobas 第三池在 TouchOfOrobas/ArchaicTooth 均不可用时仍按原生消耗一次 `NextItem` 抽取；ArchaicTooth 条件改为原生起始牌集合（移除 BREAK）。完整重建；CTest 33/33；rules_regression **833 项检查 0 失败**；pytest 363 passed / 16 skipped；1000 局冒烟 0 异常/0 截断（70.5 局/秒、4.2 µs/步）。事件清单仍为 43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED。目标 DLL `9cb4f1ad…` 仍缺失，整局差分阻塞。

> **2026-11-04 第五批（历史）：事件 RNG 边界与事件精化。** 修正 4 处 `Rng.NextInt` 排他上界翻译（PunchOff 91..98、LuminousChoir 100..149、WhisperingHollow 26..44、PunchOff 初始扣血 2..9），修复 StoneOfAllTime 药水物理槽移除；DenseVegetation、BrainLeech、PotionCourier、SpiritGrafter 经反编译审计与回归覆盖后提升为 IMPLEMENTED。事件清单 **43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED**。完整重建成功；CTest 33/33；C++ rules_regression **829 项检查 0 失败**；artifact pytest 363 passed / 0 failed / 16 skipped；1000 局冒烟 0 异常/0 截断（本次负载下 65.1 局/秒、4.7 µs/步）。已知未修 RNG 缺口：怪物 HP 使用 MonsterAi 流而非原生 Niche 流/唯一 HP 集合，109 个 HP 范围中 108 个为采样值。目标 DLL `9cb4f1ad…` 仍不在本机，整局原生差分阻塞。

> **2026-11-04 第四批（历史）：事件战斗标准奖励修复。** 反编译确认 `EncounterModel.ShouldGiveRewards` 默认 true，仅 BattlewornDummy 覆写 false；DenseVegetation、PunchOff、TheLanternKey 的事件战斗现恢复标准怪物奖励并在其后追加 ExtraRewards（PunchOff 遗物+药水，LanternKey 固定特殊卡进入下一个空奖励卡槽）。BattlewornDummy 保持无标准奖励。完整重建成功；CTest 33/33；C++ rules_regression **795 项检查 0 失败**；artifact pytest 363 passed / 0 failed / 16 skipped；1000 局冒烟 0 异常/0 截断，70.4 局/秒、战斗 4.2 µs/步。`test_smoke.py` 快照回放种子改为 5（种子 4 在修正后的奖励轨迹下提前死亡）。事件清单仍为 39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED。目标 DLL `9cb4f1ad…` 仍不在本机，整局原生差分阻塞。证据见 `validation/step2-aeonglass-events-20261104/`。

> **2026-11-04 第三批（历史）：事件战斗与收尾内容已接入。** 完整重建成功；CTest 33/33；C++ rules_regression **775 项检查 0 失败**；artifact pytest 363 passed / 0 failed / 16 skipped；1000 局冒烟 0 异常/0 截断（连续三次 66.7/67.2/66.5 局/秒，战斗 4.4 µs/步；保存单次样本 63.3 局/秒）。身份仍为 ruleset `native-41cef1ea-port-v6`、观察 v15（67784）、动作 v13（717）、ArmG feature v6、快照 v10；`PORT_SOURCE.json` 已同步。事件清单 66 项为 **39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED**；本批实现 FieldOfManSizedHoles、GraveOfTheForgotten、Symbiote、BattlewornDummy、TheLanternKey，并将 ThisOrThat 提升为 IMPLEMENTED。剩余真实缺口：FakeMerchant（自定义商店库存 UI）与 TinkerTime（MadScience 动态卡型/词条）；CrystalSphere 原生 `IsDeterministic=false`，AromaPlaceholder 无原生类，WarHistorianRepy 不可达。目标 DLL `9cb4f1ad…` 仍不在本机，整局原生差分阻塞；本地 `0861bfa1…` 不冒充目标参照。证据见 `validation/step2-aeonglass-events-20261104/`，最新断点见仓库根 `docs/native-port-step2-wip-20261031.md`。

> **2026-11-04 第二部分（历史）：Aeonglass/ByrdonisNest/Splash/药水槽/原生顺序已接入。** 完整重建成功；CTest 33/33；C++ rules_regression 686 项检查 0 失败；artifact pytest 363 passed / 0 failed / 16 skipped；1000 局冒烟 0 异常/0 截断（70.1 局/秒，战斗 4.0 µs/步）。workspace 根 `tests/` 不适用（不同 deployment 布局，基础仓库扩展陈旧）。身份为 ruleset `native-41cef1ea-port-v6`、观察 v15（67784）、动作 v13（717）、ArmG feature v6、快照 v10；`PORT_SOURCE.json` 已同步。事件清单 66 项为 33 IMPLEMENTED / 23 APPROXIMATE / 10 UNSUPPORTED；本批实现 MorphicGrove、Bugslayer、EndlessConveyor、Trial、PunchOff、RanwidTheElder、RelicTrader、SelfHelpBook、WoodCarvings，并新增 SHARP/SLITHER 附魔与遗物可交易判定。目标 DLL `9cb4f1ad…` 仍不在本机，整局原生差分阻塞；本地 `0861bfa1…` 不冒充目标参照。证据见 `validation/step2-aeonglass-events-20261104/`，最新断点见仓库根 `docs/native-port-step2-wip-20261031.md`。

# C++ native rules port workspace

## Current handoff (2026-10-31, step 1 complete)

Read the repository-root `../../../AGENTS.md` for the current round4 step1 state,
confirmed gap inventory, evidence locations, and next-step order. It supersedes
the historical agent ownership below. This directory remains the editable port.
Current ruleset is `native-41cef1ea-port-v8`, observation/action schemas 17/15
(public dimensions 69977/44284/718), ArmG feature6, snapshot12. Full native
parity is still false.

Step 1 is complete: cumulative self-damage and relative power order, deck-event
downgrade cost restoration, in-place starter relic replacement/counter alignment.
Evidence: validation/round4-step1; next scope is decision relics and persistent
state. Preserve round3 and step1 evidence. The incremental v4 patch is against
the step1 source-before snapshot, not the original immutable base.

Important audit correction: LostCoffer is already using the Ironclad reward pool
with `useBaseOdds=true`; the round3 relic report's "fixed common colorless" claim
is wrong. Its complete reward hooks remain unverified. Grapple is absent from
the target native version and intentionally excluded; do not restore it to pools.

User authorized retaining the fast C++ engine and aligning its rules to the
native game used by our headless probe. Do not commit, push, install mods, or
overwrite the immutable reference snapshot or user's uploaded checkpoint.

Base: `be401e8ba09ac58c9f3b01cf77e195f7122c8d0c` (`origin/alphazero`).
Target: local native game `v0.111.0`, release commit `41cef1ea`, game DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`.
The release label alone is not a compatibility guarantee.

Native execution oracle and prior audit:
`../../reference/alphazero-be401e8-review/`. Native source at
`../../../artifacts/native-source/v0.111.0` matches the local DLL for tested rules;
prefer actual DLL execution when evidence differs. External repository decompiles
are secondary references and contain different game rules.

Preserve game decisions; do not substitute random choices for player input.
Do not skip rules, discard legitimate actions or fabricate parity to improve speed.
Snapshots/weights must retain explicit compatibility and migration provenance.
Keep assertions enabled in regression tests. State partial coverage explicitly;
passing targeted tests does not establish complete native equivalence.

Previous agent assignments have ended. Establish fresh ownership before parallel
edits; coordinate shared headers, generated IDs, observations, bindings and
snapshot/checkpoint identities. Freeze source before an integrated build.
Preserve original reports and put future validation in new round directories.
