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

M4 的波次编排和 fail-closed 晋级审计位于 `experiments.py` 与 `promotion.py`。`bootstrap` 允许未晋级候选在新的种子上执行单人随机环境战斗并收集严格样本，但只产生独立的 `bootstrap-audit`，**不能晋级**；`evaluate` 为每个未见 seed、登记 encounter、完整/合法中途起点都运行纯 MCTS baseline 与 candidate 配对；每次都新建输出目录、完整 ExportRelease、保留 stdout/stderr，并严格回读 JSONL。`selfplay` 仍只有已晋级且哈希/门禁报告完整的 champion alias 才能启动，且禁止复用 champion 已使用的 seed。晋级审计要求真实程序集 provenance、每决策至少 1000 ms、有效模拟速率至少 100/s、统一终局回填、嵌套选择和死亡结算证据；任一缺项只写拒绝报告，不改 champion。

试验性的自博弈续训（不覆盖旧模型，网络宽度从父 checkpoint 继承）：

```powershell
python -m azcombat.experiments bootstrap --output artifacts/alphazero/new-bootstrap `
  --game-dir 'D:\Steam\steamapps\common\Slay the Spire 2' `
  --ritsu-root 'D:\Steam\steamapps\workshop\content\2868840\3747602295' `
  --model artifacts/alphazero/checkpoints/m3-candidate-20260924-v2.onnx `
  --seed NEW-A --seed NEW-B --encounter CULTISTS_NORMAL
python -m azcombat.bootstrap_cli --wave artifacts/alphazero/new-bootstrap/manifest.json `
  --checkpoint artifacts/alphazero/checkpoints/m2-smoke-20260924-v2.pt `
  --report artifacts/alphazero/new-bootstrap/bootstrap-audit.json
python -m azcombat.train_cli --bootstrap-wave artifacts/alphazero/new-bootstrap/manifest.json `
  --init-checkpoint artifacts/alphazero/checkpoints/m2-smoke-20260924-v2.pt `
  --checkpoint artifacts/alphazero/checkpoints/new-generation.pt --epochs 1
```

续训前会重新严格审计原波次；输入文件哈希、模型来源 checkpoint、训练/验证/新种子及代际信息写进新 checkpoint。`valid=true` 只证明样本来源与标签等契约成立；速率不足或 unresolved 会在审计里明示，不能当作候选通过晋级评估。

新版波次支持 `--scenario ordinary --scenario purity_choice --scenario cascade_nested --scenario native_death`：普通场景覆盖完整与经重放核验的中途起点，净化场景要求实际选牌决策，CASCADE/PREPARED 场景要求同一真实父动作下两层选择，1 HP 原生场景要求真实死亡结算；每项均 baseline/candidate 配对。请求夹具、种子、遭遇、起点、预算与模型哈希写入 manifest 并与 JSONL provenance 对账。每次发布后立即保存完整 worker stdout/stderr；审计核对原始日志中的实际加载路径、MVID、SHA256 和导出绝对路径。夹具本身不等于覆盖证明，必须由运行轨迹满足场景条件。

新导出的 `decisionMetrics` 还记录真实执行的根动作 ID、父决策编号、父动作 ID 与选择层号；晋级审计要求每个选择层都接在同一个合法父动作之后且层号连续。仅在同一父动作下实际出现第二层选择才计为嵌套，数据仍保持原严格样本 schema，模型参数不变。

当前已保存的 M4 证据包括：

- `m4-regression-20260924/paired-smoke-003`：2 seed × 1 encounter × 2 起点 × baseline/candidate，8 次完整发布；每条决策实际墙钟均 ≥1000 ms。审计按预期拒绝（样本未完成、覆盖/嵌套/死亡证据不足）。
- `m4-regression-20260924/native-death-004.jsonl` 与 `model-native-death-005.jsonl`：原生低 HP 真实死亡，最终 `loss/-1.0`，不伪造标签；候选模型路径无回退。
- `m4-regression-20260924/mid-start-model-001.jsonl`：真实 checkpoint + `EndTurn` 前缀重放后导出 `mid_combat_verified`。
- `m4-regression-20260924/matrix-smoke-001`、`matrix-smoke-002`：16 次发布的场景矩阵回归，均严格拒绝不达标覆盖与未完成轨迹；第二轮真实死亡配对已出现。旧脚本只回显 worker 日志末尾，第二轮长轨迹缺程序集标识，拒绝报告保留。
- `m4-regression-20260924/log-capture-smoke-003`：新完整日志保存逻辑下的 2 seed × 原生死亡 × baseline/candidate，4 次发布均严格回读并核对程序集与导出路径；它不是完整晋级矩阵。
- `m4-regression-20260924/choice-chain-smoke-004`：新 Release 的 2 seed × 净化 baseline/candidate，4 次发布严格回读与选择层链路对账；仅单层选择，部分速率 <100/s，门禁拒绝并保留报告。
- `m4-regression-20260924/cascade-prepared-probe-005.jsonl`：真实 CASCADE/PREPARED 战斗 40 条严格样本，包含同一 CASCADE 父动作的两层选择。`cascade-paired-006`：2 seed × baseline/candidate 实际配对；baseline 第二种子出现多层选择，但候选均未进入选择且死亡，部分初始决策仅约 44–56 sims/s，门禁拒绝。性能证据和未证实的预热假设见 `profile_output/azcombat-m4-cascade-20260924.md`。
- `m4-regression-20260924/bootstrap-smoke-007`：2 个新种子 × 2 起点的未晋级候选自博弈，4 次原生发布、48 条严格样本，审计有效但全部 unresolved，2 条运行的最低速率低于目标。独立续训的 `m4-bootstrap-20260924-g1.pt/.onnx` 保持 1,970 参数、ONNX 数值对账通过；`bootstrap-g1-smoke-008` 在另两种新种子上完成原生加载与严格审计，仍不代表晋级。
- `m4-regression-20260924/bootstrap-g1-resolved-009`：第 1 代模型另两新 seed 的 full/mid 共 4 次真实死亡结算、57 条严格样本，均统一回填 `loss/-1.0`；审计有效，但一条运行低于 100 sims/s，也没有胜利证据，不可晋级。

这些证据证明试验候选能够执行自博弈采集、续训与下一代推理，且晋级门禁会拒绝未达门槛的候选；当前没有 champion，正式 champion 自博弈尚未获准。

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
