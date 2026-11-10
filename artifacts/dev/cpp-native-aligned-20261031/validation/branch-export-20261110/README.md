# v111_simulator_test 独立导出验证

日期：2026-11-10。平台：macOS ARM64，Python 3.11.7，Command Line Tools clang。从独立工作目录完整重建，没有复用原项目的对象文件，也没有替换原项目中的 Python 扩展。

## 结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 模拟器文件与 `50d72a6` 对比 | 240 个已跟踪文件完全一致 | `source-scope.json` |
| 排除新网络 / 配置 / 训练文档 | `model/` 等排除路径相对 `bb2070f` 无变化；无 `model/spire_rl` | `source-scope.json` |
| 完整构建 | 成功；测试断言保持开启；约 103 秒 | `build.json`、`build.log` |
| C++ 回归 | 36/36 程序通过 | `cpp-*.txt`、`summary.json` |
| Python 接口及旧兼容检查 | 98 通过 | `python-interface.txt` |
| 贪心整局冒烟 | 1000 完成，0 异常，0 截断；平均 9.6 层，0 胜 | `bench-1000.txt` |
| 严格 NoSL | 本次未重跑；保留原 15 项中 7 项失败的审计；生产代码未修 | `../nosl-audit-20261110/` |
| 新 DLL 差分 / 完整原生整局 | 本次未运行 | 不作等价声明 |

冒烟约 76.6 局/秒，仅为本机当时贪心引擎吞吐，不是神经网络训练速度或通关能力。旧地图 6/6 记录依赖外部探针日志，此次未重跑。

## 初次 Python 失败及处理

初次为 90 通过、8 失败：两个测试文件的 `SimpleNamespace` 仍构造旧 `potions` 字段，而已有候选接口读取含空位的 `potion_belt`。只把这两处测试替身字段改为实际接口名，原断言不变；重新运行同一组 98 项全部通过。没有修改生产代码、原生 fixture 或网络实现。

初次日志与总表保存在 `python-interface-initial.txt`、`summary-initial.json`。C++ 和冒烟已通过，后续只重跑受影响的 Python 检查，没有重复构建与整局测试。

## 复现

从开发副本根目录执行。`build.py` 与原 `validation/build_local.py` 的编译步骤相同，只把本次构建报告放到这里。新一轮需要保留证据时先复制到新的 validation 子目录，不能覆盖本目录的归档结果。

```sh
CXX=g++ python validation/branch-export-20261110/build.py
python validation/branch-export-20261110/run_checks.py --out-dir validation/local-check
```

第一行用于 Linux/WSL2；本次实际 macOS 构建使用已安装的 CLT clang，并显式提供 SDK 与 C++ 标准库头文件目录（根 README 给出对应环境变量）。`build.json` 中的 `/private/tmp/.../cxx` 是本次临时包装器，内容为执行 CLT clang 加 `-isysroot .../MacOSX.sdk -isystem .../MacOSX.sdk/usr/include/c++/v1` 后透传参数，未修改系统设置。

默认 `run_checks.py` 只检查模拟器接口，不需要 PyTorch。此次还运行了已有 ArmG 兼容检查，可用 `--legacy-adapters` 开启，需要 PyTorch。Mac 原环境的 OpenMP 冲突仅对此次进程设置 `KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1`，没有改全局环境。归档 `summary.json` 对应含旧兼容检查的完整选择。

本目录只提交文本日志、源码和元数据，不提交对象文件、可执行文件或扩展二进制。
