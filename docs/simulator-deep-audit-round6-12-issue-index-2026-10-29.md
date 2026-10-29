# 高速模拟器深度审计第 6–12 轮问题总表

整理日期：2026-10-29

## 范围和状态口径

合并第 6 轮及其修复报告、第 7 轮、第 8 轮和第 12 轮累计报告，按根因去重。仓库没有独立的第 9、10、11 轮审计 Markdown；这些轮次的探针结果散见第 8、12 轮报告。状态根据报告记载，不代表本次重新运行探针：

- **已修复（有报告验证）**：修复报告明确记载定向探针/回归通过。
- **仍复现**：第 12 轮或标注轮次明确记载仍失败。
- **待复核**：早期探针失败，后续报告没有明确复验结论。
- **部分修复**：有部分正向回归，但同一根因仍有其他缺口。

## 结论

- 第 6 轮的 8 组问题有修复报告，记载 36/36 探针、288/288 规则回归通过；第 7 轮基线也确认第 6 轮探针全通过。
- 第 7、8 轮发现的许多规则差异仍在。第 12 轮再度记录种子/RNG、遭遇袋、A0–A10、怪物、奖励、遗物、事件、商店、观察等缺陷。
- 当前最高优先级：快照恢复可接受畸形状态并崩溃/越界；生产源码构建失败且 Python 扩展过期；Python 参数窄化导致非法动作别名。
- 随机长跑和分支克隆稳定只说明工程不变量通过，不代表与真实客户端规则等价；逐步客户端 replay 差分仍未完成。

## 1. 已修复：第 6 轮问题

| 编号 | 原问题 | 修复报告记载 |
|---|---|---|
| R6-01 | 9 张无色攻击牌没走 FromCard 伤害修正链 | 已改用 attack_from_card |
| R6-02 | Mummified Hand 把 X 费牌改成固定 0 费 | 只选本地费用大于 0 的牌 |
| R6-03 | HardToKill、Slippery 等伤害上限缺失 | 已实现伤害上限、Slippery 减层；修复报告也列出 Intangible |
| R6-04 | Axebot、PhrogParasite、Decimillipede、ThievingHopper、Door 生命周期错 | 已处理复活、召唤、复接、逃跑、阶段转换 |
| R6-05 | 多个正常三幕 Power 只有数值没有行为钩子 | PaperCuts、Territorial、Rampart、Slumber、VitalSpark、PersonalHive、Imbalanced、CrabRage、PossessSpeed/Strength、Galvanic 等已补行为 |
| R6-06 | 公开观察缺战斗计数/可见状态 | 观察升 v7、动作升 v6，加入相应字段 |
| R6-07 | MembershipCard、TheCourier、LavaLamp、Planisphere 无效果 | 已修折扣/补货、无伤奖励升级、UNKNOWN 房间治疗 |
| R6-08 | 战斗 RNG 共用导致动作互相扰动 | 已拆分 Shuffle、CardGeneration、PotionGeneration、CardSelection、EnergyCosts、Targets、MonsterAI 等流 |

修复报告还记载第 2–5 轮探针通过、矩阵/遭遇/整局扫描无失败。第 12 轮后来发现源码、扩展、schema 漂移；旧结果不能代替当前源码复验。

## 2. 工程构建与输入边界

### P0：快照恢复不验证内部状态（第 12 轮新增，仍复现）

RunContext::restore() 只查 magic/version/size 后 memcpy，没有校验计数、枚举、索引、HP、金币、地图、pending choice 或战斗状态。快照矩阵 139 字段、311 案例中接受 301 个非法输入，拒绝 0 个；9 个崩溃、1 个超时。deckCount、potionCount、各 battle pile count、pendingCount 设为 INT_MAX 可崩溃/越界，offeredCount=INT_MAX 超时。负 seed、负 HP/金币、非法卡牌 ID 等也被接受。

**影响：**不可信快照可造成进程崩溃、越界读取或错误动作。需要逐字段校验，失败时原子拒绝。

### P0/P1：生产构建失败，测试运行旧扩展（第 12 轮新增）

生产构建在 monsters.cpp:533 因缺少 relics.h 声明失败。Python 测试加载的 .pyd 比当时的 battle.cpp 和 monsters.cpp 旧；旧扩展的测试通过不能证明当前源码构建成功或生产行为已更新。

### P1：Python 绑定将越界动作参数回绕成合法动作（第 12 轮新增）

make_action() 直接将 hand/target/uid 窄化为 uint8/uint16。例如 256、256、65536 回绕成 0、0、0；step、step_combat、action_features 等入口受影响。探针显示非法动作被接受并与合法动作别名。

**影响：**外部策略输出越界时可能执行另一张牌或另一个目标。必须在窄化前校验原始整数范围。

### P1：schema 版本、维度、README、扩展互相不一致（第 12 轮新增）

当时实测 PUBLIC_OBS_DIM/PUBLIC_COMBAT_OBS_DIM：生产扩展 17815/10378，源码/快照 17835/10398，README 17805/10368；obs/action version 仍全部是 7/6。版本未表达 layout 变化。

**影响：**checkpoint/部署端可能按错误 layout 读取向量。统一维度、提升 schema 版本、更新 README，并测试精确值和扩展新鲜度。

### 测试合同：固定 seed 必胜断言失效（第 8、12 轮）

test_full_run_completes_and_wins 和 test_jsonl_trajectory_and_batch 要求 seed 273/443 必胜，报告显示分别在 floor 19 或更早死亡。规则变化会让固定轨迹漂移；应改测终止、合法动作、资源边界和 schema 性质，或重新选取并解释胜利 seed。

## 3. RNG、种子和随机池

### RNG 原语部分修复，run/event seed 仍错

- R7 发现 NextInt/NextBool 与 .NET 不同：seed 0 第 155,215 次 Next(100)，C++=16、.NET=15；Gaussian rounding 也不同。
- R8 记载 .NET RNG 前缀、counter、Gaussian 新回归通过，故底层采样有部分修正证据。
- R12 仍发现整数 master seed 未按 C# 字符串 seed 的 deterministic hash 派生；seed 123 的 run RNG seed 应为 1816791482，当前首个 UP_FRONT 样本和初始地图不同。
- Shared Event RNG 无条件混入 player id，报告中 2,000/2,000 样本不一致。
- 多页事件重建 event_rng()，没有延续 EventModel.Rng.Counter。
- R6 战斗 RNG 独立流有修复报告；run/event 层种子和流仍需修。

### 遭遇袋、事件袋、遗物袋不符合 GrabBag（第 12 轮仍复现）

- encounter weak/normal/elite bag 未实现 GrabAndRemove 和 tag 去重；R12 报告 normal encounter 每幕有 500 个额外 weak 样本，normal 重复样本 500/500。
- encounter 缺 tags，无法排除相邻同 tag 遭遇。
- event 抽取未先调用 event_allowed_now()/IsAllowed：无金币时 Wongo、无药水时 StoneOfAllTime、满血时 UnrestSite 仍能入池。
- relic pool 缺 seen/front-back queue 和完整楼层 IsAllowed；20,000 次中 2,385 次命中禁用遗物；商店池也曾混入 TheCourier、OldCoin。
- 第 7 轮全局随机遗物入口还用即时加权池，而非参考的 relic grab bag 顺序。

### 怪物随机招式数据映射错误（第 12 轮仍复现）

67 个 weighted-random 分支中 66 个字段不一致、65 个把 weight/cooldown 写反；AXEBOT 500/500 次只选 ONE_TWO。会改变动作分布和冷却节奏。

## 4. A0–A10 进阶规则整体缺失（第 12 轮仍复现）

A0–A10 初始化结果完全相同（gold 99、药水槽 3、deck 10、bane 0、elites 5、axe_one_two 5）。缺项：

- A1 精英数量；A2 Ancient 回复；A3 初始金币；A4 药水槽；A5 Ascender's Bane；A6 休息点数量；
- A7 奖励赔率/升级率（A0/A7 300 次卡奖励 hash 相同）；
- A9 敌人伤害（多个 runtime 伤害仍读 A0 表）；
- A10 双 Boss。

报告纠正：round11_a8_intent_audit.py 实际测试 A9 DeadlyEnemies 伤害，却标作 A8；181/182 不可作为 A8 错误证据，A9 伤害表仍要重写验证。

## 5. 怪物、战斗初始化和实例状态

### 怪物 Power、死亡和阶段钩子缺失/错误（R7/R8/R12）

仍列出的 Power/行为包括：Illusion、HighVoltage、Ravenous、Shriek、Skittish、Surprise、Thievery、Hatch、Plow、Soar、Flutter、Burrowed、SteamEruption、Surrounded，以及部分 PaperCuts hook。R6 已修若干 Power（例如 Galvanic、CrabRage 等），不能据此推断其余已齐全。

具体报告问题：

- Illusion 致命伤未 revive；Surprise 死亡不召唤 Gremlin；Hatch 不孵化；GremlinMerc 不偷金币。
- Soar powered card attack 减伤、Plow 阈值眩晕、SteamEruption 死亡阶段曾动态失败。
- GasBomb 自爆后仍 alive；Guardbot 不给 Fabricator 15 Block；ThievingHopper 不删除被偷牌。
- Door 二次复活最大生命 215，参考 195；Rocket/Crusher BackAttack 伤害 1.0 倍，参考 1.5 倍。
- Noisebot/TheInsatiable 随机插牌被错标成已知牌顶；TheInsatiable Sandpit 噬入/最终击杀未完成。
- BeltBuckle 药水数量变化时激活/停用错误；PaperCuts 最大生命损失未正确触发 SelfFormingClay。
- R7 静态检查还点名 Kaiser Crab BackAttack 标记、CrabRage、PossessSpeed/Strength 等；R6 修复报告称其中部分已补，状态要逐项复核。

### encounter 级初始状态丢失（R8 新发现；R12 初始化仍广泛有缺口）

生成器把遭遇的协调招式/状态压成单怪权重，运行时又逐只独立抽样。2,000 seeds 失败数：DecimillipedeElite 三段起手 1,557；ChompersNormal 1,501；InkletsNormal 1,704；PunchOff 起手 1,640；PunchOff 两只 HP 约束错误 4,000 个个体；ScrollsOfBiting Normal/Weak 1,826/1,569；TwoTailedRats 1,557；TheKinBoss 1,501。Decimillipede 分段还出现 2,571 个奇数 MaxHP、838 组重复 MaxHP；CubexConstruct 入场 13 Block 缺失（2,000/2,000 为 0）。

### 17 个实例化 Power 共用状态（第 12 轮新增）

19 个 C# Power 为 IsInstanced；C++ 仅 Automation、TheBomb 有专用实例数组，其余 17 个缺 per-instance 状态：Covered、Flanking、Grapple、Guarded、Heist、Knockdown、MagicBomb、Monologue、Nightmare、Orbit、Panache、RollingBoulder、Sandpit、Swipe、TagTeam、Thievery、ToricToughness。

探针：两个 RollingBoulder 两回合总伤害应 30、实测 25；9 个 Automation 抽满 10 张应有 9 能量、实测 8；Covered 应将 10 点 powered attack 降至 0、实测 10；两个 Grapple 对 Intangible 目标应造成 2、实测 1。Automation 有 8 实例硬上限；TheBomb 160 是存储上限，却与“规则无上限”注释冲突。

## 6. 卡牌升级、生成池与卡牌效果

### 27 张降费/关键字升级牌被判不可升级（R7-02，待复核）

card_upgradable() 只查伤害、格挡和 varUp，漏掉 costUp/flagsUp。误判牌为：AGGRESSION_CARD、BARRICADE_CARD、DARK_EMBRACE_CARD、HAVOC、HELLRAISER_CARD、INFERNAL_BLADE、JUGGLING_CARD、STOKE、TANK_CARD、UNMOVABLE、ALCHEMIZE、ANOINTED、BEACON_OF_HOPE、CALAMITY_CARD、DISCOVERY、MAYHEM_CARD、NOSTALGIA_CARD、PROLONG、SCRAWL、SECRET_TECHNIQUE、SECRET_WEAPON、STRATAGEM、APOTHEOSIS、DISTRACTION、ENTRENCH、HELLO_WORLD_CARD、WISH。影响休息、事件、遗物和战斗中升级；R12 仍指出 A7 升级率错误，但未逐项复验这 27 张。

### 战斗卡池边界只部分有修复证据（R7-16/R8-02）

- R7 报告 Ancient/Event/Basic 被混入变换、药水、Discovery 等池；R8 的正向回归称 Ancient/Event/Status/Token rarity 过滤已通过，属部分修复。
- R8 仍指出 CardDef 没有 CanBeGeneratedInCombat，Feed、HandOfGreed、Alchemize 等不应生成的牌仍可被随机生成。
- random_card_of_type() 混合 Character 和 Colorless 池；Orobic Acid、Crossbow、Choices Paradox 应只从 Character 池取。
- Jack of All Trades 应在合法 Colorless 池去重并排除自身；Vexing Puzzlebox 应随机生成 Character 任意类型并整场免费；Toolbox 应给三张不重复、合法、原价 Colorless 牌选择，而非临时降费。
- CARD_DEFS 缺少 Event rarity/池归属，不能准确表示 Ancient/Event/普通角色池。

### EventCardPool 与其他牌缺规则

R7 统计 23/27 张 EventCardPool 卡无显式效果分支。失败例：Apotheosis 不升级手牌；Apparition 不给 Intangible；Caltrops 不给 Thorns；Clash 混有非攻击牌仍可打；Exterminate、Peck、Maul、Rip and Tear 只打第一段；FeedingFrenzy 不加 Strength；NeowsFury 不回收弃牌；Rebound 不把下一张牌放回牌堆顶；Whistle 只伤害不眩晕。Distraction、DualWield、Enlightenment、HelloWorld、MadScience、Metamorphosis、Squash、Stack、ToricToughness、Wish 的附加规则也缺失/不完整。

R12 仍确认：ToricToughness 不恢复被清掉的格挡；DualWield 不开始选牌；Stomp 已在手时不动态降费；Luminesce 给 3 能量，参考 5/6。MadScience 缺类型/rider 状态。Wish、Stack、DualWield 等依赖当前缺失的嵌套选择动作模型。

### 附魔、选牌、bundle 没有动作/数据模型（R7/8/12 仍复现）

Card 未记录 enchantment identity/amount；RunAction 不能表达附魔、卡牌/遗物 bundle、多选、休息 Cook/Clone 等。Sown、Vigorous、Swift、Imbued、Glam、Clone 被升级或随机结果替代；MassiveScroll 没有按约束生成三张供选择；Choices Paradox、GlassEye、SeaGlass、Claws 的选择合同被随机结果或直接加牌替代。

### 加牌/变牌绕过统一 hook，clone UID 重复（R7/R12 仍复现）

事件和遗物直接调用加牌路径，未统一触发 AfterCardChangedPiles。Wellspring + Guilty + Lucky Fysh 不加金币；Book of Five Rings 多次加牌不触发；curse 不触发 Darkstone Periapt；Bing Bong 两张奖励可能复制同一 UID。R12 仍列 Lucky Fysh、BookOfFiveRings 和加牌 hook。

## 7. 奖励、商店、药水和遗物

### 奖励阶段、赔率与选择不符

- R7 报告精英卡奖励曾使用普通赔率（3% rare/37% uncommon，参考 10%/40%），Boss 未重置 rarity offset；R8 更正旧的 6.1% 探针结论无效，连续奖励实测约 10.8%，因此赔率须在持久 pity 状态下重测。
- Silver Crucible 计次但未用于奖励升级；R6 LavaLamp 已有修复证据。
- BlackStar 精英后额外遗物、LavaRock Act 1 Boss 两件遗物、DreamCatcher 休息后卡奖励曾失败；R12 仍列出。
- Boss relic、精英 relic、药水奖励有路径自动入袋，缺少选择/跳过/离开阶段；药水奖励有空格时直接加入。
- 满容量时领奖/购买会成功但没有物品（见第 9 节）。

### 药水池与商店药水（R8 失败，R12 未明确复验）

random_potion_from() 均匀抽 52 项，参考先过滤合法 Character+Shared pool，再按 65/25/10% rarity；当前约各 30.77%，且混入 FoulPotion、GlowwaterPotion、PotionShapedRock、DeprecatedPotion。商店药水有放回、会重复。R8 探针：2,000 次奖励中 36 次 Deprecated、151 次非法 rarity；15,000 商店槽中 282/1,125；5,000 家商店有 293 家重复。R12 的 208 药水执行矩阵通过，不足以证明池分布/合法过滤/去重已修。

### 商店经济与遗物抽取

- 价格 hook 应转 int 截断，当前 lround；75×0.5 应 37，实测 38。
- 商店 rarity 不应复用奖励 pity；TheCourier 补货应重新 roll 相应 rarity/pool。R6 修了折扣/补货入口，但 R7 后续仍报 rarity 不对。
- relic 三槽有放回；R12 100,000 家商店有 1,428 家重复（首例 seed 56）。
- relic IsAllowed 楼层门控不完整，20,000 抽中 2,385 次禁用遗物。
- 全局 relic pool 缺 front/back/seen queue。
- 容量满购买可能扣钱、标 sold/refill，却未增加物品。

### 遗物行为与静态覆盖遗漏

R7 动态失败：CallingBell 不加 CurseOfTheBell/三选遗物；PreservedFog 移除牌但不加 Folly；ScrollBoxes 未花光金币/不选 bundle；SereTalon 未加 2 curse 和 3 Wish；TanxsWhistle 不加 Whistle；DistinguishedCape 不加 3 Apparition；SwordOfStone 五精英后不换 SwordOfJade；PumpkinCandle 跨章节持续加能量；VeryHotCocoa 仅下一场生效；WongoMysteryTicket 每五场重复发奖；ToyBox 可融化外来 Strawberry；ToastyMittens 未优先耗竭非 Innate；BowlerHat 只提高战斗金币；AmethystAubergine 漏 Act1 Boss 金币；BigMushroom 首回合仍抽 5；BloodSoakedRose 不加 Enthralled。

古代遗物失败：JewelryBox 加随机 rare 而不是 Apotheosis；GlassEye 直接加 3 张而非 5 个候选；SeaGlass 直接加 3 张 uncommon 而非 15 张分层候选；Claws 任意变换而非选最多 6 张变 Maul。R12 仍点名 BloodSoakedRose、PumpkinCandle、BowlerHat、GoldenCompass、BlackStar、LavaRock、DreamCatcher、GlassEye、SeaGlass、Claws。

静态引用遗漏清单：
- 74 个有实际 AfterObtained 的遗物中，16 个在 relics.cpp 无对应引用：BEAUTIFUL_BRACELET、BYRDPIP、DOLLYS_MIRROR、ELECTRIC_SHRYMP、FAKE_SNECKO_EYE、GNARLED_HAMMER、GOLDEN_COMPASS、KIFUDA、NUTRITIOUS_SOUP、ORRERY、PAELS_CLAW、PAELS_GROWTH、PAELS_TOOTH、PUNCH_DAGGER、ROYAL_STAMP、TRI_BOOMERANG。
- 当前 ancient options 可出现的 91 个遗物中，另有 15 个在 events.cpp 之外无引用：BEAUTIFUL_BRACELET、BLACK_STAR、DRIFTWOOD、ELECTRIC_SHRYMP、GLITTER、GOLDEN_COMPASS、LAVA_ROCK、MEAT_CLEAVER、NUTRITIOUS_SOUP、PAELS_CLAW、PAELS_EYE、PAELS_GROWTH、PAELS_TOOTH、TRI_BOOMERANG、WAR_HAMMER。
- R12 还指出 15 个普通遗物没有非 event 运行引用，需逐项核实是否有意为之。

### 药水/事件状态机错误（R12 仍复现）

| 场景 | 期望 | 实测 |
|---|---:|---:|
| Cauldron 战斗外等待五项选择 | 0 | 405 |
| Lost Coffer 等待牌组奖励 | 0 | 500 |
| Lost Coffer 等待药水奖励 | 0 | 500 |
| Alchemical Coffer 不重复同组 | 0 | 58 |
| Delicate Frond 填满药水带 | 0 | 237 |

## 8. 事件内容和训练 MDP

R7 事件内容失败/待复核：

- DenseVegetation Rest 应按 Mimicked Rest 回复 30%（含回血遗物），不是直接回满。
- StoneOfAllTime Push 应加 Vigorous 附魔，不是随机升级。
- AromaOfChaos 可变出 Status/Curse（seed 5 得 SOOT）；应过滤非法变换对象。
- add_random_common_card() 曾抽到 uncommon/rare；RoomFullOfCheese 得到 uncommon Drum of Battle。
- SpiritGrafter Let It In 应给固定 Metamorphosis，却给随机 colorless；Wongo bargain bin 应 common，曾给 rare。
- Wellspring Bottle、PotionCourier Ransack 未推进 Rewards RNG。
- SapphireSeed Sown 用升级代附魔；BrainLeech、RoomFullOfCheese 等多选被 RNG 自动决定。
- HungryForMushrooms + FragrantMushroom 共造成 30 伤为正确行为，不是 bug。

事件多选、bundle、附魔、Cook/Clone、奖励保留/跳过被随机结果、自动入袋或简化动作替代；R12 Cauldron、Lost Coffer、Alchemical Coffer、Delicate Frond 仍有具体状态机失败。这些会改变合法动作和训练 MDP。

## 9. 容量失败不是原子转换（R7/8/12 仍复现）

牌组/遗物袋满时，加牌、买牌、买遗物、领奖可能返回成功但没加物品；商店仍扣金、标记 sold/refill；事件可能静默丢牌。应在任何金币、库存或状态修改前检查容量，失败时不产生部分副作用。

## 10. 公开观察状态混叠

R6 已补一批观察字段，但 R7/R12 又发现新的状态碰撞。R12 observation collision 探针 21/21 FAIL。

**战斗/卡牌/怪物遗漏：** exhaustedThisTurn、hpLostThisTurn、nextTurnEnergy、nextTurnDraw、tookUnblockedDamageThisTurn、attackSkillPlaysThisTurn、blockCardPlaysThisTurn；monster offBalance、stunned、slowCardsThisTurn、tempStrengthLoss、nemesis、combatEndBlocker；卡牌 etherealThisCombat、retainThisCombat、bonusDamage；active play replay 进度；Surrounded、当回合未格挡伤害、本战斗未格挡攻击伤害；当前 skillsLocked（合法动作不同但观测相同）。

**整局遗漏：** rewardIsBoss、potionSlots、mawBankPurchased、cardsAdded、silverCrucibleUses、nextCombatUpgradeHand、emberTeaCombats、furCoatCombats、toyBoxCombats、wongoCombats、swordOfStoneWins、paelsWingSkips 等；teaSetPending 与 nextCombatDazed 混叠；SealOfGold 实际改 battle.gold，观测仍编码旧 rc.gold。

public run deck 只按 CardId 聚合，不能表示具体哪张实例升级；已知牌顶顺序和超过前 16 张的完整信息有限。隐藏 draw/discard 顺序未泄漏是正确行为，不能为了消碰撞而公开隐藏信息。

**影响：**同一 observation 对应不同合法动作/未来转移，策略会遇到状态混叠。更新向量时同步升级维度、版本和 checkpoint。

## 11. 第 7/8/12 轮问题状态速查

| 原编号 | 主题 | 状态 |
|---|---|---|
| R7-01 | .NET RNG 原语 | 部分修复证据；seed 派生/event RNG 仍复现 |
| R7-02 | 27 张降费/关键字升级牌漏检 | 待复核；A7 升级率仍错 |
| R7-03 | 怪物 Power | 大量仍复现 |
| R7-04 | encounter/event/relic bags | 仍复现 |
| R7-05 | 奖励赔率、Crucible、BlackStar/LavaRock/DreamCatcher | 仍复现/待复核 |
| R7-06 | 统一加牌 hook、Bing Bong UID | 仍复现 |
| R7-07 | 事件内容 | 待复核，选择/状态机仍有问题 |
| R7-08 | 遗物效果/ancient 遗物 | 大量仍复现/待复核 |
| R7-09 | 附魔和嵌套选择模型 | 仍复现 |
| R7-10 | 商店经济/补货/relic bag | 部分仍复现 |
| R7-11 | PowderedDemise 延迟结算 | 待复核 |
| R7-12 | Minion 击杀不触发 Feed/Hand of Greed 奖励 | 待复核 |
| R7-13 | 公开观察状态混叠 | 仍复现，R12 21/21 collision |
| R7-14 | 容量失败原子性 | 仍复现 |
| R7-15 | snapshot 仅校验 header | 扩大为 P0 畸形快照缺陷 |
| R7-16 | 卡池/EventCardPool 效果 | Ancient/Event rarity 有部分修复证据；战斗生成限制和具体牌仍有缺口 |
| R7-17 | 奖励/界面近似改变 MDP | 仍复现 |
| R8-01 | 药水合法池/rarity/去重 | 第 8 轮失败，第 12 轮未明确复验 |
| R8-02 | CanBeGeneratedInCombat 与 Character/Colorless 池 | 第 8 轮失败，第 12 轮未逐项复验 |
| R8-03 | encounter 协同初始化 | 第 8 轮失败，第 12 轮怪物初始化仍有缺口 |
| R12 | snapshot、binding alias、schema、实例 Power、卡牌合同 | 新发现，详见上文 |

R7-11 和 R7-12 是早期具体探针失败，但后续报告未给明确状态；不能默认已修。

## 12. 建议修复顺序

1. 恢复可信构建/部署链：补 relics.h，重建当前 .pyd，锁定二进制新鲜度和精确 schema 维度。
2. 堵住输入边界：快照逐字段验证、原子拒绝；binding 在窄化前检查动作范围。
3. 修确定性基础：master seed、共享/多页 Event RNG、GrabBag、AI random 数据映射。
4. 修状态转移：A0–A10、encounter 协同初始化、怪物 Power/生命周期、实例 Power 独立状态。
5. 修卡牌/动作模型：生成池过滤、EventCard 效果、附魔/嵌套选择、统一牌堆变更 hook。
6. 修奖励与经济：奖励选择、relic/potion pool、商店赔率/去重/补货、遗物 hook、容量原子性。
7. 扩展公开观察并同步 layout/version/checkpoint。
8. 每个修复保留失败和正向对照并运行累计探针；最终做真实客户端逐步 replay。随机整局全绿不能替代规则 oracle。

## 来源报告

- simulator-deep-audit-round6-2026-10-29.md
- simulator-deep-audit-round6-fixes-2026-10-29.md
- simulator-deep-audit-round7-2026-10-29.md
- simulator-deep-audit-round8-2026-10-29.md
- simulator-deep-audit-round12-2026-10-29.md
