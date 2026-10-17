# 战士／无色第三批：持久能力与触发器

日期：2026-10-17（Asia/Shanghai）。本轮为工程接入，未启动训练，未读取或运行最终留出集。

## 范围和进度

在前两批 44 个 ID 的基础上新增 6 张及其升级版：战士 Barricade、Rage、Feel No Pain、Demon Form；无色 Fasten、Eternal Armor。当前 **50/151**（战士 37/87、无色 13/64），剩余 **101** 个 ID 尚未接通。怪物保持既有十个遭遇。

这是机制覆盖的一批推进，不代表全部战士和无色牌完成。当前逐 ID 状态见 `IRONCLAD_COLORLESS_COVERAGE.md` 与 `ironclad_colorless_coverage.json`。

## 机制、编码与重建

| 卡牌 | 本批明确实现／验证的语义 |
|---|---|
| Barricade | 回合开始保留格挡；重复打出不叠加层数 |
| Rage | 攻击结算后获得格挡；玩家回合结束移除，因此本次 Body Slam 不使用本次 Rage 刚产生的格挡 |
| Feel No Pain | 每张消耗牌触发非强化格挡；包含选择消耗、牌自身消耗及虚无牌回合末消耗 |
| Demon Form | 从下一玩家回合开始增加力量；按每次公开打出回合累计，不提前增加 |
| Fasten | 仅强化带 Defend 标签的卡牌格挡；不强化 Rage／Feel No Pain 的非强化格挡 |
| Eternal Armor | Plating 在玩家回合末早期提供格挡，敌方回合结束总层数减一；重施加累加后每回合只减一次 |

新增 `player_abilities`（能力与当前层数）和 `ability_plays`（公开 token 与打出回合）。校验当前能力与出牌记录、当前回合出牌历史、移除的能力牌、Demon Form 累积力量一致。无效能力、重复能力、错层数、跨版本数据被拒绝。搜索粒子由这些公开字段重建，不读取原世界私有状态。

实体输入增加能力触发操作与 Defend 语义标签；卡牌 ID 仍是注册查询键，不作为学习数值特征。动态合法动作继续使用当前节点的实体引用与动作候选，补测能力已激活之后的 MCTS 重建、重复搜索确定性与合法落子。

能力牌移除历史由 Inflame 单例扩展至本批能力牌。Rage 是技能牌，不记为移除的能力牌。公开 JSON、实体 Replay、粒子状态均包含新字段。

## 排查发现和修复

1. 原生 `Creature.apply_power` 对重复 Barricade 直接加层，违反本地 `decompiled/MegaCrit.Sts2.Core.Models.Powers/BarricadePower.cs` 的 Single 定义。本轮修复 Barricade 重施加路径，没有泛化修改其他尚未审计的能力。
2. Boss 第二形态 Painful Stabs 的公开伤口生成推导原先只考虑现有格挡与 Burn。加入 Plating 与 Feel No Pain 后，按“现有格挡 + Plating + 虚无消耗触发格挡 − Burn”再计算敌方各段伤害，避免伤口数量与原生执行不符。
3. 新内容的 V7 风险项 q 同步考虑上述确定性回合末格挡；世界侧、公开状态侧和 MCTS 效用使用一致口径。V7 获胜／死亡／超时公式与 H0 定义保持原规范。旧内容仍使用旧风险投影。

4. 终局公开投影直接读取已有出牌区卡牌的类型，避免仅为判断能力牌而新建卡牌实例；测试确认重复观察不会改变实例分配计数。

## 版本边界

- 内容：`ironclad-colorless-powers-v2`。
- 信息：`ironclad-colorless-information-v2`。
- 实体：`public-entities-ironclad-colorless-v2`。
- 机制：`ironclad-colorless-mechanics-v2`。
- 单人 Ironclad、Ascension 0、无遗物药水；固定 MLP 不接入新内容。
- 上批 `ironclad-colorless-batch1-v1` 不再作为当前运行版本。源码／schema 摘要改变，旧 checkpoint、Replay、冻结配置不能直接续跑。
- 前两批报告及其证据属于提交 `8231515` 的历史快照；被更新的覆盖清单以本批证据为准。

## 测试与证据

**最终 3,264 项通过，0 失败、0 错误、0 跳过（424.81 秒）**；测试前后源码摘要一致。统计和源码／文件摘要见 `ironclad_colorless_powers_evidence.json`。完整日志与 JUnit：`ironclad_colorless_powers_verification.txt/.xml`。

覆盖新旧单牌基础／升级版 × 十个遭遇、30 条二十张混合牌组轨迹、选择中断续接、格挡→Body Slam 次序、能力跨回合衰减／叠加、JSON 与 Replay 往返、已激活能力的动态 MCTS，以及既有 G2.3e、T2、Boss、变形、选择、生命周期、V7 奖励、超时 Replay 和原生卡牌／能力回归。

测试中对齐隐藏牌序／随机数只作为差分 oracle。没有使用最终留出配方，也没有启动学习实验。测试通过仅说明上述工程范围，不代表 network 效用提高；后续训练仍以实际 network 整场 V7 效用验收。

## 下一批

优先接入 **Dark Embrace 与 Rupture**：需为虚无消耗后的延迟抽牌、选择中断期间的待结算触发、同张牌自损与攻击先后顺序建立公开状态和精确重建，并补齐 Headbutt 已知牌顶／抽牌、消耗与 Body Slam 的交互。随后再处理逐实例费用／伤害变化和复杂自动出牌。
