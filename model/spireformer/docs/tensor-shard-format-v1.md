# SpireFormer Tensor Shard Format v1

日期：2026-09-24

## 定位

Tensor shard 是面向高吞吐训练的**派生数据**，不是长期保存的原始事实。
后续游戏内采集器应先写入版本化 raw JSONL；JSONL 保存可审计、可重新张量化的
完整决策记录，tensorizer 再把它物化为本文定义的 `.pt` shard。

这一分层非常重要：模型特征会持续演进，而原始轨迹不能因为一次特征设计修改就失效。

```text
游戏 / headless runner
        │
        ▼
raw JSONL（未来的 source of truth）
        │  tensorizer_version + vocabulary_hash + reward_version
        ▼
manifest.json + shard-*.pt（可重建的训练缓存）
        │
        ▼
TensorShardDataset → collate_trajectories → SpireFormerBatch/Targets
```

`state_fingerprint`、`action_id`、episode ID 等字段以后会存在 raw JSONL 中，用于
校验、回放、去重和追踪；它们不是游戏语义，不得编码进模型输入。tensor shard v1
因此完全不保存这些标识符。监督动作在每一步仅表示为合法动作列表中的局部 ordinal。

## 目录布局

```text
dataset/
├── manifest.json
├── shard-<publication>-000000.pt
├── shard-<publication>-000001.pt
└── ...
```

写入器先用同目录临时文件写完并 `fsync`，再通过原子 rename 发布每个 shard；只有
全部 shard 写完后才原子发布 `manifest.json`。因此读取端以 manifest 是否存在作为
“数据集已经完成”的判据。生产中断可能遗留不可见的 shard，但不会把半成品伪装成
完整数据集。每次 writer 使用唯一的 `<publication>` 前缀，因此 `overwrite=True` 时
也不会提前覆盖旧 manifest 正在引用的 shard；最后一次 manifest rename 才切换读者
所见的数据版本。旧 shard 可由单独的垃圾回收任务在确认无人读取后清理。

## Manifest v1

`manifest.json` 包含：

- `schema_version`：固定为 `1`；
- `dataset_id`、`created_at_utc`；
- `tensorizer_version`：原始协议到数值特征的版本；
- `vocabulary_hash`：卡牌、遗物、事件等词表的内容哈希；
- `reward_version`：整局回报定义版本；
- `no_save_load_information`：v1 必须为 `true`；
- `entity_feature_dim`、`action_feature_dim`；
- `feature_dtype`：`float16`、`bfloat16`、`float32` 或 `float64`；
- 全局 trajectory/step 数量；
- 每个 shard 的文件名、trajectory 数、step 数、字节数和 SHA-256。

读取器对字段集合、类型、计数、文件名和兼容版本做严格校验。可用
`verify_hashes=True` 在读取时额外验证文件大小与 SHA-256；大规模训练中可以在数据
发布阶段校验一次，训练热路径关闭重复哈希。

## `.pt` shard v1

文件必须由纯 Python `dict`、标量以及 `torch.Tensor` 组成，不序列化自定义 Python
对象。读取固定调用：

```python
torch.load(path, map_location="cpu", weights_only=True)
```

所有变长集合采用 packed tensor + offset：

| 字段 | dtype / shape | 含义 |
| --- | --- | --- |
| `trajectory_step_offsets` | int64 `[K+1]` | 第 `k` 条轨迹的 step 范围 |
| `entity_offsets` | int64 `[S+1]` | 第 `s` 步的 entity 范围 |
| `action_offsets` | int64 `[S+1]` | 第 `s` 步的合法动作范围 |
| `entity_features` | float `[sum(N), Fe]` | packed entity set |
| `legal_action_features` | float `[sum(A), Fa]` | packed 动态合法动作集 |
| `selected_action_indices` | int64 `[S]` | 每步动作集内的局部 ordinal |
| `returns_to_go` | float `[S]` | Decision Transformer 条件 |
| `timesteps` | int64 `[S]` | 整局决策序号 |
| `domain_ids` | int64 `[S]` | `0=combat`，`1=outside-combat` |
| `value_targets` | float `[S]` | 可选价值标签；缺失位置存零 |
| `value_target_mask` | bool `[S]` | 价值标签是否存在 |
| `teacher_policy` | float `[sum(A)]` | 可选 MCTS/teacher soft policy |
| `teacher_policy_mask` | bool `[S]` | soft policy 是否存在 |

其中 `K` 是 shard 内轨迹数，`S` 是总决策步数。每条轨迹、每个 entity set 和每个
合法动作集都必须非空；offset 必须从 0 开始、严格递增，并精确落到 packed tensor
末尾。所有浮点值必须有限；soft policy 非负且在启用的行上和为 1。

缺少 teacher policy 的步骤不会在 shard 中伪造标签。恢复成 `Trajectory` 后，现有
`collate_trajectories` 会在一个 batch 需要 soft targets 时，把这些步骤转换成所选
动作的 one-hot 监督。

## 公开 API

```python
from spireformer.data import (
    TensorShardDataset,
    TensorShardWriter,
    create_trajectory_dataloader,
    write_tensor_dataset,
)
```

流式写入：

```python
writer = TensorShardWriter(
    "artifacts/train-v1",
    entity_feature_dim=48,
    action_feature_dim=32,
    tensorizer_version="sts2-v1",
    vocabulary_hash="...",
    reward_version="whole-run-v1",
    trajectories_per_shard=1024,
)
for trajectory in trajectories:
    writer.add(trajectory)
manifest = writer.close()
```

读取与组 batch：

```python
dataset = TensorShardDataset(
    "artifacts/train-v1",
    shuffle_shards=True,
    shuffle_seed=20260924,
)
dataset.set_epoch(epoch)
dataloader = create_trajectory_dataloader(
    dataset,
    batch_size=64,
    num_workers=8,
    pin_memory=True,
    persistent_workers=True,
)
```

`TensorShardDataset` 先按 manifest 中的固定顺序给 distributed rank 做 stride 分区，
再仅在每个 rank 自己的分区内按 epoch 做确定性 shuffle，最后把该 rank 的 shard 按
DataLoader worker 做 stride 分片。这样 rank 对 shard 的所有权不会随 epoch 改变：即使
某个 rank 已进入下一 epoch、另一个 rank 仍在消费上一 epoch，也不会跨 rank 重复读取
同一个 shard。任意同一 rank 内的 worker 之间同样不会重复。单 rank 时，这一顺序仍
等价于“全量 shard 按 epoch shuffle，再分给 workers”。

## v1 边界

- shard shuffle 只打乱 shard 顺序，不在 shard 内随机打乱 trajectory；如训练需要更强
  的样本混洗，应在 tensorizer 阶段随机分桶，或在后续版本增加有界 shuffle buffer；
- tensor shard 不替代 raw JSONL，也不承担协议迁移和回放诊断；
- v1 不允许 SL 信息，不编码牌堆顺序和未来 RNG；
- 修改特征、词表或奖励定义时必须更新对应版本/哈希并重新物化 shard，不能静默复用。
