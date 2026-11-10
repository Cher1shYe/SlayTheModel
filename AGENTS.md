# SlayTheModel：模拟器测试分支交接

更新：2026-11-10。**当前分支职责是 `v111_simulator_test` 的 C++ 模拟器与验证，不开发新网络或训练方案。** 用户要求将本地模拟器单独成分支，README 和交接文档按此范围编写。

## 1. 接手先确认

- 本分支从共同历史 `bb2070f0a4467f90333c81e98332be90f05baa4c` 建立，按文件提取 `v111_SF1` 的 `50d72a6` 中的模拟器更新，并加入 2026-11-10 NoSL 审计。没有合并该提交的网络部分。
- `workspace_YE` 远端在本次查询时为 `da98753`，已有另一套独立模拟器更新（其自有 v10 / obs20 / action17 / snapshot14）。**本分支没有整合那条实现，也不是它的后继版**；不能只凭版本数字或日期判断哪一套规则更完整。
- 新 ST-DT 网络、PPO 训练与实验在 `v111_SF1`；本分支不包含 `model/spire_rl/`、`docs/configs/spire-rl-*.json`、`docs/st-dt-training-handoff-20261110.md`。共同历史里的旧网络、模组、采集器保留，不作为此分支的开发入口。
- 模拟器生产源码与 `50d72a6` 一致，本次不修游戏规则、不改变 MCTS 搜索预算、不做新训练。必要的旧接口兼容更新仅为 `agent/engine_identity.py` 的 ruleset、`agent/armg.py` 的特征版本/物理药槽、`agent/armg_train.py` 的观察版本检查。
- **严格 NoSL 审计未通过，生产修复未实施。** 新 15 项检查中 8 通过、7 失败。先读 [审计](docs/mcts-nosl-audit-20261110.md)；旧 6000 次重采样测试通过不能取代这项结论。
- 本次来源和验证见 [分支说明](docs/simulator-branch-20261110.md) 与开发副本内 `validation/branch-export-20261110/README.md`。历史文档的“WIP”“已完成”只代表当时的覆盖范围。

## 2. 目录与规则目标

以下路径相对仓库根：

| 用途 | 路径 |
| --- | --- |
| **本分支可编辑模拟器** | `artifacts/dev/cpp-native-aligned-20261031/` |
| C++ 引擎、绑定、回归 | 上述目录的 `simulator/` |
| Python 接口回归 | 上述目录的 `tests/` |
| 来源与接口身份 | 上述目录的 `PORT_SOURCE.json` |
| 历史原生探针（本地可能存在） | `artifacts/dev/rtg-probe-20261027/` |
| 原生反编译参照（本地可能存在） | `artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/` |
| 不可变 C++ 基线 | `artifacts/reference/alphazero-be401e8/` |
| 用户原始权重（不得覆盖） | `artifacts/reference/armg-live-20261031/latest.pt` |

目标原生版本：**v0.111.0 / 41cef1ea**。目标 DLL SHA-256：
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
C++ 上游基线为 `be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`，与本分支 Git 分叉点不是同一个概念。

Mac 原工作目录 `/Users/yebohou/SlayTheModel` 本地还保存了 `artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/`：440 个文件核验一致的完整安装快照。该备份未上传，新克隆不会得到它；它不是缓存，清理必须保留。原生探针、不可变参考、权重和反编译目录也不能假定每个克隆都有，先检查文件再使用。

**原生探针和 C++ 是不同实现。** C++ 回归、元数据一致或冒烟通过不等于原生完整等价。

## 3. 当前接口

- Ruleset `native-41cef1ea-port-v6`；`native_parity_complete=false`。
- 公开观察 v15、动作 v14、快照 v10、ArmG 特征 6。
- `CARD_COUNT=597`，包括 INVALID 和保留的 Grapple 槽。Grapple 无目标原生模型且从正常牌池排除，不应当作漏实现卡牌。
- 卡牌特征 631，动作特征 727；公开观察 75988，公开战斗观察 49252。
- 卡牌奖励最多 4 项；新增实体观察 `MACRO_OBS_VERSION=1` 属于模拟器接口，不包含网络实现。
- `NativeProgressContext` 包含角色/事件/epoch/遭遇发现与特殊古老角色开关；默认值不是游戏存档导入的替代品。
- 两条分支、旧快照和旧权重不可通过修改版本号强行兼容。规则、观察、动作或隐藏信息语义变化应更新身份并记录来源；扩展模块重建后重启使用它的 Python 进程。

## 4. 已做到哪里

早期已完成种子/哈希/RNG、抽洗牌、手动选牌、牌实例状态，以及多轮卡牌/遗物/事件修正。第一部分完成自伤累计顺序、事件降级费用和遗物计数关联，不要重复做旧缺口。

第二部分（见 `validation/round4-step2-resume-20261108/README.md`）：

- 接入静默猎手、故障机器人、亡灵契约师、储君的卡池和专属机制。前三者有当轮原生样例，储君主要按源码实现。
- 补齐 Sea Glass、Lead Paperweight、Dusty Tome、Arcane Scroll、Dream Catcher 等真实选择，Toy Box 蜡制、胶囊奖励、茶类和宠物持续状态，以及物理药槽。

第三至六步（见 `validation/round4-step3-events-20261108/README.md`，顺序读到末尾）：

- 补齐 34 项此前缺失的事件、小游戏和事件战斗；增加 Aeonglass，修正 Glory Boss 池和发现顺序。
- 修正地图生成、事件顺序、账号 epoch 内容过滤、Splash/Prismatic Gem、Wongo/商店过滤。
- 费用修正栈、死亡能力清理、新实体变牌、Imbued、奖励钩子、Lasting Candy 与奖励稀有度阈值。
- 测试通过 `simulator/tests/port_root.h` 定位样例；`STS2_PORT_ROOT` 优先，否则从工作目录向上查找。

**证据边界：** 历史记录为 36 个 C++ 程序通过；Python 167 项通过，另有该轮环境相关的 10 失败与 34 错误；1000 局贪心冒烟无异常/截断，普通地图 6/6 对照一致。这不是当前每次检查都可忽略失败的理由。第三步起主要是源码移植，未补对应 DLL 执行证据，也没有完整原生整局逐步对照。本次实际复验另见新的 `branch-export-20261110` 目录。

## 5. 下一步顺序

1. **修复并复验 NoSL 信息隔离。** 对同名不同成长/费用/附魔的牌建立完整可见属性规范化；补公开排序遗漏的 `bonusBlock`、`retainThisTurn`、Sly 字段；补 `orbRng` 等未来随机流的重采样，并单独核验原生初始化流。保持公开状态与搜索种子相同，仅改变真实隐藏牌序/RNG 时，观察、采样和动作应保持一致。不得用内部 UID 或真实牌序规避问题。
2. **恢复固定版本 DLL 样例宿主，补新增规则的原生差分。** 本地保全安装不代表宿主可运行；第三步起的新规则先做受控样例，再做长路径。
3. **补完整同种子、同账号进度、同决策的整局对照。** 包括后两幕、A10 第二 Boss、奖励顺序及 RNG 消耗；模拟器接受 A0–A10 不等于各进阶已专项验收。
4. **继续检查边界与复杂组合。** `double`/`decimal` 取整、固定牌堆/遗物容量；回合开始 Mayhem 与遗物相对次序；`nextTurnEnergy` / `nextTurnDraw` 当前是恒 0 占位。其他角色整局、多人和实机 UI 桥接不能视为已验证。

NoSL 证据在 `validation/nosl-audit-20261110/`，修复时新建验证目录，保留原失败记录。审计基于本地 v6，不代表远端 `workspace_YE` v10 具有相同结论。

## 6. 工作约定

- 用户最新明确指令优先；未明确授权时不提交、推送、合并、部署或发布模组。本次授权仅针对创建并发布这个模拟器分支，不延伸到其他分支。
- 保留 C++ 引擎速度与真实决策，不换纯原生执行，不通过删动作、随机代选、自动领牌或静默丢药来省事。原生候选数不足而直接完成的规则除外。
- 先读目标版本源码；不确定效果优先用匹配 DLL 核验。不得改历史原生结果来迁就 C++，也不得把测试通过写成完整等价。
- 新 ID 追加末尾；同时更新生成源与生成文件。新增状态覆盖 clone、快照、公开观察、动作与绑定；隐藏未来信息不得进入公开接口。
- 不改旧网络结构、训练器设计、`model/`、采集器或 `combat/`；如接口变更确实影响旧调用方，明确列出最小兼容修改，不能混入网络功能开发。
- 每批代码修改运行对应回归；整合接口/布局后运行完整 C++、必要 Python 和整局冒烟。检查候选顺序、RNG 消耗、选择暂停/恢复、奖励跳过、复活及满槽行为。
- 不覆盖原始权重、不可变参考、游戏备份和前轮证据。新日志写新目录，旧 README 的历史条目保留。
- 根 `.gitignore` 忽略 `artifacts/`，新文件必须按明确清单添加；不要强制添加整个 artifacts。禁止上传训练输出、`.pt`、游戏 DLL、编译产物或缓存。此次准确清单为 `docs/simulator-export-paths-20261110.txt`，它只用于此批导出，后续按实际变更更新。

## 7. 复现入口

工作目录 `artifacts/dev/cpp-native-aligned-20261031/`。构建和常规检查命令见仓库根 README。Mac 此次使用 `/opt/anaconda3/bin/python` 3.11 与 Command Line Tools，未使用或修改用户全局环境。Linux/WSL2 使用自己的 Conda Python 与 `g++`，不复用 Mac 对象文件。

`validation/build_local.py` 保持回归断言开启，并编译所有 C++ 测试；它会重写 `validation/build.json`。需要保留新证据时，用本次 `validation/branch-export-20261110/build.py` 的方式将构建报告写到新目录。历史 `run_cpp_tests.py` 和地图/NoSL 审计运行器可能重写原报告，重跑前先选择新的输出目录，不要直接覆盖归档证据。

> 导出复验补记：仅同步两处旧 Python 测试替身的字段名（`potions` → `potion_belt`），使其匹配已有物理药槽 API；没有改测试期望、生产规则或网络代码。初次 8 项失败及修正后复验均保留在 `validation/branch-export-20261110/`。
