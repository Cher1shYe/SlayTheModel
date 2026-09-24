# AlphaZero Combat

这是一个与现有 solver 隔离的单人随机战斗 AlphaZero 实验目录，目标基线为游戏原版 `v0.111.0` 和 Combat Solver 覆盖登记表中已支持的战斗内容。

**当前状态：已有 NativeWorker MCTS 严格样本导出和 Python DeepSets/MLP 冷启动训练入口；ONNX/NativeWorker 模型推理、自博弈、晋级门禁与性能验证尚未完成。** 训练器严格回读 JSONL，按 seed 隔离训练/验证；单种子数据不能生成有效验证集，因此拒绝训练。

训练前安装可选依赖：`python -m pip install -e './alphazero-combat[train]'`。使用至少两个独立种子的导出文件（不要使用旧问题样本）：

```powershell
python -m azcombat.train_cli artifacts/alphazero/m1-regression-20260924/cultists-001.jsonl `
  artifacts/alphazero/m1-regression-20260924/living-fog-002.jsonl `
  --checkpoint artifacts/alphazero/checkpoints/warm-start.pt --epochs 5
```

Checkpoint 包含模型权重、参数、每个输入 SHA256、训练/验证种子和逐 epoch 损失；这仅是冷启动训练，不代表候选已通过未见种子或晋级门槛。

实验性 ONNX 候选导出及 PyTorch/ONNX Runtime 数值对账（独立输出，不覆盖）：

```powershell
python -m pip install -e './alphazero-combat[export]'
python -m azcombat.export_cli --checkpoint artifacts/alphazero/checkpoints/warm-start.pt `
  --onnx artifacts/alphazero/checkpoints/candidate.onnx `
  --parity-jsonl artifacts/alphazero/m1-regression-20260924/choice-fixture-fixed.jsonl
```

导出的 manifest 包含模型输入维度、checkpoint/ONNX 哈希、对账样本数及最大误差。NativeWorker 可选加载候选，在 MCTS 已访问的当前合法根动作中重排；加载、编码或推理失败会保留纯 MCTS 动作。此重排并非已完成的 PUCT/价值引导搜索，也不是晋级许可。

本地导出器实验路径设置 `STS2_ALPHAZERO_ONNX_MODEL` 为 ONNX 绝对路径；设置 `STS2_ALPHAZERO_SHADOW=1` 时仅记录分数、不改变 MCTS 执行。正式 IPC 游戏控制器通过 `SLAY_THE_MODEL_ALPHAZERO_ONNX_MODEL` 环境变量或 runtime 配置把绝对路径传给 Worker；未配置时保持纯 MCTS。新发布产物的选择根对账：

```powershell
python -m azcombat.native_parity_cli `
  --checkpoint artifacts/alphazero/checkpoints/m2-smoke-20260924-v2.pt `
  --jsonl artifacts/alphazero/m3-regression-20260924/model-choice-shadow-005.jsonl `
  --stdout artifacts/alphazero/m3-regression-20260924/model-choice-shadow-005.stdout.txt
```

真实 server 请求/回退 smoke 用 `scripts/native-worker.ps1 -Mode az-server-smoke` 完整发布运行，并通过 `STS2_AZ_SERVER_VERIFY_OUT` 指定新的结果文件；测试不会自动晋级模型。仅模型启用时有一次返回 >100 sims/s，不代表多随机种子、选择与死亡状态的性能门槛通过。

从本目录运行纯 Python 合约测试：

```powershell
python -m unittest discover -s alphazero-combat/tests -v
```

调用现有入口生成一组随机战斗输入（不启动游戏、不解析模型）：

```powershell
python combat/tools/GeneratedCombatScenarios/run.py `
  --count 20 --seed AZ-HOLDOUT-A --mode Setup `
  --output .local/azcombat-inputs --write-inputs-only
```

输出目录必须不存在。详细边界、奖励与集成缺口见 [项目规格](docs/PROJECT_SPEC.md) 和 [仓库集成说明](docs/REPOSITORY_INTEGRATION.md)。
