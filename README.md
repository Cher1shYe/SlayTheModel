# SlayTheModel — v0.111.0 模拟器测试分支

`v111_simulator_test` 用于维护、验证本地这一版 C++ 模拟器，目标为《杀戮尖塔 2》**v0.111.0 / 41cef1ea**。本次按文件从 `v111_SF1` 的 `50d72a6` 提取模拟器更新，不包含新 ST-DT 网络、PPO 训练包、训练配置或权重。

## 分支分工

| 分支 | 用途 |
| --- | --- |
| **`v111_simulator_test`** | 本地模拟器版本、Python 接口、规则回归和信息隔离审计 |
| `v111_SF1` | 新 ST-DT 网络及训练实验；本次未修改 |
| `workspace_YE` | 另一条独立开发线；本次未合并、覆盖或推送 |

本分支基于共同历史提交 `bb2070f`，不是远端 `workspace_YE` 当前版本的升级。两套模拟器有不同的规则和接口演进，版本数字不能直接比较，也不能直接互换快照或权重。仓库沿用共同历史，已有的旧模组、旧网络目录仍保留；它们不是本分支的维护重点。此次只为旧调用方同步了必要的版本号和药水槽映射，没有引入新的网络结构或训练方案。

## 当前范围与限制

- 主要验证对象为铁甲单人；已接入另外四个角色的卡池和专属机制，用于跨角色内容与后续验证，不承诺所有角色完整原生等价。
- 已移植真实选牌/跳过、持续遗物状态、34 项此前缺失事件、Aeonglass/第三幕 Boss 池、账号解锁过滤、费用修正栈及奖励钩子。
- 提供 C++ 战斗与整局推进、MCTS、公开观察/动作、clone/快照，以及 `sts2_sim` Python 扩展。`macro_obs` 是模拟器的数据接口，不依赖神经网络。
- **严格 NoSL 检查尚未通过**：同名不同实例属性的牌、公开牌堆排序、`orbRng` 重采样存在已复现缺口。生产修复未实施，详见 [NoSL 审计](docs/mcts-nosl-audit-20261110.md)。
- 第三步起的规则主要按目标版本源码移植，缺少对应 DLL 执行验证；尚无完整同种子、同进度、同决策整局原生等价证明。

| 当前接口 | 版本 / 大小 |
| --- | --- |
| Ruleset | `native-41cef1ea-port-v6` |
| 公开观察 / 动作 / 快照 | v15 / v14 / v10 |
| 公开观察 / 战斗观察 | 75988 / 49252 维 |
| 卡牌 / 动作特征 | 631 / 727 维 |
| 实体观察 | `MACRO_OBS_VERSION=1` |

历史验证记录包括 36 个 C++ 程序通过、1000 局贪心冒烟无异常/截断及 6 张普通地图对照一致。它们只证明各自覆盖范围；本次独立导出的构建与检查结果见 [分支验证记录](artifacts/dev/cpp-native-aligned-20261031/validation/branch-export-20261110/README.md)。

## 获取与构建

建议单独克隆此分支，避免在有未提交训练文档的目录里切换：

```sh
git clone --branch v111_simulator_test --single-branch https://github.com/Cher1shYe/SlayTheModel.git SlayTheModel-simulator
cd SlayTheModel-simulator/artifacts/dev/cpp-native-aligned-20261031
```

构建需要 C++17 编译器和 Python 开发头文件。仓库已包含所需的 pybind11、nlohmann JSON 头文件。模拟器本身不需要 CUDA 或 PyTorch。默认 Python 回归另需 `numpy` 和 `pytest`；可选的旧 ArmG 接口检查（`run_checks.py --legacy-adapters`）还需要 PyTorch。

WSL2 / Linux（使用当前 Conda 环境的 Python）：

```sh
CXX=g++ python validation/build_local.py
```

macOS（已安装 Command Line Tools）：

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools CXX=/Library/Developer/CommandLineTools/usr/bin/clang++ SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk CPLUS_INCLUDE_PATH=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1 python validation/build_local.py
```

构建脚本生成 Python 扩展、`validation/` 下的回归程序和基准程序。换系统、Python 环境或源码后重新构建，不复制其他机器的二进制。本分支此次在 macOS 验证；WSL2 命令沿用当前模拟器的构建入口，未在此次导出中另跑 Linux 或原生 Windows 验证。

```sh
PYTHONPATH=simulator python -c 'import sts2_sim as sim; print(sim.PUBLIC_OBS_VERSION, sim.ACTION_SCHEMA_VERSION)'
./validation/bench run 1000
python validation/branch-export-20261110/run_checks.py --out-dir validation/local-check
```

`run_checks.py` 运行已编译的 C++ 回归、模拟器 Python 检查和整局冒烟；它不启动训练，也不代表 NoSL 已通过。每次需要保留结果时使用新的输出目录。已有地图对照脚本依赖原机器上的探针日志，仓库中的历史 6/6 结果不等于新克隆可以直接重跑这些外部日志。

## 接手与历史资料

- [AGENTS.md](AGENTS.md)：本分支工作范围、当前进度、下一步顺序。
- [分支导出说明](docs/simulator-branch-20261110.md)：来源、保留/排除范围与校验方式。
- [第二部分记录](artifacts/dev/cpp-native-aligned-20261031/validation/round4-step2-resume-20261108/README.md)、[第三至六步记录](artifacts/dev/cpp-native-aligned-20261031/validation/round4-step3-events-20261108/README.md)：按时间追加的历史记录；早期未完成项要结合后文看。
- [历史实机模组说明](docs/legacy-mod-readme.md)：共同历史中的 .NET 模组与 NativeWorker，不能当作本次 C++ 导出的实机验收。

仓库不包含游戏 DLL、完整游戏安装、模型权重、训练数据和本次编译产物；原生执行验证需要自行准备匹配版本的合法游戏安装。
