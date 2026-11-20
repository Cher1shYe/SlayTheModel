# 开发日志

记录项目到 2026-11-18 为止的经过：每个阶段做了什么、遇到什么问题、怎么改的、得出什么结论。2026-11-18 工作区大翻新时，旧代码、旧文档、旧训练数据和分析结果都已删除；**旧版本的完整代码和文档在 git 分支 `v111_SF1` 上**（11-14 以来的改动由用户在另一台机器同步提交）。训练数据和分析中间结果没有进 git，已经删除，下面只保留结论和关键数字。

以后的工作接着在本文件末尾按日期追加。

---

## 1. 时间线

| 日期 | 事件 |
| --- | --- |
| 2026-09-20 起 | 项目开始：游戏模组接入真实游戏，C# 原生战斗 MCTS 原型，局外“第一个合法动作”基线 |
| 09-24 | 第一个网络 SpireFormer（`model/spireformer`） |
| 10-13 至 10-19 | C# 侧：人类对局采集、MCTS 策略采集、原生状态与合法动作协议、价值叶子；ArmG 实机接入（只覆盖选牌/选路） |
| 10-27 起 | 改用同学的 C++ 模拟器（AlphaZero 分支 `be401e8` 的副本），逐条对齐原生 v0.111.0 规则 |
| 11-08、11-09 | 对齐第二、三步完成（遗物、事件、其他角色牌池等） |
| 11-09 | 新训练框架 `spire_rl`：局外策略网络（实体 Set Transformer + 因果历史 Transformer）+ PPO，战斗交给固定 C++ MCTS |
| 11-10 | 第一轮训练诊断；NoSL 信息隔离修复（ruleset v7）及一批训练改动 |
| 11-11 | 第二轮诊断；The Future of Potions 崩溃修复（ruleset v8） |
| 11-12、11-13 | 第四轮（小网络 + 蒸馏 + 分叉）三段 |
| 11-14、11-15 | 第四轮诊断，分叉损失等修复；“按选项打分的价值头”离线测试（否定） |
| 11-15、11-16 | 修复后一轮 small-b-d1；诊断：策略不看血量 |
| 11-16 | 战斗网络实验；本幕 Boss 价值头；统一网络设计与第 3–5 步代码 |
| 11-17 | 训练机跑完 MCTS 教师数据（2,000 局）；看到 AlphaDefect，决定转向 |
| 11-18 | 用户定下新方向的主要选择；工作区大翻新 |

---

## 2. 模拟器（C++）

### 2.1 来源与原则

- 同学写的 C++ 模拟器（参考 sts_lightspeed：卡牌效果是 switch 表，`BattleContext`/`RunContext` 是可复制的结构体，搜索在 C++ 里），Python 只做网络和训练。
- 目标原生版本固定为 **v0.111.0 / 41cef1ea**，DLL SHA-256 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 原则：保留并修正这个模拟器，不重写、不换成纯原生执行、不靠删掉真实决策提速；网络需要的接口只新增，不借机改规则；改规则就更新 ruleset 身份。
- 对齐方法：对照反编译源码（`artifacts/native-source/v0.111.0/`）逐行移植；新 ID 只追加在末尾（保留 Grapple 槽不复用）；生成的表改生成器再重新生成；新增状态要覆盖 clone、快照校验、公开观察和 Python 绑定；隐藏随机顺序不能泄漏到观察。

### 2.2 已完成的对齐

种子/哈希/随机数流对齐、抽牌洗牌、手动选牌、牌实例状态、596 张原生卡牌数据导出；另外四个角色的牌池和机制（静默、故障机器人、亡灵契约师与原生样例比对 0 失败，储君只按源码）；遗物的真实选择和持续状态（Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher 等，有原生样例）；药水栏空位；34 个原先缺失的事件（含小游戏和专用战斗）；Aeonglass Boss；普通地图和 6 张原生录制地图逐点一致；按 epoch 过滤内容；原生费用修正栈；卡牌奖励选项钩子和 Lasting Candy；升阶 0–10（地图精英/火堆数、A10 第三幕两个 Boss、稀有率、药水栏等）。

### 2.3 修过的严重问题

- **NoSL 信息泄漏（11-10，ruleset v7）**：隐藏信息重采样没有按卡牌全部字段规范化，公开观察的排序没覆盖所有字段，`orbRng` 没接入运行级 CombatOrbs 流。结果是 MCTS 和观察能间接看到抽牌顺序。修复后用探针验证：只改隐藏状态，公开观察不变。
- **The Future of Potions 崩溃（11-11，ruleset v8）**：事件把原生 Event / Token 稀有度的药水当成普通稀有度处理，抽到 Power 类型时抛异常（这三种药水各 68/200 次可复现）。第三轮训练因此在第 223 局崩溃。训练 1.6 万局后才暴露，说明事件里可能还有类似的少见分支。之后改成单局异常只让该局失败并记录原因，不中断训练。

### 2.4 没有验证的部分和已知差异（新版本仍然适用）

- **从没做过同种子、同决策的整局原生对照**。第三步以后新增的规则只是照源码写的，没有用 DLL 实际执行核对。A1–A10 规则没有逐项核对。
- 11-15/16 开始搭原生无界面宿主（真实 DLL + Godot 无界面，`parity/`），读开局状态时 JSON 解析失败，还没有任何对照结果。当时在核对种子 `PARITY0001` 下先古遗物的选项（PreciseScissors / BoomingConch / SilverCrucible）。
- C++ `double` 与原生 `decimal` 的取整边界；固定牌堆、遗物容量的边界。
- `after_hand_drawn` 里 Mayhem 与遗物的先后与原生不同（只影响非铁甲组合）。
- 观察里 `nextTurnEnergy` / `nextTurnDraw` 恒为 0（占位）。
- 药水表把原生 Event / Token / None 稀有度都写成 `SPECIAL`，只有 The Future of Potions 按原生还原。
- NoSL 检查没在 Linux/WSL 上跑过；CombatOrbs 映射没经 DLL 实测。
- 训练机（WSL）的轨迹在 Mac 上重放，约 22% 会中途分叉（跨平台浮点差异）；精确重放要在同一平台。
- 11-11 最后一次完整回归：C++ 36 个测试程序全过；1,000 局冒烟 0 异常；地图 6/6；药水事件探针 0 异常。

### 2.5 为网络加的接口（ruleset 不变）

- 宏观观察 `macro_observation`（v2）：局外实体（全局、界面上下文、牌组、遗物、药水、地图节点、Boss、奖励/商店/事件选项、水晶球格子）+ 候选动作指针。
- 战斗实体观察 `entity_observation`（11-16，`combat_obs.cpp`）：玩家、遭遇、能力、手牌、各牌堆（抽牌堆按规范顺序，只给已知顶牌的位置）、待选牌、正在打出的牌、怪物、药水、遗物 + 候选动作指针。
- 批量网络搜索 `NetSearch`（`net_search.cpp`）：网络给先验和叶子价值的 PUCT；树内归一化、“赢局交给网络估值”两个选项。
- MCTS 根访问次数接口 `mcts_root`、快照 `snapshot`。

---

## 3. 训练线（旧方案：网络只管局外，战斗交给 MCTS）

### 3.1 框架

`spire_rl`：一次转移 = 一次真实局外选择；只有一个合法动作的界面自动执行；战斗由 `play_combat_mcts` 打完（普通/精英 128 次、Boss 512 次）。网络 SpireNet = 实体 Set Transformer（地图连边消息传递）→ 因果历史 Transformer → 候选指针打分；策略 = P(动作组) × P(组内目标)。奖励 `5×通关 + α×(0.05×新层 + 0.5×新幕)`，γ=1、GAE λ=0.99。独立 critic，输出未来层数、未来进幕、通关概率三个分量。

### 3.2 各轮结果

验证：固定 200 个种子，按概率采样，A0。

| 版本 | 平均层数 | 到第二幕 | 到第三幕 | 通关 |
| --- | ---: | ---: | ---: | ---: |
| 第一轮 0 局（随机初始化） | 10.96 | 1% | 0% | 0/200 |
| 第一轮 6,001 局（0.2B） | 20.81 | 34% | 3% | 0/200 |
| 第二轮 8,021 局（`best.pt`） | 23.36 | 53% | 8.5% | 1/200 |
| 第二轮 10,000 局 | 22.03 | 49.5% | 7% | 0/200 |
| 第四轮 0 局（从第二轮蒸馏的 small，约 0.02B、8 步历史） | 22.25 | 46.5% | 8% | 1/200 |
| 第四轮 3,039 局 | 29.16 | 72% | 22.5% | 5/200 |
| 第四轮 7,360 局 | 29.28 | 75% | 26.5% | 4/200 |
| small-b-d1 10,022 局（修复后一轮） | 25.56 | 59% | 14.5% | 2/200 |

各轮之间模拟器和配置都变过，不是单因素对照。第四轮 3,039 局后停在 28.5–29.3。

### 3.3 发现的问题与修改

**第一轮（6,001 局）**
- critic 学不起来：共享主干的价值头解释方差全程 ≤ 0。→ 改为独立 critic。
- 少见动作被学死：精英选择率 44% → 0.7%；约 1,000 局后火堆再也不回血（低血也 0/419）。
- 受控实验（50 个第一幕 Boss 前火堆，同种子）：升级改回血，Boss 通过率 40% → 61%（16 好 1 差）；而 Boss 搜索 512 → 2048 只到 48%。
- 模仿测试：约 5M 的同族网络能学到第一轮策略的 85%；32 步、8 步、无历史三者差别在噪声内，历史 Transformer（0.2B 中约 176M）没有可测帮助，且推理占了墙钟 48%。
- 同时修：训练条件输入去掉、按动作组的策略头、菜单循环保护（同一网格连续 64 个决策截断，不代选）、KL 早停改法、保存 `last.pt`。

**第二轮（10,000 局，11.7 小时）**
- 独立 19.6M critic 留出解释方差只有 0.05–0.09（离线同族网络约 0.29，仅用层数/血量/幕的线性回归 0.23–0.34）；在线时“拟合这一批、忘掉上一批”，批内损失到 0.002。通关分量是噪声。
- 火堆反过来：几乎总回血，满血（0.88）比 HP<30%（0.78）还爱睡。
- 白拿的东西被放弃：金币留下 18.9%、遗物 9.9%、卡牌奖励不打开 15.3%、丢药 21.5%。原因是这些决策几乎没有回报信号，熵奖励让它们保持一两成概率。
- 时间花在网络上：PPO 和 critic 更新 7.6 小时、推理 3.0 小时；采样时平均每次前向只有约 1.5 个决策。
- 第一、二轮用了同一批种子；同一种子两轮最终层数相关 0.27，说明运气占很大比重。

**第三轮**：0.2B 接第二轮 + critic 先验 + 分叉。第 223 局因 The Future of Potions 崩溃，被第四轮取代。

**第四轮（小网络 + 蒸馏 + 分叉，7,769 局）**
- 首次启动被概率重算检查拦停：BF16 舍入使采样时和更新时的对数概率差到 0.053。→ small 改 FP32，输出头固定 FP32。
- 停在 29 层的原因：旧分叉损失 `−优势 × log P` 没有上限，火堆 log P(升级) 从 −19 被推到 −539，所有血量下都一样；88% 的多选决策概率 >0.99；每次更新约 7 步就被 KL 拦停；学习率 1e-4 偏大。分叉标签噪声大（两套种子均值的可靠度：地图 0.76、火堆 0.37、选牌 0.28）。通关项占回报方差约 70%。
- 解决了白拿东西被放弃的问题，但出现新问题：开了卡牌奖励后从不跳过。
- 修复（11-14/15）：分叉损失改为有上限的 KL 形式、复用最近 4 轮分叉、KL 超限时回滚到最近一次合格的权重和优化器状态、学习率 3e-5 并随拦停自动调整、menu_loop 截断不再加 critic 估计。

**缺口 1 测试（11-15，否定）**：用分叉结果监督一个按选项打分的价值头，在 18,597 个分叉上对没见过的局，相关只有火堆 0.27、选牌 0.04、地图 0.23；选牌连只用卡牌 ID 也是 0.04，40% 的选牌分叉所有选项结果相同。→ 关掉选牌分叉（它占模拟器战斗量约 40%）。

**修复后一轮 small-b-d1（11,148 局，10 小时）**
- 训练过程正常，成绩 25.6 层，低于第四轮。
- **策略网络不看血量**：窗口内血量改成 20% 或 100%，选择概率平均只变 0.03%；决策向量里血量线性可读 R² 约 0.12。12,787 个火堆分叉明确说低血该回血，而策略各血量下回血率一样。PPO 只学到了不看局面的整体偏好。
- Boss 死亡率（到达者中）：第一幕 31%、第二幕 51%、第三幕 90%。

### 3.4 战斗的上限实验

- 后期战斗搜索量（重放第二轮后期对局，1×/4×/16× 搜索）：普通与精英死亡率 12.3% / 9.4% / 7.1%，掉血 15.3% / 12.6% / 10.6%；第二幕 Boss（19 场）81.6% / 78.9% / 73.7%，差别不显著。
- 战斗网络实验（11-16，约 1.4M 网络，3 万个决策的临时版本，188 场固定战斗成对比较）：普通、精英与 MCTS 相近；Boss 死亡率：网络单独 61.6%，网络 + 搜索 47.9%，MCTS 128 档 38.4%，256 档 43.8%。
- 本幕 Boss 价值离线测试（44.8 万个样本）：Boss 前最后一层 AUC 0.86 / 0.83（第一 / 第二幕），幕开头 0.68 / 0.74；牌组是主要预测因素；血量 +10% 使通过率高 4.2 个百分点。A0 下每幕开头的先古事件会把血回满。
- 统一网络（一个网络管局内局外，约 2.5M）的 MCTS 教师数据（11-17 训练机）：2,000 局，33 万个决策，1.8 小时；small-b-d1 局外 + MCTS 256/512/1024，本幕 Boss 死亡率 31% / 46% / 80%，41 局通关。第 0 代训练没跑（训练机上旧归档已删）。

### 3.5 教训（新版本要记住的）

1. **局数太少是根本问题**。旧方案约 800 局/小时，大部分时间花在 MCTS 和逐个决策调用网络上；PPO 从整局结果里分到每个决策的信号本来就弱，局数少就只能学到整体偏好。
2. **价值函数是瓶颈**。只看公开信息、每批只在新数据上训，就会背当前批、预测不准；结果大半像运气。
3. **网络会忽视重要的数值**（血量）。只看最终回报时，网络没有动力去读那一行数。需要更密的奖励、更准的价值，或者让这些数直接参与动作打分。
4. **没有回报信号的决策会被熵推向随机**（白拿的东西）。密集奖励和取最大评估能缓解。
5. **无上限的辅助损失会把策略推死**。任何额外的监督项都要有上限，并监控最小对数概率。
6. **战斗是最大的墙**：Boss 死亡率 31% / 50% / 80–90%，加大 MCTS 搜索量收效很小。
7. **单项改动要能归因**：每轮同时改很多东西，结果无法归到单项。
8. **模拟器的少见分支会在大量训练后才暴露**，异常要记录原因并回来修。

---

## 4. 转向 AlphaDefect 式训练（11-17、11-18）

### 4.1 参照对象

AlphaDefect（`artifacts/reference/alphadefect-evaluation-overview/`，用户从 GitHub `hmty-CHEN/alphadefect-evaluation-runs` 拉回的部分）：

- 四个角色各一个模型（故障机器人、储君、静默、Fool，**没有铁甲**），18–20M 参数的实体 Transformer，一个网络打整局（局外选择和每一手出牌），**不搜索**，从零开始纯 PPO。
- 一部分引擎打整局，其余只打单场练习战，最难的战斗多练；价值函数训练时可以看隐藏信息（策略看不到）；评估用 EMA 权重、取概率最高的动作。
- 成绩（**A10**、v0.111.0、1,000 个固定种子）：储君从零 3 天 72.2%，静默 71.2%，故障机器人 70.9%（约 6 天），Fool 59.2%（v0.113.0）。第一幕 Boss 死亡率 1.5–5.7%；85–92% 的局到第三幕；每局打 5–6 个精英；主要死在第三幕末尾连续两个 Boss。
- 输入里有引擎算好的特征：怪物招式 ID 和之后最多 3 步的预测、“这回合最多还能打它多少 / 能不能打死”、“现在结束回合会掉多少血”、手牌显示的伤害和格挡、地图路线摘要。
- 评估防卡死：敌人血量合计 20 个玩家回合没有创新低判负；一回合内反复回到同一局面就强制结束回合。
- 速度：静默 1,000 局（约 93 万个决策）在一张 4090 上 3 分钟评估完。

另有 Zero-Search 预印本（arXiv 2611.12088）：6.6M 实体 Transformer，不搜索，PPO，铁甲 A0 89.8%、A10 15.6%，用了 16.6 亿个决策；奖励每层 0.01、精英 0.02、Boss 0.1、通关 1、死亡 −0.1，加血量势函数。

### 4.2 用户 11-18 的决定

- 一个网络打整局，不搜索，纯 PPO，**从零开始**。
- **密集奖励**（形式参照 Zero-Search）。
- **练习战**。
- **直接在 A10 上训练和评估**；目标：铁甲 A10、1,000 个固定种子、EMA、取最大，超过 72%。
- 观察要系统设计：人能看到的给全，再加引擎算好的辅助结论和“只用公开信息的动作效果预览”；事件只给文字里写明的结果；卡牌稀有度保底计数可以给（它由见过的牌决定）。见 `docs/observation-checklist.md`。
- 价值函数看隐藏信息：**待定**（原理已向用户解释）。
- 训练机：RTX 5090，WSL 8 线程，这就是全部配置，不要再问。
- 下一步还要做执行层面的原生对照：修好原生无界面宿主；用 AlphaDefect 的静默/储君对局记录在我们的模拟器里重放核对（等用户拉几十局）。

### 4.3 本机吞吐实测（11-17）

单线程、随机打法：模拟器走一步约 4 微秒，导出观察约 5 微秒，Python 编码约 24 微秒，整个循环约 0.15 毫秒/决策。真实局面估计慢 2–3 倍。网络推理必须集中到 GPU 成批算。目标每秒 1 万个决策以上（旧方案约每小时 18 万个）。

---

## 5. 2026-11-18 工作区大翻新

用户确认旧数据不再需要，工作区只留给新网络。

- **删除**：旧训练数据 `runs/`；全部分析目录；10 月的 C# 工程（采集器、搜索、模组适配器、smoke、工具）、CombatSolver、ArmG 实机脚本、SpireFormer；模拟器副本里的旧 Python 训练代码（ArmG 等）、旧测试、旧文档、81 个验证记录目录；`spire_rl` 的旧训练线（SpireNet、PPO、分叉、蒸馏、critic 预训练、战斗网络、统一网络的 MCTS 教师路线）；旧诊断和设计文档；`artifacts/` 下的旧实验、旧参考副本、其他项目、用户最早的 ArmG 权重。
- **保留**：C++ 模拟器（搬到顶层 `sim/`）、原生样例（`sim/native-fixtures/`）、统一网络的观察编码和网络（`train/`，作为新网络的起点）、原生对照宿主（`parity/`）、`artifacts/` 下的反编译源码、原版游戏备份、.NET SDK、AlphaDefect 参考。
- 旧版本的代码和文档都在 git 分支 `v111_SF1`。
- 新目录：`sim/`（原 `artifacts/dev/cpp-native-aligned-20261031/simulator/`，加 `native-fixtures/`、`PORT_SOURCE.json`、新编译脚本 `build.py`；vendored `json/` 只留头文件），`train/`（原 `model/spire_rl/` 的 `sim.py`、`unified_obs.py` → `obs.py`、`unified_net.py` → `net.py`，测试 `test_obs_net.py`，吞吐脚本），`parity/`（原生宿主）。`.gitignore` 改为忽略 `artifacts/`、`runs/`、`sim/build/`、`parity/stage/` 和编译产物；`sim/` 不再需要按清单强制添加。
- 改动：C++ 测试找样例的路径（`tests/port_root.h` 以 `sim/` 为根，样例在 `native-fixtures/` 下）；`sim/build.py` 输出到 `sim/build/`，`--test` 跑全部测试程序；`train/spire_rl/sim.py` 从 `sim/build/` 加载扩展；删掉依赖旧 Python 测试的 `tools/gen_coverage.py`。规则没有改，ruleset 仍是 v8。
- 验证（本机）：C++ 36/36 个测试程序通过；新编译的模拟器与旧副本的程序跑 1,000 局冒烟结果完全相同（1,000/1,000 完成、0 异常、平均第 9.6 层、5,570 场战斗、85,525 步）；Python 10 项测试通过。
- 训练机要按新路径重新编译（`CXX=g++ python sim/build.py --test`）并 `pip install -e train`。

---

## 6. 2026-11-18 随机数机制与原生的对照（静态审计）

用户要求：拿反编译源码（`artifacts/native-source/v0.111.0/`）核对模拟器的随机数机制。这次只读代码对照，加上已有的 DLL 实测测试；没有新的整局执行对照。

### 6.1 一致的部分

| 层次 | 原生 | 我们 | 结论 |
| --- | --- | --- | --- |
| 生成器 | `MegaRandom`：xoshiro256**，SplitMix64 填 4 个状态字 | `Rng`（`sim/include/sts2/common.h`） | 逐行一致 |
| 取值方式 | `Next(n)` = `(int)(NextDouble()*n)`；`NextDouble` = 高 53 位 × 2⁻⁵³；`NextFloat(a,b)` 走 `NextDouble` 再转 float；`NextBool` = `Next(2)==0`；高斯取整用 `Math.Round`（四舍六入五成双）；`Shuffle` = 从后往前的 Fisher–Yates，`NextInt(i+1)`；计数器 `_counter` | 同 | 一致 |
| 字符串种子 | `StringHelper.GetDeterministicHashCode` = xxHash64（UTF-8、种子 0）；种子文本转大写、O→0、I→1、去首尾空白 | 同（只支持 ASCII，非 ASCII 报错） | 一致 |
| 执行验证 | — | `sim/tests/native_rng_contract.cpp` 用真实 DLL 生成的数据：20 个字符串哈希、5 个种子规范化、8 个种子 × 约 53 步（整数、区间、布尔、浮点位、双精度位、高斯、64 位）逐位比对 | 通过 |
| 全局 12 条流 | `RunRngSet`：`new Rng(Seed, snake_case(类型名))`，Seed = xxHash64(种子文本) | `run.cpp` 同名同顺序 | 一致 |
| 玩家 3 条流 | `PlayerRngSet(xxHash64(种子) + 玩家槽位)`，`rewards/shops/transformations` | 单人槽位 0，同 | 一致 |
| 地图 | `Rng(Seed, "act_{n}_map")`、`"spoils_map"` | 同 | 一致（6 张原生录制地图逐点一致） |
| 先古/幕选择 | `Rng(Seed, "act_selection")` | 同 | 一致 |
| 事件 | `Rng(Seed + 槽位 + xxHash64(事件 ID))` | `Rng(seed, 事件名)`，单人槽位 0 | 形式一致（事件名与原生 ID 的对应由事件样例测试覆盖） |
| 随机目标 | `CombatTargets` 流 | 统一走 `battle.cpp` 一个函数 | 未逐处核对，形式一致 |
| 只影响画面的随机数 | `Rng.Chaotic`、每个怪物自己的 `monster.Rng`（只用于 ToughEgg 皮肤）、地图抖动、音乐等 | 不需要 | 无影响 |

### 6.2 确认不一致：怪物生成

原生开一场战斗时用了三条不同的随机数来源：

1. **遭遇的组成和开局招式**：每个遭遇自己的 `Rng(Seed + 当前总层数 + xxHash64(遭遇 ID))`（`EncounterModel.GenerateMonstersWithSlots`）。92 个遭遇类里有 14 个用它抽怪（如 SlimesWeak 抽哪种史莱姆）或抽开局招式（如 TwoTailedRats、ScrollsOfBiting、Decimillipede 的 `StarterMoveIndex`）。
2. **怪物血量**：全局 `Niche` 流，而且同一边的怪物血量不重复：在 [最小, 最大] 里去掉已有怪物的血量，再从剩下的里 `NextItem`（`Creature.SetUniqueMonsterHpValue`）。
3. **每回合出招**：全局 `MonsterAi` 流，`RandomBranchState` 用 `NextFloat(权重和)` 再逐个减权重。

我们（`sim/src/monsters.cpp` 的 `setup_encounter`、`spawn_at`）：组成、开局招式、血量**全用 `MonsterAi` 流**；组成是按权重表抽的“阵容模式”；血量是 `next_int(最小, 最大)`，不去重。后果：

- 同一个种子下，每场战斗的怪物组成、血量、开局招式和原生不一样；
- 更要紧的是 `MonsterAi` 是整局共用的流，开战时多消耗了几次，之后**整局所有怪物的出招序列都和原生错开**。
- 分布上大致对，但不是同种子可复现的，而且血量去重这条规则缺失。

来源：怪物数据（招式图、权重、阵容）是从另一个第三方重写的 Python 引擎（`sts2-rl-agent`）导出的（`sim/tools/dump_monsters.py`），阵容权重是抽样统计出来的，招式分支权重 ×10 取整；后来的 `monster_audit_regression`、A9 伤害/效果表做过部分对照，但随机数来源没改成原生的。

### 6.3 小差异

- 招式分支：原生 `NextFloat(和)` 转成 float 后用 `≤ 0` 判定，我们用 `next_int(0, 和−1)` 整数判定。两者都只消耗一次，绝大多数情况选中同一个分支；只在落到分界点、或 float 舍入把值推到分界点上时不同。原生权重是 float，我们是 ×10 的整数。

### 6.4 没有审计到的

每条流在游戏里的**每一处使用和先后顺序**（原生约 120 处，例如生成卡牌 35 处、Niche 18 处、随机目标 17 处）没有逐处对照。只要有一处多抽或少抽，同一条流之后的结果就会全部错开。静态对照很难穷尽，需要执行层面的对照来发现。

### 6.5 建议

1. **修怪物生成**（改规则，ruleset 升到 v9）：按原生逐个移植 92 个遭遇的 `GenerateMonsters`（遭遇自己的随机数）、血量改用 `Niche` 并去重、招式分支改成原生的 float 判定。工作量中等（14 个遭遇有随机逻辑，其余是固定阵容）。
2. **执行对照**：AlphaDefect 的对局记录每场战斗开头都记了敌人血量和意图，可以直接核对这一项；原生宿主修好以后做整局逐步对照。
3. 不修的影响：训练出来的策略面对的怪物分布和原生大体一样，但“同种子复现”做不到，整局对照也会从第一场战斗开始分叉，没法用来找其他规则差异。

---

## 7. 2026-11-18 怪物生成按原生重写（ruleset v9，第一阶段）

用户要求按原生逻辑修第 6.2 节的问题，不用 AlphaDefect 的记录对照。核对时发现问题不止随机数来源：怪物数据当初是从第三方 Python 重写引擎导出的（`sim/tools/dump_monsters.py`，血量标着 `sampled_only`，阵容和开局招式是抽样统计的），有一批阵容和血量本身就和原生不同。

### 7.1 改了什么

- **新工具 `sim/tools/apply_native_monsters.py`**：从原生 `Models/Monsters/*.cs` 读 `MinInitialHp`/`MaxInitialHp`，更新 `content/monsters.json`，再调 `gen_monsters.py` 重新生成表（生成器能逐字节重现旧表，已确认）。
  - 血量改了 **24 个怪物**，例如 Axebot 40–44 → 70–78（A8 76–86），Infested Prism 200 → 161，Gas Bomb 10 → 7，Guardbot/Noisebot/Stabbot/Zapbot 约低 5，Waterfall Giant 250 → 240。没有原生类的 4 个保持原值：DOOR、DOORMAKER、ROYAL_GUARD、MYSTERIOUS_KNIGHT。
  - 固定阵容改了 **6 个**：Axebots（2 台 → 1 台）、Exoskeletons 普通（3 → 4）/弱（2 → 3）、Gremlin Merc（开局三只 → 只有 Merc，另两只在它死后出现，原来就有这段逻辑）、Slumbering Beetle（加上 Bowlbug Rock 和 Silk）、Tunneler 普通（同伴从 Bowlbug 换成先尖叫的 Chomper）。
- **开战流程（`sim/src/monsters.cpp`）**：
  - 遭遇自己的随机数 `Rng(Seed + TotalFloor + xxHash64(遭遇 ID))`（`run.cpp` 传入；`floor` 与原生 `TotalFloor` 同义，都是进过的地图点数）。按原生逐个移植 14 个带随机的遭遇：SlimesWeak/Normal、BowlbugsWeak/Normal、Flyconid、RubyRaiders、SlitheringStrangler、CorpseSlugs 两种、TwoTailedRats、ScrollsOfBiting 两种、Decimillipede、PunchOff；调用顺序与原生一致（含 `NextItem` 对只剩一个元素的列表也抽一次）。
  - 血量用 **Niche** 流，按原生 `SetUniqueMonsterHpValue`：在 [最小, 最大] 中去掉其他敌人的最大血量，从剩下的升序列表里抽；中途召唤也一样。Gremlin Merc 死后先生成 Fat 再生成 Sneaky（原生顺序），死亡中的 Merc 仍计入。
  - **MonsterAi 只用于出招**；随机分支按原生用 `NextFloat(权重和)` 浮点判定，权重为 0 时也抽一次。
  - 开局招式：Corpse Slug、Two-Tailed Rat、Scroll of Biting、Decimillipede 用遭遇抽的 `StarterMoveIdx`；Tunneler 的 Chomper 先尖叫；Toadpole 前排先 Spiken、后排先 Whirl（原来是随机）；Dense Vegetation 的 Wriggler 1/3 先咬、2/4 先扭；Punch Off 第一只先快拳。
  - 顺带修正的旧错：Decimillipede 开局编号对应错（第 1、2 种互换）；Punch Off 第一只开局应为快拳（原为重拳）、血量减免应为 2–9（原为 2–10）；Decimillipede 调整血量时应和所有队友比较（原只和前面的比）。
- ruleset 升为 **`native-41cef1ea-port-v9`**（`bindings.cpp`、`PORT_SOURCE.json`）。`BattleContext::init` 加了可选参数 `encounterSeed`，`BattleContext` 加了 `hpDyingIdx`。

### 7.2 验证（本机）

- 新测试 `sim/tests/native_monster_creation.cpp`：6 个固定阵容；400 个遭遇种子下随机阵容的形状（SlimesWeak 4 种组合都出现、Ruby Raiders 60 种排列都出现、Bowlbugs 6 种都出现等）；开局招式各不相同；Exoskeleton 血量互不相同且在原生范围；Gremlin Merc 开战不消耗 MonsterAi；整局里遭遇种子公式与独立计算一致。注意：期望值是照着原生源码写的，**没有用原生 DLL 实际执行核对**。
- C++ 37/37 通过。改了 3 个旧测试：Hatchling 的期望要算上蛋自己出生时那次 Niche 抽取；Punch Off 的开局与血量范围按原生；`native_step3_events` 的“到第三幕”门槛从 12/24 降到 10/24（v8 基线正好 12/24，v9 为 11/24；没到第三幕的局是死于打不完的战斗，见 7.3）。
- Python 10 项通过。1,000 局冒烟：0 异常、可复现；平均层数 9.6 → 9.7，战斗 5,570 → 5,633 场。

### 7.3 发现但没修的

- **怪物状态机仍是第三方导出的**：开局招式多数是抽样统计的权重（例如 Axebot 开局按 411:406:207，而原生是 RAND 分支 2:1:2、顺序不同）；随机分支的顺序和权重未核对；**Punch Construct 的招式循环方向是反的**（原生 准备 → 快拳 → 重拳，我们 准备 → 重拳 → 快拳）。20 个怪物的招式名与原生不一致（有的只是改名，如 MANDIBLE/MANDIBLES，有的结构不同，如 Skulking Colony、Cubex Construct、Test Subject）。
- **攻击伤害**：能解析的 174 个攻击招式里 12 个与原生不同（如 Axebot One-Two 5 → 原生 10、Hammer Uppercut 8 → 14，Infested Prism Jab 22 → 15），另有 27 个没解析出来。
- ~~Phrog Parasite（A10）秒杀~~：已查明不是 bug。那局牌组里有 The Gambit（赌命），打出后受到一次未被格挡的攻击伤害就直接死亡，与原生 `TheGambitPower.AfterDamageReceived` 一致；测试的贪心打法会随手打出这张牌（见第 8 节）。
- 遭遇的出场顺序：对有 `Slots` 的遭遇，只确认了这次改到的几个；其余固定阵容的顺序沿用旧表（之前的比对中 68 个与原生创建顺序一致）。

### 7.4 下一步（第二阶段）

按原生逐个移植 108 个怪物的状态机（开局状态、分支顺序与权重、重复规则、条件分支）、招式数值和效果，替换抽样得到的数据。同时查 Phrog Parasite 的问题。完成前，同种子下的出招顺序仍不会和原生一致。

---

## 8. 2026-11-18 怪物 AI 按原生重新移植（ruleset v9，第二阶段）

用户要求继续修，并查 Phrog Parasite 的问题。

### 8.1 Phrog Parasite

不是 bug：那局打出了 The Gambit，之后第一次受到未被格挡的攻击就死亡（原生同样）。

### 8.2 工具

- `sim/tools/native_monster_ai.py`：解析原生 121 个怪物的 `GenerateMoveStateMachine`（招式、跟进、随机分支的顺序/重复规则/最大次数/权重/冷却、条件分支、开局）、整数属性（含 A8 ToughEnemies / A9 DeadlyEnemies）和招式函数里的效果（加能力、格挡、塞牌、回血）。`--compare` / `--effects` 输出与 `monsters.json` 的差异。
- `sim/tools/apply_native_ai.py`：按解析结果改写 `monsters.json` 和 A9 表，再生成 C++ 表。规则：保持现有状态顺序（C++ 特例按状态编号写死）；同名招式改名表（核对过是同一个招式）；原生里到不了的状态忽略、我们多出的状态保留为不可达；按字段决定开局的怪物用字段默认值；结构或效果不同的怪物（`FULL_PORT`）整体照原生重写招式；可重复运行（结果不变）。
- 第三方导出的系统性误读：原生 `AddBranch(state, 2)`（最多连续 2 次）被读成权重 2（Fossil Stalker、Flail Knight、Spectral Knight、Scroll of Biting）；冷却被读成权重（Flyconid）；开局招式是抽样统计的权重（例如 Axebot 411:406:207）。

### 8.3 改了什么

- **104 个怪物的状态机**按原生：开局状态、跟进、随机分支（顺序、重复规则、浮点权重、冷却）、条件分支；攻击伤害和段数（A0、A8、A9）。
- **整体按原生重写**：Axebot（固定循环 重锤→一二连击，无随机；重生时 Boot Up、血量 +10×重生次数、力量 3×重生次数）、Haunted Ship（作祟→横扫→践踏，作祟为虚弱 3 + 5 张眩晕）、Skulking Colony、Cubex Construct、Infested Prism（Radiate 格挡 11、Pulsate 改为 Vital Spark）、Punch Construct（快拳给脆弱而非虚弱，循环方向更正）、Terror Eel（活力 6）、Toadpole（尖刺吐射先减 2 荆棘）、Fossil Stalker（改为原生的 Suck 3：每段未被格挡的命中加 3 力量）、Mecha Knight（火焰喷射也要攻击）。
- **原来缺失的规则**：Two-Tailed Rat 呼叫援军（原来从不召唤；现按原生的动态权重、冷却 2 回合、全体计数上限 3、5 个位置）；Entomancer 条件加 2 力量；The Obscura 给全体加 3 力量；Exoskeleton / Myte / Wriggler 按位置开局。
- **引擎层面**：
  - 敌人在**玩家回合开始时统一选下一招**（按敌人顺序，在 BeforeSideTurnStart 之后），而不是出完招立刻选；选之前别的怪看到的仍是它刚出的招（原生 NextMove）。
  - 完整记录每个怪用过的招（原来只留最近 8 个，“只能用一次”在第 9 招后会失效）。
  - 敌人回合中途召唤的怪本回合不行动（原生按回合开始时的敌人列表行动）。
  - **死亡等待复活的敌人不能被选为目标**（原来可以，贪心打法会一直打 0 血的幻象，造成僵局）。
  - 敌人上限 4 → 6（原生 Ovicopter、Living Fog 有 6 个位置，老鼠、Phrog Parasite、Fabricator 有 5 个）。战斗观察里敌人位置的独热编码随之变宽。
- 测试：新增 `sim/tests/native_monster_ai.cpp`（Axebot 循环与重生、统一选招时机、Exoskeleton 按位置开局、复活中的敌人不可选、老鼠召唤、Suck）。按原生更新了旧测试里锁定旧数值的断言（Axebot 一二连击 10×2、Radiate 格挡 11、Punch Off）。

### 8.4 验证（本机）

C++ 38/38；Python 10 项；1,000 局冒烟 0 异常、可复现，平均层数 9.7 → 10.2，战斗 5,633 → 5,873 场（随机打法）。`native_monster_ai.py --compare` 剩下的差异都已核对为等价或无关：我们多出的不可达状态（Axebot 的 RAND/SHARPEN、Haunted Ship 的 RAND/RAMMING_SPEED、Cubex 的 SUBMERGE、Test Subject 的 POUNCE）、原生里不可达的状态（Inklet 的 INIT_RAND、Phrog Parasite 的 RAND）、互斥条件的顺序（Frog Knight）、原生无跟进而我们保留的（Gas Bomb、The Forgotten）、老鼠的占位权重。`--effects` 剩下的 21 处均为提取器识别不了的写法（召唤怪的能力由其自身添加、按公式算的数值、单人下 × 玩家数），已逐个核对与原生一致。

### 8.5 仍未做到的

- **敌人顺序**：原生按遭遇的位置名排序敌人（例如老鼠召唤到前面的位置会排在最前、先选招先行动）；我们按数组顺序，召唤的怪放在空位或末尾。涉及召唤的战斗里，选招与行动顺序可能和原生不同。
- 塞进抽牌堆随机位置的牌用哪条随机数流、眩晕（SetMoveImmediate）等少数时机没有逐一核对。
- 怪物招式效果里通过特殊 C++ 实现的部分（约 40 处按状态编号写死）没有逐个与原生核对。
- 没有原生执行对照：以上都是照源码移植，同种子下的整局一致性仍需原生宿主或对局记录来验证。

---

## 9. 2026-11-18 敌人顺序与特殊代码核对（ruleset v9，续）

用户要求把 8.5 的第 1、2 条一起做，验证暂不做。

### 9.1 敌人按原生顺序

- 原生的敌人列表按遭遇的 `Slots` 排序（`CombatState.SortEnemiesBySlotName`）；没有 `Slots` 的遭遇保持加入顺序。敌人回合按回合开始时的列表顺序行动，玩家回合开始时按这个顺序选招，随机目标也从这个列表里挑。
- 实现：每个怪物一个 `orderKey`（位置名在 `Slots` 中的下标；没有 `Slots` 时为 64 + 加入序号），`BattleContext::enemy_order` 按它排序。敌人回合行动、统一选招、随机目标（`random_alive_monster`，同时排除等待复活的敌人）改用这个顺序。数组下标不变，动作里的目标编号不受影响。
- 19 个有 `Slots` 的遭遇写成表（`encounter_slot_table`）；新的召唤接口 `summon_enemy` 按原生规则选位置：
  - 第一个空位（`GetNextSlot`）：Fabricator 的机器人、Living Fog 的炸弹；
  - 最后一个空位：Ovicopter 的蛋、Two-Tailed Rat；
  - 指定位置：Fogmog 的 Eye、The Obscura 的 Parafright（“illusion”，排在本体前面）、Phrog Parasite 死后的 4 只蠕虫（wriggler1–4）；Axebot 重生在原位；
  - 末尾：Gremlin Merc 死后的两只（遭遇没有 `Slots`；顺序 Sneaky、Fat）。
- 召唤改为 C++ 按原生实现（原来是表里记录的固定召唤）：
  - **Fabricator**：防御型（Guardbot/Noisebot）+ 进攻型（Zapbot/Stabbot），用 MonsterAi 流 `NextItem` 挑选并排除上一次的；原来固定召唤 Noisebot + Stabbot。
  - Ovicopter 连下 3 个蛋（各加 Minion），**敌人回合下的蛋孵化计数为 2**（原来一律 1）；Living Fog 每次 1 个炸弹；Fogmog / The Obscura 的幻象。
- 召唤条件：原来共用“数组没满”，现按原生分开：Fabricator `CanFabricate`（存活的同伴 < 4）、Ovicopter `CanLay`（≤ 3）。“第几个位置”类条件（Exoskeleton、Myte、Phantasmal Gardener、Wriggler）改按原生位置名判断。

### 9.2 特殊代码核对

逐个对照约 40 处按状态编号写死的特殊代码。编号全部仍指向原来的招式。与原生一致的：Tunneler / Terror Eel / Ceremonial Beast / Slumbering Beetle 的眩晕与唤醒、Bowlbug Rock 失衡、Waterfall Giant（加压枪 +5、蒸汽爆发、自爆）、Gas Bomb、Guardbot 给 Fabricator 格挡、Sandpit、Thievery 偷金、Test Subject 复活、Knowledge Demon 计数、Frog Knight 冲锋、Rampart、Rocket 的包围、随机插入抽牌堆用洗牌流。

改了的：
- Fake Merchant 扔遗物：原生 v0.111.0 用自己的伤害 9（A9 10），我们按旧版本强制成 13/15；
- Tough Egg 孵化后的血量：原生 `NextInt(最小, 最大 + 1)` 含最大值（A0 19–22），我们少了最大值；
- Cubex Construct 进场 13 格挡：原生对每个 Cubex 都给，我们只在单独的 Cubex 遭遇里给，Construct Menagerie 的两个没有；
- 半血判定：原生 `当前血量 < 最大血量 / 2`（整数除法），我们写成 `当前血量 × 2 < 最大血量`，最大血量为奇数时边界差 1。

没逐行核对的：Thieving Hopper 偷牌的挑选规则、Aeonglass（本来就是照原生写的）、Doormaker / Door（原生 v0.111.0 已不在怪物池里）、Knowledge Demon 选诅咒。

### 9.3 验证（本机）

C++ 38/38（`native_monster_ai` 新增：幻象排最前、蛋的位置与孵化计数、Fabricator 机器人位置与 Minion、老鼠召唤到 second、Menagerie 的 Cubex 格挡）；按原生更新了旧测试里 Fake Merchant 和孵化血量的断言。Python 10 项。1,000 局冒烟 0 异常、可复现（平均第 10.2 层，5,879 场战斗）。

## 10. 2026-11-18 Boss 与精英特殊机制逐行核对（ruleset v10）

用户指出 Knowledge Demon 每个阶段有一次玩家选择、而我们没做；并点名要求核对实验体复活、女王魂缚、沙虫吞噬、墨宝 / 墨灵的滑溜、一层 Boss 鹿的晕眩、三层三骑士。逐个对照 `artifacts/native-source/` 后的结论如下。**更正第 9.2 节**：当时把 Test Subject 复活、Ceremonial Beast 眩晕、Knowledge Demon 计数列为“与原生一致”，实际上只核对了状态编号，没核对效果，下面几处都有差异。

### 10.1 改了的（和原生不一致，已按原生修正）

- **Knowledge Demon（Curse of Knowledge）**：原生 `ChooseCurse` 在敌方回合里弹出二选一（`CardSelectCmd.FromChooseACardScreen`）：第 1 / 2 / 3 次分别是 Disintegration（每回合结束受 6 / 7 / 8 点伤害）对 Mind Rot（每回合少抽 1）/ Sloth（每回合最多打 3 张）/ Waste Away（每回合少 1 能量）。我们原来只给计数加 1，没有选择，四种诅咒对玩家也都没有效果。现在：新增选择类型 `KNOWLEDGE_CURSE`（追加在末尾）；敌方回合在 Knowledge Demon 出招后暂停（`monster_turn` 返回 false，记住行动顺序和下一个位置），玩家选完后 `resolve_choice` 接着跑剩下的敌人和回合收尾（`monster_turn_continue` + `after_monster_turn`）；四种诅咒按原生时机实现（Disintegration 在玩家回合结束、Mind Rot 改回合抽牌数、Waste Away 改回合能量、Sloth 进“禁止打出”检查）。
- **Queen（Chains of Binding，“魂缚”）**：原生是 `Bound` 附着：玩家自己回合内每抽到一张牌就挂上，每回合最多 3 张（已有其他附着的牌不挂）；被束缚的牌每回合只能打出一张；玩家回合结束时全部清除。我们原来写成“所有牌费用 +1”，完全不对。现在每张牌加 `bound` 标记，“只能打一张”和 Sloth 统一放进新的 `hook_blocks_play`（对应原生 `Hook.ShouldPlay`），手动出牌和自动打出都检查。
- **Test Subject 复活**：原生每次倒下走 `RemoveAllPowersAfterDeath`，除 Adaptable、Painful Stabs、Minion 外的能力全部清掉——包括 Enrage、攒的力量、玩家给它挂的易伤 / 虚弱。我们原来全保留，第二、三形态继承第一形态的力量和 Enrage。其余（200 / 300 血、Painful Stabs、Multi Claw 每次 +1 段、第三形态 Nemesis 隔回合无实体、复活期间不可选中）核对一致。
- **滑溜（Inklet 墨宝 1 层、Vantom 墨灵）**：原生 `SlipperyPower` 只有 `ModifyHpLostAfterOsty`，即**格挡照常吸收整次伤害，只把扣血压成 1**；只有真的扣了血才减 1 层。我们原来在格挡前就把伤害压成 1（敌人格挡几乎打不掉），而且被格挡完全挡住也减层。另外 Vantom 的层数原生是 A0 8、A8 起 9，我们 A0 也是 9。
- **扣血修正的顺序**：原生 `Hook.ModifyHpLost` 依次是 BeforeOsty → BeforeOstyLate（Hardened Shell）→ AfterOsty（Intangible、Slippery 压成 1）→ AfterOstyLate（The Boot 把 1–4 抬到 5）。我们原来先 Boot 后 Shell，Intangible 只在格挡前压伤害。按原生，**带 The Boot 打无实体 / 滑溜的敌人每下扣 5 血**。
- **Infested Prism（Vital Spark）**：我们用的是旧版本机制（被打掉血时玩家回能量）。原生 v0.111：开战时玩家所有技能牌挂 `Tainted`（A0 2、A9 3），战斗中新进入的技能牌也挂；打出被污染的技能牌，玩家获得等量 Tainted 能力，敌方攻击对玩家额外造成这么多伤害，敌方回合结束清除；Prism 死后所有污染清除。现在每张牌加 `tainted`，与 Galvanized 共用新的 `afflict_entering_card`（原来同样的代码复制了 5 份）。旧测试 `r6_vital_spark_energy` 断言的是旧机制，改为按原生断言。
- **Ceremonial Beast（鹿）**：Plow 破除时原生同时移除力量和所有临时力量类能力；我们只把力量清零，没清临时扣减记录，回合结束时又把玩家临时扣掉的力量（如 Dark Shackles）“还”回去，鹿凭空多出力量。其余（Plow 150 / A9 160、血量 ≤ Plow 时晕眩一回合，然后 Beast Cry → Stomp → Crush 循环）核对一致。
- **三骑士**：Flail Knight 只有力量，一致。**Spectral Knight 的 Hex**：原生在它死亡时移除（牌上的 Hexed 清除），我们原来整场不消失，手里没打出的牌回合末一直被消耗。**Magi Knight 的 Dampen**：原生把玩家所有已升级的牌降级，Magi Knight 死后升回来；我们完全没实现（只有一个无效果的状态）。现在每张牌加 `dampened` 标记。
- **出场能力数值全量核对**（新脚本对比所有怪物 `AfterAddedToRoom` 在 A0 / A8 / A9 的取值）：除上面的 Vantom、Infested Prism 外，Globe Head 的 Galvanic 在 A9 原生是 8，我们是 6。三处都写进 `tools/apply_native_ai.py` 的 `INNATE_AMOUNTS`，重跑生成器不会丢。

### 10.2 核对一致、没改的

- **The Insatiable（沙虫）的吞噬**：Liquify Ground 给自己 Sandpit 4，加 6 张 Frantic Escape（3 张随机插入抽牌堆，用洗牌流；3 张进弃牌堆）；敌方回合开始 Sandpit −1，到 0 直接击杀玩家（无视复活类效果）；打出 Frantic Escape 使 Sandpit +1，这张牌本场费用 +1。和原生一致，补了测试。
- Aeonglass：用户确认不用再看。

### 10.3 接口和身份

- ruleset `native-41cef1ea-port-v10`；战斗实体观察 `COMBAT_OBS_VERSION=3`：选择类型独热多一位，牌行末尾追加 bound / tainted / dampened，玩家行末尾追加“本回合已打出束缚牌”。都是玩家看得到的信息。**新字段只追加在行尾**——中途我曾把它插在玩家行中间，`train/spire_rl/obs.py` 按固定下标（`P_POTIONS = 39`）读玩家行，Python 测试当场报错，已改为追加。旧的扁平公开观察 `PUBLIC_OBS_VERSION=16`（选择类型变宽）。
- 快照 v11：`Card` 的字段布局变了（大小仍是 304 字节，新字段放进了原有的填充位），旧快照不能再读。
- 注意：`native_step3_events` 这个测试在 `main` 里放了多个 `RunContext`（每个约 630 KB），离 8 MB 栈上限很近；`Card` 一旦变大就会栈溢出（这次加 `tainted` 时出现过，挪进填充位后解决）。以后给 `Card` 加字段先看大小。

### 10.4 验证（本机）

C++ 38/38；`native_monster_ai` 新增 Knowledge Demon 选择与恢复、四种诅咒、魂缚、实验体三阶段、沙虫、滑溜（含 The Boot）、Vital Spark、鹿的晕眩、三骑士。Python 10 项。1,000 局整局冒烟 0 异常（随机打法平均只到第 10.2 层，碰不到二三幕 Boss），所以另对改动涉及的 9 场战斗各随机对打 400 局：0 卡死、0 非法动作；Knowledge Demon 平均每场 3 次诅咒选择。**这些都是“按原生源码移植并通过自测”，不是和原生 DLL 对拍过的结果。**

### 10.5 仍未核对的

Thieving Hopper 偷牌的挑选规则；一张牌同时可能被多种附着影响的组合（如 Hexed 与 Bound / Tainted，现实中这些不在同一场战斗里出现）；怪物以外的其余规则仍按第 2.4 节。

---

## 11. 2026-11-18 原生宿主启动与开局至首战对照（ruleset v11）

用户授权尝试真正运行原生对照并修正模拟器，同时要求模型动作与原生动作的含义一一对应。此次保留 C++ 执行器，修复 `parity/` 宿主和部分语义适配，再从第一个实际分歧向下追原生源码。最终完成单个种子开局至首战结束的 24 步真实执行比较；**已覆盖的公开子集相符，不代表整局或全部模型观察已经对齐。**

### 11.1 真实执行确认了什么

- Godot 无界面宿主已能加载保存的 v0.111.0 游戏运行时，初始化模型与独立测试存档，开始铁甲 A10 单人局，通过 HTTP 返回原生状态并接收动作。没有修改保留的游戏安装或用户正常存档。
- 实际开局记录 `parity/stage/native-initial-18779.json`：输入种子 `PARITY0001`，原生规范化为 `PAR1TY0001`；Neow 三个选项依次为 **NEW_LEAF、GOLDEN_PEARL、SILKEN_TRESS**。旧 C++ 则给 PRECISE_SCISSORS、BOOMING_CONCH、SILVER_CRUCIBLE。修正后 C++ 给出原生这三项，事件 RNG 消耗为 19 次。
- 原生实际选择 **GoldenPearl 后增加 150 金币**；这项领取效果相符。随后发现原生仍在 Neow 完成页，要求玩家点击 **Proceed**，而 C++ 直接进入地图。本批补 C++ 的真实 Proceed 决策后继续实时重放，初始 / GoldenPearl 后 / Proceed 后三个比较点相符；进入首战又发现遭遇差异，见第 11.7 节。
- 修正完整遗物池后再次实时执行，完成首场双 Toadpole 战斗：**提交 24 个动作，24 个决策点的已覆盖公开字段与合法动作语义均相符**，双方结束时均为 **51/80 HP、249 金币**。到奖励页因适配器尚不支持奖励选择而停止；完整记录与离线回归见第 11.8 节。
- 上述是本批原生实际执行证据的范围。其余新增遗物、额外回合、选牌和组合均是源码移植与自测，不能称为已和 DLL 对拍通过。

### 11.2 先对齐初始化上下文

原生独立测试存档已揭示所有 epochs，但历史局数为 0、没有遭遇发现记录、Underdocks 已解锁而尚未发现。这种上下文下，原生首幕为 **UNDERDOCKS**，随后是 HIVE、GLORY。C++ 普通初始化默认首幕 OVERGROWTH，且默认历史上下文不同；直接只传相同种子会把初始化差异误判为游戏规则错误。

宿主现在按原生 `ActModel.GetRandomList` 选择章节并输出规范化种子、历史局数、章节、epochs 和已见遭遇；对照入口显式传入相应 `NativeProgressContext`，不靠改样例或改种子凑结果。Neow 候选本身的分歧另有明确源码原因，不是简单由历史局数造成。

### 11.3 Neow 候选和缺失效果

按 `Models/Events/Neow.cs` 移植完整声明顺序：10 个负面组选项、14 个正面组选项及 6 个额外候选。原实现只有 6 / 9 个，且误把 ScrollBoxes 放在负面组；互斥过滤和可选候选的随机调用顺序也不完整。现在先选负面组选项，按其身份去掉冲突项，按原生次序抽取可选候选，最后进行可用性过滤和洗牌。单人排除 MassiveScroll；Kaleidoscope 要求全部五角色池解锁；ScrollBoxes 按本角色已解锁普通 / 罕见卡数量判断。没有只为当前种子的三件遗物写特例。

新生成器 `sim/tools/apply_native_neow.py` 从原生类追加内容，保持旧 ID 不变并重新生成表。新增 9 个遗物 ID：DowsingRod、HeftyTablet、NeowsBones、NeowsSacrifice、FishingRod、Kaleidoscope、PhialHolster、WingedBoots、NeowsTalisman；Ambergris 药水也追加在末尾。对应效果已实现，而不是把空效果 ID 放进池：

- **DowsingRod**：获得 Dowsing 任务卡。按原始地图点是否为 Unknown 累计进入次数，第 5 次变成 Abundance；事件内部追加的战斗不多算一次。变牌遵守原生追加到牌组末尾及获得卡牌的钩子。Abundance 按当前铁甲范围生成三张不同的本角色能力牌，全部升级，保留真实选一张，本回合免费加入手牌。
- **HeftyTablet**：三张稀有牌中可选一张，也可跳过；选择处理完后再获得 Injury。使用新的 `cardGrid.kind=16`，按原生普通非战斗生成路径，不额外抽升级概率。
- **NeowsBones**：按 Neow 全部可用候选（排除自身）洗牌后展示两件遗物，必须分别领取；其中一件若引出选牌或其他奖励，先完成内部流程，再回到外层剩余遗物。两件都完成后才从原生可生成诅咒池抽一张。没有随机代选、自动领取或提前跳过。
- **NeowsSacrifice / PhialHolster**：前者尝试获得 Ambergris，然后加 Guilty；后者加一个物理药槽，再用 CombatPotionGeneration 流生成两瓶药。原生这两件遗物调用 `TryToProcure`，满槽或 Sozu 拒收时忽略失败，**没有换药选择界面**；因此这里允许按原生失败继续，与需要真实选择的普通药水奖励区分。固定存储容量在领取前检查。
- **FishingRod**：按原生普通战斗完成计数，每三次从可升级牌中随机升级一张，使用 Niche 流，保留持久计数与遗物钩子顺序。
- **Kaleidoscope**：生成两套牌奖励，每套三张分别来自不同的其他角色牌池；两套先生成，再进入真实奖励选择流程。
- **WingedBoots**：有剩余次数时允许选下一行任意存在的节点；只有走非原连线时消耗一次，共三次。
- **NeowsTalisman**：选牌组中最后一张 Basic Strike 和最后一张 Basic Defend 升级；最后一张已升级时，不改选更前面的牌。
- **ScrollBoxes**：删除旧实现中错误的清空金币效果，保留原生卡组包选择。

### 11.4 Ambergris、Proceed 与状态接口

- Ambergris 恢复最大生命一半（整数除法）。战斗中还给予额外玩家回合：玩家回合结束后跳过整个敌方回合，不额外推进敌方招式 RNG 或敌方回合持续时间。新增 `combatRound` 区分敌我轮数和玩家回合数，额外玩家回合不增加该轮数。
- **仅本次核对到的 Neow** 补领取后的 Proceed：`eventPage=126` 表示遗物取得尚在等待选择或奖励，事件选项为 0；全部处理完成后 `eventPage=127`，唯一合法 `EVENT_CHOICE 0` 表示 Proceed，点击后才回地图。没有新增动作类型，也没有提前绕过领取中的选择。其他事件的完成页尚未作全面原生执行核对。
- NeowsBones 保存外层两件已公开遗物、已领取标记和嵌套阶段，覆盖克隆、快照校验、公开观察和绑定。Dowsing 复用 `Card.guiltyCombatsSeen` 这个既有按卡保存的进度字节；Guilty 和 Dowsing 身份互斥，变牌重置进度，`Card` 仍为 **304 字节**。
- ruleset 升为 **`native-41cef1ea-port-v11`**；`MACRO_OBS_VERSION=3`、`COMBAT_OBS_VERSION=4`、`PUBLIC_OBS_VERSION=17`、快照 **v12**。宏观 CONTEXT 行追加 Bones / Hefty 信息，玩家战斗行追加 `combatRound`。宏观卡片进度固定使用原先未用的 `num[78]`，保留 `num[79]` 的网格选中标记，**不移动旧牌组选择、来源、价格或附魔字段**。扁平观察的新增状态也放在各自尾部。旧版本快照不能直接读入。

### 11.5 原生动作接口做到哪了

宿主投影补充公开手牌位置 `slotIndex`、怪物 `slotName` / `enemyOrderIndex`、能力 modelId、物理药槽与容量、总层数和战斗回合，以及选牌对象身份。先古遗物选项从实际 `EventOption.Relic.Id` 读取，不猜展示文本；原生实体 ID / actionId 和 C++ UID / 数组下标都只作为执行句柄。

`parity/semantic.py` 只对已实现的公开子集建立语义键，`parity/compare.py` 可据此进行有步数上限的诊断。当前范围是 Neow 开局 / Proceed、地图坐标、普通出牌和结束回合的部分通路；**并未完成模型完整观察的双端接入**。牌的全部修饰与附着、能力与结构化意图、遗物计数、公开牌堆实例、药水、奖励和其他真实选择仍未覆盖。适配器遇到不支持的状态、动作或含糊目标必须明确停止；单元测试不能替代真实游戏重放。

多敌人映射新增只读 `BattleContext.monster_positions`，版本 `MONSTER_POSITION_VERSION=1`：返回物理槽索引、原生槽名、当前敌人顺序、存活 / 复活状态。槽名逐项覆盖原生 **19 个遭遇的 Slots 覆盖声明**；语义键使用公开位置，不将原生列表下标强行对应 C++ 物理槽。宿主以原生 `CombatState.Enemies` 成员资格过滤仍在播放死亡动画的尸体节点，保留原生尚未移除的复活对象；适配器对复活过渡仍明确报 unsupported。首战中第一只死亡后，剩余敌人的原生 rank 0 正确映射到 C++ 物理槽 1，已有真实记录与离线回归。

### 11.6 验证与下一步

- **最终统一验证：C++ 43/43、训练 Python 31/31、parity Python 40/40 通过。**本批新增五个 C++ 程序：`native_neow_generation`、`native_neow_relic_effects`、`native_neow_potions`、`native_abundance`、`native_relic_pool_alignment`。覆盖开局候选、领取与嵌套选择、Proceed 边界、任务变牌、额外回合、完整遗物池、克隆和快照；旧观察 / 快照测试按新尾部布局和版本更新，保留机制断言。训练测试为原 10 项加 21 项敌人位置检查；parity 包含保存的真实 24 步离线重放与敌人死亡后位置映射检查。
- 新增 NoSL 检查：改变 Niche / Shuffle / Rewards 等隐藏 RNG 状态时，NeowsBones 各阶段的公开观察不变；卡片进度变化只影响新增宏观字段，不挤动原有字段。
- 本轮使用 `/opt/anaconda3/bin/python3.11`（含 pytest、numpy、torch）；旧 `~/micromamba/envs/sts2/bin/python` 不存在，AGENTS 本机命令已更正。原生宿主在对照完成后正常停止，未提交或推送。
- 下一步从首战后的奖励选择继续扩展，随后覆盖药水、其他真实选牌和复活过渡，逐项增加完整模型观察并扩展到更多遭遇。Thieving Hopper 偷牌挑选规则、A1–A10 逐项核对及第 2.4 节其余未验证范围仍保留。不得把测试数字或单个种子的匹配扩写为整局原生通过。

### 11.7 首战差异追到完整遗物池与 UpFront 顺序

实时重放记录在 `parity/stage/reports/opening/20261118T141057Z-PARITY0001-892e4e/`。相同 fresh-unlocked-host 上下文、选择 GoldenPearl、Proceed、移动到 `(列 0, 行 1)` 后，原生为 **TOADPOLES_WEAK，两个 Toadpole 血量 25 / 26**；旧 C++ 为 SEAPUNK_WEAK、49 血。手牌原本相同。Underdocks 没有首战发现顺序改写，遭遇列表声明顺序和 GrabBag 重抽规则也不是这次根因。

真正的分叉发生在生成遭遇之前：

- 原生 `RelicGrabBag.Populate` 先处理 SharedRelicPool 的 **118 项**，再为玩家处理 Shared + Ironclad 的 **8 项**。按原生声明顺序建立稀有度分组，按分组第一次出现的顺序洗牌；Shared 重载还会洗 Event / Ancient 组，玩家重载才先过滤成 Common / Uncommon / Rare / Shop。
- C++ 旧实现按本地枚举和 `pool` 分类建池，提前过滤掉 `relic_implemented == false` 的 15 项，混入原生 Shared 池里没有的 TwistedFunnel，忽略 Shared 的 Event / Ancient 组，并固定按 Common → Uncommon → Rare → Shop 洗。结果初始化只消费 **201 次 UpFront**，原生完整流程应为 **230 次**；之后事件、遭遇与遗物顺序一起错开。不能用额外空抽 29 次来补偿。
- 新工具 `sim/tools/gen_native_relic_pools.py` 读取原生池声明，生成 `native_relic_pools.inc`；保留所有原生候选和声明顺序，不更改已有 ID。`init_relic_bags` 按实际分组洗牌；不可通过当前四类抽取接口领取的 Event / Ancient 临时组仍真实消费洗牌 RNG，普通四组才写入持久袋。Shared 普通袋数量为 **25 / 30 / 35 / 25**，玩家为 **26 / 32 / 38 / 26**。共享池刷新和快照校验也改为原生池成员规则，不再以实现状态删除候选。

**未支持范围现在明确暴露，不再隐藏在池过滤里。**以下 15 件仍未标为完整支持（其中 LastingCandy、WingCharm 等已有部分效果代码，不能笼统称为空实现）：JuzuBracelet、GamblingChip、LastingCandy、PrayerWheel、UnsettlingLamp、WhiteStar、DollysMirror、GnarledHammer、Kifuda、MiniatureTent、MysticLighter、Orrery、PunchDagger、RoyalStamp、WingCharm。本轮不扩展这 15 件的全部效果。`pull_relic` 若实际抽到允许出现但未完整支持的候选，会在移出袋子前抛出 **`unsupported native relic effect: <ID>`**；对照 / 长局 / 训练必须将它识别为覆盖边界并停止，不能跳过候选、领取空效果、自动重抽或记成正常死亡。原先能继续的随机长局现在可能更早中止，这是揭示原有缺口，不是已完成整局规则的证明。

新增第 43 个 C++ 程序 `native_relic_pool_alignment` 和固定源码顺序样例 `tests/fixtures/native_relic_pools_41cef1ea.json`：检查 all / no epochs 的两套完整池顺序与 RNG、230 次初始消耗、含未完整支持候选的快照恢复、明确的 unsupported 中止。修正后的 C++ 首战与保存的真实记录相符：TOADPOLES_WEAK、25 / 26 血、手牌 **Strike、Strike、Bash、Strike、Defend**；随后新的实时重放一直推进到首战结束，已覆盖的公开子集逐步相符，见第 11.8 节。

完整池暴露未实现边界后，首轮全量测试为 39/43：`native_step3_events` 和 `snapshot_validation` 抽到 RoyalStamp，`relic_contract` 抽到 UnsettlingLamp，`rules_regression` 抽到 Orrery。这四个测试中的商店、事件、快照和多件奖励流程改用明确的已支持遗物袋 fixture，使各自机制检查不依赖无关的未实现效果；没有修改生产池、任意换种子、删断言或降低检查阈值。`relic_contract` 的原生完整池抽取检查保留，并验证遇到不支持候选时明确中止；完整原生池和中止前不移出候选另由 `native_relic_pool_alignment` 覆盖。最终统一重跑 **43/43**，但这不表示随机长局或训练能绕过上述 15 件遗物的覆盖边界。

### 11.8 首战完整真实重放与固定回归

修正后的实时报告为 `parity/stage/reports/first-combat-fixed/20261118T142940Z-PARITY0001-980679/`。保持原始种子、fresh-unlocked-host 上下文和真实动作，不改原生样例：GoldenPearl → Proceed → `(列 0, 行 1)` → 普通出牌 / 结束回合，直到双 Toadpole 战斗结束。报告记录 **24 actions_submitted、24 aligned_decisions**，结束时双方 **HP 51/80、金币 249**；第 24 步后的奖励页报告 `unsupported`，没有代领、跳过奖励或把未比较的奖励内容称为一致。这是有上限的诊断动作序列，**不是训练策略评估**。

固定原生记录保存在 `parity/fixtures/native-first-combat-parity0001-a10/`，离线回归从相同初始化逐步重放 24 个动作，检查已覆盖的状态与合法动作集合、第一只怪死亡后 rank 0 → C++ 物理槽 1 的映射，以及最终奖励页的 51 HP / 249 金币。该回归纳入 parity **40/40**；固定记录便于以后发现退化，不能扩展为未走过的遗物、药水、复活、其他奖励选择或完整观察已经通过 DLL 对照。

---

## 12. 2026-11-18 公共模型接口与真实选择补全（America/Los_Angeles，ruleset v12）

用户要求补全上一轮发现的接口和遗物缺口，并同步 AGENTS；随后要求集中核实、加快完成。本批仍保留 C++ 执行器，没有训练、提交或推送，也没有修改原始 DLL 或旧原生样例。

### 12.1 一个模型使用同一套输入和候选动作

新增 `train/spire_rl/public_obs.py` / `public_catalog.json`，公共契约 `spire.public/1`。C++ `public_model_state` 与宿主 `NativePublicObservation` 分别导出公开事实，经过同一个 Python 编码器，网络选择 `UnifiedNetConfig(observation_schema="spire.public/1")`。候选按公开语义排序，原生 actionId / GUID 和 C++ UID / 物理索引只用于路由。不能缓存这一新契约的整段局外上下文，因为牌组、遗物显示等公开状态可能在战斗中变化；网络显式拒绝误用旧缓存。

覆盖牌实例的费用与修饰、附魔/苦难/动态变量、当前关键词、保留与临时状态、公开牌堆和能从操作推知的顶牌；能力实例显示、结构化意图、公开遗物计数、物理药槽和排队；地图、奖励/商店商品、事件页、选牌上下限与预览。无序牌堆按公开内容规范化，抽牌堆的真实随机顺序、RNG 和私有 AI 状态不进入输入。真实隐藏重采样、UID 改名、无序牌堆重排均有观察不变测试。旧 Crystal Sphere 观察也修正为只有完整揭晓奖品后才暴露类型，不再通过局部揭开格泄漏类型。

`parity/compare.py` 默认比较完整公共事实与每一个网络输入张量（含候选），通过标签为 `aligned_model_interface`。旧 `subset` 模式仅保留历史证据回归。缺字段、未知模型、含糊目标或特征容量超限明确停止，不补零、不截断、不静默删除合法动作。nullable 原生药槽 `modelId` 因 JSON `WhenWritingNull` 被省略时解释为空槽；非 nullable 字段仍必须存在。

这表示双端接入已实现，**不表示所有状态已经逐个用 DLL 验证，也不表示整局规则已对齐**。

### 12.2 保留原生的真实决策边界

- 手牌选择改为选中/取消选中/确认后生效；满额后替换最后一张。药水可在原生允许时提交，选牌过程中的使用/丢弃按 FIFO 排队，关闭选择后执行；重复提交同一物理药槽被拒绝。自动选择仅保留原生本身的强制路径。
- 商店删牌和休息升级经过真实网格选择、预览、确认或取消。Miniature Tent 保存本次休息已用选项，各选项至多一次，并保留 Proceed；Pumpkin Candle 添加 Kindle。
- 宝箱预掷内容在开箱前隐藏；开箱、领取遗物、放弃和 Proceed 分开。Silver Crucible 的空箱和首次存档 Gorget 规则按源码处理。
- 普通事件结束保留完成页，点击 Proceed 才离开；保留刚才选项与页的公开历史以恢复确切页面键。Battleworn Dummy 战斗结束恢复事件完成页；不恢复事件的战斗仍按原生直接完成房间。
- 奖励支持逐项领取、正常卡牌奖励跳过后重开、Driftwood 重掷（保留原奖励的生成来源与已经重掷标记）、Forbidden Grimoire 战后免费删牌（取消不消耗）、Lantern Key 独立特殊卡奖励。新增 RunAction 37/38/39；旧 ID 保持不变。
- Gambling、Pael’s Eye 与消耗触发 Dark Embrace → Stratagem 的嵌套选择支持暂停/恢复。核实过程中发现 Gambling 在回合开始遗物阶段被内层选牌打断后漏抽剩余牌，已修正恢复条件；通用消耗确认保存紧凑的已确认 UID 队列与源牌，不再覆盖内层 pending。

### 12.3 遗物和相关规则

此前 15 件覆盖边界全部补上：Juzu Bracelet、Gambling Chip、Lasting Candy、Prayer Wheel、Unsettling Lamp、White Star、Dolly’s Mirror、Gnarled Hammer、Kifuda、Miniature Tent、Mystic Lighter、Orrery、Punch Dagger、Royal Stamp、Wing Charm。保留完整原生池，不再依赖过滤这些候选来继续运行。追加 Adroit / Momentum / Royally Approved 附魔，旧 ID 不动；`Card` 仍 304 字节。

公共计数核对同时纠正 Pumpkin Candle 的五场燃料、Pendulum 每三回合额外抽牌、Stone Calendar 第七回合结束伤害、Pael’s Eye 首次无手动出牌回合的额外回合，以及 Brilliant Scarf 的手动出牌计数。Unsettling Lamp 精确跟踪首张牌/首次能力施加，避免多重钩子重复翻倍；药水等非卡来源不触发。

Tender / Sloth 使用能力实例自己的本回合出牌计数，不能直接拿获得能力之前的总出牌历史代替。Hexed 保存为牌的真实苦难，不能覆盖 Bound / Tainted / Galvanic；解除 Hex 时清除对应附着。Slither 的随机费用通过原生式费用修饰实现，避免篡改基础费用。相关状态覆盖克隆、快照校验、绑定与观察。

Gnarled Hammer / Kifuda 的原生 min=0/max=3 流程存在零张预览行为：确认零张不完成获得；不能擅自替玩家选一张来解除。保留原生真实决策；极端原生 UI 异常仍由对照宿主明确报错/停止。

### 12.4 完整观察发现的实际差异

1. **地图房间类型**：首次真实完整开局帧有 65 个节点，路径相同但 6 个类型不同。根因是 C++ 多出 `if (ascension >= 6) --numRests`；原生 A6 为 Inflation，`MapPointTypeCounts` 只按 A1 增加精英，没有减少休息点的规则。删除后当前种子的全部节点/连线与 DLL 一致，并增加 A5/A6 三幕不改变地图的回归。旧测试原本断言“A6 减少休息点”，按原生改正，不修改原生帧。
2. **Neow 完成页**：原生 Neow 虽传入 DONE.POSITIVE / DONE.CURSED，但 `AncientEventModel.RelicOption<T>` 在转调时丢弃 customDonePage，实际 DLL 显示 `NEOW.pages.DONE.description`。模拟器观察按实际执行结果改为 DONE，不把源码调用处的意图当成效果。
3. **空药槽**：真实 JSON 省略 null modelId，而公共读取器原先将它当成字段缺失；按宿主序列化约定补 nullable 处理。

原生初始记录与逐步报告在 `parity/stage/reports/public-v1/`。最终实测覆盖、固定样例和统一测试结果见第 12.6 节。

### 12.5 版本和构建

ruleset `native-41cef1ea-port-v12`；快照 v13；宏观观察 v4 / 96 列，战斗实体观察 v5 / 112 列，扁平观察 v18，动作 schema v15。旧实体字段保留原位置，附魔新增独热在尾部追加，牌组进度仍 num[78]、选中仍 num[79]。新公共模型契约是独立布局，不与旧权重混用。

本轮曾因共享工作区编译中途修改头文件导致扩展混入不同 ABI。现在编译前冻结源码；`sim/build.py` 记录输入指纹，若构建中途变化则不发布扩展，并使下次构建重新编译。不能把这种加载失败当成模拟规则错误。


### 12.6 最终实测与统一验证

- 完整在线报告：`parity/stage/reports/public-v1-final/20261119T022748Z-PARITY0001-7a3de6/`。全新独立存档 `SlayTheModelParity20261119Public`，真实 v0.111.0 / 41cef1ea DLL，铁甲 A10，PARITY0001，fresh-unlocked-host。
- **31 个动作、32 个决策点全部 `aligned_model_interface`**。范围：Neow 领取 Golden Pearl / Proceed → 地图 → 首战双 Toadpole → 领取 9 金币和 Ashwater → 打开卡牌奖励 → 跳过 → 重新打开相同奖励 → 领取 Thunderclap → 离开奖励返回地图。两端末态 **51/80 HP、258 金币、12 张牌（A10 初始牌组含 Ascender’s Bane）、Ashwater**。
- 原始 32 帧、配置、动作和摘要固定到 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/`，manifest 保存原始字节 SHA-256。新离线回归逐帧比较完整公共事实、全部实际编码张量与合法动作，并重放全部动作。旧 v11 样例完全保留，没有补造字段。
- **C++ 46/46、训练 Python 39/39、parity Python 63/63**；原生 C# 编译 0 warning / 0 error。训练测试在仓库根和 `train/` 工作目录均通过；editable 包同时安装 `spire_rl` 与共享的 `parity`，构建验证通过。修正了卡牌指纹错误导入 `train.spire_rl` 导致与其他工程同名 train 模块冲突的问题。
- 奖励页实际发现原生 PlayerCombatState 在战后仍存留；公共 DTO 现在按 `CombatManager.IsInProgress` 判定是否导出战斗数据。31 步实测已验证公共 DTO 修正；手动诊断顶层 Player 元数据随后同步相同判定并编译通过，避免将战后网格误识别为战斗选择。保存帧的旧顶层残留字段保持原样，公共模型只读已验证的 PublicObservation。
- 宿主已正常停止；未训练、未提交、未推送。接下来应扩展到商店、休息、宝箱、附魔/删牌选择、复杂药水和复活，继续按真实差异修正。此前 15 件遗物与额外机制的测试主要仍为源码自测，不能把本轮单种子轨迹扩大为全机制或整局已一致。`NATIVE_PARITY_COMPLETE` 保持 false。

---

## 13. 2026-11-18 基础注册审计与固定编号（America/Los_Angeles，ruleset v13）

用户要求先核对卡牌、遗物、事件、怪物和先古之民的基础注册，避免训练后发现模拟器与原生身份对不上。本轮同步检查药水与遭遇池，没有扩展为所有效果重写。完整范围、例外与复查命令见 [registry-audit.md](registry-audit.md)，逐项结果见 [registry-audit.json](registry-audit.json)。

### 13.1 原始 DLL 证据

新增宿主 `NativeRegistryExport.cs`，由 `STS2_REGISTRY_OUTPUT` 触发离线导出；初始化实际游戏后读取 ModelDb，正常创建 Ironclad A10 对局获取升阶血量，然后自动退出。未启动 HTTP 服务、未修改 DLL 规则。宿主编译 0 warning / 0 error，独立存档 `SlayTheModelParityRegistry20261119` 导出成功。退出时 Godot 有无界面资源清理警告，进程退出码为 0，完整 JSON 已解析；警告不是注册匹配证据。

原始字节固定在 `sim/native-fixtures/native-registry-41cef1ea.json`，SHA-256 `2fff4579c9fcb9c8eba920a6316ca711267529e041a858d49c9100773caa2969`。游戏 DLL SHA 仍为 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。既有完整卡牌 metadata 的原始 SHA `18290c28fe26184c533f4d18b0199d6ba7fef92a745eb8024d2d5f798e10cdb4` 也固定核验。旧原生轨迹和样例均未修改。

DLL 实际枚举：596 卡牌、299 遗物、66 药水（含 1 Mock）、57 普通事件、8 先古、107 活动怪物、85 活动遭遇、4 幕；注册全集 1,660 个模型包含其他类别和测试类，不能当活动内容数量。

### 13.2 已确认并修正的差异

1. **遗物 12 个属性**：Permafrost/TinyMailbox 为 Uncommon，BagOfMarbles/RedMask 为 Common，Bellows 为 Rare，LastingCandy 为 Uncommon；FresnelLens/LoomingFruit/VeryHotCocoa 为 Shared，TwistedFunnel 为 Silent；Circlet/DeprecatedRelic 的 None 写入原始表，不再靠名称补救。保留合法双池遗物。前三件由 Event 改成 Shared 后仍显式标记已实现，避免分类修正意外使效果停用。`apply_native_item_metadata.py` 从固定 DLL 导出更新数据，再重生成表。
2. **药水 25 个目标属性**：23 种由 Self 修为 AnyPlayer；FoulPotion 战斗外 TargetedNoCreature、战斗内 AllEnemies。战斗内条件依据原生源码，明确不是此次 DLL 战斗执行结果。PotionTarget 只在末尾追加枚举；静态 PotionDef 增加 combatTarget，运行状态结构不变，旧观察位置不变。
3. **卡牌**：MadScience 漏写 native_id/native_class/native_pool_order，顺序应为 8014。根因是生成器对原生 Type.None 提前跳过，现先写公共身份元数据。所有 CardId 保留。未配置模板的 None/Self 与旧基础表 Attack/AnyEnemy 仍作为两项明确例外；实际实例通过 tinkerType 决定类型和目标，没有伪称模板相同。
4. **怪物与遭遇**：MysteriousKnight 继承 FlailKnight 的 A10 血量 108，旧值 101 错误；修复 HP 生成器继承解析。补 SlitheringStranglerNormal 的 Jaxfruit/Slimes、SnappingJaxfruitNormal 的 Jaxfruit，并修正 TunnelerNormal 的 Chomper 标签。Hive 普通池原生只有 10 项，不包含已注册但未启用的 TunnelerNormal；排除生产抽取，保留旧枚举编号。
5. **公开原生身份**：Decimillipede 精英前/中/后三段不能报成抽象基类；按稳定 segment1/2/3 槽导出真实 Front/Middle/Back，死亡后的 rank 压缩、复活和 clone 不改变身份。仍共享相同 C++ HP/AI 实现。
6. **公共词表**：改用实际 ModelDb 注册并过滤 Mock，排除 VakuuCardSelector、三个 Temporary 能力抽象类、DecimillipedeSegment、BattlewornDummyEventEncounter 共 6 个伪注册。原三个 Temporary 内部枚举保留，无实际施加路径，公共映射为 None；若未来错误导出会明确失败。词表摘要已变化，不能静默复用旧公共词表权重。

### 13.3 核对结果和保护措施

- 卡牌 **33,552 项检查、33,546 匹配、0 未解释差异、6 明确例外**。595 个实际身份全部对应，Grapple 保留槽与 DeprecatedCard 迁移兜底各 1 项例外，MadScience 模板 2 项，新 Stardust 无 owner 导出错误 2 项。最新导出与旧完整 metadata 的 12 个池及顺序、1,190 个可读 variant 全部相同；Stardust 两个 variant 的已有有效数值保留，未填零或改原始错误。
- 遗物 **299/299**，实际药水 **65/65**。身份、所列基础属性及 Shared/Ironclad 抽取池顺序无差异。三处历史药水枚举拼写仅显式映射，不改号。
- 事件 **57/57**、先古 **8/8**（各位合计 102 个遗物候选成员）、怪物 **107/107**、遭遇 **85/85**；world 审计 **596 项检查、0 差异**。包括各幕事件/遭遇池顺序、先古候选成员、A0/A10 血量、槽名、标签、房间类别和弱敌标记。历史占位、结局、宠物、未启用或测试类单独解释。
- `registry_identity_lock.json` 固定 Card / Relic / Potion / Monster / Encounter / Event 的整数、键与原生 ID：**597 / 300 / 66 / 110 / 92 / 66 个槽**，含 INVALID 与保留槽。全部旧号不动，新项只能追加；测试故意交换、删除、改别名、插入重复/倒序编号时必须失败。常规审计不会更新锁，初次创建参数拒绝覆盖已有文件。
- 总入口 `sim/tools/audit_native_registry.py` 同时核验 DLL 原始 SHA、卡牌生成表、实际已编译遗物/药水表、ruleset、完整词表及别名、数字锁。无本机反编译源码时，只有额外的遗物 UI counter traits 重建比较明确标未检查，DLL 注册/别名/卡牌静态数值检查仍继续；词表生成器在源码不全时拒绝写空表。

### 13.4 测试和边界

首轮 C++ 为 46/47，唯一失败来自 snapshot_validation 把 TunnelerNormal 旧枚举计入普通池数量，错误要求 11 个连续不同遭遇。测试现直接读取固定 DLL 的各幕真实池，同时按实际随机幕类型处理 Underdocks；保留首轮去重断言，并新增每一个生成遭遇都属于对应原生池的检查。没有修改固定原生输出或放宽生产规则。

最终 C++ **47/47**，训练 Python **40/40**、parity Python **85/85**。新增编译表对 DLL 的逐件遗物/药水检查、HP/标签回归、蜈蚣击倒/复活身份，以及注册和编号锁故障注入。保存的完整 31 动作/32 决策原生轨迹离线重放仍通过，原始字节不变。

ruleset 升为 `native-41cef1ea-port-v13`；快照仍 v13，观察/动作版本和尺寸沿用 v12；Card 仍 304 字节。**本轮不是全部效果验证**：遗物/事件/先古动态数值与效果、候选资格和概率、怪物 AI/阵容执行、整局对照仍未全面核实。`NATIVE_PARITY_COMPLETE` 保持 false。未训练、未提交、未推送；本次原生导出进程已退出。

## 14. 全部活动怪物数值核对与修正（2026-11-18，America/Los_Angeles，ruleset v14）

用户要求下一版本核对所有小怪、精英、Boss 的数值。本轮以真实 `ModelDb.Monsters` 的 **107 个活动模型**为范围，含召唤物和组件；按 Boss 相关 15、精英相关 17、普通/事件/其他召唤物 75 分工检查。15/17 不是 Boss/精英遭遇的数量。完整清单、修正表和边界见 [monster-number-audit.md](monster-number-audit.md)，机器结果见同名 JSON。

### 14.1 真实 DLL 数值证据

新增 `NativeMonsterNumbersExport.cs`，通过真实 DLL 的可变怪物实例读取具体类及父类数值属性、字段，并构造状态机读取攻击意图的伤害/次数。宿主先在未开局上下文采集 A0，再正常创建指定升阶铁甲对局，分别采集 A7、A8、A9、A10，覆盖 A8 血量和 A9 攻击/能力变化边界。没有注入 Creature、替换规则或执行原生怪物招式。C# 构建 0 warning / 0 error，四个独立导出进程均以 0 退出；Godot 退出清理警告不作为匹配证据。

固定原始字节位于 `sim/native-fixtures/native-monster-numbers-41cef1ea/`。DLL SHA 仍为 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`；manifest 和审计代码共同锁定四份输出 SHA，旧样例未修改：

| 文件 | SHA-256 |
| --- | --- |
| monster-numbers-a7.json | `604fe7d24d845a4c32aee72159832118c960824bff04ee23c4d41f5486c07212` |
| monster-numbers-a8.json | `35172103711fd69d077883954272473965de8d051fe37a541a031c8927aea320` |
| monster-numbers-a9.json | `17fc803d0c733fb65f1240856ae7f375e0ff023e91a9125e68354ed1e1d5f6f2` |
| monster-numbers-a10.json | `ee17dfb9a25bb2d911e1f1d788a44860122d8738fb1231dfafc0a5aaf81ea666` |

去重 A0 后共 **535 个模型上下文、1,635 个招式上下文、1,075 个攻击上下文**。Python 审计总计 4,876 项检查，其中血量/伤害/次数 **3,215 项数值比较、0 未解释差异**；C++ 测试独立读取同一原始输出，核对实际编译表的同样 3,215 项数值，避免只核对生成器输入。

动态例外保留原始事实：TheForgotten.DreadDamage 因无 Creature 无法读取，原始错误不改；Waterfall 新建模型的当前压力枪伤害是 0，另读其开战基础属性 20/23，与后续 +5 成长分别检查。四个历史招式槽保留但不计为原生活动招式：Axebot.SHARPEN、Cubex.SUBMERGE、HauntedShip.RAMMING_SPEED、TestSubject.POUNCE。

### 14.2 确认并修正的数值和结算差异

- **生成表**：Crusher/Rocket A9+ 力量增长 2→3，Louse Grow 5→7，Nibbit Hiss 2→3、A8+ Slice 格挡 5→6；Waterfall A0–7 Siphon 治疗 15→10，A8+ 仍 15，压力枪 A9 基础表补 23。`apply_native_monster_numbers.py` 从固定 DLL 数值应用已审核字段后重新生成 C++ 表，重复执行输出空变更。
- **继承漏读**：`native_monster_ai.py` 先解析继承的状态机及属性，修复 MysteriousKnight A9+ Flail 10×2、Ram 17；继承随机分支等权与最多连续两次，不能把次数上限 2 当权重。旧 MonsterId 不改号。
- **动态伤害与格挡**：Forgotten Dread 为 13（A9+ 15）加实时敏捷，不能固定成首次 Miasma 后的 15/17；意图与实际攻击共用计算。怪物 Move 格挡应用敏捷、Frail 和取整；Guardbot 的 Unpowered 15 格挡不受这些修正。
- **精英能力**：Entomancer Hive 缺失或达到 3 后只加 2 力量并返回，不继续执行加 Hive/1 力量。VitalSpark 增长同步已有 Tainted 牌，包括活跃/暂停出牌与当前选牌副本；Prism 死亡调用同一同步函数清零，防止 Defend 通过 Juggernaut 中途击杀 Prism 后，活跃牌把旧污染写回弃牌堆。
- **能力数值与时序**：Crab Rage 力量 +5→+6，格挡仍 99；Curl Up 在来源攻击牌整张结算完后给 14/18 格挡，不在多段中途生效，完全被格挡的攻击仍触发，无来源卡牌的伤害不触发；Rampart 跳过额外玩家回合。
- **Aeonglass**：WitheringPresence 属于 Boss，Amount 恒为 6，另以 CardsLeft 计数，每六张牌产生 Wither。公开能力的归属、显示值和动态变量同时修正，不能在玩家身上用增长的 Amount 冒充原生计数。

三个分组的逐怪源码记录保存在 `sim/tools/monster_audit_{boss,elite,normal}.json`；记录包含修正前发现，最终是否通过以当前执行结果为准。它们是源码审阅证据，不冒充 DLL 战斗轨迹。

### 14.3 回归、状态兼容和边界

新增四个 C++ 测试程序。Boss 的 75 招式 × A0–A10 共 **825 次动作执行**，检查实际扣血、次数、格挡、能力、塞牌、治疗，另测 TestSubject 复活/次数成长、Waterfall 压力枪成长、Aeonglass 十二张牌的两个周期及 clone。精英的 36 种攻击及能力按 A0–A10 执行，包含 Hive 分支、污染增长和中途击杀清除、蜈蚣 25 血复活、四只 Wriggler。普通组有 2,091 项源码静态检查及相关变化的执行回归；Curl Up 覆盖多段、全格挡、非卡伤害、内层出牌、clone、快照和 UID 改名不改变观察。第四个程序核对全部编译数值表与 DLL。

首轮回归暴露两项旧断言（快照 v13、Crab +5）和两项新测试构造错误（蜈蚣空的 DeadMove 后才轮到 Reattach、手造卡 UID 预留未结束），均按源码/实际状态修正测试，没有修改原生样例或放宽快照校验。最后独立复查发现的 Prism 活跃牌污染残留，新增真实出牌路径回归覆盖 A0–A10。

最终 **C++ 51/51、训练 Python 42/42、parity Python 89/89**。训练侧直接检查 Aeonglass 公开能力/CardsLeft、污染牌数字、clone 与隐藏重采样后观察不变；parity 新增数值审计及篡改样例/manifest/升阶伤害必须失败的检查。原生基础注册审计、旧整数编号锁和保存的 31 动作/32 决策完整公共接口离线回归均通过。

ruleset 为 `native-41cef1ea-port-v14`，快照升 **v14**：Louse 空闲辅助槽保存待触发 CurlUp 的来源 UID，Aeonglass 空闲辅助槽保存 CardsLeft；包含恢复校验，旧快照明确拒绝。没有增大 Card（仍 304 字节），没有改旧 ID 或观察维度/位置。内部来源 UID 只输出为待触发布尔值，不进入模型特征。`AGENTS.md`、两个 README 和审计报告已同步。

**验证边界**：此次直接 DLL 证据是初始数值 getter/意图构造；动态变化与时序是源码期望加 C++ 执行回归。尚未在真实 DLL 中逐场执行全部怪物战斗，也没有穷尽遗物/能力组合、所有钩子顺序、多人缩放或整局对拍；Thieving Hopper 偷牌挑选仍未核对。`NATIVE_PARITY_COMPLETE` 保持 false。未训练、未提交、未推送，导出进程已退出。

## 15. 分支建立后的交接更新（2026-11-18，America/Los_Angeles）

用户指定完整项目改在 `v111_SF2` 工作，`v111_simulator` 只发布其中的模拟器子集，保留旧 `v111_SF1`。此前代理创建分支的环境权限被拒绝，用户要求先停在准备阶段，随后改为提供命令、由用户自行操作。最终采用在原仓库内从完整项目提交提取子树的方式，不要求新增工作区。

本次只读核验：当前分支为 `v111_SF2`，提交 `aefad6a`；`v111_simulator` 为 `fbfdd8f`。两者分别与本地 `origin/` 跟踪引用相同，本次没有联网刷新。模拟器分支根目录仅 `.gitignore`、`LICENSE`、`sim/`；两分支的 `sim/` 子树均为 `0b6a9774eb7686ee60957603781ee1a76d60f6d8`，内容比较无差异。

补齐 `AGENTS.md` 中此前遗漏的分支约定，移除“新目录仍未跟踪、尚未提交”的过时说明，并纠正 GitHub 永久不可访问的旧描述。明确主工作区留在 SF2、模拟器是子集、两者需要显式同步；后续模拟器发布要追加既有分支历史，不重新创建或混入整个工作区。完整注册审计依赖训练目录的公共词表，独立模拟器只能执行其自包含审计与测试。

此次只改交接文档，检查文档差异和分支子树一致性，没有修改规则、运行状态或生成表，也未重新执行已通过的运行测试。此前准备的独立模拟器副本已完整编译并通过 51/51 C++ 测试及怪物数值审计。此次文档修改未提交、未推送。

## 16. 公共接口提速（2026-11-18 晚，America/Los_Angeles；只改 Python，ruleset 不变）

**起因**：随机打法实测走 `spire.public/1`（`from_simulator` + `encode`）每个决策约 3 毫秒，旧观察约 0.15 毫秒；训练机 8 线程要达到计划吞吐，每个决策需在 1 毫秒以内。性能分析显示一半以上时间花在 `parity/semantic.py` 的 `SimulatorCatalog.from_repo`：**每个决策都重新读 `cards_generated.inc` 并用正则重建卡牌表**。

**改动**（不改 C++、规则、观察布局或数值）：

- `SimulatorCatalog.from_repo` 按（仓库路径、两个源文件 mtime）缓存；文件重新生成后自动重解析。
- `public_obs.py`：`need` / `number` 对精确 dict / int / bool / float 走快速路径，其他类型仍走原检查；动态变量名下标改为预建字典（与 `list.index` 同取首次出现）。
- 卡牌校验结果缓存：`_card` 只依赖原始内容和来源，键为不含 `transportId` 的**类型精确**内容（bool、int、float 分开），返回浅拷贝；同时缓存排序用 JSON 文本，`knownTopPosition` 被改写的牌重新计算。
- 编码行缓存：卡牌的 768 维行只依赖其事实字典；顶层标量键带类型（True 与 1 编码不同），嵌套值已经过 `number()` 规整。实体行改为每 64 行一次分配。
- 两个缓存各上限 8,192 项（约 5 KB/项，满了清空）。缓存假定运行期间不修改 `_CATALOG`；目前没有代码或测试这样做。

**验证**：用改动前代码的副本和新代码，在同一批种子与动作序列上逐决策比较公开事实（`repr`）、候选动作及句柄、全部 11 个网络输入张量的哈希（kind、id、num、edges、global_row、player_row、cand_type/index/t1/t2/num）。A0/A10 交替、偏向出牌的随机打法：60 局 6,366 个决策、另 200 局 20,450 个决策（最远第 17 层），**全部逐字节一致，0 异常**。（首次比较脚本有几个字段名写错、漏比候选张量，修正后重跑。）

| 每个决策（本机单线程，200 局） | 改前 | 改后 |
| --- | ---: | ---: |
| 公开事实 `from_simulator` | 2,681 µs | 517 µs |
| 编码 `encode` | 423 µs | 248 µs |
| 合计 | 3,104 µs | 765 µs |

剩余大头：`_common` 中地图与排序、动作投影 `project_simulator`（约 130 µs）、C++ 导出（约 90 µs）、编码中地图约 70 个 768 维行。随机打法牌组小（平均每决策 22 张牌），真实对局牌更多，耗时会更高。另记：每个观察约 90 个实体 × 768 维 float32 ≈ 0.27 MB，开训前要考虑 PPO 样本存储量。

新增测试 `test_observation_caches_match_uncached_results_and_keep_types_exact`：冷/热缓存结果一致、返回副本不串改、bool 与 int 键分开、行缓存与直接计算一致、卡牌表缓存与重新解析一致。**训练 Python 43/43、parity Python 91 项 + 109 子项通过**（parity 此前记 89，本次运行实际为 91，未追查差异来源）。未重编 C++、未跑 C++ 测试（未改 C++）。

本次同时更正 `AGENTS.md` 2.1：两台 Mac 的仓库路径与 Python 不同，写明各自位置并加 parity 测试命令。未提交、未推送。

## 17. 两项硬要求：人用命令行、AI 可上原生客户端（2026-11-18 晚，America/Los_Angeles；ruleset 不变）

用户明确两点：模拟器要能由人在命令行里直接操作；用模拟器训练的 AI 要能直接到**带画面的原生客户端**里玩（后者现在不做，只核实能力、防止走偏）。此前文档都没有把这两点写成要求；旧分支历史里也没有人用的命令行（旧 `cli.py` 是训练入口）。

### 17.1 人用命令行（已完成）

新增 `train/spire_rl/play_cli.py`，运行方式为 `python -m spire_rl.play_cli --seed 种子 --ascension 10`：

- 画面只从 `PublicState` 渲染，包括头部（幕/层/HP/金币/Boss）、遗物、药槽、战斗（能量、格挡、能力，敌人血量/格挡/意图/能力，手牌带费用/伤害/格挡/关键字/附魔，各牌堆张数）、带连线的地图、奖励/货架、候选牌与选择要求，以及水晶球。抽牌堆只列内容不列顺序，已知顶牌按公开位置显示。
- 候选就是网络打分的那份（同一语义动作键），每个动作都有中文标签。选牌、跳过、确认、丢药等全部由人选，不自动代选。
- 命令：数字执行；`deck/draw/discard/exhaust/map/state`；`undo`（最多 50 步，调试用，会看到同样的随机结果）；`save/load` 快照；`help/quit`。遇到公共接口不支持的局面明确停止，提示 undo/load，不猜。
- 后端接口为 `observe() -> PublicState` 和 `act(index)`。现在只有模拟器后端；以后接原生宿主（或客户端 mod），同一个前端可以直接用。

验证：120 局 A0/A10 随机脚本输入（夹杂查看/撤销命令），**0 次接口停止**，出现过的 33 种动作类型全部有标签。新增 `tests/test_play_cli.py`：随机脚本整局、**重排隐藏抽牌顺序 7 次后画面逐字相同**（NoSL）、撤销与存读快照还原同一画面、越界编号不执行。**训练 Python 47/47、parity 91 项 + 109 子项**。命令行放在 `train/`（依赖公共契约），因此不在只含 `sim/` 的 `v111_simulator` 分支里。

### 17.2 AI 上原生客户端：能力核实（结论：路子对，不需要推倒）

依据（读源码确认，未在客户端里实际运行）：

1. **宿主加载的是完整原生场景树**：`NativeBootstrap` 实例化 `res://scenes/game.tscn` 的 `NGame`，只是无画面。
2. **执行动作走真实界面**：点击真实控件（`UiHelper.Click`、`NCardHolder` 的 Pressed 信号）；丢药等少数操作提交与界面相同的 GameAction。状态读取 `RunManager` / `CombatManager`，并等待 ActionExecutor 和动作队列空闲。带画面的客户端里是同一套节点和管理器。
3. **网络输入两端同源**：原生 `NativePublicObservation` 和模拟器各自导出公开事实，经同一个 `public_obs.encode`；原生 actionId 只做执行句柄。已有 31 步真实记录证明该轨迹两端张量一致。
4. **游戏自带 mod 加载器**：v0.111.0 源码有 `Core/Modding/ModManager`，支持 manifest、依赖、Harmony，可以把桥接代码作为 mod 装进客户端。

将来真正上客户端还要做（现在不做）：mod 打包（manifest + DLL）、在已运行的游戏里挂接而不是自己创建 `NGame`、客户端内的传输（可沿用同一 HTTP 协议）、“网络选动作 → 发给原生”的循环、客户端动画速度下的等待，以及把接口覆盖从开局 31 步扩展到整局（与恢复模拟器的对照是同一件事）。

**走偏风险**：观察清单 B“动作效果预览”原计划在模拟器的 `resample_hidden` 副本上试走算出，而用户已决定要做“只用公开信息的动作效果预览”。这种算法在客户端里没有对应的模拟器状态，上线时就缺了这项输入。已在清单中注明：实现前要改成只由 `PublicState` 加共享代码算，或者两端各算一份并对拍。A 类推算量同理。其余约束写入 `AGENTS.md` 第 3 节“可部署”。

未改 C++ 或规则，未提交、未推送。

## 18. 局内概率与生成核查，修正 6 处（2026-11-18 晚，America/Los_Angeles；ruleset v15）

用户要求：随机数不必逐位一致，但训练面对的内容、数值、机制、地图生成、事件分支和所有可计算概率必须与原生一致；对照由同学负责，这里做源码核查。用户同时指定模拟器默认按全解锁玩家处理。

### 18.1 核查范围与结论

逐项阅读原生源码再对照 C++，报告见 [content-audit.md](content-audit.md)。一致的部分如下：

- 问号房基础概率、累加和遗物钩子；卡牌奖励稀有度、保底、升级和 Boss 规则；金币范围与 A3。
- 药水稀有度；遭遇生成（弱怪数、标签不重复、精英 15、Boss、A10 第二 Boss）；事件袋组成。
- 遗物稀有度、遗物袋与宝箱；商店组成、打折和卡牌/药水价格；各幕地图点数量。
- A1–A5、A7、A10 局外效果；火堆回血。

确认 6 处不一致和 1 个配置问题：

1. **问号房不出商店**：原生在记录本格历史前，看上一格的房间里有没有商店。C++ 在掷骰前已把 `lastPointType` 改成当前格，规则从未生效；用的还是地图点类型，问号房抽中的商店不算。
2. **精英战药水概率**：原生用“当前概率 + 0.125”同一门槛判掉落并更新；C++ 更新时没算精英加成。
3. **白兽雕像**：原生强制掉落时不掷骰、不改概率；C++ 每场 −0.1。
4. **逃跑金币比例**（`EncounterModel.CalculateGoldProportion`）：普通战按“1 − 逃跑数 / 出现过的怪物种类数”缩放（四舍五入到偶数），为 0 时没有金币奖励。Gremlin Merc：Fat Gremlin 逃跑给一半，金币被偷且未夺回则 0。C++ 一律给全额。
5. **商店遗物基础价**：原生 175/225/275/200，C++ 每档多 25。补货遗物的价格还按掷出的稀有度计算，袋子回退时会错。
6. **A6 删牌价**：原生 100 + 50n，C++ 一直是 75 + 25n。
7. **配置**：默认 `init` 固定第一幕 Overgrowth 且 Underdocks 未解锁，训练永远见不到 Underdocks。

小差异：原生价格取整为五成双（无色稀有牌基础 172.5 → 172，C++ 原为 173），一并修正。卡牌奖励某稀有度抽空时的回退顺序有差异，铁甲碰不到，未改。

### 18.2 改动

- `run.cpp`：`lastPointType` 改为在房间类型确定后记录本格（房间是商店则记 SHOP），问号房掷骰时读到的是上一格。药水按原生逻辑重写。新增 `battle_gold_proportion` 并按比例缩放金币。遗物价格表、补货价格、删牌价改正；新增 `native_round`（`nearbyint`）代替 `lround`。
- `battle.h` / `monsters.cpp` / `battle_damage.cpp`：新增 `escapedMonsterCount`、`fatGremlinEscaped`、`mercGoldStolen`。逃跑招式计数，Doormaker 换阶段不算 `CreatureCmd.Escape`；Surprise 死亡且偷过金币时标记 Merc 金币被偷。快照校验覆盖这三个新字段。
- `run.h`：`NativeProgressContext::underdocksUnlocked` 默认 true；`init`（及调用它的 `init_seed`）第一幕改为 `-1`，即按原生 `act_selection` 选择。
- ruleset **`native-41cef1ea-port-v15`**，快照 **v15**（旧快照拒绝）。没有新增或改动任何 ID，没有改观察布局，`Card` 大小不变。

### 18.3 验证

新增 `sim/tests/native_run_odds_v15.cpp`，覆盖以下内容：

- **问号房**：直接调用和走地图两种方式都检查。商店之后、问号房抽中商店之后，下一个问号房不再出商店，且被排除的商店概率不增长。
- **药水**：精英战 600 次按原生门槛判定并更新，其中包含落在加成区间的情况；白兽雕像不改概率。
- **金币**：逃跑比例为 0 时没有金币；Merc 给一半（A10 为 4–8）或 0；一场真实的 Thieving Hopper 逃跑使计数为 1。
- **商店**：A0/6/10 的删牌价；300 家商店的遗物价格落在原生区间，并出现低于旧最低价的价格；无色牌价格区间。
- **开局**：400 个种子中第一幕 Underdocks 占 40–60%，显式指定第一幕仍然有效。

为配合新规则改了 5 处旧测试断言：

- 3 处快照版本号 14 → 15。
- `observation_contract` 的第一幕检查改为翻转当前抽到的幕。
- 训练测试中两条录制的搜索轨迹，固定为录制时的上下文（Overgrowth、Underdocks 未解锁），否则种子 UNIFIED6 现在会抽到 Underdocks。

这些改动都没有放宽检查。

结果：**C++ 52/52、训练 Python 47/47、parity Python 91 项 + 109 子项**。基础注册审计和怪物数值审计通过，与存档报告相比只有 ruleset 名称变化，已更新 `docs/registry-audit.json` 和 `docs/monster-number-audit.json`。

**边界**：这些是源码对照与源码期望回归，不是 DLL 执行对拍。事件（含 23 个 C++ 自标“近似实现”）、遗物、卡牌、药水效果尚未系统核对。未提交、未推送。

## 19. 事件与先古核查，补上 5 件无效果的先古遗物（2026-11-18 晚，America/Los_Angeles；ruleset v16）

用户要求核对事件。方法同第 18 节：逐个对照原生 `Models/Events/*.cs` 与 C++ `events.cpp` 等，详细结果见 [content-audit.md](content-audit.md) 第 8 节。

### 19.1 结论

- **出现条件**：57 个普通事件的 `IsAllowed` 全部一致。“永恒”判断漏了 Forbidden Grimoire（铁甲拿不到），也漏了 Tezcatara 余烬附魔带来的永恒，已补。
- **23 个原“近似实现”事件**：15 个普通事件逐个核对，选项、数值、随机范围、选牌约束和后续效果都与原生一致；Neow 在 v11 已对拍；7 位先古另核对选项池。标签是早期遗留，已改为 IMPLEMENTED（只有 UNSUPPORTED 会影响事件袋，改标签不影响行为）。
- **先古选项池**：Darv、Vakuu、Tanx、Nonupeipe 一致。Tezcatara 分组写错：Seal of Gold 应在第 3 组；只有牌组有基础打击时才提供 Nutritious Soup。Pael：有事件宠物时不提供 Legion；Claw 的条件应是至少 3 张 Goopy 可附魔的牌。Orobas：Archaic Tooth 只认 Bash，不认 Break。
- **5 件先古遗物标为已实现，但拿到后没有任何效果**：Nutritious Soup、Pael's Claw、Tri-Boomerang、War Hammer、Meat Cleaver。发现方法：先发现 Soup 拿到后牌组没有变化，再统计每件遗物在 C++ 里除注册表和选项列表以外是否出现过。同样方法查出的 Divine Destiny、Ring of the Drake 是其他职业的升级起始遗物；Fake Merchant's Rug、Wongo 徽章在原生里本来就没有效果。这种排查只能发现“完全没写”的遗物，发现不了“写了但数值或时机错”的遗物。

### 19.2 改动

- **新附魔**（`EnchantmentId` 追加 GOOPY、INSTINCT、TEZCATARAS_EMBER）：
  - Tezcatara 余烬：基础费用永久为 0，升级、降级都保持；带永恒；受力量加成的攻击 +3。
  - Goopy：只能附在防御牌上；加消耗；格挡加“层数 − 1”；每打出一次层数 +1，并记录到 `BattleContext::goopyUids/goopyGrowth`，战斗结束时写回牌组（只有原始牌组里的牌有 DeckVersion）。
  - Instinct：只能附在攻击牌上；受力量加成的攻击伤害 ×2。
- **遗物效果**：
  - Nutritious Soup、Pael's Claw：获得时附魔。
  - Tri-Boomerang：新增选牌界面类型 23，由玩家选 3 张，可选不足 3 张时全部自动附魔，与原生选牌器一致。
  - War Hammer：精英战胜利后用 Niche 流打乱可升级的牌，升级前 4 张。
  - Meat Cleaver：`RunActionType::REST_COOK` 追加；可删除的牌至少 2 张时可用；删除选牌界面设 `service = 4`，可取消、需确认；确认后最大生命 +5，记入火堆已用选项第 7 位。“全部用完”的掩码从 127 改为 255。
- **选项池**：Tezcatara、Pael、Orobas 按原生修正。
- **公共接口**：`public_obs.ENCHANTMENTS` 追加三项。卡牌行原有的附魔 one-hot 在 56–74，紧接着的 76–78 已被占用，所以新附魔放在空闲的 238–240，原有特征位置不变。`parity/action_contract.py` 增加 REST_COOK→COOK 和选牌界面类型 23。旧的 legacy 观察附魔 one-hot 长度固定，不包含新附魔（新网络不使用 legacy 观察）。
- ruleset **`native-41cef1ea-port-v16`**、快照 **v16**。编号锁没有变动，`Card` 大小不变。

### 19.3 验证

新增 `sim/tests/native_ancient_relics_v16.cpp`：

- **选项池**：各种子下 Seal of Gold 只出现在第 3 组，约 1/4；没有基础打击时不提供 Soup；牌组有 Byrdonis Egg 时不提供 Legion；防御牌都已附魔时不提供 Claw；只有 Break 时不提供 Archaic Tooth。
- **Soup**：5 张基础打击 0 费、永恒、不可删除，升级后仍为 0 费，伤害 6→9。
- **Claw**：真实打出一张 Goopy 防御：格挡 5、被消耗，牌组层数 1→2。
- **Tri-Boomerang**：选牌界面要求选 3 张，攻击伤害 ×2，非攻击牌不可附魔。
- **War Hammer**：精英战升级 4 张，普通战不升级。
- **Cook**：取消后选项仍在，确认后牌组 −2、最大生命和当前生命 +5，之后其他火堆选项也不可用；全程做了快照往返。

训练测试新增一项：两种新附魔在公共状态里可见（0 费、永恒、消耗），one-hot 落在 238/240，原有区间没有被占用。

旧测试只改了一处：火堆用完后的掩码断言从 127 改为 255，另外 3 处是快照版本号 15→16。

结果：**C++ 53/53、训练 Python 48/48、parity Python 91 项 + 109 子项**；基础注册审计和怪物数值审计通过，与存档报告相比只有 ruleset 名称变化。

**边界**：仍然是源码对照，不是 DLL 执行对拍。其余 41 个事件只核对了出现条件；遗物、卡牌、药水效果的数值和时机还没有逐件核对。未提交、未推送。

## 20. 卡牌身份与编码核对（2026-11-18 晚，America/Los_Angeles；ruleset 不变）

用户要求：确保训练时网络在模拟器里选的牌，和以后在原生客户端里测试时选的是同一张，两边的编码一致。

此前 v13 注册审计核对的是 C++ 生成表与 DLL 的静态属性，没有覆盖“模拟器公开导出 → 编码器 → 网络输入”这一段。本次补上：

- 新增只读绑定 `public_card_template(card_id, upgraded)`，导出一张新牌组卡，走与真实牌组卡相同的 `public_card_view`；只是接口，不改规则。
- 新增 `parity/card_encoding_audit.py`：对 DLL 注册表每张卡、每个升级档，比较模拟器导出和按原生宿主 `DescribePublicCard` 格式构造的卡。两者经同一个 `_card` 和行编码器，比较全部公开字段与 768 维编码行。另外检查：
  - 模拟器编号到原生模型 ID 的一一对应；
  - 编号锁与动作键映射表一致；
  - C++ 打印伤害/格挡等于 DLL 数值。

结果：**1,148 个变体 0 差异**。33 个改名别名都正确；GRAPPLE 是保留空槽；DEPRECATED_CARD 只是原生兜底；例外为 Stardust（模板无持有者，导出报错）和 Mad Science（未配置模板）。报告存为 `docs/card-encoding-audit.json`。

`parity/tests/test_card_encoding_audit.py` 锁定 0 差异，并验证篡改 Bash 的关键词会被报出，防止空通过。

**parity 93 项 + 109 子项、训练 48/48** 通过。只重编了 Python 扩展，C++ 规则与测试程序未改。

**边界**：只核对新牌。战斗中的临时修改（费用修正、临时关键词、附魔、加成）也走同一编码器，但未逐卡穷举；遗物效果按用户要求暂不核对。未提交、未推送。

## 21. 怪物机制与回合触发核对（2026-11-18 晚，America/Los_Angeles；ruleset v17）

用户要求按源码核对所有小怪和 Boss 的机制、数值和每个回合的触发时机；真实执行对照不在本次范围。数值 v14 已用 DLL 导出核对过，本次重点是机制与时机。详细结果见 [content-audit.md](content-audit.md) 第 10 节。

### 21.1 方法

1. 列出原生所有怪物覆写的钩子，逐个阅读方法体。大部分只涉及台词、动画、音效，影响规则的只有 Queen 那一处。
2. 列出怪物施加的全部 68 种能力，抽出每种能力的触发方法（回合开始/结束、受伤、死亡、出牌、费用、伤害修正等），与 C++ 的实现位置和时机对照。
3. 重跑 `native_monster_ai.py --compare/--effects`，没有出现第 8.4 节之外的新偏差。
4. 核对 C++ “每只怪行动后立即结算回合末能力”与原生“敌方回合结束统一结算”的差异：没有跨怪物影响，被眩晕的怪同样结算。

### 21.2 修正（均按原生）

- **Shrinker Beetle**：Shrink −1 是永久的。`OP_POWER_PLAYER` 不再把负数改成正数，回合末只递减正数层；甲虫死亡时移除。
- **Constrict**：Slithering Strangler 死亡时移除。
- **Queen**：Torch Head Amalgam 死亡时，如果 Queen 待出招（尚未行动）是 Burn Bright For Me（状态 3），改为 Enrage（状态 7）；本回合已经出过招的不改。
- **Lagavulin Matriarch**：最后一个沉睡回合先移除镀甲，再结算镀甲格挡。
- **Tangled / Ringing / Smog**：新增 `BattleContext::turn_affliction`，按原生“一张牌只有一个附着”的规则推导 Ringing、Entangled、Smog。
  - 出牌限制只作用于带这些附着的牌；Entangled 攻击牌费用 + Tangled 层数（X 费不受影响）。
  - Tangled 和 Smog 在玩家回合末清除。
  - 公开卡牌导出补上 `AFFLICTION.RINGING/ENTANGLED/SMOG`（公共词表原本就有）。

ruleset **`native-41cef1ea-port-v17`**；数据布局没有变化，快照仍为 v16。

### 21.3 验证

新增 `sim/tests/native_monster_mechanics_v17.cpp`，覆盖：

- 真实回合中甲虫施加 −1 层，两回合后仍是 −1，甲虫死后变为 0；
- Strangler 死后 Constrict 清除；
- Queen 改招，以及本回合已出招时不改；
- Matriarch 三个沉睡回合的格挡依次为 12、11、0；
- Tangled 让攻击 +1 费、技能不变、已带其他附着的牌不受影响、回合末移除；
- Ringing 下打出一张牌后，只有已带其他附着的牌仍可出；
- Smog 锁定未附着的技能牌，并在回合末清除。

结果：**C++ 54/54、训练 Python 48/48、parity 93 项 + 109 子项**；注册表、怪物数值、卡牌编码三项审计通过，相比存档只有 ruleset 名称变化。

**边界**：源码对照，不是 DLL 战斗对拍。Thieving Hopper 的偷牌规则仍未核对。Lagavulin Matriarch 被打醒后的意图标签与原生不同（规则等价）。Python 端没有施加能力的绑定，新附着的公开导出由 C++ 端 `turn_affliction` 的断言覆盖。未提交、未推送。

### 21.4 Thieving Hopper 偷牌规则（补充）

按用户要求核对 `ThievingHopper._stealPriorities`、`ThieveryMove` 与 `SwipePower`，与 C++ `steal_hopper_card` 逐条一致：

- 候选是抽牌堆和弃牌堆中原本在牌组里的牌；
- 四档优先级为：罕见 → 普通/稀有/事件 → 基础/任务 → 先古或 Imbued，前三档都排除 Imbued；
- 四档都空时从全部候选里挑；用 CombatCardGeneration 流均匀抽取；先偷后攻击；被眩晕不偷；
- 偷走的牌同时离开牌组，打死跳蚤可通过特殊奖励拿回，逃跑则丢失。

所以**没有修改规则**，ruleset 保持 v17。`native_monster_mechanics_v17.cpp` 新增优先级测试，覆盖：

- 有罕见牌时偷罕见牌；
- 附 Imbued 的罕见牌让位给普通牌；
- 只剩基础牌时偷基础牌；
- 只剩 Imbued 牌、先古牌和诅咒时，只在前两者中挑；
- 只有诅咒时偷诅咒。

此前 DEVLOG 第 9.2、10.5、14.3 节中“偷牌规则未核对”的记录至此结清。**C++ 54/54** 通过。未提交、未推送。

## 22. 事件选项效果核对（2026-11-18 晚，America/Los_Angeles；ruleset v18）

**做了什么**：v16 只核对了全部事件的出现条件和 23 个原“近似”事件。本轮把其余 41 个普通事件逐个与原生 `Models/Events/*.cs`（以及 Crystal Sphere 小游戏、Fake Merchant 货架、各战斗事件遭遇）并排对照，内容包括初始化、选项是否可用、选项效果、数值与随机范围、所用随机流、选牌约束、奖励组成、多页流程以及战后恢复。

**结果**：39 个一致；2 处差异都与 Maw Bank 有关，已按原生修正：

- Waterlogged Scriptorium 付金币是 `PlayerCmd.LoseGold`，不是商店购买。原生 Maw Bank 不失效，C++ 却让它失效了。已删除这行。
- Fake Merchant 的货架就是商店遗物格，购买走 `MerchantEntry.OnTryPurchaseWrapper` → `Hook.AfterItemPurchased`，不限房间，花费大于 0 时 Maw Bank 失效。C++ 原来不会失效，已补上。

原生 Maw Bank 只在 `AfterItemPurchased` 时失效；C++ 商店的买牌、遗物、药水和删牌本来就正确。

**顺带发现（未修，留给遗物核对）**：Lord's Parasol 在原生里会白拿商店的全部角色牌、无色牌、遗物、药水，并强制做一次不可取消的免费删牌；C++ 只白拿遗物。

**验证**：
- 新增 `sim/tests/native_event_options_v18.cpp`，覆盖两档付费的 Waterlogged、Fake Merchant 购买、离开不买。
- 结果：**C++ 55/55、训练 Python 48/48、parity 93 项 + 109 子项**。
- 注册表、怪物数值、卡牌编码三项审计通过，相比存档只有 ruleset 名称变化。
- ruleset 升为 `native-41cef1ea-port-v18`。观察、动作和快照版本不变。

**边界**：这是源码对照，不是 DLL 执行对拍。未提交、未推送。

## 23. 遗物效果核对（2026-11-18 晚至 11-19，America/Los_Angeles；ruleset v19）

**做了什么**：把铁甲能拿到的 265 件遗物（共享池、铁甲池、事件池、先古池）逐件与原生 `Models/Relics/*.cs` 对照，按触发时机核对数值、条件、随机流和顺序。

**修正**：

| 类型 | 遗物与修正 |
| --- | --- |
| 数值 | Amethyst Aubergine（改为奖励页一份 15 金币，原来直接给 10）、Permafrost（7）、Planisphere（5）、Signet Ring（888）、Bread（第一回合 −2） |
| 时机 | Orichalcum（VeryEarly 判断）、Parrying Shield（AfterSideTurnEnd）、Brilliant Scarf（Late 修正、不影响 X 费）、Spiked Gauntlets（0 费能力也 +1） |
| 漏掉的效果 | Booming Conch 精英能量、Fiddle 禁止回合内抽牌、Belt Buckle 丢药水、Fairy 算使用药水、Philosopher's Stone 召唤物力量 |
| 按 v0.111 重写 | Diamond Diadem、Toasty Mittens（玩家选手牌消耗）、Fur Coat（地图标记 8 点、公开为地图任务）、Whispering Earring（自动预出牌阶段 + VakuuCardSelector）、Lord's Parasol（白拿全部商品 + 强制免费删牌） |

**状态与接口**：
- 快照 v17。
- 公共编码地图行第 17 位表示 Fur Coat 标记，是新增位，原有位置不变。
- 出牌合法性统一为 `hand_card_playable_now`，修掉了合法动作里漏算 Tangled 的重复费用计算。

**验证**：
- C++ 56/56，新增 `native_relic_effects_v18.cpp`；`relic_contract`、`rules_regression`、`observation_contract` 中按旧行为写的断言改为原生预期。
- 训练 Python 49/49，新增 Fur Coat 公共标记测试。
- parity 93 项 + 109 子项。
- 注册表、怪物数值、卡牌编码三项审计通过。
- 塞入新遗物的随机整局冒烟测试被用户中止，未跑。

**未修缺口**：见 AGENTS.md 第 0 节 v19 条目和 content-audit 第 12 节。

**用户决定**：模拟器工作到此暂停，等同学原生对照结果再继续。这是源码对照，不是 DLL 对拍。未提交、未推送。

## 24. 文档同步与阳伞缺口补记（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：只改文档，不改代码。
- `content-audit.md` 第 0 节速览表和第 11 节第 2 项仍写着遗物“待核对 / 下一步 / 已知待修 Lord's Parasol”，与 v19 已完成矛盾，改为与第 12 节一致。
- 补记一个遗物缺口（用户确认）：Lord's Parasol 白拿过程中弹出选牌（如 Astrolabe）时，原生逐件 `await` 购买、选完再拿下一件，药水最后拿；C++ 选牌界面打开后循环继续，后续遗物排队、药水当场拿。Astrolabe 之后有 Potion Belt / Sozu 或持有 The Courier 时结果不同。已写入 content-audit 第 12 节和 AGENTS.md v19 未修缺口。按暂停安排未修。

**依据**：`artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models/Relics/LordsParasol.cs` 与 `sim/src/run.cpp` 的 `lords_parasol_purchase_everything`、`add_relic`（选牌界面打开时排队）。源码对照，未实测。

## 25. 训练框架设定（2026-11-19，America/Los_Angeles；只记录，不写代码）

用户定：初始奖励用 Zero-Search 数值；练习战 30%；防卡死照 AlphaDefect；标量价值头；网络宽 768、12+12 层。本机用现有 `UnifiedNet`（`spire.public/1` 布局）实测 217.4M 参数，384×(6+6) 为 31.7M、512×(8+8) 为 69.1M。按实体数估算 217M 在 5090 上每秒只有几百个决策，未实测，训练机测速后再定。奖励、观察、价值可见性都要可变。**所有内容核对完之后再写训练框架。** 全部数值见 plan 第 6.2 节。

补充（同日晚）：用户可用 A100 约 3 天有效训练时间；估算 217M 在 A100 上约 300–500 决策/秒、3 天约 0.8–1.3 亿决策（未实测）。用户拍板仍用 217M。练习战改为 40%，抽样类型权重 Boss 6、精英 3、普通 1。见 plan 第 6.2 节。

## 26. 跳过卡牌奖励后可重开：原生行为，防循环放在 AI 驱动层（2026-11-19，America/Los_Angeles；ruleset 不变）

**核对**：
- 原生真实记录 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/` 第 26–29 步：奖励页 → 打开选牌 → 跳过 → 回到奖励页 → 再打开同一组牌 → 领 Thunderclap。用同一编码器比较：第 26 与 28 步（奖励页）、第 27 与 29 步（选牌页）的公开状态**完全相同**，跳过后“打开选牌”仍是合法动作。
- 模拟器同样可以无限“打开 → 跳过”，前后公开状态与网络输入张量逐位相同。
- 结论：这是原生游戏本身的行为，模拟器与原生一致，**不改模拟器**。

**问题**：网络看到的局面前后一样，取最大评估时，第一次选了打开就会永远循环；只在训练环境里防，上线原生客户端时照样会卡住。

**定下的做法（用户同意）**：防循环属于 AI 驱动程序（读 `PublicState` → 网络 → 选动作的那层 Python，模拟器和原生共用同一份），不属于游戏或模拟器：
1. 驱动程序自己记公开历史（例如这个卡牌奖励已跳过几次），作为观察值给网络；
2. 保险规则在驱动程序里从候选中去掉会造成循环的动作（例如重开超过 2 次后不再提供“打开选牌”）。原生游戏不改，按钮仍在，只是 AI 不点。
战斗防卡死规则同样放在这一层。其他界面上的往返（选中/取消、预览/取消、进出商店等）实现时按同一原则统一处理。

## 27. 观察第 1 批：E 牌组摘要、C 抽牌概率、A5 路线摘要（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：新增 `train/spire_rl/public_derived.py`，只读 `PublicState.facts`，模拟器和原生共用这一份，不改 C++。`public_obs.encode` 写入：
- **E 牌组摘要** → 全局行第 32–63 列：张数；五类牌张数与占比；不能打、X 费、平均费用、0 费与 2 费以上占比；升级比例；印刷伤害/格挡密度；打击/防御张数；群攻、消耗、虚无、固有、保留、附魔、苦难、稀有张数。印刷值，不含战斗加成（加成是 A1）。
- **C 抽牌概率** → 战斗玩家行第 32–95 列：抽牌/弃牌/消耗堆张数；已知顶牌数；抽牌堆和弃牌堆各类张数；接下来 1、2、5 张里抽到攻击/技能/能力/状态/诅咒/有伤害/有格挡/0 费牌的概率和期望张数；距下次洗牌张数。抽牌堆按多重集加已公开的顶牌位置算（超出窗口的已知牌不会进窗口），不够时从弃牌堆洗入的部分按超几何算；抽牌途中新生成或移动的牌不算。
- **A5 路线摘要** → 每个地图点第 18–41 列：到 Boss、最近火堆、商店、宝箱的步数（含能否到达）；下一个火堆前（没有则到 Boss）精英与战斗数的最少/最多；到 Boss 的精英、普通战最少/最多；问号、火堆、商店最多；路线条数。只看地图结构，按结构缓存。
- `public_obs.FEATURE_VERSION = 2`；`net.save` 记录、`net.load` 不符即拒绝。

**为什么**：用户已定的观察清单 A–E 中不依赖加成计算和引擎内部状态的三项，先做。

**验证**：新增 `train/tests/test_public_derived.py`（10 项）：抽牌概率与逐一枚举所有隐藏顺序的精确结果相等（含已知顶牌、洗牌）；小地图路线手算核对；起始牌组数值；重排隐藏抽牌顺序后全局行与玩家行逐位不变；随机整局数值有限且有界；检查点特征版本不符被拒。**训练 Python 59/59、parity 93 项 + 109 子项**。编码耗时每决策约 0.40 毫秒（路线缓存后新特征约 0.06–0.09 毫秒）。

**边界**：原生端无需新导出，三项都从已有公开事实算；未做真实原生帧上的数值比对（用户定暂不做对拍）。

## 28. 观察第 2 批：D 本幕遭遇（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：
- **模拟器导出**（`sim/bindings/public_view.inc`，只加接口）：`run.actNormalEncounters`、`run.actEliteEncounters`，即本幕已从地图房间进入的普通/精英遭遇，按顺序（遭遇袋已用的前缀）。遭遇袋本身（未来顺序，隐藏）不导出。
- **原生宿主导出**（`parity/host-src/NativePublicObservation.cs`）：同名字段，取本局历史 `MapPointHistory[当前幕]` 每个地图点的第一个房间中类型为 Monster / Elite 的遭遇 ID（事件开出的战斗第一个房间是 Event，不计入）。**这台 Mac 没有游戏备份，C# 未编译、未实跑**，要在有游戏的机器上编译并录一段新的原生记录核对。
- **公共目录**（`sim/tools/gen_public_catalog.py` 重新生成 `public_catalog.json`）：新增 `acts`（每幕弱怪/普通/精英/Boss 池，取自原生注册表；弱怪场数取自各幕源码 `NumberOfWeakEncounters`：Overgrowth、Underdocks 3，Hive、Glory 2）和 `encounterTags`。原有内容逐项不变。
- **共享推算**（`public_derived.act_encounters`）：按原生 `ActModel.GenerateRooms` 规则，从已遇到的历史推下一场的概率——前若干场从弱怪袋、之后从普通袋抽，袋空才整池补满；每次在“不等于上一场、且不与上一场共享标签”的袋内遭遇中均匀抽，没有则在袋内任抽。精英同理（一个袋）。只用公开历史和静态规则。
- **编码**：全局行第 64–79 列（本幕普通/精英场数、弱怪还剩几场、是否弱怪阶段、当前袋剩余数、下一场候选数、历史缺失标记）；每个本幕遇到过或下一场可能遇到的遭遇一个实体（kind 6，与 Boss 共用，第 0 列区分 Boss），含遇到次数、是否刚打过、弱/普通/精英、下一场普通/精英概率、是否仍在当前袋中。Boss 行第 9 列标第二个 Boss。`FEATURE_VERSION = 3`。
- **旧原生录制**：`from_native` 缺这两个字段时默认报错（不静默补零）；只有 `compare_decision(..., legacy_capture=True)` 回放此前保存的录制时，两边都去掉这两项并在报告里列为未覆盖。`test_native_public_fixture` 用此模式。

**验证**：新增 4 项测试：弱怪阶段排除已抽、首个普通战排除与上一场同标签的遭遇；精英袋满一轮后补满；旧录制模式与模拟器导出；40 局随机整局里**每一场实际进入的遭遇，在进入前的预测概率都大于 0**，且每次预测概率和为 1（模拟器真实遭遇袋 vs 共享规则）。随机打法基本只到第一幕，Hive、Glory 的池子靠注册表数据，未经整局覆盖。**训练 Python 63/63、parity 93 项 + 109 子项**。编码每决策约 0.48 毫秒，局外实体平均多约 9 个。

**边界**：第一局教学顺序（`numberOfRuns == 0` 时 Overgrowth 固定排序）未建模；默认全解锁进度不会触发。遭遇列表用完后循环的情况未建模（返回空预测）。

## 29. 观察 A1：加成后的牌面伤害和格挡（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：
- **C++ 新增 `sim/include/sts2/card_preview.h`、`sim/src/card_preview.cpp`**（只读，不改规则）：照原生 `DamageVar / BlockVar / CalculatedDamageVar / CalculatedBlockVar.UpdateCardPreview`、`Hook.ModifyDamage / ModifyDamageInternal / ModifyBlock` 和每个相关的 power / relic / 附魔钩子移植。规则要点：
  - 只有手牌和出牌区的牌跑全局修正（`CardModel.UpdateDynamicVarPreview`）；其他牌堆只算附魔。
  - 附魔先于其他修正（Corrupted 打击 + 2 力量 = 6×1.5+2 = 11，不是 12）；加法（力量、Vigor、Strike Dummy、Miniature Cannon、Mystic Lighter、One For All 预览分支）→ 乘法（Weak、Shrink、Double Damage、Gigantification、Pen Nib、目标的 Vulnerable/Paper Phrog/Cruelty、Soar、Flutter、Covered、Slow）→ 封顶（Intangible、Hard To Kill）→ 至少 0 → 截断取整。
  - 格挡：附魔（Goopy、Nimble）→ 敏捷、Fasten → Unmovable、Shadowmeld、Frail、No Block、Vambrace、Pael's Legion。
  - 按局面计算的牌：铁甲可得的 Ashen Strike、Body Slam、Bully、Gang Up、Gold Axe、Mind Blast、Perfected Strike、Rend、Demonic Shield、Expect a Fight、Mimic、Stack 已按原生公式移植；其他职业的计算牌（Prismatic Gem 才可能出现）返回“不支持”，观察里标为未知，不给数。
  - 原生是十进制 decimal，这里用精确分数计算，最后截断一次，不用浮点。
- `rend_debuff_count` 从文件内私有改为共享（逻辑不变），预览和出牌用同一份。
- **导出**：模拟器 `previewDamage`（不选目标时）、`previewBlock`、`previewDamageVs`（按公开敌人顺序逐个目标）；原生宿主同名字段（调用原生 `UpdateDynamicVarPreview` 读 `PreviewValue`，最后恢复为不选目标的显示），**C# 未编译**。
- **Python**：只给牌本身有对应变量的手牌/出牌区牌；牌行第 544–563 列（有无伤害、伤害、有无格挡、格挡、不支持标记、对 6 个敌人位置的伤害）。显示值不进入排序和动作身份。原生缺字段默认报错，旧录制用 `legacy_capture` 两边都去掉。`FEATURE_VERSION = 4`。

**验证**：
- `sim/tests/card_preview_native.cpp`：53 项，每个期望值按原生源码手算并写在旁边（各修正单独和组合、附魔顺序、十进制取整、Pen Nib 出牌区、封顶、One For All、12 张计算牌、格挡各修正）。另对其中 29 项在战斗副本里实际打出比对引擎。**C++ 57/57**。
- `train/tests/test_card_preview.py`：字段只出现在应有的牌上、编码位置、不支持标记、原生缺字段报错、显示值不改变牌的身份；60 局随机对局中 **4,821 次伤害、3,860 次格挡** 预览与引擎实际出牌结果逐一相等（其中 998 次伤害带加成）。**训练 Python 69/69、parity 93 项 + 109 子项**。
- 公开状态约 0.65 毫秒、编码约 0.49 毫秒每决策。

**顺带发现的引擎差异（未修，模拟器暂停中）**：
1. **Perfected Strike 打出时少算自己**：原生 OnPlay 时这张牌在出牌区（`CardModel.cs` 注释“While this method is being run, this card will be in the Play pile”），`AllCards` 计入；C++ 出牌时不计入，少 2/3 点（升级前/后）。预览按原生。
2. **伤害用 double 计算**：少数乘数组合下比原生少 1。例：(6+9)×3（Gigantification）×1.4（Slow 4 张）原生 63，引擎 62。在 0–399 的伤害和三种以内乘数组合里有 610 种这样的情况，多与 Slow、Shrink 有关。格挡用 float 但只乘 2、0.75，没发现误差。
3. **Unmovable 计数口径**：原生数本回合的 BlockGainedEntry 条数，C++ 数获得格挡的出牌次数，一张牌两次获得格挡时不同（代码注释已写明，预览沿用 C++ 口径）。

## 30. 修正 A1 发现的三处引擎差异（2026-11-19，America/Los_Angeles；ruleset v20）

用户要求修正第 29 节列出的三处差异。

**改动**：
1. **Perfected Strike 计入自己**（`cards_ironclad.cpp`）：原生 OnPlay 期间牌在出牌区，`AllCards` 包含它；C++ 出牌时把它放在牌堆之外，现在不在任何牌堆里时补算自己。预览（`card_preview.cpp`）同样处理出牌区中的这张牌。
2. **伤害改为精确十进制**：新增 `sim/include/sts2/exact.h`（精确分数）。`calc_player_damage`、`calc_monster_damage`、`thrash_damage_growth` 全部改用它，最后截断一次；原来分别是 double / float。其他职业助手函数返回的 double 乘数用分母 ≤ 10000 的最佳有理数逼近还原成准确分数——第一版按 4 位小数取整时，Debilitate 的 2.0/1.5 = 4/3 被截成 1.3333，Necrobinder 原生 DLL 样例（Debilitate + 易伤，原生 22）掉到 21，测试当场报错，改成逼近后恢复。预览共用同一个工具。
3. **Unmovable 按原生记录计数**：`blockCardPlaysThisTurn / blockPlayIndex` 改为 `blockGainEntriesThisTurn / blockGainEntriesThisPlay`：每次出牌获得格挡且大于 0 记一条（原生 `CreatureCmd.GainBlock` 只在 > 0 时 `History.BlockGained`），条件为“本回合其他出牌的记录数 < Amount”。快照 v18（字段含义变化，旧快照拒绝），快照校验覆盖新字段；旧观察 `observe.cpp`、`combat_obs.cpp` 读取新计数。

**验证**：
- `card_preview_native` 增至 58 项（新增 Unmovable：同一次出牌两次获得格挡都翻倍，下一次出牌不翻倍，获得 0 不记录），**引擎实际出牌与预览 0 处差异**（修正前 2 处）。
- **C++ 57/57**；含原生 DLL 样例的测试全部通过，其中 Necrobinder 198 个样例 3,357 项。更新了 3 个测试里写死的快照版本号。
- **训练 Python 69/69**（随机对局预览与实际出牌对照仍全部一致）、**parity 93 项 + 109 子项**；注册表、怪物数值、卡牌编码三项审计通过，报告中 ruleset 更新为 v20。
- 怪物伤害原为单精度 float：在 1–199 的伤害与三种以内乘数组合里没找到算错的例子，改为精确计算只为一致。

**边界**：源码对照加原生样例回归，不是新的 DLL 执行对拍。未提交。

## 31. 用户指定的 A1 同步测试三条（2026-11-19，America/Los_Angeles；ruleset 不变）

新增 `sim/tests/card_preview_user_cases.cpp`（70 项）。每条都用真实出牌得到能力，再比较三样：预览值、实际打出结果、按 v0.111.0 源码手算的原生值（源码推导，不是 DLL 实跑，这台 Mac 没有游戏）。

1. **残酷 CRUELTY 25 / 残酷+ 50**，敌人易伤 4 层，无遗物：易伤倍率 1.5 + Amount/100。欺凌 = 4 + (2 / 3) × 易伤 4 = 12 / 16。
   - 残酷：打击 10、打击+ 15、欺凌 21、欺凌+ 28；残酷+：12、18、24、32；两张都打（75）：13、20、27、36。三者全部一致。
2. **无惧疼痛 FEEL_NO_PAIN 3 / 4 + 重振精神 SECOND_WIND 5 / 7**，手里 4 张非攻击牌（防御、耸肩、燃烧、伤口）和 1 张打击：原生逐张“消耗（无惧疼痛 +3/+4 无加成格挡）→ 获得 5/7 格挡”。预览显示每张 5 / 7；总格挡 32、40、36、44；消耗 4 张、打击留在手里。全部一致。
3. **Regent：剑圣 SWORD_SAGE + 招架 PARRY 10 / 14 + 淬炼刀刃 REFINE_BLADE 锻造 8 / 12** 生成并强化大剑 SOVEREIGN_BLADE，打出一次：剑圣给大剑 1 次重放；每次伤害 10 + 锻造 = 18 / 22，每次获得格挡 = 招架层数。预览伤害 18 / 22、预览格挡 10 / 14（两张招架都打为 24）；实际打出（共 2 次）伤害 36 / 44、格挡 20 / 28 / 48。全部一致。

**为此补的一处预览**：大剑的 CalculatedBlock（`GetOwnerParryAmount`：在战斗牌堆中时等于玩家 ParryPower）原来按“其他职业计算牌”标为不支持，现在实现。

**验证**：C++ 58/58、训练 Python 69/69、parity 93 项 + 109 子项。

补充（同日）：用户要求第 1 条的易伤层数从 0 到 5 各跑一次。测试改为对 0–5 层、三种残酷配置逐一检查（144 项，预览、实际打出、原生公式三者全部一致）。0 层时易伤不生效，打击 6 / 9、欺凌 4 / 4；有易伤时伤害 = ⌊印刷伤害 × (150 + 残酷) / 100⌋，欺凌印刷伤害随层数 4 + 2n / 4 + 3n。C++ 58/58。用户确认通过后数值这一条结束。

## 32. 观察 A3 / A4 / B：能打多少、结束回合掉多少血、每个动作的效果预览（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**（新增 `train/spire_rl/public_tactics.py`，只读公开状态，两端共用，建立在 A1 显示值和公开意图上）：
- **A3** 每个敌人：用当前手牌和能量最多能打它多少（合法出牌各一次的 0/1 背包，不考虑抽牌和出牌顺序带来的加成，按用户定义的简化版）、能否打死（≥ 血 + 格挡）。随机目标按期望。
- **A4** 现在结束回合会掉多少血，按原生顺序：回合结束前（Orichalcum / Fake Orichalcum 先查格挡是否为 0；Plating、Cloak Clasp、Ripple Basin 加格挡；Regret 此时数手牌）→ 虚无牌消耗（Feel No Pain 加格挡）→ 回合结束牌按手牌顺序（Burn、Decay、Infection、Toxic、Wither 可格挡；Bad Luck 13、Beckon 6、Regret 不可格挡）→ Constrict、Demise、Disintegration → 敌人回合逐下结算意图。伤害：Intangible 每下至多 1、格挡、**Osty 先吃攻击伤害**、Tungsten Rod / Beating Remnant（按遗物栏顺序）、Buffer。不含下回合开始时的效果（Inferno 自伤、中毒）。隐藏意图标未知。
- **B** 每个出牌动作：对目标打掉多少（含格挡）、是否打死、所有敌人总伤害、获得格挡（牌面显示值 + 攻击牌的 Rage）、出牌后剩余能量（含 Sown 返还）、出牌后再结束回合会掉多少血、是否致死；“结束回合”动作给当前 A4。打死敌人且幸存敌人带有可能对同伴死亡作出反应的能力（如 Corpse Slug 的 Ravenous）时标未知。
- **打击次数表**：`gen_public_catalog.py` 从原生出牌代码解析 `WithHitCount(...)` 写入 `public_catalog.json` 的 `cardHits`（固定次数 / Repeat 变量 / X 费 / 出牌时才决定）；Spite、Dismantle 按原生条件单独处理；出牌时才决定的标未知。
- **Osty 公开**：模拟器与原生宿主（C#，未编译）导出 `player.ostyHp / ostyMaxHp`。核对中发现：Kaleidoscope 给的死灵牌召唤出 Osty 后，它替玩家挡攻击伤害，而公开状态原来完全没有它——这是观察缺口，已补。旧原生录制按 legacy 处理。
- **编码**：A4 → 玩家行 96–101，Osty → 104–106；A3 → 敌人行 600–603；B → 候选行新增第 512–543 列（`CAND_NUM` 512→544，语义描述上限仍 495 字节）。`FEATURE_VERSION = 6`。

**验证**（`train/tests/test_public_tactics.py`）：用模拟器实际结束回合 / 实际出牌作对照，只排除定义之外的局面（敌人意图含增益/减益/召唤等会改变其他敌人伤害的招式、下回合开始掉血的能力）：
- A4：**2,003 个局面**预测与实际结束回合掉血完全一致（1,852 个掉血 > 0）。
- B：**6,620 次出牌**的剩余能量、获得格挡、对所有敌人的总伤害一致；其中 **3,458 次**再结束回合，掉血与预测一致。
  > **更正（2026-11-20，见第 35 节）**：这组对照只覆盖 20 张白名单普通牌，且跳过有特殊能力的敌人；其余牌（放血、重振精神、自伤牌、重放等）实际有系统性偏差却标“已知”。“出牌效果预览与实际一致”只对白名单成立，第 35 节已改为全量对照。
- A3：1,564 个敌人上，背包结果与枚举所有出牌组合的最优解相等。
- 规则单测：Orichalcum 判定时机、Burn 可格挡、Regret 计数、Feel No Pain + 虚无、Intangible、Buffer、Tungsten Rod、Beating Remnant、Constrict/Demise、Osty、隐藏意图。
- 过程中修正：Sown 返还能量、Rage 格挡、Osty 导出与吸收、反应性击杀标未知、测试排除 Inferno。
- **C++ 58/58、训练 Python 73/73、parity 93 项 + 109 子项**。公开状态约 0.49 毫秒、编码约 0.45 毫秒每决策。

**边界**：A3 不考虑出牌顺序（先上易伤再打）和抽牌；B 只预测伤害、格挡、能量和结束回合掉血，不预测其他效果（给敌人上虚弱等）；A4 不含敌人回合中途的增益/减益对后续攻击的影响（例如一个敌人先给另一个加力量）。

## 33. 观察 A2：怪物招式 ID 与后续两步预测（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：
- `gen_monsters.py` 额外生成 `MON_STATE_NAMES`（与 `MON_STATES` 平行的招式名），重新生成的 `monsters_generated.inc` 只有新增，原有内容逐字节不变。
- `monsters.cpp`：把随机分支的权重计算（重复、连续次数上限、冷却）抽成 `random_branch_weights`，真实出招和预测共用（逻辑不变，C++ 全套与怪物数值审计确认）；新增只读 `predict_monster_moves`：第 0 步为当前显示的招式（概率 1），之后按“执行该招 → 记录招式历史与 AI 计数器 → 后续状态 → 随机分支按权重 / 条件分支按当前战场展开”推出第 1、2 步的概率分布，并给出每个候选招式的攻击伤害与段数。不读任何随机数。
- 公开状态：每个敌人 `moves`（三步，每步为 招式名、局部编号、概率、意图类型、伤害、段数）和 `stunned`；原生缺失默认报错，旧录制 legacy。编码：敌人行 610–657（三步各 16 格概率）、658–661（后两步攻击概率与期望伤害）、664 眩晕、665 缺失。`FEATURE_VERSION = 7`。

**验证**（`train/tests/test_move_prediction.py`）：
- 第 0 步与显示的意图一致；每步概率和为 1。
- 40 局随机对局的战斗局面，每个局面把隐藏随机（含怪物 AI 流）重采样 24 次后**实际结束回合**（前 8 次再结束一回合看第 2 步）：**13,131 次**实际出现的招式全部在预测的候选内；随机分支频率与预测概率的合并卡方 χ²/df = 1.27（df 66），离线大样本（13 个随机选招局面 × 200 次）实际频率与预测非常接近（如 50%/50% 实际 99:101、91:109）。
- 只改隐藏随机后预测不变（NoSL）；原有“重采样后编码逐位相同”测试也覆盖它。
- **C++ 58/58、训练 Python 76/76、parity 93 项 + 109 子项**，三项审计通过。

**边界**：条件分支按当前战场判断（敌人回合中血量等变化后可能不同）；被眩晕/复活中的敌人第 0 步以外仅供参考（标记 `stunned`）。**原生端未实现**：需要在宿主里读原生 MoveStateMachine 并按同样规则推算（C# 版本），部署前必须补。

## 34. 观察 A6：选牌用途；A–E 收尾与原生端欠账（2026-11-19，America/Los_Angeles；ruleset 不变）

**做了什么**：选牌决策新增公开的 `purpose`（用途）和 `service`（商店 / 休息点 / 奖励等来源）。战斗内 17 种（升级、消耗、放回牌堆顶、抽到手、变化、复制、弃牌……），局外 23 种（删牌、变化、变化并升级、升级、各附魔、Brain Leech、Scroll Boxes、Sea Glass、Hefty Tablet、事件选牌……）。词表 `public_obs.PURPOSES` 只能追加；C++ 导出表和 Python 词表由测试锁定一致，`ChoiceOp` 每个值都有对应用途。编码在上下文行 360–423（用途）、424–429（来源），359 为旧录制缺失标记。`FEATURE_VERSION = 8`。战斗中触发选牌的那张牌本来就以“出牌区”牌导出，不另加。

**未做**：事件选项提示（用户定，另有人做）；遗物“本场是否已触发”等额外状态（现有状态 / 计数 / 蜡封 / 熔化已导出，收益小）。

**验证**：训练 Python 77/77、parity 93 项 + 109 子项。随机对局中各用途正确进入编码。

**观察 A–E 至此完成**（除上面两项）。每决策：公开状态约 0.5 毫秒、编码约 0.5 毫秒。

**部署到原生客户端前必须补的原生端工作**（模拟器侧都已完成并测试）：
1. 编译并实跑原生宿主中已写好的 C# 导出：本幕遭遇（D）、牌面显示值（A1）、Osty 血量。这台 Mac 没有游戏备份，均未编译。
2. 原生端招式预测（A2）：在宿主中读原生 MoveStateMachine，按同样规则推算（尚未写）。
3. 原生选牌界面到 `PURPOSES` / `service` 的映射（A6，尚未写）。
4. 补完后录一段新的原生记录，用完整对照（非 legacy）核对上述字段。

## 35. B 效果预览改为“我方精确、敌方不追”；A4 补漏；选牌用途表错位与牌面小数伤害两处修复（2026-11-20，America/Los_Angeles；ruleset 不变，`FEATURE_VERSION = 9`）

**起因**：用户的检查器指出，B（每个出牌的效果预览）没有算条件效果、重放、回能、遗物触发和出牌后的手牌/血量变化。例：重振精神预测卡面 5，实际是 5 × 消耗张数；放血预测出牌后仍是 3 能量，实际回能。核实：60 局随机对局 10,933 次出牌里约 446 次（约 4%）数字错误但标“已知”；第 32 节“6,620 次一致”只覆盖 20 张白名单牌（已在第 32 节更正）。

**口径**（用户 2026-11-20 同意：敌人机制多，不追）：
- **我方这一侧精确，算不准就标未知**：按原生 `CardModel.OnPlayWrapper` 在 `PublicState` 上结算一次出牌，不在模拟器副本上试走（可部署）。
- **敌人一侧不追**：伤害定义为“牌面伤害 × 段数 + 我方遗物/能力的伤害”，**不含敌人自身的防御与反应**（滑溜、Skittish、坚硬外壳、荆棘、蜷缩……），由网络从敌人能力编码里学。会反击或改变敌人本回合行动的敌方能力被打到时，“出牌后结束回合掉血”标未知。
- 讨论结论：改“说法”本身不改变网络输入；真正改变输入的是我方这一侧的数字。预期收益小但成本低，且训练开始前改观察没有代价。

**做了什么**（`train/spire_rl/public_tactics.py`）：
- 出牌次数：附魔重放 + 一二拳（攻击）/ Duplication / Burst（技能）/ Throwing Axe（本场第一张）；Echo Form、Tag Team、Signal Boost 标未知。重放时会变的（自加能力、算式牌、给敌人上能力的牌、Vigor、Pen Nib、Vambrace、Pael's Legion、Shuriken/Kunai/Rainbow Ring/Red Skull、Rupture+自伤）标未知。
- 每次出牌：出牌前（Intimidating Helmet）→ 效果 → 出牌后（Rage、Ornamental Fan、Kusarigama、Letter Opener、Nunchaku、Tuning Fork、Daughter of the Wind、Lost Wisp、Iron Club、Game Piece、Music Box、Permafrost→未知），全部按原生计数。
- 卡牌本身：自伤（放血、血墙、突破、御血术、Offering、Brand：不可格挡，经无实体/钨棒/Beating Remnant/Buffer；Inferno 自伤反伤；Demon Tongue/Centennial Puzzle）、回能（放血、Offering、Forgotten Ritual、Production、Luminesce、Fuel、Brightest Flame、Restlessness 条件）、重振精神（每张非攻击牌先消耗再格挡）、Entrench（当前格挡）、Evil Eye（本回合消耗过牌则两次）、Pact's End（消耗堆 ≥ 3 才有伤害，A3 同样生效）、Not Yet 回血、Brightest Flame 降上限、Stoke（消耗全部手牌）、True Grit/Cinder 随机消耗一张、True Grit+/Brand/Burning Pact 只剩一张时原生自动选中。
- 消耗触发：Feel No Pain、Dark Embrace、Joss Paper、Burning Sticks、Charon's Ashes、Forgotten Soul、Drum of Battle（被消耗回能）。
- 击杀触发：Gremlin Horn（回能 + 抽牌）；打死 Constrict 施加者 → 结束回合未知；预测打死的敌人有自身防御 → 结束回合未知。
- 出牌后结束回合：带入出牌后的格挡、已掉血、Buffer、手牌（重振精神/Stoke 确定移除）、这张牌给自己加的 Plating / Feel No Pain / 无实体 / 火焰屏障 / 荆棘 / The Gambit / Stampede；抽牌/加牌/随机消耗时，若回合结束受手牌影响（Cloak Clasp、手里有 Regret、Feel No Pain、抽牌堆/弃牌堆里有回合末伤害牌或虚无牌）标未知；Weak/减力量/眩晕等改变敌人本回合的牌标未知（Whistle 眩晕目标直接去掉其意图）。
- 只对复核过 OnPlay 的卡池（铁甲、无色、事件、诅咒、状态、衍生，227 张）给数；其他职业的牌、从抽牌堆自动打牌（浩劫、Cascade、Catastrophe、Beat Down、Uproar）、Fisticuffs、Omnislice、Thrash、Mad Science、友方目标牌标未知；出牌带非 Hexed 的负面附加，或场上有对出牌有反应的敌方能力（Strangle、Haunt、Gravity、Galvanic、Enrage、Monologue、Tender、Withering Presence、Smoggy、Chains of Binding、Vital Spark）标未知。
- 新字段 `self_hp_loss`（出牌过程中自己掉的血，负数为回血），编码在候选行 522；`lethal_after` 改为“出牌自伤 + 出牌后结束回合掉血 ≥ 当前血量”。`FEATURE_VERSION 8 → 9`。

**A4（结束回合掉血）顺带补漏**（同一函数，B 也用）：同一种能力多条记录改为求和（原来只取第一条）；回合结束消耗虚无牌触发 Charon's Ashes（确定，可致死）、Forgotten Soul（可能致死时未知）；Juggernaut 在回合结束获得格挡时可能打死或惊动敌人 → 未知；火焰屏障/荆棘反伤可能打死攻击者或触发其反应 → 未知；The Gambit、Stampede、最后一回合的 The Bomb、消耗堆里的 Howl from Beyond → 未知。

**另修两处已有的观察错误**（不改规则，ruleset 不变）：
1. **A6 选牌用途表错位**（第 34 节引入）：`public_view.inc` 用按位置排列的 18 项字符串表，而 `ChoiceOp` 有 25 个值（同一行写了多个枚举值，原测试按行计数漏掉）。第 14 项以后全部错名，`GAMBLING_CHIP`（铁甲可得遗物）和 `KNOWLEDGE_CURSE`（Knowledge Demon）直接越界抛错，训练中遇到会中断采样。改为逐个 `case` 的显式映射；`PURPOSES` 末尾追加 7 个新名称（只追加）；新增绑定 `choice_purposes()`，测试按枚举逐个核对。
2. **A1 牌面伤害遇到小数基础伤害抛错**：原生 Thrash 把被消耗攻击牌经加成后的伤害（decimal，可为小数，如虚弱 ×0.75）加进自己的 `Damage.BaseValue`，A1 原来把非整数当错误。改为按精确小数参与计算。

**测试接口**：绑定新增 `RunContext.add_card(id, upgraded)`（与 `add_relic` 同类，仅用于测试布置，不改规则），用于把特殊牌塞进随机对局。

**验证**（`train/tests/test_public_tactics.py`，白名单测试改为全量）：所有牌、所有局面里 B 标“已知”的出牌，剩余能量、获得格挡、出牌自伤、对敌伤害（敌人无反应类能力时）必须与模拟器实际完全一致；不含未知时，出牌后结束回合掉血也必须一致。开发期四组大样本对照（随机 60 局；塞入 24 种特殊牌 30 局；再加两组遗物各 25 局）共比对 B 标“已知”的 42,472 次出牌、8,991 次出牌后结束回合：前三组全部一致；第四组（Cloak Clasp、Tungsten Rod、Juggernaut 等遗物组合）有约 30 处不一致（打击 19、Dark Embrace 5、Juggernaut 6）。逐个查过的打击、Dark Embrace 案例都是下面第 4 条模拟器问题（回合开始流程未走完），Juggernaut 的 6 处未逐个查。修复后不再出现选牌用途越界和小数伤害报错；Fake Merchant 报错在 100 局里出现 5 次（含开发期）。正式测试：随机 15 局 + 塞特殊牌 6 局 + 塞特殊牌与遗物 4 局，外加放血/御血术/重振精神/Offering 定点检查。

**对照中查出、未修的模拟器问题**（按约定模拟器规则暂停修改，待统一处理；均为源码对照所见）：
1. **Intimidating Helmet**：原生每次重放都走 `BeforeCardPlayed`，每次都加 4 格挡；模拟器整张牌只触发一次（`battle.cpp` 出牌扣费处）。重放时模拟器少给格挡。
2. **Pen Nib 跨战斗**：原生若第 10 次攻击直接结束战斗，`AfterCardPlayed` 不执行，`AttackToDouble` 留着旧牌引用，下一场任何牌都不再翻倍，直到计数再次归零；模拟器把 aux=100 带进下一场，使下一场第一次攻击翻倍。
3. **同一时机多个遗物的顺序**（已登记）：Beating Remnant 与 Tungsten Rod 同为 `ModifyHpLostAfterOsty`，原生按遗物栏顺序，模拟器固定先钨棒。
4. ~~**回合开始流程未走完就交出操作权**（较强怀疑，待复现）~~ **已否定（第 37 节）**：实为预览漏算附魔（Swift 抽牌、Corrupted 自伤）：在一些局面里，玩家已可出牌，模拟器的 `pendingDrawRemainder`（被选择打断后剩余的抽牌）或回合开始效果（如 Inferno 自伤）要等玩家下一个动作才执行。原生在交出操作权前处理完。影响：该局面手牌少于原生，且差异对公开观察不可见。
5. **Fake Merchant 结束页导出报错**（训练前必须解决）：原生 Fake Merchant 是商店界面，`GenerateInitialOptions` 为空，没有文字页；模拟器离开商店后进入事件结束页（127），`event_page_key` 找不到原生说明而抛错，采样会中断（第 2 幕起常见）。需到有游戏的机器上看原生这时导出什么（可能根本没有这一步），再决定改模拟器流程还是导出键。

**测试**：C++ 58/58、训练 Python 79/79（新增全量 B 对照与定点检查）、parity 93 项 + 109 子项；注册表、怪物数值、卡牌编码审计未受影响（未改规则与注册表）。

## 36. ruleset v21：Fake Merchant 离开直接回地图（2026-11-20，America/Los_Angeles）

**问题**：第 35 节发现，离开 Fake Merchant 后公开观察抛错（`No native finished event description for FAKE_MERCHANT`），训练采样会中断。

**原生（反编译源码确认）**：`FakeMerchant.LayoutType = Custom`，`GenerateInitialOptions` 为空；事件开始时 `SetInitialEventState` 把说明设为 `FAKE_MERCHANT.pages.INITIAL.description`，之后不再改，也从不调用 `SetEventFinished`。界面是 `NFakeMerchant`：商店 + 继续按钮，继续按钮 `HideScreen` 直接 `NMapScreen.Instance.Open()`；地图从进入起就允许出发（`SetTravelEnabled(true)`）。原生 AutoSlay 离开时也只点这一个按钮。

**模拟器原来**：选“离开商店”后进入事件结束页（127），再要一次“继续”才回地图——多出一个原生不存在的决策，且结束页没有原生说明文字，导出报错。

**改动**：`events.cpp` 中 Fake Merchant 选项 6（离开）改为 `leave_event` 直接回地图。ruleset `v20 → v21`（`PORT_SOURCE.json`、`ENGINE_RULESET_ID`、README、parity/README、AGENTS）；快照格式不变。买遗物、扔 Foul Potion 开战的流程不变。语义层原本就把 Fake Merchant 第 0 页当商店（`leave_shop`），不需要改。`event_page_key` 里结束页仍会对 Fake Merchant 抛错，作为不该再到达的保护。

**边界**：原生打开地图后玩家理论上还能关掉地图回到商店（再买或扔药水）；模拟器离开即不可返回。这只少了一个“离开又回来”的绕路，不少真实选择。

**验证**：C++ `native_step3_events` 改为断言离开后直接到地图；C++ 58/58；注册表、卡牌编码、怪物数值审计通过并以 v21 重新生成；之前报错的 4 个对局（8103、8114、8215、8218）复跑全部走完、不再报错，其中 B 对照 2,578 次出牌全部一致；训练 Python 79/79、parity 93 项 + 109 子项。

## 37. 附魔补进 B；“回合开始流程”怀疑否定；训练框架第一版（2026-11-20，America/Los_Angeles；ruleset 不变）

**否定第 35 节第 4 条**：新增只读诊断绑定 `RunContext.debug_turn_flow`（回合流程阶段、`pendingDrawRemainder`、自动打牌队列；只用于诊断，不进观察），在 85 局（含塞牌塞遗物）共约 1.75 万个可出牌决策点扫描：回合开始流程未走完 0 次。逐个复查第 35 节剩余偏差：打出 Dark Embrace 多抽 2 张是这张牌带 **Swift 附魔**（打出时抽牌）；打击自伤 1 点并触发 Inferno 是 **Corrupted 附魔**（每次打出自伤 2）。模拟器没有问题，是 B 漏了附魔。

**B 补附魔**（按原生 `EnchantmentModel.OnPlay`，在牌本身效果之后、每次重放都执行）：Corrupted 每次 2 点不可格挡自伤；Swift 首次打出抽牌（手牌变化）；Sown 回能（原有）；Adroit 的格挡加成未逐项核对 → 未知；Inky 给敌人上虚弱 → 出牌后结束回合未知；Momentum / Goopy / Vigorous 重放时数值会变 → 未知；Sharp、Tezcatara's Ember 等只改牌面数值（A1 已含），Glam / Spiral 为重放次数（已计入）。另补：打出 Juggernaut 这张牌后，新得的 Juggernaut 在回合结束获得格挡时可能打死敌人 → 带入结束回合计算。

**全量对照（最终，脚本 `train/scripts/audit_action_preview.py`）**：四组（随机 60 局；塞 24 种特殊牌 30 局；再加两组遗物各 25 局）B 标“已知”的 **43,206 次出牌、8,965 次出牌后结束回合，全部与模拟器一致**（排除项只有已查明的 Intimidating Helmet 重放差异与 Beating Remnant/Tungsten Rod 顺序差异）。

**训练框架第一版**（用户要求今晚搭好、明天上 A100）：
- `spire_rl/driver.py`（AI 驱动层，训练与原生客户端共用，只读 `PublicState` 与自身公开历史，不改规则）：同一作用域内同一网络输入第三次出现时，去掉已从它走过的候选（作用域：战斗内按回合，战斗外按层与地图/房间）；战斗中同一回合内重复出现的决策只允许结束回合；敌人血量+格挡合计 20 个玩家回合未创新低判负；一局 5,000 决策判负。只有一个可选候选时由驱动层直接执行，不进网络、不成样本，奖励并入下一个样本。
- `spire_rl/rewards.py`：每项奖励一个函数和权重（层 +0.01、精英 +0.02、Boss +0.1、通关 +1、死亡 −0.1、血量势函数 0.1，终局势能 0）；判负（停滞、超限、异常）按死亡计。`--reward '{"floor": 0.02}'` 可改权重。
- `spire_rl/rollout.py`：多进程（spawn）每进程若干局，同步推进；网络输入约 98% 为零，传输与存储都用稀疏格式（每样本约十几 KB，6.5 万样本约 1 GB）。单局异常记入日志并换新局，不中断训练。
- `spire_rl/ppo.py`：同步整局 PPO，GAE（γ 0.999、λ 0.95）、截断 0.2、KL 早停、熵 0.01→0.001 线性下降、学习率 3e-5 带预热、梯度裁剪 1.0、每次更新 65,536 样本 × 2 遍、小批 4,096 按 `--micro` 梯度累积、CUDA 上 BF16 自动混合精度；EMA 按 2 小时时间常数换算衰减；`latest.pt`（含优化器）与 `ema.pt` 原子覆盖保存，只留两份；`--hours` 到时、Ctrl-C/SIGTERM 在当前更新后保存退出，同一 `--run` 再运行即续训；网络配置或观察版本不符拒绝续训；`--bench` 测采样决策/秒、更新速度与显存。
- 网络加标量价值头 `value`（原三个 Boss 概率保留为辅助输出，暂不训练）。
- **尚未做**：练习战池；价值函数看隐藏信息（`--value-hidden` 预留，目前拒绝）；EMA 取最大评估脚本。217M 在 GPU 上的速度未实测。

**验证**：`train/tests/test_training.py`（6 项）：稀疏打包还原逐位相同；战斗内重复决策只剩结束回合；房间内第三次出现时去掉已走候选；停滞与超限判负；奖励各项数值；小网络 CPU 上整局 PPO 两次更新并续训。本机小网络（0.9M）2 进程 × 4 局实测约 350–440 决策/秒（CPU 推理）。C++ 58/58、训练 Python 85/85、parity 93 项 + 109 子项。

