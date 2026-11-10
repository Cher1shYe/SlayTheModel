# v0.111.0 C++ 模拟器

本目录是 `v111_simulator_test` 的当前模拟器源码。入口说明、构建命令与分支分工见 [仓库 README](../../../README.md)，接手约定见 [AGENTS.md](AGENTS.md)。

| 目录 | 内容 |
| --- | --- |
| `simulator/include`、`simulator/src` | 规则、战斗、整局推进、MCTS、观察、快照 |
| `simulator/bindings` | `sts2_sim` Python 接口，包括独立的实体观察接口 |
| `simulator/content`、`simulator/tools` | 数据表与生成源 |
| `simulator/tests`、`tests` | C++ 与 Python 回归 |
| `validation`、`native-*-fixtures` | 分轮验证记录与已有原生样例 |
| `agent`、`deployment` | 共同历史中的旧策略/训练工具，不是本分支的新开发入口 |

当前 ruleset `native-41cef1ea-port-v6`，观察/动作/快照 v15/v14/v10。目标 DLL 与源码身份见 `PORT_SOURCE.json`。**未证明完整原生等价，严格 NoSL 审计尚未通过。**

- [此次导出检查](validation/branch-export-20261110/README.md)
- [NoSL 失败复现](validation/nosl-audit-20261110/README.md)
- [第二部分历史](validation/round4-step2-resume-20261108/README.md)
- [后续步骤历史](validation/round4-step3-events-20261108/README.md)
- [旧模拟器与训练说明归档](docs/legacy-simulator-training-readme.md)：仅保留原文供历史查阅，其中性能、兼容性和旧训练命令不能作为本分支的新验收结果。

模拟器编译和纯接口使用不依赖 PyTorch/CUDA；新 ST-DT 训练包在另一分支，不随此次导出提供。
