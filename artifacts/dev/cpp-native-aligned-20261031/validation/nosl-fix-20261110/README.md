# NoSL 修复（G1）与宏观观察 v2（G3）

日期：2026-11-10。对应审计：`../nosl-audit-20261110/`（修复前证据，未改动）。总体诊断与方案：仓库根 `docs/claude-run1-diagnosis-and-fix-plan-20261110.md`。

## 改动

| 文件 | 内容 |
| --- | --- |
| `simulator/include/sts2/common.h` | 新增 `card_public_key`（玩家可见的全部卡牌字段，恰好对应 `push_card_instance` 输出；前 19 项与旧 `visible_choice_key` 同序）和 `card_canonical_less`（公开键 + 原始费用字段 + 费用修正栈，除 UID 外的全序） |
| `simulator/src/observe.cpp` | `visible_choice_key` 改为调用 `card_public_key`（补 `bonusBlock`、`retainThisTurn`、`slyThisTurn`、`slyThisCombat`） |
| `simulator/src/battle.cpp` | `resample_hidden` 抽牌堆/弃牌堆先按 `card_canonical_less` 排序再洗，并重置 `orbRng`；`init` 从运行级 RNG 第 10 号流（`RunRngType.CombatOrbs`）取 `orbRng`，无运行 RNG 时用 `seed ^ 0x3C6EF372` |
| `simulator/src/run.cpp` | `finish_combat` 把 `orbRng` 写回 `runRng[RNG_COMBAT_ORBS]`；战斗快照校验补 `orbRng` |
| `simulator/include/sts2/macro_obs.h`、`src/macro_obs.cpp` | 宏观观察 v2：候选第 5 个数值 = 该 `SELECT_GRID_CARD` 会取消一张已选的牌 |
| `simulator/bindings/bindings.cpp`、`agent/engine_identity.py`、`PORT_SOURCE.json` | ruleset `native-41cef1ea-port-v7` |

原生依据：`MegaCrit/sts2/Core/Runs/RunRngSet.cs` 的 `CombatOrbGeneration => GetRng(RunRngType.CombatOrbs)`，由 `Models/Cards/Chaos.cs` 与 `Models/Powers/TrashToTreasurePower.cs` 使用；与其他运行级流一样在 `RunRngSet` 构造时按名称创建，C++ 的 `runRng[i] = Rng(seed, RUN_RNG_NAMES[i])` 已对应。**该映射按源码实现，未用目标 DLL 执行验证。**

**随机序列变化（需记录）**：持有 Chaos / Trash to Treasure 时，随机球结果与 v6 不同（v6 每场从 `Rng(0)` 起步，与原生不符）。MCTS 重采样对含成长/特殊状态牌的局面会得到不同样本。因此旧 v6 归档不能保证在 v7 上逐步重放一致；新实验必须使用新 run 目录。公开观察布局不变，仍为 v15（只在原先并列时多用 4 个字段排序；升 v16 需改旧 ArmG 代码中的硬检查，按约定不动，语义变化由 ruleset 升级标记）。

## 验证（本机 macOS arm64，Apple clang 21 / Command Line Tools，Python 3.11.18）

| 项 | 结果 | 文件 |
| --- | --- | --- |
| 原审计探针（`probe.cpp`，原样复制） | 15 项 0 失败（修复前 7 失败）：同名成长牌 0/100 不同样本、0/24 根动作不同；`orbRng` 重采样后两份状态输出相同、100 次采样出现 5 种球、0/24 根动作不同；`bonusBlock`/`retainThisTurn` 公开牌堆不变；已知顶牌保留 | `probe.txt` |
| 新增探针（`probe_extra.cpp`） | 20 项 0 失败：`slyThisTurn`、`slyThisCombat`、`bonusBlock`、`retainThisTurn`、`bonusDamage`、仅费用修正到期不同（玩家看不到）六种情况下，公开牌堆不变、抽牌堆与弃牌堆重采样与真实顺序无关；战斗从运行级 CombatOrbs 流开始；重采样替换该流 | `probe_extra.txt` |
| 旧重采样测试 `hidden_resampling` | 通过（6000 次） | `hidden_resampling_control.txt` |
| C++ 回归 | 36 个程序 0 失败 | `cpp-tests.json`、`cpp-logs/` |
| Python（torch 桩） | 167 通过、10 失败、34 错误；失败/错误集合与 2026-11-09 记录**逐项相同**（缺 torch/cmake 等环境原因），无新增 | `pytest-no-torch.txt` |
| 1000 局贪心冒烟 | 0 异常、0 截断；平均层数 9.6、5570 场战斗、85525 步，与上一轮记录完全相同。速度 105–124 局/秒（上一轮 150），测量时系统后台进程占用约 70% CPU；贪心冒烟不经过本次修改的代码 | `bench-1000.txt` |
| 普通地图对照 | 6/6 与原生录制一致 | `map-parity.txt` |
| `model/spire_rl` 测试 | 24 项通过（ruleset v7、宏观观察 v2、候选 5 维） | — |
| G3 真实状态检查 | 用训练期构建重放 2 局 Sea Glass 循环到网格并保存快照（第 3 局跨平台在第 26 步分叉），在新构建上恢复：原循环动作在第 64 个网格决策以 `menu_loop` 截断、保留末状态；其中 27–28 个动作被识别为“取消” | `artifacts/analysis/claude-run1-20261110/seaglass/g3_check.json` |

注意：
- 新增探针只在修复后运行，没有对修复前代码编译验证“修复前会失败”；原审计探针有修复前（7 失败）与修复后（0 失败）对照。
- Linux / WSL 构建与本目录检查尚未执行（`CXX=g++ python validation/nosl-fix-20261110/run_checks.py` 可运行，会在本目录 `obj/` 编译自己的对象文件）。
- 本次没有做 DLL 实测或完整原生整局对照；NoSL 修复不等于规则原生等价。

## 复现（副本根目录）

本机默认 Xcode 入口需要接受许可，构建改用 Command Line Tools；`build_local.py` 把 `CXX` 当成单个可执行文件，所以用一个包装脚本传 SDK 参数：

```sh
cat > /tmp/clangxx <<'EOF'
#!/bin/sh
exec /Library/Developer/CommandLineTools/usr/bin/clang++ -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -isystem /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1 "$@"
EOF
chmod +x /tmp/clangxx
export DEVELOPER_DIR=/Library/Developer/CommandLineTools CXX=/tmp/clangxx
PY=~/micromamba/envs/sts2/bin/python
$PY validation/build_local.py
$PY validation/nosl-fix-20261110/run_checks.py          # 会重写本目录 probe*.txt 与 results.json
$PY validation/nosl-fix-20261110/run_cpp_tests.py       # 会重写本目录 cpp-tests.json 与 cpp-logs/
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=$PWD/validation/round4-step3-events-20261108/python-no-torch/torch-stub \
  $PY -m pytest -q -rfE -p no:cacheprovider --continue-on-collection-errors tests/
./validation/bench run 1000
$PY validation/round4-step3-events-20261108/map-parity/compare_maps.py
```

构建后扩展 SHA-256：`1499c6c9db0dcd231c8ac0114a6c7fe4fbe028f07a73913339e6f6f7913b19ec`（本机，跨平台不同）。

## 上传

`artifacts/` 被根 `.gitignore` 忽略。本目录中的源码与文本（`README.md`、`probe.cpp`、`probe_extra.cpp`、`run_checks.py`、`run_cpp_tests.py`、`*.txt`、`*.json`、`cpp-logs/`）需要按清单强制添加；不要上传 `probe`、`probe_extra`、`hidden_resampling_control` 可执行文件或 `obj/`。改过的已提交源码（上表）git 能直接看到。
