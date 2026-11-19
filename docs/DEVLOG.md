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

## 12. 2026-11-18～19 公共模型接口与真实选择补全（ruleset v12）

用户要求补全上一轮发现的接口和遗物缺口，并同步 AGENTS；11 月 19 日要求集中核实、加快完成。本批仍保留 C++ 执行器，没有训练、提交或推送，也没有修改原始 DLL 或旧原生样例。

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

## 13. 2026-11-19 基础注册审计与固定编号（ruleset v13）

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

## 14. 全部活动怪物数值核对与修正（2026-11-19，ruleset v14）

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

## 2026-11-19 · sh02v17 在 v14 上的 A9 最终 Boss 评估

移除独立的 v30 模拟器和私有扩展，使用本仓库 v14 的宏观实体、公开向量和可执行动作。按字段映射到权重的 80 维状态 token、729 维动作特征和原词表，保留动作与执行描述符的一一对应。缺失字段和新增内容的处理见 [适配说明](../train/a9/README.md)。

专用评估模式在直线地图上跳过最终 Boss 之外的全部战斗，包括事件战。跳过的战斗保留 HP、金币、药水、遗物和各自的 RNG 状态，走 v14 战后奖励流程。范围限定在显式调用该入口的局和当前调用，普通游戏、快照布局和规则身份保持 v14。打开卡牌奖励并选择跳过会结算当前奖励槽，避免模型在奖励列表与同一张选牌界面之间往返。

同一 sh02v17 权重和 500 个固定种子，CPU 冻结推理，未训练。允许重新打开的 v14 基线胜 41 局，433 局在奖励相关页面触发循环。原始逐局结果和修改后的复查记录在 `train/a9/`。

相同 500 个种子重评：跳过后消耗当前卡牌奖励槽，最终 282 胜（56.4%），496 局进入最终 Boss。146 局正常战败，70 局循环截断，2 局触发 v14 的 Finished card identity capacity 上限。奖励及选牌页面的循环从 433 局降至 0 局。模拟器异常单独记录；胜率分母包含全部 500 局。

回归：v14 C++ 51 项、训练包 Python 45 项通过；普通模式原生首战和奖励离线记录回放 2 项测试、35 项子测试通过。

### Fetch 计数和选牌适配后的复评

同一固定面板（7540000–7540499）仅打最终 Boss，冻结 sh02v17，8 个 CPU worker。Fetch 只登记该牌自身的不同实例；先用原适配器回放 7540124 和 7540316，两局均由容量异常变为正常胜利。加入必选单张的确认、多选去除已选牌和无效空确认后，500 局全部正常终局，351 胜、149 负（70.2%），499 局进入最终 Boss。与跳过奖励槽的基线相比净增 69 胜（13.8 个百分点）；此前 70 局循环现在 45 胜、25 负，2 局容量异常现在均胜。

[逐种子记录](../train/a9/a9-final-boss-fetch-selection-500.jsonl)。C++ 回归 51 项、Python 回归 48 项全部通过。

### sh02v17 的 S3 参数搜索（2026-11-19）

新增 [独立搜索目录](../train/s3_search/README.md)，在 SF2 v14 上只执行 A9 最终 Boss 战，支持 Codex 直接编辑父权重以及脚本提案。8 个初始候选在 12 个开发种子上校准，拟合胜率筛出 7 个种子，后续两轮各评估 2 个新候选，合计 124 个唯一候选与种子组合。直接提交权重模式另以 6 个候选验证了 24 局和续跑。固定 500 种子留作独立评估。

### sh02v17 单候选三区组搜索与四模型测试（2026-11-19）

基线和五个直接子候选各完成 100 个开发种子。正式搜索每轮从四人池随机抽父代，Codex 自选权重修改方向，每轮入场一人。50 次主比较与 7 次召回共采纳 2,893 条不同的开发对局（含首批 600），每条新观测更新后验。另有 164 条预取结果留在缓存。先前固定面板的三轮不计入正式结果。

最后保留 31、42，池外后验前二为 37、51；冻结后按原固定 500 种子仅打 A9 最终 Boss，依次得到 348、346、358、352 胜，全部正常终局。历史同种子基线 351 胜。37 号有 48 个种子由负转胜、41 个由胜转负。复现说明见 [S3 搜索说明](../train/s3_search/README.md)，本机结果在 train/s3_search/runs/live50/summary.json。

### latest_106 当步权重的 50 轮单候选搜索（2026-11-19）

使用新开发种子 8542000–8542099，基线和五个子权重的首批胜局依次为 70、72、72、73、72、72。50 轮采用四人父代池，累计 19 次召回，连同首批 600 局共采纳 2,798 条开发观测。冻结最终保留者 48、50 和池外后验前二 16、19 后，按原固定 500 种子只打 A9 最终 Boss，分别得到 368、370、369、376 胜。原始当步权重为 367 胜。19 号有 34 个种子由负转胜、25 个由胜转负。四份权重均有 1 局宏观动作异常，计入分母。本机汇总在 train/s3_search/runs/model106-live50/summary.json。
