# 战士／无色简单效果扩展 V3

日期：2026-10-17。范围沿用单人 Ironclad、无遗物药水、既有十个遭遇。未启动训练、未使用最终留出集。

## 本批接入

新增 20 个基础 ID 及全部升级版，累计 **70/151**：战士 **50/87**、无色 **20/64**，剩余 **81**。

- 战士：CONFLAGRATION, EXPECT_A_FIGHT, PERFECTED_STRIKE, PILLAGE, FIEND_FIRE, SECOND_WIND, STOKE, STONE_ARMOR, SWORD_BOOMERANG, PACTS_END, EVIL_EYE, FORGOTTEN_RITUAL, BATTLE_TRANCE。
- 无色：DRAMATIC_ENTRANCE, FISTICUFFS, IMPATIENCE, MIND_BLAST, OMNISLICE, REND, VOLLEY。

优先覆盖即时伤害／格挡／抽牌／能量、公开牌堆与回合计数、普通消耗、既有 Plating，以及简单 NoDraw。每张牌均接通显式机制描述、实体特征、动态合法动作、公开状态重建、粒子模拟和 MCTS。原生已注册不代表这些链路自动可用。

## 机制与重建

- Conflagration 按本回合已完成攻击牌数计算，不把多段伤害计为多张攻击；Perfected Strike 提供 Strike 标签语义，按所有牌堆统计。
- 本回合消耗记录仅由公开消耗堆增量构造，下一回合清空；重建原生事件供 Evil Eye／Forgotten Ritual 使用。Pact’s End 合法性随消耗堆变化。
- Fiend Fire、Second Wind、Stoke 保留消耗与后续伤害／格挡／抽牌的顺序；验证 Feel No Pain→Second Wind→Body Slam、消耗抽牌与已知顶牌。
- Stone Armor 仍为能力牌，计入移除能力账本；复用 Plating。Battle Trance 先抽牌再禁止额外抽牌，重复施加 NoDraw 不叠层、回合结束移除。
- 先天牌进入开局手牌；Sword Boomerang／Volley 将原生目标槽别名折叠成一个随机攻击动作，实体候选保留所有可随机命中的敌人引用。
- Volley 记录实际 X 能量消耗，包括零能量；新版公开能量／支付上限为 4003，覆盖 400 次决策与每次至多 10 点收益的保守边界，旧内容仍保留 1203 上限。
- 新描述还包含 Mind Blast 的抽牌堆计数、Rend 的减益种类、Fisticuffs 的实际伤害结果格挡及 Omnislice 的无加成溅射。

## 版本与验证

内容 `ironclad-colorless-simple-v3`，信息、实体、机制 schema 同步升级 V3。旧 Replay／权重不兼容，不沿用旧冻结实验恢复。工程测试不等于 network 效用提升，后续学习验收继续采用实际整场 V7 效用。

完整回归 **3,849 项通过**，耗时 239.03 秒，零失败／错误／跳过；测试前后源码摘要一致。测试结果与源码摘要以 [机器证据](ironclad_colorless_simple_evidence.json)、[原始日志](ironclad_colorless_simple_tests.txt)、[JUnit](ironclad_colorless_simple_verification.xml) 为准。测试包括全新增牌基础／升级版 × 十遭遇的公开重建轨迹，动态 MCTS、Replay 往返、Transformer 契约以及原生参考机制回归；新增 52 项专用组合／状态测试。

## 剩余工作

[覆盖清单](IRONCLAD_COLORLESS_COVERAGE.md) 与 JSON 已增加注册钩子源码摘要，避免仅凭主效果函数把自动出牌／延迟回手判断为简单牌。旧 V1/V2 报告的统计和清单哈希对应各自历史提交，当前清单以 V3 为准。

下一批优先补基础状态依赖（例如 Uppercut／Shockwave 所需的敌方 Weak）和对应风险／Boss 重建契约；随后再处理 Dark Embrace／Rupture、自动打出、逐实例成长、延迟回手与选择续接。多人专用、永久 HP／金币／药水等外部资源依赖继续拒绝准入。**尚未实现全部 151 张，也未扩到其他职业。**
