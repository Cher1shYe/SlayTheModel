# AlphaZero Combat

这是一个与现有 solver 隔离的单人随机战斗 AlphaZero 实验目录，目标基线为游戏原版 `v0.111.0` 和 Combat Solver 覆盖登记表中已支持的战斗内容。

**当前状态：严格观测、Python/ONNX 编码和 NativeWorker 树内 policy/value 试验链路已可运行；1,970 参数模型只用于接口验证，尚未通过 M4 晋级或性能门槛。** 训练器严格回读 JSONL，按 seed 隔离训练/验证；单种子数据不能生成有效验证集，因此拒绝训练。当前搜索仍使用真实 seed 的全知模拟器，只有网络观测受限。

训练前安装可选依赖：`python -m pip install -e './alphazero-combat[train]'`。使用至少两个独立种子的导出文件（不要使用旧问题样本）：

```powershell
python -m azcombat.train_cli artifacts/alphazero/m4-regression-20260924/final-ordinary-045.jsonl `
  artifacts/alphazero/m4-regression-20260924/final-nested-047.jsonl `
  --checkpoint artifacts/alphazero/checkpoints/new-warm-start.pt --epochs 5 --hidden 16
```

Checkpoint 包含模型权重、参数、每个输入 SHA256、训练/验证种子和逐 epoch 损失；这仅是冷启动训练，不代表候选已通过未见种子或晋级门槛。

实验性 ONNX 候选导出及 PyTorch/ONNX Runtime 数值对账（独立输出，不覆盖）：

```powershell
python -m pip install -e './alphazero-combat[export]'
python -m azcombat.export_cli `
  --checkpoint artifacts/alphazero/checkpoints/policy-observation-v4-smoke-20260924.pt `
  --onnx artifacts/alphazero/checkpoints/new-candidate.onnx `
  --parity-jsonl artifacts/alphazero/m4-regression-20260924/final-ordinary-045.jsonl `
    artifacts/alphazero/m4-regression-20260924/final-nested-047.jsonl
```

新导出的 manifest 包含 `azcombat.onnx.v4`、`azcombat.features.v4`、观测 schema 3、输入维度、checkpoint/ONNX 哈希及数值对账证据。当前 checkpoint 为 `azcombat.checkpoint.v3`，训练样本顶层 schema 仍为 1。既有 v4/v4 与 v3/v4 产物未单列观测 schema 字段时，特征 ABI 已固定对应 schema 3；显式字段若存在必须为 3。旧格式、错误哈希和错误特征 ABI 均拒绝。NativeWorker 默认保留历史 `post-mcts-rerank`，只有明确请求 `policy-value-tree-v1` 才在树内应用 prior/value；推理失败标明纯 MCTS 回退，不算成功引导。

本地导出器实验路径设置 `STS2_ALPHAZERO_ONNX_MODEL` 为 ONNX 绝对路径；设置 `STS2_ALPHAZERO_SHADOW=1` 时仅记录分数、不改变 MCTS 执行。正式 IPC 游戏控制器通过 `SLAY_THE_MODEL_ALPHAZERO_ONNX_MODEL` 环境变量或 runtime 配置把绝对路径传给 Worker；未配置时保持纯 MCTS。`native_parity_cli` 只检查历史 post-rerank 的根动作日志，不能作为树内 ONNX/Native 数值一致性证据；树内模式仍需针对当前普通、选择和嵌套输入扩大该项对账。

真实 server 请求/回退 smoke 用 `scripts/native-worker.ps1 -Mode az-server-smoke` 完整发布运行，并通过 `STS2_AZ_SERVER_VERIFY_OUT` 指定新的结果文件；测试不会自动晋级模型。仅模型启用时有一次返回 >100 sims/s，不代表多随机种子、选择与死亡状态的性能门槛通过。

M4 的波次编排和 fail-closed 晋级审计位于 `experiments.py` 与 `promotion.py`。`bootstrap` 允许未晋级候选在新的种子上执行单人随机环境战斗并收集严格样本，但只产生独立的 `bootstrap-audit`，**不能晋级**；`evaluate` 为每个未见 seed、登记 encounter、完整/合法中途起点都运行纯 MCTS baseline 与 candidate 配对；每次都新建输出目录、完整 ExportRelease、保留 stdout/stderr，并严格回读 JSONL。`selfplay` 仍只有已晋级且哈希/门禁报告完整的 champion alias 才能启动，且禁止复用 champion 已使用的 seed。晋级审计要求真实程序集 provenance、每决策至少 1000 ms、有效模拟速率至少 100/s、统一终局回填、嵌套选择和死亡结算证据；任一缺项只写拒绝报告，不改 champion。

正式晋级门禁要求每个真实决策实际使用树内 policy prior 与 value、零回退，并核对每个决策的模拟次数、预算及实际加载程序集；网络调用总数是树节点调用数，不等于真实决策数。当前严格观测已覆盖 live 与预测节点，并排除 RNG、不可见抽牌顺序和未来意图，但这不消除搜索模拟器对真实 seed 的使用。

当前入口的最小配对 smoke（输出目录必须不存在；不会晋级或启动正式 self-play）：

```powershell
python -m azcombat.experiments evaluate --output artifacts/alphazero/new-tree-smoke `
  --game-dir 'D:\Steam\steamapps\common\Slay the Spire 2' `
  --ritsu-root 'D:\Steam\steamapps\workshop\content\2868840\3747602295' `
  --model artifacts/alphazero/checkpoints/policy-observation-v4-smoke-20260924.onnx `
  --seed NEW-A --seed NEW-B --encounter CULTISTS_NORMAL --scenario ordinary `
  --candidate-search-mode policy-value-tree-v1 --max-simulations 50 `
  --budget-ms 1000 --max-decisions 3
python -m azcombat.wave_smoke_report --wave artifacts/alphazero/new-tree-smoke `
  --expected-runs 8 --report artifacts/alphazero/new-tree-smoke/smoke-audit.json
```

`wave_smoke_report` 严格回读全部样本并对账每决策的真实模式、预算、模拟次数、网络调用、回退与程序集身份；它不是晋级门禁。50 次上限和至少 1 秒预算不能证明达到 100 simulations/s。旧 bootstrap/续训产物保留为历史证据，但其旧 ABI 模型不能进入当前严格评估入口。

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
- `m4-regression-20260924/tree-mode-smoke-010`：新 Release 的 2 seed × full/mid 候选采集 4 次，严格回读与 provenance 对账；明确标记搜索后重排、树内推理计数为零。bootstrap 审计有效但全部 unresolved，2 条运行低于 100/s，不具备晋级资格。
- `m4-regression-20260924/entry-tree-smoke-20260924-002`：正式编排入口的 2 seed × full/mid × baseline/tree 共 8 次新 ExportRelease，24 条样本严格回读；candidate 树内 prior/value 各 600 次、回退与非法动作均为零。8 条轨迹均因 3 个父决策上限为 unresolved，无真实选择节点；M4 因覆盖与 100/s 门槛不足明确拒绝，未创建 champion。先前 `-001` 保留作缩窄推理回退捕获前的对照，不作为最终验收。

下一阶段的真实 Native 选择、完整胜负和独立无模拟上限的墙钟性能验证见 [Native 验证记录](docs/NATIVE_VALIDATION_20260924.md)。其中纯 MCTS 的复杂选择根未达到 100 simulations/s；树内试验模型仅在本批小样本中超过门槛，不能据此晋级。

纯 MCTS 的后续同 checkpoint 冷/热根与分段工作量归因见 [同根诊断](../profile_output/mcts-same-root-diagnosis-20260924.md)。该报告只提出按需物化选择兄弟分支的后续验证方向，本轮未修改搜索算法或降低 100/s 门槛。

这些证据证明试验候选能够执行自博弈采集、续训与下一代推理，且晋级门禁会拒绝未达门槛的候选；当前没有 champion，正式 champion 自博弈尚未获准。

### 纯 MCTS 教师与完整战斗对比（2026-09-25）

本轮固定 20/5/10 个互不重叠的训练/验证/评估 seed、5 套显式铁甲战士牌组，以及 `CULTISTS_NORMAL` / `LIVING_FOG_NORMAL` 两个遭遇。R3 的 50 个教师任务全部尝试，严格审计为 48 场胜利、2 项 worker 启动前的发布文件占用错误；使用 48 条真实终局轨迹的 1,380 个决策（172 个自然选择节点）训练了独立 1,970 参数候选。训练集没有死亡标签。新候选的 Python/ONNX/Native 数值对账通过。

预留 10 seed × 2 遭遇 × 3 策略的 60 场 headless 完整战斗全部严格通过，20 个配对开局一致：纯 MCTS 胜 19/20、旧树模型 10/20、新树模型 9/20（另 3 场 unresolved）。新模型在邪教徒遭遇提高了胜场，但 Living Fog 明显退化；不能宣称总体改善或晋级。完整逐场审计、训练曲线、计算成本和失败现场见 [研究报告](../artifacts/alphazero/teacher-tree-r3-20260924/study-report.md)。没有修改 M4 门槛、创建 champion 或启动正式 self-play。

后续局部回归修复了 HEADBUTT 末击后预测侧错误保留选牌的问题；NativeWorker 每次发布现在使用独立 stage，不覆盖旧 EXE/DLL/日志。冻结根诊断发现 PURITY、CASCADE 的实际树内模型输入仍缺少 `Choice` 上下文，选择感知效果暂不能据此评判。只读 R3 校准显示失败/未完成普通根的 value 普遍偏正；本轮没有重训或调参。证据见 [边界与诊断报告](../artifacts/alphazero/headbutt-boundary-20260925/report.md)和[冻结根报告](../artifacts/alphazero/frozen-prior-value-20260925-summary.md)。

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
