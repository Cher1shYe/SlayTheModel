# STS2 C++ 模拟器与 PPO 训练

更新日期：**2026-11-05**。本分支根目录来自 `sts2-workspace_YE/artifacts/dev/cpp-native-aligned-20261031` 的当前源码快照，整体替换原 `alphazero` 文件树，不混入旧分支文件。发布的是源码、测试和文档；游戏 DLL、模型权重、本机编译产物与缓存不随仓库分发。

C++ 引擎负责游戏状态推进、战斗、整局流程和搜索，Python/PyTorch 负责策略与训练。当前主要验证目标是铁甲战士单人强化学习；其他四角色内容已接入，但不能将条目存在或主效果测试等同于完整规则等价。

## 当前进度

- 内容清单包含 596 张卡牌、66 种药水、300 件遗物。覆盖清单已修正：**368 张卡没有自动化测试文本引用**；不再采用此前“全部条目均已测”的错误结论。详见 [内容清单](validation/rl-audit-20261105/content-inventory-20261104.md)。
- 已修复遗物选牌网格、药水物理槽、Pounce 免费技能、公开卡牌状态、MadScience 变体、隐藏牌堆重采样顺序，以及启发式非法动作等已复现问题。
- 本次跟进修复：PPO 异常局状态名、need-rules 采样与训练概率一致性、Boss 搜索预算重复乘三倍、长循环访问记录、进程池中断后的重试与保存、串并行逐局种子一致性。
- 内部验证包含牌组 Elo 奖励，`best.pt` 按完整验证奖励选取；只有全部验证局正常结束才更新最佳模型。
- 当前身份：ruleset `native-41cef1ea-port-v10`，公开观察 v20 / 83208，战斗公开观察 49972，动作 schema v17 / 729，ArmG feature v9，snapshot v14，trainer v2。

最新状态见 [PORT_STATUS.md](PORT_STATUS.md)，机器可读身份见 [PORT_SOURCE.json](PORT_SOURCE.json)，本轮详情见 [修复与验证报告](validation/rl-fixes-20261105/README.md)。历史文档中的旧布局、训练方法和旧成绩不代表当前状态；部分历史路径指向原工作区外部资料。

## 已完成的本机验证

| 检查 | 结果 |
| --- | --- |
| 最终完整构建 | 成功 |
| CTest | 42/42 通过 |
| Python 测试 | 444 通过、17 跳过（可选历史资产缺失） |
| 铁甲 A0 / A10 冒烟 | 各 202 局，共 404 局；0 异常、0 截断 |
| need-rules PPO 短程验证 | 2 workers，8 局训练 + 2 局验证，正常完成 |

证据：[CTest](validation/rl-fixes-20261105/ctest-complete.txt)、[pytest](validation/rl-fixes-20261105/pytest-complete.txt)、[整局冒烟](validation/rl-fixes-20261105/smoke.json)、[PPO 指标](validation/rl-fixes-20261105/ppo-smoke/metrics.jsonl)。404 局使用启发式局外决策和 greedy 战斗，0 胜；这是稳定性验证，不是模型胜率证明。首轮中断日志不作为通过证据。

## PPO 与奖励

`agent/armg_train.py` 使用 actor-critic PPO，只学习**局外决策**。战斗由固定控制器执行，并未在此训练战斗策略。

正常终局（含死亡）的总奖励为：

```text
R = Σ_i (L_i × i / 20 + E_i × i / 10)
    + Σ_{k=1..B} k / 2
    + 0.05 × U + 0.02 × D
    + 平均牌组 Elo / 600
```

- `i` 是幕数；`L_i` 是该幕到达的最高层数，`E_i` 是该幕击败的精英数。
- 第 k 个 Boss 额外加 k/2，四个累计 +5。
- `U` 仅统计火堆实际升级次数，`D` 仅统计商店实际删牌次数。
- Elo 按永久牌组统计；打击、防御、痛击及缺失 Elo 牌按 1150，升级牌沿用原牌 Elo。
- 多人专用牌、诅咒、状态、衍生、事件牌、腐化、Break、GRAPPLE 不计入 Elo 分子或分母；空集合奖励为 0。
- 错误与截断局不作为正常终局进入 PPO 更新。

训练及评估采用 `SINGLE_PLAYER_TRAINING` 内容配置：**排除水晶球事件与多人专用卡牌**。该配置改变原生内容分布。水晶球完整规则暂不作为本轮修复目标。

`mcts-oracle` 会读取完整战斗状态及未来 RNG，成绩不能称为纯玩家可见信息策略；`mcts-resampled` 对隐藏状态重采样。搜索预算为 `base + per_floor × (floor−1) + elite/boss 增量`，没有隐式 Boss 三倍。

## 构建与测试

需要 Python（本机验证为 3.12）、C++17 编译器、CMake。Windows 可在 Visual Studio x64 开发者终端中使用 Ninja：

```powershell
python -m pip install -r requirements.txt
python -m pip install cmake ninja
cmake -S simulator -B simulator/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build simulator/build --parallel 4
ctest --test-dir simulator/build --output-on-failure
python -m pytest -q tests
```

扩展默认输出到 `simulator/`，由 Python 层加载。正在使用扩展的 Python 进程应退出后再重新链接。仓库中已包含 pybind11 构建所需文件。历史日志中的 `build-win`、绝对路径和工具版本属于验证机器，不是通用安装路径。

## 训练入口

Elo 冻结快照需单独准备，目录中包含 `cards.json` 和 `manifest.json`；当前默认路径指向原机器，换机器应显式传入 `--elo-data`。缺失文件会报错，不能把“单张卡缺 Elo 按 1150”当成整份快照缺失时的回退。

```powershell
python -m agent.armg_train --help
python -m agent.armg_train --games 8 --batch-size 4 --eval-every 8 --eval-runs 2 --combat greedy --workers 2 --elo-data D:/path/to/elo-snapshot --out-dir runs/ppo-smoke-new
```

正式训练可选择 `--combat mcts-oracle` 或 `mcts-resampled`，配置 `--simulations`、`--floor-increment`、`--elite-simulations`、`--boss-simulations`。`--need-rules` 和 `--relic-rules` 默认关闭。

输出含 `latest.pt`、验证最佳 `best.pt`、`metrics.jsonl`、`worker-events.jsonl`。恢复用 `--resume` 并匹配环境及训练配置；`--init-checkpoint` 只在身份兼容时初始化权重。旧模型不得伪造版本或哈希直接加载，本轮未覆盖旧权重。

## 剩余限制

- 目标 DLL `9cb4f1ad…` 不在本机；本轮依据本地源码阅读与 C++/Python 测试，未进行目标原生差分，不宣称完整原生等价。
- 多人运行时未实现，多人卡不属于单人训练支持承诺。
- 复杂费用栈的完整可观察性、长组合、所有事件分支尚未穷举。
- 过去 worker 崩溃的底层原因尚未定位；现已加入一次原批次重试，持续失败则保存批次前状态并报错。
- 长循环恢复保留全部合法选择并记录强制干预，不保证任何旧模型都无需恢复；旧 1024 局模型未在本次修复后重做长程评估。

## 目录

- `simulator/`：C++ 引擎、绑定、搜索与引擎测试。
- `agent/`：PPO、奖励、内容过滤、特征及策略。
- `deployment/`：评估与其他训练入口；部分为历史实验工具。
- `tests/`：Python 回归测试。
- `docs/`、`validation/`：规则文档、历史记录和验证证据。
