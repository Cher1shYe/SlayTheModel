# 全部活动怪物数值核对（v14）

2026-11-18（America/Los_Angeles），目标原生 `v0.111.0 / 41cef1ea`，模拟器 `native-41cef1ea-port-v14`。范围为单人 A0–A10：小怪、精英、Boss，以及这些遭遇中的召唤物和组件。**静态数值使用真实 DLL 导出核对，动态数值按源码核对并测试 C++ 执行；没有将后者称为原生战斗对拍。**

## 覆盖范围与证据

以原生 `ModelDb.Monsters` 的 **107 个活动模型**为全集，不用源码文件数量代替。为避免重复，按 Boss 优先、精英其次、其余最后划分：

| 分组 | 模型数 | 包含内容 |
| --- | ---: | --- |
| Boss 相关 | 15 | Boss 本体、蟹的两臂、Kin 随从、女王的 Amalgam 等 |
| 精英相关 | 17 | 精英本体、蜈蚣三个具体节段、Wriggler 等 |
| 普通/事件/其他召唤物 | 75 | 普通敌人、事件敌人、机器人、蛋、幻象等 |

Aeonglass 也纳入本次核对。Decimillipede 的三个模型仍共享一套 C++ 数值实现，身份映射保持 v13 的 Front/Middle/Back。

真实 DLL 在 **A7、A8、A9、A10** 的普通开局上下文中读取属性；各次开局前再读取 A0。由此核对血量变化的 A8 边界、攻击与能力变化的 A9 边界，以及目标 A10。DLL 导出是全新的可变怪物实例，没有注入 Creature 或强行替换内部字段；无法读取的动态属性明确报错。

- **535 个模型上下文、1,635 个招式上下文、1,075 个攻击上下文，3,215 次血量/伤害/次数比较，0 个未解释差异。**同一数据另与实际编译后的 C++ 表逐项比较，不能只让两个 Python 表互相证明。
- Boss 的 **75 个活动招式 × 11 个升阶 = 825 次 C++ 动作执行**，检查真实扣血、命中次数、格挡、能力、塞牌和治疗；另检查复活血量、次数成长、压力枪成长、Wither 升级和六牌周期。
- 精英的 36 种攻击及附加效果按 A0–A10 执行，另检查 Hive 上限、Tainted 同步、蜈蚣 25 血复活和四只 Wriggler。
- 普通组有 2,091 项源码静态检查；本轮修正的成长、格挡、继承伤害和相关能力时序增加了专项执行测试。

机器报告见 [monster-number-audit.json](monster-number-audit.json)。逐怪源码审阅记录在 `sim/tools/monster_audit_boss.json`、`monster_audit_elite.json`、`monster_audit_normal.json`；报告保留修正前发现，不能把它们误读成当前仍有同样差异。

## 已修正的确定差异

| 对象 | 修正 |
| --- | --- |
| Crusher / Rocket | A9+ 的 Adapt / Charge Up 力量增长各由 2 改为 3。 |
| Louse Progenitor | A9+ 的 Grow 力量增长由 5 改为 7。 |
| Nibbit | Slice 格挡在 A8+ 由 5 改为 6；Hiss 力量在 A9+ 由 2 改为 3。 |
| Waterfall Giant | Siphon 在 A0–7 治疗量由 15 改为 10，A8+ 仍 15；压力枪 A9+ 的基础表值补为 23，实际每次使用继续 +5。 |
| Mysterious Knight | 修复继承漏读：A9+ Flail 为 10×2、Ram 为 17；同时继承原生随机分支的等权和最多连续两次规则。旧值为 9×2、15，旧分支把“最多两次”误作权重。 |
| The Forgotten | Dread 改为基础 13（A9+ 15）加当前敏捷。旧表把首次 Miasma 后的数值固定成 15/17，后续不再增长。显示和执行共用计算。 |
| 怪物格挡 | `ValueProp.Move` 格挡先加敏捷，再应用 Frail、取整并限制至少 0。Guardbot 给 Fabricator 的 15 点是 Unpowered，继续不吃敏捷/Frail。 |
| Entomancer | Hive 缺失或已达到 3 时，吐息只加 2 力量并结束；不再额外加 Hive 和 1 力量。 |
| Infested Prism | VitalSpark 增长时，同步已有 Tainted 卡牌的数值，包括活跃牌和选择副本；死亡时也清除活跃牌副本的污染，避免技能通过 Juggernaut 杀死 Prism 后又把旧污染写回牌堆。 |
| Crab Rage | 一侧死亡后，另一侧力量由错误的 +5 修为 +6；格挡 99 保持。 |
| Curl Up | 整张来源攻击牌完成后才获得 14/18 格挡；多段中途不提前获得，攻击全部被挡住仍触发，无来源卡牌的伤害不触发。 |
| Rampart | 额外玩家回合不重复给炮台增加 25 格挡。 |
| Aeonglass | WitheringPresence 放在 Boss 身上，Amount 恒为 6，独立 CardsLeft 从 6 递减，每六张牌生成一张 Wither；模型正确看到能力归属、Amount、显示值和 CardsLeft。 |

生成表通过生成器更新，没有直接修改生成的 C++ 表或原生样例。`native_monster_ai.py` 现在追踪继承的状态机；`apply_native_monster_numbers.py` 从固定 DLL getter 数据应用已审核数值，TheForgotten 的动态公式另核对原生源码。

## 动态例外与未覆盖部分

- **TheForgotten.DREAD**：未挂 Creature 的 DLL getter 无法读取敏捷；保留原始错误，动态回归验证无敏捷、第一次和第二次 Miasma 后的伤害与格挡。
- **Waterfall 压力枪**：新建但未加入战斗的原生模型，其当前伤害字段是 0；表中存的是实际开战基础 20/23。审计分别读取 `BasePressureGunDamage`，执行测试验证后续每次 +5，不把原生 fresh 0 改成 20/23。
- TestSubject 多爪次数、复活血量，Axebot 复活成长，Aeonglass 的 Wither 和力量成长等不能只凭初始 getter 相同就宣称完整一致；它们有源码期望及专项 C++ 回归。
- 四个旧招式槽保留但不属于当前原生活动招式：Axebot.SHARPEN、Cubex.SUBMERGE、HauntedShip.RAMMING_SPEED、TestSubject.POUNCE。保留本地索引，避免破坏旧状态引用。
- 没有完成所有玩家遗物/能力组合、全部能力钩子顺序、多人缩放或整局对拍。Thieving Hopper 偷牌的挑选规则仍是原有待核对项。这次的“数值通过”不能扩大成这些机制也已完全一致。

## 编号、快照与复查

所有怪物、卡牌、遗物等旧整数 ID 保持不变，v13 的注册审计和编号锁仍通过。Card 仍为 304 字节，观察维度与字段位置不变。

快照升到 **v14**：Louse 的空闲辅助槽保存 CurlUp 来源卡 UID；Aeonglass 的空闲辅助槽保存 CardsLeft。它们覆盖 clone、快照校验和观察；UID 只用于执行，观察输出 pending 布尔值，不泄漏内部编号。旧 v13 快照按版本拒绝，不能按新语义静默解释。

```sh
python sim/tools/audit_monster_numbers.py --out docs/monster-number-audit.json
python sim/tools/audit_native_registry.py --out docs/registry-audit.json
```

固定原始数据在 `sim/native-fixtures/native-monster-numbers-41cef1ea/`。manifest 和审计代码均钉住各文件 SHA-256；故意修改原始数值或 manifest 不会被当成新的正确答案。源码期望样例 `sim/tests/fixtures/monster_boss_numbers_41cef1ea.json` 明确标为源码整理，不冒充 DLL 执行记录。

最终回归：**C++ 51/51、训练 Python 42/42、parity Python 89/89**。保存的 31 动作/32 决策原生完整公共接口轨迹仍通过离线重放，原始帧未修改；本轮没有增加全怪物的原生战斗执行轨迹。
