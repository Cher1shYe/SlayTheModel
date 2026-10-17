# 战士／无色 V4：状态、选择续接与原生生成依赖

日期：2026-10-17。**5,111 项必要测试全部通过**，失败／错误／跳过均为 0；24 个测试文件按四组执行，核对每个收集用例恰好执行一次。最终摘要见同目录 `ironclad_colorless_foundation_evidence.json`；没有启动训练实验或读取最终留出集。

## 覆盖范围

相对已发布 V3 的 70 张，本批新增 **50 张及升级版**，累计 **120/151**：战士 **83/87**、无色 **37/64**，剩余 **31**。逐牌六链路状态见 [覆盖清单](IRONCLAD_COLORLESS_COVERAGE.md) 和 `ironclad_colorless_coverage.json`。

| 机制 | 本批接入 |
|---|---|
| 基础状态 | Weak、临时正负力量、Dexterity、Cruelty、Colossus、No Block、Vigor、Pyre 最大能量；对应 Uppercut、Shockwave、Setup Strike、Mangle、Dark Shackles、Fight Me、Prowess、Cruelty、Colossus、Panic Button、Prep Time、Pyre |
| 选择与后续结算 | Brand、Thinking Ahead、Secret Technique、Secret Weapon、Seeker Strike、Stratagem；选择后的力量、抽牌、格挡和多目标结算可暂停与续接 |
| 检索与牌堆消耗 | Cinder、Anointed、Aggression、Drum of Battle；保留可见筛选结果与牌面，不暴露抽牌堆索引 |
| 自动打出与嵌套执行 | Havoc、Cascade、Howl from Beyond、Catastrophe、Beat Down、Hellraiser、Mayhem、Stampede；保存父子出牌、抽牌、回合阶段、监听器和剩余队列 |
| 触发能力 | Dark Embrace、Rupture、Vicious、Flame Barrier、Grapple、Juggernaut、Crimson Mantle、Inferno、Juggling、One Two Punch、Unmovable、Unrelenting |
| 牌面与公开历史 | Rampage、Thrash 的逐实例伤害成长；Spite 的本回合掉血条件、Tear Asunder 的整场受击计数；复制标记、临时能量／星费用和回合清理 |
| 原生生成 | Jackpot、Infernal Blade、Discovery、Calamity；对应原生候选池完整闭合，不按已支持子集过滤 |

表中“接入”指本版本单人战斗模型的引擎、公开状态、实体描述、动态动作和粒子／MCTS 接口，不能解读为所有游戏内容或任意资源环境均已支持。

## 生成范围的明确边界

`ironclad_colorless_generation_pools.json` 保存候选 ID、池摘要和未支持依赖，来源是原生工厂的候选规则。

- 战士原生战斗候选共 **79** 个，全部进入 V4 编码与搜索合同；Discovery 使用完整角色池，Infernal Blade／Calamity 使用完整角色攻击池，Jackpot 使用原生零费池。
- **Splash 暂缓**：会带入其他职业牌和机制。
- **Jack of All Trades 暂缓**：原生无色池含 Splash。保留原生规则中排除自身的行为，不另做支持性过滤。
- **Entropy 暂缓**：变换无色、事件或远古牌时可进入含 Splash 的无色池。不能把它改成只生成战士牌并称为原版一致。
- 因此本批没有宣布随机变换全覆盖；这是按用户最新范围要求执行的依赖暂缓。旧 Primal Force 固定变换继续保留。

## 公开状态、网络与搜索

1. `ironclad-colorless-foundation-v4` 使用 V4 information/entity/mechanic schema；扩展牌面采用 `az-public-card-state-v2`，旧内容仍使用 V1 codec。
2. 牌面记忆从初始牌组和公开生成、升级、变换、成长、移动事件推导。抽牌堆只存无序多重集和已知顶／底前缀；同牌面身份有歧义时保守忘记相关已知位置，不读取隐藏索引来补齐。
3. 出牌栈保存父牌、重放次数、自动打出标记、目标、后续效果和队列。Beat Down 的剩余随机批次公开完整候选集合与次数，隐藏已打乱顺序，由搜索粒子重新采样。
4. 保存公开能力顺序、额外计数、Rupture 延迟力量、Calamity 待触发攻击与 Unmovable 所需格挡历史。进程地址、原生 instance ID、真实 RNG 状态不进入序列化；恢复时绑定粒子内对象。
5. 实体输入包含上述牌面与阶段信息、可见选择候选及触发顺序；动作仍由合法状态动态生成，没有新增卡牌 ID 策略输出头。
6. 有限实现预算继续失败即拒绝：单状态牌数上限 2145、公开能量上限 4003；实体上限调整为 `2 * MAX_CARDS + 128`，允许可见选择与候选投影。它们是运行容量边界，不能当作任意自动生成链的数学上界；超限不得静默裁剪或降级为结束回合。
7. V4 schema、牌面和执行状态与旧 Replay／权重不直接兼容。没有迁移或恢复既有训练运行。

## 修复的交互问题

- 自动打牌遇到选择时，恢复剩余批次与父牌；回合开始／结束中的选择不提前推进敌人行动。
- 抽牌触发 Hellraiser 后，保留外层抽牌与 Battle Trance／Drum of Battle／Thinking Ahead 的后续效果。
- Dark Embrace 的抽牌可暂停剩余消耗监听器；Fiend Fire、Second Wind、Stoke、Purity、Burning Pact、Brand 的后续效果按原顺序续接。
- Vicious 在多敌人 Vulnerable 施加过程中触发选择时，保留剩余敌人的状态结算。
- Juggling 中途生效读取此前已开始的攻击记录；One Two Punch 的重放不再受“出牌次数必须不超过决策次数”的旧假设限制。
- Boss 公开回合和形态历史按实际可见行动／击倒事件更新；不再假定一次结束回合动作必然完成整轮。
- 初始所有牌堆统一绑定所属玩家，修复隐藏 Stomp 费用变化漏记；整堆 Stomp 更新和回合费用清理的日志规范排序，不暴露隐藏遍历顺序。包含不同升级版 Stomp 的多粒子一致性测试。

## 验证与验收口径

最终必要测试覆盖逐牌基础／升级版、既有十个遭遇、公开状态往返、粒子单步对照、动态 MCTS、原生池闭包、临时零费／复制清理、嵌套选择，以及旧 Boss／Replay／奖励和原生规则回归。使用合成工程夹具；随机初始化模型仅用于接口测试。

最终测试计数、源码稳定性、schema 摘要和工件 SHA-256 记录在证据 JSON；原始输出和 JUnit 文件同目录保存。`file_sha256` 对应本地测试字节，`canonical_text_sha256` 统一 CRLF/LF 后用于跨平台 Git 检出核验。

**未评估策略学习增益。** 后续训练仍以实际 network 整场 V7 效用验收；胜率只作诊断。本次不改 V7 公式。风险项仍是公开意图波次的估计，不展开未来随机自动打出、生成或反击连锁，因此不能等同于完整执行下一回合后的实际掉血。

## 下一步

继续按覆盖清单处理剩余 31 张的独立依赖；战士剩余为 Corruption、Demonic Shield、Feed、Tank。优先盘点它们的费用／消耗改写、队友目标、最大生命与战斗外副作用，再决定单人战斗合同的可接入范围。Splash、Jack of All Trades、Entropy 维持暂缓。任何新训练或最终留出使用都需要新的用户任务授权。
