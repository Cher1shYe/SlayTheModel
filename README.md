# SlayTheModel — STS2 战斗策略研究工作区

当前快照：2026-10-17。目标是在明确支持的游戏规则范围内，构建使用公开信息、可审计、能泛化到合法卡牌与怪物组合的战斗策略模型。

## 项目结构

- `sts2-rl-agent/`：Python 战斗模拟、公开信息投影、粒子搜索、AlphaZero 风格采集/Replay/训练/评估，以及新增 Transformer。
- `sts2-cli/`：C# 游戏战斗接口与工具；具体运行要求见其 README。
- `probe/`、根目录 Python 脚本：本地接口和性能诊断工具。
- `AGENTS.md`：工作区协作规则。原始本地两个子目录是独立 Git 仓库；本远程分支保存普通目录形式的发布快照。

## 开发进度

旧 MLP 链路已有公开信息边界、粒子重建、合法动作约束、逐场 Replay、恢复与结果复算；内容逐批扩展至 G2.3e。G2.3e 双 seed 各三轮已完成，但整体学习增益未通过，聚焦 Boss 仍为零胜。工程执行完成不代表策略质量通过。

新路线以 [`spec_1.md`](sts2-rl-agent/spec_1.md) 为准：机制描述 + 两级实体 Transformer + 动态合法动作评分，避免随内容 ID 增加而扩大固定输入和策略分类层。

| 阶段 | 当前状态 |
|---|---|
| T0/T1 最小切片 | starter 三种基础卡和 Shrinker 已接入公开实体编码、动态动作头、五档模型及严格 checkpoint；19 项契约测试通过 |
| T0 既有内容审计 | 已扩展至 G2.3e 冻结范围：33 基础卡牌、63 升级变体、10 遭遇、10 怪物实体；逐项支持矩阵见扩展报告 |
| T2 | 已接入 G2.3e 的机制描述、公开实体、单选/原子多选、双敌/召唤/Boss 搜索重建、紧凑 Replay 与精确恢复；必要回归见扩展报告 |
| T3 | V7 S 两轮 smoke 与双 seed 各三轮完成；1,080 场、96 更新，工程与冻结 network 效用增益门槛通过。Boss 难例及通用质量仍未通过 |
| T4 | 自然后期课程与留出已冻结；新编排固定整场/后期 3:1、分池 Replay、更新级恢复和 network 效用验收，308 项本轮测试通过；未新训练 |
| T5 | 档位比较及独立质量验收尚未完成 |

当前 v2 架构五档精确参数量为 XS 1,059,554；S 5,671,522；M 16,221,154；L 41,372,514；XL 121,264,738。XS/S 已做真实批处理与契约检查；M/L/XL 仅参数实例化和形状验证，不宣称训练性能合格。历史 schema/权重不自动迁移。

## 当前目标与边界

1. T4 新运行编排已完成：每轮 135 整场/45 后期、batch 48/16，S smoke 两轮每轮 4 更新，正式双 seed 各三轮每轮 16 更新。保持实际 network V7 效用验收，支持完整轨迹、AdamW 更新和验证缓存恢复；双冠军共同冻结后才做留出诊断。未启动新训练，下一步仅在用户授权后执行 smoke 并汇报证据。详见 [T4 编排报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T4_RUNNER.md)。
2. 每次扩展明确列出 engine、observation、action、network、belief/search 和 tests 支持状态；未知机制必须拒绝。
3. 之后再冻结训练/验证/测试配方，评估未见组合与内容 ID 的泛化。未见机制测试只验证拒绝，不混入普通胜率。

目前没有“任意卡牌/怪物均支持”或“已达到通用高质量”的结论。奖励选卡、地图、商店及整局策略不属于首批目标。未获当次明确授权不启动训练实验或定时任务。

## 安装与必要测试

Python 项目依赖见 `sts2-rl-agent/pyproject.toml` 和锁文件，可用 uv 创建环境；Torch 实验依赖按该项目说明安装。已有 Windows 开发环境可运行：

```powershell
cd sts2-rl-agent
.\.venv-az\Scripts\python.exe -m pytest tests/test_az_transformer.py tests/test_az_information.py -q
.\.venv-az\Scripts\python.exe scripts/audit_az_transformer.py
```

第二条执行参数、公开夹具和合成梯度审计，不启动自对弈。详见 [T0/T1 交付报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T0_T1.md)、[资源原始报告](sts2-rl-agent/docs/transformer_t0_t1_audit.json)、[旧规格](sts2-rl-agent/spec.md) 和 [历史规格](sts2-rl-agent/spec_0.md)。已查看的夹具不能充当未见测试集。

新增 [T2 交付报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T2.md) 与 [T2 资源审计](sts2-rl-agent/docs/transformer_t2_audit.json)。可用 `python -m pytest tests/test_az_transformer_t2.py -q` 检查 Replay、动态搜索和恢复。该阶段测试只运行固定小夹具；后续 T3 实测结果见下文。

最新交付见 [G2.3e Transformer 扩展报告](sts2-rl-agent/docs/AZ_TRANSFORMER_G23E.md)、[逐项支持与资源审计](sts2-rl-agent/docs/transformer_g23e_audit.json)、[必要测试结果](sts2-rl-agent/docs/transformer_g23e_tests.txt)。836 项测试通过，覆盖 180 个训练配方完整轨迹、选择/生成/临时费用、召唤和 Boss 后续阶段，以及动态搜索、Replay 与恢复。人工夹具不计为自然战斗胜率；后续 T3 实测结果见下文。

## 快照说明

最新 [持续结束回合诊断与 V7 修订](sts2-rl-agent/docs/AZ_TRANSFORMER_V7_DIAGNOSIS.md)：历史网络贪心评估全部结束回合，旧 MCTS 在访问次数同票时忽略更好的 Q。新版按 visits → Q → prior 选动作，截断叶节点使用用户指定风险公式；同时更新整场 value 标签及 network 验收。521 项测试通过。同权重开局诊断从几乎全部结束回合改善为 255/256 出牌，不作为学习增益结论。

最新 [T3 V7 正式结果报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T3_V7_RESULTS.md)：S 两轮 smoke 和 seed 42/43 各三轮已完成，工件独立复算通过。最终 network 效用：seed 42 −1.000000→+0.325891，seed 43 +0.171655→+0.344832；均通过冻结门槛。每 seed 216 场测试中的 Boss 子集 54 场全部死亡，不能据总体提升宣称 Boss 已解决或通用质量通过。

[结果摘要与工件哈希](sts2-rl-agent/docs/transformer_t3_v7_results.json)保存逐轮晋级、network/search 分项、分遭遇结果、资源及统计局限。最终测试已查看，下一阶段需要新的独立组合/ID 留出。下一步是 T4；当前无训练任务运行，本次仅整理报告和更新文档。

本分支以当前源码、配置、测试和文档替换旧快照布局，保留 Git 提交历史。子项目来源和版权以各自 LICENSE/README 为准。虚拟环境、嵌套 `.git`、构建缓存、模型权重/训练输出、`.handoffs` 发布历史与本地任务状态不纳入本次快照。源码引用的游戏运行时资源仍需按各项目说明准备。
