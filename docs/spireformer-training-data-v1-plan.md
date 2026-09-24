# SpireFormer 训练数据 v1 规划

日期：2026-09-24  
状态：第二阶段的数据契约草案；采集器尚未实现

## 1. 实施顺序

后续严格按同一条数据链推进：

1. 固定原始轨迹事件格式与版本规则；
2. 在正常启动的游戏中实现 live collector，先验证数据完整性；
3. 用 live/golden 原始事件验证离线 tensorizer，并生成训练 shard；
4. 最后用同一 writer 接入 headless runner，不另外发明一种格式；
5. shard 只做可重建缓存，原始 JSONL 永远是 source of truth。

这样 headless 只替换“状态从哪里产生”，不会同时重写观察、动作、reward 和训练格式。

## 2. 文件布局

```text
dataset-root/
  dataset-manifest.json
  episodes/
    <episode-id>.jsonl
  tensors/
    <tensorizer-version>-<vocab-hash>-<reward-version>/
      manifest.json
      shard-<publication-id>-000000.pt
      shard-<publication-id>-000001.pt
```

`episodes/*.jsonl` 是协议级原始记录。`tensors/` 是 PyTorch 训练缓存；其 v1 实现和精确字段见 `model/spireformer/docs/tensor-shard-format-v1.md`。

## 3. JSONL 事件公共头

每一行是独立 JSON object，并具有：

```json
{
  "schema_version": 1,
  "event_type": "decision",
  "episode_id": "uuid",
  "global_step": 42,
  "recorded_at_utc": "2026-09-24T12:34:56.000Z",
  "source": "live",
  "build": {
    "game_version": "...",
    "assembly_sha256": "...",
    "mod_revision": "..."
  }
}
```

- `source` 只能是 `live` 或 `headless`；它属于数据审计字段，不作为模型特征。
- `global_step` 在同一 episode 内严格递增，局内和局外共用一条时间轴。
- 游戏 seed 可以放在受限 metadata 中用于复现，但不能进入 policy observation 或 tensor feature。
- 写盘采用 append + flush；崩溃后的半局保留，但默认不产生 value label。

## 4. 事件类型

### 4.1 `episode_started`

记录角色、协议/build 版本、采集策略、是否 no-SL，以及可选的复现 metadata。它不包含第一步观察。

### 4.2 `decision`

一条真正交给策略的决策边界：

```json
{
  "event_type": "decision",
  "decision_id": "uuid",
  "global_step": 42,
  "domain": "combat",
  "state_fingerprint": "sha256",
  "observation": {},
  "legal_actions": [],
  "policy": {
    "policy_id": "mcts",
    "model_revision": null,
    "selected_action_index": 3,
    "selected_action_id": "optional-stable-id",
    "logits": null,
    "mcts_visit_counts": [12, 4, 91, 140]
  }
}
```

- `observation` 与 `legal_actions` 必须来自过滤后的 `CombatDecisionPoint` 或 `OutsideCombatDecisionPoint`，不能直接序列化 Godot node、checkpoint、隐藏 RNG 或 `NativeMctsRequest`。
- `selected_action_index` 永远以该行的 `legal_actions` 为基准。
- outside 同时保存现有 `ActionId`；combat 需要增加稳定 descriptor digest。
- `state_fingerprint`、action ID/digest、ordinal 是关联与校验信息，tensorizer 默认不把它们当特征。
- MCTS 训练数据应保存根节点所有合法动作的 visit counts，而不仅是最终动作。

### 4.3 `execution_result`

记录动作有没有真正生效，至少包含：

- `decision_id / global_step / expected_state_fingerprint`；
- action index 与冗余 ID/digest；
- `status = observed_transition | applied | cancelled | failed | timed_out | stale`；
- 可选诊断信息与 next-state fingerprint。

只有 `observed_transition` 或 `applied` 可以成为行为克隆标签。失败、取消、超时和 stale 响应必须保留用于 debug，但不能静默标成训练动作。现有 `OutsideCombatExecutionResult` 已具有大部分语义；combat 需要补同等级结果协议。

### 4.4 `reward`

Reward 与观察分开存，允许以后在不重新跑游戏的情况下重算训练目标：

```json
{
  "event_type": "reward",
  "global_step": 42,
  "reward_version": "whole-run-v1",
  "components": {
    "terminal": 0.0,
    "hp_delta": -0.02,
    "gold_delta": 0.0,
    "progress": 0.01
  }
}
```

训练时使用哪个组合由 `reward_version` 决定。禁止只写一个无法追溯来源的最终浮点数。

### 4.5 `episode_finished`

记录胜负、到达位置、最终生命/金币/牌组摘要、终止原因与完整性状态。正常结束的 episode 才生成可靠整局 return；崩溃或人工中止默认 `value_target_valid=false`，但其中成功执行的动作仍可用于 policy imitation。

## 5. no-SL 信息边界

允许模型看到玩家在正常 no-SL 游玩时可知的完整集合，但不允许利用存档或模拟器额外泄露的信息：

- 抽牌堆、弃牌堆编码为集合，不编码内部顺序；
- 不输入未来随机数、地图未揭示结果、隐藏敌方 roll；
- seed、checkpoint、replay prefix 只允许作为复现 metadata；
- 同名卡仍通过当前状态内实体引用区分，但本地递增 ID 本身不当作可学习数值；
- 训练、live play 和 headless 必须经过同一个 tensorizer 与 feature manifest。

## 6. 从事件到训练样本

离线 assembler 按 `episode_id + global_step + decision_id` 关联：

1. 读取 decision；
2. 找到成功 execution result；
3. 保留 chosen action 或 MCTS visits 作为 policy target；
4. 用后续 reward/terminal 计算 RTG 与 value target；
5. 按 episode 生成整局 `Trajectory`；
6. 使用固定 `tensorizer_version + vocabulary_hash + reward_version` 写 tensor shard。

任何缺口、重复 step、action 对不上 legal list、fingerprint 不一致或非有限 reward 都应隔离到 rejected 数据集并给出原因，不能“尽量猜一个值”。

## 7. live 与 headless 的共同验收

- 同一 decision fixture 经两条采集路径得到字节级等价的协议 observation/action；
- episode/global step 连续，局内转局外时不归零；
- 所有已标注动作均有成功 execution result；
- 每个 soft policy 长度等于合法动作数且和为 1；
- tensorizer 对集合重排保持输出语义一致；
- collector 崩溃不会破坏已 flush 的 JSONL；
- 未完成 episode 不会错误地产生终局 value 标签；
- manifest 能精确定位游戏 build、协议、tensorizer、词表和 reward 版本。

该契约确认后，先实现 live collector；只有 live 数据通过完整性审计，才将同一采集接口接入 headless 全局模拟器。
