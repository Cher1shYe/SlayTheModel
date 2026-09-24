# 局外决策接口 v1

局外控制被拆成五个边界：

```text
游戏 RunState + 当前 UI
  -> 原生动作枚举
  -> OutsideCombatDecisionPoint
  -> IOutsideCombatPolicy
  -> OutsideCombatStepRequest
  -> 原生动作绑定与执行
```

策略层只依赖 `SlayTheModel.Sts2.Protocol`，不依赖 `sts2.dll`、Godot 或 Mod。
因此同一个策略可以用于游戏内 play、无头评估，以及之后的训练进程。当前
`FirstLegalOutsideCombatPolicy` 是同步的轻量基线；慢神经网络或远程模型必须放在异步
worker 中，通过请求与结果交接，不能阻塞 Godot 主线程的帧回调。

## 观察

`OutsideCombatObservation` 当前包含：

- 当前选择界面类型；
- `choice_context`：稳定的 `context_id`、不透出正文的 `state_token`、
  `phase`、选择数上下限、已选数量以及取消/确认约束；
- act、楼层、房间和当前位置；
- 每名玩家的 HP、金币、完整牌组、遗物和药水；
- 已知地图节点、节点类型和有向边。

其中 `context_id` 区分删牌、升级、变形等共用同一类 UI 的决策目的；
`phase` 和选择上下限区分选择、预览确认和多选阶段；`state_token` 则使小游戏等
复用控件的内部阶段参与状态指纹。`state_token` 对稳定状态特征求 SHA-256，
协议中只导出不透明 token，不导出本地化正文。

观察不包含 Godot 节点路径、实例 ID、本地化显示文本、原生存档或隐藏 RNG。
游戏版本、程序集 SHA-256 和 MVID 单独存放在决策点的 `BuildIdentity` 中，训练端可以据此分桶或拒绝不兼容数据。

## 动作

每个合法动作都用 `OutsideCombatActionDescriptor` 表示：

- `action_id`：只在当前状态指纹下有效的唯一 ID；
- `kind`：选卡、确认、路线、事件、奖励、商店删牌等语义；
- `ordinal`：原生枚举后的稳定顺序；
- 可选的卡牌/遗物 ID、牌组下标、地图坐标和价格。删牌动作必须同时携带卡牌
  model ID 和 `target_deck_index`，从而区分牌组中的同名卡实例。

Godot 控件只保存在 Mod 内部的临时绑定中。策略返回完整的
`OutsideCombatActionDescriptor`；`action_id` 只是该描述符在当前状态指纹下的唯一标识。
适配器再从描述符构造 `OutsideCombatStepRequest`，执行前由 `OutsideCombatStepGuard`
同时检查状态指纹和动作合法性，避免把旧界面的动作应用到新界面。

`FirstLegalOutsideCombatPolicy` 是第一个协议消费者。普通界面选择 ordinal 最小的动作；
商店删牌是明确的策略特例，依次优先打击、防御、卡牌 ID，而不是写死在 UI 枚举器中。
当前 v1 的商店动作集合仅包含删牌与离开，不包含购买卡牌、遗物或药水；扩充商店动作时
应新增语义动作和观察字段，不能让策略读取原生商店节点。

## 数据采集

启用 `--outside-combat-policy first-legal` 后，每次真正提交动作都会更新：

- `latest-outside-decision.json`：最近一次完整局外决策；
- `latest-outside-sample.json`：最近一次决策、策略和所选动作；
- `latest-outside-result.json`：该动作的最近执行结果。

同时启用 `--capture-history` 后，还会写入：

- `outside-decision-*.json`：不可变的单步样本；
- `outside-trajectory.jsonl`：便于流式读取、跨局和跨进程追加的样本集合；
- `outside-result-*.json` 与 `outside-results.jsonl`：可关联的动作执行结果。

每条 `OutsideCombatDecisionSample` 有独立的 `schema_version`，其版本与内嵌的
`OutsideCombatDecisionPoint` 版本分开演进。样本使用 `episode_id`、`decision_index`、
状态指纹和 `request_id` 关联。
读取 JSONL 时应按 `episode_id` 分组，而不是把整个文件视为同一条轨迹。
`OutsideCombatExecutionResult` 再用同一组 `episode_id`、`decision_index`、`request_id`
标记 `observed_transition`、`applied`、`cancelled`、`failed` 或 `timed_out`。普通 Godot
控件只能确认输入后观察到了不同状态，原生商店事务则能明确返回成功或取消。

正常运行时，每个 `request_id` 只写入一条终态结果；强制退出、进程崩溃或操作系统直接终止进程时，结果行可能缺失。训练拼接应以决策样本为左表，按 `request_id` 左连接 `outside-results.jsonl`；只把 `observed_transition` 和 `applied` 视为成功，缺失结果以及 `cancelled`、`failed`、`timed_out` 都应过滤或单独分析。
它可以直接用于 first-legal 模仿数据；强化学习所需的终局结果和 reward 将在接入局外无头推进器后作为独立结果事件追加，不会把某一种 reward 定义固化进观察协议。

## 版本约束

- 协议结构发生不兼容变化时递增对应 `CurrentSchemaVersion`；
- `OutsideCombatDecisionSample`、`OutsideCombatDecisionPoint` 和
  `OutsideCombatExecutionResult` 分别维护自己的 `schema_version`；
- 仅改变策略实现不修改 schema；
- `state_fingerprint` 对 Build、观察和有序合法动作求 SHA-256，不包含时间戳、episode ID 或 decision index；
- 新策略不得接收 Mod 的原生节点绑定。

无游戏协议测试：

```bash
dotnet run --project smoke/SlayTheModel.Outside.Smoke -c Release
```

完整终端测试：

```bash
./scripts/macos.sh --action test
```
