# SlayTheModel：当前任务与交接

更新：2026-10-31。此文件是用户要求给下一个 AI 的交接记录。
重点是**保留 C++ 模拟器的速度，将铁甲战士单人规则对齐到原生高速探针使用的游戏版本**。
历史结果只代表下面注明的版本和覆盖范围；继续工作前核对实际文件，避免把旧审计当成现状。

## 1. 用户目标与工作约定

- 最终用途：让模型高速完成对局、记录新训练数据，再进行自迭代。
- 用户选择保留同学的 C++ 模拟器，修正规则；不要擅自换成纯原生执行、重写整套引擎，或通过删掉真实决策来提速。
- 当前主要范围是铁甲战士。其他四个角色尚未完成完整牌池、专属机制和原生对照；跨角色生牌仍会影响铁甲。
- 保留玩家真实选择：选牌、跳过奖励、药槽满时换药等不能用随机选择、自动领取或静默丢弃替代。
- 未获新的明确指令时，不提交、推送、合并分支、部署或发布模组。用户通常自己提交，需要时提供命令和 commit message。
- 不覆盖用户原始权重、不可变参考副本或前轮证据。与当前任务无关的模型、采集器、`combat/` 改动不混入本轮。
- 子目录的历史发布/PR授权不代表当前用户已授权发布。前轮 agent 分工已结束，继续并行时重新安排文件所有权。

## 2. 真正工作的目录：不要改错副本

以下路径相对本仓库根目录：

| 用途 | 路径 |
| --- | --- |
| **当前可编辑 C++ 对齐副本** | `artifacts/dev/cpp-native-aligned-20261031/` |
| 原生高速探针/执行参照 | `artifacts/dev/rtg-probe-20261027/` |
| 目标原生反编译源码 | `artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/` |
| 不可变 C++ 基线 | `artifacts/reference/alphazero-be401e8/` |
| 初始原生比较记录 | `artifacts/reference/alphazero-be401e8-review/` |
| 用户原始权重（不要覆盖） | `artifacts/reference/armg-live-20261031/latest.pt` |

- 当前开发副本基线：`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`，来自 `origin/alphazero`。
- **原生探针与 C++ 模拟器是两个不同执行实现。** 原生探针用实际游戏代码；当前修复发生在 C++ 副本，不能把一方的测试通过当作另一方已等价。
- 根 `.gitignore` 忽略 `artifacts/`。所以根 `git status` 看不到本轮主要代码修改；不能因此认为没有改动或已同步远程。
- 本机安装路径：`/Users/yebohou/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources`。

## 3. 版本、证据和模型兼容性

目标是本机原生 **`v0.111.0 / 41cef1ea`**，DLL SHA-256：

`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`

当前开发副本：

- ruleset：`native-41cef1ea-port-v3`；`NATIVE_PARITY_COMPLETE=false`。
- 公开观察 schema12、动作 schema11、ArmG feature4、快照v7。
- `CARD_COUNT=223`，含 INVALID 和保留的 Grapple；222个卡牌条目中221个对应目标原生模型。
- 卡牌特征251维，战斗动作343维，ArmG动作1300维；公开观察46079维，其中战斗29688维、局外16391维。
- 旧权重/快照必须通过版本和引擎身份检查。**尚无经过审核的旧模型→新 Not Yet 词表迁移适配**，前两轮迁移器会明确拒绝，不能只改版本号/哈希强行加载。
- `agent/engine_identity.py` 绑定源码、特征与二进制身份；加载后重新构建模块需要重启 Python 进程。
- 原始上传权重 SHA-256：`cfcb115024b0b0a222b88bf0033ef55e1e7b3cf667194c9dbba36b923180b91c`，第三轮结束时未改变。

以下文档均在当前 C++ 开发副本内：

- `PORT_STATUS.md`：最新中文总览；`PORT_SOURCE.json`：版本来源。
- `validation/round3/summary.json`、`cpp-tests.json`、`python-tests.txt`、`engine-contract.json`：本轮最终验证。
- `validation/round3/cards-audit.json`、`relics-audit.json`、`events-audit.json`：逐项审计及剩余问题。
- `native-round3-{card,relic,event}-fixtures/`：实际目标 DLL 的受控样例、宿主源代码、结果及验证信息。
- `validation/round3/source-before/`：本轮前的备份；旧轮次的报告/样例不要覆盖。
- `validation/round3/native-rules-port-v3.patch`、`changed-files.json`：累计源码补丁与清单，已做基线 apply 检查；不含游戏DLL、宿主二进制或权重，尚未提交/推送。
- `docs/native-act-alignment-20261031.md`：幕、Boss、账号发现顺序及生成时序边界。

### 审计记录的一条纠正

`relics-audit.json` 里 **LostCoffer“固定普通无色牌”是过期/错误描述**。
当前 `relics.cpp` 调用 `queue_card_reward(Rarity::COMMON, true)`；第二参数是 `useBaseOdds`，默认牌池是 Ironclad。
不要把它重新列为“牌池写错”；剩余应核验完整奖励稀有度修正、升级与联动流程。
此外 Grapple 在目标原生不存在，保留旧ID并排除正常使用是已完成的兼容措施，不是待实现原生卡牌。

## 4. 已做成什么：避免重做

前两轮已对齐/补充：原生种子字符串规范化、哈希/RNG、部分抽洗牌规则；战斗内外手动选牌；公开牌实例状态；多个选牌遗物、附魔和结算钩子；Golden Compass；有限账号进度及替代第一幕 Underdocks。

第三轮主要完成：

- 导出596个原生卡牌模型的基础/升级版本，校正62条已有卡牌数据。
- 末尾追加 **Not Yet**：2费、治疗10/13、消耗、不能战斗随机生成。保留已有 CardId，HEAL 追加到 VarId 末尾。
- 排除原生不存在的 Grapple，铁甲单人全解锁变牌池80张候选及顺序与实际 DLL 列表一致。
- 修复 Conflagration、Spite、Dominate、Forgotten Ritual、Pact’s End、Drum of Battle、Second Wind、Maul、Rend 等效果；随机多段的 Vigor/Skittish；Brightest Flame 最大生命损失、复活/Rupture；六张只改变行为的升级。
- 修复 Distinguished Cape、Sere Talon、Leafy Poultice、Neow’s Torment、Stone Cracker、Seal of Gold、Fake Strike Dummy；Red Skull 随血量即时更新。
- 修复 Aroma/Wellspring/Spirit Grafter 的真实选牌、Dense Vegetation、Tablet、部分金币生成时机；事件减伤/复活；休息入口 Feather/Tea、Mailbox两瓶奖励、满药槽奖励保留及非战斗药水池顺序。
- 共检查23类普通事件、30类遗物。数字/元数据匹配不代表全部效果组合已等价。

已验证：

| 检查 | 第三轮结果 |
| --- | --- |
| 实际目标DLL受控效果样例 | 153个成功：卡牌70、遗物26、事件/休息/药水57 |
| C++回归 | 23个程序全部通过；含3996项新卡牌对照、447项原规则、104项观察检查 |
| 快照与隐藏状态 | 6742个运行中快照、6000次重采样通过 |
| Python接口/版本身份/桥接编码 | 113项通过 |
| 整局贪心冒烟 | 1000局正常终止，0异常、0截断，平均9.6层、0胜 |

本机冒烟约110局/秒，仅是贪心引擎吞吐，不是神经网络/MCTS训练速度或模型通关证据。
第三轮没有重新训练。第二轮曾跑2局训练+1局验证，仅证明当时训练流程；不能据此宣称当前模型已通关或适用新版本。
**尚无完整同种子、同进度、同决策整局与原生逐步一致的证明。**

## 5. 已确认的具体缺口

### A. 卡牌

| 对象 | 原生要求 | 当前差异 |
| --- | --- | --- |
| Crimson Mantle | 每次施加累计每回合自伤量 | 仍固定自伤1 |
| Inferno | 独立累计自伤状态 | 仍固定自伤1 |
| Splash | 已解锁其他角色的攻击牌池 | 使用铁甲牌池近似替代 |
| Mad Science | 事件配置决定类型和效果 | 缺少完整配置状态 |

### B. 遗物

| 对象 | 原生要求与当前差异 |
| --- | --- |
| Toy Box | 原生5件蜡制遗物，每3战按顺序熔化，15战结束；当前4件普通遗物并持续随机删除，缺少完整蜡制状态 |
| Sea Glass | 原生指定角色15张候选，玩家选0～15；当前自动加3张随机铁甲非普通牌 |
| Lead Paperweight | 原生2张无色候选，可跳过；当前自动加1张随机无色非普通牌 |
| Dusty Tome | 原生预选并保存古老角色牌，升级加入；当前用随机稀有牌替代 |
| Prismatic Gem | 原生扩展已解锁角色牌池；当前仅第三个奖励位置变无色 |
| Dream Catcher | 休息治疗后正常选牌奖励流程缺失 |
| Bone Tea | 指定一场战斗升级初始手牌的触发缺失 |
| Fake Venerable Tea Set | 进入休息点后下场战斗+1能量的保存/触发状态缺失 |
| Byrdpip | 鸟蛋变牌与宠物召唤系统不完整 |
| Touch of Orobas | 原生原位替换起始遗物；当前移除再追加，且遗物附属计数未同步移动，可能错位 |
| Arcane Scroll | 当前直接抽稀有牌，未走完整原生奖励牌生成随机流和联动 |
| Small Capsule | 当前直接获取，未保留遗物奖励的跳过与获取时机 |
| Large Capsule | 原生按有序遗物袋取出；当前额外随机稀有度，流程不同 |
| Delicate Frond | 药水生成候选、分布和失败处理未完整对齐 |
| Alchemical Coffer | 向新增4槽发药水的随机流和槽位规则未对齐 |
| Massive Scroll | 原生多人专用；当前单人过滤不完整并近似为随机无色牌 |

### C. 已有事件的剩余差异

- Welcome to Wongo’s：特卖遗物选择、商店过滤、消费触发、徽章/进度状态不完整。
- Reflections 及 Wongo’s 的降级操作：仅翻转升级标记，可能保留升级后的 storedCost，需要完整降级恢复。
- Dense Vegetation：主要流程已修，但模拟休息仍缺 Dream Catcher 联动，保留 APPROXIMATE。

### D. 整项未实现的原生事件

已核对 **31项已注册但 UNSUPPORTED，另3项未注册**。不计纯占位 `AROMA_PLACEHOLDER`。
当前过滤未支持事件，会改变事件池、概率和随机序列；不能将“没有遇到它”视作已实现。

| 范围 | 已注册但未实现 | 原生存在但尚未注册 |
| --- | --- | --- |
| 第一幕 Overgrowth（密林） | ByrdonisNest、JungleMazeAdventure、LuminousChoir、MorphicGrove | WhisperingHollow、WoodCarvings |
| 替代第一幕 Underdocks | EndlessConveyor、PunchOff、TrashHeap | — |
| 第二幕 Hive | Amalgamator、Bugslayer、ColorfulPhilosophers、ColossalFlower、FieldOfManSizedHoles、InfestedAutomaton、TheLanternKey | ZenWeaver |
| 第三幕 Glory | BattlewornDummy、GraveOfTheForgotten、RoundTeaParty、TinkerTime、Trial | — |
| 共享 | CrystalSphere、DollRoom、FakeMerchant、RanwidTheElder、RelicTrader、SelfHelpBook、SlipperyBridge、Symbiote、TeaMaster、TheFutureOfPotions、TheLegendsWereTrue、WarHistorianRepy | — |

### E. Boss、进度和生成时序

- **AeonglassBoss 无对应C++怪物/遭遇实现。** 原生Glory池是 Aeonglass/Queen/TestSubject；当前仍是 Doormaker/Queen/TestSubject，A10第二Boss也受影响。
- 指定发现进度要求首次出现 Aeonglass 时当前会拒绝初始化；`aeonglassSeen=true`默认值不表示Boss已实现。
- ByrdonisNest 有枚举无实现，原生首次Overgrowth强制该事件的入口当前明确拒绝。
- 密林已是第一幕；Underdocks 已作为替代第一幕接入，不是第四幕。普通 `init/init_seed` 默认 Overgrowth→Hive→Glory，带 context 的入口才执行第一幕选择。
- 当前只接入有限账号发现/解锁开关，没有完整epoch内容过滤和原生存档进度导入。
- 原生开局生成所有幕的rooms；当前进入对应幕才生成。此时序不同，尚未证明一般等价，也不能断言每条路径必然不同。
- PunchOff 的专用战斗还涉及两只怪的不同初始招式和随机初始HP减少值，不能直接套普通遭遇。

## 6. 尚待核验，不要当成已确认错误

- Primal Force 的可变牌筛选、新实体替换、生成牌钩子组合。
- 自定义奖励完整稀有度修正、升级概率及遗物联动，包括上面纠正后的 Lost Coffer。
- 特殊生成牌、宠物/随从、队友及复杂效果组合；其中多人机制不属于当前单人完整支持承诺。
- 固定牌堆/遗物容量边界，以及 C++ double 与原生 decimal 的取整边界。
- 原生桥接的活动选牌网格、Pael暂存牌来源范围与UI执行仍不完整。已有编译/编码测试不是游戏UI实测。
- 完整同种子、同账号进度、同决策长路径对照。

## 7. 下一步建议与实施方法

推荐顺序（后续用户指令优先）：

1. 修复铁甲核心战斗的自伤状态，以及费用恢复、遗物计数错位等直接影响收益的问题。
2. 补齐会改变决策空间的遗物真实选牌/跳过和持续状态，禁止用随机自动领取掩盖缺失。
3. 补事件及正确Boss池、账号过滤，再做后两幕的完整长路径对照。
4. 等规则/特征稳定后审核旧权重迁移或从新环境初始化训练，之后才评估大规模自迭代。

工作方式：

- 先读目标原生源码；重要/不确定交互用实际目标DLL受控样例核验。不要采用其他游戏版本的卡牌描述冒充目标规则。
- 每批使用新的 fixture/validation 目录保留证据；不改旧样例结果来迁就模拟器。
- 多人并行时给文件划清所有权；共享头文件、布局、观察/动作和身份变更统一协调，构建前冻结源码。
- 若新增状态，必须覆盖 clone、snapshot、公开观察、动作/桥接等相关路径；隐藏随机顺序不能泄漏给模型。
- 新增ID追加到末尾，不复用Grapple槽、不重排旧ID；同时恢复原生候选顺序，编号顺序不一定等于抽取顺序。
- 更新生成源与生成文件，避免重新运行生成器丢失修复。
- 重要验证维度：结果、候选身份/顺序、RNG调用计数、选择暂停/恢复、奖励跳过、伤害/复活和满槽行为。
- 小批修复后跑针对性原生对照和回归，再汇总明确已修/未修；不要把“不崩溃”或元数据一致写成完整原生等价。

## 8. 本机复现入口

以下命令的工作目录是 `artifacts/dev/cpp-native-aligned-20261031/`：

```sh
/opt/anaconda3/bin/python validation/build_local.py
/opt/anaconda3/bin/python validation/round3/run_cpp_tests.py
```

第二条会重写第三轮测试汇总；继续新一轮时应复制/调整运行器，将新日志写入新目录以保留旧证据。
构建脚本使用Apple clang、Python3.11，复用对象文件并保持回归断言开启；本机未用cmake入口，未验证Windows构建。

第三轮Python选择集：

```sh
/opt/anaconda3/bin/python -m pytest -q tests/test_content.py tests/test_binding_schema_contract.py tests/test_native_act_context.py tests/test_native_seed_identity.py tests/test_engine_checkpoint_identity.py tests/test_armg_native_bridge.py tests/test_armg_features.py tests/test_armg_floor_final_boss.py
```

上一轮只粗估过“3～5轮”，不是完成承诺；按实际缺口、依赖和验证结果重新评估，不给没有证据的百分比。
