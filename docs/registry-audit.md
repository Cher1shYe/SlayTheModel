# 基础注册核对：v0.111.0 / 41cef1ea

2026-11-19，模拟器 ruleset `native-41cef1ea-port-v13`。依据是真实游戏 DLL 导出的 `ModelDb` 注册与属性，并用反编译源码解释条件属性、继承和遗留占位。**这里只核对身份、注册池和所列基础属性，不代表所有效果或整局行为一致。**

## 核对范围和结果

| 类别 | 原生范围 | 核对内容与结果 |
| --- | --- | --- |
| 卡牌 | 596 个注册模型，其中 1 个 DeprecatedCard 为旧存档兜底 | 595 个实际内容全部有映射；类型、稀有度、目标、费用、升级、关键词、数值、标签、生成限制、12 个池及顺序。MadScience 未配置模板的类型/目标差异单独保留，见下文。 |
| 遗物 | 299 件 | 299/299 身份、稀有度、所属池；Shared/Ironclad 实际抽取池的成员和顺序。 |
| 药水 | 65 种实际内容，另 1 个原生测试 Mock | 65/65 身份、稀有度、使用时机、目标、职业限制、战斗生成；Shared/Ironclad 池顺序。 |
| 普通事件 | 57 个活动事件 | 全部存在；各幕及共享池成员、顺序相同。 |
| 先古之民 | 8 位 | 全部存在；各幕与共享池顺序、合计 102 个遗物候选成员关系相同。102 是各位候选数之和，不表示互不重复的遗物数。 |
| 怪物 | `ModelDb.Monsters` 的 107 个活动模型 | 全部有映射；A0/A10 基础血量区间相同。蜈蚣前/中/后段保留同一套 C++ 规则实现，公开身份分别对应三个真实模型。 |
| 遭遇 | `ModelDb.AllEncounters` 的 85 个活动模型 | 全部有映射；各幕普通/弱敌/精英/Boss 池成员与顺序、标签、槽名声明已核对。 |

模拟器枚举槽数和上述“活动模型数”不同，不能只比较总数判断是否缺失。完整逐字段结果见 [registry-audit.json](registry-audit.json)，保留每项例外和未核对范围。

## 本次修正

- **遗物稀有度 6 项**：Permafrost、TinyMailbox 改为 Uncommon；BagOfMarbles、RedMask 改为 Common；Bellows 改为 Rare；LastingCandy 改为 Uncommon。Circlet、DeprecatedRelic 的基础表改为真实 None 稀有度，取消靠名称特判补救。
- **遗物所属池 4 项**：FresnelLens、LoomingFruit、VeryHotCocoa 改为 Shared；TwistedFunnel 改为 Silent。LastingCandy、RazorTooth、SparklingRouge 原生同时出现在多个池，保留合法的 Shared 分类。前三件修改分类后仍显式标为已实现。
- **药水目标**：23 种 Self 改为原生 AnyPlayer；FoulPotion 的战斗外目标为 TargetedNoCreature，战斗内为 AllEnemies。后者条件来自原生源码，未声称做过该药水战斗内实际 DLL 执行。
- **MadScience 元数据**：补全真实模型 ID、类名和事件卡池顺序 `8014`；旧生成器跳过类型 None，导致这三个基础字段漏掉。
- **MysteriousKnight**：A10 血量由错误的 101 修为 108；原生继承 FlailKnight 的升阶血量，旧生成器漏处理继承。
- **遭遇池与标签**：TunnelerNormal 虽有注册类，但不在原生 Hive 普通池，已从生产池排除并保留旧枚举；补齐 SlitheringStranglerNormal 的 Jaxfruit/Slimes、SnappingJaxfruitNormal 的 Jaxfruit，并纠正旧 TunnelerNormal 的 Chomper 标签。
- **蜈蚣身份**：按持久槽名 segment1/2/3 导出 Front/Middle/Back，避免把抽象类 DecimillipedeSegment 当作原生模型；击倒、敌人列表变短、复活和 clone 不改变剩余段的身份。
- **模型词表**：从 DLL 实际注册建立词表并排除 Mock；去掉 VakuuCardSelector 辅助类、三个 Temporary 能力抽象类、DecimillipedeSegment 和 BattlewornDummyEventEncounter 抽象类造成的 6 个伪注册。词表摘要随之改变，旧公共词表权重不可静默复用。

## 保留的例外与验证边界

- GRAPPLE、AROMA_PLACEHOLDER、DOOR/DOORMAKER/ROYAL_GUARD、DOORMAKER_BOSS/TOADPOLES_NORMAL 是保留旧编号的非活动槽，不冒充当前原生内容。
- DeprecatedCard、DeprecatedEvent、DeprecatedAncientEvent 是原生兼容旧存档的兜底；TheArchitect 是结局事件，不是普通事件池漏项。宠物、调试模型、未启用类也分别列在机器报告中。
- MadScience 的原生未配置模板是 None/Self；旧基础表为 Attack/AnyEnemy，事件实际牌实例另用 `tinkerType` 决定类型和目标。这两个模板差异被明确报告，不计为一致，也不在本次重写事件效果。
- 新 DLL 导出中 Stardust 两个 variant 因没有 owner 而报错；原始错误照存。既有完整卡牌 DLL 样例覆盖它的数值，其余 1,190 个可读取 variant 与旧样例交叉核对相同。没有把导出异常填成 0。
- 遗物/事件/先古的动态数值常写在效果处理器中，并无单独对应的 C++ 注册字段，本轮未把这些效果全面核实。怪物 AI、初始阵容生成、事件奖励路由、动态选项条件与概率、整局执行仍需后续逐步对照。

## 防止再次错位

`sim/content/registry_identity_lock.json` 锁定现有 **Card / Relic / Potion / Monster / Encounter / Event** 的实际整数、枚举名和原生 ID 映射。旧编号不可删除、重排或重新指向别的内容；新增只能追加。锁定包含 INVALID 和历史占位，共 597 / 300 / 66 / 110 / 92 / 66 个槽。

正常核对命令不会改写基线：

```sh
python sim/tools/audit_native_registry.py --out docs/registry-audit.json
```

命令同时检查原始 DLL 导出 SHA-256、生成表、已编译的遗物/药水表、公共词表、ruleset 身份和编号锁。有未解释差异时返回非零退出码。`--create-lock` 只用于初次创建，已有基线会拒绝覆盖；不要删除重建来掩盖差异。

原始导出：`sim/native-fixtures/native-registry-41cef1ea.json`，SHA-256 `2fff4579c9fcb9c8eba920a6316ca711267529e041a858d49c9100773caa2969`。对应游戏 DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。导出步骤见 [parity/README.md](../parity/README.md)。
