# MCTS 与采集器整合修复

更新时间：2026-10-15  
游戏版本：`v0.111.0`

## 断点续采

旧数据 `fcb5038d6f77493ea3f9f84f1fca92cc` 最后两条为
`process_exit` 和 `collector_error`。保存的检查点停在事件序号 5，日志已经写到
序号 12；续局进入检查点不匹配分支时，匿名对象中的两个字段在 snake_case
转换后重名，导致序列化失败并停用采集器。

现在使用 `ResumeCheckpointMismatch` 为检查点序号和 journal 序号提供不同的稳定
wire name。无法证明连续性时，旧片段按 `incomplete` 发布，新片段重新开始；不会把
缺失内容补写成完整轨迹。采集器自身异常同时进入 Godot 日志和 journal diagnostic。

## MCTS 自动操作采集

MCTS 的原生 `GameAction` 入队不经过人工点击入口，`ICardSelector` 返回也不经过
普通选牌 UI。当前工作树通过 Adapter 的只读 telemetry，在动作入队前冻结观察，
入队后记录提交，并在选牌请求、自动完成、人工 fallback 和失败边界分别记录来源。

与远程分支最初的 `automation_or_unknown` 桥接相比，合并后的实现会写入明确的
`native-mcts` 和 `native_checkpoint_privileged`，人工 fallback 只有在观察到真实输入
证据后才标为 human。战斗外人工操作不会因为战斗策略是 MCTS 而被错误改标。

## 同名卡牌身份

Combat Solver 的选牌 token 按卡牌 ID 与升级等级计算实例序号。原 live 解析却在
完整状态键相同的候选中计算序号；同名副本具有不同附魔或关键词时，第二个实例可能
无法找到。现在先按 token 口径定位实例，再严格核对完整语义状态，并拒绝重复实例。

## 验证边界

- Collector smoke 覆盖断点序号 wire name，不再产生 JSON 名称冲突。
- Policy/MCTS choice smoke 覆盖显式来源、自动选牌、人工 fallback、失败和重复回执。
- Native worker 的头槌夹具覆盖普通/虚无、普通/附魔和完全相同副本，并核对原生
  continuation key。
- `collector-policy-verify` 在同一无窗口原生进程中加载实际 Adapter 和 DataCollector
  Release DLL，连续执行两张防御、头槌和一次弃牌选择；journal 得到 4 组
  decision/action/result/reward，全部为 `native-mcts` / `native_checkpoint_privileged`，
  且没有 coverage gap。
- 以上已经覆盖原生 `GameAction`、`ICardSelector` 与真实 journal writer 的整条链路，
  仍不能替代一整局可见 Steam MCTS 采集复测；旧 JSONL 不回填。
# 2026-10-16：茂密植被事件战斗暂停

茂密植被选择回血后进入四扭动虫战斗时，原生战斗房间具有 `ParentEventId`。原版 v0.111.0 的 `CombatRoom.ToSerializable()` 不允许序列化尚未结束的事件战斗；Adapter 此前直接调用它，导致开战 checkpoint 捕获失败，MCTS 无法开始搜索。

修复在 `NativeCombatCheckpoint` 内为此类活动事件战斗构造 worker 专用 `SerializableRoom`，按原版字段复制遭遇、事件、奖励和自定义状态。普通房间继续使用原接口。不把真实房间标记为完成，不移除父事件，不改变游戏存档政策。该快照只用于隔离 worker 中的战斗重建。

验证命令：`scripts/native-worker.ps1 -GameDir <游戏目录> -Mode event-checkpoint-verify`。回归经实际事件房间、原生休息回血和四怪战斗入口复现旧版异常；修复后核对恢复前后完整状态，实际执行 MCTS 选中动作及敌方回合，与模拟完整 continuation key 对账通过，普通战斗快照往返通过。无头验证未执行事件 UI 音效/按钮交互，也未验证所有其他事件遭遇。

部署后重启游戏生效；旧进程中已经丢失的开战 checkpoint 无法靠 F8 补回，需要重新进入战斗。

## 2026-10-16：知识恶魔反复异常

结束回合的诅咒选择存放在 TurnStartChoices，MCTS 导出此前只读取动作内选择，导致两个原生选项在预测侧变成空选择。现按完整执行顺序导出跨回合选择，并专门校验知识恶魔生成的临时诅咒卡身份及当前轮次的瓦解伤害。原生选择接口虽传 0..1，实际知识恶魔页面不允许跳过，worker 按 1..1 对齐。

异常恢复还有两层问题：冷 worker 不能从挂起选择状态直接捕获根，却访问未初始化的预测状态；取消旧选择时，敌方回合任务不属于普通动作执行器，未等它结束就建立新战斗会留下 UNSET_MOVE。现从开战快照重放已发生输入恢复选择，严格核对状态，并在新战斗前排空旧回合任务。

`-Mode knowledge-demon-verify` 已通过正常 HP 下实际 IPC 的选择恢复、三轮诅咒两条路线（测试 HP 1000，共 18 回合完整原生/预测状态对账）及既有普通选牌、头槌身份回归。未声称整场胜率提高或完成可见 UI 验证。修复 worker 已发布到配置引用的 native-host 目录，重启游戏后生效。

## 2026-10-19：战斗选择面与药水

Native MCTS 的公开动作现在包含 Combat Solver 能精确模拟的药水，动作身份携带物理槽位、药水模型和目标。worker 把模拟侧的隐含自身目标转换为原生协议中的玩家 combat ID；手动用药进入动作前缀，并能在同步打开选牌时成为本次选择的重建触发动作。相邻同槽用药不再被当作重复输入删掉。

药水使用复用 Combat Solver 已有的 `PreparePotionActions`、`PotionExecutionSupport` 和 `PotionChoiceContinuation`。原生只有一个实际候选的必选单选自动完成；多个候选即使语义去重后只有一个结果，仍保留选择节点。冷 worker 已在赌博药水的挂起多选中从 checkpoint 与前缀恢复并返回选择。工具箱等原生页面会把不可跳过的单选报告成 `0..1`，worker 只在预测明确为 `1..1` 且候选身份完全相同时接受这一接口差异，不把真正可跳过的选择改成必选。

`combat-choice-verify` 在 macOS ARM64 v0.111.0 无头原生进程中通过：工具箱、选择悖论、烤手套、探寻打击、六种跨回合选择能力、普通格挡药，以及九种原版选牌药水均核对完整 continuation；液态记忆的唯一候选走原生自动完成，其余夹具覆盖随机生成、抽牌堆、手牌范围、多选与冷启动恢复。`collector-policy-verify` 追加赌博药水和子选择后得到 6 组 decision/action/result/reward，均为 `native-mcts` / `native_checkpoint_privileged` 且无 gap。赌博筹码、知识恶魔、通用 smoke 回归通过。尚未完成可见游戏整局和第三方药水验证。

随后新增 `combat-potion-verify`，直接遍历 v0.111.0 的 `ModelDb.AllPotions`。目录中的 63 种正式手动药水全部由 Native MCTS 枚举并执行，逐瓶与原生完整 continuation 对账；九种选择药水同时走完选择。每瓶在铁甲战士夹具中核对使用完成后的状态，不代表穷尽所有跨回合与遗物组合。仙女瓶已验证不提供手动动作，自动死亡保护由既有引擎处理，本次没有新增死亡触发验证；`DEPRECATED_POTION` 与 `MOCK_DISCARD_AND_ADD_SHIVS_POTION` 作为内部目录模型明确不进入搜索。最终固定单防御牌夹具的 ReplayMcts 在 350 次完成模拟中访问格挡药根分支 117 次，证明药水不只存在于协议结构，也实际进入 UCT 树。

2026-10-20 同步前审查进一步将选择签名兼容严格限定到 `1..1` / `0..1`，避免错误接受 `1..2` / `0..2` 等多选差异。新增 7 个边界用例，并重新通过 macOS ARM64 的 `combat-choice-verify`，含开局选择、牌内选择、跨回合能力、九种选牌药水与冷 worker 恢复；本次未重跑无关测试。
