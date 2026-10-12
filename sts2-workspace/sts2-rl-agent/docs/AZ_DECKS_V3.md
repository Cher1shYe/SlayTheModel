# M6.2–M6.6 卡池扩展与持续训练

执行依据：`spec.md`（2026-10-09）。`spec_0.md`、旧配置、模型、Replay 和历史结果保持原样。

## 内容与构筑

新内容版本 `three-weak-decks-v1`，奖励 `win-timeout-hp-v3`，信息版本 `decks-information-v1`，编码 `az-decks-encoder-v1`。新运行从随机权重开始，拒绝旧内容或旧奖励 checkpoint/Replay。

白名单直接调用 `sts2_env/cards/ironclad.py` 的显式工厂；全部支持普通与升级版。数值清单冻结在 `configs/az_decks_v3/content_manifest.json`。

| 卡牌 | 完整机制及依赖 |
|---|---|
| STRIKE_IRONCLAD | 单目标伤害，力量与敌方易伤修正 |
| DEFEND_IRONCLAD | 格挡 |
| BASH | 伤害后施加易伤 |
| POMMEL_STRIKE | 伤害后抽 1/2 张；抽空后洗弃牌堆 |
| SHRUG_IT_OFF | 格挡后抽 1 张 |
| BLOODLETTING | 无视格挡自伤 3，获得 2/3 能量；允许致死 |
| INFLAME | 获得 2/3 力量，打出后离开普通牌堆；公开记忆追踪已用能力牌 |
| OFFERING | 自伤 6，获得 2 能量，抽 3/5 张，消耗；允许致死，支持满手与洗牌 |

初批没有选牌、生成牌、临时费用、临时能力或随机目标卡。上述机制和其他能力直接拒绝，不将候选阶段压成普通出牌。ARMAMENTS、ANGER 等依赖未纳入，未入池。

四个家族：starter（保留原始十张基础牌），cycle（Pommel Strike + Shrug It Off 抽牌攻防），strength（Inflame + Pommel Strike 的持续力量收益），burst（Bloodletting + Offering + Pommel Strike，以生命换取能量和抽牌）。非 starter 配方改变基础牌数量、加入家族牌并随机升级；家族按定义牌和允许牌校验。单牌组 6–20 张，同 ID 普通/升级合计至多 5 张；禁止零数量、布尔计数、重复条目、未知卡和缺少家族定义牌。生成器当前只产生该边界内的子集。

## 信息和编码

牌的 ID 和升级状态使用局部词表 token，完全不使用全局实例 ID。手牌 10 个槽、每槽 14 个数值；numeric **133 维**；动作仍为 115。编码包含初始公开牌组、抽/弃/消耗组成、已使用能力牌、本回合打牌类型计数、力量、双方初始 HP 等。20 张牌组按组成完整编码，不截断为十张。

抽牌堆组成通过初始牌组和公开牌堆变化推断，不读取真实未知牌序。每条搜索路径保持独立粒子的未知牌序及 RNG，保留引擎随机流别名；粒子重建和特征模板工厂均还原全局卡牌 ID 分配器。抽牌可能在同回合再次抽回已打出的牌，因此重建本回合打牌历史不再错误要求其全部位于弃牌堆。

## Reward v3 与分层

统一终局函数：胜 `0.8 + 0.2*h`，超时 `-0.2 + 0.4*d`，死亡 `-1 + 0.2*d`。`h` 使用本场己方初始 HP；`d` 使用实测敌方初始 HP，不使用最大 HP 代替。异常与 NaN 拒绝结算。真实胜负优先于同一步达到预算上限。搜索深度截断使用价值预测，不生成战斗超时。

HP 档 **15、25、40/80**，三个已有单敌遭遇 × 四个家族 × 三档 HP，共 36 个组合。固定验证 256 场、测试 150 场，覆盖全部 36 组合，配额相差至多一场；不按胜负筛选。仍保留 starter 40 HP 基础场景。

训练每轮按 master seed、轮次和 job 坐标产生新配方。环境 seed 使用注入式坐标编码，训练、验证、测试保留不相交空间；配方随机源使用稳定用途哈希。每轮实际清单及内容哈希保存在 `seed-*/manifests/train-*.json`；恢复按 job 坐标生成，与已提交 job 数量无关。生成配置、固定 manifest 和 schema 在运行目录再次冻结。

Replay 保留 200,000 决策，整局提交／去重／淘汰，按家族与遭遇、episode、决策分层抽样。记录敌方初始/最终/最大 HP，重新计算所有 value 标签。新运行使用 OS 进程锁，异常退出由 OS 释放锁，避免两个协调器写同一目录。

## 运行和恢复

本仓库使用 `.venv-az/Scripts/python.exe`。在项目根目录执行：

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_decks.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --smoke --output output/az_decks_v3_smoke_r2 --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --output output/az_decks_v3_r2 --workers 8 --smoke-evidence output/az_decks_v3_smoke_r2/smoke_report.json
```

恢复使用与首次启动完全相同的最后一条命令。若原进程仍在运行，锁会拒绝重复启动。代码、运行环境、冻结配置或清单改变时拒绝恢复；不能删除失败记录后重用目录。smoke 证据绑定引擎/训练模块与入口脚本摘要。修复代码后需新目录重新 smoke。

smoke：一组 seed、两轮，每轮 36 场采样、4 次更新、36 场验证，采样/评估预算 16。回合/动作上限仍为 100/400。36 场验证不满足 256 场正式晋级门槛，不能作为学习增益证据；不运行最终测试。

长期入口：seed 42/43 各 50 轮；每轮采样 256、更新 200、验证 256；采样/评估搜索 64/256；8 workers、每进程 CPU 推理线程 1；其余默认与 spec 一致。两 seed 按完整轮次交替执行。候选拒绝仍继续，异常停止并记录，轮数到顶停止；不自动调参或增加预算。

晋级每种模式均按家族×遭遇×初始血量分层进行 10,000 次成对 bootstrap；效用 CI 下界必须为正，胜率 CI 下界为正或逐场胜负标记完全一致。纯网络、搜索两模式均通过才晋级。旧汇总只检查搜索模式的问题已修复；旧实验产物不重写。

两组冠军冻结后才评估各自初始/最终模型的纯网络及搜索模式，每 seed 同一组全新 150 场。自动保存原始量、总体与家族/遭遇/HP/交叉组合报告、随机合法基线；旧规则基线明确标为不兼容。未晋级或无增益也照实生成报告。

## 产物与状态

- `output/az_decks_v3_smoke_r2/smoke_report.json`：两轮 smoke 的实际采样、更新、吞吐和粗略耗时估计。
- `output/az_decks_v3_r2/progress.json`：当前 seed、轮次和阶段。
- `output/az_decks_v3_r2/seed-*/state.json`：可恢复状态；`champion.json` 指向可加载冠军。
- `output/az_decks_v3_r2/timings.json`、`seed-*/evaluation-*.json`：阶段耗时和完整晋级记录。
- `output/az_decks_v3_r2/frozen_final_models.json`：仅在两个 seed 全部结束后生成。
- `output/az_decks_v3_r2/report.json`：仅在最终评估结束后生成，分别报告工程、训练、成绩和学习增益。

M6.2–M6.4 的实现和机制测试已完成；M6.5 是否完成须以实际轮次日志为准；M6.6 必须等待两组模型冻结和最终测试，不提前标记完成。

首次正式启动在验证清单选择时停止，尚未采样或更新。旧选择器无法处理 256 场分布到 36 组的非整除配额；已修复为按家族/遭遇/HP轮询、跳过已用尽配额，并增加完整 256 场及两个默认 seed 初始化回归。首次错误和初始 checkpoint 保留在 `output/az_decks_v3`，对应旧 smoke 保留在 `output/az_decks_v3_smoke`；当前代码重新运行 smoke 后使用上述 `_r2` 新目录。

2026-10-09 实测：353 项测试和 8 个子测试通过；当前代码的两轮 smoke 实际采样 72 场/1,025 决策、8 次更新。正式运行已启动（启动时 PID 75476），两 seed 初始模型均创建，按完整轮次交替推进；M6.5 仍在运行，M6.6 尚未开始。smoke 线性预算估算约 17.9 小时（不含最终测试，非完成时间承诺）。验收快照见 `docs/az_decks_v3_acceptance.json`，实时状态以运行目录日志为准。
