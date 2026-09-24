# SpireFormer v0.1

SpireFormer 是 SlayTheModel 的第一版统一神经决策器。它把两种结构组合在一起：

- **Set Transformer** 编码同一状态内无顺序的实体集合，例如卡牌、怪物、遗物、药水和地图候选；
- **Decision Transformer** 编码跨局内、局外决策的因果历史；
- **动态合法动作头** 只对当前协议给出的合法动作打分，不建立固定大小的“所有动作词表”。

局内与局外不是两个独立策略。它们共享集合编码器、时序主干、动作评分器和价值目标，只通过 `domain_ids` 与不同的实体/动作特征区分。这样“现在喝药”和“把药留给后面的精英”等跨层权衡可以在同一个轨迹目标下学习。

## 模型规模

下表使用 `entity_feature_dim=48`、`action_feature_dim=32` 与 `max_timestep=4096` 精确计数。计数通过 PyTorch meta device 完成，不会为了查看 Large 大小而真的申请 2B 参数内存。

| Preset | 参数量 | hidden | 时序层 | heads | 用途 |
|---|---:|---:|---:|---:|---|
| `tiny` | 2,882,818 | 128 | 4 | 4 | 验证架构、数据和训练闭环 |
| `small` | 100,801,538 | 768 | 6 | 12 | 第一档正式训练规模 |
| `medium` | 707,891,714 | 1536 | 17 | 24 | 大规模离线训练 |
| `large` | 2,033,487,362 | 2304 | 24 | 36 | 分布式高容量实验 |

```bash
spireformer presets
spireformer presets --json
```

## 当前边界

v0.1 已包含完整的离线训练栈：BF16、梯度累积/裁剪、warmup+cosine、activation checkpointing、DDP、原子 checkpoint/resume、指标日志以及版本化 tensor shard。它还没有把 `--card-play-mode spireformer` 接进 Godot 模组。当前 C# 协议仍缺少部分高质量特征（例如敌人 intent、完整卡牌动态属性）与整局 reward/episode 记录；在没有可用 checkpoint 和稳定 tensorizer 时开放启动参数会制造一个表面可选、实际不可工作的模式。

模型刻意遵守 no-SL 信息边界：一个状态内不为抽牌堆或弃牌堆加入位置编码，也不接收隐藏 RNG、checkpoint、回放前缀或 `state_fingerprint` 作为特征。`state_fingerprint` 以后只用于 C# 执行动作前的状态一致性校验。

## 安装与测试

建议先按 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/) 安装与你的系统/CUDA 匹配的 PyTorch。5090 机器尤其不要随意固定旧 CUDA wheel。然后运行：

```bash
cd model/spireformer
python -m pip install -e '.[test]'
pytest
```

本模块只依赖 PyTorch；没有沿用旧版 Decision Transformer 的 Hugging Face GPT-2 依赖。

## GPU smoke test

smoke test 不需要游戏或训练数据，用合成的合法 batch 检查指定 preset 是否能在当前设备完成计算。建议在 5090 上先确认 CUDA/BF16，再按 Tiny → Small → Medium → Large 的顺序执行：

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0), torch.cuda.is_bf16_supported())"

spireformer smoke --preset tiny --device cuda --precision bf16 --mode train
spireformer smoke --preset small --device cuda --precision bf16 --mode train
spireformer smoke --preset medium --device cuda --precision bf16 --mode train
spireformer smoke --preset large --device cuda --precision bf16 --mode inference
```

`inference` 使用推理模式并测试 BF16 参数存储；`train` 保留 FP32 master parameters、使用 BF16 autocast，并完成一次 forward、policy/value loss 和 backward，但不创建 AdamW 状态。成功结果是一个 JSON object，其中 `finite=true`，并报告参数量、输出 shape、耗时与 CUDA 峰值显存。输入规模可用 `--batch-size`、`--steps`、`--entities` 和 `--actions` 调整。

这个命令只证明模型实现、精度路径和计算图可以执行，不衡量策略强度，也不证明该 preset 可以在相同显存下完成带 optimizer 的正式训练。Large 的完整训练仍需要 FSDP/ZeRO 或 offload。

## 命令行训练

训练输入必须是版本化 tensor dataset，格式见 [Tensor Shard Format v1](docs/tensor-shard-format-v1.md)。先执行 `--dry-run` 可以验证数据 manifest、模型尺寸和训练配置；它只构建 meta 模型对象用于精确计数，不分配真实参数存储：

```bash
spireformer train \
  --dataset artifacts/train-v1 \
  --output runs/spireformer-small \
  --preset small \
  --precision bf16 \
  --total-steps 100000 \
  --batch-size 4 \
  --gradient-accumulation-steps 8 \
  --dry-run
```

确认后去掉 `--dry-run`。恢复训练使用同一个模型与数据契约：

```bash
spireformer train \
  --dataset artifacts/train-v1 \
  --output runs/spireformer-small \
  --preset small \
  --precision bf16 \
  --total-steps 100000 \
  --batch-size 4 \
  --gradient-accumulation-steps 8 \
  --resume runs/spireformer-small/checkpoint-latest.pt
```

resume 会严格校验模型、数据集、reward、词表、loss、batch/accumulation、worker 数、world size、设备类型和训练配置，并恢复各 rank 的 RNG 与数据游标；不匹配时会在改写运行配置前拒绝启动。`run-config.json` 固定上述契约，`metrics.jsonl` 记录训练指标，`checkpoint-latest.pt` 包含模型、优化器、scheduler、trainer step、manifest 和续训状态。

多 GPU 可以直接使用 `torchrun`。tensor shards 会按 rank 与 DataLoader worker 无重复分配：

```bash
torchrun --standalone --nproc-per-node=4 -m spireformer train \
  --dataset artifacts/train-v1 \
  --output runs/spireformer-medium \
  --preset medium \
  --precision bf16 \
  --activation-checkpointing
```

当前内置多卡策略是 DDP，会在每张卡复制完整参数和 AdamW 状态。训练器在梯度累积的非边界 microbatch 使用 `no_sync()`，日志指标跨 rank 加权聚合；shard 先固定归属 rank，再在 rank 内按 epoch shuffle，快慢 rank 不会跨轮读到同一 shard。它适合 Tiny/Small 以及显存足够的 Medium 实验；2B Large 的完整训练需要 FSDP/ZeRO 等参数与优化器分片，不能把“配置能够生成”误解为“单张 5090 可以直接训练”。

### BF16 语义

默认训练模式是 BF16 autocast：矩阵乘法、Attention 和激活采用 BF16，参数主副本、AdamW 状态与 policy/value loss 保持 FP32。BF16 不使用 FP16 的 loss scaler。模型也支持纯 BF16 权重推理：

```python
import torch

from spireformer import PrecisionMode, cast_model_for_inference

model = cast_model_for_inference(
    model,
    mode=PrecisionMode.BF16,
    device="cuda",
)
batch = batch.to("cuda", dtype=torch.bfloat16)
```

Medium/Large 默认启用 activation checkpointing；Tiny/Small 可通过 `--activation-checkpointing` 手动开启。

## 最小训练示例

```python
import torch

from spireformer import (
    DecisionDomain,
    SpireFormer,
    SpireFormerConfig,
    Trajectory,
    TrajectoryStep,
    collate_trajectories,
    compute_spireformer_loss,
)

entity_dim = 48
action_dim = 32
trajectory = Trajectory.from_sequence([
    TrajectoryStep(
        entity_features=torch.randn(12, entity_dim),
        legal_action_features=torch.randn(5, action_dim),
        selected_action_index=2,
        return_to_go=0.8,
        value_target=0.7,
        timestep=0,
        domain=DecisionDomain.COMBAT,
    ),
    TrajectoryStep(
        entity_features=torch.randn(20, entity_dim),
        legal_action_features=torch.randn(3, action_dim),
        selected_action_index=0,
        return_to_go=0.7,
        value_target=0.6,
        timestep=1,
        domain=DecisionDomain.OUTSIDE_COMBAT,
    ),
])

batch, targets = collate_trajectories(
    [trajectory],
    entity_feature_dim=entity_dim,
    action_feature_dim=action_dim,
)
model = SpireFormer(SpireFormerConfig(
    entity_feature_dim=entity_dim,
    action_feature_dim=action_dim,
))
output = model(batch)
loss = compute_spireformer_loss(output, batch, targets)
loss.total.backward()
```

## 张量协议

`SpireFormerBatch` 同时 padding 三个动态维度：

| 维度 | 含义 |
|---|---|
| `T` | 一局游戏中的决策历史 |
| `N` | 每个状态可见的实体集合 |
| `A` | 每个状态当前合法的动作集合 |

公开 batch 的 `entity_mask`、`legal_action_mask`、`step_mask` 都使用 `True = 有效`。只有 Set Transformer 内部的 `padding_mask` 跟随 PyTorch，使用 `True = padding`。字段名和转换位置是有意固定的，避免局内/局外数据合并后出现反向 mask 的静默错误。

`previous_action_features[:, t]` 表示导致当前状态的 `a_(t-1)`。时序核心将它放入上一组 `(R, S, A)` 的 A 槽，因此 `S_t` 能看见上一动作，但看不见当前待预测动作。

## 训练目标

- 行为克隆数据：使用执行成功动作的 one-hot 目标；
- MCTS 蒸馏：使用根节点 visit count 归一化后的软目标；
- value：只训练带有效整局结果的 timestep；局外 first-legal 但没有终局结果的样本必须把 `value_target_mask` 设为 `False`；
- padding、执行失败、取消或 stale-state 动作不参与 loss。

模型输出 `policy_logits[B,T,A]` 和 `state_value[B,T]`。非法动作的 logit 固定为 `-inf`；在线执行仍应只返回动作槽位，由 C# 使用原始决策对象完成动作 ID 与状态指纹复核。

设计与实现记录见 [SpireFormer v0.1 开发日志](../../docs/spireformer-v0.1-development-log.md)。下一阶段的 raw JSONL、live collector 与 headless collector 顺序见 [训练数据 v1 规划](../../docs/spireformer-training-data-v1-plan.md)。
