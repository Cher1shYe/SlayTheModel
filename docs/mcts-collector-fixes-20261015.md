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
