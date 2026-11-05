# C++ 原生规则对齐：第二批修复

日期：2026-10-31。独立开发副本，基线 `be401e8`，目标为原生探针的
`v0.111.0 / 41cef1ea`、DLL SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
当前 ruleset 为 `native-41cef1ea-port-v2`；`NATIVE_PARITY_COMPLETE=false`。
主工作区没有切分支、提交、推送或部署模组。原始模型权重没有覆盖。
第一批记录保留在 `validation/round2/round1-status.md`。

## 本轮完成

- **模型输入**：抽牌、弃牌、消耗牌堆保留逐张公开的费用、伤害成长、重复打出、附魔、保留等状态；候选和已知顶部牌补齐相同属性。不可见的堆内顺序仍不暴露。新增 Pael 暂存牌、等待获得的遗物、幕类型和已知账号进度输入。
- **遗物和选牌**：Pomander / YummyCookie 改为玩家选择升级；潘多拉只变基础打击、防御，执行正常加牌钩子；WarPaint / Whetstone / SandCastle 使用原生筛选及稳定随机顺序；Pael’s Tooth 保留真实选择，暂存后逐战随机升级返还并创建新实体；连续获得遗物按顺序等待选择完成。
- **地图与幕**：Golden Compass 黄金路线及问号规则；Underdocks 作为替代第一幕，20个遭遇池与新增 SeapunkNormal；有限账号解锁、发现顺序和历史输入。详见 `docs/native-act-alignment-20261031.md`。
- **事件和附魔**：新增 AbyssalBaths、DrowningBeacon、SunkenTreasury、DoorsOfLightAndDark、SpiralingWhirlpool、WaterloggedScriptorium 六个事件。补 Spiral、Steady、Nimble 和 Fresnel Lens 的相关钩子，支持真实选牌及满药槽时保留药水奖励。
- **顺带核实的旧规则**：Expect a Fight 改为3费、按力量获得格挡；Setup Strike 临时力量改为3/4；肉骨在燃烧之血前判断血量；降低生命上限经过伤害与复活流程。同步 Cinder 的内容生成源，重新生成不会回退上轮修复。
- **训练与桥接**：显式权重迁移，新增从新环境初始化 PUCT 的入口；可明确使用全新随机战斗先验并关闭网站先验。隔离的原生桥接补丁补真实字段与严格拒绝边界，已编译，未部署，详见 `bridge/README.md`。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 本轮真实游戏 DLL 样例 | 48 个成功：遗物/附魔24，事件15，结算/Setup Strike9 | 三个 `native-*-round2-fixtures/` 与 `native-boundary-fixtures/` |
| C++ 回归 | 19 个程序全部通过；包括447项原有规则、104项观察区分检查、93项本轮遗物检查 | `validation/round2/cpp-tests.json` |
| 快照与隐藏状态 | 6,811 个实时快照、6,000 次隐藏状态重采样通过 | 同上 |
| Python 原有接口及新幕上下文 | 58 项通过 | `validation/round2/python-integration.txt` |
| 身份、迁移、新训练初始化与桥接字段 | 32项通过，另7项战斗分类检查通过 | `validation/round2/python-identity-results-final.txt` |
| 原生桥接编译 | 0 warning，0 error；尚未做游戏UI实测 | `validation/round2/bridge-build.txt` |
| 整局冒烟 | 1,000 局正常终止，0异常，0截断；简单贪心策略0胜，平均9.6层 | `validation/round2/benchmark-1000.txt` |

本机这次冒烟约106局/秒。测试期间还有其他校验进程，这不是严格基准对比，
也不是神经网络或MCTS训练速度。原生样例均为受控场景；地图部分使用目标源码
提取的夹具。上述结果不代表同种子整局已与原生逐步一致。

**实际跑通2局训练+1局独立验证**：训练平均13.5层，验证17层，均正常死亡，
无异常或截断。网络6个参数张量均实际更新，优化器完成1步，保存后的模型与战斗先验
严格重载通过。新环境训练局数记录为2。使用8次模拟/决策、oracle搜索信息、
全新未训练的冻结战斗先验、禁用网站先验；不等于同学的完整训练配置。
报告为 `validation/round2/puct-training-smoke-audit.json`，checkpoint为
`validation/round2/puct-training-smoke-fixed/latest.pt`。短训练只验证流程，不作为
策略强度、收敛或原生可用性证据。

实际训练首先暴露旧版战斗分类门拒绝schema11的问题；修复为核对原生公开的
inBattle/elite/boss字段并加入7个回归，保留最初0局失败的日志。

## 仍需补齐

1. **完整内容池**：Prismatic Gem 仍缺其他角色完整牌池；下水道的 EndlessConveyor、PunchOff、TrashHeap，以及多项共享事件尚未实现。Glory 的 Aeonglass Boss 与完整原生Boss池也未补齐。当前过滤未实现内容会改变事件池和随机数消耗。
2. **整局同种子对照**：有限进度上下文还不包括全部epoch解锁过滤；需原生账号完整进度、同决策长路径逐步对照。首次教程要求未实现的 ByrdonisNest、强制发现 Aeonglass 的上下文会明确拒绝。
3. **原生桥接复杂选择**：新增字段和最小补丁已编译，但活动grid、selection template、非空Pael暂存状态仍明确拒绝。需要原生取得来源scope及后续操作信息，再做UI执行验证。
4. **训练有效性**：这轮可以新建训练，但新随机战斗先验不是同学已训练的战斗先验；关闭网站先验也不等于复现其完整训练配置。还没有证明新环境模型能通关或迁移到原生稳定游玩。
5. 其余卡牌、敌人、遗物组合仍需逐项对照；固定容量、double与decimal差异及所有幕提前生成的时序尚未整体消除。

## 版本与交付

公开观察 schema11、动作 schema10、ArmG feature3、快照v6。
旧快照拒绝加载；旧网络只能经过显式、具来源校验的权重迁移。迁移保留已核对的旧列，
新增列置零，不继承优化器、旧环境局数或随机状态。

当前副本是可审查、可运行的开发版。新的完整源码补丁与清单位于
`validation/round2/native-rules-port-v2.patch`、`validation/round2/changed-files.json`；
原来的第一批补丁保留。补丁不含游戏DLL、原生宿主二进制或模型权重。

本机重建入口：`python validation/build_local.py`。Python环境需要开发头文件和PyTorch；
本轮使用Apple clang直接构建，未声称Windows构建已经验证。
