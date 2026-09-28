# Research Output Manifest

> Planning artifacts only; no experiment, training, promotion or self-play was started.

| Timestamp | Skill | File | Stage | Description |
|-----------|-------|------|-------|-------------|
| 2026-09-24 19:29:21 | /experiment-plan | refine-logs/EXPERIMENT_PLAN_20260924_192921.md | implementation | 树内 MCTS 到受控自进化的分阶段计划；包含本次只读检查发现的入口阻塞 |
| 2026-09-24 19:29:21 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER_20260924_192921.md | implementation | 拟执行任务列表，全部 TODO |
| 2026-09-24 19:29:21 | /experiment-plan | refine-logs/EXPERIMENT_PLAN.md | implementation | 最新计划副本 |
| 2026-09-24 19:29:21 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER.md | implementation | 最新跟踪表副本 |
| 2026-09-26 02:10 | /experiment-plan | artifacts/alphazero/r4-training-admission-20260926-001/index.json | implementation | R4 20 场数据唯一准入索引与 provenance |
| 2026-09-26 02:10 | /experiment-plan | artifacts/alphazero/r4-training-admission-20260926-001/R4_TRAINING_PLAN_20260926_021055.md | implementation | R4 第一轮小规模训练方案冻结版 |
| 2026-09-26 02:10 | /experiment-plan | artifacts/alphazero/r4-training-admission-20260926-001/R4_TRAINING_PLAN.md | implementation | R4 第一轮小规模训练方案最新副本 |
| 2026-09-26 02:10 | /experiment-plan | artifacts/alphazero/r4-training-admission-20260926-001/R4_ADMISSION_CHECKLIST_20260926_021055.md | implementation | R4 数据准入清单冻结版 |
| 2026-09-26 02:10 | /experiment-plan | artifacts/alphazero/r4-training-admission-20260926-001/R4_ADMISSION_CHECKLIST.md | implementation | R4 数据准入清单最新副本 |
| 2026-09-26 02:25 | /experiment-plan | alphazero-combat/src/azcombat/r4_training.py | implementation | R4 准入索引加载、轨迹级加权与 unresolved value 掩码 |
| 2026-09-26 02:25 | /experiment-plan | alphazero-combat/tests/test_r4_training.py | implementation | R4 加权训练入口最小回归 |
| 2026-09-26 02:40 | /run-experiment | artifacts/alphazero/r4-smoke-weighted-mix-20260926-001/report.json | result | R4-SMOKE-WEIGHTED-MIX-001 工程训练报告（不可晋级） |
| 2026-09-26 02:40 | /run-experiment | artifacts/alphazero/r4-smoke-weighted-mix-20260926-001/candidate.pt | result | R4 工程候选 checkpoint，1970 参数，禁止作为 champion |
| 2026-09-26 02:45 | /run-experiment | artifacts/alphazero/r4-smoke-weighted-mix-20260926-001/candidate.onnx | result | R4 工程候选 ONNX，Python/ONNX 数值对账通过 |
| 2026-09-26 02:45 | /run-experiment | artifacts/alphazero/r4-smoke-weighted-mix-20260926-001/candidate.manifest.json | result | ONNX ABI、checkpoint provenance 与 parity manifest |
| 2026-09-26 02:55 | /run-experiment | alphazero-combat/src/azcombat/r4_promotion.py | implementation | R4 训练候选晋级前置条件的 fail-closed 判定 |
| 2026-09-26 02:55 | /run-experiment | artifacts/alphazero/r4-smoke-weighted-mix-20260926-001/promotion-assessment.json | result | R4 晋级评估：DENY |
| 2026-09-26 03:30 | /run-experiment | alphazero-combat/src/azcombat/cycle_smoke.py | implementation | R4 工程自进化闭环编排：训练、导出、Native 配对 screen |
| 2026-09-26 03:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/plan.json | result | 新登记开发 seed 的闭环计划与 provenance |
| 2026-09-26 03:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/screen.json | result | 4 对 Native screen，候选拒绝，未创建 champion |
| 2026-09-27 09:30 | /run-experiment | alphazero-combat/src/azcombat/trajectory_parity.py | implementation | 对 surviving Native 树内回调执行 Python/ONNX/Native 数值对账 |
| 2026-09-27 09:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/001.numeric-parity.json | result | DEV01 CULTISTS 候选树根数值对账，21 roots |
| 2026-09-27 09:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/003.numeric-parity.json | result | DEV01 LIVING_FOG 候选树根数值对账 |
| 2026-09-27 09:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/005.numeric-parity.json | result | DEV02 CULTISTS 候选树根数值对账 |
| 2026-09-27 09:30 | /run-experiment | D:/sts2-experiments/r4-cycle-repair-001/007.numeric-parity.json | result | DEV02 LIVING_FOG 候选树根数值对账 |
| 2026-09-27 09:30 | /run-experiment | alphazero-combat/tests/test_r4_training.py | verification | C 盘 R4 输入已授权清理，集成测试显式 skip，不伪造恢复数据 |
