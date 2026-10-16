# AlphaZero 实施记录

## M0：场景与契约

新增 `sts2_env/az/{config,scenarios,adapter}.py`，独立于 PPO 接口。
场景使用严格 JSON 配方和 SHA-256 内容哈希；manifest 联合检查所有 split 的 seed 与 ID 不重叠。
首版构筑家族只有 `ironclad-starter`，因此同家族跨 split 仅用于 seed 泛化，不能称未见构筑泛化。

生成清单：

```powershell
.venv/Scripts/python.exe scripts/prepare_az_manifest.py
.venv/Scripts/python.exe -m unittest tests.test_az_scenarios tests.test_search_mcts -v
```

默认生成 256 train / 512 validation / 2000 test 配方。生成测试配方不运行测试战斗。
这是 M0 开发清单；正式实验开始前仍需按难度诊断冻结实验清单。

### 内容审核：shrinker-starter-v1

| 机制 | 当前引擎行为及后续覆盖要求 |
| --- | --- |
| 牌组 | 5 Strike Ironclad、4 Defend Ironclad、1 Bash，均未升级 |
| 玩家动作 | 定向攻击、自身格挡、结束回合；无选牌、生成牌、消耗、药水和遗物 |
| Bash | 攻击并施加 Vulnerable；编码层数和持续时间，遵循引擎伤害取整 |
| Shrink | 怪物首次行动施加 -1；当前实现 powered attack 伤害乘 0.7，负层数不会按回合递减；施加者死亡时移除。不能照注释当作 -1 Strength |
| 怪物 | SHRINKER_BEETLE，38–40 HP；SHRINKER → CHOMP(7) → STOMP(13) → CHOMP 循环，ascension 0 |
| 随机性 | 怪物初始 HP、初始洗牌、弃牌重洗；怪物行动周期本身确定 |
| 隐藏信息 | 未知抽牌顺序和未来 RNG；M2 必须从公开组成与历史重新采样，不传真实 world/seed |
| 规则动态 | 费用、能量、回合、格挡重置、抽牌／弃牌、公开意图、Vulnerable 与 Shrink 生命周期 |

这里只审核当前模拟器行为，不构成与实机规则完全一致的证明。
其他遭遇、升级和构筑均明确拒绝，待更新机制清单及编码器后开放。

### 接口约定

- `make_scenario(recipe)` 返回真实 WorldState，显式空遗物和空药水，不重置全局卡牌实例计数器。
- `CombatAdapter` 是真实执行接口，不是正式 planner 的输入；M2 的 InformationState 尚未实现。
- mask 使用引擎同一规则，绑定 115 维。终局返回全零 mask，禁止再次行动。
- masked-legal 动作被拒绝时抛出异常；非法动作、容量超限和选牌阶段均 fail fast。step 异常保存配方、成功动作前缀、尝试动作和预算到错误目录。
- 胜利 +1，死亡／真实 episode 预算超限 -1；异常不会转成失败标签。终局优先于预算。
- 允许玩家在第 100 回合行动，结束后进入第 101 回合时立即超限，不再做决策；报告 turns 为 100。
- 轨迹与场景属于调试元数据，不能作为未来网络训练张量接口。
- 原子 JSON 使用同目录临时文件、fsync 和 replace；用途 seed 用 SHA-256 稳定派生。

## M1：网络与确定性闭环调试

已实现 `encoder.py`、`network.py`、`puct.py` 和 `scripts/smoke_alphazero_debug.py`。
本机独立环境 `.venv-az`：Python 3.12.14、PyTorch 2.14.1+cpu，未修改原 Python 3.14 模拟器环境。
`az` optional extra 只新增 PyTorch，`uv.lock` 已同步。复建环境可使用 Python 3.12：

```powershell
python -m venv .venv-az
.venv-az/Scripts/python.exe -m pip install -e ".[az,dev]"
.venv-az/Scripts/python.exe scripts/smoke_alphazero_debug.py --output output/az_m1_smoke
.venv-az/Scripts/python.exe -m pytest tests/test_az_encoder.py tests/test_az_puct.py tests/test_az_smoke.py tests/test_az_scenarios.py tests/test_search_mcts.py tests/test_gym_env.py -q
```

输出目录必须为空；命令自动加入 `full_state_debug` 子目录，避免覆盖前次结果。

- 编码：10 个手牌槽位的固定词表 ID 和 8 维数值，59 维全局特征，115 维 mask。能力覆盖 Shrink/Vulnerable 层数、跳过持续时间扣减、ignore 标记和施加者；牌堆按组成计数，不含未知顺序。公开动作历史在 debug 阶段从引擎日志提取，不能因此声称已实现正式 InformationState。
- 限定范围内牌值固定；不支持升级、临时费用、附魔、其他状态或选牌时立即拒绝。引擎在出牌时写入 `_stars_spent_for_play=0`，该无效应记账值允许存在，其余未建模 combat_vars 拒绝。
- 网络：32 维卡牌 embedding，256×256 MLP，115 维策略头和 tanh 价值头，共 242,932 参数；策略与损失均按合法索引计算。
- 搜索：共享玩家视角 PUCT，不翻转价值；终局直接使用效用，搜索深度上限 bootstrap；训练根噪声与动作温度独立，标签始终 `N/sum(N)`；唯一合法动作 one-hot 且计 0 simulation。
- 所有搜索操作在克隆上执行，正常及异常退出均恢复全局卡牌 ID 分配器。这里仍然复制真实未来随机状态，属于有完整信息权限的 debug 搜索，不能用于 observable 晋级。
- Checkpoint 包含模式、schema 哈希、动作／效用／内容／规则版本、源码摘要、配置及统计；加载校验版本和有限权重，不允许用 debug checkpoint 冒充 observable。只支持权重重载，M4 的训练状态恢复尚未实现。
- 完整 episode 原子保存；终局后统一补充 z。可重放配方/seed/actions 单独存入 traces，训练张量从 observation 访问。此调试脚本没有 replay buffer、正式评估或晋级功能。

已运行两场 debug 战斗（每步 8 次模拟），得到 41 个决策样本，并完成 10 次 AdamW 更新与 checkpoint 精确重载。两场均胜利，loss 从 2.4148 降至 1.5268；这些仅说明接线和梯度正常，不证明学习增益，也不是 M3 要求的两轮正式 smoke run。
报告：`output/az_m1_smoke/full_state_debug/report.json`；可加载权重：同目录 `initial.pt`、`candidate.pt`。

## M2：玩家信息与随机粒子搜索

已新增 `information.py`、`observable_puct.py` 和 `ObservableCombatAdapter`。
`plan_observable(info, model, ...)` 与 `BeliefSampler.sample(info, search_rng)` 严格拒绝 world/recipe 输入。

### 信息边界与范围

- InformationState 为不可变纯数据，不含真实世界引用、scenario ID、环境 seed、卡牌实例 ID 或 RNG。
- Observer 只读可见手牌、弃牌、消耗牌、血量／格挡／能量、公开能力层数及意图；抽牌组成由初始牌组守恒推导，完全不访问真实抽牌堆。PublicHistory 在环境执行动作后显式更新，不读取 AI 的 state_log 或 performed 标记。
- 当前牌组无生成、消耗、抽牌控制、星能、临时费用、能力牌、遗物或药水。跨回合伤害／抽牌计数等引擎日志没有白名单机制消费；当前回合已出牌、怪物公开行动史与现有能力层数足以支持未来规则。未来增加机制必须重新审核这些省略项。
- Shrinker 的行动周期可由公开历史唯一确定，不存在需要推测的未公开 AI 分支。Shrink 施加者必为唯一怪物且值为 -1；敌人 Vulnerable 必来自 Bash，持续扣减标记按这一规则推导，不把私有 power 字段当可见特征。
- 牌顶／牌底约束字段显式存在，目前必须为空；白名单没有揭牌或排牌效果，非空约束会拒绝，不声称已支持这些扩展机制。
- 终局杀敌牌可能仍停在 play 区，将其归入终局公开弃牌组成以维持守恒；终局不会再被采样或送入价值网络。

### 粒子模型与搜索

每次模拟用公开状态独立构造 CombatState 与怪物闭包。根未知牌序在剩余组成内洗牌，整条模拟路径保持该牌序，后续重洗由同一个搜索 RNG 推进。所有模拟器 shuffle/AI/target 等随机路由继续别名到该单一流；不复制环境 RNG，不为不同事件随意拆分随机流。

这里采用未知牌均匀排列、未来随机事件按模拟器随机模型采样的信念假设；不从公开抽牌轨迹反推真实伪随机 seed。仅有公开组成约束的当前场景使用该模型；新增具有额外隐藏历史约束的机制必须扩展条件采样器。

每个动作边维护共享 P/N/W/Q 和按无损公开信息结构索引的结果分支。结果由粒子转移自然产生，PUCT 只选择玩家动作。同一公开节点的 mask 必须一致；mask 不参与节点身份，避免不一致被藏成新分支。没有跨次搜索的缓存，节点结果键另包含 model version。

Observable encoder schema 独立版本化，在 M1 形状基础上增加两个 episode 预算特征（61 维全局输入）；网络、观测及 checkpoint 均检查信息模式，debug 权重不能冒充 observable。schema 保存于 `configs/az_observable/encoder_schema.json`。

### 验收与运行

```powershell
.venv-az/Scripts/python.exe scripts/smoke_alphazero_observable.py
.venv-az/Scripts/python.exe -m pytest tests/test_az_information.py tests/test_az_stochastic.py tests/test_az_encoder.py tests/test_az_puct.py tests/test_az_smoke.py tests/test_az_scenarios.py tests/test_search_mcts.py tests/test_gym_env.py -q
```

85 项测试、30 个子测试通过。其中覆盖：

- 多回合下真实牌序／RNG／实例 ID／私有 AI 日志变化，噪声开关两种配置的根先验、访问数、策略标签及动作完全一致。
- Observer 禁止读取 draw_pile/RNG 的哨兵测试；粒子条件组成和抽牌频率、路径内因果一致、RNG 别名关系、异常后全局 ID 恢复。
- 10 场完整战斗逐步重建对照。测试专用代码耦合两个世界的随机性以验证转移一致性；生产采样器没有接收真实隐藏状态的接口。
- 可枚举随机树验证期望值、随机结果访问频率、多后继；不可区分隐藏状态必须共享决策统计；mask 不一致报错；深度 bootstrap 和训练／评估噪声隔离。

固定随机网络（未训练）、每步 64 次模拟的两场 smoke 共 52 次决策、2,880 次模拟（强制动作不计模拟），有 34 个根动作边实际出现多个公开结果。两场均死亡，结果完整保留，不修改难度或验收标准。单进程集成运行约 3.87 秒，搜索延迟 p50/p95 约 85/92 ms；这不是 M5 的正式端到端 1/4/8 worker benchmark。

`output/az_m2_smoke/observable/` 保存随机初始 checkpoint、schema、完整 episode、独立复现 traces 和报告；`docs/az_m2_acceptance.json` 保存验收结果。本阶段不做训练、晋级或最终测试评估。

## 后续门槛

M4–M5：晋级恢复、性能测试和正式三 seed 学习验收。

目前已有 debug checkpoint 和可加载的 observable 随机初始 checkpoint；正式 observable 工程训练闭环和学习效果验收均未完成。

## M3：自主采样与训练（已完成）

`self_play.py` 使用可复用的 spawn 进程池，每个 worker 只用一个 CPU 推理线程，按 checkpoint SHA256 缓存冻结网络。每个任务采样一场完整战斗；模型文件被替换、版本不符或模拟异常均使本轮失败，不产生失败标签。训练搜索默认 64 simulations，根噪声使用既定参数，前 10 次决策温度为 1，此后为 0。搜索随机种子由 master seed、轮次、job ID、决策位置派生，与环境随机源分开。

`replay_buffer.py` 只接受完整 train episode，检查版本、终局标签、观测形状、合法动作和原始访问分布。episode 文件先原子写入，再原子更新 manifest；后者是提交点，中断产生的孤立文件不会自动加载。重复任务去重，冲突标签报错。容量默认 200,000 个决策，按最旧整局从活动集合淘汰，磁盘文件保留作审计档案，因此磁盘占用并不受此容量限制。manifest 保留淘汰记录，避免重试复活旧数据。单 coordinator 写入；不支持并发写同一 buffer。

批次按非空 family → episode → decision 逐层均匀抽取，记录 family_counts。learner 接口只返回 observation、pi、z，真实场景和随机种子另存 debug 目录。决策耗时正常保留，但不计入确定性重试的标签摘要。

`learner.py` 从 champion 复制 candidate，每轮新建 AdamW，默认 lr=0.0003、weight_decay=0.0001、clip=1，记录策略／价值损失、熵、MAE、KL、梯度范数与家族比例。checkpoint 仍仅支持权重加载；优化器／训练 RNG 中途恢复及晋级将在 M4 实现。

复现命令：

```powershell
.venv-az/Scripts/python.exe scripts/smoke_alphazero_training.py --output output/az_m3_acceptance
.venv-az/Scripts/python.exe -m pytest tests/test_az_replay.py -q
```

两轮 smoke：2 个持续 worker，每轮 4 场、每步 64 次模拟、20 次训练更新、batch 256。共 8 胜、145 个决策、7,552 次模拟。第一轮 loss 2.26088 → 1.22799，第二轮 2.25287 → 1.29603。两轮均从同一个随机 champion 采样并初始化 candidate；未实现评估之前不擅自晋级。第二轮训练使用累计 replay。输出包含 initial.pt、candidate-0.pt、candidate-1.pt、独立轨迹、replay manifest 和逐更新报告。

新增 14 个测试覆盖串并行标签一致、进程池复用、完整标签、版本／split 隔离、整局淘汰、重复提交、提交中断、损坏数据、失败 worker、固定小批次过拟合及 champion 权重不变。完整相关回归：99 passed，30 subtests passed；M2 搜索隔离测试继续通过。正式训练默认每轮 256 场，本次小规模 smoke 明确不满足正式训练规模，也不用于证明学习增益。

下一步 M4：成对评估、接受／拒绝晋级、coordinator 状态机、optimizer/RNG 恢复及中断去重。工程完整闭环和学习效果验收仍待完成。

## M4：晋级与恢复（已完成）

`coordinator.py` 提供 collect → train → evaluate → finalize 状态机和结束状态，正式默认配置使用 `configs/alphazero_combat.json`。配置采用标准库可解析 JSON，不额外引入 YAML。固定 manifest 的内容、副本、代码摘要、依赖版本、CPU 线程数和确定性设置随运行保存。每轮 champion 固定；候选重新初始化 optimizer。当前仅支持已审核的单场景家族，多家族验证集需补齐平衡选择审核后才能启用。

`evaluation.py` 同场景、同环境 seed、同搜索 seed 分别评估网络直接决策与固定预算搜索。搜索模式的成对效用差决定晋级：恰好 512 个验证场景、10,000 次固定 seed bootstrap、95% CI 下界严格大于 0、无异常和非法动作。小规模验证或非默认 episode 上限不能晋级。异常直接中止并保留可复现轨迹；同一轮曾失败则恢复后仍禁止晋级。

采样恢复以 replay 已提交 episode ID 为准，仅重新调度缺失任务。每次训练更新后原子保存模型、AdamW optimizer、更新计数、独立 NumPy Generator 状态、Python/Torch RNG、完整历史及 replay manifest 摘要。中断可重现下一批数据和下一次更新。评估中断会重跑该轮成对评估。代码、依赖、schema、场景清单、champion 或训练时 replay 改变会拒绝恢复，不能无提示改变实验。

`state.json` 是唯一轮次／晋级提交点，`champion.json` 是其派生指针：指针更新中断时，重启会依据 state 修复。候选未晋级也保留 checkpoint 与评估报告。单运行目录只允许一个 coordinator；本阶段不支持多进程同时写同一运行目录。首次初始化在 state 提交前中断时，应使用新的空输出目录。

新增入口：

```powershell
# 小规模工程验收；不满足正式晋级样本量
.venv-az/Scripts/python.exe scripts/train_alphazero_combat.py --config configs/az_m4_smoke.json --output output/az_m4_acceptance
.venv-az/Scripts/python.exe scripts/train_alphazero_combat.py --resume output/az_m4_acceptance
# 正式配置入口，尚未执行长训练
.venv-az/Scripts/python.exe scripts/train_alphazero_combat.py --config configs/alphazero_combat.json --output output/az_combat
```

`evaluate_alphazero_combat.py` 支持独立 checkpoint 评估，默认 validation split，提供随机合法策略、固定公开信息规则（Bash → Strike → Defend → 结束回合）、网络及网络搜索结果；可显式开启旧 MCTS oracle，结果标为 full_state_oracle，不参与 observable 公平排名。最终测试必须显式选择 test，coordinator 晋级始终只读 validation。未发现／接入 PPO checkpoint，不引用历史 PPO 指标。

验收输出 `output/az_m4_acceptance/`：2 轮、4 个完整训练 episode、每轮 3 次更新；每轮 4 个成对验证场景，同时测网络和 8 simulations 搜索。两轮均不晋级；网络 champion 胜率 0，candidate 分别 0.25、0.5，搜索双方均 0。样本量太小且搜索没有改善，这些数字仅确认工程路径，不支持学习增益结论。恢复已完成运行不会重复采样或更新。

新增 6 项测试：正式 512 场合成接受／拒绝门槛、异常禁止晋级、小验证集禁止晋级、下一批和参数更新精确恢复、损坏 schema 拒绝、采样提交后中断去重、训练／评估阶段重启、晋级指针修复、配置与 manifest 校验、公开规则和随机基线可复现。真实 smoke 覆盖拒绝路径，接受路径通过合成效用与独立指针测试验证，未把合成结果作为真实晋级。

M4 工程阶段验收通过；M5 的 1/4/8 worker 端到端性能测量、正式训练成本估算、三训练 seed 和最终独立测试尚未完成。完整首版与学习效果仍不能宣称完成。

## M5：性能与调整范围实验已完成，学习验收未达标

新增 `benchmark_alphazero_combat.py`、`profile_alphazero_combat.py` 和可恢复的 `run_alphazero_experiment.py`。1/4/8 worker 的端到端固定任务标签一致，温吞吐约 737/2426/3380 simulations/s；选用 8 workers。评估也使用持久进程池，并将每场完整结果原子缓存，串并行随机 seed 对齐测试通过。psutil 作为 AZ extra 依赖用于实测进程树内存。

三组 seed 各 2 轮的运行已完成：每轮 256 场、200 updates、512 validation、eval simulations 256。最终测试后续调整为每 seed 500 场，见下方修改记录。完成了调整范围的工程实验；seed 42 和 44 两种模式均有显著正增益，seed 43 初始已满胜率且没有晋级，整体学习验收未达标。原规格的每 seed 至少 2,000 场测试条件仍未满足，不将调整范围的完成描述为原规格全部通过。结果与区间见 [AZ_EXPERIMENT_RESULTS.md](AZ_EXPERIMENT_RESULTS.md)。

详细性能、profiling、实验预算、恢复方式及局限见 [AZ_PERFORMANCE.md](AZ_PERFORMANCE.md)。相关回归：108 tests、30 subtests 通过。

2026-10-09 用户同意将最终测试从每 seed 2,000 场减为 500 场。修改时仍在 seed 42 第一轮验证，最终测试尚未开始。保留旧计划并记录 test_count_amendment.json，固定取原 manifest 前 500 个 test 配方；原训练 checkpoint 和验证缓存继续使用。恢复命令需增加 `--test-count 500`，训练／512 场晋级验证参数未改动。新增缩减样本数门槛测试，相关 experiment 测试 3 项通过。

### 2026-10-09：Windows 原子替换的间歇性失败修复

两次实验进程均因 replay manifest 的 `os.replace` 抛 WinError 5 退出；具体占用进程尚未确认。新增统一 `atomic_replace`，JSON 和 checkpoint 均使用：只对 Windows 错误码 5/32/33 重试，最多 16 次尝试、累计等待 11.55 秒；指数退避从 50ms 到 1s。保留同一个已刷盘临时文件，不先删除目标、不降级成非原子覆盖。持续失败仍抛出异常，其他错误立即失败。首次冲突和恢复均记录日志。

测试覆盖瞬时／永久冲突、非 Windows 错误不重试、原内容保持、临时文件清理、checkpoint 共用逻辑，以及实际 Windows 不允许删除共享的文件句柄在释放后提交成功。额外执行 1,000 次真实原子替换，遇到两次实际 WinError 冲突，均一次重试后恢复。相关完整回归：116 tests、30 subtests 通过。

恢复前验证源码变化仅限 config.py/network.py 的 IO 路径，旧／新源码、摘要、plan/state 和 475 个已提交 episode 的数量保存在 `output/az_m5_experiment/io_fix_resume_audit.json`。显式迁移运行摘要后恢复，未修改 checkpoint、标签或游戏机制；旧的 `round_failed` 标记保留，因此 seed 42 第二轮不会晋级，即使验证改善。第一轮已晋级的模型不受影响。评估缓存绑定代码摘要，旧摘要缓存仍保留，必要时会重新评估而非静默复用。


## Reward v2：当前限定范围验收完成

40 HP、seeds 42/43、各两轮、各 500 场测试已结束。四项网络／搜索相对初始模型的胜率与效用增益 CI 均为正，当前 spec v0.2 门槛通过。旧 v1 未达标报告保持独立。最终网络和搜索均满胜率，但搜索平均少保留约 4.64 HP，且网络尚未超过固定规则的保血表现。文件与统计复算通过；完整结果、限制和后续诊断见 [AZ_HP_V2_RESULTS.md](AZ_HP_V2_RESULTS.md)。
