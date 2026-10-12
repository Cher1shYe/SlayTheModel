# 五遭遇、双 seed 十轮训练

2026-10-09 用户调整：停止三 weak 遭遇的 50 轮运行；增加真正高难度怪物，每 seed 改为 10 轮。旧进程树已停止；`output/az_decks_v3_r2/stopped_by_user.json` 保留停止快照，旧 state/checkpoint/Replay/晋级记录不改写。停止时 seed 42 已完成第 1 轮、正在第 2 轮验证，seed 43 已完成第 1 轮。

## 新内容

内容 `five-encounters-decks-v2`，信息 `hard-information-v2`，编码 `az-hard-encoder-v2`。原 8 卡白名单、升级及四个构筑家族不变。新运行从随机权重初始化；旧模型和 Replay 不混入新 schema。

| 遭遇 | 原生 HP | 实现与公开信息依赖 | 初始己方 HP |
|---|---:|---|---|
| Shrinker Beetle | 38–40 | 原有 Shrink／攻击循环 | 15/25/40 |
| Fuzzy Wurm Crawler | 55–57 | 原有力量成长循环 | 15/25/40 |
| Nibbit（单只） | 42–46 | 原有格挡／力量循环 | 15/25/40 |
| **Bygone Effigy（精英）** | **127** | 初次睡眠→苏醒（+10 力量）→持续 15 基础攻击；Slow 按本回合每次出牌累计 10% 受击增伤，敌方回合开始清零 | **40/60/80** |
| **Byrdonis（精英）** | **91–94** | 16 基础俯冲与 3×3 啄击交替；Territorial 每个敌方回合结束增加 1 力量，多段攻击逐段应用力量 | **40/60/80** |

两种新增怪物直接复用已有原生精英工厂，不修改原生怪物血量或攻击数据。已核对本地引擎、能力实现及反编译参考。仍限单敌；没有附带开放召唤、状态牌、多敌或 Boss。

numeric 由 133 扩为 **145 维**，动作仍为 115。新增精英类型、Slow、Territorial、Slow 可推断计数、睡眠/多段攻击意图及精英行动历史。Slow 计数从公开的本回合出牌历史重建，不读取真实世界的私有能力计数器。每条模拟路径仍保持独立 RNG/牌序，搜索不修改真实卡牌 ID 分配器。

共 4 家族×5 遭遇×3 HP 档 = **60 组合**。验证 256 场和测试 150 场都覆盖全部组合，各组配额最多相差 1 场。精英约占场景的 40%；训练继续逐轮生成新配方和环境 seed。新训练种子空间增加固定偏移，新验证/测试 master seeds 为 174/272，与上一轮清单隔离。

Reward v3、两个模式联合晋级、10,000 次分层成对 bootstrap 和胜率保护条件不变。增加怪物不修改晋级门槛。正式预算：seed 42/43 **各 10 轮**；每轮 256 采样、200 更新、256 验证；采样/验证搜索 64/256；8 workers。配置总预算为 5,120 采样局、4,000 更新，实际数量以日志为准。

## 启动／恢复

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_hard.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --hard --iterations 10 --smoke --output output/az_hard_v2_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --hard --iterations 10 --output output/az_hard_v2 --workers 8 --smoke-evidence output/az_hard_v2_smoke/smoke_report.json
```

同一条正式命令用于恢复；运行锁拒绝重复协调器。smoke 两轮各 60 采样、4 更新、60 验证，16 搜索预算；覆盖全部 60 组合，不运行测试，不满足正式晋级样本量门槛。运行目录冻结配置、内容版本、schema 和代码摘要。

`output/az_hard_v2/progress.json` 是实时状态；`seed-*/evaluation-*.json` 保留总体和分层晋级结果。两个 seed 都到 10 轮后才冻结最终模型，并自动执行各 150 场初始/最终、纯网络/搜索测试。结束后生成 `report.json`，未晋级或未达学习增益也保留真实结果。

验收记录：786 项测试、8 个子测试通过；两轮 smoke 实际采样 120 场/1,912 决策、完成 8 次更新。双 seed 十轮正式运行已后台启动（启动时 PID 75500）。smoke 线性外推约 3.3 小时，不含最终测试，实际随战斗长度和缓存变化。机器可读快照见 `docs/az_hard_acceptance.json`；当前状态以运行目录日志为准，尚不报告最终成绩或学习增益。
