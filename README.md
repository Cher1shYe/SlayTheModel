# SlayTheModel — STS2 战斗策略研究工作区

当前快照：2026-10-16。目标是在明确支持的游戏规则范围内，构建使用公开信息、可审计、能泛化到合法卡牌与怪物组合的战斗策略模型。

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
| T0 全内容审计 | 尚未覆盖 G2.3e 全集；当前网络只开放明确的 starter 白名单 |
| T2 | starter 白名单内已接入紧凑 Replay、逐节点动态搜索、既有协调器与确定性恢复；串并行和中断契约验证通过，详见 T2 报告 |
| T3 | 待单独授权：S 两轮 smoke，seed 42/43 各三轮验证 |
| T4/T5 | 组合扩展、复杂选择、Boss 难例、档位比较及独立质量验收尚未完成 |

五档精确参数量为 XS 1,029,666；S 5,587,234；M 16,049,698；L 41,081,122；XL 120,635,170。XS/S 已做真实前后向与更新检查；M/L/XL 仅参数实例化和形状验证，不宣称训练性能合格。

## 当前目标与边界

1. T2 starter 接口已闭环；下一步扩大 G2.3e 对齐内容的机制覆盖，并冻结实验配方和资源配置。
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

新增 [T2 交付报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T2.md) 与 [T2 资源审计](sts2-rl-agent/docs/transformer_t2_audit.json)。可用 `python -m pytest tests/test_az_transformer_t2.py -q` 检查 Replay、动态搜索和恢复。该测试只运行固定小夹具；本次没有启动 S smoke 或正式训练实验。

## 快照说明

本分支以当前源码、配置、测试和文档替换旧快照布局，保留 Git 提交历史。子项目来源和版权以各自 LICENSE/README 为准。虚拟环境、嵌套 `.git`、构建缓存、模型权重/训练输出、`.handoffs` 发布历史与本地任务状态不纳入本次快照。源码引用的游戏运行时资源仍需按各项目说明准备。
