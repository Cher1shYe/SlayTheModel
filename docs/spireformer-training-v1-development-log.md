# SpireFormer 多规模训练版开发日志

日期：2026-09-24  
状态：离线训练栈完成；live/headless 原始数据采集尚未开始

## 1. 本次交付

第一版模型核心已经扩展成可以实际启动训练的工程，而不仅是几个网络层：

- Tiny / Small / Medium / Large 四档架构；
- BF16 autocast 与纯 BF16 推理；
- FP32 master weight + AdamW；
- warmup + cosine scheduler；
- 梯度累积、尾批修正、梯度裁剪；
- Set/Decision Transformer activation checkpointing；
- 单卡与 `torchrun` DDP；
- train/eval 指标聚合，DDP 日志执行跨 rank 加权归并；
- 原子 checkpoint、resume、manifest 兼容检查和 RNG 恢复；
- 安全、版本化、可并行读取的 tensor shard；
- `spireformer train` / `python -m spireformer train` 命令行。
- 无需数据集的 `spireformer smoke`，用于在目标 GPU 验证 BF16 推理或单步反向、数值有限性与峰值显存。

模型仍然是随机初始化，不包含任何预训练权重。

## 2. 四档模型

基准输入宽度为 entity 48、action 32、`max_timestep=4096`：

| 档位 | 精确参数量 | hidden | trajectory layers | heads |
|---|---:|---:|---:|---:|
| Tiny | 2,882,818 | 128 | 4 | 4 |
| Small | 100,801,538 | 768 | 6 | 12 |
| Medium | 707,891,714 | 1536 | 17 | 24 |
| Large | 2,033,487,362 | 2304 | 24 | 36 |

参数量由真实模型在 PyTorch meta device 上计算，不维护一份容易和代码漂移的手算公式，也不会为 Large 分配真实权重。

## 3. BF16 的具体实现

训练默认使用 BF16 autocast，但不把所有东西粗暴转换成 BF16：

- Attention、Linear 和主要激活：BF16；
- 参数主副本、optimizer states：FP32；
- policy log-softmax、entropy 与 value reduction：显式 FP32；
- mask：bool；timestep、domain 与 action index：int64；
- BF16 不使用 GradScaler。

集成时发现 ISAB 的第一段 attention 在 autocast 后输出 BF16，而下一段仍收到 FP32 原始 query；原先严格的同 dtype 检查会错误拒绝合法的 autocast 图。现在只在 autocast 已启用时允许该中间混合，并保证投影后的 Q/K/V 统一为 BF16。完整模型 BF16 forward/backward 已加入回归测试。

纯推理可以把参数和浮点 batch 都转成 BF16。2.033B Large 的 BF16 权重约 3.79 GiB，但这不等于训练只需要 3.79 GiB。

## 4. 显存边界

标准 FP32 master + FP32 gradient + 两份 Adam moment 的静态下限约为 16 bytes/parameter，尚未计算激活、临时 attention tensor、DDP bucket、checkpoint 保存/恢复峰值和 CUDA allocator：

| 档位 | BF16 权重 | FP32 Adam 训练静态下限 |
|---|---:|---:|
| Tiny | 0.005 GiB | 0.043 GiB |
| Small | 0.188 GiB | 1.50 GiB |
| Medium | 1.32 GiB | 10.55 GiB |
| Large | 3.79 GiB | 30.30 GiB |

因此 Large 虽然是有效且可实例化的模型配置，但使用当前稳定训练语义时不能宣称单张 5090 可以直接完成 full training。Activation checkpointing 只减少激活，不减少参数、gradient 和 optimizer state。Large 的正式训练需要 FSDP/ZeRO 或 optimizer/parameter offload；当前 CLI 的 DDP 会在每张卡复制全部状态。

## 5. Tensor dataset

训练缓存采用：

```text
manifest.json
shard-<publication-id>-000000.pt
shard-<publication-id>-000001.pt
...
```

关键特性：

- packed tensor + offsets 表示变长 trajectory/entity/action；
- `torch.load(weights_only=True)`，不反序列化任意 Python 对象；
- shard 与 manifest 都原子发布；
- manifest 记录 tensorizer、词表、reward、no-SL 和 feature dtype；
- 可选 size/SHA-256 验证；
- distributed rank × DataLoader worker 确定性无重复分片；
- 缺失 value 和 soft teacher 分别有显式 mask；
- fingerprint、action ID、episode ID 不进入 tensor feature。

这只是 raw 数据的派生缓存。格式细节见 `model/spireformer/docs/tensor-shard-format-v1.md`。

## 6. Checkpoint 一致性

每个 checkpoint 保存：

- model / optimizer / scheduler state；
- global step 与 trainer counters；
- `SpireFormerManifest` 及其 digest；
- 每个 rank 的 Python、Torch CPU、CUDA/MPS RNG 与数据游标；
- preset、训练配置、loss、数据 manifest、batch/worker 与 world size resume contract。

checkpoint 使用同目录临时文件、flush/fsync 和 `os.replace` 原子提交，并固定 `weights_only=True` 加载。恢复时先把 payload 载入 CPU，避免整份 checkpoint 先额外驻留 GPU。数据、tensorizer、vocabulary、reward、训练超参数、world size 或游标语义不同，即使参数 shape 碰巧相同也拒绝 resume；运行配置只在校验成功后更新。

DDP 的 shard 所有权先按 rank 固定，再只在本 rank 内按 epoch shuffle，最后分给 DataLoader worker，因此某个 rank 较早进入下一 epoch 时也不会读取仍属于其他 rank 的 shard。梯度累积期间仅在边界 microbatch 同步梯度，避免重复 all-reduce。

## 7. 数据采集阶段的固定顺序

本次只完成训练 tensor 缓存，没有提前把 collector 塞进模型工程。下一阶段按以下顺序进行：

1. 审核并冻结 `docs/spireformer-training-data-v1-plan.md` 的 raw JSONL 事件；
2. 在真实游戏游玩中实现 live collector，验证 decision → execution → reward → terminal 关联；
3. 完成 golden raw JSONL → tensorizer → shard；
4. 最后将同一个 collector/tensorizer 接到 headless runner。

headless 与 live 必须生成同构数据。headless 不能另建一套“更方便但信息边界不同”的训练格式。

## 8. 当前验证

当前自动化结果为 **83 tests passed**。验证覆盖：Set 置换语义、时序因果性、动态动作、hard/soft loss、BF16、activation checkpointing、四档精确计数、训练累积与精确 resume、DDP `no_sync`/全局指标语义、原子 checkpoint、tensor shard round-trip/rank-worker 分片、CLI 单步训练，以及 smoke 的 BF16 inference/train 与失败退出语义。此外，`mypy`、`black --check`、`compileall` 与 `git diff --check` 均通过。

当前 macOS 沙箱不允许 `torchrun` 建立本地 rendezvous，因此真实多进程与 CUDA/5090 尚未在这台机器上实测；这里不会把 mock DDP 或 CPU BF16 测试写成多卡/5090 性能结论。
