## 最新修复：原生续跑与显式截断样本（2026-10-19）

原生推理增加有界token哈希缓存和可选叶评估重复率诊断；250ms串行ABBA实测平均模拟次数97.4→101.4，深度2.665→2.699，叶输入重复率12.7%。严格校验保留，隔离DLL测试，107项回归通过；口径、波动及复现见[实测报告](docs/NATIVE_TOKEN_CACHE_20261019.md)。

另修复 SEEKER_STRIKE 击杀后仍请求选择，以及 EVIL_EYE 第二段格挡丢失出牌身份导致 UNMOVABLE 翻倍不足（24→32）的问题；保留失败轨迹和逐字段差异日志。

本轮按用户要求收窄随机卡池：排除 `SPLASH`、`JACK_OF_ALL_TRADES`（无色生成）、`ENTROPY`（转化）和 `ALCHEMIZE`（药水→无色生成），包含各自升级版；当前为 **134 张基础牌／268 个含升级 token**。职业卡池生成的 DISCOVERY/STOKE 不会生成无色 SPLASH，保留。冻结验证保留 224 个未受影响配方及缓存，替换并重新冻结 72 个；原始 296 配方、8 场训练缓存与 state 完整归档于本轮 `.control/before-splash-exclusion/`。由于训练尚未发生第一次更新，沿用原 initial.pt 重算新验证基线；旧训练配方不匹配新卡池生成器，不混用。迁移记录 `splash-exclusion-migration.json`。

充能球价值投影已补齐，暗黑球专项 25 决策／24 个带球帧通过实机与分支一致性检查；伙伴状态仍明确拒绝。此修复不扩大上述正式卡池。

TEAR_ASUNDER 的保留根历史重复计数也已修复：计算变量读取捕获时的根历史，加本分支预测历史，避免实机推进后被重复计入；固定 TUNNELER_WEAK 配方整场 28 决策通过。

修复 CATASTROPHE 连续出牌时 live 先推进导致预测读取失效的问题：先推进预测分支，再执行已解析的 live 动作。修复 TUNNELER 的 Burrowed 破盾时序：在破盾 hook 内立即眩晕、移除能力和清除格挡，取消延迟历史补偿。固定失败配方分别通过 16、44 决策整场一致性检查。

达到 40 回合／100 决策护栏时，显式记录 `time_limit`、原始轨迹 `complete=false` 和 V7 超限评分。按用户后续选择，训练搜索的截断样本也进入回放：样本记录 `truncated=true`，最后一步 `terminalAfter=false`，不伪装胜利或死亡；验证仍不得进入训练。回放兼容标记为 `v7-bounded-episode-v1`，报告记录 `collection_truncated`。模拟或数据一致性异常依然立即失败。验证汇总新增 `time_limit_rate`，验证进度单位为 `evaluated_fights`。NIBBITS 固定配方 100 决策复现得分 −0.61765625；回归测试区分验证超限和训练截断准入，检查预算边界及奖励不能被篡改。

原正式运行沿用 `output/az_native_ic138_w4_20261019_174426/`，不重置初始模型。来源变更的缓存只在逐场复核后显式迁移，旧文件和断点备份保留在相邻 `.control/before-*-fix/`；各次迁移记录及后台日志同目录。实时进度为 `.control/progress.json`，随产物落盘更新。

## 原生 MCTS 配置传递与缓存续跑（2026-10-19）

本轮初始验证遇到 STRATAGEM 选牌组合缺失：专用 profile 仅放入 policy，没有传给求解器构造参数，实际仍使用默认 Beam 的选牌限额。补齐参数后，失败配方整场 12 决策通过，首个选择覆盖全部 37 个语义组合；40 项相关测试通过。已有 38 场在修复版本重验，编码输入、动作和奖励全部相同；保留旧缓存备份并迁移来源指纹，加上修复配方共 39 场可续用。初始模型未重置，仍在初始验证阶段，尚未发生训练更新。证据：`output/native_stratagem_fixed_20261019/`、`output/native_stratagem_cache_revalidation_20261019/`；迁移记录在本轮 `.control/profile-fix-migration.json`。

## 正式原生采集支持 4 worker 并发（2026-10-19）

通用原生后端 `native-generic-collection-v1` 已接入 ALL runner 的 `--workers 4`；支持 1–4 个并发进程，默认仍为 1。每个进程有独立任务、日志、Godot 用户目录；先串行构建，再并发执行。`backend.fights_per_worker` 仍表示单个进程连续采集的场数，不是并发数。冻结验证也复用该并发执行器，学习者和冠军机制保持原有行为。

完整战斗继续逐场原子缓存。失败后等待同批在途 worker 结束，保留并校验成功场次，不再派发下一批；`--resume` 只补采缺失战斗。相同来源／模型／配方／搜索设置下，可在续跑时调整 worker 数；不会放宽旧缓存的来源校验。进度位于对应采集目录的 `progress.json`，包含 workers、已完成、缓存命中、新增、待采与异常；分进程日志在 `workers/batch-*/worker.log`。每个 worker 保留 120 秒超时及超时清理子进程机制。不要对同一个输出目录同时启动多个 runner，也不要在采集期间重建共享原生二进制。

启用方法：在原有通用原生训练命令后添加 `--workers 4`；失败续跑使用相同输出目录和原配置，再加 `--resume --workers 4`。其他训练参数不变，现有示例配置没有自动替换成全卡池正式训练配置。

验证：85 项相关 Python 测试通过（包含 1/4 worker 下的初始化、更新、验证失败恢复及冠军保留），4-worker CLI preflight 通过。正式采集代码的真实验收完成 4 场／95 决策，含构建耗时 17.41 秒；新建后端重读缓存未启动任何 worker，原战斗文件内容与修改时间不变。产物：`output/native_parallel_entry_20261019/`；复现脚本：`scripts/check_native_parallel.py`。本轮没有启动自进化。

## 逐场缓存续跑与原生采集测速（2026-10-19）

完整战斗逐场原子保存，失败后验证并复用已完成场次；未完成的那场重采。新增缓存命中／新增／待采／损坏统计及 `backend.fights_per_worker` 小批量复用配置。4 个固定配方实测：每 worker 1 场耗时 45.22 秒，2 场耗时 30.36 秒；双场组搜索阶段约 188 次模拟/s，端到端约 120 次/s。故障注入后前两场文件不变、只补采剩余两场；全缓存重读约 0.108 秒、零 worker 启动。82 项相关测试通过。搜索路径不同，结果仅作当前吞吐样本。未启动自进化、更新模型或修改正式训练配置。详见 [缓存与测速报告](docs/NATIVE_COLLECTION_CACHE_SPEED_20261019.md)。

## 单人卡池修复、升级牌与新种子回归（2026-10-19）

已修复动态费用投影、召唤后实体顺序及外部 MCTS 失败诊断；按原生元数据排除 17 张多人专用卡，剩 138 张战士／无色卡，并支持一级升级。新增选牌中间态与完整后继的严格边界校验。单人范围内 7 个固定失败配方、7 个对应升级配方、8 个新随机配方累计完成 22 场、424 个有效决策；失败尝试及各场来源均保留。137 项 Python 回归、C# CollectionContracts smoke 和真实 worker 的升级多人卡拒绝检查通过。没有更新模型或启动正式训练。详见 [修复与回归报告](docs/NATIVE_SCOPE_REPAIR_20261019.md)。

## 前轮验收：扩大卡池发现的整场问题（2026-10-19）

原生目录包含 155 张战士／无色卡；旧清单 76 种遭遇中有 2 个 ID 在当前版本不存在。其余 74 种遭遇的随机卡组开局全部通过，但固定抽取的 8 场完整采集仅 1 场成功、7 场因费用字段、合法动作、召唤后实体顺序或搜索动作链问题失败。失败数据未进入回放，仅保留 11 个合格决策。42 项协议／价值网络回归通过；未更新模型、未启动正式训练。下一步应修复这些问题，不能把此前小卡池验收外推为全卡池支持。详见 [验收报告](docs/NATIVE_SCOPE_AUDIT_20261019.md)。

## 价值网络接入 C# MCTS（2026-10-19）

通用原生后端现支持 `heuristic`、`learned`、`mixed` 三种模式。学习／混合模式读取模拟分支的公开特征，在完整叶子调用同一采集模型的价值头；混合权重是学习价值占比，终局始终使用原生奖励。配置及命令行覆盖会传到 worker，并进入轨迹、缓存及回放兼容性校验。根先验、持续学习者、独立冠军和断点恢复保留。

新增真实／分支特征对账、分支／真实根不变检查、价值调用与实际回传统计，以及终局、选牌、超时和异常值测试。默认仍为手写 rollout；本轮只做有界工程验收，未启动正式训练。模型编码及参数结构与原通用 Transformer 兼容；不同搜索配置的数据不能混用。三种模式的准确语义、预算和覆盖限制见 [C# MCTS 价值叶子说明](docs/NATIVE_VALUE_MCTS_20261019.md)。

本轮 130 项 Python 测试和 C# ReplaySearch smoke 通过；三模式各两场采集加 8 场冻结验证，共 223 个决策检查通过。混合样本完成两步工程更新及精确恢复，实际缓存续跑未修改已有产物，冠军保留。这些是接线与恢复证据，不是学习增益结论。

## 历史进度：通用原生状态／合法动作 → Transformer（2026-10-19）

新增 `native-generic-collection-v1` 路径，直接使用现有采集模组的公开观察及 C# MCTS 合法动作、访问次数和终局奖励。卡牌／遭遇 ID 是课程清单数据，Python 不再逐张注册或重写效果；动态动作候选直接由 Transformer 评分。通用字段编码、模型与回放有独立版本，旧权重不混用，旧后端保留。

已接入现有 ALL runner，保留最新学习者采集、独立冠军、逐场缓存、按遭遇分层回放、优化器和 RNG 的逐更新恢复。独立冻结 8 个验证配方；有界验收已完成 4 场采集、8 场验证及两步工程更新与精确恢复，未启动正式训练。覆盖升级、能力、多选消耗及多怪；不是全部内容支持声明。

初始版仅提供真实决策根先验，树内使用 C# rollout 与均匀先验；价值叶子接入见上方最新进度。配置 `configs/az_native_generic_v1/` 是接线示例，搜索预算以毫秒计。协议、数据一致性、恢复范围、限制和验证证据见 [通用原生协议说明](docs/NATIVE_GENERIC_PROTOCOL_20261019.md)。

## 历史进度：C# 后端扩展并接入 ALL 生命周期（2026-10-19）

已扩展至六种未升级卡牌（基础三牌 + IRON_WAVE／POMMEL_STRIKE／TWIN_STRIKE）与 BYRDONIS_ELITE／NIBBITS_WEAK 两个遭遇，复用已有卡牌效果描述、实体编码和 Learner。冻结独立随机验证集 24 个配方（每遭遇 12 个），训练／验证种子域分离。通过配置选择 C# 后端，保留最新学习者采集、逐场缓存、逐更新恢复与独立冠军判定；新增基线验证失败恢复。

本轮 4 场采集 + 24 场验证共 265 次状态／动作检查通过；41 条训练样本通过两步工程更新和精确恢复。实际续跑复用全部 28 场，冠军未变；88 项 Python 测试与 C# ReplaySearch smoke 通过。原生费用及伤害／格挡／抽牌基础值与旧 Python 卡牌描述逐项核对；修复大种子上限与 V7 浮点运算次序造成的校验误报。没有启动正式训练。该后端仍是完整信息 rollout 教师，尚不支持学习价值叶子、升级／选牌／多怪等机制，也不是全部 76 遭遇替换。配置、预算单位、限制及验收见 [C# 后端 v2 说明](docs/NATIVE_BACKEND_V2_20261019.md)。

## 历史进度：C# 原生采集桥接试点（2026-10-19）

已复用 `sts2_datacollection/SlayTheModel` 的 C# Combat Solver／ReplayMcts，打通 BYRDONIS + 未修改打击／防御／痛击的原生采集 → 独立实体回放 → 现有 Learner。18 场固定开局对照完成，281 次状态／动作核对通过；学习先验组 102 条样本通过两步更新和优化器／RNG 精确恢复，冠军权重未改。原生 UCT／学习先验 PUCT 分别约 716／161 次模拟每秒，三组均为 3/6 胜，尚无显著强度增益。适配及相关回归 61/61 通过；完成对局续采复用检查通过。

这是完整信息 rollout 教师、公开特征学生的受限工程试点，使用独立数据契约，不能混入旧 observable replay。没有启动正式训练、打开测试集或迁移全部遭遇；正式 ALL runner 默认后端未改。入口 `scripts/check_native_collection.py`，范围、奖励／动作差异、复现方式及结果见 [原生采集桥接报告](docs/NATIVE_COLLECTION_PILOT_20261019.md)。

## 历史进度：动态 MCTS 性能分析与精确缓存（2026-10-18）

已按要求停止 256 次模拟后台对照，保留 103 场结果，未重启实验或训练。固定状态剖析发现重复实体编码占约一半耗时，Transformer 推理约占 6%。加入单次搜索内、最多 256 条的公开状态编码／预测缓存；键包含合法动作掩码，保留契约检查，不跨搜索或模型更新复用。开局 32 次模拟编码次数从 221 降至 33；256 次模拟学习价值耗时从 15.76 秒降至 8.44 秒，完整搜索树一致。固定状态计时不代表整场吞吐，旧无网络 MCTS 的速度不适用于此路径。详见 [性能分析与复现说明](docs/AZ_SEARCH_PERFORMANCE_20261018.md)。

## 历史进度：消耗历史升级修复与预算／深度诊断（2026-10-18）

骑士精英 Dampen 解除可将已消耗的 Cinder 升级。消耗历史现按事件快照恢复，不再用历史牌名查找当前消耗堆；保留事件归属与本回合消耗条件，当前牌堆不改。增加保存状态回归。搜索诊断额外记录每次搜索的实际平均／最大路径深度，区分模拟预算与深度上限；支持 manifest 指定对照组和深度上限。256 模拟预算及仅提高深度上限的试验使用同模型、同冻结配方，独立目录；不启动训练。

## 历史进度：VIGOR 续执行修复与搜索对照（2026-10-18）

修复已消耗 VIGOR 仍留在回合开始钩子队列、公开状态重建直接查力量字典而报错的问题。仅对继承空操作钩子的已移除力量恢复队列占位，不重新添加力量；缺失有状态钩子继续严格拒绝。原失败搜索可按原模型／种子重放通过，相关回归 37 项通过。

`scripts/run_search_value_comparison.py` 支持固定模型与配方的纯网络、学习价值 MCTS 8/32、混合价值 MCTS 8/32 五组诊断，无训练更新、无探索噪声。每场结果带摘要缓存，`progress.json`／`progress.log` 实时记录完成数，最终 `report.json` 给出配对效用差及区间。诊断仅使用训练侧配方，不打开测试集。五组真实双进程短程 smoke 与缓存续跑已通过。

## 历史进度：逐场采集缓存（2026-10-18）

ALL runner 将完成的战斗立即原子写入 `collection-cache/<轮次>/<job_id>.json`，并行 worker 也在返回结果前落盘。同一运行使用 `--resume` 时复用已完成战斗，只重跑缺失／失败的战斗；并行批次中单场失败不会丢失其他 worker 已落盘的结果。整轮全部成功才进入更新，未结束的战斗不作为训练样本。缓存保存完整轨迹与终局标签，不是战斗中途断点。

缓存绑定源码／配置／协议、采集模型摘要、配方、种子、搜索参数及战斗上限，并验证内容摘要；不匹配或损坏时明确报错，不静默混用。worker 数量可调整。源码或学习率改变仍受原有严格恢复检查约束，不能把旧实验直接当作同一运行续跑；历史失败轮未落盘的战斗无法追溯恢复。缓存保留在输出目录，便于恢复和审计，需预留完整轨迹的磁盘空间。

学习率保持原配置（最近实验为 `3e-4`），本次不启动训练。缓存专项与 runner／采集背压回归 **32/32 通过**，恢复回归 **6/6 通过**；覆盖真实双进程缓存、失败批次成功对局保留、仅重采缺失对局、配置漂移和文件损坏拒绝。

## 历史进度：MCTS 价值估计与采集模型可选（2026-10-18）

MCTS 非终局叶子支持 `heuristic`（手写风险评分）、`learned`（价值网络）、`mixed`（两者线性混合）三种模式。`--value-mix` 是混合时学习价值的权重，范围 0～1；胜负／时间上限仍按原有 V7 搜索终局规则结算，不用网络覆盖。默认继续 `heuristic`，未改搜索预算、牌池或验证晋级规则。

`--collection-model learner` 使用上一轮最新已提交学习者采集，即使候选未晋级也更新下一轮的采集模型；`champion` 保留原行为且仍为默认值。每轮采集冻结权重，冠军独立保留供配对晋级和最终评估。模式、混合权重、采集来源及 checkpoint 摘要写入报告；恢复禁止中途切换，Replay 拒绝混入不同叶子模式或不同混合权重的数据。

专项及相关回归 **315/315 通过（113.63 秒）**，覆盖三种回传模式、混合端点、终局优先、真实 spawn 一致性、回放隔离、CLI 参数和学习者／冠军分离及精确恢复。

本次在独立工作树开发和测试，未启动新训练或正式诊断；正在运行的 v3 所在目录、源码、配置和输出未改动。原训练目录暂不拉取这些改动，待当前运行结束后再同步。参数与使用示例见 [运行手册](docs/AZ_ALL_XS_RUNBOOK.md#10-mcts-叶子估值与采集模型选择)。以下为历史记录。

## 最新进度：分层随机采集与冻结验证集（2026-10-18）

默认每轮 **76 种遭遇 × 4 场 = 304 场**。每场按独立坐标生成随机卡组和战斗种子，下一轮换新组合；不是反复训练固定卡组。验证集在独立种子区间生成 **304 个配方（每种遭遇 4 个）后冻结**，用于配对比较。最终测试集原有 64 个配方保持不变，未评估。

已移除 64 场限制及旧配方坐标循环：支持每轮 1～1024 场、最多 1024 轮，坐标不回绕，支持范围内战斗种子不碰撞。默认 8 轮共 2432 个训练开局与 304 个验证开局的构造／编码预检全部通过。持续学习与冠军分离、ALL 遭遇分层回放继续生效。

隔离副本专项及相关回归 **89/89 通过**。本次只改采样与验证方案，MCTS=8、每轮更新16次、batch64等其他训练参数保持原值；没有启动训练。新协议须用新目录，不能续跑旧协议结果；历史分数不能与新验证集直接比较。见 [操作手册](docs/AZ_ALL_XS_RUNBOOK.md)。以下为历史记录。

## 最新进度：持续学习与训练诊断（2026-10-18）

runner 升级为 v3：持续学习模型与冠军分离，跨轮保留权重、AdamW 和 RNG，候选未晋级也继续学习；冠军仍独立负责采集、晋级比较和最终评估。ALL 回放按遭遇均匀分层，避免高频遭遇占据大部分样本。

新增只读价值网络诊断（MSE／MAE／相关性／常数基线／终局分组）与训练侧配对纯网络、MCTS 8/32 诊断（效用／延迟／动作覆盖率）。只接受训练数据，最终测试集保持封存。详见 [v3 操作与诊断手册](docs/AZ_ALL_XS_RUNBOOK.md)。

v3 必须使用新训练目录，不能直接 resume 历史 v2 正式结果。默认更新次数、搜索预算、模型和牌池不变；本次仅实现改进并运行测试夹具，没有启动新训练。专项与相关回归 **75/75 通过**，并在不含用户未提交修改的隔离副本中复验。以下为历史记录。

## 最新进度：自进化训练准备修复（2026-10-18）

已完成 runner v2 的配置生效、整场 MCTS 契约、更新级断点恢复和冠军保留；**本次没有新增卡牌，没有启动正式训练，没有评估最终留出集**。当前准入保持 **146/151 张牌（战士 87、无色 59）和 76/81 种遭遇**，尚不能宣称支持任意卡牌、任意怪物。

默认参数现在实际生效：8 轮 × 48 场、每轮 16 次更新、batch 64、MCTS 8、value weight 0.1；采集与验证均为 40 回合／400 决策。召唤主敌、Hex 清理／升级、复活、逃跑及连续召唤槽位的公开状态契约已修复。候选只有在完整验证集上相对冠军的配对 95% 区间下界大于 0 才晋级；否则保留冠军。

更新级恢复保存权重、AdamW、采样 RNG 和 Torch RNG，使用 `state.json` 恢复；旧 checkpoint／Replay 与旧 runner 输出不能直接续跑。无更新的整场 MCTS 检查覆盖 64 个验证配方＋76 个准入遭遇；具体结果、测试证据和边界见 [修复报告](docs/AZ_TRAINING_READINESS.md)。

大范围回归仍有 **20 项历史失败／错误**，已在修复前提交复现（旧 T4 冻结工件与旧 EXPANSION_CONTENT 契约）；详见修复报告，不能宣称全仓测试全绿。新 runner 最终专项 **55/55**、引擎回归 **356/356**、整场 MCTS **140/140** 通过。

**下一步：先按 [运行手册](docs/AZ_ALL_XS_RUNBOOK.md) 用新目录做短程 smoke，经确认后再启动正式训练。** 不要从旧 v1 结果直接续训，也不要把工程契约通过当作学习效果提升。以下章节保留历史进度，以本节和修复报告为准。

## 最新机制接入：战士／无色状态、续接与原生生成池（2026-10-17）

本批新增 **50 张及升级版**，累计 **120/151**（战士 **83/87**、无色 **37/64**），剩余 **31**。补齐基础状态、选择后的结算、检索与牌堆消耗、嵌套自动打出、触发能力、实例成长，以及实体编码、动态动作和 MCTS 重建。

战士原生战斗候选 **79 个全部闭合**；Jackpot、Infernal Blade、Discovery、Calamity 保留完整原生池。**Splash、Jack of All Trades、Entropy 暂缓**，后两者依赖含 Splash 的无色生成／变换池，不做支持性裁剪。

[本批报告](docs/AZ_IRONCLAD_COLORLESS_FOUNDATION.md) · [逐牌清单](docs/IRONCLAD_COLORLESS_COVERAGE.md) · [原生池审计](docs/ironclad_colorless_generation_pools.json) · [测试证据](docs/ironclad_colorless_foundation_evidence.json)

必要测试 **5,111 项全部通过**，失败／错误／跳过均为 0；源码稳定、用例无遗漏和证据摘要校验通过。V4 内容／schema 与旧权重和 Replay 不直接兼容。没有启动训练或使用最终留出；后续继续按实际 network 整场 V7 效用验收。本批只验证工程机制，不宣称策略效用提升。下一步盘点剩余 31 张的独立机制，战士剩余 Corruption、Demonic Shield、Feed、Tank。下文为历史进度。

## 最新机制接入：战士／无色即时效果与公开计数（2026-10-17）

本批新增 **20 张及升级版**，累计 **70/151**（战士 50、无色 20），待接入 **81**。覆盖普通消耗、抽牌、随机攻击、X 费、先天、公开条件伤害／格挡，以及 Battle Trance／Stone Armor；同步补齐实体编码、动态合法动作和 MCTS 重建。

[本批报告](docs/AZ_IRONCLAD_COLORLESS_SIMPLE.md) · [逐牌清单](docs/IRONCLAD_COLORLESS_COVERAGE.md) · [测试证据](docs/ironclad_colorless_simple_evidence.json)

必要测试 **3,849 项通过**。新内容与 schema 升级 V3，旧权重和 Replay 不直接兼容。下一批优先补 Weak 等基础状态依赖，再处理延迟触发、回手和实例成长。本次未启动训练或使用最终留出；后续继续按实际 network 整场 V7 效用验收。下文为历史进度。

## 最新机制接入：战士／无色持久能力（2026-10-17）

新增 Barricade、Rage、Feel No Pain、Demon Form、Fasten、Eternal Armor 及升级版，已接通 **50/151**（战士 37、无色 13），剩余 **101**。内容升级为 `ironclad-colorless-powers-v2`，补齐公开能力状态、实体机制与 Defend 标签、动态动作、粒子与 MCTS 重建；修复重复 Barricade 叠加及回合末格挡对 Boss 伤口／V7 风险的影响。

[本批报告](docs/AZ_IRONCLAD_COLORLESS_POWERS.md) · [覆盖清单](docs/IRONCLAD_COLORLESS_COVERAGE.md) · [测试与摘要证据](docs/ironclad_colorless_powers_evidence.json)

必要测试 **3,264 项通过**，源码与证据摘要校验通过。本次未训练、未使用最终留出集；下一批为 Dark Embrace／Rupture 的延迟触发与续接。后续仍按 network 整场 V7 效用验收。下文较早批次计数为历史记录，旧权重与 Replay 不能直接用于新 schema。

# STS2 RL Agent

A reinforcement learning agent for **Slay the Spire 2**, built on a high-performance headless combat simulator and a Gymnasium training environment. Includes a C# bridge mod for connecting the trained agent to the real game.

## 战士与无色牌内容扩展（2026-10-17）

按最新范围完成 151 张卡牌的分层盘点，并接通前两批 17 张基础牌及升级版。当前实体／动态动作／MCTS 链路覆盖战士 33/87、无色 11/64，合计 **44/151**；其余 **107 张仍待实现，不能按全覆盖使用**。修复参考工厂重复实例 ID、Dominate 跨回合力量历史及新增抽牌的已知顺序恢复。新内容版本 `ironclad-colorless-batch1-v1`，旧冻结实验不可直接续跑。

- [逐牌覆盖清单](docs/IRONCLAD_COLORLESS_COVERAGE.md)
- [分批实现、测试与剩余工作报告](docs/AZ_IRONCLAD_COLORLESS_EXPANSION.md)

本次未启动训练，未使用最终留出集；后续仍按实际 network V7 效用验收。当前优先继续补齐持久能力和触发器，再处理逐卡变化、复杂选择与自动出牌。以下为历史阶段记录。

## T4 多 seed 短程确认已完成（2026-10-17）

value=0.1、MCTS=8 的新 seed 44/45 两轮确认及证据复核完成，共 720 条轨迹、16 次更新。最终冠军 network 效用分别 0.322412 / 0.123696，均通过相对初始化的增益门槛，但第二轮均未晋级。Boss 各 84 场验证全部死亡；seed 45 采集到一条合法获胜后缀，却未在第二轮四次更新中抽到。下一步优先版本化成功轨迹的训练覆盖，正式训练未启动。详见 [确认结果与建议](docs/AZ_TRANSFORMER_T4_VALUE01_CONFIRMATION_RESULTS.md)。以下章节保留历史进度。

## T4 最新状态与多 seed 确认（2026-10-17）

T4 两轮 smoke 已完成，第一轮冠军 network 效用 0.252700；第二轮候选退步，未晋级。单因素消融独立审计通过：value=0.1 为 0.235308、search=32 为 0.237246，均改善失败第二轮的 0.152759，但均未超过第一轮冠军，Boss 仍未通过。详见 [消融结果](docs/AZ_TRANSFORMER_T4_ABLATION_RESULTS.md)。以下旧章节保留阶段历史，以本节为当前状态。

用户决定跳过 value=0.1/search=32 组合补测，采用 value=0.1、MCTS=8 开展全新 seed 44/45 的 S 两轮短程确认。每 seed 每轮 135 整场＋45 后期、4 次更新，batch 48/16，CPU 单线程；总计 720 条记录、16 次更新。课程与 network 效用门槛保持不变。新配置 configs/az_transformer_t4_value01_confirmation_v1/execution.json，入口 scripts/run_t4_value_confirmation.py；实时进度 T4_VALUE_CONFIRMATION_PROGRESS.md。没有授权或启动正式训练，不自动打开最终留出。

## Transformer T3 当前进度（2026-10-17）

V7 S 两轮 smoke 与正式 seed 42/43 各三轮已完成：正式采集 1,080 场、30,557 个决策、96 次更新。工程工件及最终评估已复算；两个 seed 均通过冻结的 network 终局效用增益门槛。

| seed | 最终测试初始效用 | 最终冠军效用 | 增益 |
|---|---:|---:|---:|
| 42 | −1.000000 | +0.325891 | +1.325891 |
| 43 | +0.171655 | +0.344832 | +0.173177 |

每 seed 最终测试 216 场。Boss 子集各 54 场全部死亡；未见组合、未见 ID 与通用质量尚未验收。冻结分层 bootstrap 出现零宽度，报告提供补充敏感性分析并明确其局限。V7 同时改变了奖励和搜索，不能据此归因为 Transformer 相对旧 MLP 的架构收益。

完整结果见 [T3 V7 结果报告](docs/AZ_TRANSFORMER_T3_V7_RESULTS.md) 与 [可复算结果摘要](docs/transformer_t3_v7_results.json)；修订背景见 [持续结束回合诊断](docs/AZ_TRANSFORMER_V7_DIAGNOSIS.md)。T4 当前审计进展与后续任务见下一节。当前无训练运行，不自动追加轮数或启动 M/L/XL。

## T4 / G2.3f 审计进度（2026-10-17）

已重放核对全部 594 场训练 Boss、21,933 个决策，并复跑冻结冠军的 188 场验证 Boss：两 seed 的 network 效用仍为 −1，但均没有只结束回合的战斗，也没有在可出牌时结束回合。固定规则策略在 540 场原训练配方中找到 2 场合法胜利；同一个可解案例中，seed 43 network 出现 7 次零格挡 Body Slam，说明仍有明确的出牌顺序问题。

自然第三形态已有 147 场、2,309 个决策，但所有 Boss 训练 value 标签都是 −1，缺少成功轨迹。798 项测试与 605 个源工件 / 6 条合法见证复算通过。详见 [G2.3f 审计报告](docs/AZ_TRANSFORMER_G23F_AUDIT.md)。下一步实现版本化自然后期课程、组合顺序搜索诊断及组合/ID 留出；T4 整体尚未完成，未启动新训练。

## T4 自然后期课程与留出冻结（2026-10-17）

已实现 `natural-late-course-v1`：8 个第二/第三形态、Burn 与 Purity 自然起点，支持完整合法前缀恢复、可重复采样、独立后缀采集/校验及现有实体 learner 数据接口。保留原始整场 HP 和预算；快照结果不参与整场验收。

冻结 48 train、256 validation、24 未见组合、24 完整 ID 留出配方；BLUDGEON 及升级版只在 ID 留出中出现，未来必须从全新模型开始。组合诊断复现 Armaments→Body Slam 的 5 对 0 伤害、Iron Wave→Body Slam 的 14 对 7；旧 seed 43 的 8 次搜索仍可选零格挡 Body Slam。822 项测试及独立证据复算通过。

详见 [T4 课程与留出报告](docs/AZ_TRANSFORMER_T4_COURSE.md)。验收入口继续采用 256 场实际 network V7 效用；本轮未启动新训练，新增学习增益未评估。新 runner 的课程混合比例与运行预算仍需在启动前冻结。

## T4 新运行编排（2026-10-17）

已实现并冻结 `transformer-t4-run-v1`：每轮 135 整场＋45 自然后期，batch 为 48＋16，均为 3:1；两类 Replay 分池、完整记录 FIFO、原子提交与摘要校验，最多常驻 16 条轨迹。恢复覆盖采集、参数＋AdamW 更新边界及逐场验证缓存。

S smoke 固定 seed 41 两轮、每轮 4 更新；正式 seed 42/43 各三轮、每轮 16 更新。晋级与最终冠军增益均采用 network V7 效用；正式必须先通过 smoke，双冠军共同冻结后才评估 192 场初始/最终留出战斗。308 项必要测试与冻结校验通过，**本轮未启动新训练**。入口与预算详见 [T4 编排报告](docs/AZ_TRANSFORMER_T4_RUNNER.md)。

## Architecture

```
+-----------------------------------------------------------------------+
|  Headless Python Simulator (sts2_env/)                                |
|                                                                       |
|  +----------------+  +----------------+  +---------------------------+|
|  | Core Engine    |  | Game Content   |  | Gym Environments          ||
|  | combat.py      |  | 577 cards      |  | combat_env.py  (single)  ||
|  | creature.py    |  | 260 powers     |  | run_env.py     (full run)||
|  | hooks.py       |  | 121 monsters   |  | observation.py (131-dim) ||
|  | damage.py      |  | 290 relics     |  | action_space.py(61/100)  ||
|  | rng.py         |  | 63 potions     |  | reward.py                ||
|  +-------+--------+  +-------+--------+  +-----------+--------------+|
|          |                    |                        |              |
|          +--------------------+------------------------+              |
+-----------------------------------------------------------------------+
           |                                             |
           v                                             v
+---------------------+                  +--------------------------+
| Training Pipeline   |                  | Bridge to Real Game      |
| MaskablePPO (SB3)   |                  | bridge_mod/ (C#/Godot)|
| train_combat.py     |------model------>| agent_runner.py (Python) |
| train_full_run.py   |                  | TCP JSON protocol        |
+---------------------+                  +--------------------------+
```

## Project Stats

| Metric | Value |
|--------|-------|
| Source files | 133 Python + C# |
| Lines of code | ~50,000 |
| Test functions | 408 |
| Cards implemented | 577 |
| Powers implemented | 260 |
| Monsters implemented | 121 |
| Relics implemented | 290 |
| Potions implemented | 63 |
| Playable characters | 5 (Ironclad, Silent, Defect, Necrobinder, Regent) |
| Simulation speed | ~1,200 combats/sec, ~28,000 steps/sec |
| Combat win rate (trained PPO) | ~92% (Act 1 Ironclad) |

## Quick Start

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **pip** (included with Python)
- For training: a CUDA-capable GPU is recommended but not required
- For real-game bridge: .NET 9 SDK, Godot 4.5.1 Mono, Slay the Spire 2 (Steam)

### Install

```bash
git clone <repo-url>
cd sts2-rl-agent

# Core simulator only
pip install -e .

# With training dependencies (PyTorch, SB3, sb3-contrib)
pip install -e ".[train]"

# With dev dependencies (pytest)
pip install -e ".[dev]"
```

### Run Benchmark

Measure simulation throughput with random actions:

```bash
python scripts/benchmark.py
```

Expected output on a modern CPU:

```
Episodes:       1000
Total steps:    28101
Time:           0.78s
Episodes/sec:   1276
Steps/sec:      28101
```

### Play a Full Run in the Terminal

Start from the opening event, choose map nodes, fight combats, collect rewards,
and continue the run from the command line:

```bash
python -m sts2_env.cli.play_run
```

Useful options:

```bash
python -m sts2_env.cli.play_run --character Silent --seed 123 --ascension 0
```

Without `--character`, the CLI asks you to pick a character first. Inside the
game, enter the number beside an action. Shortcuts: `a` takes the first listed
action, `c` confirms or skips, and `q` quits.

### Play a Full Run in the Browser

Run the local web UI:

```bash
python -m sts2_env.web.play_run --port 8765
```

Then open <http://127.0.0.1:8765/>. The browser UI uses the same `RunManager`
logic as the terminal version, but presents the run as clickable screens for
map, combat, events, rewards, shop, rest sites, treasure, and boss relics.

### Train a Combat Agent

Train a MaskablePPO agent on single-combat encounters:

```bash
python scripts/train_combat.py \
    --total-timesteps 500000 \
    --n-envs 4 \
    --output-dir output/combat_ppo
```

Key flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--total-timesteps` | 500,000 | Total environment steps |
| `--n-envs` | 4 | Parallel environments (use CPU cores) |
| `--lr` | 3e-4 | Learning rate |
| `--batch-size` | 256 | Minibatch size |
| `--n-steps` | 2048 | Steps per rollout per env |
| `--output-dir` | output/combat_ppo | Where to save models and logs |

### Train a Full-Run Agent

Train an agent that handles an entire run (combat + map + rewards + events):

```bash
python scripts/train_full_run.py \
    --total-timesteps 1000000 \
    --act-count 1 \
    --n-envs 4 \
    --output-dir output/run_ppo
```

The `--act-count` flag controls how many acts per episode (1 = Act 1 only, 3 = full game).

### Connect to Real Game

After training, run the agent against the actual game:

1. Build and install the bridge mod (see [docs/MOD_BUILD_GUIDE.md](docs/MOD_BUILD_GUIDE.md))
2. Start Slay the Spire 2
3. Run the agent:

```bash
python -m sts2_env.bridge.agent_runner \
    --model-path output/combat_ppo/best_model/best_model.zip \
    --verbose
```

See [docs/AGENT_USAGE_GUIDE.md](docs/AGENT_USAGE_GUIDE.md) for details.

## Project Structure

```
sts2-rl-agent/
|-- pyproject.toml                 # Package config, dependencies
|-- scripts/
|   |-- benchmark.py               # Throughput benchmark
|   |-- train_combat.py            # Combat-only training
|   +-- train_full_run.py          # Full-run training
|
|-- sts2_env/                      # Python package (headless simulator)
|   |-- core/                      # Combat engine
|   |   |-- combat.py              # CombatState (turn flow, card play)
|   |   |-- creature.py            # Creature (HP, block, powers)
|   |   |-- hooks.py               # Central hook dispatch (~25 hooks)
|   |   |-- damage.py              # Damage/block calculation pipelines
|   |   |-- enums.py               # CardId, PowerId, IntentType, etc.
|   |   |-- constants.py           # Game constants from decompiled source
|   |   +-- rng.py                 # Seeded RNG
|   |
|   |-- cards/                     # Card definitions (577 cards)
|   |   |-- base.py                # CardInstance class
|   |   |-- effects.py             # 12 composable effect primitives
|   |   |-- registry.py            # Card ID -> effect dispatch
|   |   |-- ironclad.py            # Ironclad cards
|   |   |-- silent.py              # Silent cards
|   |   |-- defect.py              # Defect cards
|   |   |-- necrobinder.py         # Necrobinder cards
|   |   |-- regent.py              # Regent cards
|   |   |-- colorless.py           # Colorless cards
|   |   +-- status.py              # Status/Curse cards
|   |
|   |-- powers/                    # Status effects (260 powers)
|   |   |-- base.py                # PowerInstance base class
|   |   |-- common.py              # Core powers (Strength, Vulnerable, etc.)
|   |   |-- damage_modifiers.py    # Damage pipeline hooks
|   |   |-- block_modifiers.py     # Block pipeline hooks
|   |   |-- card_play_effects.py   # On-card-play triggers
|   |   |-- damage_reactions.py    # Thorns, reactive powers
|   |   |-- duration.py            # Tick-down / duration powers
|   |   |-- turn_effects.py        # Start/end of turn triggers
|   |   +-- monster.py             # Monster-specific powers
|   |
|   |-- monsters/                  # Monster AI (121 monsters)
|   |   |-- state_machine.py       # MoveState, RandomBranch, ConditionalBranch
|   |   |-- intents.py             # Intent types
|   |   |-- act1_weak.py           # Act 1 weak encounters
|   |   |-- act1.py                # Act 1 monsters
|   |   |-- act2.py                # Act 2 monsters
|   |   |-- act3.py                # Act 3 monsters
|   |   +-- act4.py                # Act 4 monsters
|   |
|   |-- relics/                    # Relic effects (290 relics)
|   |-- potions/                   # Potion effects (63 potions)
|   |-- orbs/                      # Orb mechanics (Defect)
|   |-- characters/                # Character starting states
|   |-- encounters/                # Encounter definitions (88 encounters)
|   |-- events/                    # Event decision trees (68 events)
|   |-- map/                       # Map generation algorithm
|   |-- run/                       # Full-run state management
|   |   |-- run_manager.py         # Run loop (map -> room -> rewards)
|   |   |-- run_state.py           # Persistent run state
|   |   |-- rewards.py             # Card/gold/potion rewards
|   |   |-- shop.py                # Shop system
|   |   |-- rest_site.py           # Rest site (heal/upgrade)
|   |   +-- events.py              # Event handler
|   |
|   |-- gym_env/                   # Gymnasium environments
|   |   |-- combat_env.py          # Single-combat env (Discrete(61))
|   |   |-- run_env.py             # Full-run env (Discrete(100))
|   |   |-- observation.py         # State -> 131-dim float32 vector
|   |   |-- action_space.py        # Action encoding + masking
|   |   +-- reward.py              # Reward shaping
|   |
|   +-- bridge/                    # Real-game connection
|       |-- client.py              # TCP client
|       |-- protocol.py            # Message types, phases
|       |-- state_adapter.py       # Game JSON -> observation vector
|       +-- agent_runner.py        # Main agent loop
|
|-- bridge_mod/                    # C# Bridge Mod (Godot project)
|   |-- STS2BridgeMod.csproj       # Build config (Godot.NET.Sdk/4.5.1)
|   |-- MainFile.cs                # Entry point, Harmony patches
|   |-- BridgeServer.cs            # TCP server
|   |-- RlAutoSlayer.cs            # AutoSlay-based automation
|   |-- RlCombatHandler.cs         # Combat decision handler
|   |-- RlMapHandler.cs            # Map navigation handler
|   |-- RlCardSelector.cs          # Card selection handler
|   +-- RlCardRewardScreenHandler.cs
|
|-- tests/                         # 14 test files, 408 test functions
|-- docs/                          # Documentation
|   |-- GAME_BRIDGE_REFERENCE.md   # Bridge architecture and protocol
|   |-- AUTOSLAY_BRIDGE.md         # AutoSlay-based bridge design
|   |-- GAME_SYSTEMS_REFERENCE.md  # Game mechanics reference
|   |-- CARDS_REFERENCE.md         # All 577 cards
|   |-- POWERS_REFERENCE.md        # All 260 powers
|   |-- MONSTERS_REFERENCE.md      # All 121 monsters
|   +-- RELICS_REFERENCE.md        # All 290 relics
|
|-- RESEARCH.md                    # Research notes and prior work
+-- DECOMPILED_ARCHITECTURE.md     # Decompiled C# architecture analysis
```

## Game Content Coverage

| Content Type | Game Total | Implemented | Coverage |
|-------------|-----------|-------------|----------|
| Cards | 577 | 577 | 100% |
| Powers (status effects) | 260 | 260 | 100% |
| Monsters | 121 | 121 | 100% |
| Relics | 290 | 290 | 100% |
| Potions | 63 | 63 | 100% |
| Encounters | 88 | 88 | 100% |
| Events | 68 | 68 | 100% |
| Characters | 5 + 2 | 5 | 100% (playable) |
| Acts | 4 | 4 | 100% |

## How It Works

### Two-Phase Approach

Following lessons from the STS1 RL community, this project uses a two-phase strategy:

1. **Headless Simulator** (for training): A pure-Python reimplementation of STS2 combat and run mechanics, verified against the decompiled C# source. Runs at ~1,200 combats/second -- fast enough for millions of training episodes.

2. **Bridge Mod** (for validation): A C# mod that hooks into the real game via Harmony, exposes state over TCP, and injects agent decisions. Includes 5-10x speed patches for faster real-game evaluation.

### RL Algorithm

- **MaskablePPO** from sb3-contrib (Stable Baselines 3)
- **Invalid action masking**: Each step, the environment provides a boolean mask indicating which actions are legal (playable cards, valid targets). Illegal actions are zeroed out before policy sampling.
- **Observation**: 131-dimensional float32 vector encoding player state, hand cards, pile summaries, and enemy state
- **Action space**: Discrete(61) for combat (end turn + 10 self-target + 50 targeted), Discrete(100) for full run

### Reward Design

**Combat environment:**
- Win: +1.0
- Loss: -1.0
- HP loss: small negative penalty (encourages efficient play)

**Full-run environment:**
- Win the run: +1.0
- Death: -1.0
- Optional shaping: small bonuses for floor progression and act completion

## Documentation

| Document | Description |
|----------|-------------|
| [README.md](README.md) | This file |
| [RESEARCH.md](RESEARCH.md) | Research notes, prior work, algorithm selection |
| [DECOMPILED_ARCHITECTURE.md](DECOMPILED_ARCHITECTURE.md) | Decompiled C# analysis for simulator |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guide, dev setup, adding content |
| [docs/SIMULATOR_ARCHITECTURE.md](docs/SIMULATOR_ARCHITECTURE.md) | Python simulator internal architecture |
| [docs/TRAINING_GUIDE.md](docs/TRAINING_GUIDE.md) | Comprehensive RL training guide |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | TCP bridge communication protocol |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Current known issues and limitations |
| [docs/MOD_BUILD_GUIDE.md](docs/MOD_BUILD_GUIDE.md) | How to build and install the bridge mod |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems and solutions |
| [docs/GAME_BRIDGE_REFERENCE.md](docs/GAME_BRIDGE_REFERENCE.md) | Bridge architecture and design notes |
| [docs/AUTOSLAY_BRIDGE.md](docs/AUTOSLAY_BRIDGE.md) | AutoSlay-based bridge design |
| [docs/GAME_SYSTEMS_REFERENCE.md](docs/GAME_SYSTEMS_REFERENCE.md) | Game mechanics reference |

## License

This project is for research and educational purposes. Slay the Spire 2 is the property of Mega Crit Games.

## Acknowledgments

- [decapitate-the-spire](https://github.com/jahabrewer/decapitate-the-spire) -- STS1 headless simulator, architectural inspiration
- [spire-codex](https://github.com/ptrlrd/spire-codex) -- STS2 data extraction pipeline
- [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod) -- STS1 game bridge protocol design
- [BaseLib-StS2](https://github.com/Alchyr/BaseLib-StS2) -- STS2 mod framework
- [Stable Baselines 3](https://github.com/DLR-RM/stable-baselines3) -- RL training framework

2026-10-19 续跑修复：PossessStrength/PossessSpeed 在原生死亡事件返还被偷属性，确保旋风斩后续命中使用更新后的力量；固定 seed 2000063 完整状态/动作/后继对账通过。已完成缓存按原来源留档，严格校验后继续使用。

2026-10-19：修复 HIDDEN_GEM+ 随机候选过滤，按 v0.111.0 排除 Curse/Quest，保留可打出的 Status。最小 seed37003 修复前第4决策失败，修复后24决策完整对账并实际打出 replay=3 的 SLIMED；原 seed2000125 重跑51决策通过。保留125场已完成采集及模型断点。

随后续跑 seed2000129 暴露 BRAND/INFERNO 终局选择时序差异：改用显式自伤 mirror，去掉延迟重复补偿；自伤结束战斗时不请求选择，空手使用既有无选择后处理。最小配方同时覆盖普通选牌、无选牌和终局；实际失败配方29决策获胜并完整对账。保留133场缓存续跑。

续跑补充：seed2000147 HAVOC 自动打出 TEAR_ASUNDER，在 WATERFALL_GIANT 致死后的多段攻击中暴露阶段切换延迟。SteamEruption 现于原生 AfterDeath 立即切换，后续命中正确扣10 HP；固定配方29决策完整对账，保留149场缓存续跑。

原生采集修复（2026-10-19）：HEADBUTT 末击后不再请求弃牌选择；CALAMITY 生成 STOMP 使用已完成攻击历史计算费用。新增 native_headbutt_terminal_v1 / native_calamity_stomp_entry_v1 严格轨迹回归。

原生注入选牌器时序修复（2026-10-19）：在完整回合准备后执行 AfterSideTurnStart，修复 HELLRAISER/SEEKER_STRIKE 与 RAMPART 的提前触发。新增诊断重放夹具 native_selector_turn_start_v1；严格校验不变。
