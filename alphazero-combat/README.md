# AlphaZero Combat

这是一个与现有 solver 隔离的单人随机战斗 AlphaZero 实验目录，目标基线为游戏原版 `v0.111.0` 和 Combat Solver 覆盖登记表中已支持的战斗内容。

**当前状态：规格、观测/动作 ABI 草案、奖励函数和单元测试骨架。尚未实现 MCTS 样本采集/训练、自博弈、ONNX 导出、NativeWorker 策略加载或实测性能。** 目录不会修改现有核心代码；集成阶段只从这里调用仓库已有的随机战斗场景生成器和无人测试入口。

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
