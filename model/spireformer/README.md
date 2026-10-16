# SpireFormer v0.1

SpireFormer 是 SlayTheModel 的第一版统一神经决策器。它把两种结构组合在一起：

- **Set Transformer** 编码同一状态内无顺序的实体集合，例如卡牌、怪物、遗物、药水和地图候选；
- **Decision Transformer** 编码跨局内、局外决策的因果历史；
- **动态合法动作头** 只对当前协议给出的合法动作打分，不建立固定大小的“所有动作词表”。
- **集合选择头** 对多卡选择的可见候选牌逐张打分，并预测选择张数；一次选择仍是一个整局决策步。

局内与局外不是两个独立策略。它们共享集合编码器、时序主干、动作评分器和价值目标，只通过 `domain_ids` 与不同的实体/动作特征区分。这样“现在喝药”和“把药留给后面的精英”等跨层权衡可以在同一个轨迹目标下学习。

## 模型规模
下表使用 `entity_feature_dim=48`、`action_feature_dim=32` 与 `max_timestep=4096` 精确计数。计数通过 PyTorch meta device 完成，不会为了查看 Large 大小而真的申请 2B 参数内存。

| Preset | 参数量 | hidden | 时序层 | heads | 用途 |
|---|---:|---:|---:|---:|---|
| `tiny` | 2,916,099 | 128 | 4 | 4 | 验证架构、数据和训练闭环 |
| `small` | 101,984,259 | 768 | 6 | 12 | 第一档正式训练规模 |
| `medium` | 712,616,451 | 1536 | 17 | 24 | 大规模离线训练 |
| `large` | 2,044,113,411 | 2304 | 24 | 36 | 分布式高容量实验 |

```bash
spireformer presets
spireformer presets --json
```

## 当前边界

v0.1 已包含离线训练栈：BF16、梯度累积/裁剪、warmup+cosine、activation checkpointing、DDP、原子 checkpoint/resume、指标日志以及版本化 tensor shard。模型新增集合选择头；raw JSONL → shard 默认使用 `bc-only`，当前首版奖励为 `whole-run-act-v1`，历史 `whole-run-hp-safe-v1` / `whole-run-win-v1` 仍可显式选择。除原有混合 BC Tiny 外，当前已有一个用 3 胜 1 负分幕 RTG 训练 1,000 步的 Tiny 试验 checkpoint；它只证明离线条件训练链路可用。默认只监督可靠的人类动作；显式 `--allow-policy native-mcts` 可纳入来源及教师信息核验通过的新 MCTS 步骤，信息模式和整局审计门槛仍保留。`value_target` 仍缺失；游戏内 `spireformer` policy 尚未接入。

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

## 从人类 JSONL 到训练 shard

### Spire Codex 公开回放 BC

仓库根目录的 `scripts/convert-spire-codex-replays.py` 会先把本地保留的 166 份
严格回放重建成不含 seed、RNG、未来抽牌顺序、时间和原生实例 ID 的审计格式。
`scripts/assemble-spire-codex-dataset.py` 再读取其中 4,603 个安全局外 BC 步骤，
并可合并通过哈希校验的原生战斗重放报告：

```bash
python3 scripts/convert-spire-codex-replays.py
python3 scripts/assemble-spire-codex-dataset.py \
  --native-replays artifacts/reference/spire-codex/native-replay-pilot
```

组装器只用 train episode 拟合特征词表，并按角色、完整 episode 确定性划分
train/val/test。当前忽略目录 `artifacts/reference/spire-codex/tensor-bc-v3/` 包含
126 局 3,788 步训练、17 局 497 步验证和 17 局 411 步测试；三个 split 都覆盖
五个角色且 episode 不重叠。总计 4,696 步，其中 4,603 步来自安全局外选择，
93 步来自 7 场通过原生胜利校验的完整战斗：五角色各一场首战，以及铁甲样本
`a8d7ab6d08211e91` 顺序重放的首战和第二战。FP16 只用于约 881 MB 的磁盘缓存，
训练器和 evaluator 读取后提升为 FP32。`return_to_go` 全为零占位，`value_target`
全缺失，训练必须保持 `--value-weight 0`。

Spire Codex 战斗日志没有输入瞬间的完整合法动作集合；转换器目前标出 24,856 个
安全顺序重放候选，只有上述 93 步已经由原生 `v0.111.0` runner 在输入边界重新
投影 observation 和合法动作后进入 BC。结束回合日志状态属于点击后状态，训练时
只使用原生执行前投影。恢复段也全部保留在审计格式中，但在连续性得到独立证明前
不会进入 shard。第二战验证表明 RNG counter 相同不足以恢复随机流；必须从新局或
可信 checkpoint 顺序执行此前的战斗、奖励和局外选择。公开回放没有记录玩家解锁
状态，因此当前连续试点按记录指定原生 encounter model，不把外部地图遭遇选择
冒充为已验证。详细的筛选、
动作映射、集合选择和验证结果见
[Spire Codex 回放重建格式 v1](../../docs/spire-codex-conversion-v1.md)。

### 混合 BC 首轮试训

`scripts/assemble-mixed-bc-dataset.py` 会在张量化之前合并上述 Spire Codex 安全步骤
和明确选择的本项目 collector no-SL episode，并只用两个来源的 train split 共同
拟合词表。2026-10-14 的首轮数据共有 8,717 步：train 6,800、val 1,278、test
639；其中 4,021 步来自 6 局 collector，4,696 步来自 Spire Codex。所有 shard
哈希和 166 个 episode/source hash 的 split 隔离均已重读核验。

3,200,387 参数 Tiny 完成 3,000 步 CPU/FP32 BC 试训。整局隔离 test 的整体、战斗、
局外 top-1 分别为 55.40%、56.91%、54.80%，均超过首合法动作和均匀随机基线；
集合 exact-set 为 19.05%。这是使用记录历史动作的 teacher-forced 离线评估，不代表
原生跑局胜率。数据、命令、完整指标和当前边界见
[SpireFormer 混合 BC 首轮试训](../../docs/spireformer-mixed-bc-pilot-v1.md)。

### 本项目 collector journal

`assemble` 读取已发布的 `.jsonl`，校验逐行哈希链与动作/结果关联，用明确列出的 episode ID 按整局分出 train、val、test，并把缓存写入一个新的输出目录。下面的 BC-only 四局命令是**历史试验记录**：这些原始 JSONL 目前不在 `artifacts/human-dataset/episodes`，需先恢复对应源文件，才能从仓库根目录重跑。四局此前已分别通过只读药水槽位审计；不能据此推断其他历史局都安全。输出目录若已存在，命令会拒绝覆盖。下一节的两局 RTG 命令同样是**已作废的历史记录**。

```bash
python -m pip install -e './model/spireformer[test]'
spireformer assemble \
  --input artifacts/human-dataset/episodes \
  --output artifacts/tensor-v2/bc-demo-v3 \
  --train-episode ba8f9848c0804175b3c6e64f2fc03747 \
  --train-episode 148a980306c24c8aadda13cbc30f57b4 \
  --val-episode 42e3c58940b54a36908e32e28b9c893b \
  --test-episode bb42726c849b46068175a7ad7aeaf543 \
  --max-window-steps 64
```

输出包含 `train/`、`val/`、`test/` 的 shard/manifest，以及 `feature-spec.json` 和 `assembly-report.json`。报告列出各局的原始步骤、实际 BC 步骤、排除原因与集合选择标签数。只有 `information_regime=no_sl`、actor 为人工、提交动作与当时合法集对应，且原生结果为 `applied` 或 `observed_transition` 的步骤才进入 shard；后到的关联缺口会排除对应动作。缺口、回档或取消不会凭相邻事件被补成训练标签。当前 tensorizer 版本为 `collector-raw-bc-v3`，磁盘 shard 格式仍为 v2；它还对照同一步 observation 与 run context 的完整药水槽号和模型 ID，旧压缩槽号即使碰巧存在、却指向另一瓶药，也会被排除。使用其他旧局前仍应检查报告中的排除原因。源 JSONL 保持不变。

特征版本 `sts2-raw-features-v2` 用训练集拟合的有限语义词表和每个数值的“值 + 存在位”编码公开状态。它纳入手牌/牌堆集合、药水、遗物、能力、敌人意图、地图、已揭示的 Crystal Sphere 格子与集合候选；不读身份、seed、时间戳、原生对象 ID、状态指纹、未经核对的旧动态预览或本地化说明。实际特征宽度写在 `feature-spec.json`，因此训练模型的精确参数量可与上方以 48/32 参考维度计数的 preset 表稍有不同。

默认 `bc-only` 模式将必填的 `return_to_go` 设为常数 0；这个 0 只是条件输入占位。下文另说明纯通关与 HP shaping 的 RTG 模式。三种模式的 `value_target` 都缺失，训练时应指定 `--value-weight 0`。下面的旧示例还关闭熵正则，以便观察纯行为克隆指标。离线验证只能衡量对已记录人工动作的模仿，不能证明模型会独立打赢游戏。

```bash
spireformer train \
  --dataset artifacts/tensor-v2/bc-demo-v3/train \
  --output artifacts/runs/spireformer-bc-tiny-v3 \
  --preset tiny --device cpu --precision fp32 \
  --total-steps 20 --warmup-steps 2 \
  --batch-size 1 --checkpoint-every 20 --log-every 1 \
  --value-weight 0 --entropy-weight 0 --verify-data

spireformer evaluate \
  --checkpoint artifacts/runs/spireformer-bc-tiny-v3/checkpoint-latest.pt \
  --dataset artifacts/tensor-v2/bc-demo-v3/val \
  --device cpu --precision fp32 --verify-data
```

`evaluate` 默认把 return-to-go 输入置零，报告总体与多合法动作步骤的 top-1/NLL、局内/局外分项，并同时给出 uniform 和 first-legal 基线；集合选择另报集合及张数准确率。评估同一次 `assemble` 的 `val/` 或 `test/` 时，它还核对 assembly report 中的 episode ID、源文件哈希与 train split 的互斥性；通过后报告 `episode_split_verified=true`。可把 `--dataset` 改为 `.../test` 做第二份整局隔离的检查。拥有 CUDA/BF16 的机器可把训练命令改为 `--device cuda --precision bf16`；CUDA 能运行仍不等于策略强度已验证。
上面的 20 步 CPU 命令只检查数据、前后向、checkpoint 与评估链路。要讨论模型是否形成有用策略，需增加独立跑局数据，在未见过的 episode 上反复比较基线，再进行真实游戏内评估。

### 当前首版奖励：分幕、Boss 准备与战斗 HP

2026-10-15 按用户确认新增 `--reward-scheme whole-run-act-v1`：三幕通关分别
`+1/+2/+3`；非 Boss 战后 `(战后 HP − 战前 HP) / 战后最大 HP`；每幕 Boss
前按当前已升级牌每张 `+0.05`、当前遗物每件 `+0.1` 全量重计；第三幕额外
`HP/maxHP`；整局败北追加 `−10`。`gamma=1`，RTG 按真实边界自动计算，
Boss 入场奖励不重复出现在已进入战斗的决策 RTG 中。

奖励公式在离线转换阶段应用，原始 JSONL 保持只读。旧 `whole-run-v2` 日志可由
公开决策状态、逐动作 HP 变化、战斗生命周期和原生终局重建标签：当前 6 局 no-SL
日志共得到 4,021 个安全步骤（train 2,738 / val 781 / test 502）；训练集含 3 胜 1 负。旧日志的战前
锚点是首个公开战斗决策；新采集器的精确起止快照仍作为更强审计证据优先使用。
因此调整这些已记录事实上的奖励权重只需重新 assemble，不需重新打局。完整规则、
原生边界、验证边界及使用入口见
[分幕奖励说明](../../docs/spireformer-act-reward-v1.md)。

Tiny 在 `act-rtg-human-v2/train` 上完成 1,000 个 CPU/FP32 optimizer step（约 17 个
trajectory epoch）。使用真实记录 RTG 时，整局隔离 val/test top-1 分别为
49.68%/53.98%，多合法动作步骤为 46.68%/49.45%；两份评估均确认 episode split
无重叠。置零 RTG 的 top-1 为 49.17%/53.78%，差异很小，尚不能证明模型已经形成
稳定的奖励条件控制。test NLL 1.962 还差于 uniform 的 1.600，说明少量数据下存在
过度自信错误；4 个集合标签的 exact-set 全为 0。checkpoint 和四份评估报告位于
忽略目录 `artifacts/train-runs/tiny-act-rtg-human-v2-1000steps/`。

### 历史奖励：纯通关 RTG（用户已改用分幕方案）

2026-10-14 新增 `--reward-scheme whole-run-win-v1`，规则定义于
`spireformer/rewards.py`：整局通关奖励 +1，整局失败奖励 0，过程动作奖励 0，
折扣为 1，不做归一化。放弃、截断、未知终局不得当作失败 0。这使每个决策前的
实际 RTG 在胜局为 1、败局为 0；先按真实整局终点计算，再切 tensor 窗口，
窗口末尾不是游戏终点。奖励无需写进网络结构，assembler 自动写入
`TrajectoryStep.return_to_go`，现有 DT 主干读取它，训练损失继续监督动作。

首版沿用严格整局门槛：源日志 `whole-run-v2`、Python 全局审计通过、从开局明确
观察、连续 no-SL 决策、无 coverage gap/save-load/药水漏记/动作语义问题，终局
由 `termination_reason=native_run_history` 确证。数学上纯终局回报不需要逐步 HP
奖励；完整性要求是当前数据策略，并非 RTG 求和的必要条件。原始 collector reward
事件保留原义，新方案在派生数据中计算，不改原 JSONL，也不调用旧 HP shaping。

目前 8 局本地 journal 中只有 `32a38225...` 败局符合门槛（228 步）。验证产物放在
忽略目录 `artifacts/spireformer/win-rtg-v1-audit/holdout/`，只检查转换；该局在混合
BC 中原本属于 test，此处仍保持 holdout，没有拿来更新原 BC 模型。源审计报告为
`artifacts/spireformer/win-rtg-v1-source-audit.json`。尚缺合格胜局，不能把纯零回报
数据上的训练称为学会了胜败条件。

验证：`tests/test_win_rewards.py` 的 26 个用例覆盖胜败 RTG、跨窗口保留、
不合格日志拒绝、shard 读写和 RTG 输入的梯度；胜局使用合成测试日志，不代表
真实胜局已通过审计。本轮完整模型测试为 165 passed。

从仓库根目录可在新的输出位置复跑检查：

```bash
spireformer assemble \
  --input artifacts/human-dataset/episodes \
  --output artifacts/spireformer/win-rtg-v1-audit \
  --holdout-episode 32a3822509ec4c9fa8d00017103daee6 \
  --feature-spec artifacts/spireformer/mixed-bc-v1/feature-spec.json \
  --reward-scheme whole-run-win-v1
```

待胜败数据齐全后，使用显式 train/val/test 整局划分生成新数据集，再用普通
`spireformer train --value-weight 0` 训练。manifest/checkpoint 会绑定新的
`reward_version=whole-run-win-v1`；旧 BC checkpoint 不能作为该任务的严格 resume。
混合 BC 组装器仍只输出 BC 数据，未给 Spire Codex 不完整轨迹推定整局 RTG。

训练 RTG 从实际奖励自动计算；自主使用时另需指定目标 RTG。此方案可先请求目标
1，过程中收到零奖励时目标保持 1，到真正终局为止。它不是获胜概率，也不保证
模型通关。当前离线 evaluator 默认 `conditioning=zero`，对该方案表示请求失败
回报；`recorded` 使用真实未来胜败，只能作事后诊断。目标 1 的在线执行与胜率
评估尚未实现，不能把记录 RTG 的离线准确率当成部署成绩。

### 整局 HP RTG 模式（历史可选方案）

`--reward-scheme whole-run-hp-safe-v1` 的目标是只接受完整、无回档、`no_sl`、`whole-run-v2` 且语义审计通过的跑局。**首轮数据集和 checkpoint 已作废，以下组装、训练、评估数字仅为历史链路记录，不能作为正式训练/续训/评估输入。**旧胜局 `433d5532920444a1afac0716251e12c4` 的 step 270 在选牌后药水数减少 1，却没有对应的局外用药或弃药决策；新局 `ec731...` 的 step 79/608 也分别在领奖励和继续后出现同类减少。原始事件关联、原采集器的 `value_target_valid=true` 和当时的逐步语义审计均未发现这一缺失。败局 `32a3822509ec4c9fa8d00017103daee6` 未见同类减量，但仅有一局败局不足以训练或验证期望的胜败 RTG 策略。raw auditor 将旧文件受影响步骤标为 `unexplained_outside_potion_decrease` 并排除 BC 标签，RTG assembler 拒收整局。旧 BC-only shard 和 checkpoint 的 reward 契约不同，也不能直接续训到该模式。

新采集器只在 v0.111.0 的 Rewards 为顶层、药水栏和全部持有槽可核对、无正在执行的局外父动作或 selector、前一奖励已到稳定边界时，结构化手动局外 UsePotion/DiscardPotion：冻结包含 ClaimReward、Proceed 和合规 Use/Discard 的 Rewards 合法集，使用原生真实槽号与模型 ID，并以同一个 `GameAction` 的结果结算。普通 Rewards 点击也包含这些药水候选。若界面或快速并发操作无法证实，仍记 `coverage_gap`，不生成该动作 BC 标签且整局 RTG 无效；其他局外动作出现无法解释的药水净减少也记关联 gap。core 已有局外排队日志 API，Runtime 不据此推断不稳定前态。此有限路径尚未实机验证，不修复旧 JSONL、shard 或 checkpoint。

设 `H₀` 为本局开始时的最大生命上限，整局固定；`q(H)=clip(H/(0.5H₀),0,1)`。实际生命变化给 `0.2×(q(H_after)−q(H_before))`，胜利终局给 `1`，败北给 `0`，折扣 `γ=1`。每个决策从**该决策内部状态中的当前 HP**计算 `RTG=terminal+0.2×(q(H_final)−q(H_decision))`。生命值高于初始上限一半时，额外回血不加分；前两幕没有单独的离幕高血量奖励。末段回血若仍低于安全线，仍可能增加回报。临近终局的低血量状态在未来回血后，其 RTG 可以超过 `1`，因此不能把 `1` 固定理解为最佳目标。

不能简单按 JSONL 中较晚的 reward 行求后缀和：快速排队时，下一条 `decision` 可能已经观察到前一动作带来的生命变化，reward 事件却尚未落盘。HP 项是可望远镜求和的状态势差，故上述闭式计算以决策实际看到的 HP 为准；本轮两局的终局 HP 由全局 `hp_delta` 重建，旧文件没有独立终局 HP 字段可交叉核验。此模式仍不训练独立 value head，训练命令须保持 `--value-weight 0`。离线已记录 RTG 包含未来结局，只能作为训练标签或事后诊断，不能当成推理时已知的答案。

未来接入在线策略时，可按 `G_target(t)=G_target(0)−0.2×[q(H_t)−q(H_start)]` 更新剩余目标；起始目标必须从**重新审计通过**的胜败数据选取。旧胜局首步的 `0.94` 已不适合作为已验证的在线目标。需要更多独立胜败局及真实游戏内评估后，再比较不同目标值；当前没有游戏内 SpireFormer policy，尚未执行这套在线更新。

以下命令是**已作废的历史实验记录，不要原样重跑或用其产物继续训练**。对应输出目录现已存在；修复采集与拒收规则后，应选择新实机数据并写入新目录：

```bash
spireformer assemble \
  --input artifacts/human-dataset/episodes \
  --output artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1 \
  --train-episode 433d5532920444a1afac0716251e12c4 \
  --train-episode 32a3822509ec4c9fa8d00017103daee6 \
  --reward-scheme whole-run-hp-safe-v1 \
  --max-window-steps 64

spireformer train \
  --dataset artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1/train \
  --output artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1 \
  --preset small --device cpu --precision fp32 \
  --total-steps 20 --warmup-steps 2 --batch-size 1 \
  --checkpoint-every 5 --log-every 1 \
  --value-weight 0 --entropy-weight 0 --verify-data
```

历史组装曾生成 `1211` 个动作标签、`22` 个最长 64 步的轨迹窗口，reward version 为 `whole-run-hp-safe-v1`；旧胜局 RTG `0.94–1.135`、重建终局 HP 28，败局 RTG `−0.20–−0.05`、终局 HP 0。这些数值只描述当时的输入和计算，不证明轨迹覆盖完整。Small 以当时特征宽度构建后有 `103,301,379` 个参数，并在本机 CPU/FP32 完成 20 个 optimizer step；checkpoint `artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1/checkpoint-latest.pt` **已作废**。末步 `policy_loss=1.0698057` 也不能作为有效训练或验证指标。时序主干每次最多看到窗口内的 64 个决策，不等于一次读完 985 步历史。

历史训练集曾以 `--conditioning recorded --allow-training-dataset` 做事后检查：整体 top-1 为 56.65%；1115 个多合法动作步骤为 52.91%（first-legal 25.92%，uniform 期望 19.59%）；8 个集合选择标签的 exact accuracy 为 0。这些结果来自已作废数据集，**不得作为正式离线评估或模型质量证据**。当时报告也明确写 `episode_split_verified=false`、`training_overlap_allowed`、`recorded_future_return_input=true`。重新采集胜败轨迹后，应按 episode 留出验证集，再评估条件目标和真实游戏表现。

要把另一次亡灵契约师跑局作为**独立同角色 holdout**，需复用训练集的 `feature-spec.json`，不能用这局重新拟合词表。下例的输出目录也须尚不存在：

```bash
spireformer assemble \
  --input artifacts/human-dataset/episodes \
  --output artifacts/tensor-v2/necrobinder-holdout-demo-v3 \
  --holdout-episode 4be275a1f2554b938c3f90908c02ef23 \
  --feature-spec artifacts/tensor-v2/bc-demo-v3/feature-spec.json \
  --max-window-steps 64

spireformer evaluate \
  --checkpoint artifacts/runs/spireformer-bc-tiny-v3/checkpoint-latest.pt \
  --dataset artifacts/tensor-v2/necrobinder-holdout-demo-v3/holdout \
  --training-assembly-root artifacts/tensor-v2/bc-demo-v3 \
  --device cpu --precision fp32 --verify-data
```

`--training-assembly-root` 使评估器核对独立 holdout 与训练组装结果中的 episode ID 和原始文件 SHA-256 不重叠。该局有 339 个可用 BC 步，另有 2 次取消与一次 `TO_TRANSFORM` 多卡采集缺口；缺口会切断轨迹，不能将它作为整局 value 或多卡选择的验证样本。

### 本地 Tiny 试训证据

已用 `artifacts/tensor-v2/bc-pilot-20260930-v3` 训练 Tiny 200 个 optimizer step（CPU、FP32、`--value-weight 0 --entropy-weight 0`），checkpoint 位于 `artifacts/train-runs/tiny-bc-pilot-20260930-v3/checkpoint-latest.pt`。独立亡灵契约师 holdout 位于 `artifacts/tensor-v2/necrobinder-holdout-20261001-v3`，复用同一特征词表。所有 shard 已经带哈希校验重读，四个 split 的 RTG 均为零占位、value target 均缺失；全套模型测试 116 项通过。

| 整局隔离的评估集 | 多于一个合法动作的步骤 | Tiny top-1 | first-legal | uniform 期望 top-1 |
| --- | ---: | ---: | ---: | ---: |
| Ironclad val | 625 | 45.12% | 25.44% | 20.94% |
| Silent test | 192 | 39.06% | 21.88% | 23.71% |
| Necrobinder holdout | 314 | 50.96% | 28.98% | 21.74% |

三份评估的 `episode_split_verified=true`；val 仅有 2 个集合标签，集合 exact accuracy 为 0。本次结果证明转换、训练和离线评估链路能够运行，并显示对这几局人工动作的模仿好于表中的简单基线。样本与训练量很小，不能据此判断在线胜率或模型是否形成可迁移的策略。

## 命令行训练

训练输入必须是版本化 tensor dataset，当前写入格式见 [Tensor Shard Format v2](docs/tensor-shard-format-v2.md)。先执行 `--dry-run` 可以验证数据 manifest、模型尺寸和训练配置；它只构建 meta 模型对象用于精确计数，不分配真实参数存储：

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

训练指标中 `set_loss` 和 `set_targets` 单独统计多卡集合选择；普通动作仍使用 `policy_loss` 和 `policy_targets`。

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

`SpireFormerBatch` padding 整局长度和三个局部集合维度：

| 维度 | 含义 |
|---|---|
| `T` | 一局游戏中的决策历史 |
| `N` | 每个状态可见的实体集合 |
| `A` | 每个状态当前合法的动作集合 |
| `C` | 多卡选择时可见的候选卡牌；普通决策没有这一集合 |

公开 batch 的 `entity_mask`、`legal_action_mask`、`set_candidate_mask`、`step_mask` 都使用 `True = 有效`。只有 Set Transformer 内部的 `padding_mask` 跟随 PyTorch，使用 `True = padding`。字段名和转换位置是有意固定的，避免局内/局外数据合并后出现反向 mask 的静默错误。

`previous_action_features[:, t]` 表示导致当前状态的 `a_(t-1)`。时序核心将它放入上一组 `(R, S, A)` 的 A 槽，因此 `S_t` 能看见上一动作，但看不见当前待预测动作。

多卡选择的普通动作列表只保留一个集合动作模板（若可以取消，再加取消动作）；`C` 张候选牌进入共享 Set Transformer 和因果主干后的集合选择头。模型输出每牌一个 logit 和合法张数 `min_select..max_select` 的 logit。训练时对真实无序集合使用条件 Bernoulli 的精确归一化，动态规划复杂度为 `O(C × k)`，其中 `k` 是目标选择张数。19 选 4 因此使用 19 张候选牌和一个模板动作，不建立 3876 个组合动作。可变张数和合法的零张选择也适用。候选自注意力可利用其他牌的上下文，但最终集合概率仍由逐牌分数与张数决定，尚不能表达依赖已选子集的任意搭配效应。

训练轨迹的 `executed_action_features` 必须描述真正选中的集合，供下一步的 `previous_action_features` 使用；模板动作本身不含所选牌。tensorizer 应从 `action_submitted.selected_action` 的具体 `selected_cards` 生成这个特征和 `set_selected_mask`。候选按决策时 `option_index` 对齐，但 index、原生对象 ID、Steam 身份、seed 和时间戳不能直接作为模型数值特征。取消或缺少可靠回执时不形成集合监督。

## 训练目标

- 行为克隆数据：使用执行成功动作的 one-hot 目标；
- MCTS 蒸馏：使用根节点 visit count 归一化后的软目标；
- value：只训练带有效整局结果的 timestep；局外 first-legal 但没有终局结果的样本必须把 `value_target_mask` 设为 `False`；
- padding、执行失败、取消或 stale-state 动作不参与 loss。

模型输出 `policy_logits[B,T,A]`、可选 `set_candidate_logits[B,T,C]`、`set_count_logits[B,T,C+1]` 和 `state_value[B,T]`。非法动作或张数的 logit 固定为 `-inf`；在线执行时由同一决策对象复核动作模板、所选卡牌和状态指纹。

设计与实现记录见 [SpireFormer v0.1 开发日志](../../docs/spireformer-v0.1-development-log.md)。raw JSONL 的采集、首版 BC 转换与后续 value/headless 方向见 [训练数据 v1 规划](../../docs/spireformer-training-data-v1-plan.md)。
