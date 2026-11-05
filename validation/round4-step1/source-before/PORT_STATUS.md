# C++ 原生规则对齐：第三轮审计

2026-10-31。独立开发副本，基线 `be401e8`；目标为本机原生探针使用的
`v0.111.0 / 41cef1ea`，游戏 DLL SHA-256：
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。

当前 ruleset：`native-41cef1ea-port-v3`，**仍不是完整原生等价**。
本轮覆盖卡牌数据和选定效果、23类普通事件、30类遗物。逐项报告：
`validation/round3/cards-audit.json`、`events-audit.json`、`relics-audit.json`。
第二轮状态保留于 `validation/round3/source-before/PORT_STATUS.md`，原始证据未覆盖。

## 这轮修正了什么

### 卡牌

- 从实际游戏 DLL 导出596个卡牌模型的基础与升级版本。当前222个编译卡牌条目中，221个能对应目标原生模型；修正62条既有数据，涵盖费用、类型、稀有度、数值和关键词。
- 末尾追加 **Not Yet**：2费、回复10/13生命、消耗、不能在战斗中随机生成。保留旧编号；原生已不存在的 Grapple 保留编号用于识别，但拒绝正常使用和进入牌池。
- 铁甲单人随机变牌池80个候选及顺序与原生 DLL 导出列表逐项一致。Not Yet 虽是末尾追加编号，抽取顺序仍位于 Molten Fist 与 Offering 之间。
- 修正 Conflagration 多段群攻、Spite 条件多段、Dominate 结算顺序、Forgotten Ritual、Pact’s End 可打出但不满足条件时零伤害、Drum of Battle 技能/消耗回能、Second Wind 消耗顺序、Maul 自身成长、Rend 负面状态分类等效果。
- 修正随机多段攻击的 Vigor、Skittish 结算；Brightest Flame 降低生命上限经过伤害、复活和 Rupture 钩子。六张只改变行为的升级牌恢复可升级判定。

### 遗物

- Distinguished Cape 改为两张不同诅咒及三张 Apparition；Sere Talon 改为降低9生命上限及三张 Wish。
- Leafy Poultice 降低12生命上限，只变第一张基础打击和防御，使用正确随机流、候选顺序和加牌钩子。
- Stone Cracker 每场战斗随机升级两张合适的抽牌堆卡；Seal of Gold 花费3金币；Neow’s Torment 获得 Neow’s Fury；Fake Strike Dummy 补伤害加成。
- Red Skull 在受伤、治疗、复活时立即更新力量。相关新增卡牌获取会在固定容量不足时提前拒绝，避免获取后静默丢牌。

### 事件与休息

- Aroma、Wellspring、Spirit Grafter 保留真实玩家选牌，支持选择中快照恢复；纠正 Dense Vegetation、Tablet of Truth 等费用、奖励和阶段。
- 事件伤害统一经过减伤及复活流程；部分随机金币改为进入事件时抽取，匹配原生随机数消耗时机。
- Eternal Feather 和茶具在进入休息房间时触发；Tiny Mailbox 只在休息治疗后提供两瓶药水奖励。满药槽保留奖励，Wellspring/Courier 也不再直接丢弃奖励。
- 非战斗药水池使用原生顺序。Dense Vegetation 仍标记为近似支持，因为 Dream Catcher 的普通战斗牌奖励尚未补齐。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 新增实际目标 DLL 效果样例 | 153个：卡牌70、遗物26、事件/休息/药水57；均成功，目标DLL哈希一致 |
| C++回归程序 | 23个全部通过；包括3,996项新卡牌对照、447项既有规则、104项观察检查 |
| 快照与隐藏状态 | 6,742个运行中快照；6,000次隐藏状态重采样通过 |
| Python接口、观察、权重身份和桥接编码检查 | 113项通过 |
| 整局冒烟 | 1,000局正常终止，0异常、0截断；简单贪心策略平均9.6层、0胜 |

整局冒烟约110局/秒，属于引擎贪心测试，不是神经网络或MCTS训练速度，也不是模型能力证据。
本轮没有重新训练模型。原生样例是受控调用，不是同种子完整对局逐步对照。
完整日志和汇总：`validation/round3/summary.json`、`cpp-tests.json`、`python-tests.txt`。

## 已确认但尚未修完

- **复杂遗物**：Toy Box 蜡制遗物及熔化流程、Sea Glass/Lead Paperweight 的真实选牌、Dusty Tome；Dream Catcher、Bone Tea、Fake Venerable Tea Set、Byrdpip 等仍有缺失钩子。
- **卡牌状态**：Crimson Mantle / Inferno 每次施加累计自伤；Mad Science 事件配置；Splash及其他跨角色牌池。数值对齐不等于这些状态已完整实现。
- **事件与随机池**：Wongo 的商店与进度过滤、部分降级后的费用恢复、完整账号epoch解锁；未实现事件及Boss仍是上一轮列出的缺口。
- **整局与桥接**：尚未证明同种子同决策整局完全一致；原生桥接活动选牌网格、Pael暂存状态和UI执行仍需补齐。

## 版本与使用边界

加入 Not Yet 后，公开观察为 **schema12**、动作 **schema11**、ArmG特征 **v4**、快照 **v7**。
223个卡牌ID包含INVALID及保留的Grapple；卡牌特征251维、战斗动作343维、ArmG动作1300维。
旧快照和旧模型默认拒绝加载。前两轮的权重迁移器没有新牌词表的已审核适配，
现会明确拒绝；旧模型需要另做显式迁移，或从新环境初始化训练，不能直接续训。
旧训练权重和用户上传权重均未覆盖。

本机重建：`python validation/build_local.py`；测试：`python validation/round3/run_cpp_tests.py`。
本轮在Apple clang/Python3.11验证，未声称Windows构建已经验证。
完整累计源码补丁：`validation/round3/native-rules-port-v3.patch`，清单为 `changed-files.json`；
未提交、推送或部署。补丁不包含游戏DLL、宿主二进制和模型权重。
