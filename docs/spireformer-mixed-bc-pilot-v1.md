# SpireFormer 混合 BC 首轮试训

更新时间：2026-10-14

## 数据

`scripts/assemble-mixed-bc-dataset.py` 在张量化之前合并两类严格 no-SL 数据，
并且只用训练 split 拟合一份共享特征词表：

- Spire Codex：4,603 个安全局外步骤，加 93 个原生重放核验的战斗步骤；
- 本项目 collector：6 局铁甲日志的 4,021 个安全步骤；
- 新上传的 `a09f25fa...` 和 `d9c27368...` 因
  `information_mode=unknown`、`no_sl_expected=false`，没有进入训练数据。

人类日志按完整 episode 固定划分：

- train：`433d5532...`、`ec731392...`、`2085af58...`、`2d9fc925...`；
- val：`1ddd1912...`；
- test：`32a38225...`。

Spire Codex 保留原有按角色分层的确定性整局划分。最终数据集位于忽略目录
`artifacts/spireformer/mixed-bc-v1/`：

| split | episode | 步骤 | 战斗 | 局外 | 人类 | Spire Codex |
|---|---:|---:|---:|---:|---:|---:|
| train | 130 | 6,800 | 2,168 | 4,632 | 3,012 | 3,788 |
| val | 18 | 1,278 | 601 | 677 | 781 | 497 |
| test | 18 | 639 | 181 | 458 | 228 | 411 |
| 合计 | 166 | 8,717 | 2,950 | 5,767 | 4,021 | 4,696 |

数据集 ID 为 `2ed66b6b7ca90cb3e4e09884d23a2f43`，词表哈希为
`018124302d985371ca7549f754080bf80d1085bedd0f6c108718c78ab8838dff`，
entity/action 宽度为 609/570。12 个 FP16 shard 共约 1.2 GB，均已按 manifest
SHA-256 完整重读；166 个 episode ID 和源文件哈希在三个 split 间无重叠。

复跑命令：

```bash
python scripts/assemble-mixed-bc-dataset.py \
  --output artifacts/spireformer/mixed-bc-v1 \
  --human-train-episode 433d5532920444a1afac0716251e12c4 \
  --human-train-episode ec73139250034d688b68013581a0a640 \
  --human-train-episode 2085af58548044b9b192db449a6dbbf0 \
  --human-train-episode 2d9fc925402f440eaba2c30e5c214966 \
  --human-val-episode 1ddd1912ef634cbeb9d331f52b79cf24 \
  --human-test-episode 32a3822509ec4c9fa8d00017103daee6
```

## Tiny 试训

首个有效 checkpoint 使用共享词表后的 3,200,387 参数 Tiny，在 CPU/FP32 上训练
3,000 个优化步骤。配置为 batch size 1、300 步 warmup、峰值学习率 `3e-4`、
AdamW weight decay 0.1、policy weight 1、entropy weight 0.01、value weight 0。
RTG 输入恒为零，不训练 value head。

```bash
spireformer train \
  --dataset artifacts/spireformer/mixed-bc-v1/train \
  --output artifacts/train-runs/tiny-mixed-bc-v1-3000steps \
  --preset tiny --device cpu --precision fp32 \
  --total-steps 3000 --warmup-steps 300 \
  --batch-size 1 --value-weight 0 --verify-data
```

checkpoint 和评估 JSON 位于忽略目录
`artifacts/train-runs/tiny-mixed-bc-v1-3000steps/`。

## 整局隔离离线评估

评估使用零 RTG，并由 assembly report 验证训练 episode 与 held-out episode 没有
ID 或源文件哈希重叠。top-1 是在每个记录状态及其合法动作集合上预测记录动作；
历史动作仍来自记录轨迹，因此这是 teacher-forced 行为克隆评估，不是模型自主跑局。

| split / domain | 模型 top-1 | 首合法动作 | 均匀随机期望 | 模型 NLL | 均匀 NLL |
|---|---:|---:|---:|---:|---:|
| val 全部 | 48.04% | 32.16% | 28.21% | 1.217 | 1.560 |
| val 战斗 | 41.60% | 19.30% | 15.18% | 1.503 | 2.056 |
| val 局外 | 53.77% | 43.57% | 39.78% | 0.964 | 1.121 |
| test 全部 | 55.40% | 44.60% | 37.79% | 0.969 | 1.146 |
| test 战斗 | 56.91% | 33.70% | 23.97% | 1.276 | 1.622 |
| test 局外 | 54.80% | 48.91% | 43.25% | 0.848 | 0.958 |

test 中排除只有一个合法动作的 598 步后，模型 top-1 为 52.34%，首合法动作
40.80%，均匀随机期望 33.52%。这说明模型已经学习到超出动作顺序和合法动作数量
的策略信号。

集合选择仍是首轮短板：val/test exact-set 分别为 22.22%/19.05%。当前数据也没有
独立 value target，所以这份 checkpoint 只能视为第一版 BC 策略验证。游戏内推理
和高速 runner 的自主闭环尚未接入，不能用这些离线指标推断真实胜率或自迭代能力。
另外，test 的 181 个战斗步骤中 167 个来自单局铁甲 collector、14 个来自 Spire
Codex 原生重放；当前战斗指标主要说明模型学到了这位玩家的铁甲动作分布，尚不能
证明五角色战斗泛化。
