> **2026-11-05 后续训练审计修复完成（trainer v2）。**
> 修复隐藏牌堆排序遗漏公开状态、异常局 error/errors 导致 KeyError、need-rules 的 PPO 采样/更新概率不一致、Boss 预算隐式三倍。
> 新增整局循环访问计数、BrokenProcessPool 原批次重试/失败保存、串并行一致的逐局采样种子；验证加入 Elo，best 按完整奖励选择。
> 最终本机验证：CTest **42/42**；pytest **444 passed / 17 skipped**；A0/A10 各 202 局合计 **404 局 0 异常/0 截断**；need-rules + 2 workers 的 PPO **8 局训练 + 2 局验证**正常完成。
> 证据及边界见 `validation/rl-fixes-20261105/README.md`。旧 1024 局权重未改写，未重跑其长程评估；过去 worker 崩溃底层原因仍未知，新增的是可审计的恢复路径。
> 水晶球及多人卡继续排除；未提交、未推送。观察/动作/特征布局未变，但源/二进制身份与训练配置已变化，旧 checkpoint 不得伪造身份直接 resume。

> **2026-11-05 铁甲 RL 审计修复与 PPO：当前身份 v10 / 观察 v20 / ArmG feature v9。**
> 对应 `reports/ironclad-rl-audit-20261104/REPORT.md` 的 8 项已复现问题全部修复
> （水晶球隐藏信息、三种遗物选牌网格、药水物理槽、Pounce FREE_SKILL、卡牌状态混叠、
> 局外 MadScience 变体、隐藏重采样顺序、启发式非法动作）。新增独立训练内容配置
> `RunContentProfile.SINGLE_PLAYER_TRAINING`（洗牌前排除 CrystalSphere、全部生成入口
> 排除多人卡，运行中逐步断言），并说明它改变了原生内容分布。训练目标改为
> actor-critic PPO + 指定终局奖励（层数/精英/首领/营地升级/商店删牌/永久牌组 Elo）。
> 上面提到的 `scripts/content_inventory.py` 集合表达式问题已修复：596 张卡中
> **368 张无自动化测试引用**（此前误报 0），修正结果见 `validation/rl-audit-20261105/`。
> 验证：CTest 42/42；`audit_rl_regressions` 新增 5 组引擎检查；artifact pytest
> **437 passed / 17 skipped / 0 failed**；A0/A10 各 200 局整局冒烟 0 异常/0 截断。
> ArmG feature 由 8 升到 9（动作特征的附魔三元组偏移修正为引擎真实位置）。
> 旧 checkpoint 因引擎源哈希/特征版本不符被拒绝，未改写版本号强行加载。
> 目标 DLL 仍不在本机：不宣称原生差分，`mcts-oracle` 战斗控制器使用完整状态与
> 未来 RNG，相关成绩不能称为纯玩家可见信息策略。
> 证据 `validation/rl-audit-20261105/`。

> **2026-11-04 推送前核验：当前身份为 v10，覆盖统计存在已知问题。**
> 当前 ruleset `native-41cef1ea-port-v10`，公开观察 v19、动作 schema v17、ArmG feature v7、快照 v14；下方第十批 v8 是历史记录。推送前复跑已有构建：CTest 41/41 通过，artifact pytest 362 passed / 17 skipped。此前五角色 25 局冒烟均正常结束；这些测试不证明所有交互或多人运行时已经验证。
> `scripts/content_inventory.py` 的卡牌测试引用集合表达式会把所有 Python 测试文件加入每张卡，故 `docs/content-inventory-20261104.*` 及 `validation/round7-full-coverage-20261104/inventory-summary.json` 中卡牌“无测试引用为 0”等结果不可靠，须修正生成器并重新盘点。即使修正，源文件引用也不等于逐项语义断言。该问题尚未修复。

> **2026-11-04 续接更新（第十批）：TinkerTime / FakeMerchant / CrystalSphere 收尾与遭遇计划。**
> 事件清单 66 项现为 **64 IMPLEMENTED / 0 APPROXIMATE / 2 UNSUPPORTED**，两项剩余均不可达：`AROMA_PLACEHOLDER` 无原生类、`WAR_HISTORIAN_REPY` 原生 `IsAllowed=false`。本批实现：TinkerTime 的 Attack/Skill/Power + 三条 Rider 二选一、`CardType`/`RiderEffect` 存卡、Sapping/Choking/Energized/Wisdom/Chaos、Violence 三段、Expertise/Curious/Improvement 能力、Curious 降费、Improvement 战斗结束升级、升级得 Innate；FakeMerchant 九个假遗物 `UnstableShuffle` 取 6、价格 `round(50*Shops.NextFloat(0.85,1.15))`（ToEven）、购买/售罄、FoulPotion 触发 300 金币战斗与 Rug+未售遗物 ExtraRewards；CrystalSphere 11×11 雾格、15 件物品放置、初始 24 揭开/97 隐藏、Small/Big 工具、3/6 次占卜、UncoverFuture 金币与 PaymentPlan Debt、按揭开顺序构建奖励；FishingRod 按原生 `Encounter.RoomType==Monster` 统计事件战斗。遭遇计划复核：`ActModel.GenerateRooms` 在 `Rng.UpFront` 上按 事件洗牌→weak→regular→elite→Boss→Ancient 生成，`NextNormalEncounter` 以 `visited % Count` 回绕；删除 `begin_combat(INVALID)` 的 MonsterAi 回退（现抛 `std::invalid_argument`）。绑定补齐 `REST_HATCH`/`REST_COOK`/`CRYSTAL_DIVINE` 并把 `step` 上界改为 `CRYSTAL_DIVINE`；策略在 CrystalSphere 网格页选择网格动作。身份升至 ruleset `native-41cef1ea-port-v8`、观察 v17（69977）、动作 v15（718）、战斗观察 44284、快照 v12、ArmG feature v6；旧 v16/v14/v11 checkpoint 被拒绝。
> 验证：clean 重建 `build-clean-20261104r.txt`（exit 0、0 error）；CTest 33/33（`ctest-final-20261104r2.txt`）；`rules_test.exe` **1053 项检查 0 失败**（`rules-regression-final-20261104r.txt`，新增 6 项遭遇计划/UpFront 检查）；artifact pytest **363 passed / 16 skipped / 0 failed**（`pytest-final-20261104r.txt`）；`bench.exe run 1000` 连续三次 **1000/1000 正常终止、0 截断、0 异常**，65.8/70.3/128.4 局/秒（同机噪声）、战斗 2.4–4.4 µs/步，三次 `combats=5587`、86,622 步一致（`benchmark-runs-1000-final-20261104r.txt`）。目标 DLL `9cb4f1ad…` 不在本机；按用户 2026-11-04 指示，不以与该 DLL 的严格对照作为验收条件，本批证据级别为反编译源码核对 + C++ 回归，不宣称目标差分；本地 `0861bfa1…` 不冒充目标参照。证据 `validation/step2-events-rng-20261104/`。
> 已知限制：CrystalSphere 的 `PopulateItems` 重试路径未建模（原生 51/121 占用下不可达）；多个金币奖励合并进 `pendingGoldReward`（净结果一致）；MadScience RiderEffect 未进入卡牌特征；CrystalSphere 无专属动作特征；ArmG 原生桥对两个新事件载荷保持显式 0。

> **2026-11-04 续接更新（第九批）：遗物抽取来源审计（商店过滤 + Wongos FeaturedItem）。**
> 反编译核对全部 15 处 `RelicFactory.PullNextRelicFromFront/Back` 调用点。修正两处：其一，`RelicModel.IsAllowedInShops` 在 5 个遗物上为 false（AmethystAubergine/BowlerHat/LuckyFysh/OldCoin/TheCourier），商店 `FillSlot` 与 Wongos 两处购买都按其过滤；C++ 之前只在后排抽取排除 OldCoin/TheCourier，前排无过滤。新增 `relic_allowed_in_shops` 与 `pull_relic(..., shopsOnly)`：商店后排传 `fromBack`，Wongos 前排传 `shopsOnly`，前排被过滤的遗物按原生 `PullFromFront` 语义保留在队列中。其二，`WelcomeToWongos.GenerateInitialOptions` 在事件开始时以显式 Rare（不消耗 Rewards 抽取）从玩家稀有队列前排取 FeaturedItem 并从共享袋移除；C++ 之前按 RelicId 顺序扫描且不消耗背包。现在事件开始时存入 `eventData[0]`，FeaturedItem 购买直接获得该遗物，Bargain Bin 改为显式 Common 前排 + 商店过滤。其余 12 处（LargeCapsule、ToyBox、PaelsWing、BattlewornDummy V3、LuminousChoir、Ranwid、RelicTrader、RoundTeaParty、ThisOrThat、Trial、UnrestSite 等）与原生一致。
> 验证：当前源码 clean 完整重建（`build-clean-20261104q.txt`，exit 0、0 error）；CTest 33/33（`ctest-final-20261104q.txt`）；`rules_test.exe` **840 项检查 0 失败**（`rules-regression-final-20261104q.txt`，新增 7 项 Wongos/商店检查）；monster audit 0 失败；map_event_audit 0 失败（`map-event-audit-final-20261104q.txt`，新增 Tablet/LostWisp/Wellspring 分支检查）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104q.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常、77.2 局/秒、战斗 3.9 µs/步（`benchmark-runs-1000-final-20261104q.txt`）。同时复核并提升 TABLET_OF_TRUTH、LOST_WISP、SAPPHIRE_SEED、WELLSPRING 为 IMPLEMENTED：TabletOfTruth 逐页费用 3/6/12/24/MaxHp-1、第五次升级全部可升级牌、致命分支先降到 1 MaxHp 再 Kill；LostWisp 金币 `60 + NextInt(-15,16)` 走事件 RNG，Claim 加 Decay + LostWisp 遗物（Power 牌 8 点 Unpowered 伤害）；SapphireSeed 的 Eat 回血 9 + 升级、Plant 只对 Sown 可附魔牌选择；Wellspring 的 Bottle 按 Ironclad+共享药水池顺序从 Rewards 流抽 1 瓶并作为药水奖励，Bathe 先移除 1 张再加 Guilty。事件清单现为 **47 IMPLEMENTED / 14 APPROXIMATE / 5 UNSUPPORTED**（其中 AROMA_PLACEHOLDER 无原生类、WarHistorianRepy 不可达，真实缺口 3 项）（Wongos 的商店抽取已修正，但 Wongo 积分/徽章为账号进度，仍列近似）。目标 DLL `9cb4f1ad…` 仍缺失，同种子整局原生差分阻塞。

> **2026-11-04 续接更新（第八批）：遭遇名单重新盘点。**
> 新增 `validation/step2-monster-hp-20261104/extract_encounters.py`，逐遭遇比较反编译 `GenerateMonsters` 与采样 roster：修正 6 个确定性名单（AxebotsNormal 1 只、ExoskeletonsNormal/Weak 4/3 只、SlumberingBeetle 为 Rock+Silk+Beetle、TunnelerNormal 为 Chomper(ScreamFirst)+Tunneler、GremlinMercNormal 仅 Merc）。GremlinMerc 的 Sneaky/Fat 改为 SurprisePower 死亡触发（追加到敌方列表末尾并转移偷取金币），不再作为初始成员。6 个随机 roster（Flyconid、Slimes normal/weak、SlitheringStrangler、Bowlbugs normal/weak、RubyRaiders）改为在 `native_random_roster` 中重放原生 `NextItem`/`NextBool` 抽取；SlimesWeak 采用原生 small1, medium, small2 顺序。DenseVegetation 的审计差异为解析器误报（原生按 4 个 Slots 循环）。
> 验证：完整重建；CTest 33/33（`ctest-final-20261104j.txt`）；rules 833/0（`rules-regression-final-20261104j.txt`）；monster audit 0 失败（`monster-audit-final-20261104j.txt`）；pytest 363 passed / 16 skipped（`pytest-final-20261104j.txt`）；1000 局冒烟 0 异常/0 截断、47.4 局/秒、6.8 µs/步（`benchmark-runs-1000-final-20261104j.txt`）。目标 DLL `9cb4f1ad…` 仍缺失，整局差分阻塞。

> **2026-11-04 续接更新（第七批）：怪物初始 HP 与遭遇 RNG。**
> 反编译确认 `Creature.SetUniqueMonsterHpValue` 使用 `RunState.Rng.Niche`，在 `[MinInitialHp, MaxInitialHp]` 中排除同侧已有 MaxHp 后按升序 `NextItem`（空集退回均匀抽取）。C++ 改为两遍选择并在 `spawn_at` 使用 `nicheRng`。HP 范围由 `validation/step2-monster-hp-20261104/extract_hp.py` 从反编译提取（A0/A8、继承、Axebot 默认 StockAmount=2）：106/109 匹配，23 个范围更新（Crusher 209/219、Byrdonis 81..84、WaterfallGiant 240 等）；DOOR/DOORMAKER/ROYAL_GUARD 无对应类，保留 sampled_only。
> 遭遇随机改用原生一次性 RNG `Rng(seed + TotalFloor + hash(Id.Entry))`：`EncounterDef.nativeEntry` 由生成器输出（含事件 `_EVENT_ENCOUNTER` 后缀），`begin_combat` 在 `++floor` 后构造并传入 `setup_encounter`，覆盖 roster、Decimillipede/Scrolls/TwoTailedRats/CorpseSlugs 关联起始和 PunchOff 两次扣血；单 roster 不消耗抽取。修正 Decimillipede 起始映射为 WRITHE/BULK/CONSTRICT，CorpseSlugs 改为一次抽取轮转。MonsterAi 仍负责 `RollMove`/随机分支（与原生一致）。
> 验证：clean 完整重建（`build-clean-20261104h.txt`，exit 0、0 error）；CTest 33/33（`ctest-final-20261104i.txt`）；`rules_test.exe` **833 项检查 0 失败**（`rules-regression-final-20261104i.txt`）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104i.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常、本次 52.5 局/秒、战斗 5.7 µs/步（同机负载噪声约 51–108 局/秒，`benchmark-runs-1000-final-20261104i.txt`）。
> 仍为近似：roster 变体按采样权重而非原生 `NextItem` 列表；bag 耗尽回退仍用 MonsterAi；`docs/MONSTERS_REFERENCE.md` 未重生成。目标 DLL `9cb4f1ad…` 仍缺失，同种子整局差分阻塞。证据见 `validation/step2-monster-hp-20261104/`。

> **2026-11-04 续接更新（第六批）：Orobas 锁定选项与锁定抽取。**
> 原生 `OptionPool3` 在 TouchOfOrobas/ArchaicTooth 均不可建立时返回一个 `onChosen=null` 的禁用选项；C++ 现在把 INVALID 远古遗物槽标为不可选，并在锁定情况下仍消耗一次 `NextItem` 抽取。ArchaicTooth 的牌组条件改为原生起始牌集合 Bash/Neutralize/Unleash/FallingStar/Dualcast（不再错误接受 BREAK）。
> 验证：完整重建；CTest 33/33（`ctest-final-20261104f.txt`）；`rules_test.exe` **833 项检查 0 失败**（`rules-regression-final-20261104f.txt`）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104f.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常、70.5 局/秒、战斗 4.2 µs/步（`benchmark-runs-1000-final-20261104f.txt`）。

> **2026-11-04 续接更新（第五批，历史）：事件 RNG 边界与事件精化；43 IMPLEMENTED / 18 APPROXIMATE / 5 UNSUPPORTED。**
> 反编译核对全部双参数 `Rng.NextInt(min,max)`（原生上界排他），修正 4 处实现内容的 off-by-one：PunchOff 金币 91..98、LuminousChoir 费用 100..149、WhisperingHollow 金币 26..44、PunchOff 构造体初始扣血 2..9。StoneOfAllTime 的 Lift 改为按非空物理药水槽映射索引并用 `potion_remove_at` 保留空位，不再压缩药水带。
> 审计并提升 4 个事件为 IMPLEMENTED：DenseVegetation（金币 61..99、8 点伤害换金币、休息回血+休息遗物、战斗标准奖励）、BrainLeech（5 选 1 非战斗铁甲牌；Rip 5 伤害+3 张无色基础概率奖励）、PotionCourier（3 瓶 FoulPotion；Ransack 用 rewards RNG 取 1 瓶罕见药水）、SpiritGrafter（+25 回血与 Metamorphosis；Rejection 升级 1 张后 10 点不可挡伤害）。
> 验证：完整重建；CTest 33/33（`ctest-final-20261104e.txt`）；`rules_test.exe` **829 项检查 0 失败**（`rules-regression-final-20261104e.txt`）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104e.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常；本次并发测试负载下 65.1 局/秒、4.7 µs/步（`benchmark-runs-1000-final-20261104e.txt`）。
> 仍存 RNG 缺口（已记录未修）：怪物 HP 与部分遭遇随机当前用 MonsterAi 流，原生 `SetUniqueMonsterHpValue` 用 Niche 流且排除同侧重复 HP；109 个怪物中 108 个 HP 范围来自 512 次采样而非反编译。目标 DLL `9cb4f1ad…` 仍缺失，同种子整局差分阻塞。

> **2026-11-04 续接更新（第四批，历史）：事件战斗标准奖励修复；源码完整构建，CTest/pytest 全绿。**
> 反编译核对 `EncounterModel.ShouldGiveRewards`（默认 true，仅 BattlewornDummy 三个变体覆写 false）与 `RewardsSet.WithRewardsFromRoom`（ExtraRewards 追加在普通奖励之后）。修复后 DenseVegetation、PunchOff、TheLanternKey 的事件战斗恢复标准怪物奖励（金币、药水判定、三选一卡牌），再追加事件额外奖励：PunchOff 为遗物+药水，LanternKey 为固定特殊卡（放入下一个空奖励卡槽，不再覆盖标准卡槽 0）；BattlewornDummy 保持无标准奖励。`shouldResumeAfterCombat=false` 的事件在奖励列表生成时清除事件状态，离开奖励界面即结束房间。
> 验证：完整重建；CTest 33/33（`ctest-final-20261104d.txt`）；`rules_test.exe` **795 项检查 0 失败**（`rules-regression-final-20261104d.txt`）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104d.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常、70.4 局/秒、战斗 4.2 µs/步（`benchmark-runs-1000-final-20261104d.txt`）。
> `tests/test_smoke.py` 快照回放种子由 4 改为 5：修复后的奖励改变了轨迹，种子 4 在 250 步前死亡（种子 5 已验证 250 步非终局；条件跳过分支保留）。事件清单仍为 66 项中 39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED。目标 DLL `9cb4f1ad…` 仍缺失，同种子整局差分继续阻塞。

> **2026-11-04 续接更新（第三批，历史）：事件战斗与收尾内容；源码完整构建，CTest/pytest 全绿。**
> 事件清单 66 项：**39 IMPLEMENTED / 22 APPROXIMATE / 5 UNSUPPORTED**。本批实现 FieldOfManSizedHoles、GraveOfTheForgotten、Symbiote（PerfectFit/SoulsPower/Corrupted）、BattlewornDummy（三种 BattleFriend + 3 回合超时逃脱与三档奖励）、TheLanternKey（MysteriousKnight + 特殊卡奖励）；ThisOrThat 提升为 IMPLEMENTED（Ornate 走前置遗物抽取）。
> 验证：完整重建；CTest 33/33（`ctest-final-20261104c.txt`）；`rules_test.exe` **775 项检查 0 失败**（`rules-regression-final-20261104c.txt`）；artifact pytest 363 passed / 16 skipped / 0 failed（`pytest-final-20261104c.txt`）；`bench.exe run 1000` 1000/1000 正常终止、0 截断、0 异常（`benchmark-runs-1000-final-20261104c.txt`）。
> 剩余 unsupported：AROMA_PLACEHOLDER（无原生类）、WAR_HISTORIAN_REPY（`IsAllowed=false`，不可达）、CRYSTAL_SPHERE（原生 `IsDeterministic=false` 交互小游戏）、FAKE_MERCHANT（自定义商店库存）、TINKER_TIME（MadScience 动态卡型/词条）。
> 吞吐仍受机器噪声影响：连续三次 66.7/67.2/66.5 局/秒、战斗 4.4 µs/步；保存单次样本 67.6 局/秒、4.2 µs/步。与 ~2.3 µs 基线的差距仍待剖析，未以规则换速度。目标 DLL `9cb4f1ad…` 仍缺失，同种子整局差分继续阻塞。

> **2026-11-04 续接更新（第二批，历史）：第二部分 WIP；源码完整构建，差分与 Python 回归全绿。**
> 六个新角色/遗物样例集全部通过 C++ 差分：card-reward 82 例/5932 检查、persistent 18 例/415 检查、relic-lifecycle 24 例、silent 240 例/242956 检查、defect 176 例/191627 检查、necrobinder 198 例/3357 检查。全量 CTest 33/33；C++ rules_regression 686 项检查 0 失败。
> 身份：ruleset `native-41cef1ea-port-v6`、公开观察 v15（67784）、动作 schema v13（717）、ArmG feature v6、快照 v10；旧 checkpoint 会被身份检查拒绝。快照布局未变（新增选择类型仍在 1 字节字段内）。
> 事件清单 66 项：33 IMPLEMENTED / 23 APPROXIMATE / 10 UNSUPPORTED。本批实现 MorphicGrove、Bugslayer、EndlessConveyor、Trial、PunchOff、RanwidTheElder、RelicTrader、SelfHelpBook、WoodCarvings；新增 SHARP/SLITHER 附魔、遗物可交易判定（含 46 项 upon-pickup/pet 排除集）和 `remove_relic`。
> 10 个 unsupported 中 AROMA_PLACEHOLDER 无原生类、WarHistorianRepy 的 `IsAllowed` 恒为 false；真实缺口 8 项：CrystalSphere/FakeMerchant（交互 UI）、TinkerTime（MadScience）、BattlewornDummy/TheLanternKey（事件怪）、FieldOfManSizedHoles/GraveOfTheForgotten/Symbiote（PerfectFit/SoulsPower/Corrupted 附魔）。
> artifact pytest 363 passed / 0 failed / 16 skipped；workspace 根 `tests/` 不适用于该构建（不同 `deployment` 布局，基础仓库扩展陈旧）。
> 本机 `sts2.dll` SHA-256 为 `0861bfa1…`，与差分参照 `9cb4f1ad…` 不是同一构建，按约定不冒充目标参照；目标 DLL 整局差分仍阻塞。
> 1000 局冒烟 1000/1000 正常终止、0 截断、0 异常，70.1 局/秒，战斗 4.0 µs/步；同机交错历史对比中位数 68.2 → 65.3 局/秒（本批未重做 A/B）。未提交、推送或替换参照证据。最新断点见仓库根 `docs/native-port-step2-wip-20261031.md`。

# C++ 原生规则对齐：第四轮第一部分

## 2026-11-04 第二部分：Aeonglass / ByrdonisNest / Splash / 药水槽 / 原生顺序

身份：ruleset `native-41cef1ea-port-v6`、公开观察 v15（67784 = 局外 23519 + 战斗 44265）、
动作 schema v13（717）、ArmG feature v6、快照 v10。`PORT_SOURCE.json` 已同步。

本批完成：

- **药水实体空位**：`Player.PotionSlots` 的 null 空洞、首个空位添加、保留空位移除、满槽替换/丢弃、
  快照校验、公开观察和 Python 绑定统一按物理槽处理。
- **Splash**：全部已解锁角色池减去持有者池（仅当池数 >1）、可战斗生成 Attack、
  `GetDistinctForCombat` 取 3、可跳过、选中牌本回合免费并入手。
- **Aeonglass Boss**：512/535 HP、Ebb 22/26 + 33 格挡、Eye Lasers 11x2/12x2、
  Increasing Intensity（生成 Wither、假升级层数、累积力量）、WitheringPresence 六张计数、Artifact 3。
- **Wither**：不可打出、回合末在手伤害、假升级伤害。
- **ByrdonisNest**：TAKE 获得 Byrdonis Egg / EAT +7 最大生命、宠物 `IsAllowed`、
  首次运行 Overgrowth 教学房间事件槽 0。
- **事件与遭遇顺序**：四种幕的事件按原生 `AllEvents.Concat(AllSharedEvents)` 声明顺序入袋；
  Hive 遭遇按原生 20 项声明顺序，排除非原生 `SETUP_TUNNELER_NORMAL`；
  Boss `AllBossEncounters` / `BossDiscoveryOrder` 均按原生声明顺序。
  WhisperingHollow/WoodCarvings/ZenWeaver 已登记为 unsupported，保证清单完整但仍不入袋。

验证：完整重建成功；CTest 33/33；artifact pytest 362 passed / 0 failed / 17 skipped；
1000 局多 seed 整局冒烟 0 异常、0 截断；同机吞吐中位数 68.4 → 65.2 局/秒（波动范围内）。

证据：`validation/step2-aeonglass-events-20261104/`（README、CTest/pytest 输出、吞吐对比、阻塞说明）。
**没有目标 DLL 差分**：`9cb4f1ad…` 不在本机，本地 `0861bfa1…` 虽 `release_info.json` 标注同一
`41cef1ea/v0.111.0`，按约定不冒充目标参照；同种子整局原生轨迹仍阻塞。
本轮后续又按反编译实现 JungleMazeAdventure、InfestedAutomaton、DollRoom、SlipperyBridge、
TheFutureOfPotions、ZenWeaver、Amalgamator，事件清单为 66 项中 22 IMPLEMENTED / 23 APPROXIMATE / 21 UNSUPPORTED。
仍未完成：21 个 unsupported 事件未实现（其不入袋会改变事件袋 RNG；其中 CrystalSphere 为交互式
小游戏、FakeMerchant 为自定义商店 UI、WoodCarvings/Symbiote/SelfHelpBook/GraveOfTheForgotten/
FieldOfManSizedHoles 需要尚未建模的附魔 Corrupted/Sharp/SoulsPower/PerfectFit）、23 个 APPROXIMATE 事件、
Wither 假升级层数未进入公开观察（少编码，无隐藏信息泄漏）、战斗单步约 1.9x 变慢待剖析。
SlipperyBridge 的跳过集合用 62 个卡组位置的位图表示（超过 62 张时高位的跳过卡可能再次被抽到），
TheFutureOfPotions 的均匀三选一顺序是近似实现；均已在 `rules_regression.cpp` 注释中说明。
未提交、未推送、未覆盖旧证据或原始权重。



2026-10-31。当前开发副本，基线 `be401e8`；目标 `v0.111.0 / 41cef1ea`，
DLL SHA-256：`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。

**第一部分已完成：自伤累计、局外降级费用恢复、遗物计数关联。**
第一部分的 ruleset 为 `native-41cef1ea-port-v4`（已被 v5 取代，仅作历史）；`NATIVE_PARITY_COMPLETE=false`。
下一部分是遗物的真实选牌/跳过和持续状态；3～5步是工作划分预期，不是完整等价的完成承诺。

## 本步修改

- Crimson Mantle / Inferno 分别保存每次实际出牌或重放累计的 SelfDamage，升级改变能力数值而不改变一次自伤增量。保留两能力首次获得顺序；移除重获会清零并重新排序。
- Inferno 只在己方回合受到实际伤害时触发；敌方回合、直接扣血和完全挡住的伤害不触发。Tungsten Rod / Beating Remnant 减伤先于 Buffer，归零后不消耗 Buffer。
- Reflections 和 Wongo 离开分支统一调用降级函数，恢复基础费用/关键词，保留卡牌实例、附魔、成长和已独立表达的费用状态。
- Touch of Orobas 原位替换首件起始遗物，初始化新遗物计数并经过获取钩子，不扰乱其他遗物的计数。没有起始遗物时在变更前拒绝；已升级起始遗物按原生回退 Circlet。
- 新获取遗物清零空槽计数；Toy Box 的既有删除路径同步移动 ID/计数并清理尾槽。这里只修数组一致性，Toy Box 蜡制遗物规则仍未补齐。
- 新状态接入 clone、快照校验、公开观察和 Python 绑定；公开战斗观察末尾追加3维，原有偏移不变。局外 ArmG 编码布局不变，工作进程入口版本检查同步更新。

## 本步验证

| 检查 | 结果 |
| --- | --- |
| 实际目标 DLL 新样例 | 95个：自伤56、降级28、遗物替换11，C++对照通过 |
| C++回归程序 | 27个全部通过；自伤1379项检查、遗物替换293项检查 |
| 快照与隐藏状态 | 6742个运行中快照、6000次重采样通过；新状态另测32次重采样、克隆/恢复后续、非法状态拒绝与新战斗清零 |
| Python检查 | 131通过、4跳过（缺少可选历史训练/网站数据） |
| 局外桥接工作进程 | 使用临时未训练的当前格式模型启动后EOF，退出0；未操作游戏UI |
| 贪心整局冒烟 | 1000局正常终止，0异常、0截断，平均9.5层、0胜，约114.8局/秒 |

吞吐只代表本机这次贪心测试，不是训练速度或模型能力。没有重新训练，也没有证明完整同种子整局原生等价。
原始权重SHA-256未变：`cfcb115024b0b0a222b88bf0033ef55e1e7b3cf667194c9dbba36b923180b91c`。

新证据在 `validation/round4-step1/`，原生宿主/结果在 `native-round4-step1-{card,downgrade,relic}-fixtures/`。
首次测试失败也保留：降级测试的不可打出费用标记转换错误已纠正，原生结果未修改；旧迁移测试已改为要求现有身份保护，未放宽加载规则。
第三轮报告/原生结果未覆盖，其当时的总览保存在 `validation/round4-step1/source-before/PORT_STATUS.md`。

## 当前版本与限制

- 观察schema13、动作schema12、ArmG feature4、快照v8。卡牌ID不变：223；卡牌特征251、战斗动作343、ArmG动作1300。
- 公开观察46082维＝战斗29691＋局外16391。旧快照/模型依然须通过身份检查；没有审核好的旧权重迁移方案。
- 本步降级修复用于两个牌组事件。完整战斗费用修正栈仍缺少来源信息，例如 Snecko 和 Frantic Escape；不宣称任意战斗中降级已完整等价。
- 原生最终死亡会清空全部能力，C++保留既有终局能力值。本步验证致死效果与失败结果，不包含全局死亡清理对齐。
- Splash / Mad Science、复杂遗物真实选择和持续机制、34项缺失事件、Aeonglass Boss、完整账号过滤与房间生成时序仍待完成。
- 原生桥接的活动选牌网格、Pael暂存范围与游戏UI执行仍不完整。

## 复现与交付

```sh
/opt/anaconda3/bin/python validation/build_local.py
/opt/anaconda3/bin/python validation/round4-step1/run_cpp_tests.py
/opt/anaconda3/bin/python validation/round4-step1/bridge_startup_check.py
```

Python完整选择命令见 `validation/round4-step1/commands.txt`。本机用Apple clang/Python3.11验证；未验证Windows或CMake构建。
源码增量补丁：`validation/round4-step1/native-rules-port-v4-step1.patch`，对本步前v3源码备份做apply检查。
第三轮累计基线补丁仍保留。补丁不含游戏DLL、宿主二进制或权重。未提交、推送、部署或发布。

## 2026-11-04 本机回归记录

运行环境：Windows/MSVC 19.51、Ninja、`/UNDEBUG`（assert 保持启用），Python 来自 `D:/sts2_datacollection/sts2/.venv`。

| 检查 | 结果 |
| --- | --- |
| CTest | 33/33 通过（含 `regent_mechanics` 51 项检查） |
| artifact `tests/` pytest | 352 passed、0 failed、16 skipped |
| workspace `tests/` pytest | 39 passed、1 skipped |

本轮收尾修复（均为根因修复，未放宽规则）：

- **快照确定性**：`Card` 的尾部 padding 进入原始对象快照哈希；`Card` 默认构造先清零整个对象再设 `combatCostCap = -1`，`test_deterministic_replay`、`test_snapshot_blob_is_deterministic` 恢复通过。
- **回合末费用修正清理**：原生 `PlayerCombatState.EndOfTurnCleanup` 在弃手后清掉所有牌的 EndOfTurn 局部费用修正；C++ 之前只清 `played`（4）而从不清理 `2`，重复打出 Bullet Time 会耗尽修正槽并抛异常。现在在 `discard_hand`/空灵结算后遍历 hand/draw/discard/exhaust/play/returnNextTurn 清理 expiration 2；相邻完全相同的绝对修正在 `card_modify_cost` 中去重（解析费用相同）。
- **schema/身份升级**：`observe.h` 公开观察 v14、动作 v13（尺寸由 597 卡/276 能力词表推导：67775/44261/625/717）；快照头版本 9；ruleset `v5`；`PORT_SOURCE.json` 同步，并单列本机 DLL 哈希。
- **golden 重录**：`test_map_golden_hashes` 9 个摘要按 v0.111 对齐后的生成器重录；结构性质仍由 `test_map_generation_properties` 与原生 `native_act_41cef1ea.json` 差分（`native_act_alignment`）覆盖。
- **测试夹具修正**：事件池包含 Underdocks（event_act 4，与 act 0 共享事件）；Dusty Tome 先调用新增的 `prepare_dusty_tome`（模拟 Darv 预备）；`GRAPPLE` 保留槽与多人专属卡按绑定标志跳过；事件遗物计数 133。
- **ArmG 用例**：隔离扩展替身改为当前引擎的字节副本（checkpoint 设置本就按加载引擎校验）；分段梯度容差写明 float32 批量矩阵噪声上界（实测约 7.5e-6）；需要 `STS2_PRIOR_PYD` 与归档 `runs/*.pt` 的预检用例在缺件时明确 skip。

储君实现覆盖：星费读取/支付、星 X、Void Form 免耗与强制结束回合、Child of the Stars 格挡、Star Next Turn、Orbit 每 4 能量触发、Monologue 力量回滚、Pale Blue Dot 第五张牌后抽牌、Sword Sage 重放、Arsenal 生成加力量、Supermassive 全战斗生成计数、Tyranny 抽牌+弃牌选择、Spectrum Shift 生成、Reflect 反伤与持续时间、Beat Into Shape 命中计数。未覆盖/仍按旧近似：星费临时修改栈（Snecko 类全局费用仍共享既有表示）、Split 类多段目标统计、以及任何原生储君差分断言。

仍未完成：原生储君样例生成与差分；药槽空位模型与遗物选择/持续状态全部接入；Splash/跨角色生成与单人过滤审计；整局冒烟与训练。未提交、推送或替换参照证据。

## 2026-11-04 第五轮：全内容覆盖收尾（本机 Windows/MSVC）

运行环境：Windows/MSVC 19.51、Ninja Release、测试目标 `/UNDEBUG`，Python `D:/sts2_datacollection/sts2/.venv`。
参照：原生 v0.111.0 / 41cef1ea，本地 DLL SHA-256 `0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9`。
目标 DLL `9cb4f1ad...` 本机不存在，本轮没有、也无法做目标差分；下面的“通过”均指本地 C++ 回归。

身份（代码与 `PORT_SOURCE.json` 一致）：ruleset `native-41cef1ea-port-v10`、公开观察 v19（70651 维，战斗 44306）、动作 schema v17（729 维）、ArmG feature v7、快照 v14。

| 检查 | 结果 |
| --- | --- |
| 全量重建 | 成功（Ninja，含两个新测试目标） |
| CTest | 41/41 通过（新增 `relic_coverage_round7` 154 项、`potion_coverage_round7` 31 项） |
| dev 副本 `tests/` pytest | 362 passed、17 skipped（跳过项均为缺少历史训练/网站数据） |
| 五角色 × 5 种子整局冒烟 | 25 局，0 异常、0 截断，约 6202 步/秒；全部正常终止（策略失败，不作胜率结论） |

本轮实现/修复：

- **多人专属卡**：16 张 `CardMultiplayerConstraint.MultiplayerOnly` 卡全部实现单人退化语义（Blaze、Midnight、Outrage、The Ball、Demonic Shield、Tank、Imitation Learning、Beacon of Hope、Gang Up、Huddle Up、Intercept、Knockdown、Lift、Mimic、Rally、Tag Team），并把 Tank 的 1.5× 受伤倍率、Covered 归零、Imitation Learning 的 Power 克隆/自动打出接入战斗钩子。模拟器没有多人运行时；这些效果只在单人目标/队友为空时验证，不宣称多人语义已验证。
- **战斗/遗物缺口**：Brimstone 每回合重复加力修复；Ghost Seed 从铁甲专属改为全角色 Basic Strike/Defend；Phylactery 战前召唤接入；Ring of the Drake、Divine Destiny、Infused Core 的额外效果补齐。
- **Electric Shrymp / Imbued**：新增 Imbued 附魔、卡组选牌 kind 23、回合 1 手牌/抽牌堆自动打出、抽牌堆底部置入；并修复 `card_grid_can_select` 未校验 kind 23 资格（会接受任意牌并抛异常）。
- **Miniature Tent**：新增显式 `REST_LEAVE` 动作与用尽位掩码，休息站可连续使用多个选项；动作 schema 从 v16 升到 v17，ArmG feature 6→7，工作进程门禁改为 `(19,17,7)`。
- **角色池时序**：`BattleContext::init` 新增角色池参数并在战前钩子前赋值；此前 `begin_combat` 在 init 之后才写 `characterPool`，导致非铁甲角色的 Big Hat 按铁甲池抽样。`RunContext::begin_combat` 现在把角色作为 init 参数传入。
- **Dramatic Entrance**：在无色卡分派中显式落为全体攻击，不再只依赖通用回退。
- **测试**：新增 `relic_coverage_round7.cpp`（154 项，覆盖本轮之前无测试引用的遗物、含 Alchemical Coffer、Archaic Tooth、Ectoplasm、四张 Fake 遗物、Fake Snecko Eye 与新实现遗物）、`potion_coverage_round7.cpp`（31 项，覆盖 20 个此前无测试的 药水）；`multiplayer_cards.cpp` 扩到 105 项；`native_card_alignment.cpp` 增加 Dramatic Entrance 基础/升级断言。

覆盖清单（`scripts/content_inventory.py` 重新生成 `docs/content-inventory-20261104.md`）：

- 卡牌 596、药水 66、遗物 300；无测试引用：卡 0、药水 0、遗物 0。
- 无源码效果引用：仅 `DEPRECATED_POTION`、`DEPRECATED_RELIC`（占位/废弃）与 `WONGO_CUSTOMER_APPRECIATION_BADGE`（原生无行为的事件标记遗物）。
- 多人专属卡 37 张单独列出（其中 16 张为 MultiplayerOnly 约束）；单人运行时边界见上。

仍未完成/边界：

- 目标 DLL 严格差分不可做；本地证据级别是“移植自本地反编译 + 本地 C++ 断言”，不是原生差分。
- 多人战斗运行时不存在：multiplayer-only 卡只验证单人退化路径与目标/队友语义的代码分支，不宣称多人完整验证。
- 组合覆盖仍是主效果级：跨卡/跨遗物的长链组合、全部事件分支组合、Snecko 类全局费用栈与多段目标统计未逐项穷举。
- 未重新训练模型；未提交、推送、部署，未覆盖原始权重。
