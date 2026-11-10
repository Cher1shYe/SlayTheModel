# v111_simulator_test 导出说明

日期：2026-11-10。用户决定把本地模拟器单独发布到新分支 `v111_simulator_test`，保留 `workspace_YE` 和 `v111_SF1` 各自的工作。

## 来源与边界

- Git 历史基点：`bb2070f0a4467f90333c81e98332be90f05baa4c`。
- 模拟器源码来源：`50d72a6`（`v111_SF1`）。只按路径提取模拟器和对应测试/证据，没有整体合并该提交。
- 查询到的远端 `workspace_YE`：`da987531d829086ed538f4ca3e0d561c68de50d7`。它比共同基点多 3 个提交，与本地有 50 个模拟器文件重叠修改；它的 v10 / obs20 / action17 / snapshot14 与本地 v6 / obs15 / action14 / snapshot10 是独立演进。本次未覆盖、整合或推送该分支。
- `v111_SF1` 的未提交文档和 NoSL 检查原件保留。本分支复制了 NoSL 审计的源码与文本结果，没有修复生产代码，也没有替换原目录的扩展模块。

## 本次包含什么

- `artifacts/dev/cpp-native-aligned-20261031/simulator/` 的规则更新、MCTS、Python 绑定、公开实体观察接口、生成器和 C++ 回归。
- 对应的 Python 接口测试、历史分轮文本证据与源码备份。
- 旧调用方的最小兼容变更：`agent/engine_identity.py` 的 ruleset；`agent/armg.py` 的特征版本与物理药槽索引；`agent/armg_train.py` 的观察版本检查。没有新的网络结构或训练算法。
- 本分支 README、根/子目录 AGENTS、NoSL 审计和此次导出验证记录。

## 本次不包含什么

- 新的 `model/spire_rl/`、ST-DT 训练设计与 `docs/configs/spire-rl-*.json`。
- 训练数据、训练曲线、检查点、原始权重、游戏 DLL/安装备份、可执行文件、扩展二进制与缓存。
- 远端 `workspace_YE` 新增的 ArmG PPO 实验和另一套模拟器修改。

共同历史中已有的旧 `model/`、旧 ArmG、实机模组和采集器保留，因此“只同步模拟器”指本次新增/更新的范围，不声称历史仓库从未存在模型代码。今后也不要整体合并训练分支来更新模拟器。

## 验证与未完成事项

本次从独立目录重新构建，源文件完整性与回归结果见 [验证记录](../artifacts/dev/cpp-native-aligned-20261031/validation/branch-export-20261110/README.md)。路径清单见 `simulator-export-paths-20261110.txt`，用于审核本次提交范围。

严格 NoSL 检查已有 7 项失败；第三步起规则缺对应 DLL 差分与完整整局对照。此次导出不会把这些缺口变为“已完成”。后续修复需要新验证记录与适当的接口/规则身份更新。

## 后续拉取

在专用的模拟器克隆目录中执行：

```sh
git switch v111_simulator_test
git pull --ff-only origin v111_simulator_test
```

原训练目录存在未提交修改时，不要强制切换、重置或覆盖。可以按根 README 另建克隆。根 `.gitignore` 会隐藏 artifacts 内新文件；新增源码必须按明确路径添加，避免把构建产物强制加入。

> 导出复验补记：仅同步两处旧 Python 测试替身的字段名（`potions` → `potion_belt`），使其匹配已有物理药槽 API；没有改测试期望、生产规则或网络代码。初次 8 项失败及修正后复验均保留在 `validation/branch-export-20261110/`。
