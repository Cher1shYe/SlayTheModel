# SlayTheModel：交接说明

更新：2026-11-19（ruleset v14：全部 107 个活动怪物的数值核对及修正；静态值比对真实 DLL，动态效果按源码核对并做 C++ 回归。此前基础注册与 31 步完整公共接口证据保留，整局对齐仍未完成）。本文件是接手的唯一入口。项目经过和教训见 [docs/DEVLOG.md](docs/DEVLOG.md)；新版本方案见 [docs/plan.md](docs/plan.md)；观察设计见 [docs/observation-checklist.md](docs/observation-checklist.md)。源码与本文不一致时以源码为准，并更新本文。

## 0. 现状

**目标**：一个网络打《杀戮尖塔 2》整局（局外选择加每一手出牌），**铁甲战士、A10、单人、NoSL**（策略只用人能看到的信息），不搜索，从零开始纯 PPO。参照 AlphaDefect（v0.111.0、A10、1,000 个固定种子、EMA、取最大：储君 72.2%、静默 71.2%）。**目标：铁甲 A10 在 1,000 个固定种子上超过 72%。**

**已定**（用户 2026-11-18）：密集奖励（形式参照 Zero-Search，权重实现时确认）；练习战（一部分环境只打单场战斗，难的多练）；从零开始；直接在 A10 上训练和评估；观察系统设计（人能看到的给全，再加引擎算好的辅助结论和只用公开信息的动作效果预览）。

**待定**：价值函数训练时能否看隐藏信息（原理已解释，见 plan 第 6 节）；观察清单里 A–F 哪些做、做到什么程度（用户在看）；密集奖励的具体权重。

**做到哪了**（细节见 DEVLOG 第 6–14 节）：
- 工作区清理完成；旧代码在分支 `v111_SF1`。
- 随机数机制对照原生：底层随机数与各随机流的种子一致（第 6 节）。
- 怪物部分按原生源码重新移植（v9）：生成、血量、阵容、招式状态机、招式效果、敌人顺序、召唤位置（第 7–9 节）。
- Boss / 精英特殊机制逐行核对修正（v10，第 10 节）：Knowledge Demon 诅咒二选一（敌方回合中途暂停等玩家选）、女王魂缚、实验体复活、滑溜和扣血修正顺序、Infested Prism 污染、鹿的晕眩、Spectral Knight 的 Hex、Magi Knight 的 Dampen；沙虫核对一致；Aeonglass 用户确认不用看。
- v10 本机验证：C++ 38/38、Python 10/10、1,000 局冒烟 0 异常、改动涉及的 9 场战斗各随机打 400 局 0 卡死。**这些是按源码移植后的自测，不是和原生 DLL 对拍。**
- v11 原生宿主已能启动并返回真实状态；`parity/semantic.py`、`compare.py` 建立了部分公开状态和动作语义的对照通路。铁甲 A10、`PARITY0001` 真实执行从 Neow 三选项、GoldenPearl 增加 150 金币、Proceed 到首战结束，**提交 24 个动作、24 个决策点的已覆盖字段和合法动作语义相符**；双方结束时均为 **51/80 HP、249 金币**，在尚未支持的奖励页明确停止。此前首战遭遇差异追到完整遗物建池 / UpFront 顺序，已按原生修正。报告与固定回归样例见 DEVLOG 11.7–11.8；这不代表完整模型观察或整局已对齐。
- v11 按原生源码补齐 Neow 候选池、随机调用顺序、9 件缺失遗物及相关 Dowsing / Abundance、Ambergris 效果，保留必领、选牌、跳过和 Proceed 决策。最终 **C++ 43/43、训练 Python 31/31、parity Python 40/40** 通过。训练测试包含 21 项敌人位置检查，parity 包含保存的真实 24 步离线重放；新增机制的源码自测不等于 DLL 验证。四个独立机制测试使用固定的已支持遗物袋，完整原生池与未实现效果中止另有专门回归；全测试通过不表示长局不会遇到覆盖边界。
- 多敌人目标已通过只读 `monster_positions` 绑定公开位置：覆盖原生 19 个遭遇的槽名声明，并按当前敌人顺序映射；不能把原生列表下标当作 C++ 物理槽。宿主排除已离开原生 `Enemies`、但死亡动画尚未消失的尸体节点。v12 可识别原生仍在敌人列表中的 Adaptable 复活对象，不能把它当成可攻击目标；此项尚缺真实复活轨迹验证。
- v12 已按源码补齐此前 15 件遗物，并修正 Pumpkin Candle、Pendulum、Stone Calendar、Pael’s Eye、Brilliant Scarf 的相关状态。完整原生池保留全部候选；新增 `native_remaining_relics`、`native_decision_contract`、`native_reward_contract` 回归。不能把源码自测称为全部遗物已通过 DLL 对拍。
- 模型双端公共契约 **`spire.public/1`**：原生和模拟器分别导出公开事实，经过同一个 `train/spire_rl/public_obs.py` 编码器，使用同一网络、同一候选语义。覆盖牌实例/费用修饰/附着/动态变量、公开牌堆与已知顶牌、能力显示、意图、遗物计数、物理药槽、地图、奖励、商店、事件及选牌约束。原生 actionId 与 C++ UID 只用于执行，不进入特征；缺字段/未知状态明确中止。
- 真实选择补齐：手牌选中/取消/确认、网格预览/确认/取消、商店删牌、休息后 Proceed、宝箱打开/领取/放弃/Proceed、普通事件结束页、药水丢弃及选牌期间的排队、奖励重掷/免费删牌/特殊牌。Gambling、Pael’s Eye 及消耗触发抽牌的内层选择可以暂停后继续。
- v12 最终验证：**C++ 46/46、训练 Python 39/39、parity Python 63/63**；C# 宿主编译 0 warning / 0 error。两种 Python 测试分别覆盖观察/网络、语义映射/真实记录，均不能替代未走过的 DLL 场景。
- **当前核实边界**：v11 的 24 步真实记录仍按原始字节保留，只证明当时公开子集；v12 新默认比较完整公共事实及实际网络张量，不会因旧子集通过就继续执行。首次完整比较发现并修复 A6 错减休息点造成的 6 处地图差异、Neow 实际完成页键及战后残留战斗状态。最终真实执行 **31 个动作、32 个决策点**，每个完整公共事实/模型输入张量/合法动作集合一致，覆盖开局、首战、领金币和药水、卡牌奖励跳过后重开并领取、返回地图；末态 **51/80 HP、258 金币、12 张牌、Ashwater**。原始 32 帧和离线回归见 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/`。尚不能宣称其他场景或整局已完全一致。

- v13 基础注册审计：真实 DLL 导出 596 卡牌模型（595 个实际内容 + DeprecatedCard 迁移兜底）、299 遗物、65 种实际药水、57 普通事件、8 先古、107 活动怪物、85 活动遭遇。身份、所列静态属性、池成员/顺序通过；MadScience 动态模板、历史占位及 Stardust 无 owner 导出限制明确列出，不能当作完全相同。报告见 [docs/registry-audit.md](docs/registry-audit.md)。
- v13 修复 6 件遗物稀有度、4 件所属池、2 件 None 稀有度元数据；23 种药水 AnyPlayer 目标与 FoulPotion 条件目标；MadScience 注册字段；MysteriousKnight A10 血量 108；遭遇标签及 Hive 误入的 TunnelerNormal；蜈蚣三节段分别导出真实 Front/Middle/Back 身份。真实 ModelDb 词表排除 6 个源码辅助/抽象类伪注册。
- v13 最终验证：**C++ 47/47、训练 Python 40/40、parity Python 85/85**，总注册审计通过（保留明确例外）；此前 31 动作/32 决策完整原生记录的离线回归仍通过。
- 新增 `sim/content/registry_identity_lock.json`：锁定六类 C++ 整数 ID、枚举键和原生 ID，所有旧号保留，新项只能末尾追加。`python sim/tools/audit_native_registry.py --out docs/registry-audit.json` 可复查；不得删除重建锁来掩盖编号变化。本轮未全面核对各卡/遗物/事件效果，`NATIVE_PARITY_COMPLETE` 仍为 false。
- v14 全怪物数值核对：覆盖 107 个活动模型（Boss 相关 15、精英相关 17、普通/事件/其他召唤物 75，分组含组件与随从）。真实 DLL 在 A0/7/8/9/10 导出的血量、伤害和次数与实际编译表进行 **3,215 次数值比较，0 未解释差异**；TheForgotten 无 Creature、Waterfall 新建实例的动态例外明确保留。报告见 [docs/monster-number-audit.md](docs/monster-number-audit.md)。不能据此宣称全部怪物已通过原生战斗执行对拍。
- v14 修复升阶力量/格挡/治疗、MysteriousKnight 继承伤害与随机分支、Forgotten 实时敏捷伤害、怪物招式格挡修正、Entomancer Hive 上限、Prism 污染增长与死亡清除、Crab Rage +6、Curl Up 整张来源牌结束后触发、Rampart 额外回合、Aeonglass 能力归属及六牌倒数。Boss 75 招式在 A0–A10 共 825 次 C++ 执行，精英/普通另有专项测试；它们是源码期望回归，不是 DLL 战斗轨迹。
- v14 最终验证：**C++ 51/51、训练 Python 42/42、parity Python 89/89**；基础注册审计与编号锁仍通过，旧整数 ID 不变。快照升 v14，Card 仍 304 字节，观察版本/尺寸不变；此前 31 动作/32 决策原生记录的离线回归仍通过。

**等用户**：用户把怪物部分交给同学对比核查（2026-11-18 晚）。收到反馈后先按原生源码确认，再改 C++，改完跑测试、记 DEVLOG、必要时升 ruleset。

**下一步**：
0. 基础注册和全怪物数值核对已完成（第 13–14 节，明确例外见报告）；以后改内容先跑两项审计并保持 ID 锁。继续用户已授权的完整 `spire.public/1` DLL 对照；先修已记录的实际差异，再扩大到奖励、商店、遗物选牌、药水及复活场景。遇到不支持或目标含糊必须停止。处理同学的怪物核查反馈；Thieving Hopper 偷牌挑选规则仍未核对。
1. 用户定观察清单 → 改 C++ 观察接口（只新增，不改规则）。
2. 新训练框架：多进程采样、GPU 集中推理、整局 PPO、练习战、EMA 与取最大评估、防卡死、`--ascension`。
3. 原生对照：宿主已可用，继续扩大执行核对范围；用户计划提供几十局 AlphaDefect 静默/储君的对局记录，之后在模拟器里重放核对。不能将开局小范围结果写成整局通过。
4. 训练机测速，然后按工作日分段训练。

**当前代码状态**：`sim/` ruleset **`native-41cef1ea-port-v14`**（怪物生成 / AI 见 DEVLOG 第 7–9 节，Boss / 精英特殊机制见第 10 节，原生开局对照与 Neow 修正见第 11 节，公共接口与选择补全见第 12 节，基础注册核对见第 13 节，全怪物数值见第 14 节）；`train/` 有旧观察 `obs.py`、公共双端编码 `public_obs.py`、网络 `net.py`（legacy 布局约 2.5M，新增公共契约布局可选，带本幕 Boss 价值头；训练方案仍待实现）、模拟器加载 `sim.py`、吞吐测试脚本。没有训练循环。

## 1. 目录

| 路径 | 内容 | git |
| --- | --- | --- |
| `sim/` | C++ 模拟器：`src/`、`include/`、`bindings/`（Python 扩展 `sts2_sim`）、`content/`（生成的数据表）、`tools/`（生成器；`apply_native_monsters.py` 更新怪物血量和阵容，`native_monster_ai.py` / `apply_native_ai.py` 核对与套用 AI，`apply_native_neow.py` 追加原生 Neow 内容）、`tests/`（C++ 测试程序）、`native-fixtures/`（测试读的原生样例）、`build.py`、`PORT_SOURCE.json`（身份）、vendored `pybind11/`、`json/` | 跟踪；`sim/build/` 忽略 |
| `train/` | Python 包 `spire_rl`（`pip install -e train`）：`sim.py`、`obs.py`、`public_obs.py`、`net.py`；`tests/`；`scripts/bench_throughput.py` | 跟踪 |
| `parity/` | 原生无界面宿主（真实 DLL + Godot 无界面）：`host-src/`、`stage.py`、`run_host.sh`；语义适配 `semantic.py` / `action_contract.py`、逐步诊断 `compare.py`（默认完整公共模型输入）、`tests/` | 跟踪；`stage/` 忽略 |
| `docs/` | `DEVLOG.md`、`plan.md`、`observation-checklist.md`、`registry-audit.md/json`、`monster-number-audit.md/json` | 跟踪 |
| `artifacts/native-source/v0.111.0/` | 原生反编译源码（3,537 个 `.cs`），对齐规则用 | 忽略，只在本机 |
| `artifacts/preserved-game-versions/` | 原版游戏 v0.111.0 安装备份，**不可删除** | 忽略，只在本机 |
| `artifacts/tools/` | .NET SDK 9.0.321、ilspycmd（原生宿主和反编译用） | 忽略，只在本机 |
| `artifacts/reference/alphadefect-evaluation-overview/` | AlphaDefect 评估摘录（文档、5 次评估汇总、5 局记录） | 忽略，只在本机 |
| `runs/` | 训练输出（建议路径） | 忽略 |

## 2. 命令

### 2.1 这台 Mac（4 核、8 GB；Python `/opt/anaconda3/bin/python3.11`）

默认 Xcode 入口需要接受许可（不要代用户接受），用 Command Line Tools 的包装脚本：

```sh
cat > /tmp/clangxx <<'EOF'
#!/bin/sh
exec /Library/Developer/CommandLineTools/usr/bin/clang++ -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -isystem /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1 "$@"
EOF
chmod +x /tmp/clangxx
PY=/opt/anaconda3/bin/python3.11
DEVELOPER_DIR=/Library/Developer/CommandLineTools CXX=/tmp/clangxx $PY sim/build.py --test --jobs 2   # 编译并跑全部 C++ 测试
cd train && KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
```

本轮确认旧 `~/micromamba/envs/sts2/bin/python` 路径不存在；上述 Anaconda Python 3.11 已有 pytest、numpy、torch，可执行本轮测试。本机 torch 有 OpenMP 冲突：按命令临时设上面三个环境变量，不改全局；多线程 torch 会崩，用单线程。内存小，大任务先量内存，别并行开太多。这台 Mac 解析不了 `github.com`（DNS 问题），GitHub 上的东西找用户要文件。

### 2.2 训练机（Windows `LegionB` + WSL2）

RTX 5090、WSL 里 8 个线程，**这就是全部配置，不要再问**。Conda `slay`（Python 3.12），仓库 `/mnt/c/Users/yebohou/SlayTheModel`。

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
CXX=g++ python sim/build.py --test          # 目录改过，第一次必须重新编译
pip install -e train                        # v12 新增共享 parity 包，重新执行 editable 安装
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"   # native-41cef1ea-port-v14
python -m pytest -q train/tests
```

该机 CPU 不支持 BF16 反向；GPU 只能在用户工作时间挂着用，训练要按工作日分段、到点正常退出、可以接续；不要多存检查点（硬盘小）。

## 3. 用户约定（必须遵守）

- **不提交、推送、合并**，除非用户明确要求；用户自己在另一台机器提交推送，需要时给命令和说明。旧版本在 git 分支 `v111_SF1`。
- **不启动、停止、重置**训练机上的实验；本机只做代码、分析和 CPU 小规模测试。
- **保留玩家真实选择**：选牌、跳过、确认、药槽满时换药等不能用随机、自动领取或静默丢弃替代；只有原生本身直接完成的选择才自动完成。卡死只能截断，不能代选。
- **模拟器**：保留同学的 C++ 模拟器并修正规则；不重写、不换成纯原生执行、不靠删掉真实决策提速。网络需要的接口只能新增，不能借机改规则；改规则要更新 ruleset 身份（`sim/PORT_SOURCE.json`、`ENGINE_RULESET_ID`）。对齐规则时对照 `artifacts/native-source/` 逐行移植，新 ID 只追加在末尾，生成的表改生成器再重新生成，新增状态覆盖 clone、快照校验、观察和绑定。出现差异以原生 DLL 为准改 C++，不改样例。
- **NoSL**：策略的输入只能有人能看到的信息（或由它和规则推算出的）。隐藏随机顺序不能泄漏到观察；新观察要用“只改隐藏状态、观察不变”的检查验证。
- 不删 `artifacts/preserved-game-versions/`。
- 核对规则要核对**效果**，不能只看招式编号对得上（DEVLOG 9.2 曾因此把几处错的写成一致，第 10 节已更正）。
- 基础注册检查入口为 `sim/tools/audit_native_registry.py`，原始 DLL 表 `sim/native-fixtures/native-registry-41cef1ea.json` 不可改写；旧整数与别名按 `registry_identity_lock.json` 锁定。源码文件名可能是抽象类或辅助类，不能直接当原生模型注册。
- 怪物数值检查入口为 `sim/tools/audit_monster_numbers.py`；原始 DLL 文件在 `sim/native-fixtures/native-monster-numbers-41cef1ea/`，不可改写或重算 SHA 掩盖差异。`apply_native_monster_numbers.py` 更新已审核数值，继承 AI 由 `native_monster_ai.py` 解析；新变更要同时检查静态表和实际执行/公开显示。
- 观察新增字段**只追加在行尾**：`train/spire_rl/obs.py` 按固定下标读战斗观察的玩家行（如 `P_POTIONS = 39`），中间插入会错位。
- `Card` 现为 304 字节，填充位已用完；再加字段会变大，`tests/native_step3_events.cpp` 的 `main` 栈上放了多个 `RunContext`，可能栈溢出。加字段前先量大小。
- 编译期间先冻结 C++ 头、源文件和绑定；`sim/build.py` 检测到输入中途变化会拒绝发布扩展并要求重编，避免混合结构布局。
- 每批改动都跑 C++ 和 Python 测试，并在 `docs/DEVLOG.md` 末尾记录（日期、做了什么、为什么、结果）。不要把“不崩溃”写成“和原生一致”。
- 用户不熟悉实现细节：先说结论，用平实的话，直接给建议；分析要基于原始数据，区分已确认、较强怀疑与证据不足。

## 4. 版本与身份

**git 状态（未提交，由用户在另一台机器提交）**：清理删除了 4,000 多个旧文件；`sim/`、`train/`、`parity/`、`docs/` 是新目录，目前未跟踪，提交时要 `git add` 这几个目录以及 `AGENTS.md`、`README.md`、`.gitignore`。`sim/build/`、`artifacts/` 已忽略。

- 目标原生：`v0.111.0 / 41cef1ea`，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 模拟器 ruleset `native-41cef1ea-port-v14`；宏观观察 `MACRO_OBS_VERSION=4`（96 列）；战斗实体观察 `COMBAT_OBS_VERSION=5`（112 列）；扁平公开观察 `PUBLIC_OBS_VERSION=18`；`ACTION_SCHEMA_VERSION=15`；快照 v14（CurlUp 来源 UID 和 Aeonglass CardsLeft 使用空闲辅助槽，旧快照拒绝）。公共双端契约 `spire.public/1`；它是独立新布局，旧网络默认仍使用 legacy 布局，新模型需设置 `UnifiedNetConfig(observation_schema="spire.public/1")`。敌人上限 6；观察新字段只追加在行尾，宏观卡片进度固定放 `num[78]`，保留 `num[79]` 的选中标记。`train/spire_rl/obs.py` 仍按固定下标读玩家行。`CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽），`Card` 仍为 304 字节。
- 模拟器的已知差异和未验证部分见 DEVLOG 第 2.4、11–14 节：**没有完成整局原生对照**；本轮核对了怪物 A8/A9 数值边界，其他 A1–A10 规则仍未逐项核对。当前最强真实战斗执行证据仍为单个种子从 Neow 到首战、领奖并回地图的 31 步完整公共契约对照。

sh02v17 使用本分支 v14 的 A9 最终 Boss 评估命令和观测/动作适配说明见 [train/a9/README.md](train/a9/README.md)。
