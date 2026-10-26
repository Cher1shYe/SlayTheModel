# 本机部署与项目对比

日期：2026-10-26。部署的是 Jialeiv/sts-rl-agent 的 **Ironclad A0 主线模拟器版本**，不是 Defect A20 分支或 Steam 游戏自动操作服务。

## 已部署内容

- 源码：`D:\project\sts\sts-rl-agent`，提交 `039c199933b7d3a2e5d8fde51ae77a9175e1031f`，源码仓库保持干净。
- 模拟器：`D:\project\sts\simulator`，基于 `7476a81954020087da31d41d16fddf475746ec2d`，应用上游 `sim_rl_hooks.patch` 和 `combat_rules.patch`。
- 环境：`D:\project\sts\.venv`，Python 3.12.13，继承 `D:\miniconda\envs\sts` 的 PyTorch 2.12.0+cpu。该环境依赖基础 Conda 环境继续存在；未修改基础环境。
- 编译器：本机 Visual Studio Build Tools 2026 / MSVC x64；CMake 4.4.4。
- Python 扩展：`simulator\build312\Release\slaythespire.cp312-win_amd64.pyd`。
- 模型：仓库附带 `weights\armG_model_G128x128_15k.pt`，实测 116,609 参数，412 维观察 + 368 维候选描述，隐藏层 128/128。
- json 子模块固定上游版本 `0b345b20c888f7dc8888485768e4bf9a6be29de0`；pybind11 升至 `v2.13.6`（`a2e59f0`）以适配 Python 3.12。

## 运行

PowerShell：

```powershell
& D:\project\sts\Run-Agent.ps1 -Seeds '1,2' -Simulations 100
```

`-Simulations` 是每次有多个合法战斗动作时的 MCTS 搜索预算。可改为 2000；`-Seeds` 接受逗号分隔的整数。默认输出 `deployment\smoke.json`，可用 `-Output` 指定另一文件。这是无界面的完整模拟对局，运行结束即退出；没有后台服务。

启动器正确定位模拟器、词表、Python 模块和权重，使用上游非战斗策略及原生 `mcts_recommend`。它遇到异常、未结束的超长对局或无合法动作会失败，而不会像上游部分评估脚本的 `except Exception: pass` 一样把异常悄悄变成楼层结果。

重新编译并运行规则回归：

```powershell
& D:\project\sts\deployment\Rebuild.ps1
```

## 验收证据

- 上游 `sim_patch/tests`：**17/17 通过**。涵盖血液药水、铁斩波、无牌状态、毒伤及死亡时序等。
- `deployment/smoke.json`：种子 1 到第 50 层后死亡，22 场战斗、389 个战斗动作、103 次非战斗决策；种子 2 到第 24 层后死亡，14 场战斗、227 个战斗动作、46 次非战斗决策。均完整结束，搜索预算 100。
- 这是部署/集成验收，不是统计性能评估。没有重新运行上游 50 种子基准，也没有训练新权重。
- 上游已注明其公开成绩产生于战斗规则补丁之前；本部署包含修复，不能把旧成绩直接当成本机结果。

## Windows 适配

1. Git 的自动 CRLF 转换导致补丁解析失败；在 deployment 内保留 LF 版本后应用。
2. CMake 按 MSVC 分支使用 `/O2 /EHsc /bigobj`，不传 GCC 专用参数。
3. `fixed_list` 使用 `std::array::data()` 返回指针，避免把 MSVC 迭代器隐式当指针。
4. 地图生成的非标准变长栈数组改为 vector 存储加指针；数量与原有循环不变。
5. 补全 `<chrono>` 头文件；把实际定义为 struct 的类型前向声明统一为 struct，修复 MSVC 链接符号不一致。
6. Python 绑定升级至 pybind11 v2.13.6。

`deployment/simulator-local.patch` 保存相对固定模拟器提交的完整差异（**已包含两份官方补丁**，不可重复叠加）。子模块版本另外记录在 `deployment/versions.json`。本次初始完整 clone 因网络中断失败，已改用浅克隆的 simulator 目录完成部署。

## 与 sts2_compactformer/sts2-rl-agent 的区别

对比的是本机当前工作目录内容，而不只是 Git 提交。对方工作区 HEAD 为 `b713986`，存在 PPO、GRPO、原生桥接等未提交修改；本次只读检查，没有更改或启动其训练。

| 维度 | Jialeiv/sts-rl-agent | 本机 sts2_compactformer/sts2-rl-agent |
|---|---|---|
| 游戏 | 杀戮尖塔 1；本次部署战士 A0 | 杀戮尖塔 2 |
| 主要学习任务 | 完整爬塔中的选路、选牌、商店、休息、事件 | 主要发展战斗策略与价值学习；仓库也保留 Python 整局/环境代码 |
| 当前成功主线 | 非战斗 MLP + 原生 MCTS 战斗 | 原生战斗状态/动态动作 → Transformer；有 AlphaZero、PPO、GRPO 路径 |
| 网络输入 | 固定 412 维状态拼接 368 维候选描述 | 属性哈希/数值编码为实体；可变实体及合法动作集合 |
| 网络结构 | 共享 128/128 ReLU MLP 为每个非战斗候选打分 | NativeTransformer：实体 TransformerEncoder，动作对状态的交叉注意力，策略头与价值头；XS 为 4 层、宽度 128、4 heads |
| 战斗动作 | 主线完全由 ScumSearch/MCTS 选择 | AZ 路径可用模型指导 MCTS；PPO 轨迹要求 simulations=0，由当前策略采样；GRPO 做组内相对回报学习 |
| 主线训练 | REINFORCE，最终楼层稀疏回报、移动基线 | AZ 用搜索策略/终局监督；PPO 有策略及价值训练；GRPO 无 critic 回归且冻结价值头 |
| 引擎 | 独立 C++ sts_lightspeed 重实现 + pybind11 | Python 模拟器与 C#/Godot 原生采集路径共存；原生路径需要对应游戏程序集和 ABI |
| 奖励/评估目标 | 整局楼层、通关率 | 战斗胜负、HP/风险/回合成本、V7 等版本化指标，按所选算法配置 |
| 数据与恢复 | 主线研究脚本较简洁，部分脚本吞异常；Defect 分支另有更完整恢复逻辑 | 原生轨迹验证、模型/来源摘要、逐场缓存、冻结验证、优化器/RNG 恢复更丰富 |
| 实机桥接 | Java 游戏 + ModTheSpire/BaseMod/CommunicationMod + RNG 导出 | C#/Godot 原生模组与 worker/网络策略桥接 |
| 可复用性 | 思路、候选评分方法、实验对照 | 不能直接载入对方权重、状态 schema、动作 ID 或 replay |

依据文件：Jialeiv 仓库的 `agent/armG_train.py`、`agent/armG_train_parallel.py`、`eval/armB_blind.py`、`combat_experiments/armB_selfplay.py`；本机项目的 `sts2_env/az/native_transformer.py`、`transformer_network.py`、`ppo.py`、`grpo.py`、`scripts/run_native_ppo.py`、`docs/GRPO_NATIVE.md`。这些是代码能力的比较，不等于已证实哪种算法更强。

## 如何理解对方的结果

上游报告：战士 A0、相同 50 个种子、相同 50000 战斗搜索预算，启发式非战斗为平均 31.2 层/6% 通关，学习非战斗为 42.5 层/14% 通关。这支持非战斗决策的价值，不能用来证明它的战斗网络优于你本地模型。

其六类战斗学习实验未达到相应搜索基线，包含模仿、DAgger、RL、attention、value lookahead 和引导搜索；仓库实际上也有 `armB_selfplay.py`，因此不能说它完全没有 AlphaZero/自对弈代码。未来牌序信息不对称、模型/训练预算、目标和引擎都会影响结果；这些负结果不能推出“网络学不会战斗”。

Defect A20 是独立扩展，输入和权重不同，训练未完成；保留的评估无 Heart 胜利。本次没有部署该扩展，也没有把它的结果混入战士主线。

对你的项目，最值得借鉴的是：给完整爬塔单独增加轻量非战斗策略层；用“固定战斗策略、只替换非战斗策略”的消融验证收益；做相同预算下的纯网络/盲搜索/网络引导搜索对照。若目标仍是战斗模型能力，继续在现有 STS2 原生 Transformer/PPO/GRPO 基础上做配对评估更直接。

Steam 真游戏自动操作尚未部署或验收：需要 STS1 及对应 Java 模组；本次完成的是能够实际运行的无界面模拟器版。

上游来源：https://github.com/Jialeiv/sts-rl-agent 。
