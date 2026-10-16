# STS2 局内战斗 AlphaZero 实施规格

版本：0.3  
日期：2026-10-09  
状态：M0–M5 的原 Shrinker 限定范围已完成；M6 第一批新增 Fuzzy Wurm Crawler 与单只 Nibbit，机制／编码／粒子测试及 smoke 通过，三遭遇正式实验已完成并通过产物／统计核验，双 seed 学习增益验收未通过（seed 43 搜索保血退化导致未晋级）。实验使用 2 seeds、256 场晋级验证、各 150 场最终测试。

本次修订决策：先扩充卡牌种类、可配置牌组和训练场景，再开展持续训练；不再把独立诊断／调参实验作为下一阶段前置任务。Reward v3 将战斗超时单独置于死亡与胜利之间。下文新增要求是待实现目标，当前代码及历史结果仍使用 Reward v2，不能视为已经升级。

## 1. 目标与完成定义

在本项目内实现单场战斗的 AlphaZero 式学习系统：策略／价值网络指导 MCTS，搜索生成策略标签，战斗结果生成价值标签，反复训练、评估和更新模型。

这里的 self-play 指智能体自主与规则驱动的怪物战斗。怪物不训练成对手模型，不使用双人零和游戏的逐层价值取负。

首个正式版本必须同时满足：

1. 从随机初始化的小网络开始，完成采样 → 训练 → 评估 → 晋级或保留旧模型的闭环。
2. 在限定的铁甲战士战斗场景中稳定执行，包含结束回合、出牌、选目标。
3. 正式搜索和策略输入只使用玩家可见信息及可推断的历史；禁止读取真实未来牌序或 RNG 状态。
4. 新模型在独立场景中表现出可测量的学习增益；分别报告不搜索的网络表现与固定搜索预算下的表现。
5. 支持断点恢复、模型版本追踪、可复现评估和多进程采样。

工程闭环验收与学习效果验收是两个独立状态。程序能运行、训练 loss 下降或几场胜利，均不能声明“自进化成功”。若未达到学习指标，保留完整实验结果，不自动放宽标准。

## 2. 范围

### 2.1 首版范围

| 项目 | 决策 |
|---|---|
| 角色 | Ironclad |
| 难度 | 固定 ascension 0 |
| 决策粒度 | 一次出牌、选目标或结束回合；怪物回合由规则推进 |
| 构筑 | 当前仅未升级的 5 Strike + 4 Defend + 1 Bash；下一批优先开放白名单新卡、升级、删牌及可变牌数 |
| 遗物与药水 | 第一条训练闭环均为空；场景必须显式记录，不能隐式加载角色默认遗物 |
| 首个调试遭遇 | `setup_shrinker_beetle_weak` |
| 当前难度 | 初始己方血量 40/80；通过独立 pilot 从 10–60 HP 扫描选定 |
| 首版扩展遭遇 | M6 第一批已接入 `setup_fuzzy_wurm_crawler_weak`、`setup_nibbits_weak`，限各一只敌人；机制通过，双 seed 学习增益未通过 |
| 执行环境 | 本地 Python 模拟器；CPU 必须可运行，GPU 可选 |
| 训练方式 | 分轮同步采样与训练，先正确再提高吞吐 |
| 模型 | 小型卡牌 embedding + MLP，策略头与价值头共享编码器 |

每个遭遇进入训练前，必须列出会产生的卡牌、状态、怪物行为及随机事件。其完整机制都要在编码器和搜索状态中得到支持；不支持时拒绝场景，不能用全零特征或自动替代动作蒙混通过。

### 2.2 后续扩展

下一步先完成白名单卡池与牌组扩展，再启动长期训练。当前固定十张基础牌和三种 weak 遭遇已出现胜率饱和，不能仅增加基础牌副本或重复训练轮数来代替决策复杂度扩展。

1. 将场景工厂从固定 starter 改为按 deck 配方创建牌组，支持卡牌种类、升级、删牌和牌数变化；支持范围及数量边界显式记录在内容版本中。
2. 首批白名单覆盖攻击、防御、抽牌、能量、力量、消耗等不同用途，具体卡牌以仓库引擎实际支持并通过机制检查的条目为准。需要战斗内选牌的卡，必须先实现对应 phase、候选编码和动作处理。
3. 构造有明确差异的牌组家族，按牌组家族、遭遇和初始血量组合生成场景。保留基础场景，同时加入更困难的组合；新增遭遇逐项核对机制，不一次性开放全卡池。
4. 完成编码、粒子重建、动作与奖励一致性的必要回归及短程 smoke 后，直接进入分轮持续训练，不另设调参实验、消融实验或难度扫描作为启动门槛。
5. 后续再逐项开放药水／遗物、多敌人、精英／Boss 和其他角色。战斗奖励选卡、跑图等仍不属于本轮范围。

扩展必须更新场景清单、内容版本、编码 schema 和回归测试；未实现机制不得进入正式采样。

### 2.3 首版不包含

- 跑图、奖励选卡、商店、事件和完整通关策略。
- 全卡池、全角色、多人模式。
- MuZero 的学习式世界模型。
- 实机在线搜索和自动部署游戏 mod。
- 自动购买云 GPU、跨机器分布式训练。
- 对“超人类”“全游戏最优”或持续单调变强的承诺。

## 3. 当前基础与已知边界

| 路径 | 当前能力 | 本次处理 |
|---|---|---|
| `sts2_env/core/combat.py` | 战斗规则、回调、选牌、随机流 | 复用；扩展处需回归 |
| `sts2_env/gym_env/combat_env.py` | 铁甲初始牌组单场环境 | 保留 PPO 接口；新增 AZ 场景适配器 |
| `sts2_env/gym_env/action_space.py` | 动作解释与掩码 | 作为统一规则来源 |
| `sts2_env/core/constants.py` | 当前动作空间为 115 | 按版本绑定，禁止照抄旧 README 的 61 |
| `sts2_env/gym_env/observation.py` | 131 维 PPO 观测 | 不作为 AZ 的完整状态编码 |
| `sts2_env/gym_env/reward.py` | 胜 +1、败 -1 | AZ 独立定义并版本化效用 |
| `sts2_env/search/clone.py` | 支持闭包、绑定方法、slots 的复制 | 复用，扩大覆盖测试 |
| `sts2_env/search/mcts.py` | 无网络先验的确定性搜索 | 保留作性能／回归基线；不能直接用作信息集搜索 |
| `sts2_env/search/batch.py` | starter 场景配方、多进程独立搜索 | 复用进程组织方式，扩展为完整战斗采样 |
| `sts2_env/parity/bridge_replay.py` | 部分状态与实机轨迹对照 | 后续迁移验证 |

现有复制测试不等于全卡池安全性证明。模块全局对象仍可能被共享；当前只显式隔离了已知卡牌 ID 分配器。新增机制必须审查全局可变状态。

现有搜索的确定性 replay 假设“一串动作对应唯一状态”。正式随机搜索不能沿用该假设，不能仅给旧搜索换一个 value evaluator 就称为 AlphaZero。

## 4. 系统结构

```text
场景清单 + 当前 champion checkpoint
                 |
                 v
          多进程战斗采样器
                 |
     玩家信息状态 -> 网络 p,v -> 信息集 PUCT
                 |                 |
                 +--- 搜索策略 π <--+
                 |
          环境执行一个真实动作
                 |
       完整 episode + 终局结果 z
                 |
                 v
            Replay Buffer
                 |
                 v
          Learner -> candidate
                 |
       独立评估 -> 晋级 / 保留 champion
```

初版按轮执行：冻结 champion → 完成本轮采样 → 训练 candidate → 评估 → 更新 champion。每场战斗使用固定模型版本；禁止中途替换权重。

## 5. 场景、状态与动作契约

### 5.1 CombatScenario

用 JSON/YAML 可表达的数据配方创建场景，不 pickle 包含闭包的运行中 CombatState。

必要字段：

```text
schema_version, scenario_id, family_id, split
character_id, ascension, encounter_id
deck: [{card_id, upgraded, count}]
player_hp, player_max_hp
relics, potions
environment_seed
rules_version, content_manifest_version
```

首版从战斗开始采样，不实现任意中途场景导入。中途局面由场景配方和已执行动作重放得到。训练样本只需公开状态张量；场景完整信息与环境种子仅供环境执行／重放，不能流入网络或搜索采样器。

训练、验证、最终测试的 seed 集合不相交。牌组扩展后按 `family_id` 划分构筑家族，避免仅换 seed 就声称未见构筑泛化。完整清单保存为 manifest 并记录内容哈希。

扩展后的训练场景按冻结的生成规则持续产生，每轮保存实际使用的配方及内容哈希，保证可重放、恢复和 job 去重；不局限于重复抽取原有 256 个固定训练场景。验证和最终测试配方固定，使用独立 seed 命名空间，不参与训练生成。分层覆盖牌组家族、遭遇和血量档；配方生成失败不能静默换成 starter。是否留出整个构筑家族作泛化评估必须明确标记，不把同家族的新随机 seed 称为未见构筑。

### 5.2 三种状态

| 类型 | 用途 | 禁止事项 |
|---|---|---|
| `WorldState` | 环境真实推进，包含真实随机状态 | 不传给正式 planner |
| `InformationState` | 玩家当前可见信息、记忆与未知部分的约束 | 不含隐藏牌序、未来 RNG、私有 AI 状态 |
| `SearchParticle` | 从 InformationState 采样的假设完整状态 | 不得以真实隐藏状态为采样捷径 |

`InformationState` 包括已知牌堆组成、已公开的牌顶／牌底信息、已观察的怪物行动历史，以及本场中影响后续规则的公开计数。暂不实现历史神经网络；首版用明确的规则充分统计量表示所支持的记忆。

公开信息不足以推断的怪物内部状态也属于隐藏状态，应进入粒子假设。不能因为模拟器能读取它就放入观测。

### 5.3 动作

- 首版保留 115 维动作头，动作掩码与引擎使用同一规则来源。
- action 0 在普通阶段表示结束回合，在选牌阶段表示确认／跳过，必须有明确 phase 特征。
- 手牌／敌人索引属于当前决策状态，不跨状态复用旧索引。
- 当前无药水的场景中，药水动作全部 mask。
- 加入选牌后，编码候选内容、顺序、已选集合、最小／最大数量和是否可确认。
- 候选数量超过动作容量时直接报 schema 不支持；禁止静默截断。
- 非终局空 mask、执行合法动作失败、NaN 等均记为模拟器／接口错误，保留轨迹并终止本轮；不能伪装成正常失败样本。

## 6. 观测与网络

### 6.1 Encoder v1

新增独立 AZ 编码器，不改变现有 PPO 的 131 维接口。

| 输入分组 | 至少包含 |
|---|---|
| 玩家 | 当前／最大血量、格挡、能量、最大能量、回合数、本回合相关公开计数 |
| 能力 | 白名单场景涉及的全部玩家／敌人能力、层数和必要持续计数 |
| 手牌 | 卡牌 ID embedding、升级、当前费用、X 费用标记、数值、关键词／临时状态、槽位 mask |
| 牌堆 | 可见的抽牌堆组成及已知位置约束、弃牌堆／消耗堆组成；不输入未知抽牌顺序 |
| 敌人 | 怪物 ID、存活、绝对血量和最大血量、格挡、公开意图及伤害／次数、必要公开历史 |
| 阶段 | 普通战斗／选牌；首版虽仅普通阶段，也预留 schema |
| 合法动作 | 115 维 mask，策略归一化及训练损失统一使用 |

枚举 ID 使用固定词表，不将枚举序号归一化成有大小关系的连续值。不使用全局卡牌实例 ID 作为网络特征。超出支持范围时 fail fast，不能静默映射为普通牌。

向量形状、词表、归一化参数、能力白名单和 phase 编码存入 `encoder_schema.json`。Checkpoint 加载时必须检查 schema 哈希。

### 6.2 模型

起始结构：32 维卡牌 embedding + 显式数值特征 → 两层 256 宽 MLP → policy logits[115]、value[1]。value 通过 tanh 限制到 [-1, 1]。参数规模、是否需要扩大网络以实际观测维度和实验为准。

策略分布只在合法动作上 softmax；非法动作概率严格为零。损失使用合法索引，避免 `0 * -inf` 导致 NaN。

CPU 推理必须可运行。第一版不要求 Transformer，不先实现多角色共享网络。允许以后替换结构，但不得改变已有 checkpoint 的隐式输入含义。

## 7. 搜索算法

### 7.1 两种信息模式

- `full_state_debug`：可使用完整确定性状态，服务于网络／PUCT 的快速接通和回归。输出目录、数据集和 checkpoint 均带模式标记；不能晋级为正式玩家信息模型。
- `observable`：正式训练、评估和晋级模式。Planner 接收 InformationState，不能接收真实 WorldState 或环境 seed。

两个模式的 replay buffer、模型与指标严格分开。只完成 debug 模式不算首版完成。

### 7.2 PUCT 决策节点

从玩家视角维护每个动作的 `P, N, W, Q`：

```text
Q = W / N，未访问时 Q = 0
score(a) = Q(a) + c_puct * P(a) * sqrt(1 + sum_b N(b)) / (1 + N(a))
```

不要求像旧搜索那样先把所有动作各展开一次。每次模拟选择一条路径，到达未展开信息节点时，用网络计算先验和叶值；终局使用真实终局效用，不调用网络覆盖终局。

默认取消随机 rollout，使用 value head 评估叶节点。原 rollout MCTS 继续作为独立基线；不把取消 rollout 产生的提速表述为同等强度下的免费优化。

备份时不交替取负号。首版 gamma=1，同一玩家视角的终局效用沿路径回传。模拟深度上限使用 value bootstrap，不当成环境战败；根状态／网络结果可缓存，但缓存键必须包含模型版本和信息状态。

### 7.3 随机性与隐藏信息

采用共享信息历史树的粒子搜索，首版不实现完整通用 POMDP 求解器：

1. 根据公开牌堆组成和已知位置约束生成根粒子，不读取真实未知牌序。
2. 将未来随机事件视为模型中的随机转移，用独立搜索随机源采样；不能复制环境当前 RNG 来预测结果。
3. 保持模拟器随机流的路由和别名关系，不随意改成“每种事件互相独立”。受公开历史约束的隐藏状态必须条件采样。
4. 决策节点按公开历史／充分信息状态组织，键使用无损的规范化结构，不能只用可能有碰撞的归一化网络向量。
5. 同一动作的不同可见结果进入不同后继；随机结果按生成概率采样，不能用 PUCT 挑选“最幸运的随机结果”。
6. 公开信息相同的粒子共享动作统计和网络先验，不能为每个真实隐藏牌序建立独立最优策略再简单平均冒充无信息泄漏。
7. 模拟中的公开观察更新 InformationState 与已知位置约束。未知牌序在一次粒子模拟内应保持因果一致，不能每次抽牌前任意重排。
8. 相同信息节点的合法动作集合应一致；若不一致，要么缺少公开信息，要么尚未支持隐藏相关合法性，必须报错排查。

现有 replay 树仅保存动作序列不够用。正式树需保存动作边及公开结果分支；若实施粒子复用或节点缓存，必须验证不会把第一个随机后继固定成唯一后继。

隐藏信息的关键验收：两个真实局面具有相同公开历史但不同真实牌序／RNG 时，给 planner 相同的搜索 seed 和模型，根先验、访问分布和选中动作应完全一致。该测试要覆盖搜索标签，不能只测网络输入。

### 7.4 预算、探索与策略标签

- 默认采样预算 64 次模拟／动作，评估预算 256；同时支持 32/64/128/256 的预算曲线。
- 一次 simulation 定义为一次完成叶评估或到达终局并完成 backup 的路径；重试／取消不计数。
- 训练根先验使用 `(1-epsilon)P + epsilon*Dirichlet(alpha)`，仅对合法动作加噪声；起始 epsilon=0.25、alpha=0.3。
- 评估无根噪声、无温度采样，选择根访问最多的动作；并列使用固定动作顺序。
- 策略训练标签固定为 `pi = N / sum(N)`。动作采样温度独立：前 10 次决策 tau=1，之后 tau=0；这是起始配置，不是最终最优参数。
- 单一合法动作可直接执行，不增加搜索计数；记录 forced_action，策略标签为 one-hot。
- 起始 `max_search_depth=128`，防止搜索在零费循环或多选切换上无限深入。

## 8. 效用与训练样本

### 8.1 Reward v3：胜利、超时、死亡分别结算

下一阶段使用新奖励版本 `win-timeout-hp-v3`（待实现）。过程中奖励为 0，gamma=1，仅在终局一次性结算。历史 `win-loss-v1` 和 `win-first-hp-v2` 保留原定义与结果；v2 将超时和死亡同等处理，不回改历史标签。

定义 `h = clip(final_hp / initial_hp, 0, 1)`，`d = clip((enemy_initial_hp - enemy_final_hp) / enemy_initial_hp, 0, 1)`。

| 终局原因 | v3 效用 z | 范围与含义 |
|---|---|---|
| 胜利 win | `1 - 0.2 * (1 - h)` | `[0.8, 1]`；惩罚己方本场净掉血 |
| 死亡 death | `-1 + 0.2 * d` | `[-1, -0.8]`；敌方净掉血越多，失败惩罚越小 |
| 战斗超时 time_limit | `-0.2 + 0.4 * d` | `[-0.2, 0.2]`；介于死亡和胜利之间，敌方净掉血越多越好 |

任意单场胜利严格高于任意超时，任意超时严格高于任意死亡。超时对敌方造成 0%、50%、100% 净掉血时，效用分别为 -0.2、0、0.2；真实胜利已发生则必须归类 win，不能因同时达到预算上限覆盖成超时。这些系数为本次规格默认值，不表述为已验证最优。

己方掉血以本场初始血量为分母，不惩罚开局前已损失的血量。敌方使用终局净掉血，不能重复领取逐步伤害奖励。当前单怪无治疗且初始血量等于最大血量；扩展应保存明确的 enemy_initial_hp，而不是对新机制默认沿用 enemy_max_hp。真实环境、搜索终局、replay 标签和评估必须调用同一版本的奖励函数。

有限权重的标量期望不等于严格的胜率字典序优化；当前仍采用单一 value head 和效用 PUCT，晋级另设胜负优先门槛。本轮不引入多价值头或字典序搜索。

每场最多 400 次智能体决策、100 个玩家回合，在尚未胜利或死亡时触发任一上限即 `reason=time_limit`，按独立超时公式结算。超时不是胜利，胜率分母包含这些场次，必须单列超限率；选牌操作也计入决策数。允许存活至超时优于死亡是明确的设计选择，需持续记录拖延与循环情况，不把超时增多描述为胜率提高。

MCTS 到达新叶节点或搜索深度上限时，若战斗仍可继续，使用价值网络 bootstrap，不使用超时奖励。只有模拟战斗本身达到与真实环境相同的回合／动作上限，才结算 time_limit。搜索预算用尽也不会使真实战斗变成超时。

模拟器异常不能当作 time_limit 或 loss。失败场景进入错误目录，本轮不得晋级；支持修复后按场景配方复现。

药水、治疗、复活或多怪加入后，需重新审核初始血量定义和净伤害计算，不静默沿用当前单怪公式。

### 8.2 样本与 episode

每个决策保存：

```text
episode_id, scenario_id, family_id, step_index
information_mode, encoder_version, action_schema_version, reward_version
model_version, observation, legal_mask, root_visits, policy_target
chosen_action, search_simulations, search_seconds, forced_action
```

Episode 完成后补充 `z, termination_reason, final_hp, initial_hp, enemy_initial_hp, enemy_final_hp, enemy_max_hp, turns, decisions`，支持从原始量复算奖励。enemy_initial_hp 为 v3 明确保存的字段；历史 v2 保留其单怪假设。由于 gamma=1 且仅终局奖励，同一 episode 的 value target 都是 z。

Replay 以完整 episode 原子提交；中断、异常和不完整 episode 不进入训练 buffer。记录可重放的场景配方、真实动作序列及随机 seed，但这些调试元数据必须与网络张量访问接口分离。

Buffer 起始容量 200,000 个决策样本，按最旧完整 episode 淘汰。每批先均匀抽取场景家族，再抽取 episode 内决策，避免长局和单一遭遇占满训练分布。无兼容家族样本时使用当前非空家族，记录实际采样比例。

信息模式、encoder/action/reward/rules 版本不兼容时拒绝混用数据。需要迁移就生成新 buffer；禁止静默 reshape 或覆盖标签。

## 9. 训练、自进化与持久化

### 9.1 分轮训练

1. 加载或随机初始化 champion，固定本轮模型版本。
2. 各 worker 采样完整战斗，收集本轮至少 256 个有效 episode。
3. 将完整 episode 写入 buffer，生成采样统计和异常报告。
4. 从 champion 权重初始化 candidate；首版每轮重置 optimizer，避免跨版本优化器状态含义不明确。
5. 训练 candidate，记录 loss 与模型／数据版本。
6. 在验证集比较 candidate 与 champion。
7. 通过门槛则原子更新 champion 指针，否则保留 champion。保留候选 checkpoint 及评估报告。
8. 下一轮按 champion 继续采样；候选失败不修改历史样本。

初始候选从随机网络和搜索数据训练，不强制 PPO 或专家预训练。若需要启发式／PPO warm start，作为独立配置明确标注，不能与从零训练结果混称。

### 9.2 起始超参数

| 参数 | 默认 |
|---|---:|
| train simulations | 64 |
| eval simulations | 256 |
| c_puct | 1.5 |
| collector workers | 4，性能验证后可调 8 |
| episodes per iteration | 256 |
| replay capacity | 200,000 decisions |
| batch size | 256 |
| optimizer | AdamW |
| learning rate | 0.0003 |
| weight decay | 0.0001 |
| updates per iteration | 200 |
| gradient clip norm | 1.0 |
| maximum iterations | 50，达到上限停止并报告结果 |

损失：`policy_cross_entropy(pi, p) + value_mse(z, v)`；L2 类约束通过 AdamW weight decay 实现，不再重复添加相同正则项。记录 policy entropy、value MAE、梯度范数、KL(pi || p) 和各场景样本比例。

以上是可修改的起点，不能作为已验证能收敛的配置。新机制和 v3 完成必要回归及 2 轮小规模 smoke 后，直接启动 2 个 seed（42、43）的持续训练，默认各最多 50 轮；不再沿用旧实验“各仅训练 2 轮”的停止规则。每轮 256 场采样、200 次更新，256 场固定晋级验证；两组最终模型冻结后，各 150 场最终测试。未晋级时保留冠军并继续下一轮，达到预设轮数后据实报告。

新内容／编码／奖励版本使用新的运行目录和 replay。不能直接恢复旧 v2 运行或把旧标签交给 v3 价值头。默认新版本随机初始化；如实施旧策略权重迁移，必须显式映射兼容特征、处理新增词表与价值头、记录来源并完成兼容性检查，不能静默加载。旧运行及原始结果完整保留。

### 9.3 模型与恢复

Checkpoint 至少包含模型参数、schema 哈希、配置、模型版本、信息模式、奖励版本、规则版本／代码摘要、轮次和训练统计。迭代中恢复还要保存 candidate optimizer、随机源状态、buffer manifest 和已提交 episode/job ID。

- 使用临时文件 + 原子重命名写 checkpoint、manifest 和 champion 指针。
- 中断采样后重新调度未提交 job，按 episode/job ID 去重。
- 中断训练后可恢复更新步；若仅支持轮次边界恢复，要明确标记并从该轮重新训练，不能重复提交数据。
- 不要求跨不同硬件位级一致，但必须记录依赖版本和 determinism 配置；同硬件／同配置的恢复测试应重现下一批样本与更新结果。
- 每个 job seed 从 master seed、iteration、job ID 和用途标签稳定派生，不使用 Python 随机化的内置 hash。

## 10. 评估与晋级

### 10.1 基线与指标

必须比较：随机合法策略、可复现规则策略、现有无网络 MCTS、champion 网络、candidate 网络。PPO checkpoint 存在且输入／动作版本兼容时才加入；不存在时不得使用 README 中的历史胜率充当实测基线。

公平比较的策略必须使用相同信息权限。旧全状态 MCTS 只能作为标注清楚的 oracle 参考，不与 observable 策略混排宣称优劣。

每个模型同时测：

- 网络直接决策，不搜索。
- 相同搜索预算下的表现。
- 选定预算下的端到端决策延迟 p50/p95。

指标：胜率、终局效用、剩余血量、胜局剩余血量、回合数、药水消耗（启用后）、超限率、异常率、非法动作数、各遭遇结果、采样吞吐与样本数。死亡场次剩余血量计零；条件指标明确标出条件，避免幸存者偏差。

### 10.2 晋级规则

- 每次晋级使用固定 256 个验证场景，遭遇分层平衡；新旧模型使用相同场景配方和环境 seed。
- 对成对场景的终局效用差做 10,000 次成对 bootstrap，使用固定统计 seed。
- 95% 置信区间下界 > 0、无模拟器异常／非法动作，才晋级；否则保留 champion。
- Reward v1 下效用差等价于胜率差的线性变换。仅剩余血量更好不触发 v1 晋级。
- Reward v2/v3 还必须满足：胜率成对差的 95% CI 下界 > 0，或者全部配对场景的胜／未胜结果逐场完全相同。后一情况下允许通过更高效用晋级；v3 包含胜局保血、死亡局敌方净掉血和超时效用改善。仅平均胜率相等但胜负场景发生交换不算同结果。效用 CI 下界仍须 > 0。必须分别报告胜率差与效用差，禁止把效用差除以 2 冒充胜率差。纯网络和固定预算搜索均须通过，才更新共同冠军。
- 这是操作门槛，不是反复选择后仍无偏的科研显著性证明。固定验证集参与选择，最终测试集不参与任何晋级或调参。

### 10.3 首版学习验收

固定最终 checkpoint 后，在未使用过的 150 个测试场景上运行，并报告 2 个独立训练 seed（默认 42、43）的结果。分别给出配对胜率差、效用差、置信区间和各遭遇指标。

2026-10-09 用户将后续最终测试规模调整为每个 seed 150 场，晋级验证调整为每轮 256 场，仍使用 2 个训练 seed；每轮训练采样场数不变。已完成的 500 场测试／512 场验证实验保留原始结果，不截断重算。后续 M6 测试数为每 seed 总计 150 场，验证数为每轮总计 256 场，按牌组家族与遭遇分层平衡并覆盖设定血量档；不能整除时各层数量最多相差 1。分层数量超过固定预算时须明确缩小本轮纳入范围，不能宣称覆盖未评估的组合。新阶段使用全新的训练／验证／测试 seed，不能重复使用已查看的旧测试集。此前 10–60 HP pilot 与 40 HP 选择属于历史记录；后续不要求重复独立难度扫描，先按冻结的内容生成规则扩大场景，再在持续训练中记录难度分层指标，禁止依据最终测试选择难度。

必须证明：最终网络单独决策相对初始网络有学习增益；最终模型配合搜索，在相同信息权限和预算下相对初始模型配合搜索有增益。若仅增加模拟次数才提高分数，不能判定模型自进化。

若限定场景过易导致初始搜索已接近满胜率，保留该诊断结果，在验证阶段增加合理的初始血量／构筑难度后重新冻结 manifest；不能看过最终测试结果再修改同一测试集继续宣称独立评估。

## 11. 性能与并行

当前已测基线见 `docs/MCTS_PERFORMANCE.md`：12 个开局／中途场景、每步 128 次模拟、rollout depth 40，串行约 391 sims/s，4 worker 约 1,479，8 worker 约 2,198。数字不含池启动，且尚未包含神经网络和信息粒子采样，不能直接当作 AZ 吞吐承诺。

实现顺序：

1. 每个 worker 持有冻结的小网络副本，CPU 推理线程数默认为 1，避免进程 × BLAS 线程过度订阅。
2. 复用进程池，一次任务采样完整 episode，不为每次出牌创建进程。
3. 记录 cloning、合法动作、环境推进、粒子采样、网络推理、IPC、训练各项耗时。
4. 只有推理占比明显时，增加集中式批量推理；请求需带 model version、request ID 和合法 mask，超时／失败必须显式处理。
5. GPU 放在 learner 或独立 inference server；不默认每个采样 worker 各加载一份 GPU 模型。

性能验收：固定 manifest、预算、模型和信息模式，测试 1/4/8 worker；报告 simulations/s、decisions/s、episodes/s、p95 延迟、峰值 RAM 和 startup 时间。正确性模式下串并行应生成相同访问分布；性能测试不得改变 rollout 深度或忽略失败任务来制造加速。

当前阶段不设未经验证的绝对吞吐硬指标。进入长训练前必须有一次包含网络和信息采样的端到端测量，并据此估算本轮成本。

## 12. 文件与接口规划

下列新增路径和命令属于实施目标，当前尚未存在，不能直接运行。

```text
configs/alphazero_combat.yaml
sts2_env/az/
    config.py          # 配置、版本与运行清单
    scenarios.py       # 白名单场景配方、split、重放
    adapter.py         # 环境推进、公开信息投影、终局语义
    information.py     # 历史统计、隐藏约束、粒子采样
    encoder.py         # AZ 专用观测和 schema
    network.py         # 策略／价值网络与 masked inference
    puct.py            # 网络先验、信息节点和随机后继
    self_play.py       # 完整战斗采样、多进程 collector
    replay_buffer.py   # episode 事务、分层采样、版本校验
    learner.py         # 损失、优化器、checkpoint
    evaluation.py      # 基线、成对评估与晋级
    coordinator.py     # iteration 状态机、恢复与 champion 管理
scripts/
    train_alphazero_combat.py
    evaluate_alphazero_combat.py
    benchmark_alphazero_combat.py
tests/
    test_az_information.py
    test_az_encoder.py
    test_az_puct.py
    test_az_replay.py
    test_az_resume.py
    test_az_smoke.py
```

关键接口的职责：

```python
world = make_scenario(recipe)
info = observer.observe(world, public_history)
particle = belief.sample(info, search_rng)   # 不接收 world 或 environment_seed
encoded = encoder.encode(info)
priors, value = network.predict(encoded, legal_mask)
result = planner.search(info, model_version, search_seed, budget)
transition = environment.step(result.action)
buffer.commit(completed_episode)
report = evaluator.compare(candidate, champion, validation_manifest)
```

CLI 目标：

```powershell
python scripts/train_alphazero_combat.py --config configs/alphazero_combat.yaml --output output/az_combat
python scripts/train_alphazero_combat.py --resume output/az_combat
python scripts/evaluate_alphazero_combat.py --checkpoint output/az_combat/champion.pt --manifest data/az/test.json
python scripts/benchmark_alphazero_combat.py --config configs/alphazero_combat.yaml --workers 1 4 8
```

依赖规划：新增最小 `az` optional extra，先只要求 PyTorch；配置尽可能用标准库可解析格式或明确添加 YAML 依赖，不把 SB3 作为 AZ 必需依赖。实施时先确认本机 Python／PyTorch 可用组合；如果当前 Python 3.14 环境不兼容，新建独立 AZ 虚拟环境，不破坏现有模拟器环境。

## 13. 分阶段任务与验收

| 阶段 | 交付 | 必须通过的门槛 |
|---|---|---|
| M0 场景与契约 | manifest、场景工厂、状态／动作／终局适配器、版本配置 | 场景重放一致；异常不吞；原有搜索测试继续通过 |
| M1 网络与确定性闭环调试 | encoder、网络、masked PUCT、debug 数据格式 | 小型已知最优决策测试；非法概率为零；value 备份不翻号；输出明确标 debug |
| M2 玩家信息搜索 | InformationState、受约束粒子采样、随机后继树 | 隐藏牌序/RNG 置换不影响同 seed 的规划结果；小型随机树期望值正确 |
| M3 自主采样与训练 | collector、buffer、learner、2 轮 smoke run | 完整 episode 标签正确；loss 有限；版本隔离；固定小数据可过拟合；原状态不被搜索修改 |
| M4 晋级与恢复 | coordinator、champion/candidate、成对评估、恢复 | 接受／拒绝两条路径都可测试；中断不重复提交；恢复 schema 校验有效 |
| M5 性能与正式实验 | 端到端 benchmark、限定场景训练、最终评估报告 | 固定预算和信息权限；2 个训练 seed；各 150 场最终测试；工程与学习验收分别出结论 |
| M6 范围扩展 | 牌组、选牌、药水／遗物，逐项开放 | 每个新机制有编码、搜索隔离与引擎规则回归，不一次性开放全卡池 |

执行顺序为 M0 → M1 → M2 → M3 → M4 → M5。M1 的 full-state smoke 仅用于调试，不能替代 M2。M6 不阻塞首版限定范围验收。

## 14. 必测失败模式

1. 复制选牌回调、怪物闭包、RNG 和 slots 后，原战斗及兄弟分支保持不变。
2. 搜索生成牌不会推进真实战斗的全局卡牌 ID 分配器；异常退出也恢复。
3. 同信息不同隐藏状态的根策略一致；同隐藏 seed 不能通过场景 ID、实例 ID 或缓存键泄漏。
4. 随机后继的选择按概率发生；使用可枚举小环境验证期望值和访问统计。
5. 相同动作索引在不同阶段被正确解释；不可执行旧状态的目标映射。
6. 搜索节点达到深度上限用 bootstrap，真实 episode 达到预算上限用明确的 time_limit 标签。
7. 同一模型版本串行与并行输出一致；任务失败不能丢弃后仍计算漂亮的吞吐。
8. 不完整 episode、模式不兼容样本、损坏 checkpoint 均被拒绝。
9. 无噪声评估与有噪声训练不会互相污染；测试集不进入 replay。
10. 权重晋级为原子操作，worker 不会在一场战斗中混用模型版本。

## 15. 交付与风险处理

首版交付包括源码、配置、场景 manifests、测试、benchmark JSON、训练日志、至少一个可加载 checkpoint 和评估报告。没有验证增益的 checkpoint 也可交付，但必须标记“工程闭环完成，学习效果未达标”。

最主要的风险是模拟器规则偏差、隐藏信息泄漏、状态遗漏和采样成本。分别通过限定机制清单、信息边界测试、encoder 覆盖门槛和端到端 benchmark 控制。遇到不支持的新机制应缩小显式范围或补齐实现，而不是继续大规模采样。

原 40 HP Shrinker 实验已完成。M6 第一批三遭遇实验详见 docs/AZ_M6_ENCOUNTERS.md；实验已完成并核验，最终四组均 150/150 胜，但 seed 43 保留初始模型，学习增益未通过。该结论及搜索保血退化记录保留，不改写成验收通过。

下一步实施顺序：可配置牌组与白名单新卡 → 对应编码／粒子／动作支持及 Reward v3 → 分层场景生成与必要回归、短程 smoke → 2 seeds 持续训练及自动晋级 → 冻结最终模型后各 150 场测试。搜索保血指标随训练持续记录，不再先安排独立诊断实验；若发现规则或实现错误仍须修复。药水、遗物、多敌人及后续内容分批开放。本次仅修订规格，不代表上述扩展已实现或长期训练已启动。
