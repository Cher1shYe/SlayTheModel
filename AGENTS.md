# SlayTheModel：交接说明

更新：2026-11-20 晚，America/Los_Angeles（B 效果预览重做 DEVLOG 35、Fake Merchant v21 DEVLOG 36、训练框架第一版 DEVLOG 37）。本文件是接手的唯一入口：第 0 节先说清**已办、缺口、待办**，细节按指向去 [docs/DEVLOG.md](docs/DEVLOG.md)（按节号）、[docs/plan.md](docs/plan.md)（训练方案与已定参数）、[docs/observation-checklist.md](docs/observation-checklist.md)（观察设计）、[docs/content-audit.md](docs/content-audit.md)（规则核对记录）。源码与本文不一致时以源码为准，并更新本文。

## 0. 现状

### 0.1 目标与已定决策

**目标**：一个网络打《杀戮尖塔 2》整局（局外选择加每一手出牌），**铁甲战士、A10、单人、NoSL**（策略只用人能看到的信息），不搜索，从零开始纯 PPO。参照 AlphaDefect（v0.111.0、A10、1,000 个固定种子、EMA、取最大：储君 72.2%、静默 71.2%）。**第一个目标：铁甲 A10 在 1,000 个固定种子上超过 72%。**

**两项硬要求**（用户 2026-11-18）：
1. 模拟器可由人在命令行里直接操作——已完成（`python -m spire_rl.play_cli`，见 2.1）。
2. 用模拟器训练的 AI 能直接到带画面的原生客户端里玩——现在不实现，但每项设计都要保持这条路通（第 3 节“可部署”）；原生端还欠的工作见 0.3.3。

**已定决策**（用户 2026-11-18 / 19，详见 plan 第 6、6.2、7 节）：
- 一个网络打整局；**从零开始纯 PPO**；直接在 A10 上训练和评估；**MCTS 教师 / 战斗先验蒸馏路线放弃**（plan 第 7 节）。
- **网络**：宽 768、局外 12 层 + 战斗 12 层，实测 217.4M 参数（用户拍板，不再改小）。其他超参按比例（plan 第 6.2 节）。
- **奖励**：初始用 Zero-Search 数值——每层 +0.01、精英 +0.02、Boss +0.1、通关 +1、死亡 −0.1、血量势函数 0.1；全部是参数，**奖励项要能随时加**。
- **练习战**：40% 环境只打单场战斗（从整局存下的战斗开始快照读档、每次重新打乱隐藏随机）；输 −0.1，赢用战后状态的价值估计结算；抽样权重 Boss 6、精英 3、普通 1，再按最近死亡率和掉血加权。
- **防卡死 / 防循环**：敌人血量合计 20 个玩家回合没创新低判负、一回合内回到同一局面强制结束回合、一局最多 5,000 决策、判负记 −0.1；**这些规则属于 AI 驱动层**（训练和上线同一份代码），不改模拟器和游戏（DEVLOG 第 26 节）。
- **价值头**：标量；原三个 Boss 概率留作辅助输出。**价值函数看不看隐藏信息做成开关**，先用只看公开信息的版本。
- **观察**：做清单 A–E（F 暂不做）；**观察空间要能变**（`FEATURE_VERSION` 写入检查点，不符拒绝加载）；招式预测带概率；事件只给文字里写明的结果；卡牌稀有度保底计数可以给；**事件选项提示不做，另有人做**。
- **可用算力**：A100 约 3 天有效训练时间（也能用 H100）；217M 在 A100 上估计每秒 300–500 决策（未实测）。**用户 2026-11-20 定：先上 5090（2.2 节）测速和跑第一段，再去 A100。**

### 0.2 已办

**模拟器 `sim/`（ruleset `native-41cef1ea-port-v21`，快照 v18）**——全部是对照原生源码移植并自测，**不是原生 DLL 执行对拍**（例外见“原生对照”）：
- 随机数机制与各随机流种子（DEVLOG 6）；怪物生成、血量、阵容、招式状态机、招式效果、敌人顺序、召唤位置（v9，DEVLOG 7–9）；Boss / 精英特殊机制（v10，DEVLOG 10）；怪物机制与回合触发全部钩子、怪物施加的 68 种能力（v17，DEVLOG 21）。
- 基础注册（v13）：卡牌、遗物、药水、事件、先古、怪物、遭遇的身份和静态属性与真实 DLL 导出一致，C++ 整数 ID 由 `registry_identity_lock.json` 锁定（DEVLOG 13，`docs/registry-audit.md`）。
- 全怪物数值（v14）：107 个怪物在 A0/7/8/9/10 的血量、伤害、次数与 DLL 3,215 次比较 0 未解释差异（DEVLOG 14，`docs/monster-number-audit.md`）。
- 局内概率与生成（v15）：问号房、各类奖励、遭遇与事件抽取、商店、宝箱、地图、A1–A10 局外效果；默认全解锁进度（DEVLOG 18）。
- 事件：57 个出现条件、全部选项效果（v16、v18，DEVLOG 19、22）。
- 铁甲可得 265 件遗物逐件核对，修正 19 件（v19，DEVLOG 23）。
- v21：Fake Merchant 离开直接回地图（原生没有结束页），去掉一个多余决策和导出报错（DEVLOG 36）。
- v20：Perfected Strike 打出时计入自己；**玩家和怪物的伤害修正改用精确十进制**（原来 double/float 在少数乘数组合下少 1）；Unmovable 按原生“获得格挡记录”计数（DEVLOG 30）。
- 卡牌身份与编码：596 个模型、1,148 个变体，模拟器导出与原生格式逐位相同（DEVLOG 20）。

**原生对照 `parity/`**：无界面宿主能启动真实 DLL 并导出公开状态。最强实测证据：种子 `PARITY0001`（A10 铁甲）从 Neow 到首战、领奖、回地图的 **31 个动作 / 32 个决策点**，完整公开事实、网络输入张量、合法动作集合逐步一致（DEVLOG 11–12，固定样例 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/`）。此后新增的观察字段在这份旧录制上以 `legacy_capture=True` 回放（两边都去掉、报告标“未覆盖”）。

**公开观察 `spire.public/1`（`FEATURE_VERSION=9`）**：原生和模拟器各自导出公开事实，经同一个 `train/spire_rl/public_obs.py` 编码，同一网络、同一候选语义；原生 actionId / C++ UID 只用于执行。真实选择全部保留（DEVLOG 12）。观察清单 **A–E 已全部完成**（DEVLOG 27–34）：

| 项 | 内容 | 实现 | 主要验证 |
| --- | --- | --- | --- |
| E | 牌组摘要 | `public_derived.py` | 起始牌组数值、随机整局有界 |
| C | 抽牌概率（1/2/5 张内抽到各类牌） | `public_derived.py` | 与枚举全部隐藏顺序的精确值相等 |
| A5 | 地图路线摘要 | `public_derived.py` | 手算小地图 |
| D | 本幕已遇遭遇、下一场概率 | C++ 导出历史 + `public_derived.py` | 40 局里每场实际遭遇都在预测内 |
| A1 | 加成后的牌面伤害/格挡（含对每个敌人） | C++ `card_preview.cpp` | 按原生公式手算 58 项 + 用户指定 3 组 144+ 项；随机对局 4,821 次伤害、3,860 次格挡与实际出牌一致 |
| A3 | 每个敌人这回合最多打多少、能否打死 | `public_tactics.py` | 与枚举出牌组合最优解相等 |
| A4 | 现在结束回合掉多少血（含回合末效果、Osty、减伤遗物） | `public_tactics.py` | 2,003 个局面与实际结束回合一致 |
| B | 每个出牌的效果预览：我方一侧（能量、格挡、自伤、重放、遗物/能力触发、出牌后手牌）精确或标未知；对敌伤害不含敌人自身防御与反应（DEVLOG 35） | `public_tactics.py` | 全量对照（`train/scripts/audit_action_preview.py`）：标“已知”的 43,206 次出牌、8,965 次出牌后结束回合全部与模拟器一致（DEVLOG 37） |
| A2 | 怪物当前招式 + 后两步概率 | C++ `predict_monster_moves` | 13,131 次实际出招全在候选内，频率与概率吻合 |
| A6 | 选牌用途与来源（40 种用途） | C++ 导出 + `PURPOSES` | C++/Python 词表锁定一致 |

另外：公开状态补上了 Osty（死灵召唤物，替玩家挡攻击伤害）的血量；每张牌打几下的表 `cardHits` 从原生出牌代码解析生成。每个决策：公开状态约 0.5 毫秒、编码约 0.5 毫秒、平均约 103 个实体。所有新观察都通过“只改隐藏随机、观察逐位不变”的 NoSL 检查。

**工具**：人用命令行 `play_cli.py`（撤销、存读档、只显示公开信息，DEVLOG 17）；公共接口提速到每决策约 0.77 毫秒（DEVLOG 16，之后加了 A–E 仍约 1 毫秒）。

**训练框架第一版（2026-11-20，DEVLOG 37）——已可开训（最小完整版：整局 PPO、限时退出、续训）**：
- `spire_rl/driver.py`：AI 驱动层，只读 `PublicState` 与自身公开历史，训练与原生客户端共用。同一作用域内同一网络输入第三次出现时去掉已走过的候选；战斗中同一回合重复出现的决策只允许结束回合；敌人血量合计 20 个玩家回合没创新低、或一局超过 5,000 决策判负；只有一个可选候选时直接执行，不进网络。
- `spire_rl/rewards.py`：每项奖励一个函数一个权重（0.1 节的数值），`--reward` 可覆盖。
- `spire_rl/rollout.py`：多进程采样（每进程若干局同步推进），网络输入约 98% 为零，传输与存储用稀疏格式（每样本约十几 KB）；单局异常写进日志并换新局，不中断训练。
- `spire_rl/ppo.py`：同步整局 PPO（超参见 plan 6.2）、CUDA 上 BF16、EMA（2 小时时间常数）、`latest.pt` + `ema.pt` 两份原子覆盖保存、`--hours` 到时或 Ctrl-C 在当前更新后保存退出、同一 `--run` 再运行即续训、`--bench` 测速。
- **网络**（`net.py`，2026-11-16 写好，本次只加了标量价值头）：每个“东西”（牌组里的牌、遗物、药水、地图点、手牌、各牌堆的牌、敌人、能力……）是一个实体向量 = 类型 + 身份 + 数值特征；地图点沿路线先传一轮信息；局外实体过 12 层 Transformer 编码器；战斗实体过 12 层 Transformer 解码器（自注意 + 交叉注意局外）；注意力汇总后与全局行（血量、金币等）、玩家行拼成局面向量。策略头给每个合法候选打分（动作类型 + 候选数值特征含 B 预览 + 它指向的实体向量 + 局面向量），驱动层不允许的候选屏蔽后做 softmax；价值头输出一个标量；原三个 Boss 概率保留为辅助输出（暂不训练）。局外与战斗同一个网络。
- 本机只用小网络（0.9M）在 CPU 上跑通；**217M 在 GPU 上的速度未实测**。尚未做：练习战、价值函数看隐藏信息（`--value-hidden` 预留，目前拒绝）、EMA 取最大评估脚本。

**测试现状**：C++ 58/58、训练 Python 85/85、parity 93 项 + 109 子项；注册表、怪物数值、卡牌编码三项审计通过。

**尚未提交**：v15 起至今的全部改动都在工作区，未提交（最后一次提交 `aefad6a` 还是 v14）。按约定由用户自行提交。

### 0.3 缺口

#### 0.3.1 模拟器规则（已知、未修，均为源码对照所见）
- 遗物（content-audit 第 12 节）：Unceasing Top 只在出牌后检查空手；Ghost Seed 不处理战斗中新生成的基础牌；同一时机多个遗物按 C++ 固定顺序而非遗物栏顺序结算；History Course、Imbued 自动打出、Mercury Hourglass 时机早于原生；Gremlin Horn 在“被阻止的死亡”上未核对；Lord's Parasol 白拿中途弹出选牌（如 Astrolabe）时后续遗物/药水的先后不对（与 Potion Belt / Sozu / The Courier 组合时结果不同）；其他职业的初始遗物升级版未查。
- B 对照中新查出（DEVLOG 35，未修）：Intimidating Helmet 重放时只触发一次（原生每次重放都触发）；Pen Nib 第 10 次攻击结束战斗后，模拟器下一场第一次攻击翻倍（原生不翻倍）。（曾怀疑的“回合开始流程未走完”经扫描否定，实为预览漏算附魔，DEVLOG 37。）
- **卡牌效果、药水效果尚未系统做源码对照**（只核对了身份、编码和牌面数值；A1 顺带核对了伤害/格挡的计算部分）。
- 其他小项：卡牌奖励某稀有度抽空时的回退顺序与原生不同（铁甲池碰不到）；第一局教学固定顺序未建模（默认进度不触发）。

#### 0.3.2 观察（按设计的边界或未做）
- 事件选项提示里的物品：不做，另有人做。
- 遗物的“本场是否已触发”等额外状态未导出（已有状态/计数/蜡封/熔化）。
- A3 不考虑出牌顺序和抽牌；A4 不含敌人回合中一个敌人给另一个加力量这类中途变化，也不含下回合开始时的掉血（Inferno、中毒、Crimson Mantle）。
- B 口径（DEVLOG 35）：我方一侧精确，算不准标未知；对敌伤害**不含敌人自身的防御与反应**（滑溜、Skittish 等，留给网络学）；会反击或改变敌人本回合行动的敌方能力被打到、改变敌人本回合的牌（上虚弱、减力量）、抽牌/加牌而回合结束受手牌影响时，“出牌后结束回合掉血”标未知；只对复核过源码的卡池（铁甲、无色、事件、诅咒、状态、衍生）给数。
- 其他职业的“按局面计算”的牌（Prismatic Gem 等才会出现）预览标未知；出牌时才决定打几下的牌（Fiend Fire 等）标未知。
- A2 的条件分支按当前战场判断；被眩晕 / 复活中的敌人只给参考。

#### 0.3.3 原生端欠账（上线原生客户端前必须补；在模拟器里训练不受影响）
1. 已写好但**未编译、未实跑**的宿主 C# 导出：本幕遭遇（D）、牌面显示值（A1）、Osty 血量。这台 Mac（`~/Workspace/SlayTheModel`）没有游戏备份，需在有游戏的机器上编译。
2. **A2 招式预测的原生端未写**：宿主要读原生 MoveStateMachine，按同样规则推算。
3. **A6 选牌用途映射未写**：原生选牌界面 → `PURPOSES` / `service`。
4. 补完后录一段新的原生记录，用完整对照（非 legacy）核对所有新字段。现在的 `from_native` 缺这些字段会直接报错，不会默默补零。

#### 0.3.4 验证覆盖
- 整局原生对照没有做；真实战斗执行证据只有上面那一局的开头 31 步。
- 塞入新遗物后的随机整局冒烟测试没跑完（v19 时用户中止）。
- 第二、三幕的遭遇池（D）只靠注册表数据，随机打法到不了，未经整局覆盖。

### 0.4 待办（按顺序）
1. **（用户）提交并推送**当前工作区，训练机 `git pull`；需要时给出提交和同步 `v111_simulator` 的命令。
2. **（用户）5090 测速并开训**（2.2 节命令）：先 `--bench` 看决策/秒和显存，再定 `--workers/--games/--micro`；若 217M 只有每秒几百决策，和用户商量是否先用中档网络跑通流程。第一段看：平均层数、第一幕 Boss 死亡、`reasons` 里 stall/cap/error 是否异常多、`errors` 内容。之后再上 A100（2.3 节）。
3. **训练框架补完**：练习战池（存档、读档、重打乱隐藏随机——**先核对 `resample_hidden` 与原生一致**）；价值函数看隐藏信息（开关已预留，`--value-hidden` 目前拒绝）；EMA 取最大评估脚本（1,000 个固定种子）。
4. 卡牌效果、药水效果的源码对照（正式长训前做），以及 0.3.1 的遗物小缺口——**模拟器规则改动按用户安排暂停中，等同学的原生对照反馈后统一处理**。
5. 原生端欠账（0.3.3），在上线原生客户端之前完成。
6. 原生对照扩大：奖励、商店、遗物选牌、药水、复活场景；用户计划提供几十局 AlphaDefect 静默/储君对局记录，到时在模拟器里重放核对。

### 0.5 等外部
- 同学对怪物部分的原生对比核查结果：收到后先按原生源码确认，再改 C++、跑测试、记 DEVLOG、必要时升 ruleset。
- AlphaDefect 对局记录（用户提供）。

## 1. 目录

| 路径 | 内容 | git |
| --- | --- | --- |
| `sim/` | C++ 模拟器：`src/`、`include/`、`bindings/`（Python 扩展 `sts2_sim`）、`content/`（生成的数据表）、`tools/`（生成器；`apply_native_monsters.py` 更新怪物血量和阵容，`native_monster_ai.py` / `apply_native_ai.py` 核对与套用 AI，`apply_native_neow.py` 追加原生 Neow 内容）、`tests/`（C++ 测试程序）、`native-fixtures/`（测试读的原生样例）、`build.py`、`PORT_SOURCE.json`（身份）、vendored `pybind11/`、`json/` | 跟踪；`sim/build/` 忽略 |
| `train/` | Python 包 `spire_rl`（`pip install -e train`）：`sim.py`（加载扩展）、`public_obs.py`（公开状态与编码，`spire.public/1`）、`public_derived.py`（C/D/E/A5）、`public_tactics.py`（A3/A4/B）、`public_catalog.json`（生成的公开词表、遭遇池、打击次数）、`net.py`（网络，旧 `obs.py` 布局仍可用）、`play_cli.py`；训练：`driver.py`（AI 驱动层）、`rewards.py`、`rollout.py`、`ppo.py`（`python -m spire_rl.ppo`）；`tests/`；`scripts/bench_throughput.py` | 跟踪 |
| `parity/` | 原生无界面宿主（真实 DLL + Godot 无界面）：`host-src/`、`stage.py`、`run_host.sh`；语义适配 `semantic.py` / `action_contract.py`、逐步诊断 `compare.py`（默认完整公共模型输入）、`tests/` | 跟踪；`stage/` 忽略 |
| `docs/` | `DEVLOG.md`、`plan.md`、`observation-checklist.md`、`content-audit.md`、`registry-audit.md/json`、`monster-number-audit.md/json`、`card-encoding-audit.json` | 跟踪 |
| `artifacts/native-source/v0.111.0/` | 原生反编译源码（3,537 个 `.cs`），对齐规则用 | 忽略，只在本机 |
| `artifacts/preserved-game-versions/` | 原版游戏 v0.111.0 安装备份，**不可删除** | 忽略，只在本机 |
| `artifacts/tools/` | .NET SDK 9.0.321、ilspycmd（原生宿主和反编译用） | 忽略，只在本机 |
| `artifacts/reference/alphadefect-evaluation-overview/` | AlphaDefect 评估摘录（文档、5 次评估汇总、5 局记录） | 忽略，只在本机 |
| `runs/` | 训练输出（建议路径） | 忽略 |

## 2. 命令

### 2.1 Mac（4 核、8 GB）

项目由用户和同学在不同 Mac 上推进，路径和 Python 不一定相同，先核实再用。2026-11-18 晚核实：仓库在 `~/Workspace/SlayTheModel` 的那台 Mac 上 **没有** `/opt/anaconda3`，可用的是 `~/micromamba/envs/sts2/bin/python`（3.11，含 numpy、torch、pytest，与现有扩展同为 3.11 ABI）；另一台记录的是 `/opt/anaconda3/bin/python3.11`、仓库 `~/SlayTheModel`。两者都要按下面临时设三个环境变量（torch 有 OpenMP 冲突，单线程）。内存小，大任务先量内存，别并行开太多。`~/Workspace/SlayTheModel` 这台的 `artifacts/preserved-game-versions/` 是空的（2026-11-19 核实）：**原生宿主在这台既不能编译也不能运行**，原生端工作要到有游戏的机器上做。

默认 Xcode 入口需要接受许可（不要代用户接受），用 Command Line Tools 的包装脚本：

```sh
cat > /tmp/clangxx <<'EOF'
#!/bin/sh
exec /Library/Developer/CommandLineTools/usr/bin/clang++ -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk -isystem /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1 "$@"
EOF
chmod +x /tmp/clangxx
PY=$( [ -x /opt/anaconda3/bin/python3.11 ] && echo /opt/anaconda3/bin/python3.11 || echo ~/micromamba/envs/sts2/bin/python )
DEVELOPER_DIR=/Library/Developer/CommandLineTools CXX=/tmp/clangxx $PY sim/build.py --test --jobs 2   # 编译并跑全部 C++ 测试
cd train && KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=. $PY -m pytest -q -p no:cacheprovider tests/
cd .. && KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 PYTHONPATH=.:train $PY -m pytest -q -p no:cacheprovider parity/tests
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train $PY -m spire_rl.play_cli --seed MYSEED --ascension 10   # 人手动玩模拟器；输入 help 看命令
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train $PY -m parity.card_encoding_audit --out docs/card-encoding-audit.json   # 卡牌身份/编码与原生一致性
```

### 2.2 训练机（Windows `LegionB` + WSL2）

RTX 5090、WSL 里 8 个线程，**这就是全部配置，不要再问**。Conda `slay`（Python 3.12），仓库 `/mnt/c/Users/yebohou/SlayTheModel`。

```sh
conda activate slay
cd /mnt/c/Users/yebohou/SlayTheModel
CXX=g++ python sim/build.py --test          # 目录改过，第一次必须重新编译
pip install -e train                        # v12 新增共享 parity 包，重新执行 editable 安装
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"   # native-41cef1ea-port-v21
python -m pytest -q train/tests
```

该机 CPU 不支持 BF16 反向（训练在 GPU 上用 BF16，不受影响）；GPU 只能在用户工作时间挂着用，训练要按工作日分段、到点正常退出、可以接续；不要多存检查点（硬盘小）。**按约定实验由用户启动和停止。**

训练（`spire_rl.ppo`，DEVLOG 37；8 线程所以 `--workers 6`）：

```sh
python -m pytest -q train/tests                                                   # 85 项，约 4 分钟
python -m spire_rl.ppo --run runs/bench --bench --workers 6 --games 32           # 测速约 2 分钟：决策/秒、每小时决策数、显存峰值
python -m spire_rl.ppo --run runs/5090-1 --hours 8 --workers 6 --games 32        # 开训；到点保存退出；同一 --run 再运行即续训
tail -f runs/5090-1/log.jsonl
```

- 每个决策 CPU 约 1.6 毫秒，6 个进程采样上限约每秒三千多决策；217M 的瓶颈预计在 GPU。
- 显存 32 GB：若爆显存加 `--micro 128 --infer-batch 256`（只影响速度）。检查点 `latest.pt`（含优化器，217M 约 3.5 GB）+ `ema.pt`，只这两份。

### 2.3 A100 / H100（Linux，训练框架 `spire_rl.ppo`，DEVLOG 37）

```sh
CXX=g++ python sim/build.py --test --jobs 8            # 编译模拟器扩展并跑 C++ 测试（58/58）
pip install -e train                                   # spire_rl + parity；torch 需带 CUDA
python -c "from spire_rl.sim import sim; print(sim.ENGINE_RULESET_ID)"   # native-41cef1ea-port-v21
python -m pytest -q train/tests                        # 约 4 分钟
# 1) 先测速（约 2 分钟）：采样决策/秒、更新速度、每小时决策数、显存峰值
python -m spire_rl.ppo --run runs/bench --bench --workers $(( $(nproc) - 2 )) --games 32
# 2) 训练：217M 默认配置；到 --hours 正常退出，同一 --run 再执行即续训
python -m spire_rl.ppo --run runs/a100-1 --hours 10 --workers $(( $(nproc) - 2 )) --games 32
tail -f runs/a100-1/log.jsonl                          # 每次更新一行：决策/秒、平均层数、胜率、结束原因、KL、熵
```

- 显存不够：减小 `--micro`（训练每次前向的行数，默认 256）和 `--infer-batch`（采样时前向的行数，默认 512）；不影响训练语义。
- 采样慢于 GPU：加 `--workers`（每个约占一个 CPU 核，内存约 0.3 GB）；`--games` 是每个进程同时开的局数。
- 中途 Ctrl-C / SIGTERM：当前更新做完后保存再退出。`latest.pt`（含优化器）与 `ema.pt` 每 30 分钟和退出时覆盖保存，只这两份。
- 换网络大小或观察版本必须换新的 `--run`，旧检查点会被拒绝。

## 3. 用户约定（必须遵守）

- **不提交、推送、合并**，除非用户明确要求；目前由用户自行操作，需要时给命令和说明。完整工作分支为 `v111_SF2`，旧版本在 `v111_SF1`；`v111_simulator` 只保存模拟器子集。用户已完成此次建分支，不代表后续修改自动获得提交/推送授权。
- **不启动、停止、重置**训练机上的实验；本机只做代码、分析和 CPU 小规模测试。
- **保留玩家真实选择**：选牌、跳过、确认、药槽满时换药等不能用随机、自动领取或静默丢弃替代；只有原生本身直接完成的选择才自动完成。卡死只能截断，不能代选。
- **模拟器**：保留同学的 C++ 模拟器并修正规则；不重写、不换成纯原生执行、不靠删掉真实决策提速。网络需要的接口只能新增，不能借机改规则；改规则要更新 ruleset 身份（`sim/PORT_SOURCE.json`、`ENGINE_RULESET_ID`）。对齐规则时对照 `artifacts/native-source/` 逐行移植，新 ID 只追加在末尾，生成的表改生成器再重新生成，新增状态覆盖 clone、快照校验、观察和绑定。出现差异以原生 DLL 为准改 C++，不改样例。
- **可部署到原生客户端（硬要求，现在不实现但不能走偏）**：
  - 要上线的策略网络只能读 `spire.public/1` 的 `PublicState`（原生端由宿主 `NativePublicObservation` 导出），不能用旧 `obs.py`、C++ `entity_observation` 或模拟器内部状态。
  - 观察里新加的任何推算量（观察清单 A–F，如“这回合最多打多少”、动作效果预览）必须只由 `PublicState` 加共享代码算出，或者两端各实现一份并有对拍测试。**不能依赖“在模拟器副本上试走”**，客户端里没有对应的模拟器状态。
  - 价值函数看隐藏信息只用于训练，不受此限。
  - 原生端执行动作只走真实界面控件，或与界面相同的 GameAction，不加只有无界面宿主才有的捷径。
  - 宿主的读状态/执行逻辑（`NativeGameBridge` / `NativeGameScreens` / `NativePublicObservation`）与启动（`NativeBootstrap`）、传输（`HeadlessHttpServer`）保持分开。
  - 命令行只从 `PublicState` 渲染，以后可以直接接原生后端。
  - **防循环 / 防卡死属于 AI 驱动层**（读 `PublicState` → 网络 → 选动作的共享 Python），训练与上线用同一份；可以把驱动层自己记的公开历史（如已跳过次数）作为观察，可以从候选里去掉会循环的动作；不改模拟器和原生游戏。例：跳过卡牌奖励后可重开是原生行为（DEVLOG 第 26 节）。
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

**分支约定（用户 2026-11-18 指定并自行操作）**：

- `v111_SF2`：完整项目和当前工作分支，后续在现有工作目录继续开发（各机器路径不同，见 2.1）。目录清理及 `sim/`、`train/`、`parity/`、`docs/` 等已纳入 Git；有无新修改用 `git status` 核实。
- `v111_simulator`：从已提交的 `v111_SF2` 提取的模拟器子集，根目录仅 `sim/`、`.gitignore`、`LICENSE`。保留 `sim/` 目录层级，源码、生成表、绑定、依赖和固定样例均在其中；不包含训练框架、原生宿主、项目文档或根目录 `AGENTS.md`。它有独立提交历史，**不要求创建第二个本地工作区，也不需要把主工作区切换过去**。
- `v111_SF1`：保留旧版；删除或覆盖任何已有分支需用户明确指定。
- 同步顺序：先在 `v111_SF2` 提交需要发布的内容，再提取该提交的模拟器子集更新 `v111_simulator`。两分支不会自动同步；发布时比较两边的 `sim/` 子树。后续更新应在已有模拟器分支历史上追加提交，不重复初次创建分支的步骤，不通过合并完整工作区把 `train/`、`parity/` 等带进去。
- 2026-11-18 本地核验：`v111_SF2` 为 `aefad6a`，`v111_simulator` 为 `fbfdd8f`，各自与本地 `origin/` 跟踪引用相同；两边 `sim/` 子树均为 `0b6a9774eb7686ee60957603781ee1a76d60f6d8`。本次未联网刷新，不能将跟踪引用称为远程实时状态。
- `sim/build/`、`parity/stage/`、`artifacts/`、`runs/` 等继续忽略。游戏备份、反编译源码、SDK 和训练输出不会随分支上传，需另外保留。

模拟器子集可独立编译并跑 C++ 固定样例测试、`sim/tools/audit_monster_numbers.py`；准备阶段已在隔离目录重新编译，51/51 C++ 测试通过。完整注册审计 `audit_native_registry.py` 依赖 `train/spire_rl/public_catalog.json`，应在完整工作区执行；重新生成原生内容还需要本地 `artifacts/native-source/`。

- 目标原生：`v0.111.0 / 41cef1ea`，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 模拟器 ruleset `native-41cef1ea-port-v21`；宏观观察 `MACRO_OBS_VERSION=4`（96 列）；战斗实体观察 `COMBAT_OBS_VERSION=5`（112 列）；扁平公开观察 `PUBLIC_OBS_VERSION=18`；`ACTION_SCHEMA_VERSION=15`；快照 v18（Unmovable 计数改为本回合 / 本次出牌的获得格挡记录数；v17 起 Fur Coat 标记坐标等遗物状态；v16 起 Goopy 写回牌组的状态；v15 起逃跑金币比例状态；v14 起 CurlUp 来源 UID 和 Aeonglass CardsLeft 使用空闲辅助槽；旧快照拒绝）。**默认 `NativeProgressContext` 是全解锁老玩家**（用户 2026-11-18 指定），`init` / `init_seed` 的第一幕按原生在 Overgrowth / Underdocks 间各 50%；需要固定第一幕或复现旧录制时用 `init_seed_with_context(种子, 进阶, 第一幕, progress)`。公共双端契约 `spire.public/1`，**`public_obs.FEATURE_VERSION=9`**（检查点记录，不符拒绝加载）；实体行 `NUM=768` 列，动作候选行 `CAND_NUM=544` 列（语义描述字节上限 495），各新增特征的列位置见 `docs/observation-checklist.md` 末尾“编码布局”；它是独立新布局，旧网络默认仍使用 legacy 布局，新模型需设置 `UnifiedNetConfig(observation_schema="spire.public/1")`。敌人上限 6；观察新字段只追加在行尾，宏观卡片进度固定放 `num[78]`，保留 `num[79]` 的选中标记。`train/spire_rl/obs.py` 仍按固定下标读玩家行。`CARD_COUNT=597`（含 INVALID 与保留的 Grapple 槽），`Card` 仍为 304 字节。
- 模拟器的已知差异和未验证部分见 DEVLOG 第 2.4、11–14 节：**没有完成整局原生对照**；怪物 A8/A9 数值边界已核对；v15 按源码核对了 A1–A7、A10 的局外效果（A6 删牌价已修）。当前最强真实战斗执行证据仍为单个种子从 Neow 到首战、领奖并回地图的 31 步完整公共契约对照。
