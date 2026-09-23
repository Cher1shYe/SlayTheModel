# 现有仓库入口集成

所有调用从本目录的脚本/配置发起；禁止编辑既有 solver、协议、游戏 Mod 或 NativeWorker 核心文件。

## 完整随机战斗输入

场景 JSON schema 以 `combat/tools/GeneratedCombatScenarios/random.json` 和 `combat/src/Testing/GeneratedCombatScenario.cs` 为准（场景 schemaVersion 1）。现成批量脚本可按每个 case 生成固定 seed 输入：

```powershell
python combat/tools/GeneratedCombatScenarios/run.py `
  --count 20 --seed AZ-TRAIN-000 --mode Setup `
  --output .local/azcombat-train-inputs --write-inputs-only
```

`--write-inputs-only` 只写 unresolved 输入，不启动游戏也不解析出角色/遭遇/卡牌；它不是已采样战斗，也不能作为训练状态。去掉该选项会进入现有无人测试启动链路，需要本机游戏与冻结构建环境。`Setup` 用于场景建立/预检，`Search` 跑现有 solver，`Deploy` 部署现有 solver；三者都不是 AlphaZero rollout writer。

无人测试入口为 `combat/tools/run-unattended-test.ps1`（Windows）和 `combat/tools/run-unattended-test.sh`（Linux/macOS）。每次运行使用专属 evidence/output 和 instance，固定 seed，保存完整日志。不得让批量任务覆盖他人运行目录或复用游戏交互实例。

## 合法中途状态

仓库 checkpoint archive/CheckpointTool 和 replay/search 模式可检查、恢复、重放已有问题包。它们面向复现/回归，默认 checkpoint 可为战斗入口，不保证任意中途状态/嵌套 choice 都能变成独立训练 root。未来 adapter 必须：

1. 选择明确 checkpoint selector 和版本固定的 archive；检查 `materials_valid`，确认原版 v0.111.0 与 solver build/coverage 身份。
2. 恢复并回放到目标决策边界；确认捕获状态、合法动作树和再次恢复后的指纹/动作一致。
3. 只把 `DecisionObservationProjector.ToCombat()` 对应白名单写入网络样本；原生 replay payload 仅保留在隔离环境用于重建，不提供给模型。
4. 将可证明的样本标记 `mid_combat_verified`；失败恢复、边界模糊或历史不完整的样本隔离，不降级伪装为完整战斗样本。

具体 archive 参数/语义以 `combat/docs/CHECKPOINT_REPLAY.md` 与无人测试脚本帮助为准。当前目录尚无中途 root importer。

## MCTS / NativeWorker 边界

现有 NativeWorker replay 环境及 `NativeMctsSimulationApi` 提供原生模拟/MCTS基础设施，但没有本目录要求的 Python 自博弈采样、稳定样本格式、ONNX model evaluator 或 alpha 策略 IPC ABI。接入时通过新 adapter 暴露“严格观测+合法分层动作+搜索访问次数”和 `Evaluate(observation, action candidates)`；本地 native state 仅作为模拟器私有环境存在。

已有 benchmark 是旧 MCTS 搜索的历史证据，不代表本模型已达到 100 次模拟/秒。性能报告必须在新 ONNX/NativeWorker 路径上实测有效完成的模拟，并单独测量决策点墙钟预算。
