> 本文记录提交 `8231515` 的前两批历史结果。最新进度为 50/151，见 [持久能力第三批报告](AZ_IRONCLAD_COLORLESS_POWERS.md)；当前覆盖清单已更新，历史原始文件摘要请在该提交读取。

# 战士／无色牌机制扩展：覆盖盘点与前两批

日期：2026-10-17。按用户最新范围，仅新增战士和无色牌；不启动训练，不读取或运行最终留出集。策略验收仍为实际 network 的 V7 终局效用；本报告仅作工程验收，不声称 network 质量提高。

## 覆盖分母与实际进度

固定范围来自本地 `core/card_pools.py`：战士 87、无色 64，共 **151 个基础 ID**，升级版单独检查。原生工厂及效果函数均已注册，但注册不代表机制、公开表示或搜索正确。

| 牌池 | 基础 ID | 原有实体链路接通 | 本次新增 | 当前接通 | 尚待接通 |
|---|---:|---:|---:|---:|---:|
| 战士 | 87 | 24 | 9 | 33 | 54 |
| 无色 | 64 | 3 | 8 | 11 | 53 |
| 总计 | 151 | 27 | 17 | 44 | 107 |

**这不是全部 151 张牌完成。** 逐牌清单见 [覆盖清单](IRONCLAD_COLORLESS_COVERAGE.md)，机器清单 `ironclad_colorless_coverage.json` 分别记录 engine、observation、action、network、belief/search、tests、源码位置、升级描述摘要和阻塞路径。注册状态不冒充引擎语义审计；剩余 107 张仍拒绝进入新内容配方。

## 本次两批

1. 基本有序效果与抽牌／保留：BLOOD_WALL、BREAKTHROUGH、TREMBLE、TAUNT、FINESSE、FLASH_OF_STEEL、MASTER_OF_STRATEGY、PRODUCTION、ULTIMATE_DEFEND、ULTIMATE_STRIKE、SALVO、SCRAWL。
2. 易伤交互：BREAK、BULLY、DISMANTLE、DOMINATE、MOLTEN_FIST。

17 张均包含基础及升级版。沿用经过显式审计的原生执行函数，新增机制描述、版本化配方准入、卡牌 codec、实体编码、当前节点合法动作映射、公开历史及粒子恢复。未把卡面文本当执行器，也未按 ID 扩大固定策略头。

新增机制操作：抽至手牌上限、按目标易伤计算伤害、条件连击、按目标易伤获得力量、倍增目标易伤。`damage_conditional_hits` 的 `hits=2` 是满足条件时次数，`coefficient=1` 是不满足时次数；伤害仍由引擎逐击结算并检查死亡。`strength_from_target_vulnerable` 引用所选敌方，收益归出牌者。效果顺序保留：例如自损在格挡前、伤害在易伤倍增前。

## 修复的问题

### 原生参考工厂未分配唯一实例 ID

`cards/factory.py::_build_reference_card` 原来使用默认 `instance_id=0`。多个相同 Salvo 因 dataclass 相等比较被判为同一实例，第三次出牌后缺少一张弃牌；公开牌守恒将缺口归入未知抽牌堆，粒子恢复与真实执行不一致。

修复为每次创建分配新的实例 ID。探测工厂仍保存／恢复全局计数，粒子仍使用局部隔离计数；实例 ID 不进入网络数值特征。覆盖范围内每张卡的两个独立实例及升级版均做唯一性检查；额外回归完整原生卡牌工厂测试。

### Dominate 的跨回合力量历史缺失

旧校验仅由已打出的 Inflame 推导力量。新增 `PublicHistory.dominate_strength`，由出牌前所选公开敌方的易伤层数和公开卡牌倍率累积，跨回合保存；校验玩家力量必须等于 Inflame 收益与该累计值之和。旧内容不允许非零新字段。不拷贝私有 world 或未来随机状态。

### 抽牌位置与 Salvo 保留

将新增抽牌牌接入公开牌顶／牌底消费逻辑，覆盖 Headbutt→Finesse／Flash of Steel／Master of Strategy／Scrawl。Salvo 接入保留回合历史，升级 Scrawl 的静态 Retain 和升级 Production 移除 Exhaust 均依原生版本编码。

## 版本和使用边界

- 内容：`ironclad-colorless-batch1-v1`；配方族 `ironclad-colorless-audit`。
- 信息：`ironclad-colorless-information-v1`；实体：`public-entities-ironclad-colorless-v1`；机制：`ironclad-colorless-mechanics-v1`。
- 单人 Ironclad、Ascension 0、无遗物药水；怪物仍是既有十个遭遇。原有生成牌依赖保留；本次没有扩大其他角色牌或怪物准入。
- 新内容只接入实体 Transformer；固定 MLP schema 显式拒绝。旧 `g2-boss-v1` 不接纳新增卡牌。
- 新 schema/源码摘要与旧 checkpoint、Replay、冻结运行配置不兼容。历史实验工件保留；没有修改原冻结配置或把它们视为可续跑。本次未建立训练划分或打开训练入口。
- 动态动作来自当前原生合法动作表，引用实体位置；每个搜索节点重新构建。测试中对齐隐藏抽牌／随机数只用于原生差分 oracle，不进入观察或模型。

## 测试证据

最终 **2,858 项通过，0 失败**：新增／范围测试 719，既有回归 2,136，Replay 超时依赖 3。测试前后源码摘要一致。

最终日志：`ironclad_colorless_tests.txt`（新增及范围测试）、`ironclad_colorless_regression.txt`（既有回归），对应同名 XML；证据摘要与文件 SHA-256：`ironclad_colorless_evidence.json`。另同步发布已经修复的 Replay 超时回合口径依赖，单独测试记录为 `ironclad_colorless_timeout_dependency.txt`。

覆盖：151 张范围内卡牌的基础／升级版原生执行与实例身份；新增 17 张 × 2 版本 × 10 遭遇的整段轨迹原生／公开／粒子对照；公开 JSON 与 Replay 编码往返；确定性小预算 MCTS 和合法动作；自损致死；格挡→Body Slam；易伤条件单／双击；神器抵消；易伤倍增→力量转换；Headbutt 已知牌顶消费；Armaments 升级；Primal Force 变形；20 张混合牌组中的选择、生成、消耗与重建；既有 G2.3e/T2、Boss 重建、V7 奖励及全原生卡牌工厂回归。

这些测试不证明尚未接通牌的全部特殊语义正确，也不是 network 评估。尚未测得新内容 network 效用。

## 后续批次

1. **持久能力和触发器**：Barricade、Rage、Feel No Pain、Dark Embrace、Rupture、Demon Form，以及无色对应能力。先建立可版本化的公开能力状态、触发顺序与重建字段，再开放卡牌。
2. **逐实例变化**：Rampage、费用修改、附魔、重复打出；公开区域不能仅按 ID 合并，必须保存每实例变化和关系。
3. **复杂选择和自动出牌**：Brand、Discovery、Jack of All Trades、Havoc、Cascade 等，补齐公开选择候选、续接状态、随机生成和自动播放历史。
4. **长期统计与外部依赖**：受击／消耗／出牌计数、最大 HP、药水、多人目标等。对依赖不完整的整场继续拒绝；不能给未知 token 后放行。

完成这些内容批次后，另行冻结适配新 schema 的课程与运行方案。后续经授权实验仍按 network 效用验收，不以胜率或搜索成绩替代。
