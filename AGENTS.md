# SlayTheModel：交接说明

更新：2026-11-25，America/Los_Angeles（遗物核对范围更正与生成牌通知，DEVLOG 56；Fur Coat 核查与遗物复查 v30，DEVLOG 55；遗物结算时机与遗物栏顺序、Lord's Parasol v29，DEVLOG 54；通关奖励 1.6，DEVLOG 53；两层时间尺度优势、折扣按层数，DEVLOG 52；价值目标归一化，DEVLOG 51；输入归一化 FEATURE_VERSION 12，DEVLOG 50；学习率预热按步数、网络端复查，DEVLOG 49；整局冒烟测试、遗物上限 64 v28，DEVLOG 48；5090 第二轮日志与速度分析，DEVLOG 47；5090 第一轮结果、练习战、价值函数隐藏信息开关、固定种子评估，DEVLOG 38；第一轮日志 debug，DEVLOG 39；C++ 测试段错误、BF16 精度、诊断日志，DEVLOG 40；六敌人数组修复 v22，DEVLOG 41；随机数调用逐处对照 v23，DEVLOG 42；药水效果对照 v24，DEVLOG 43；铁甲卡牌与能力对照 v25，DEVLOG 44；无色/事件牌、回合时序、A2/A4 观察 v26，DEVLOG 45；其他职业牌、充能球观察、遗物时序 v27，DEVLOG 46）。本文件是接手的唯一入口：第 0 节先说清**已办、缺口、待办**，细节按指向去 [docs/DEVLOG.md](docs/DEVLOG.md)（按节号）、[docs/plan.md](docs/plan.md)（训练方案与已定参数）、[docs/observation-checklist.md](docs/observation-checklist.md)（观察设计）、[docs/content-audit.md](docs/content-audit.md)（规则核对记录）。源码与本文不一致时以源码为准，并更新本文。

## 0. 现状

### 0.1 目标与已定决策

**目标**：一个网络打《杀戮尖塔 2》整局（局外选择加每一手出牌），**铁甲战士、A10、单人、NoSL**（策略只用人能看到的信息），不搜索，从零开始纯 PPO。参照 AlphaDefect（v0.111.0、A10、1,000 个固定种子、EMA、取最大：储君 72.2%、静默 71.2%）。**第一个目标：铁甲 A10 在 1,000 个固定种子上超过 72%。**

**两项硬要求**（用户 2026-11-18）：
1. 模拟器可由人在命令行里直接操作——已完成（`python -m spire_rl.play_cli`，见 2.1）。
2. 用模拟器训练的 AI 能直接到带画面的原生客户端里玩——现在不实现，但每项设计都要保持这条路通（第 3 节“可部署”）；原生端还欠的工作见 0.3.3。

**已定决策**（用户 2026-11-18 / 19，详见 plan 第 6、6.2、7 节）：
- 一个网络打整局；**从零开始纯 PPO**；直接在 A10 上训练和评估；**MCTS 教师 / 战斗先验蒸馏路线放弃**（plan 第 7 节）。
- **网络**：宽 768、局外 12 层 + 战斗 12 层，实测 217.4M 参数（用户拍板，不再改小）。其他超参按比例（plan 第 6.2 节）。
- **奖励**：初始用 Zero-Search 数值——每层 +0.01、精英 +0.02、Boss +0.1、通关 +1、死亡 −0.1、血量势函数 0.1；**2026-11-24 起通关改为 +1.6**（配合每层折扣 0.99，DEVLOG 53）；全部是参数，**奖励项要能随时加**。
- **练习战**：40% 环境只打单场战斗（从整局存下的战斗开始快照读档、每次重新打乱隐藏随机）；输 −0.1，赢用战后状态的价值估计结算；抽样权重 Boss 6、精英 3、普通 1，再按最近死亡率和掉血加权。
- **防卡死 / 防循环**：敌人血量合计 20 个玩家回合没创新低判负、一回合内回到同一局面强制结束回合、一局最多 5,000 决策、判负记 −0.1；**这些规则属于 AI 驱动层**（训练和上线同一份代码），不改模拟器和游戏（DEVLOG 第 26 节）。
- **价值头**：标量；原三个 Boss 概率留作辅助输出。**价值函数看不看隐藏信息做成开关**，先用只看公开信息的版本。
- **观察**：做清单 A–E（F 暂不做）；**观察空间要能变**（`FEATURE_VERSION` 写入检查点，不符拒绝加载）；招式预测带概率；事件只给文字里写明的结果；卡牌稀有度保底计数可以给；**事件选项提示不做，另有人做**。
- **可用算力**：A100 约 3 天有效训练时间（也能用 H100）；217M 在 A100 上估计每秒 300–500 决策（未实测）。**用户 2026-11-20 定：先上 5090（2.2 节）测速和跑第一段，再去 A100。**

### 0.2 已办

**模拟器 `sim/`（ruleset `native-41cef1ea-port-v30`，快照 v20）**——全部是对照原生源码移植并自测，**不是原生 DLL 执行对拍**（例外见“原生对照”）：
- 随机数机制与各随机流种子（DEVLOG 6）；怪物生成、血量、阵容、招式状态机、招式效果、敌人顺序、召唤位置（v9，DEVLOG 7–9）；Boss / 精英特殊机制（v10，DEVLOG 10）；怪物机制与回合触发全部钩子、怪物施加的 68 种能力（v17，DEVLOG 21）。
- 基础注册（v13）：卡牌、遗物、药水、事件、先古、怪物、遭遇的身份和静态属性与真实 DLL 导出一致，C++ 整数 ID 由 `registry_identity_lock.json` 锁定（DEVLOG 13，`docs/registry-audit.md`）。
- 全怪物数值（v14）：107 个怪物在 A0/7/8/9/10 的血量、伤害、次数与 DLL 3,215 次比较 0 未解释差异（DEVLOG 14，`docs/monster-number-audit.md`）。
- 局内概率与生成（v15）：问号房、各类奖励、遭遇与事件抽取、商店、宝箱、地图、A1–A10 局外效果；默认全解锁进度（DEVLOG 18）。
- 事件：57 个出现条件、全部选项效果（v16、v18，DEVLOG 19、22）。
- 铁甲可得 265 件遗物逐件核对，修正 19 件（v19，DEVLOG 23）。
- v30：铁甲可得 265 件遗物按“原生钩子 ↔ 模拟器位置”复查（只是时机层面；逐行核对效果的约 45 件，DEVLOG 56）；修 Tea of Discourtesy（Dazed 随机插入而非置顶）、Fur Coat 目标，以及 5 件遗物加牌时缺的生成牌通知（Radiant Pearl、Vexing Puzzlebox、Music Box、Burning Sticks、Biiig Hug）；Fur Coat 只比坐标、后续幕坐标重合（偶尔第三幕 Boss）也变 1 血是原生行为，保留（DEVLOG 55、56）。
- v29：遗物按原生时机与遗物栏顺序结算——玩家回合开始拆成原生各阶段（Blood Vial、Mr Struggles、Festive Popper、Royal Poison、Brimstone、Sai、Lantern 等能量遗物移到正确阶段），出牌后 / 消耗后 / 回合结束前按遗物栏顺序且出牌后遗物排在玩家能力之后；Bag of Marbles 等只打可命中敌人、Twisted Funnel 受 Artifact 阻挡；Lord's Parasol 逐件等待每件遗物的选择和奖励界面，The Courier 每次购买都判断（DEVLOG 54）。
- v28：遗物上限 32 → 64（原生无上限；32 件时给遗物的事件选项全被禁用，曾出现非终局无动作）；整局冒烟测试 8,000 局塞遗物 + 4,500 局训练分布（DEVLOG 48）。
- v27：静默、故障机器人、储君、亡灵法师的牌和能力对照，补上 Pounce / Synthesis 免费、七张储君牌缺失的钩子、变形与生成的区分、两处 4 格敌人数组；遗物时序修正（Unceasing Top、Ghost Seed、Mercury Hourglass、History Course、Gremlin Horn、Intimidating Helmet、Pen Nib）（DEVLOG 46）。
- v26：无色、事件、状态、诅咒牌对照；回合开始 / 结束时序按原生重排；Entropy、Neow's Fury 恢复玩家选择；修正 Rebound、Bolas、Fasten、Omnislice、Constrict 等（DEVLOG 45）。
- v25：铁甲 90 张牌和相关能力逐个对照，修正群攻目标、Armaments、Pillage、Juggling、Free Attack、Corruption 费用顺序（DEVLOG 44）。
- v24：药水效果逐个对照，修正 Touch of Insanity 可选牌、Blessing of the Forge、Soldier's Stew、范围药水目标和药水后钩子（DEVLOG 43）。
- v23：逐处对照原生随机数调用：战斗生成牌的卡池、原生顺序和消耗次数，洗牌排序，Stampede / Beat Down / 塞入抽牌堆的流；修正 Infernal Blade、Calamity、Aggression、Bottled Potential、Jeweled Mask 的规则错误（DEVLOG 42）。
- v22：Oblivion、Strangle、Regent 命中计数的每敌人数组从 4 格改为 6 格。原来第 6 个敌人会把任意职业的攻击伤害读成 Oblivion 并加 Doom（DEVLOG 40、41）。
- v21：Fake Merchant 离开直接回地图（原生没有结束页），去掉一个多余决策和导出报错（DEVLOG 36）。
- v20：Perfected Strike 打出时计入自己；**玩家和怪物的伤害修正改用精确十进制**（原来 double/float 在少数乘数组合下少 1）；Unmovable 按原生“获得格挡记录”计数（DEVLOG 30）。
- 卡牌身份与编码：596 个模型、1,148 个变体，模拟器导出与原生格式逐位相同（DEVLOG 20）。

**原生对照 `parity/`**：无界面宿主能启动真实 DLL 并导出公开状态。最强实测证据：种子 `PARITY0001`（A10 铁甲）从 Neow 到首战、领奖、回地图的 **31 个动作 / 32 个决策点**，完整公开事实、网络输入张量、合法动作集合逐步一致（DEVLOG 11–12，固定样例 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/`）。此后新增的观察字段在这份旧录制上以 `legacy_capture=True` 回放（两边都去掉、报告标“未覆盖”）。

**公开观察 `spire.public/1`（`FEATURE_VERSION=12`，所有输入有界 ≤ 6，DEVLOG 50）**：原生和模拟器各自导出公开事实，经同一个 `train/spire_rl/public_obs.py` 编码，同一网络、同一候选语义；原生 actionId / C++ UID 只用于执行。真实选择全部保留（DEVLOG 12）。观察清单 **A–E 已全部完成**（DEVLOG 27–34）：

| 项 | 内容 | 实现 | 主要验证 |
| --- | --- | --- | --- |
| E | 牌组摘要 | `public_derived.py` | 起始牌组数值、随机整局有界 |
| C | 抽牌概率（1/2/5 张内抽到各类牌） | `public_derived.py` | 与枚举全部隐藏顺序的精确值相等 |
| A5 | 地图路线摘要 | `public_derived.py` | 手算小地图 |
| D | 本幕已遇遭遇、下一场概率 | C++ 导出历史 + `public_derived.py` | 40 局里每场实际遭遇都在预测内 |
| A1 | 加成后的牌面伤害/格挡（含对每个敌人） | C++ `card_preview.cpp` | 按原生公式手算 58 项 + 用户指定 3 组 144+ 项；随机对局 4,821 次伤害、3,860 次格挡与实际出牌一致 |
| A3 | 每个敌人这回合最多打多少、能否打死 | `public_tactics.py` | 与枚举出牌组合最优解相等 |
| A4 | 现在结束回合掉多少血（含回合末效果、Osty、减伤遗物） | `public_tactics.py` | 2,003 个局面与实际结束回合一致 |
| B | 每个出牌的效果预览：我方一侧（能量、格挡、自伤、重放、遗物/能力触发、出牌后手牌）精确或标未知；对敌伤害不含敌人自身防御与反应（DEVLOG 35） | `public_tactics.py` | 全量对照（`train/scripts/audit_action_preview.py`）：标“已知”的 43,206 次出牌、8,965 次出牌后结束回合全部与模拟器一致（DEVLOG 37） |
| A2 | 怪物当前招式 + 后两步概率 | C++ `predict_monster_moves` | 13,131 次实际出招全在候选内，频率与概率吻合 |
| A6 | 选牌用途与来源（40 种用途） | C++ 导出 + `PURPOSES` | C++/Python 词表锁定一致 |
| 充能球 | 队列里的球、当前被动值和激发值、槽位数；A4 计入回合末被动（DEVLOG 46） | C++ 导出 + `public_tactics.py` | 带 Cold Snap 等牌的预览审计 0 差异 |

另外：公开状态补上了 Osty（死灵召唤物，替玩家挡攻击伤害）的血量和充能球（DEVLOG 46）；每张牌打几下的表 `cardHits` 从原生出牌代码解析生成。每个决策：公开状态约 0.5 毫秒、编码约 0.5 毫秒、平均约 103 个实体。所有新观察都通过“只改隐藏随机、观察逐位不变”的 NoSL 检查。

**工具**：人用命令行 `play_cli.py`（撤销、存读档、只显示公开信息，DEVLOG 17）；公共接口提速到每决策约 0.77 毫秒（DEVLOG 16，之后加了 A–E 仍约 1 毫秒）。

**训练框架第一版（2026-11-20，DEVLOG 37）——已可开训（最小完整版：整局 PPO、限时退出、续训）**：
- `spire_rl/driver.py`：AI 驱动层，只读 `PublicState` 与自身公开历史，训练与原生客户端共用。同一作用域内同一网络输入第三次出现时去掉已走过的候选；战斗中同一回合重复出现的决策只允许结束回合；敌人血量合计 20 个玩家回合没创新低、或一局超过 5,000 决策判负；只有一个可选候选时直接执行，不进网络。
- `spire_rl/rewards.py`：每项奖励一个函数一个权重（0.1 节的数值），`--reward` 可覆盖。
- `spire_rl/rollout.py`：多进程采样（每进程若干局同步推进），网络输入约 98% 为零，传输与存储用稀疏格式（每样本约十几 KB）；单局异常写进日志并换新局，不中断训练。
- `spire_rl/ppo.py`：同步整局 PPO（超参见 plan 6.2）、CUDA 上 BF16、EMA（2 小时时间常数）、`latest.pt` + `ema.pt` 两份原子覆盖保存、`--hours` 到时或 Ctrl-C 在当前更新后保存退出、同一 `--run` 再运行即续训、`--bench` 测速。
- **网络**（`net.py`，2026-11-16 写好，本次只加了标量价值头）：每个“东西”（牌组里的牌、遗物、药水、地图点、手牌、各牌堆的牌、敌人、能力……）是一个实体向量 = 类型 + 身份 + 数值特征；地图点沿路线先传一轮信息；局外实体过 12 层 Transformer 编码器；战斗实体过 12 层 Transformer 解码器（自注意 + 交叉注意局外）；注意力汇总后与全局行（血量、金币等）、玩家行拼成局面向量。策略头给每个合法候选打分（动作类型 + 候选数值特征含 B 预览 + 它指向的实体向量 + 局面向量），驱动层不允许的候选屏蔽后做 softmax；价值头输出一个标量；原三个 Boss 概率保留为辅助输出（暂不训练）。局外与战斗同一个网络。
- 217M 已在 5090 上实跑 10 小时（下一条）。

**5090 第一轮（2026-11-21，日志 `runs/5090-train1-10h/log.jsonl`，DEVLOG 38）**：217M、61 次更新、400 万决策、50,932 局；平均层数 3.4 → 约 12，最后 11 次更新约 1% 的局到第二幕，0 通关；实际约 40 万决策/小时，69% 时间在网络更新。这轮**没有**练习战，也没做过固定种子评估。

**5090 第二轮（2026-11-24，日志 `runs/5090-train2/log.jsonl`，DEVLOG 47）**：v27 代码、有练习战，17 小时只做了 **20 次更新**、131 万决策。按每次更新算学得和第一轮一样（更新 20 时平均 7.2 层，第一轮 7.0；价值解释方差升到 0.56；0 异常）。问题是速度：网络更新每次从第一轮的约 7 分钟变成 19 分钟，并涨到约 70 分钟、忽快忽慢；GPU 实际算力只有 2 TFLOPS 量级。较强怀疑是显存溢出到系统内存（Windows/WSL 默认不报 OOM），未确认；已确认补齐浪费约 42%（已改为按大小分组）。另外 `--warmup 20` 按更新次数算，这一轮整轮都在学习率预热里。检查点已在训练机上删除（用户每轮从零开始）。

**训练框架补完（2026-11-22，DEVLOG 38，只在本机 CPU 小网络验证，未上 GPU）**：
- 练习战（`--practice`，默认 0.4）：存“进战斗前一刻”的状态，读档后只换战斗随机流、走原本的开战流程，所以起手牌、怪物血量、意图都重新随机；不用旧的 `resample_hidden`（它不换起手牌，还会打乱公开的弃牌堆）。
- 价值函数看隐藏信息（`--value-hidden`，默认关）：第一版只看抽牌堆顶 10 张的顺序，策略读不到。
- 评估：`python -m spire_rl.evaluate --checkpoint <ema.pt>`，1,000 个固定种子、取最大、Wilson 95% 区间。

**测试现状**：C++ 64/64、训练 Python 104 通过 + 1 跳过（需 CUDA 的 BF16 测试）、parity 93 项 + 109 子项；注册表、怪物数值、卡牌编码三项审计通过；63 个 C++ 测试程序在本机 clang 的 AddressSanitizer + UBSan 下干净（训练机 g++ 未复测）。

**尚未提交（v30）**：DEVLOG 38–56 的改动（含 `sim/bindings/bindings.cpp` 新增接口）和本文件都只在工作区；最新提交是 `973fc0b`（BF16 地图消息修复）。按约定由用户自行提交；`sim/` 变了，发布时要同步 `v111_simulator`。

### 0.3 缺口

#### 0.3.1 模拟器规则（已知、未修，均为源码对照所见）
- 遗物：**约 220 件铁甲可得遗物的效果细节尚未逐行重核**（只核了时机；v19 的核对漏过几类问题，清单见 DEVLOG 56 末尾，下一步先做战斗内的）。v29 已修同一时机的遗物顺序（会影响结果的时机：回合开始各阶段、出牌后、消耗后、回合结束前）和 Lord's Parasol（DEVLOG 54）。仍未做：受到伤害后 / 洗牌后 / 使用药水后 / 开战三段没拆（核对过顺序不影响结果）；Self-Forming Clay 在原生是一个能力，模拟器用遗物计数表示（时机已对，观察里显示方式不同）；其他职业的 32 件遗物未实现（铁甲拿不到；以后重放静默 / 储君对局前必须实现，DEVLOG 55）。
- 四个其他职业的牌和能力已逐张读过一遍并修正（DEVLOG 46），但回归测试只覆盖修过的点，没有逐张执行对照。药水已在 DEVLOG 43 对照；其他职业专属药水在模拟器里没有效果，铁甲拿不到。
- 其他小项：卡牌奖励某稀有度抽空时的回退顺序与原生不同（铁甲池碰不到）；第一局教学固定顺序未建模（默认进度不触发）。

#### 0.3.2 观察（按设计的边界或未做）
- 事件选项提示里的物品：不做，另有人做。
- 遗物的“本场是否已触发”等额外状态未导出（已有状态/计数/蜡封/熔化）。
- A3 不考虑出牌顺序和抽牌；A4 不含敌人回合中一个敌人给另一个加力量这类中途变化，也不含下回合开始时的掉血（Inferno、中毒、Crimson Mantle）。
- B 口径（DEVLOG 35）：我方一侧精确，算不准标未知；对敌伤害**不含敌人自身的防御与反应**（滑溜、Skittish 等，留给网络学）；会反击或改变敌人本回合行动的敌方能力被打到、改变敌人本回合的牌（上虚弱、减力量）、抽牌/加牌而回合结束受手牌影响时，“出牌后结束回合掉血”标未知；只对复核过源码的卡池（铁甲、无色、事件、诅咒、状态、衍生）给数。
- 其他职业的“按局面计算”的牌（Prismatic Gem 等才会出现）预览标未知；出牌时才决定打几下的牌（Fiend Fire 等）标未知。
- A2 的条件分支按当前战场判断；被眩晕 / 复活中的敌人只给参考。
- 充能球已进公开观察（DEVLOG 46）。A4 按队列结算 Frost、Lightning、Glass 的回合末被动；Hailstorm、Consuming Shadow 和双触发的 Glass 标未知。

#### 0.3.3 原生端欠账（上线原生客户端前必须补；在模拟器里训练不受影响）
1. 已写好但**未编译、未实跑**的宿主 C# 导出：本幕遭遇（D）、牌面显示值（A1）、Osty 血量、充能球。这台 Mac（`~/Workspace/SlayTheModel`）没有游戏备份，需在有游戏的机器上编译。
2. **A2 招式预测的原生端未写**：宿主要读原生 MoveStateMachine，按同样规则推算。
3. **A6 选牌用途映射未写**：原生选牌界面 → `PURPOSES` / `service`。
4. 补完后录一段新的原生记录，用完整对照（非 legacy）核对所有新字段。现在的 `from_native` 缺这些字段会直接报错，不会默默补零。

#### 0.3.4 验证覆盖
- 整局原生对照没有做；真实战斗执行证据只有上面那一局的开头 31 步。
- 整局冒烟测试已做（DEVLOG 48，`train/scripts/smoke_full_runs.py`）：塞遗物与牌、从三幕分别开局 8,000 局 1 个失败（Lord's Parasol 类排队，见 0.3.1），训练分布 4,500 局 0 失败；第二、三幕的 D 预测在 Hive / Glory 上逐场核对通过。这是“不崩、自洽”，不是和原生一致。
- v23–v29 的随机数、药水、卡牌和遗物修复都是读反编译源码加定点回归测试，没有逐张牌在真实 DLL 上执行对拍。

#### 0.3.5 训练框架（2026-11-23 复查）
- 练习战、隐藏信息开关、评估脚本**只在本机 CPU 小网络验证**，未在 GPU / 217M 上运行，BF16 下的隐藏价值分支也未实跑。
- 价值函数“隐藏信息”第一版只看抽牌堆顶 10 张，是否做成更强的全知版本等网络架构讨论后由用户定；效果未验证，默认关闭。
- 第一轮日志里的 1 局异常 `Finished card identity capacity`：v27 起这张表只记 Fetch，不会再由普通出牌触发（DEVLOG 46）。那局为什么一回合出现 160 张以上不同的牌**仍未查清**（DEVLOG 39）；新日志的异常会带种子，再出现可重放。
- `native_step3_events` 的 `-11`：本机确认是测试程序栈不够，`sim/build.py` 已提高测试栈（DEVLOG 40），**训练机 g++ 未复测**。
- 第二轮更新变慢（DEVLOG 47）：显存溢出是较强怀疑、未确认；按大小分组小批、`--micro-tokens` 已做但未在 GPU 上测；学习率预热已改为按优化器步数（`--warmup-steps 100`，约 3 次更新，DEVLOG 49）。
- 网络端复查（DEVLOG 49），**都要新开一轮才能改**（改编码或价值头含义，第二轮检查点不能续训）：① 输入归一化**已做**（DEVLOG 50，FEATURE_VERSION 12）；② 价值目标归一化**已做**（DEVLOG 51；实测价值梯度原来只有策略的约 1/1000，归一化后约 1/40）；③ 两层时间尺度优势（战斗内 GAE + 局外半马尔可夫 GAE）、折扣按层数 0.99、分组标准化**已做**（DEVLOG 52，`--credit flat` 保留旧做法）。都未在 GPU 上跑过；第三轮的学习效果要和旧做法对照。
- 第一轮日志 debug（DEVLOG 39）：已修 32 样本小批误触发 KL 早停；下一轮用 `--ent-updates 450`。解释方差、死亡层数、分段耗时已加入日志（DEVLOG 40）。

### 0.4 待办（按顺序）
1. **（用户）同步代码到训练机并重新编译模拟器**（v28–v30 改了 `sim/`）：`CXX=g++ python sim/build.py --test`，应看到 `native-41cef1ea-port-v30`。用户每轮都从零开始、旧权重直接删，不续训。提交时 v27–v30 一起提交；发布时同步 `v111_simulator`。
2. **（用户）在 5090 上先测速（5–15 分钟），确认是不是显存溢出**（见 2.2 第三轮操作手册第 2 步）：用新的空目录跑 `--bench --bench-micro 64,128,256`（第二轮权重已删；新网络打得浅、局面小，所以测速只能看出明显溢出，真实训练中随牌组变大的显存要看新日志的 `gpu_memory_gib`）。如果 micro 64 每样本明显比 256 快，或 Windows 任务管理器里“共享 GPU 内存”在涨，就是溢出，正式训练改用不溢出的最大 micro，或保留 micro 256 加 `--micro-tokens`（每块“行数 × 实体数”上限，长样本自动少放几行，DEVLOG 48）；也可以在 NVIDIA 控制面板把 CUDA Sysmem Fallback Policy 设成 Prefer No Sysmem Fallback，让溢出直接报错而不是悄悄变慢。
3. **从零跑第三轮**（用户启动，新目录 `runs/5090-train3`；v30、FEATURE_VERSION 12、按步数预热、价值归一化、两层优势、通关 1.6 都已在代码里）：按 2.2“第三轮操作手册”走。重点看每次更新的 `learn_s` 能否回到第一轮约 10 分钟以内，以及 `value_ev_macro` 是否上升。
4. **剩余约 220 件遗物逐行核对**（DEVLOG 56 末尾的清单），先战斗内。
5. 原生端欠账（0.3.3），在上线原生客户端之前完成。
6. 原生对照扩大：奖励、商店、遗物选牌、药水、复活场景；用户计划提供几十局 AlphaDefect 静默/储君对局记录，到时在模拟器里重放核对。

### 0.5 等外部
- 同学对怪物部分的原生对比核查结果：收到后先按原生源码确认，再改 C++、跑测试、记 DEVLOG、必要时升 ruleset。
- AlphaDefect 对局记录（用户提供）。

## 1. 目录

| 路径 | 内容 | git |
| --- | --- | --- |
| `sim/` | C++ 模拟器：`src/`、`include/`、`bindings/`（Python 扩展 `sts2_sim`）、`content/`（生成的数据表）、`tools/`（生成器；`apply_native_monsters.py` 更新怪物血量和阵容，`native_monster_ai.py` / `apply_native_ai.py` 核对与套用 AI，`apply_native_neow.py` 追加原生 Neow 内容）、`tests/`（C++ 测试程序）、`native-fixtures/`（测试读的原生样例）、`build.py`、`PORT_SOURCE.json`（身份）、vendored `pybind11/`、`json/` | 跟踪；`sim/build/` 忽略 |
| `train/` | Python 包 `spire_rl`（`pip install -e train`）：`sim.py`（加载扩展）、`public_obs.py`（公开状态与编码，`spire.public/1`）、`public_derived.py`（C/D/E/A5）、`public_tactics.py`（A3/A4/B）、`public_catalog.json`（生成的公开词表、遭遇池、打击次数）、`net.py`（网络，旧 `obs.py` 布局仍可用）、`play_cli.py`；训练：`driver.py`（AI 驱动层）、`rewards.py`、`rollout.py`、`ppo.py`（`python -m spire_rl.ppo`）、`evaluate.py`；`tests/`；`scripts/bench_throughput.py` | 跟踪 |
| `parity/` | 原生无界面宿主（真实 DLL + Godot 无界面）：`host-src/`、`stage.py`、`run_host.sh`；语义适配 `semantic.py` / `action_contract.py`、逐步诊断 `compare.py`（默认完整公共模型输入）、`tests/` | 跟踪；`stage/` 忽略 |
| `docs/` | `DEVLOG.md`、`plan.md`、`observation-checklist.md`、`content-audit.md`、`registry-audit.md/json`、`monster-number-audit.md/json`、`card-encoding-audit.json` | 跟踪 |
| `artifacts/native-source/v0.111.0/` | 原生反编译源码（3,537 个 `.cs`），对齐规则用 | 忽略，只在本机 |
| `artifacts/preserved-game-versions/` | 原版游戏 v0.111.0 安装备份，**不可删除** | 忽略，只在本机 |
| `artifacts/tools/` | .NET SDK 9.0.321、ilspycmd（原生宿主和反编译用） | 忽略，只在本机 |
| `artifacts/reference/alphadefect-evaluation-overview/` | AlphaDefect 评估摘录（文档、5 次评估汇总、5 局记录） | 忽略，只在本机 |
| `runs/` | 训练输出（建议路径） | 忽略 |

## 2. 命令

### 2.1 Mac（4 核、8 GB）

项目由用户和同学在不同 Mac 上推进，路径和 Python 不一定相同，先核实再用。2026-11-18 晚核实：仓库在 `~/Workspace/SlayTheModel` 的那台 Mac 上 **没有** `/opt/anaconda3`，可用的是 `~/micromamba/envs/sts2/bin/python`（3.11，含 numpy、torch、pytest，与现有扩展同为 3.11 ABI）；另一台记录的是 `/opt/anaconda3/bin/python3.11`、仓库 `~/SlayTheModel`。两者都要按下面临时设三个环境变量（torch 有 OpenMP 冲突，单线程）。内存小，大任务先量内存，别并行开太多。`~/Workspace/SlayTheModel` 这台的 `artifacts/preserved-game-versions/` 是空的（2026-11-19 核实）：**原生宿主在这台既不能编译也不能运行**，原生端工作要到有游戏的机器上做。

默认 Xcode 入口需要接受许可（不要代用户接受），用 Command Line Tools 的包装脚本：

```sh
cat > /tmp/clangxx <<'EOF'
#!/bin/sh
exec /Library/Developer/CommandLineTools/usr/bin/clang++ -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -isystem /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1 "$@"
EOF
chmod +x /tmp/clangxx
PY=$( [ -x /opt/anaconda3/bin/python3.11 ] && echo /opt/anaconda3/bin/python3.11 || echo ~/micromamba/envs/sts2/bin/python )
DEVELOPER_DIR=/Library/Developer/CommandLineTools CXX=/tmp/clangxx $PY sim/build.py --test --jobs 2   # 编译并跑全部 C++ 测试
cd train && KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
cd .. && KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 PYTHONPATH=.:train $PY -m pytest -q -p no:cacheprovider parity/tests
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train $PY -m spire_rl.play_cli --seed MYSEED --ascension 10   # 人手动玩模拟器；输入 help 看命令
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train $PY -m parity.card_encoding_audit --out docs/card-encoding-audit.json   # 卡牌身份/编码与原生一致性
```

### 2.2 训练机（Windows `LegionB` + WSL2）

RTX 5090、WSL 里 8 个线程，**这就是全部配置，不要再问**。Conda `slay`（Python 3.12），仓库 `/mnt/c/Users/yebohou/SlayTheModel`。

第一次在这台机器上配置时还要执行一次 `pip install -e train`（装 `spire_rl` 和共享的 `parity` 包）；之后每次只需按下面手册第 1 步编译和测试。

该机 CPU 不支持 BF16 反向（训练在 GPU 上用 BF16，不受影响）；GPU 只能在用户工作时间挂着用，训练要按工作日分段、到点正常退出、可以接续；不要多存检查点（硬盘小）。**按约定实验由用户启动和停止。**

#### 第三轮操作手册（2026-11-24 起；给在训练机上跑训练的人）

第三轮和第二轮相比改了很多：模拟器 v30（遗物上限、遗物结算顺序与复查）、所有网络输入有界、按步数预热、价值目标归一化、两层时间尺度的优势、通关奖励 1.6（DEVLOG 47–53）。**从零开始，不读任何旧权重**；`runs/` 下旧的检查点可以全部删掉（硬盘小）。按约定由用户启动和停止。

**第 1 步：拉代码、编译、跑测试（约 10 分钟）**

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
git pull                                     # 或用户指定的同步方式；DEVLOG 38–53 的改动要先由用户提交推送
CXX=g++ python sim/build.py --test           # 最后一行应是 64/64 test programs passed
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"      # 必须是 native-41cef1ea-port-v30
python -c "from spire_rl import public_obs; print(public_obs.FEATURE_VERSION)"  # 必须是 12
python -m pytest -q train/tests              # 应为 105 passed（含 1 个只在有 GPU 时才跑的 BF16 测试）
```

- C++ 测试 `native_step3_events` 如果报 `FAILED (-11)`：是测试程序栈不够（DEVLOG 40），记下输出发回来，不影响训练，可以继续。其他失败先停下，把输出发回来。

**第 2 步：测速，确认显存会不会溢出（5–15 分钟）**

```sh
python -m spire_rl.ppo --run runs/bench-micro --bench --workers 6 --games 16 --bench-micro 64,128,256
```

- 它先采样 1 分钟，再对 micro = 64 / 128 / 256 各测一次训练速度（`random` 是旧的随机分组，`sorted` 是按实体数分组，正式训练用 sorted）。每行有“samples/s per epoch”、`peak reserved`（显存峰值）和 `free after`（剩余显存）。只测速，不写检查点。
- 同时开着 Windows 任务管理器 → 性能 → GPU，看“共享 GPU 内存”。
- **怎么选 `--micro`**：取 sorted 一行里每秒样本数最高、且 `peak reserved` 明显低于 32 GiB（留 3 GiB 以上）的那个。如果 micro 256 比 128 反而慢，或共享 GPU 内存在涨，就是显存溢出到了系统内存（第二轮变慢的头号怀疑，DEVLOG 47）。
- 新网络打得浅、局面小，测速时的显存比后期训练小。所以第 3 步开训后还要盯日志里的 `gpu_memory_gib`。
- 可选：NVIDIA 控制面板 → 管理 3D 设置 → “CUDA - Sysmem Fallback Policy” 设为 “Prefer No Sysmem Fallback”。这样显存不够会直接报错（OOM），不会悄悄变慢。

**第 3 步：开第三轮**

```sh
python -m spire_rl.ppo --run runs/5090-train3 --hours 8 --workers 6 --games 16 --ent-updates 450 --micro 256
tail -f runs/5090-train3/log.jsonl
```

- `--micro` 按第 2 步的结果改。如果后期 `gpu_memory_gib.peak_reserved` 逼近 30，加 `--micro-tokens 30000`（每个小块“行数 × 实体数”的上限，长局面自动少放几行），或把 `--micro` 降一档。这些只影响速度和显存，不影响训练结果。
- `--hours 8` 到点后，在当前这次更新做完时保存并退出。**第二天用完全相同的命令再运行，会从 `runs/5090-train3` 接着跑**（同一轮之内的接续，和“不续训旧轮”不矛盾）。提前要停就按一次 Ctrl-C，等它把当前更新做完、保存后自己退出（可能要等十几分钟），不要连按、不要直接关窗口。
- 盘上只保留 `latest.pt`（约 3.5 GB，含优化器）和 `ema.pt` 两份，每 30 分钟和退出时覆盖保存。
- 第三轮的默认设置都已写进代码，命令里不用再加：每层折扣 0.99、战斗内 λ 0.95、局外 λ 每层 0.9、通关奖励 1.6、预热 100 步、价值归一化、练习战 40%。

**第 4 步：看日志**（`log.jsonl` 每次更新一行，健康范围是按前两轮的数据估的，供参考）

| 字段 | 含义 | 健康 / 要报告的情况 |
| --- | --- | --- |
| `learn_s`、`collect_s` | 这次更新里训练、采样各花几秒 | 第一轮训练约 420 秒；第二轮从 1,145 涨到 4,200 秒就是不正常。**训练时间一路上涨或忽快忽慢 → 报告** |
| `timing_s` | 分段耗时（模拟器、拼批、网络、优化器） | `learn_network` 占大头正常 |
| `gpu_memory_gib` | 显存：`peak_reserved` 峰值、`free_after` 剩余、`total` 总量 | `peak_reserved` 超过约 30 → 按第 3 步调 `--micro` / `--micro-tokens` |
| `learn_tokens` | 补齐浪费（`padded_over_real`）、每行平均和最大实体数 | 分组后应接近 1.05；每行实体数随牌组变大会慢慢涨 |
| `decisions_per_s` | 采样速度 | 前两轮约 300–500 |
| `floor_mean`、`death_floors`、`act_reached`、`win_rate` | 整局的平均层数、死在哪层、到第二/三幕的局数、胜率 | 应该随更新慢慢涨；前两轮 20 次更新约到 7 层 |
| `fights`、`deaths_by_encounter` | 进入/赢下的普通、精英、Boss 场数，最常死在哪些遭遇 | 看卡在哪 |
| `practice` | 练习战各类场数和胜率 | 精英、Boss 胜率前期很低是正常的 |
| `reasons` | 整局怎么结束的：`died` 死亡、`won` 通关、`stall` 20 回合敌人没掉血判负、`cap` 超过 5,000 决策、`no_actions` 没有可选动作、`error` 异常 | 除 `died`、`won` 外的都应接近 0；**出现 `no_actions` 或 `error` → 把 `errors` 里的行（带种子）发回来** |
| `errors`、`practice_errors` | 异常信息，带种子、层数、遭遇 | 应为空 |
| `kl`、`kl_max`、`kl_stop`、`kl_stop_at` | 每次更新策略变了多少 | `kl` 通常 0.002–0.01；`kl_stop` 经常为 true → 报告 |
| `entropy` | 策略的随机程度 | 从约 1.6 慢慢下降；突然掉到 0.3 以下 → 报告 |
| `lr`、`optimizer_steps_total` | 当前学习率、累计优化步数 | 前 100 步从 3e-7 升到 3e-5，之后恒为 3e-5 |
| `value_ev`、`value_ev_combat`、`value_ev_macro` | 价值函数解释回报的比例（总体 / 战斗决策 / 局外决策；1 = 完美，0 = 等于没学） | 前十几次更新应升到 0 以上；`value_ev_macro` 一直在 0 附近 → 报告（这是“会打不会选牌”的信号，DEVLOG 52） |
| `value_norm` | 价值归一化用的回报均值和标准差 | 标准差前期约 0.03，会随打得更远变大 |
| `macro_share` | 局外决策占样本比例 | 约 0.1–0.2 |
| `value_loss` | 价值损失（归一化单位） | 和第一、二轮的数不可比 |

**第 5 步：评估（一轮结束或想看成绩时）**

```sh
python -m spire_rl.evaluate --checkpoint runs/5090-train3/ema.pt --workers 6
```

1,000 个固定种子、每步取概率最大的动作，打印胜率（含 95% 区间）、到第二 / 三幕的局数、平均层数、结束原因、按遭遇编号统计的死亡数；逐种子结果写在 `ema.pt` 旁边的 JSON。训练日志里的胜率是边探索边打的成绩，评估的数才是对外比较用的（目标：超过 AlphaDefect 的 72%）。

**第 6 步：发回来的东西**

- 第 2 步测速的完整输出，以及任务管理器里共享 GPU 内存有没有涨。
- `runs/5090-train3/log.jsonl`。
- 第 1 步如果有失败，失败的输出；训练中如果崩溃，终端最后几十行。
- 做了评估的话，评估打印的那段 JSON。

#### 训练参数速查（`python -m spire_rl.ppo --help` 有完整列表）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--run` | 必填 | 运行目录（日志、检查点）。换网络大小或观察版本必须换新目录 |
| `--hours` | 0 | **本次启动**跑多久后，在当前更新结束时保存退出（0 = 不限）；第二天再启动重新计时 |
| `--workers` / `--games` | CPU 数 − 2 / 32 | 采样进程数 / 每个进程同时开几局。训练机用 6 / 16 |
| `--micro` | 256 | 训练时一次前向的行数。只影响显存和速度 |
| `--micro-tokens` | 0（关） | 每块“行数 × 实体数”上限，后期局面变大时防止显存溢出 |
| `--infer-batch` | 512 | 采样时一次前向的最大行数 |
| `--ent-updates` | 3000 | 熵系数从 0.01 降到 0.001 用多少次更新。训练机用 450 |
| `--warmup-steps` | 100 | 学习率预热的优化器步数（约 3 次更新） |
| `--credit` | two-level | 优势计算方式；`flat` = 第一、二轮的旧做法，只在做对照时用 |
| `--gamma-floor` / `--lam-combat` / `--lam-macro` | 0.99 / 0.95 / 0.9 | 每层折扣 / 战斗内 λ / 局外每层 λ |
| `--reward` | 见 `rewards.py` | 改奖励权重，如 `'{"win": 1.0}'` |
| `--practice` | 0.4 | 练习战占的局数比例 |
| `--no-value-norm` | — | 关掉价值归一化（只做对照时用） |
| `--value-hidden` | 关 | 价值函数看抽牌堆顶 10 张（只训练时用，默认关） |
| `--bench`、`--bench-micro` | — | 只测速，不训练 |

#### 其他

- 每个决策 CPU 约 1.6 毫秒，6 个进程采样上限约每秒三千多决策；217M 的瓶颈在 GPU。
- 该机 CPU 不支持 BF16 反向（训练在 GPU 上用 BF16，不受影响）；GPU 只能在用户工作时间挂着用，所以按工作日分段、到点退出、第二天接着跑。

### 2.3 A100 / H100（Linux，训练框架 `spire_rl.ppo`，DEVLOG 37）

训练设置、日志字段、参数含义与 2.2“第三轮操作手册”相同；下面只列 Linux 上不同的命令（`--workers` 按核数取）。

```sh
CXX=g++ python sim/build.py --test --jobs 8            # 编译模拟器扩展并跑 C++ 测试（64/64）
pip install -e train                                   # spire_rl + parity；torch 需带 CUDA
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"   # native-41cef1ea-port-v30
python -m pytest -q train/tests                        # 约 4 分钟
# 1) 先测速（约 2 分钟）：采样决策/秒、更新速度、每小时决策数、显存峰值
python -m spire_rl.ppo --run runs/bench --bench --workers $(( $(nproc) - 2 )) --games 32
# 2) 训练：217M 默认配置；到 --hours 正常退出，同一 --run 再执行即续训
python -m spire_rl.ppo --run runs/a100-1 --hours 10 --workers $(( $(nproc) - 2 )) --games 32
tail -f runs/a100-1/log.jsonl                          # 每次更新一行：决策/秒、平均层数、胜率、结束原因、KL、熵
```

- 显存不够：减小 `--micro`（训练每次前向的行数，默认 256）和 `--infer-batch`（采样时前向的行数，默认 512）；不影响训练语义。
- 采样慢于 GPU：加 `--workers`（每个约占一个 CPU 核，内存约 0.3 GB）；`--games` 是每个进程同时开的局数。
- 中途 Ctrl-C / SIGTERM：当前更新做完后保存再退出。`latest.pt`（含优化器）与 `ema.pt` 每 30 分钟和退出时覆盖保存，只这两份。
- 换网络大小或观察版本必须换新的 `--run`，旧检查点会被拒绝。

## 3. 用户约定（必须遵守）

- **不提交、推送、合并**，除非用户明确要求；目前由用户自行操作，需要时给命令和说明。完整工作分支为 `v111_SF2`，旧版本在 `v111_SF1`；`v111_simulator` 只保存模拟器子集。用户已完成此次建分支，不代表后续修改自动获得提交/推送授权。
- **不启动、停止、重置**训练机上的实验；本机只做代码、分析和 CPU 小规模测试。
- **保留玩家真实选择**：选牌、跳过、确认、药槽满时换药等不能用随机、自动领取或静默丢弃替代；只有原生本身直接完成的选择才自动完成。卡死只能截断，不能代选。
- **模拟器**：保留同学的 C++ 模拟器并修正规则；不重写、不换成纯原生执行、不靠删掉真实决策提速。网络需要的接口只能新增，不能借机改规则；改规则要更新 ruleset 身份（`sim/PORT_SOURCE.json`、`ENGINE_RULESET_ID`）。对齐规则时对照 `artifacts/native-source/` 逐行移植，新 ID 只追加在末尾，生成的表改生成器再重新生成，新增状态覆盖 clone、快照校验、观察和绑定。出现差异以原生 DLL 为准改 C++，不改样例。
- **可部署到原生客户端（硬要求，现在不实现但不能走偏）**：
  - 要上线的策略网络只能读 `spire.public/1` 的 `PublicState`（原生端由宿主 `NativePublicObservation` 导出），不能用旧 `obs.py`、C++ `entity_observation` 或模拟器内部状态。
  - 观察里新加的任何推算量（观察清单 A–F，如“这回合最多打多少”、动作效果预览）必须只由 `PublicState` 加共享代码算出，或者两端各实现一份并有对拍测试。**不能依赖“在模拟器副本上试走”**，客户端里没有对应的模拟器状态。
  - 价值函数看隐藏信息只用于训练，不受此限。
  - 原生端执行动作只走真实界面控件，或与界面相同的 GameAction，不加只有无界面宿主才有的捷径。
  - 宿主的读状态/执行逻辑（`NativeGameBridge` / `NativeGameScreens` / `NativePublicObservation`）与启动（`NativeBootstrap`）、传输（`HeadlessHttpServer`）保持分开。
  - 命令行只从 `PublicState` 渲染，以后可以直接接原生后端。
  - **防循环 / 防卡死属于 AI 驱动层**（读 `PublicState` → 网络 → 选动作的共享 Python），训练与上线用同一份；可以把驱动层自己记的公开历史（如已跳过次数）作为观察，可以从候选里去掉会循环的动作；不改模拟器和原生游戏。例：跳过卡牌奖励后可重开是原生行为（DEVLOG 第 26 节）。
- **NoSL**：策略的输入只能有人能看到的信息（或由它和规则推算出的）。隐藏随机顺序不能泄漏到观察；新观察要用“只改隐藏状态、观察不变”的检查验证。
- 不删 `artifacts/preserved-game-versions/`。
- 核对规则要核对**效果**，不能只看招式编号对得上（DEVLOG 9.2 曾因此把几处错的写成一致，第 10 节已更正）。
- 基础注册检查入口为 `sim/tools/audit_native_registry.py`，原始 DLL 表 `sim/native-fixtures/native-registry-41cef1ea.json` 不可改写；旧整数与别名按 `registry_identity_lock.json` 锁定。源码文件名可能是抽象类或辅助类，不能直接当原生模型注册。
- 怪物数值检查入口为 `sim/tools/audit_monster_numbers.py`；原始 DLL 文件在 `sim/native-fixtures/native-monster-numbers-41cef1ea/`，不可改写或重算 SHA 掩盖差异。`apply_native_monster_numbers.py` 更新已审核数值，继承 AI 由 `native_monster_ai.py` 解析；新变更要同时检查静态表和实际执行/公开显示。
- 观察新增字段**只追加在行尾**：`train/spire_rl/obs.py` 按固定下标读战斗观察的玩家行（如 `P_POTIONS = 39`），中间插入会错位。
- `Card` 现为 304 字节，填充位已用完；再加字段会变大，`tests/native_step3_events.cpp` 的 `main` 栈上放了多个 `RunContext`，可能栈溢出。加字段前先量大小。
- 编译期间先冻结 C++ 头、源文件和绑定；`sim/build.py` 检测到输入中途变化会拒绝发布扩展并要求重编，避免混合结构布局。
- 每批改动都跑 C++ 和 Python 测试，并在 `docs/DEVLOG.md` 末尾记录（日期、做了什么、为什么、结果）。不要把“不崩溃”写成“和原生一致”。
- 用户不熟悉实现细节：先说结论，用平实的话，直接给建议；分析要基于原始数据，区分已确认、较强怀疑与证据不足。

## 4. 版本与身份

**分支约定（用户 2026-11-18 指定并自行操作）**：

- `v111_SF2`：完整项目和当前工作分支，后续在现有工作目录继续开发（各机器路径不同，见 2.1）。目录清理及 `sim/`、`train/`、`parity/`、`docs/` 等已纳入 Git；有无新修改用 `git status` 核实。
- `v111_simulator`：从已提交的 `v111_SF2` 提取的模拟器子集，根目录仅 `sim/`、`.gitignore`、`LICENSE`。保留 `sim/` 目录层级，源码、生成表、绑定、依赖和固定样例均在其中；不包含训练框架、原生宿主、项目文档或根目录 `AGENTS.md`。它有独立提交历史，**不要求创建第二个本地工作区，也不需要把主工作区切换过去**。
- `v111_SF1`：保留旧版；删除或覆盖任何已有分支需用户明确指定。
- 同步顺序：先在 `v111_SF2` 提交需要发布的内容，再提取该提交的模拟器子集更新 `v111_simulator`。两分支不会自动同步；发布时比较两边的 `sim/` 子树。后续更新应在已有模拟器分支历史上追加提交，不重复初次创建分支的步骤，不通过合并完整工作区把 `train/`、`parity/` 等带进去。
- 2026-11-18 本地核验：`v111_SF2` 为 `aefad6a`，`v111_simulator` 为 `fbfdd8f`，各自与本地 `origin/` 跟踪引用相同；两边 `sim/` 子树均为 `0b6a9774eb7686ee60957603781ee1a76d60f6d8`。本次未联网刷新，不能将跟踪引用称为远程实时状态。
- **2026-11-20 上传完成（America/Los_Angeles，用户确认）**：完整项目已推送至 `origin/v111_SF2`，提交 `ac34251`（`Add PPO training, improve public observations and update simulator to v21`）；模拟器子集已推送至 `origin/v111_simulator`，提交 `b159d4e`（`Sync simulator v21 from v111_SF2`）。本地核验 `v111_SF2` 与 `origin/v111_SF2` 均指向 `ac34251`，且完整项目与 `origin/v111_simulator` 的 `sim/` 子树均为 `79731ae2b788ffe2c20561bb968a801f846ea27d`。本次仅读取本地引用，上传成功依据用户确认；这次补记的 `AGENTS.md` 修改尚未提交或推送。
- `sim/build/`、`parity/stage/`、`artifacts/`、`runs/` 等继续忽略。游戏备份、反编译源码、SDK 和训练输出不会随分支上传，需另外保留。

模拟器子集可独立编译并跑 C++ 固定样例测试、`sim/tools/audit_monster_numbers.py`；准备阶段已在隔离目录重新编译，51/51 C++ 测试通过。完整注册审计 `audit_native_registry.py` 依赖 `train/spire_rl/public_catalog.json`，应在完整工作区执行；重新生成原生内容还需要本地 `artifacts/native-source/`。

- 目标原生：`v0.111.0 / 41cef1ea`，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 模拟器 ruleset `native-41cef1ea-port-v30`；宏观观察 `MACRO_OBS_VERSION=4`（96 列）；战斗实体观察 `COMBAT_OBS_VERSION=5`（112 列）；扁平公开观察 `PUBLIC_OBS_VERSION=19`（v19 起遗物上限 64）；`ACTION_SCHEMA_VERSION=15`；快照 v20（v20 起遗物数组 64 格，含 v29 的回合流程额外回合标记与 Lord's Parasol 购买进度；v19 起每敌人出牌状态覆盖 6 个敌人槽位；v18 起 Unmovable 计数改为本回合 / 本次出牌的获得格挡记录数；v17 起 Fur Coat 标记坐标等遗物状态；v16 起 Goopy 写回牌组的状态；v15 起逃跑金币比例状态；v14 起 CurlUp 来源 UID 和 Aeonglass CardsLeft 使用空闲辅助槽；旧快照拒绝）。**默认 `NativeProgressContext` 是全解锁老玩家**（用户 2026-11-18 指定），`init` / `init_seed` 的第一幕按原生在 Overgrowth / Underdocks 间各 50%；需要固定第一幕或复现旧录制时用 `init_seed_with_context(种子, 进阶, 第一幕, progress)`。公共双端契约 `spire.public/1`，**`public_obs.FEATURE_VERSION=12`**（检查点记录，不符拒绝加载）；实体行 `NUM=768` 列，动作候选行 `CAND_NUM=544` 列（语义描述字节上限 495），各新增特征的列位置见 `docs/observation-checklist.md` 末尾“编码布局”；它是独立新布局，旧网络默认仍使用 legacy 布局，新模型需设置 `UnifiedNetConfig(observation_schema="spire.public/1")`。敌人上限 6；观察新字段只追加在行尾，宏观卡片进度固定放 `num[78]`，保留 `num[79]` 的选中标记。`train/spire_rl/obs.py` 仍按固定下标读玩家行。`CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽），`Card` 仍为 304 字节。
- 模拟器的已知差异和未验证部分见 DEVLOG 第 2.4、11–14 节：**没有完成整局原生对照**；怪物 A8/A9 数值边界已核对；v15 按源码核对了 A1–A7、A10 的局外效果（A6 删牌价已修）。当前最强真实战斗执行证据仍为单个种子从 Neow 到首战、领奖并回地图的 31 步完整公共契约对照。
