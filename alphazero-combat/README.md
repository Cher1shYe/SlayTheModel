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

导出的 manifest 包含模型输入维度、checkpoint/ONNX 哈希、对账样本数及最大误差；尚未接入 NativeWorker 推理或搜索。

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
