# SlayTheModel AI 开发交接

更新时间：2026-10-15  
仓库：`https://github.com/Cher1shYe/SlayTheModel`  
当前工作目录：`/Users/yebohou/SlayTheModel`

这份文件是当前工程状态与下一位 coding agent 的交接入口。源码和可重跑测试优先于历史对话；实现发生变化时，应同步更新本文件、README 和对应设计文档。

## 0. 接手摘要（2026-10-15）

| 方向 | 已完成到哪里 | 接手时最重要的边界 |
|---|---|---|
| 人类数据采集 | 独立只读 Mod、统一 JSONL journal、局内/局外观察、事件哈希链、partial 恢复、语义审计、tensor 转换入口与自动紧凑事件视图已在本地工作树；奖励公式现由旧日志事实离线重建；Adapter 的 MCTS 动作和直接选牌可写明确来源 | 6 局 no-SL 日志的 4,021 个安全步骤可用于分幕 RTG；另外三局为 unknown/来源不足。原生无窗口整链路已验证 4 个 MCTS 步骤零 gap，可见整局仍待复测。原始 JSONL 始终是事实源，不因改奖励回填或重采 |
| SpireFormer | Set Transformer + DT 风格共享主干、动态合法动作头、tensor shard v2、BC-only、分幕 RTG 组装和整局隔离评估已落地；现有混合 BC Tiny 的 held-out test 整体/战斗/局外 top-1 为 55.40%/56.91%/54.80%；`act-rtg-human-v2` 按 2,738/781/502 步分 train/val/test，训练集含 3 胜 1 负，Tiny 已训练 1,000 步 | 奖励数据仍只有铁甲 6 局；真实 RTG 与零 RTG 的 holdout top-1 只差 0.51/0.20 个百分点；没有游戏内推理、独立 value target或自主跑局胜率；Spire Codex BC 不应以 RTG=0 直接混入分幕训练 |
| 原生终端界面 | 独立 `Sts2.HeadlessHost`、终端客户端和脚本可通过 loopback 操作一个另启的原生游戏进程；同一原生测试局已从第 1 层连续走到第 17 层首领败局 | 宿主虽以 Godot `--headless` 启动，仍加载完整 `NGame` 场景、UI 和音频，不能用于高速自迭代，也未接采集 writer/模型；快速地图转场仍可短暂暴露旧页面输入 |
| 高速无界面原型 | `NativeThroughputBenchmark` 已实测独立原生战斗；通用 `WholeRunSpeedProbe` 的 20 个规范化种子全部以 `error=null` 到达原生终局；终端败局的 169 个战斗动作/16 次地图移动已重放；两条 A0 胜局 journal 已分别连续核到 step 700/494 的首个缺口边界；三条无 gap A0 败局已完整到原生终点，新两局最近约 1.39/1.05 秒 | `WinRun` 尚无运行时胜局证据；相同种子还要求相同局数与 encounter 发现历史，缺源 progress 时必须显式记录恢复输入；两条胜局分别在 step 701/495 有 gap；live 动画中间态只在战斗首决策严格对齐。TestMode 满槽自动领奖日志仍有 warning |

用户随后授权继续调试无界面选牌。历史未规范化种子夹具已到达原生败局终点，并验证其商店、休息点、宝箱分支；默认探针现按游戏规则规范化种子、从隔离 profile 生成解锁状态，并在 TestMode 中强制使用正常游戏的发现顺序规则。同种子首战、奖励与首个自然问号事件已有分支对照；2026-10-09 又用终端宿主打完一局第 17 层败局，将完整决策轨迹在无场景探针中重放到同一终点。2026-10-14 新增任意种子通用入口并实测 20 个种子，其中第 4 个已有真实跨幕证据，`ABYSSAL_BATHS` 的可重复选项循环也已修复；同日将两条现存 A0 胜局 journal 的无缺口前缀分别扩到第三幕 step 700 与 step 494，后者原生重放了 Crystal Sphere 三次翻格与奖励，并完整重放三条无 gap A0 败局。新两局分别消费 233/226 个决策，在第 17 层 `WATERFALL_GIANT_BOSS` / `SOUL_FYSH_BOSS` 死亡且各重复通过。这些结果证明源 profile 的局数与发现/遭遇历史也是同种子重放上下文的一部分，并补齐商店 RNG、事件恢复、跨幕、非卡包型涅奥选择、奖励页弃药、Crystal Sphere、空宝箱和败局终点。下一步需要用原始记录本身无 gap 的胜局验证最终终点，再决定如何把共享 writer 和模型推理接进高速 runner。

## 1. 当前 Git 状态：先保护现场

- 2026-10-15 用户明确奖励公式必须离线应用，不能因改奖励而重采。新增 `act_reward_derived.py`：从旧 `whole-run-v2` 的公开决策状态、逐动作 HP transition、原生战斗生命周期和原生终局重建 `whole-run-act-v1`，源 JSONL 不改写；新 `act_reward_boundary` 仅作为更精确的可选审计证据。当前 9 局中 6 局 no-SL 日志合格，共 4,021 个安全步骤；最终按 episode 隔离组装到忽略目录 `artifacts/spireformer/act-rtg-human-v2/`，train 4 局/2,738（3 胜 1 负）、val 1 局/781、test 1 局/502，证据模式均为 `derived_from_public_journal_v1`。旧日志战前锚点是首个公开战斗决策，不能冒充原生 BeforeCombatStart 快照。局部 gap 切历史并排除相应标签，不再仅因整局 `value_target_valid=false` 否定可独立核验的奖励。审计报告 `artifacts/spireformer/act-readiness-20261015.json` 已更新；Python 全套 292 passed。
- `tiny-act-rtg-human-v2-1000steps` 已完成 1,000 个 CPU/FP32 optimizer step（约 17 个 trajectory epoch）。真实 RTG 条件下整局隔离 val/test top-1 49.68%/53.98%，多合法动作 46.68%/49.45%；零 RTG 为 49.17%/53.78%。episode split 均验证无重叠。差异太小，不能宣称稳定 RTG 控制；test NLL 1.962 高于 uniform 1.600，4 个 holdout 集合标签 exact-set 均为 0。checkpoint 与评估 JSON 位于忽略目录 `artifacts/train-runs/tiny-act-rtg-human-v2-1000steps/`，没有接入游戏内推理。
- 2026-10-15 用户新上传 `f0006360521a489cb71b7e9e8f22dcf7` 铁甲 A0 第 48 层胜局：562 决策（355 战斗/207 局外）、20 场战斗，哈希链通过；但信息模式全部 unknown、策略笼统为 observed-automation，且 step 489 缺选牌完成证据与一处空选择缺人工确认，共 2 个 gap。该局仍因信息模式和来源证据排除，与奖励能否离线重建无关。新日志中的 mcts_card_choice 路径不在此前本地源码，不能将上传构建与本地源码等同。旧文件保持原样。
- 2026-10-15 新增可选 Adapter→DataCollector 来源桥：`PolicyDecisionTelemetry` / `PolicyTraceMetadata` 与 `CollectorPolicyTelemetry` / `CollectorPolicyActionCapture` / `CollectorPolicyOrigin`。在真实 GameAction 入队前冻结公开状态，入队事件按对象身份绑定合法动作，复用原生执行/取消结果；MCTS 明确 `policy_id=native-mcts, teacher_information=native_checkpoint_privileged`，first-legal 为 public_observation。没有确证来源仍是 observed-automation；手动配置的局外域可保留 human，MCTS fallback 选择器的真实人工确认也保留 human。原 no-SL/SL/unknown 配置不自动改变。header 新增采集能力版本与 collector_binary_sha256，便于分辨未提交构建。MCTS 根节点 visits 仍未采集，搜索摘要不进入模型特征。
- 2026-10-15 MCTS 选牌修复：`ICardSelector` 的直接回传分支不会产生原生 PlayerChoiceSynchronizer 回执，新增请求/实际返回关联；fallback UI 与同一请求关联，核对确认（含空选）、UI Task 与实际 callback 返回，失败或未完成仍记 gap。普通原生人工选择器继续要求同步回执。生产 observation source 使用通用 card_selector；tensorizer 也将历史 mcts_card_choice 归一，防教师来源进入特征。必须同时更新 Adapter 和 DataCollector 才有这条桥。新增 NativeWorker `collector-policy-verify` 在同一无窗口原生进程加载实际两个 Release DLL，执行两张防御、头槌及一次弃牌选择；journal 的 4 组 decision/action/result/reward 全为 `native-mcts` / `native_checkpoint_privileged` 且零 gap。本轮未安装、未启动可见游戏，真实整局验收仍待进行。
- 2026-10-15 新增 `scripts/audit-act-reward-data.py` 只读审计入口；assembler/CLI 可显式 `--allow-policy native-mcts`（或 first-legal），严格核对 policy_id/teacher_information 并保留来源统计，默认 human-only 不变。此选项不放宽 unknown 或原生终局门槛；局部 gap 切历史并排除受影响标签。隔离分幕奖励采集 smoke 通过，来源与选牌 smoke 使用原生类型/模拟生命周期，不代表新实机跑局。
- 2026-10-15 用户确定新的首版 `whole-run-act-v1`，取代此前纯胜败方案：三幕胜利 +1/+2/+3，非 Boss 战 `(战后HP−战前HP)/战后maxHP`，每幕首个 Boss 前全量统计当前升级牌每张 +0.05 和当前遗物每件 +0.1（包含起始遗物），第三幕另加 HP/maxHP；败北追加 −10，gamma=1，不裁剪。新增 `act_rewards.py`、`act_reward_journal.py` 和离线通用事实重建器，assembler/CLI 显式选择该版本并自动生成事件账本及 RTG。新 `CollectorActRewardCapture.cs` 写入的精确边界是可选增强证据；未声明精确边界的旧日志使用明示的首公开决策/通用 HP transition 口径。采集补丁尚未实机复测；具体规则见 `docs/spireformer-act-reward-v1.md`。−10 不是保证败局总回报为负的硬上限。
- 2026-10-14 用户授权首版奖励函数，新增 `spireformer/rewards.py` 与 assembler/CLI 的显式 `whole-run-win-v1`：整局通关 +1、失败 0、过程 0、折扣 1。训练 RTG 自动计算，胜局各步 1/败局各步 0；保留严格 no-SL 整局审计、开局观察与 `native_run_history` 终局证据，放弃/缺口/未知模式不转失败标签。8 局现存 journal 仅 `32a...` 的 228 步败局通过；忽略产物 `artifacts/spireformer/win-rtg-v1-audit/holdout/` 已哈希重读，只验证转换，保留原 mixed BC 的 test 隔离，没有更新 BC checkpoint。其余 5 局胜局有缺口/药水漏记，新 2 局模式 unknown。新方案未用真实胜败数据训练，value target 仍缺失；自主玩另需目标 RTG（该方案可先请求 1），在线执行尚未接入。`whole-run-hp-safe-v1` 保持为历史可选方案，原 JSONL reward 不改写，详见 `model/spireformer/README.md` 的纯通关 RTG 说明。
- 当前分支：`workspace_YE`。
- 当前 HEAD：`53d09f4 feat: add human trajectory collector with compact journals`。2026-10-15 `origin/workspace_YE` 已前进到 `fbf33cc`，比本地 HEAD 多 4 个提交：`b9386b1`、`0666c09`、`dad372e`、`fbf33cc`。用户要求不由 agent commit/push；工作树已选择性吸收断点续采字段冲突、MCTS 选牌卡牌身份与失败/截断 rollout 敌方 HP 进度评分，并保留本地更严格的显式 policy telemetry，没有直接 cherry-pick 远端的通用 `automation_or_unknown` 桥。合并与验证细节见 `docs/mcts-collector-fixes-20261015.md` 和 `docs/mcts-progress-reward-20261015.md`。
- 2026-10-09 应用户要求，将 SpeedX 作者注明参考过的开源加速模组 `jidon333/STS2_Superfast_Mod` 浅克隆到忽略目录 `artifacts/reference/STS2_Superfast_Mod/`，检出 `src/`、`docs/`、`config/` 和根 README；固定提交 `427f46931fb3431fa3f7f5a7f14da81b217e2a7f`。后续可参考其 `src/Sts2Speed.ModSkeleton/Runtime/SpeedPatches.cs` 中原生 `Cmd.CustomScaledWait`、`CombatState.GodotTimerTask`、Spine `SetTimeScale` 与 UI/VFX `_Process` 补丁位置，分析 live collector 的动画/结算时序。它不是皮皮极速 SpeedX 本体；这些旧版本 patch target 不代表当前 `v0.111.0` 已验证。该参考目录不进入本仓库提交。
- 2026-10-10 用户授权研究并归档 Spire Codex 公开回放：`ptrlrd/spire-codex-mod` 参考源码仍在忽略目录 `artifacts/reference/spire-codex-mod/`，提交 `8600222a` 与远端 `main`、`v1.2.1` 标签一致。历史公开清单去重后有 14,848 个 hash，14,794 份可解析，录制模组 `v1.2.1` 的有 2,575 份。曾用 `scripts/fetch-spire-codex-replays.py` 下载全量、`scripts/filter-spire-codex-replays.py` 根据回放首行模组清单和游戏版本筛选；这些是筛选过程的历史统计，不代表当前硬盘上仍有全量归档。下载脚本现会拒绝向已精简的归档目录重新下载。
- 2026-10-10 用户随后明确要求“只保留这些数据，其他的全扔”：已删除 Spire Codex 其他回放、下载缓存、错误隔离文件及两份早期样本，只保留 166 份严格候选，约 17 MB，位于忽略目录 `artifacts/reference/spire-codex/bulk/v1.2.1/<角色>/`。条件为五原版角色、录制模组 `v1.2.1`、游戏 `v0.111.0`、加载模组恰为 `BaseLib` 和 `SpireCodex`、`capture_status=complete`、标准单人、无 modifiers、回放头开局 reloads=0。五角色分别为 IRONCLAD 31、SILENT 37、DEFECT 25、NECROBINDER 57、REGENT 16。总清单 `bulk/v1.2.1/manifest.jsonl` 与角色清单 `bulk/v1.2.1/filtered/strict-by-character/<角色>/manifest.jsonl` 各行保留文件 SHA-256；`bulk/summary.json` 记录筛选条件与历史来源计数。`affects_gameplay` 是模组声明，`complete` 不证明逐决策覆盖，开局 reloads=0 不排除局中读档；外部回放的 `draw_order` 等隐藏信息不得进 no-SL 特征，尚未通过本项目 BC/RTG 审计，不可直接当训练样本。不得恢复全量归档，除非用户明确要求。
- 2026-10-11 应用户要求重建这 166 局：新增标准库转换器 `model/spireformer/spireformer/spire_codex.py`、入口 `scripts/convert-spire-codex-replays.py`、测试与 `docs/spire-codex-conversion-v1.md`。输出在忽略目录 `artifacts/reference/spire-codex/reconstructed-v1/`，166 局全部通过源/输出 SHA-256 与递归禁用字段核验，共 56,160 步。7,537 个局外步骤中 7,341 个候选与选择结构完整；保守排除首段后的 238 个 `resumed_segment_unverified` 录制段后，安全 BC 索引为 4,603 步。严格语料都是 `v0.111.0` 无 modifier 标准局，header 未直接记录的新局初始金币按原生规则恢复为 99；134 个后续具有可逆金币锚点的新局均反推得到 99，恢复段仅保留审计且不训练，BC observation 的公开跑局字段无缺失。48,623 个战斗步骤重建了无序公开状态，但原日志没有输入时完整合法动作集合，全部保持直接 BC ineligible；排除恢复段后有 24,856 个顺序原生重放候选。5,274 个结束回合可以驱动顺序重放，但 raw 状态发生在点击后，明确写 `reconstructed_observation_valid=false`，必须使用原生执行前投影；另 10 个缺少边界的结束回合继续排除。亡灵契约师 ally 已修正为 companion。seed、RNG state、未来 draw/shuffle 顺序、时间、本地化文本和原生实例 ID 均不输出；不生成 RTG/value。
- 2026-10-11 Spire Codex 原生战斗试点与 tensor bridge 已落地：`scripts/extract-spire-codex-combat-plan.py` 生成仅供恢复的内部计划，`spire-codex-combat-replay` worker 用固定 `v0.111.0` 执行动作，并在每个真实输入边界投影 observation、完整合法动作和所选动作。计划包含 seed/RNG/opening draw order 且标记 `replay_only_hidden_state=true`；训练 loader `spire_codex_native.py` 以 SHA-256 绑定计划和报告，输出中不含这些字段。DEFECT/IRONCLAD/NECROBINDER/REGENT/SILENT 各一场完整首战分别有 12/11/13/14/20 个决策；另以铁甲 `a8d7ab6d08211e91` 从正常新局顺序执行涅奥、首战 11 步、原生奖励和第二战 12 步，合计 7 场战斗、93 个 BC 步骤均原生胜利。中途直接重建即使 RNG counter 相同仍出现不同起手牌，证明 counter 不是完整 RNG 状态；顺序路径 23/23 决策一致。外部 header 不记录玩家解锁状态，同 seed/坐标在全解锁隔离档可生成不同遭遇，所以本试点按记录指定原生 encounter model，并未把地图遭遇选择冒充为已验证。
- 2026-10-11 `spire_codex_tensor.py` 和 `scripts/assemble-spire-codex-dataset.py` 已把 4,603 个安全局外步骤与上述 93 个战斗步骤合并。最新结果位于忽略目录 `artifacts/reference/spire-codex/tensor-bc-v3/`，FP16 缓存约 881 MB，dataset ID `afecb42485a472e6f97ce8d6baa08650`，vocabulary hash `83f4c23b1ccc004eacbb51354c2eff7a4417241b3b3b431805680b17de1f0aae`，entity/action 宽度 609/560。train 126 局 3,788 步（战斗 43）、val 17 局 497 步（战斗 36）、test 17 局 411 步（战斗 14），另 6 局没有安全步骤；三个 split 均覆盖五角色且 episode 不重叠。476 个集合选择界面中 448 个有集合标签，28 个合法取消只监督模板/取消动作。所有 shard 已按 manifest SHA-256 重读；Tiny 完成一次 CPU 优化器更新，evaluator 对 val/test 均返回 `episode_split_verified=true`。本轮修正 evaluator 未将 FP16 shard 特征提升到 FP32、导致 Set Transformer query/key/value dtype 不一致的问题并增加回归测试。RTG 全为 0 占位、value target 全缺失。
- 2026-10-14 新增 `mixed_bc.py` 与 `scripts/assemble-mixed-bc-dataset.py`，在张量化前用 train-only 共享词表合并上述 4,696 个 Spire Codex 步骤和 6 局 collector 的 4,021 个严格 no-SL BC 步骤；新两局 `a09.../d9...` 因 information mode unknown 明确排除。忽略数据集 `artifacts/spireformer/mixed-bc-v1/` 共 8,717 步、约 1.2 GB，train/val/test 为 6,800/1,278/639 步，战斗为 2,168/601/181 步；12 个 FP16 shard 和 166 个 episode/source hash 的 split 隔离均已重读核验。dataset ID `2ed66b6b7ca90cb3e4e09884d23a2f43`，词表哈希 `018124302d985371ca7549f754080bf80d1085bedd0f6c108718c78ab8838dff`，宽度 609/570。实际 3,200,387 参数 Tiny 在 CPU/FP32 完成 3,000 步纯 BC 试训，忽略 checkpoint 位于 `artifacts/train-runs/tiny-mixed-bc-v1-3000steps/`；整局隔离 val/test 整体 top-1 为 48.04%/55.40%，test 战斗/局外为 56.91%/54.80%，均超过对应首合法和随机基线，`episode_split_verified=true`。test 集合 exact-set 仅 19.05%；评估使用记录历史动作，不是自主原生跑局，value target 仍全缺失。完整命令和指标见 `docs/spireformer-mixed-bc-pilot-v1.md`。
- 2026-10-12 参考 Spire Codex 的可读事件流思路，但未复制其源码，在原采集器上新增 `CompactEpisodeJournal`。完整哈希链 JSONL 先照常原子发布，再自动生成 `episodes/_compact/*.compact.jsonl`；decision 继续逐步保存完整合法动作与具体集合选择标签，observation/context 使用每 64 步 checkpoint 的可逆 JSON Pointer 差量，重复手动输入证据在与对应 decision/attempt 逐项一致后改为步骤引用，少数执行观察保存相对 decision 的差量。每个差量发布前都还原并与原始 JSON 比较，末行绑定原始文件 SHA-256；派生失败只记录 warning，不使原始 episode 失败。collector smoke 覆盖自动发布、回填、数组差量与局内/局外集合标签；Collector 和 DataCollector 均 0 warning 编译。当前 6 份历史实机日志全部离线导出成功，合计 156,638,021 → 29,624,597 字节，减少 81.1%；`2085...` 的 5,516 事件/932 decision 从 35,405,881 → 6,675,823 字节。自动生成路径尚未安装或实机复测，tensorizer 仍只读取原始 JSONL。
- 2026-10-07 用户授权制作可玩的原生整局 headless，并明确只用终端界面。新增 `tools/Sts2.HeadlessHost/`、`scripts/headless-*`、`smoke/headless-play-client-smoke.py` 和对应文档，均保留为本地未提交成果。宿主保留原生场景树，用匹配的游戏引擎 `--headless` 执行，终端通过 loopback JSON 操作；没有网页。最新运行验证状态见 `docs/headless-terminal-v0.1.md`，特殊事件静态覆盖与逐分支验证边界见 `docs/headless-event-coverage-v0.111.0.md`。目前未接入训练 writer/模型推理，不能把终端 JSON 当作原有训练 JSONL。
- 2026-10-08 用户明确指出速度是整局自迭代的首要门槛。当前终端宿主会加载完整场景、音频并读取部分界面节点，只作原生交互对照，不能当作高速训练环境。新增 `NativeThroughputBenchmark` 和 `native-throughput` worker 模式；macOS ARM64 上三个固定 `CULTISTS_NORMAL` 原生战斗分别测得 573–754 决策/秒（不含进程启动、投影、模型、局外或落盘）。固定种子的无完整界面最小跑局路径已在后续探针中通过，但不得用战斗速度或短路径时间推断完整整局吞吐量。详见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-08 `WholeRunSpeedProbe` 已补齐原生 `ICardSelector`/`CardRewardSelection` 引用，改用 `EventOption.Chosen()`，并在同一个无 `NGame` 进程里通过原生选择器选择涅奥 `PRECISE_SCISSORS` 的删牌目标。固定种子随后完成 `SHRINKER_BEETLE_WEAK` 战斗、原生奖励和 `AROMA_OF_CHAOS` 单卡变形；继续经过 `NIBBITS_WEAK` 战斗、`MORPHIC_GROVE` 双卡变形、`SELF_HELP_BOOK` 单卡附魔，在第 7 层 `BYGONE_EFFIGY_ELITE` 战斗后 HP 0、`RunManager.IsGameOver=true`。三次短败局约 491.5/531.3/485.7 ms（不含进程启动、构建、终端、模型、协议投影或落盘），三个战斗分别有 9/9/21 个决策。战后奖励在普通游戏中由 `NCombatUi` 动画完成后调用 `CombatRoom.OfferRoomEndRewards()`；无界面探针在相同原生边界显式调用此方法，并由 TestMode 原生奖励选择流程结算，不伪造奖励。同种子另有商店、休息点与宝箱分支实测，详见第 3.6 节。这些路径不代表完整胜局或通用 runner。先前 `OnChosen` UI 异常与 CS0246 只作为历史阻挡记录。
- 2026-10-08 同输入种子对照发现历史速度夹具的 `STM-WHOLE-RUN-SPEED-1` 未经过 `SeedHelper.CanonicalizeSeed`；正常游戏将 `O` 变为 `0`。**默认** `whole-run-speed-probe` 现先规范化并将实际 `seed`、`inputSeed` 写入输出，跑通涅奥、首战、奖励和下一节点；旧第 7 层败局与 `shop|rest` 需显式 `whole-run-speed-probe-legacy` 复跑，不能用作同输入种子等价证据。规范化后涅奥三项、首选 `SCROLL_BOXES` 和第一幕地图 65 节点/77 连线与完整场景宿主一致；最初首战却是探针 `SLIMES_WEAK`、宿主 `TOADPOLES_WEAK`。根因是探针给 `Player.CreateForNewRun` 传入 `UnlockState.all`，而原生 `NGame.StartNewSingleplayerRun` 从 profile 生成解锁状态。默认探针现与宿主一样在隔离 profile 中 reveal 全部 epoch，再调用 `SaveManager.GenerateUnlockStateFromProgress()`；复测首战均为 `TOADPOLES_WEAK`，两只敌人初始 HP 25/21、玩家 HP 80、13 张牌组成逐项一致。旧 legacy 模式仍用 `UnlockState.all`，复跑到第 7 层败局且 `error=null`。TestMode 仍启用；首战其他策略和后续节点的逐步等价性未验证，详见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-08 首战抽牌逐决策对照：设置 `STS2_PROBE_TRACE_DRAWS=1` 时，默认探针新增 `first-combat-decision-trace`，只写每步手牌和各牌堆的无序卡牌 model ID 集合、玩家/敌人状态与所选动作；普通速度测量不生成此轨迹。`scripts/check-headless-draw-parity.py` 从完整 `NGame` 宿主的新测试局提交相同涅奥、卡牌包、地图和 8 个首战动作；8/8 个决策点的回合、HP、能量、存活敌人及手牌/draw/discard/exhaust/play 集合逐项一致，包括第 3 回合洗牌后的手牌。胜利后两边玩家均 75 HP，宿主进入奖励页。完整场景暂留 0 HP 敌人动画节点，对照脚本按存活敌人比较。结果 `artifacts/headless/first-combat-draw-parity.json`；不代表未来隐藏牌序、其他策略、其他种子或后续房间已对齐。宿主仍不是高速 runner。详见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-09 同种子首个自然问号事件对照：默认探针设置 `STS2_PROBE_ROUTE=event` 后，经同样 8 个首战动作和原生战后奖励，金钱奖励 10、药水 `FIRE_POTION`、三张卡牌候选及第一张 `SWORD_BOOMERANG` 均与完整场景宿主一致；自然连线 `(0,1)→(1,2)` 生成同一 `SPIRALING_WHIRLPOOL`，选项顺序 `Observe / Drink` 一致。各用新局验证两个分支：`Observe` 的 5 张 Strike / 4 张 Defend 候选、选中 Strike 后的 `ENCHANTMENT.SPIRAL`、最终牌组/HP/金币/遗物/药水一致；`Drink` 的 HP 75→80 且其他状态不变也一致。两边事件结束后沿合法连线 `(1,2)→(2,3)` 都进入 `CORPSE_SLUGS_WEAK`，两只 `CORPSE_SLUG` 初始 HP 27/26，玩家 HP/金币/牌组一致。两份自动对照各有 `matchedDecisions=8`、`eventRoute.matches=true`、`nextRoom.matches=true`，见忽略文件 `artifacts/headless/event-parity-observe.json` 与 `event-parity-drink.json`。只证明此事件两条选项及下一场遭遇入口，不证明其他事件或后续战斗逐步一致；复跑方法见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-09 终端宿主长路径：`scripts/headless-long-path-smoke.py` 用同一 loopback API 从新局连续操作规范化种子 `STM-WHOLE-RUN-SPEED-1`，经第 1–17 层、9 场战斗（含瀑布巨兽首领）、“螺旋漩涡”单卡选择、“满屋芝士”双卡选择、4 个休息点和 1 个宝箱，最终原生 `status=finished, screen=defeat, hp=0`。中途仅重启测试脚本修正双选牌策略，宿主和原生测试局未重启；原始 API 轨迹 `artifacts/headless/long-path-trace.jsonl` 共 209 个接受动作（含旧脚本在双选牌页的重复切换）与一次可恢复的 stale revision 409，宿主日志无 action/capture failed。此路径只验证完整场景终端宿主，不是无 `NGame` 高速探针的第 17 层对照。第一次不带等待的自动尝试发现：地图提交后短暂暴露前一涅奥页“继续”，快速点击可跳过首战；当前脚本地图后等待 2.5 秒并核对稳定 revision，宿主仍需转场输入栅栏。Ctrl-C 退出时仍有 Godot static-string / `libc++abi` 清理错误，发生在败局状态返回之后。详情见 `docs/headless-terminal-v0.1.md`。
- 2026-10-09 应用户明确“标准是高速探针”后，新增 `STS2_PROBE_LONG_PATH=1` 与 `STS2_PROBE_ROUTE=event` 的无 `NGame` 长路径。规范化种子 `STM-WH0LE-RUN-SPEED-1` 从第 1 层连续经 9 场原生战斗共 130 个决策、两个自然事件、4 个休息点和 1 个宝箱，到第 17 层 `WATERFALL_GIANT_BOSS` 死亡；输出 `long-path-natural-defeat`、`RunManager.IsGameOver=true`、`gameSceneLoaded=false`，修正发现顺序规则后最近复跑探针内计时 788.9 ms。此前首领为 `LAGAVULIN_MATRIARCH_BOSS` 的原因是 TestMode 默认跳过 `ActModel.ApplyDiscoveryOrderModifications`；默认规范化探针现设置原生 `ForceDiscoveryOrderModifications=true`，与正常游戏首领对齐。第 14 层满药水槽时，跳过新药水是合法选择；探针调用原生 `RewardsSetSynchronizer.SkipLocalRewardsSet()`，断言奖励集合完成，并验证原有三瓶药水槽位和种类未变，其他不完整奖励直接失败。TestMode 自动领奖在跳过前仍记一条 `RewardsSet is not complete` 日志，输出保留 `warnings` 和 `complete-with-warnings`；这指日志问题，不是奖励未结算。默认不启用长路径时的 `event` 前缀复跑仍为 `canonical-prefix-complete`、`error=null`。结果 `artifacts/native-host/whole-run-speed-probe-event-long.json`，详情见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-09 按用户要求，通过完整场景原生终端宿主另开铁甲新局，agent 控制脚本 `scripts/headless-agent-run.py` 从公开状态选择动作，原生终态为第 17 层 `WATERFALL_GIANT_BOSS` 败局、HP 0、金币 213。`artifacts/headless/agent-run-trace.jsonl` 保存 244 个被接受的动作及各动作前公开状态（16 次地图移动、127 次出牌、40 次结束回合、2 次战斗用药等）；中途弃一瓶 Fire Potion、跳过第 9 层整组战后奖励也原样保留。`WholeRunSpeedProbe.RecordedReplay.cs` 在无 `NGame` 的独立 worker 依次执行同一动作，16 次地图移动和 169 个战斗动作前核对 HP、金币、楼层、牌组/附魔、遗物、药水、手牌和各牌堆无序集合、能量、格挡、敌人 HP/格挡，最终同在第 17 层 HP 0 原生败北；`error=null`、`gameSceneLoaded=false`，探针内部 817.3 ms。重复基础 Defend 的跨进程对象 ID 不稳定，第 11 层被附魔对象以 `STS2_PROBE_REPLAY_DEFEND_ORDINAL=1` 根据后续状态消歧；此轨迹不证明通用身份映射、其他种子或胜局。终端 API JSONL 不是训练 journal。详情见 `docs/headless-performance-gate-v0.1.md`，结果 `artifacts/native-host/whole-run-speed-probe-recorded-replay.json`。
- 2026-10-14 用户重新授权继续高速探针。新增 `STS2_PROBE_GENERIC=1` 和 `STS2_PROBE_SEED=<seed>`：涅奥后直接进入通用原生房间循环，不再依赖固定首战/问号前缀；无子节点时按原生 `EnterNextAct()` 跨幕，最终幕完成时调用 `WinRun()`，终局统一记录胜败。连续检查 `STM-WHOLE-RUN-SPEED-{1..20}`，全部 `error=null`、`gameSceneLoaded=false`，终局在第 7–18 层并覆盖 20 种非涅奥事件；第 4 个种子打赢 `VANTOM_BOSS`，通过原生 `EnterNextAct()` 落到第二幕 `MapRoom`，以 `run.Map.StartingMapPoint` 取得合法入口后进入第 18 层 `EXOSKELETONS_WEAK` 并败北，最近约 1468.9 ms。第 9 个种子曾因 `ABYSSAL_BATHS` 的 `LINGER` 重建同名选项而超过旧 8 步限制；事件策略现优先选择使用次数较少的合法选项并保留 32 步保护，复跑以 `IMMERSE → LINGER → EXIT_BATHS` 正常退出，第 13 个种子也通过。`STS2_PROBE_USE_POTIONS=1` 另按原生可用性和目标规则生成药水动作；第 4 个种子已在半血后真实消费三瓶并处理选牌，但该简单策略仍退回第一幕，故默认关闭并单独输出 `*-potions.json`。旧 `event + LONG_PATH` 复跑仍到同一第 17 层败局。`WinRun` 尚无运行时证据，新种子未做完整场景逐决策对照。macOS 脚本的 `--skip-build` 现会重打包最新 DLL，构建使用单 MSBuild 节点并关闭 node reuse，避免执行旧 staged worker 或本机共享节点无错误卡住。详情见 `docs/headless-performance-gate-v0.1.md`。
- 2026-10-14 又新增 `WholeRunSpeedProbe.CollectorReplay.cs` 与 `STS2_PROBE_COLLECTOR_REPLAY=<jsonl>`，把人类采集 journal 直接驱动到无 `NGame` worker。无 gap 的历史 A0 胜局 `435800f8...` 原始 JSONL 已不在本机，故使用现存 48 层铁甲 A0 胜局 `1ddd1912...`；该源文件自身在 step 701 有一次商店购买 gap，不能恢复为严格 RTG。设置 `STS2_PROBE_PROGRESS_SAVE=<progress.save>` 时只读反序列化源玩家进度到 worker 内存；仅有相同 seed 和全解锁状态会生成不同首战，载入发现/遭遇历史后首战自然对齐，未强制替换 encounter。入口现连续重放 step 0–700，经两次原生 `EnterNextAct()` 到第三幕第 45 层商店，并在执行未知购买前核对 step 701 的 gap observation；两次完整复跑均为 `verifiedThroughGlobalStep=700`、`gapBoundaryVerified=true`、`matchedCombatDecisions=497`、`matchedOutsideDecisions=203`、`error=null`、`gameSceneLoaded=false`，探针内计时约 1.83–1.98 秒。覆盖 44 次地图移动、21 场战斗、20 组奖励、8 次锻造、3 个宝箱、多次商店交易/删牌、事件集合选择及两次跨幕。缺口前 3 个 `cancelled` 结果也按无副作用语义处理：两次满槽药水领取失败，一次致命牌仍排队时的战斗输入由原生取消。为保持 RNG，TestMode 商店补回正常游戏的三次药水价格 roll；`BATTLEWORN_DUMMY` 战后通过原生父事件恢复入口产生两张随机升级。live journal 的动画中间态仍只在每战首决策严格核验，之后要求原生合法动作并在战后汇合；结果不表示 497 个动画中间态逐项相同。入口标记 `continuous-prefix-before-first-gap`，不猜测 step 701，也不验证 gap 后的最终胜局。结果与复跑命令见 `docs/headless-performance-gate-v0.1.md`。
- 同一入口又将无 coverage gap 的铁甲 A0 败局 `32a3822509ec4c9fa8d00017103daee6` 完整重放两次。该局涅奥为 `GOLDEN_PEARL`，没有卡包子选择；入口现根据下一条 observation 决定是否安装 bundle selector，不再硬编码 `SCROLL_BOXES`。228/228 个决策全部消费，13 次地图移动、9 场战斗、8 组奖励、3 个事件、2 次锻造和 1 个宝箱通过，第 14 层 `BYGONE_EFFIGY_ELITE` 原生死亡终点为 `terminalOutcomeVerified=true`。结果 `matchedCombatDecisions=167`、`matchedOutsideDecisions=61`、`error=null`、`gameSceneLoaded=false`，两次约 0.83–0.84 秒；忽略报告 `artifacts/native-host/whole-run-speed-probe-collector-replay-32a38225.json`。
- 2026-10-14 又将铁甲 A0 胜局 `2d9fc925402f440eaba2c30e5c214966` 连续重放到自身首个可定位缺口前。该 journal 的两个 gap 顶层步号均为空，其中 `outside_potion_loss_during_other_action` 通过 `related_decision_id` 关联 step 495；解析器现综合顶层步号、失效步和 decision ID 关联确定边界。三次严格复跑均执行 step 0–494，并在 step 495 动作前核对 HP/max HP、金币、层数、牌组、遗物及稀疏药水槽：`matchedCombatDecisions=270`、`matchedOutsideDecisions=225`、`gapBoundaryVerified=true`、`error=null`、`gameSceneLoaded=false`，约 2.05–3.18 秒。step 459–466 的 `CRYSTAL_SPHERE` 通过 UI-free patch 截获原生 `CrystalSphereMinigame`；三次大工具翻格逐步核对 121 格隐藏/高亮、揭示物品类别与图标，原生 30 金币和满槽 `FIRE_POTION` 取消/跳过均一致。奖励页结构化 `discard_potion` 现按顺序调用 `PotionCmd.Discard`；召唤怪目标改按 model/同类序号映射，战斗选牌按 model/升级/附魔/同类序号映射。加入严格药水核对后，`1ddd1912...`、`32a38225...`、`2d9fc925...` 三条回归均重新通过。忽略报告 `artifacts/native-host/whole-run-speed-probe-collector-replay-2d9fc925.json`；不得越过 step 495 猜测缺失弃药或把这局当完整 RTG。
- 2026-10-14 新上传的同账号连续铁甲 A0 败局 `a09f25fa...` 与 `d9c27368...` 已各完整重放两次。前者 233/233 个提交决策、156 战斗/77 局外、9 场战斗及 1 次取消全部消费，在第 17 层 `WATERFALL_GIANT_BOSS` 死亡，重复约 1.49/1.39 秒；后者 226/226、156 战斗/70 局外、9 场战斗，在第 17 层 `SOUL_FYSH_BOSS` 死亡，重复约 1.10/1.05 秒。两者均 `terminalOutcomeVerified=true`、`error=null`、`gameSceneLoaded=false`。`SILVER_CRUCIBLE` 导致的首次空宝箱现由原生奖励生成后允许 `open_chest → proceed`，第二宝箱仍领取 `TUNGSTEN_ROD`。源账号 progress 未上传；零局隔离档的问号教学规则会令第一局第 4 个问号房 RNG 分叉，因此新增显式 `STS2_PROBE_COLLECTOR_PRIOR_RUNS`；第二局又需用 `STS2_PROBE_COLLECTOR_SEEN_ENCOUNTERS` 输入第一局已确证见过的 encounter，原生发现顺序才自然生成 `SOUL_FYSH_BOSS`。这些输入写入报告，不直接替换房间/首领；有源 `progress.save` 时仍优先使用。报告为忽略文件 `whole-run-speed-probe-collector-replay-a09f25fa.json` 与 `...-d9c27368.json`。两份 journal 都是 `information_mode=unknown`、`no_sl_expected=false`，重放通过不等于 no-SL 训练合格。
- 人类数据采集 Mod 是当前工作树中的**未提交改动**，尚未 commit 或 push。先前铁甲局 `41774d4079db46029762d6b64df1a5bc` 有 1036 个结构化决策，其中 936 个可进入 BC-only tensorizer；旧采集器的 97 次 Toasty Mittens 单卡选择未关联原生 choice ID，另有一次 `EVENT.TRIAL` 双卡变化缺口，整局回报无效。当前工作树已针对 Toasty 修正内部手牌候选冻结与晚到的 `CombatCard` 回执关联，但尚未实机验证。另两局铁甲胜败轨迹 `433d5532920444a1afac0716251e12c4` 与 `32a3822509ec4c9fa8d00017103daee6` 曾用于首轮 HP RTG 组装；**该 shard 和 Small 20 步 checkpoint 已因漏记局外药水操作而作废**，详见第 4 节。此前亡灵契约师 `4be275a1f2554b938c3f90908c02ef23` 的双卡变化也有相同缺口。原始文件不可回填。
- 当前工作树已修正稀疏药水槽号投影；2026-09-30 又把局内/局外多卡选择改为候选列表、单个合法模板和提交时的真实集合，避免枚举组合。SpireFormer 共享主干新增候选牌/选择数训练头、tensor shard v2 读写与 raw JSONL → shard assembler。转换器保留默认 BC-only 模式，另支持明确启用的 `whole-run-hp-safe-v1` 整局 RTG；独立 value target 仍缺失。旧版槽位及排队合法集须在派生数据中核验。木札 29 选 3 的模板路径已有实机证据；新补的双卡变形路径仅有离线验证，尚未安装或实机验证。此前的 UUID 命名文件保留原名。
- 2026-09-30 用户明确将手动战斗输入的决策边界定为**点击时游戏内部状态**：手牌、抽牌堆、弃牌堆及合法动作均按该瞬间的原生状态记录，不再要求 Hand 与 UI holder 相等。live collector 产出的战斗 observation v5 普通 Hand `display` 对每张内部卡由原生 `CardModel` 计算当前能量/星星/X 费用，`description=null`、`dynamic_values=[]`；不读 UI holder 动画进度。选择器候选 `display` 仍用旧 UI 展示语义。泛协议投影与当前 headless writer 仍可生成 v5 且 Hand `display=null`；未来 runner 应补齐等价费用。此新边界尚未安装或实机验证，旧 JSONL 不回填。
- 2026-10-02 最新三份 no-SL 铁甲胜局 `2085af58...`、`1ddd1912...`、`2d9fc925...` 的哈希链完整，分别有 922/781/502 个 BC-only 可用步骤，但重叠局外药水操作及一次商店未匹配点击造成显式 gap，三局整局 HP RTG 均无效。Rewards 顶层两次独立弃药已结构化成功；本轮受控重叠药水边界和商店 `Task<bool>` 结果核对仍待安装及实机验证，旧 JSONL 不回填。
- 不要执行 `git reset --hard`、`git restore .`、强制切分支或清理未跟踪文件；这些改动属于当前开发成果。
- 不要自动 commit、push、开 PR、安装 Mod 或启动 Steam。只有用户明确要求时才执行。

交接时 `git status --short` 应包含下列本地成果（完整列表以实际命令为准）：

```text
 M .gitignore
 M README.md
 M docs/baseline-design.md
 M docs/outside-combat-interface-v1.md
 M docs/spireformer-training-data-v1-plan.md
 M model/spireformer/README.md
 M model/spireformer/docs/tensor-shard-format-v1.md
 M model/spireformer/spireformer/batch.py
 M model/spireformer/spireformer/cli.py
 M model/spireformer/spireformer/data.py
 M model/spireformer/spireformer/losses.py
 M model/spireformer/spireformer/model.py
 M model/spireformer/spireformer/training.py
 M model/spireformer/spireformer/trajectory.py
 M model/spireformer/tests/test_cli.py
 M model/spireformer/tests/test_presets.py
 M model/spireformer/tests/test_training.py
 M scripts/macos.sh
 M scripts/native-worker-macos.sh
 M scripts/native-worker.ps1
 M scripts/windows.ps1
 M smoke/SlayTheModel.Outside.Smoke/Program.cs
 M smoke/SlayTheModel.Protocol.Smoke/Program.cs
 M src/SlayTheModel.Sts2.ModAdapter/CombatCaptureService.cs
 M src/SlayTheModel.Sts2.ModAdapter/OutsideCombatCaptureService.cs
 M src/SlayTheModel.Sts2.Protocol/CombatActionDescriptor.cs
 M src/SlayTheModel.Sts2.Protocol/CombatSnapshot.cs
 M src/SlayTheModel.Sts2.Protocol/DecisionObservations.cs
 M src/SlayTheModel.Sts2.Protocol/OutsideCombatDecision.cs
 M tools/Sts2.NativeWorker/NativeSession.cs
 M tools/Sts2.NativeWorker/Worker.cs
?? AGENTS.md
?? docs/headless-event-coverage-v0.111.0.md
?? docs/headless-performance-gate-v0.1.md
?? docs/headless-terminal-v0.1.md
?? docs/human-data-collector-v0.1.md
?? docs/native-interaction-audit-v0.111.0.md
?? docs/spire-codex-conversion-v1.md
?? docs/spireformer-mixed-bc-pilot-v1.md
?? model/spireformer/docs/tensor-shard-format-v2.md
?? model/spireformer/spireformer/assemble.py
?? model/spireformer/spireformer/evaluate.py
?? model/spireformer/spireformer/mixed_bc.py
?? model/spireformer/spireformer/raw_features.py
?? model/spireformer/spireformer/raw_journal.py
?? model/spireformer/spireformer/spire_codex.py
?? model/spireformer/spireformer/spire_codex_native.py
?? model/spireformer/spireformer/spire_codex_tensor.py
?? model/spireformer/tests/test_assemble.py
?? model/spireformer/tests/test_evaluate.py
?? model/spireformer/tests/test_raw_features.py
?? model/spireformer/tests/test_raw_journal.py
?? model/spireformer/tests/test_set_selection.py
?? model/spireformer/tests/test_spire_codex.py
?? model/spireformer/tests/test_spire_codex_native.py
?? model/spireformer/tests/test_spire_codex_tensor.py
?? scripts/assemble-spire-codex-dataset.py
?? scripts/assemble-mixed-bc-dataset.py
?? scripts/audit-collector-potions.py
?? scripts/check-headless-draw-parity.py
?? scripts/collector-macos.sh
?? scripts/collector-windows.ps1
?? scripts/convert-spire-codex-replays.py
?? scripts/extract-spire-codex-combat-plan.py
?? scripts/fetch-spire-codex-replays.py
?? scripts/filter-spire-codex-replays.py
?? scripts/headless-agent-run.py
?? scripts/headless-long-path-smoke.py
?? scripts/headless-macos.sh
?? scripts/headless-play.py
?? scripts/headless-stage.py
?? scripts/headless-windows.ps1
?? smoke/SlayTheModel.Collector.Smoke/
?? smoke/SlayTheModel.HeadlessCollector.Smoke/
?? smoke/headless-play-client-smoke.py
?? src/SlayTheModel.Collector/
?? src/SlayTheModel.Sts2.DataCollector/
?? src/SlayTheModel.Sts2.ModAdapter/RelicDisplayProjector.cs
?? src/SlayTheModel.Sts2.Protocol/CombatChoiceActionBuilder.cs
?? tools/Sts2.HeadlessHost/
?? tools/Sts2.NativeWorker/NativeThroughputBenchmark.cs
?? tools/Sts2.NativeWorker/SpireCodexCombatReplayPilot.cs
?? tools/Sts2.NativeWorker/WholeRunApiProbe.cs
?? tools/Sts2.NativeWorker/WholeRunSpeedProbe.CollectorReplay.cs
?? tools/Sts2.NativeWorker/WholeRunSpeedProbe.RecordedReplay.cs
?? tools/Sts2.NativeWorker/WholeRunSpeedProbe.cs
```

如果状态与此不同，先查看 diff 并确认是不是用户或其他 agent 的新改动，不要自行回滚。

## 2. 项目目标与已经确定的方向

项目面向《杀戮尖塔 2》，当前游戏接口固定在 `v0.111.0`，主要目标是：

1. 保留清晰、稳定的局内与局外决策协议；
2. 用原生语义构建可复制战斗状态和实验性 MCTS 基线；
3. 采集人类、MCTS 和未来自博弈产生的统一整局轨迹；
4. 训练统一处理局内/局外决策的 `SpireFormer`；
5. 最终用全局 headless runner 做高速自博弈和评估。

重要产品约束：

- no-SL 场景允许看到玩家应当知道的完整集合，但抽牌堆、弃牌堆按无顺序 multiset 处理；不得泄漏未来 RNG、隐藏牌序、checkpoint 或重放前缀。
- 手动战斗决策以原生手动入口触发时的内部状态为准；即使抽牌动画尚未把新牌画到 UI，已进入内部 Hand 的牌也属于该步 observation。live 与未来 headless 使用同一状态语义。live collector 的 v5 普通 Hand 每张卡都从原生 `CardModel` 生成非 null 的费用 `display`，子费用计算失败可为 null，不代表 UI 不可见；UI holder 动画进度不决定能否产生训练步骤。仍须核对动作属于当时合法集、排除同一张已排队卡并绑定真实 `GameAction`。
- SL/no-SL 是数据语义，不应靠“是否加载过存档”猜测；必须显式配置并保留连续性证据。
- 局内与局外不能成为两个互不沟通的最终模型。喝药、留药、路线和当前战损需要在统一轨迹目标下学习。
- live 数据闭环继续保留；用户已于 2026-10-07 启动可交互原生 headless 终端工作。当前先验证完整原生跑局接口，后续高速化和数据录制复用同一 writer。
- 上传数据、匿名化、用户同意和服务端接口尚未实现，也不应在未得到用户授权前添加。

## 3. 仓库模块地图

### 3.1 稳定协议

`src/SlayTheModel.Sts2.Protocol/`

- `CombatSnapshot.cs`、`CombatStepProtocol.cs`：局内观察和 step 协议。
- `OutsideCombatDecision.cs`：局外 observation、surface、合法动作和结果协议。
- `SearchAction.cs`、`CombatActionDescriptor.cs`：搜索/执行动作描述。
- `DecisionObservations.cs`、`CombatChoiceActionBuilder.cs`：局内 `active_choice` 保存可见候选与选择约束；多卡选择只暴露一个 `ResolveChoice` 模板，实际集合写入 `action_submitted.selected_action`，不枚举组合。可取消且最少选 1 张时，取消另列一个空选择动作。原生节点不进入策略。
- `CombatObservation` 的内部 schema 现为 v5，仍能读取旧 v1/v2/v3/v4：v2 增加局内金币、充能球容量、旧 UI 手牌费用/说明、卡牌升级附魔、在场伙伴与经 UI 核对的敌人意图；v3 增加每步玩家遗物的可见计数和图标状态；v4 增加附魔可见展示语义与选择器候选卡的可选 UI 展示，并停止写未经渲染核对的卡牌动态预览值；v5 live collector 将普通 Hand 的 `display` 改为每张内部卡的原生当前能量/星星/X 费用，`description=null`、`dynamic_values=[]`。选择器候选、敌意图和遗物展示语义不变。协议与当前 headless writer 仍允许 v5 Hand `display=null`，不应把 live collector 的填充保证当成 schema 强制条件。局外 observation 为 v5，整局 `run_context` 为 v3。外层 JSONL 事件 schema 仍为 v1；旧 v2/v3 `display.dynamic_values` 与缺失字段必须由 tensorizer 掩码，旧 v4 手卡 `display` 保留原版 UI 语义，不能伪装成 v5 原生费用投影。
- `ProtocolJson.cs`：严格 JSON 序列化和校验。

协议层不能依赖 `sts2.dll`、Godot 节点或 UI 控件。策略只看协议对象；原生节点绑定只能留在 Mod 内部。当前局外动作已经加入 `BuyCard / BuyRelic / BuyPotion`，主要供只读采集器记录；自动化 Adapter 仍未实现购买执行。

### 3.2 游戏内 Adapter

`src/SlayTheModel.Sts2.ModAdapter/`

- `AdapterBootstrap.cs`、`AdapterConfiguration.cs`：Mod 入口和统一启动配置。
- `CombatCaptureService.cs`：把原生战斗状态投影为协议状态。
- `LiveCombatController.cs`：局内 `first-legal`。
- `OutsideCombatController.cs`：局外 `first-legal` 与 UI/原生语义绑定。
- `MctsCombatController.cs`：游戏内 MCTS 调度、连续思考和状态校验。
- `NativeWorkerClient.cs`、`NativeWorkerLaunch.cs`：独立 worker 通信。
- `CombatActionExecutor.cs`、`NativeActionCompletion.cs`：执行动作并等待真实结算。
- `AiStatusOverlay.cs`：右上角状态按钮，MCTS 支持 F8/点击暂停。

Adapter 三个显式配置维度：

```text
SLAY_THE_MODEL_RUN_MODE=play|train
SLAY_THE_MODEL_COMBAT_POLICY=manual|first-legal|mcts
SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY=manual|first-legal
```

`train` 目前只是预留入口；SpireFormer 尚未接进游戏。旧 `SLAY_THE_MODEL_LIVE_POLICY` 仍兼容，但新代码应使用显式 CombatPolicy。

### 3.3 搜索与原生战斗 worker

- `src/SlayTheModel.Search/`：不依赖游戏程序集的 UCT/MCTS、`ReplayMcts`、`IOmniscientEnvironment`。
- `tools/Sts2.NativeWorker/`：独立 Godot/.NET 进程，用原生战斗状态、checkpoint 和动作前缀重放提供模拟。
- `combat/`：内嵌 Combat Solver 源码，只作为可复制的原生战斗模拟后端；本项目仍使用自己的 ReplayMcts/UCT，不使用它的 Beam Search 作最终决策。

进入 `combat/` 修改前必须完整阅读 `combat/AGENTS.md`。不要把该子仓库的发布、性能或 Steam 操作规则外推到根工程，也不要随意改它固定的 source commit。

当前 MCTS 是实验性战斗内基线，不是局外或全局 MCTS：首步约 5 秒，后续利用动作/动画时间 ponder，并按完整状态指纹复用结果。当前明确面向单人铁甲战士，药水不在搜索动作集。已完成 macOS ARM64/Windows 的原生重放、选牌和跨进程校验，但没有证明全卡牌、全角色或完整跑局兼容。主要性能瓶颈是战斗前缀越来越长时的重放成本。

### 3.4 SpireFormer

`model/spireformer/`

这是纯 PyTorch、自定义实现且**没有预训练模型**的统一决策器：

- Set Transformer 编码当前无序实体集合；
- Decision Transformer 风格因果主干编码整局历史；
- 动态动作头只对当前合法动作打分；
- 局内/局外共享模型，通过 domain 与实体/动作特征区分；
- 支持 BF16、activation checkpointing、DDP、严格 checkpoint/resume、版本化 tensor shard。

固定预设参数量：

| preset | 参数量 |
|---|---:|
| tiny | 2,916,099 |
| small | 101,984,259 |
| medium | 712,616,451 |
| large | 2,044,113,411 |

本地工作树已有 raw JSONL 审计器与 shard assembler：只从 no-SL、执行成功的人工决策产生行为标签，并按 episode 切分训练/验证；source JSONL 不改写。当前语义检查会对照同一步 observation 与 run context 的完整药水 `(slot_index, model_id)` 集合，拒绝缺槽和旧压缩槽号虽存在却指向另一瓶药的步骤；也会拒绝出牌卡不在 Hand、已排队同卡仍进入合法集的步骤。默认 `bc-only` 仍将 `return_to_go=0` 用作占位。`whole-run-hp-safe-v1` 只接受完整、无回档、`whole-run-v2`、经逐步语义审计的 no-SL 整局；令开局最大生命为固定 `H₀`、`q(H)=clip(H/(0.5H₀),0,1)`，实际 HP 变化给 `0.2×Δq`，胜利终局加 1、败北加 0，`γ=1`。每步 `RTG=terminal+0.2×[q(H_final)−q(H_decision)]`，使用决策时内部状态里的 HP，因为前一动作 HP 已可见时其 reward 行仍可能晚于下一决策落盘。其他 `reward.components` 尚未标量化；所有模式的 `value_target=None`，训练用 `--value-weight 0`。旧版 episode 仍需审阅逐局排除报告。游戏内 `spireformer` policy 尚未接入，离线试训 checkpoint 仍需独立跑局验证。DDP 会在每卡复制完整参数和 AdamW 状态；Large 完整训练需要 FSDP、ZeRO 或 offload。5090 的 CUDA/BF16 smoke 仍应在目标机器实际运行，不能把本机 CPU 测试当成 5090 验证。

注意：`docs/spireformer-training-v1-development-log.md` 中“live collector 尚未开始”的旧描述已经过时；以本文件、`docs/human-data-collector-v0.1.md` 和当前源码为准。

### 3.5 独立人类数据采集 Mod（当前未提交成果）

核心：`src/SlayTheModel.Collector/`

- `CollectorEvents.cs`：版本化事件定义。
- `EpisodeStateMachine.cs`：可回放的 decision → action → execution → reward 状态机；快速输入时允许多个战斗 decision 待结算，并按 decision ID 关联后续事件。
- `JsonlEpisodeJournal.cs`：逐行 SHA-256 链、每事件 flush-to-disk、`.partial` 恢复和原子发布。
- `CompactEpisodeJournal.cs`：从已完成原始 episode 派生紧凑事件流；用可逆 observation/context 差量和已核对的步骤引用去重，不替代事实源。
- `EpisodeSession.cs`、`CollectorStore.cs`：线程安全 episode API 与存储边界。
- `HeadlessEpisodeRecorder.cs`、`WholeRunV2RewardCalculator.cs`、`DatasetManifestWriter.cs`：供全局 headless runner 复用同一 JSONL journal、奖励组件和 manifest；新增的 `tools/Sts2.HeadlessHost` 终端宿主尚未接入此录制链路。

游戏集成：`src/SlayTheModel.Sts2.DataCollector/`

- 独立产物 `SlayTheModelDataCollector.dll`，manifest 中 `affects_gameplay=false`。
- 不链接自动控制器或 MCTS，不点击、不打牌、不上传。
- `CollectorHarmony.cs`：观察真实原生语义入口。
- `CollectorRuntime.cs`：run/combat/selector 生命周期与稳定边界。
- `CollectorManualCombatInput.cs`：只为原生手动出牌、用药和结束回合入口提交的同一个 `GameAction` 标记人工证据；自动卡牌效果也会入队，不能凭队列入口直接标为 human。
- `CollectorCombatChoiceRuntime.cs`、`CollectorCombatChoiceOptions.cs`：战斗内卡牌选择候选冻结、父子 decision 结算，以及手牌确认状态、Task 结果和原生 `CombatCard` 回执核对；有界多卡路径尚未实机验证。
- `CollectorEpisodeCoordinator.cs`：episode、save/load、sidecar、恢复和最终发布。
- `CollectorCombatProjector.cs`、`CollectorOutsideProjector.cs`、`CollectorRunContextProjector.cs`：协议观察和整局上下文投影。
- `CollectorCardDisplayProjector.cs`、`CollectorVisibleIntentProjector.cs`、`CollectorCompanionProjector.cs`：live collector 的普通 Hand v5 只从内部 `CardModel` 投影当前费用，不读取手牌 UI；战斗选择器候选的可选 `display` 仍核对可见卡节点。敌方意图与在场伙伴继续按原有公开展示语义核对；敌人 `NextMove` 可能先于 UI 出现，必须核对可见图标。旧 v2–v4 手牌说明曾从已渲染 UI 读取，原始 JSONL 保持旧语义。

统一 JSONL 事件：

```text
episode_started
decision
action_submitted
execution_result
reward
manual_combat_input
manual_combat_input_outcome
save_load
coverage_gap
diagnostic
episode_finished
```

关键数据不变量：

- 局内和局外共用单调递增 `global_step`。
- 原始 `episodes/*.jsonl` 是事实来源；tensor shard 只能是可重建缓存。
- `episode_started` 局级 metadata 记录角色、进阶、UTC 开局时间、原始 run seed，以及可取得时的 Steam 昵称和 ID；Steam 不可用时保留状态而不冒充系统用户名。seed、身份、时间与 run key 都不得进入每步 observation/context.run_context 或模型特征。此条按用户 2026-09-25 的明确要求覆盖旧版“不写原始 seed”约束。
- 新采集局的 `episode_started.metadata` 写采集段起点 HP；仅原生新局入口得到确认时，`observed_from_run_start=True` 并写 `run_start_current_hp/max_hp`。旧存档或入口证据缺失不能冒充完整开局。`episode_finished.summary` 尽可能写终局 HP/maxHP 与 `terminal_hp_status`；RTG assembler 对可用锚点严格核验。旧 JSONL 没有这些字段，仍按首决策与 `hp_delta` 重建并在报告中标注推断来源。
- 每行有 `event_sequence`、`timeline_generation`、前一事件 hash 和当前 hash。
- 事件写入后立即 `Flush(true)`；结算后从 `_open/*.jsonl.partial` 原子移动到 `episodes/*.jsonl`。
- 新发布的正式文件名由 Steam ID、角色、进阶、UTC 时间戳和防碰撞 episode ID 构成；临时 partial 与 sidecar 继续按 episode ID 恢复。旧 UUID 命名的已发布 JSONL 保留原名，并必须继续支持按 episode ID 读取。文件名不替代内部 hash 链和 episode ID。
- 损坏但换行完整的 partial 移入 `episodes/_quarantine/`，不能进入训练。
- 只有原生 save fingerprint 与持久 sidecar cursor 同时精确匹配才续写同一 episode。
- `auto` 信息模式写 `unknown`；`no-sl` 的精确 checkpoint 续玩是 `resume`；`sl` 加载是 `rewind`。
- 一旦 no-SL 连续性无法证明，后续单步降级为 `information_regime=unknown`。
- pending、unknown load、rewind、不确定执行或 `coverage_gap` 都会阻止可靠整局 RTG/value target。`value_target_valid=true` 还须叠加逐步语义检查；当前 RTG 模式不会训练独立 value head。
- 只有 `applied` 或 `observed_transition` 可以进入行为克隆；cancelled/failed/stale 不进入 loss。
- `manual_combat_input` / `manual_combat_input_outcome` 通过 `intent_id` 与 `native_action_id` 保存原生手动输入和结果；它们的 `global_step=null`，并以 related decision/attempt ID 对照结构化 step。快速点击若可冻结合法动作且与同一原生 `GameAction` 精确匹配，可写独立排队 decision；`observation.pending_manual_actions` 只含玩家自己已提交的动作，不含原生 ID 或时间戳。无法证实点击时合法集合时仍不补造行为克隆样本。
- snapshot 与 `episode_finished` 统计原始输入总数、未配对数、未结构化总数和未结构化且有执行风险的数量。只有未配对或 unsafe 数非零时，原始输入本身阻止整局完整；执行前干净取消的输入留作审计。
- 旧轨迹中 `transition_contaminated_by_queued_manual_input` 与空 `next_state_fingerprint` 仍表示父动作的 reward/transition/value 不可训练。新代码在下一条原生手动动作开始时先结算前一条的奖励；不得回写旧 JSONL 来伪造这条边界。
- 未支持交互必须写 `coverage_gap`，不能静默把 episode 标成 complete。

采集器配置：

```text
SLAY_THE_MODEL_COLLECTOR_ENABLED=0|1
SLAY_THE_MODEL_DATASET_DIR=/absolute/path
SLAY_THE_MODEL_INFORMATION_MODE=auto|no-sl|sl
SLAY_THE_MODEL_COLLECTOR_ACTOR=human
```

采集器会检查相邻 Adapter runtime JSON、`SLAY_THE_MODEL_COMBAT_POLICY`、`SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY` 和旧 `SLAY_THE_MODEL_LIVE_POLICY`。如果发现 first-legal/MCTS，会把 actor 标为 `automation_or_unknown`，不能伪装成人类示范。

v0.1 已结构化覆盖：局内出牌/目标/药水/结束回合；地图、事件、休息点、奖励、卡牌奖励、商店购买/删牌/离开、宝箱、原生单卡/网格/遗物选择，以及 run/combat/save/load/terminal 边界。战斗中的手牌、牌堆和原生单卡选择器已有实机证据。当前工作树把局内/局外多卡改为“候选列表 + 一个合法选择模板 + 提交时的真实集合”；局外 observation v5 的 `card_selection_options` 保存候选，局内继续用 `active_choice.cards`。旧组合枚举 JSONL 原样保留，不能视为已被修复。Rewards 顶层稳定边界下的独立弃药已有两次实机结构化证据；局外用药、重叠药水点击及商店药水路径尚待验证。Crystal Sphere 已在 `2d9fc925...` 留下完整结构化实机步骤，并由无场景原生重放逐格核验；工具切换/快速连点仍无样本，通用附魔页新路径仍需实机验证。

当前明确不完整：战斗多卡候选缺少原生 CombatCard ID 时仍记 gap；局内/局外多选若不能冻结候选、缺少人工确认、原生回执或 Task 结果不一致，也必须记 gap。卡牌奖励 reroll/alternative、其他复杂事件小游戏、未知 Mod 页面仍未覆盖。木札 20 张候选选 1–3 张、浸水抄写室 12 张候选选 2 张都只产生一个选择模板；实际集合由提交事件记录，不再枚举 1350/66 个动作。`NDeckTransformSelectScreen` 的 `TO_TRANSFORM` 新路径从原生 `CardSelectCmd` 过滤后的选择器 `_cards` 与选择约束冻结候选及 min/max，核对卡对象点击、预览页最终确认、Task 与 `DeckCard` 回执；不以动画中的 UI holder 可见性作为冻结门槛。该路径已通过 build、collector smoke 和独立 Harmony ABI 检查，尚未实机验证；旧 `4be...`、`4177...` 缺口不可回填。

首次实机跑局揭示了采集时序问题，2026-09-25 已完成以下修复；第二份实机文件使用这些修复后的 `whole-run-v2`：

- 卡牌奖励屏幕 `_extraOptions` 的普通 `Skip` 不再误判为不支持；以原生 `_options` 和 `_extraOptions` 的实际顺序记录完整合法集，实际点击 reroll/其他 alternative 才记 gap。
- 成功动作先暂存，待下一个稳定的局内/局外决策、子选择器或终局才连续写 `execution_result` 与 `reward`；奖励版本升为 `whole-run-v2`。`SaveRun` 在地图楼层更新前发生时不再提前结算，也不发布未完成事务的恢复游标。
- 战斗中无玩家合法动作的中间状态不再写大量 `combat_decision_cache_failed`；当时尚未结构化的 `CombatCard` 人类选择会记 detached `coverage_gap`。

第二份实机暴露问题后，2026-09-26 的工作树新增了以下修复；后续实机文件提供了部分验证：

- 只把原生手动入口提交的同一个 `GameAction` 视为人工动作；执行中的自动或来源不明动作记诊断，无法归属且无父动作时记 detached `coverage_gap`，不再让 `combat_action_without_decision` 作废正在结算的父动作。
- 手动入口执行前重新捕获当前前态和合法动作，并用 transpiler 将其绑定到真实提交的 `GameAction`；药水会在入队事件前设置 `IsQueued`，不能等到该事件再捕获。若前一动作还在执行，没有稳定前态就记 detached gap。原生 `GameAction.Cancel` 在入队通知之后发生时，为待处理动作写 `cancelled` 或不确定失败并清掉悬挂的提交记录。
- 战斗内单卡 selector 在人工点击/确认前冻结可见候选，创建子 `decision` 和合法 `ResolveChoice`，用 selector Task 结果及可取得的原生 `CombatCard` 回执校验选择；父动作在子选择边界结算，晚失败以关联的 detached gap 排除对应 BC 标签。
- selector Task 同步完成时先 drain，再处理下一个战斗动作或缓存，防止跨选择器串位；多选仍明确记 gap。

`ff7431...` 实机揭示快速输入与临时生成卡选择缺口后，2026-09-27 的工作树进一步允许点击时完整合法集合对应的快速输入直接形成排队的结构化 decision/action，按各自的 decision ID 结算；不可核实的输入仍留原始事件和实际执行时的 gap。生成卡单卡选择采用选择器局部候选序号和真实对象身份核对；无法匹配的原生 `Index/Indexes` 回执会明确记 gap。headless 记录封装与 live 共用 core writer、manifest 和 `whole-run-v2` 奖励计算器。先前 `9ecfc...` 实机已显示 80 个排队的结构化输入和 2 个成功关联的原生 `Index` 回执，但未覆盖路径仍产生 gap。

先前 `39445f...` 实机又揭示 `phase=Start` 输入：四张卡（`BATTLE_TRANCE`、`BLOODLETTING`、`FEEL_NO_PAIN`、`DARK_EMBRACE`）和一瓶 `HEART_OF_IRON` 药水在点击时排队、到 `Play` 才实际执行。旧实现为 `Start` 增加原生 `CanPlay`/目标、药水和结束回合按钮的候选冻结，又要求 UI holder 与内部 Hand 按对象身份一致。`24b...` 与 `ba8...` 的快速连点表明此 UI 门槛会漏掉真实执行的输入：已排队的牌可能离开 holder，新抽牌也可能先进入内部 Hand 后完成动画。按用户新的数据契约，本地采集改以手动入口瞬间的内部 Hand、牌堆和合法动作建立 `Start`/`Play` 观察；不再核对整手牌 holder。`Start` 合法集只列内部 `CanPlay` 卡与可用药水，不列 EndTurn；v0.111.0 原生 `TurnStarted` 转入 `Play` 后按钮才启用，异常 `Start` EndTurn 按不在合法集记 gap。live collector 的普通 Hand 每张内部卡由原生 `CardModel` 计算费用，v5 `display.description=null`、`dynamic_values=[]`，不再记录 UI 卡面动画状态。已排队的同一原生卡 ID 仍从候选动作中排除，实际动作仍须与同一 `GameAction` 精确匹配。不得用执行时 `Play` 状态倒填点击时前态。共享自动策略 `GetLegalActions` 仍限制 `Play`，headless writer 沿用同一事件契约。新边界尚未安装或实机验证，旧 JSONL 不回填。

随后 `435800f...` 实机在同一命名格式下发布：4 次 `Start` 快速出牌均形成独立决策、执行结果和奖励；整局 730 个决策配对完整、无 coverage gap，胜利且 `value_target_valid=true`。该局只验证了旧 combat observation v1 的出牌路径；当时尚未覆盖 `Start` 用药、抽牌动画全部边界和多选。

2026-09-28 工作树增加 combat observation v2：玩家 gold 与 orb capacity；所有牌的升级/附魔，以及 UI 可见手牌的费用、X/星星成本、动态预览值和已渲染本地化说明；当前在场伙伴的归属、HP/格挡/powers（核对友方 roster 与宠物列表，非 roster 候选还须 UI 节点可见）；敌人 UI 已显示且逐一核对的意图及攻击数字。已有玩家/敌人 HP、格挡、powers、药水、牌堆集合与充能球继续保留。`Damage`/`Block` 预览键受战斗修正，但尚未证明与所有卡牌说明文字逐项相同，暂不单列为精确显示伤害/格挡。不可见或核对失败的 UI 内容以 null/`not_visible`/`unverified` 表示，不能猜测隐藏 `NextMove`。`CombatSnapshot` 与原生 worker 指纹未改变。`36df...` 实机证实 gold/capacity/意图字段入盘，但被点击卡牌在 461 次普通 `Play` 决策中缺少 `display`；随后将手动选中的原生 CardModel 传给可见 NCard 核对。离线 IL 证实 `CardModel.TryManualPlay` 调用 `EnqueueManualPlay` 早于 UI `Cleanup`，`NPlayerHand.GetCard` 会搜索拖出后暂存的 `_holdersAwaitingQueue`。`59261c...` 实机的 482 次实际出牌、`fcbb...` 实机的 404 次及最新 `dd28...` 实机的 161 次已提交出牌，所选卡均有 `display` 和说明。

随后战斗 observation 升 v3，为每步玩家遗物增加可选 `display`：可见图标状态、融化/蜡化、仅在 `ShowCounter && RunManager.IsInProgress` 时按 UI 规则应显示的计数，以及原生主悬停说明。局外 observation 升 v2，`context.run_context` 升 v2，三处共用同一展示语义投影；新数据不再无条件写 raw StackCount、IsUsedUp、Status、DisplayAmount。旧 run_context v1 的遗物字段未经 UI 可见性验证，assembler 不得直接作为 no-SL 特征。`display=null` 和 `visible_counter=null` 必须与真实显示零区分；额外悬停提示中还存在动态状态说明和卡牌预览，尚未结构化。投影未逐帧核对遗物栏节点是否刷新。Headless runner 将来须提供等价公开展示语义或缺失 mask，不读内部计数。先前 `fcbb...` 实机确认战斗和局外遗物实例分别有 5048/5048、2179/2179 个 `display`；不能据此声称所有遗物视觉边界已覆盖。旧 JSONL 不修改。

`36df...` 的 17 个单卡 `combat_index_choice_without_selector` 都有已冻结 `active_choice`、原生合法 option index 和后续成功选择，属于 native choice ID 在 selector 打开后才预留或未被捕获的误报。工作树现为所有已冻结单卡选择保留临时 ticket；晚到的预留 ID 只绑定同一父动作、仍在进行的唯一选择器，已完成或 Task 已完成但尚未清理的选择器不得抢下一次 ID；未绑定 ID 的 Index 回执只可与同一父动作、已有人工输入证据、仍在进行的唯一合法候选关联，之后继续与 selector Task 的对象身份/option index 核对。预留 ID 只在活跃战斗内接收，战斗开始/结束清除暂存值，避免跨战斗误配。人工选择若最终没有原生回执，仍记 `combat_choice_native_result_missing` 缺口，不得静默标为完整。随后 `59261c...` 实机有 3 次 Index 回执成功关联、无同类误报；不可事后修改原始文件。

`41774d...` 的 Toasty Mittens 97 次选牌已有冻结候选、人工选择 Task 和原生 `CombatCard` 回执，所选卡牌 ID 逐次一致；旧代码只按原生 choice ID 精确关联，选择器 ticket 的 ID 留空，于是每次产生 `combat_card_choice_without_selector` 与 `combat_choice_native_result_missing` 两条缺口。本地手牌选择现在从单人战斗的内部 `PlayerCombatState.Hand.Cards` 按原生 `SelectCards` filter 冻结候选，不以 UI holder 或抽牌动画作为候选门槛；选择器卡面 `display` 仍为可选的 UI 展示证据。`CombatCard` 回执仍优先按精确 choice ID 关联；缺 ID 时，仅在同一 run generation、战斗、非空父动作下存在唯一未绑定 ticket、有人工 `Prepared` 证据、且完成的 selector Task 所选卡对象可映射至候选并与回执的原生卡 ID 完全一致时，才关联已经完成或仍在进行的 ticket。同一父动作打开后续选择器时，旧无 ID ticket 不再有兜底资格，即使新选择器冻结失败；预留、打开及 reservation 被 guard 忽略时均写只读诊断。`active_choice.choice_id` 在缺原生 ID 时是合成的协议标识，未来在线执行器不能直接当作原生 choice ID。无法唯一核对或回执缺失仍记 gap。该修复只影响后续采集，尚未安装或实机验证；旧 JSONL 和派生 BC 步数不回填。

卡牌旧 `energy_cost` 来自原生快照的可空费用覆写：当前全修正费用等于标准费用时是 `null`，不是 0 或未修正。旧 v2–v4 的 `display.energy_cost` 对 UI 卡面保存当前全修正费用；旧 v2/v3 的 `display.dynamic_values` 曾无条件写入所有原生 `PreviewValue`，某些值没出现在卡面文字中，不能直接训练。v4 将动态数组置空，仅保留可见卡牌已渲染的说明。live collector 产出的 v5 普通 Hand `display` 对每张内部卡非 null，原生计算当前能量/星星/X 费用，`description=null`、`dynamic_values=[]`；这些空值并不表示卡牌无效果。旧版本字段须由 assembler 按版本掩码，原始 JSONL 不回写。只凭 model ID、升级和双方 powers 仍无法重建所有卡牌效果：卡实例 BaseValue、临时费用、遗物内部计数、历史与目标也可能影响结果。

先前 `59261c...` 实机的 3 个真实缺口是开局卡包、事件选 2 张和移除 3 张牌。旧版局外多卡曾枚举最多 3 张、4096 个集合；2026-09-30 本地改为 observation v5 候选列表、一个 `ChooseCardSet` / `RemoveCardSet` 模板与提交时的真实集合。人工点击、原生 Index/DeckCard 回执和 Task 结果仍须精确核对。旧实机文件不回填，新路径尚未安装或实机验证。

战斗多选从 `NPlayerHand.SelectCards` 的可见候选与 `CardSelectorPrefs` 建立子决策，按候选数裁剪原生最大选择数。旧版曾枚举最多 4096 个完整集合；2026-09-30 本地改为一个 `ResolveChoice` 模板，提交时附上按原生 CombatCard ID 区分的真实集合。手动确认的原生已选对象、selector Task 和 `PlayerChoiceReceived` 回执继续核对。0 张成功确认只有在最少选 0 张时才属于模板；最少选 1 张且可取消时另列取消动作。Gambler's Brew 手牌多选新路径仍待实机验证，旧缺口不回填。

原生手牌选择即使选满 `MaxSelect` 也只会更新选中列表和确认按钮，不会自动完成 Task；要求手动确认的多卡选择必须有确认按钮入口证据，不能仅凭“选满”推断玩家确认。`CardSelectCmd.FromHand` 在真正没有合格卡时会先返回空结果，不打开 `NPlayerHand.SelectCards`；若已进入手牌 UI 却冻结到零候选，现记 `combat_hand_choice_empty_interface_mismatch` gap，不能静默写成自动完成。

不要回归以下已修复的原生语义问题：

- `NMerchantInventory.Close` 只是关库存 overlay，不是离开商店。真正离开分别 hook `NMerchantRoom.HideScreen` 和 `NFakeMerchant.HideScreen`。
- 首次商店/奖励 Proceed 可能只弹 FTUE 而不推进；`NMerchantFtue.Create` 和 `NCombatRewardFtue.Create` 会把 in-flight 动作记为 `Cancelled`。
- 宝箱 `ProceedButton.IsSkip` 会同步调用 `PickRelicLocally(null)`；只能由 relic synchronizer 记录一次，不能再写第二条 treasure proceed。
- selector Task 可能同步完成并立即打开下一个 selector；所有 selector prefix/Prepare 必须先 drain 已完成 selector，避免新 gap 作废旧 decision。
- 异步父动作晚失败且子 decision 已开始时，coverage gap 必须 detached，不能误伤当前子 decision。
- 晚失败若发生在成功结果落盘前，应把暂存结果降级为 `failed`；若成功结果已落盘，detached gap 的 `related_decision_id` / `related_attempt_id` 必须供 assembler 排除对应 BC 标签。
- run generation guard 必须阻止旧 episode 的 deferred callback 污染新 episode。

### 3.6 终端界面与无界面整局性能探针

- `tools/Sts2.HeadlessHost/` 是可玩的终端原生交互原型：`scripts/headless-macos.sh` / `scripts/headless-windows.ps1` 准备并启动独立 Godot 进程，`scripts/headless-play.py` 通过本机 loopback JSON 读取状态和发送动作。它加载完整 `NGame` 场景，按 `ActiveScreenContext` 和节点回调处理地图、战斗、事件、商店、奖励等；无图形窗口仍会初始化音频，用户曾听到声音。这不是对现有 Steam 游戏状态的镜像，也不是高速自迭代环境。当前 JSON 接口只服务终端操作，未接 `HeadlessEpisodeRecorder` 或 SpireFormer。实机验证范围、最终版本尚未二次实跑的限制和启动方法见 `docs/headless-terminal-v0.1.md`；特殊事件的静态接入与实测状态分开记录在 `docs/headless-event-coverage-v0.111.0.md`。
- `tools/Sts2.NativeWorker/NativeThroughputBenchmark.cs` 借现有 `NativeSession` 在不加载 `NGame` 的 Godot `--headless` 进程中跑原生战斗。2026-10-08 macOS ARM64：一个热身局后，三个固定 `CULTISTS_NORMAL` 战斗分别为 24/20/19 个决策、41.4592/26.5295/33.1307 ms 动作结算时间，即 578.88/753.88/573.49 决策/秒，均获胜。结果文件 `artifacts/native-host/native-throughput.json` 被 Git 忽略。计时仅覆盖战斗动作提交到下一决策点；不能据此宣称完整跑局、模型推理或采集落盘的吞吐量。复跑命令见第 6 节和 `docs/headless-performance-gate-v0.1.md`。
- `tools/Sts2.NativeWorker/WholeRunApiProbe.cs` 用于只读查看本机 v0.111.0 原生 API 和关键调用链，输出 `artifacts/native-host/whole-run-api-probe.txt`（忽略文件）。默认 `WholeRunSpeedProbe.cs` 用 `SeedHelper.CanonicalizeSeed` 规范化输入，按终端宿主的隔离 profile epoch 配置生成玩家解锁状态，并启用原生发现顺序规则，再建立 run；实测涅奥首选 `SCROLL_BOXES`、第一幕 65 节点/77 连线、首战 `TOADPOLES_WEAK` 获胜并领取奖励、移动到下一节点，输出 `canonical-prefix-complete`。首战初始敌人 HP、玩家 HP 与牌组均和完整场景宿主对齐，8 个决策点的同动作抽牌对照由 `scripts/check-headless-draw-parity.py` 复跑。规范化路线设置 `STS2_PROBE_ROUTE=event` 时沿另一条合法连线进入自然问号事件；历史 `PRECISE_SCISSORS` 删牌、`SHRINKER_BEETLE_WEAK` 与 452.5 ms 最小路径属于显式 `whole-run-speed-probe-legacy`；`STS2_PROBE_ROUTE=shop|rest` 目前也只支持该 legacy 模式。
- 同一自然路线的下一节点是 `AROMA_OF_CHAOS`。探针调用其 `LET_GO` 选项，通过原生 `CardSelectCmd.FromDeckForTransformation` 单选 `STRIKE_IRONCLAD`，原生变形后牌组 10 张不变，选中卡的对象身份从牌组移除，生成卡 `TREMBLE` 在牌组中，事件标记完成。随后 `NIBBITS_WEAK` 战斗 9 个决策获胜，HP 67；原生奖励令牌组 10→11、金币 116→133、药水 1→2。没有使用 `EnterRoomDebug` 或直接修改卡牌。
- 下一事件 `MORPHIC_GROVE` 的 `GROUP` 通过原生选择器提交两张不同对象的 `STRIKE_IRONCLAD`；两张旧牌离开牌组，生成 `JUGGLING` 与 `SWORD_BOOMERANG`，牌组仍 11 张、金币 133→0。再下一事件 `SELF_HELP_BOOK` 的 `READ_THE_BACK` 通过原生选择器给一张 `STRIKE_IRONCLAD` 加 `SHARP`，附魔卡数 0→1。第 7 层 `BYGONE_EFFIGY_ELITE` 经 21 个决策后玩家 HP 0，`CombatManager.IsInProgress=false`、`RunManager.IsGameOver=true`；三次输出 `natural-run-defeat`、`error=null`、`gameSceneLoaded=false`，从创建 run 到败局分别约 491.5/531.3/485.7 ms。该历史路线现在用 `./scripts/native-worker-macos.sh --mode whole-run-speed-probe-legacy --timeout-seconds 120` 复跑，结果在忽略文件 `artifacts/native-host/whole-run-speed-probe-legacy.json`。这些时间不含进程启动、构建、终端、协议投影、模型推理或 JSONL 落盘，也不代表同输入种子的正常游戏路线。
- 商店分支经五场原生战斗抵达第 7 层 `MerchantRoom`，HP 39、金币 175。原生购卡成功，金币 175→137、牌组 14→15；原生删牌服务与选择器成功，金币 137→62、牌组 15→14，选中卡对象移出牌组。无 `NRun` 时购买方法不会调用 UI 的 `NMerchantInventory.OnCardRemovalUsed`；原生 UI 回调的最终逻辑是 `MerchantCardRemovalEntry.SetUsed()`，探针在购买成功后调用并核对 `Used=true`、`IsStocked=false`。药水槽 3/3 已满时原生药水购买返回 `false`，金币和药水不变；之后进入下一层精英战房间。legacy 复跑结果在忽略文件 `artifacts/native-host/whole-run-speed-probe-legacy-shop.json`，不代表有空药水槽时的购买、遗物购买或其他商店布局已验证。
- 休息点分支同样经过五场原生战斗，以 HP 39 抵达第 7 层 `RestSiteRoom`。原生按钮实际调用 `RestSiteSynchronizer.ChooseLocalOption`，探针用同一入口回血 39→63，记录所选索引并清空可选项；转场后获胜 `FOGMOG_NORMAL`，第二个休息点再次回血 57→80。第 10 层宝箱经 `TreasureRoom.DoNormalRewards()`、`DoExtraRewardsIfNeeded()` 给出 `BEATING_REMNANT`；`TreasureRoomRelicSynchronizer.PickRelicLocally(0)` 经过原生动作队列触发 `RelicsAwarded`，无 UI 探针读取获奖角色与遗物后调用普通 UI 所用的 `RelicCmd.Obtain`，角色遗物数 2→3，再转入下一个地图战斗节点且保留遗物。legacy 复跑结果在忽略文件 `artifacts/native-host/whole-run-speed-probe-legacy-rest.json`；锻造、多人宝箱与其他奖励布局未验证。
- 已解决的历史阻挡：直接反射调用 `OnChosen` 会跳过 `EventOption.Chosen()` 设置 `WasChosen` 和执行 `BeforeChosen` 的语义；无 selector 时 `CardSelectCmd.FromDeckGeneric` 会尝试创建 `NDeckCardSelectScreen`，在无场景时抛 `InvalidCastException`。探针现调用 `Chosen()`，用 `CardSelectCmd.PushSelector(new AutoProbeCardSelector())` 接住原生候选与选择数，编译错误通过引入 `MegaCrit.Sts2.Core.TestSupport` 解决；战后卡牌奖励也由同一 selector 选择原生候选，并核对牌组变化。不能据此推断所有事件选择器都已覆盖。
- 战后奖励有额外的 UI 推进入口：普通游戏由 `NCombatUi` 在胜利动画后调用 `CombatRoom.OfferRoomEndRewards()`。无 `NCombatUi` 的探针在原生战斗结束且房间标记 `IsPreFinished` 后显式调用该原生方法；`RewardsSet.Offer()` 在 TestMode 中结算原生奖励。没有直接改金币、药水或牌组。长路径的满槽药水采用原生剩余奖励跳过动作，并在输出保留 warning；不能把 TestMode 先记录的未完成错误隐藏成干净结算。
- 同种子入口及隔离 profile 解锁状态、原生发现顺序规则已统一；涅奥、第一幕地图、首战遭遇/初始状态、固定动作下的 8 次抽牌、战后奖励候选、首个自然 `SPIRALING_WHIRLPOOL` 的 `Observe` / `Drink` 两分支，以及下一场 `CORPSE_SLUGS_WEAK` 的入口状态已与完整场景宿主逐项对照。`Observe` 使用原生附魔选牌，`Drink` 回血；两份忽略文件 `artifacts/headless/event-parity-*.json` 的 `eventRoute.matches=true` 且 `nextRoom.matches=true`。此后另用 `scripts/headless-agent-run.py` 记录的一条原生终端败局，已经在 `WholeRunSpeedProbe.RecordedReplay.cs` 中按同动作重放到第 17 层；逐战斗决策与地图前状态通过，详情见上文和 `docs/headless-performance-gate-v0.1.md`。下一道门槛是扩展其他种子/角色与房间分支、消除重复卡跨进程身份歧义、覆盖完整胜局，并量整局时间分布、并行规模、协议投影和共享 JSONL writer。终端宿主仍作原生交互对照；这条轨迹不等于通用高速 runner 已完成。
- `WholeRunSpeedProbe.CollectorReplay.cs` 读取现存人类 A0 journal 和源玩家的只读 modded progress，在同一个无 `NGame` run 中顺序执行无缺口前缀。`1ddd1912...` 已两次从 step 0 重放到 step 700，并在停止前核对 step 701 gap observation；21 场战斗、两次跨幕、事件、商店、锻造和宝箱均在后续公开状态汇合。TestMode 商店必须补回正常游戏三次药水价格 RNG；有 `ParentEventId` 且要求恢复的事件战斗必须走 `ProceedFromTerminalRewardsScreen()`，使原生 `EventModel.Resume` 结算“战损木偶”的随机升级。不得越过 step 701 猜测购买动作，也不得把此结果称为完整胜局重放。
- 同一 journal 入口现能从无顶层步号的 coverage gap 中，通过 `related_decision_id` 等关联恢复首个可定位边界。`2d9fc925...` 已两次重放到 step 494，并严格核对 step 495 动作前的药水槽等公开状态；原生 Crystal Sphere 的三次翻格、完整可见棋盘、奖励及退出已在 step 459–466 对齐。奖励页 discard 必须按记录动作顺序执行，不能仅重放 claim；召唤怪目标不能依赖 `CombatState.Enemies` 与 journal 的列表顺序。该源轨迹 step 495 有缺失人工弃药，仍只算无缺口前缀。

## 4. 当前测试证据

2026-09-30 新增 `model/spireformer/spireformer/raw_journal.py` 只读审计入口：按原始字节验证每行 SHA-256、前序链、连续事件序号、episode ID、timeline generation，并关联 decision、attempt、执行结果、reward、save/load、coverage gap 与原生手动输入。8 个独立单元测试通过；先前 16 份正式 JSONL 和随后新增的第 17 份 `4be...` 均能严格加载。亡灵契约师胜利局 `148a...` 审出 1015 个决策，其中 1014 个成功 no-SL BC 候选；短弃局 `f64f...` 有 6 个 BC 候选、0 个整局 value 候选。这里只证明事件结构与关联可回放，不证明旧观察里的药水槽位、排队合法集或每个模型特征都具有正确语义。

新亡灵契约师局 `4be275a1f2554b938c3f90908c02ef23` 的 1954 行、逐行 SHA-256 链、341 组 decision/submission/result 全部通过只读审计；339 个成功动作有 reward，2 个结果为正常 `cancelled`，248 组原始手动输入/结果配对，所有决策均为 `no_sl`，无 save/load/rewind。265 个战斗观察为 v5、76 个局外观察为 v4；药水审计的 265 个战斗决策在观察槽号、同一步 run context、合法动作与实选用药上均无错位或无法核对。用首轮训练集拟合的 `sts2-raw-features-v2` 词表实际编码 339 个 BC 步成功，按真实缺口切成 7 段；没有集合选择标签。事件序号 961 有 `multi_card_selection_options_unavailable`：局外 `TO_TRANSFORM` 的 15 张候选未能冻结，随后原生 `DeckCard` 回执选了 2 张，不能倒推为子决策。该局终局 defeat、`completeness=incomplete`、`value_target_valid=false`；仅可保留已完整配对的动作作独立同角色 BC holdout，不能作整局 value 或多卡选择验收。

`collector-raw-bc-v3` 已从四份经审阅原始局组装 `artifacts/tensor-v2/bc-pilot-20260930-v3`：train 2 局、1545 个 BC 步和 14 个集合标签；val 1 局、669 步和 2 个集合标签；test 1 局、219 步、0 个集合标签。独立 `artifacts/tensor-v2/necrobinder-holdout-20261001-v3` 复用训练词表，仅有 `4be...` 的 339 个 BC 步、0 个集合标签。四个 split 的 shard 均以 `verify_hashes=True` 重读，RTG 全为 0 占位、value target 全为缺失。v3 组装报告记录 `feature_spec_source=fit_train_only` / `external`，训练与 holdout 的词表哈希一致；本轮特征宽度为实体 596、动作 553。旧 `collector-raw-bc-v2` 产物是药水完整集合对照加入前的试验缓存，不应与 v3 混称。

v3 数据上已完成 Tiny 200 个 optimizer step 的本机 CPU/FP32 BC 试训，checkpoint 为 `artifacts/train-runs/tiny-bc-pilot-20260930-v3/checkpoint-latest.pt`，训练设 `value_weight=0`、`entropy_weight=0`。整局隔离评估均报告 `episode_split_verified=true`：Ironclad val 的 625 个多合法动作步骤 top-1 为 45.12%（first-legal 25.44%、uniform 20.94%）；Silent test 的 192 步为 39.06%（21.88%、23.71%）；新亡灵契约师 holdout 的 314 步为 50.96%（28.98%、21.74%）。val 仅有 2 个集合标签，集合 exact 为 0；value 标签为 0。`model/spireformer` 全套 pytest 116 项通过，`git diff --check` 通过。这些只证明当前离线行为模仿管线与少量整局隔离样本上的准确率，不能推断游戏内胜率或 5090 性能；游戏内 `spireformer` policy 仍未接入。

2026-10-01 的首轮 `whole-run-hp-safe-v1` 曾选用两局当时标记完整的铁甲轨迹。胜局 `433d5532920444a1afac0716251e12c4` 的事件审计显示 5707 行、985 个决策，其中 983 个成功动作可入 BC、2 个取消；全部为 no-SL、无 coverage gap，终局 win、`completeness=complete`、`value_target_valid=true`。开局生命/最大生命 80/80，整局 `hp_delta` 累计 −52，重建终局生命 28；初始安全线 40，首步 RTG 0.94。败局 `32a3822509ec4c9fa8d00017103daee6` 有 228 个决策、228 个成功动作标签，`value_target_valid=true`。两个旧文件都没有独立终局 HP 字段交叉核验。**后续语义审计推翻了胜局的完整性判断**：step 270 的卡牌奖励选牌伴随 `potion_count_delta=-1`，却没有局外用药/弃药 decision。新局 `ec731...` 的 step 79/608 也在领奖励/继续动作中吸收药水减少。原采集器的 `value_target_valid=true` 与当时的检查漏掉了这类人工操作；旧 JSONL 不回填。raw auditor 排除受影响 BC 步，RTG assembler 拒收整局。`32a...` 未见同类减量，但单独只有败局，不能作为预期的胜败 RTG 训练集。旧 BC-only 产物也不得作为本模式的 resume 输入。

2026-10-02 最新三局 `2085af58548044b9b192db449a6dbbf0`、`1ddd1912ef634cbeb9d331f52b79cf24`、`2d9fc925402f440eaba2c30e5c214966` 都是 no-SL 铁甲胜局，SHA-256 链与事件配对完整，分别有 932/787/508 个决策、922/781/502 个 BC-only 可用步骤。`2085...` 的 3 次局外药水点击与尚未结算的父动作重叠；`2d9...` 有 1 次买遗物期间的弃药；`1ddd...` step 701 的商店购买点击未匹配合法动作，前后金币、卡组、遗物和药水未变，但旧事件缺目标与原生 `Task<bool>` 返回值，不能推定为被游戏拒绝。三局都有 gap、`completeness=incomplete`、`value_target_valid=false`，不能作整局 HP RTG。Rewards 顶层的独立弃药在 `2085...` step 408 与 `2d9...` step 404 已正确结构化，所选槽位与后续库存一致；局外用药尚无成功结构化的实机样本。原始 JSONL 不回填。

当前工作树的局外药水路径以 v0.111.0 原生状态和页面核对为准：普通 Rewards 点击的合法集包括 ClaimReward、Proceed 与合规的 Use/Discard，药水候选写真实槽号和模型 ID，提交/结果绑定同一个原生 `GameAction`。针对上述快速重叠输入，若有未结父动作则必须唯一且已被原生接受；同时须无选择器、执行器空闲、原生动作队列为空，且顶部 Rewards 或商店页面与药水栏可核对，才能把下一次药水点击作为稳定边界先结算父步，再冻结新决策。任一条件不满足仍记 `coverage_gap`，并记录分项阻挡诊断，不从后续库存净减少倒填标签。商店未匹配购买延后至原生 `Task<bool>`：只有点击与结果边界稳定、无其他待处理操作、明确 `false` 且状态和库存均未变才降为 `diagnostic`，其他情况保留 gap。core 的局外排队日志 API 已有，Runtime 不靠它推断不稳定边界。此轮新边界与商店判定尚未安装或实机验证；旧 JSONL、shard 和 checkpoint 保持原样且首轮产物仍作废。

历史产物 `artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1/train` 曾包含 1211 个动作标签、22 个轨迹窗口、schema v2、reward version `whole-run-hp-safe-v1`；胜局 RTG `0.94–1.135`，败局 RTG `−0.20–−0.05`、终局 HP 0。Small 使用该特征宽度的参数量为 103,301,379；本机 CPU/FP32 曾完成 20 个 optimizer step（batch 1、window 64、value/entropy weight 均 0），checkpoint 为 `artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1/checkpoint-latest.pt`。**shard 与 checkpoint 均已作废，不得用于正式训练、续训或评估。**末步 `policy_loss=1.0698057` 和训练集 `--conditioning recorded --allow-training-dataset` 的整体 top-1 56.65%、多合法动作 top-1 52.91%（1115 步）只保留为当时链路执行记录，不能当作可靠模型指标。该检查还使用真实未来 RTG、无整局隔离（`episode_split_verified=false`）；原始文件保留供审计。

2026-09-29 Crystal Sphere 工具/格子/离开采集、局外 v3 可见棋盘与异步翻格屏障加入后，`./scripts/macos.sh --action test`、`./scripts/collector-macos.sh --action test`、局外协议 smoke、直接运行的 `HeadlessCollector.Smoke`、DataCollector 和 ModAdapter Release 构建、`git diff --check` 均通过。独立临时 ABI harness 在本机 `sts2.dll v0.111.0` 应用了四个 Crystal Sphere 原生入口补丁，并核对了界面与物品节点的私有字段。smoke 验证 v2 非 Crystal 页面保持旧 JSON、v3 棋盘可往返/影响指纹、隐藏物品或视觉 ID 被拒绝；headless smoke 额外用同一 writer 写出 v3 Crystal 决策、执行结果和奖励并回放。原生 IL 与只读复核支持“翻开后图标渐显才可记录物品类别”的门槛；这些离线证据不能替代游戏内画面、快速连点和奖励边界复测。新 DLL 未由 agent 安装，旧 `8adb...` JSONL 不回填。

2026-09-29 旧枚举版战斗多卡集合动作修复后，通过 collector smoke、DataCollector Release、主工程测试、HeadlessCollector smoke 和 Harmony ABI 检查；旧 smoke 覆盖 5 张候选的 32 个集合。这是旧实现的历史测试记录。2026-09-30 模板版改为一个合法动作，新增 12/13 张候选及取消边界测试，仍需实机验证。

2026-09-29 下一局前复查发现并修复：NSimple 无手动确认时较小集合被误列为合法动作；界面排序后原生 `Indexes` 回执使用原始顺序；最后一次点击可能在 Harmony postfix 前同步完成；Task 完成与回执到达存在短暂时差；以及局外选择器准备失败时可能误伤事件父动作。卡包回执现仅接受原生 `Index`。这些修复后重新通过 collector smoke、主工程 smoke 和 DataCollector Release 构建（0 warning / 0 error）。随后新实机轨迹暴露 NSimple 多卡单个 `Index` 回执的误判，另见下文；本条测试不能证明该边界。

2026-09-29 审计先前 `fcbb45909a9044f6b696695c35439b54` 后，NSimple 多选回执现同时接受原生 `Index` 与 `Indexes`，仍须通过候选、点击证据和 Task 结果的一致性核对。修复后重新通过 DataCollector Release 构建（0 warnings / 0 errors）、`./scripts/collector-macos.sh --action test`（`collector_smoke=ok`）及 `git diff --check`。游戏内已安装 DLL 与修复后的 Release 构建不同；尚未安装或实机验证该修复。旧 JSONL 不回填。

2026-09-29 卡包与局外多卡选择代码加入后，重新通过 `./scripts/collector-macos.sh --action test`、`./scripts/macos.sh --action test`、直接运行 `HeadlessCollector.Smoke` 程序、DataCollector 与 ModAdapter Release 构建（均 0 warning / 0 error）、`git diff --check` 和 shell 语法检查。独立进程在本机 `sts2.dll v0.111.0` 上成功应用新增 Harmony 补丁；反射检查覆盖了有上限的组合枚举。原生 IL 检查确认卡包节点包含全部卡牌，网格使用可滚动复用的卡牌节点；多卡点击时按此核对冻结候选与可见节点。这些离线测试不等于新卡包或多卡路径的游戏内验证，agent 未安装 DLL 或启动游戏。

2026-09-28 的 `36df...` 实机文件证实部分 v2 字段落盘，同时揭示被点击卡牌显示缺失和单卡 Index 误报。随后 v3 遗物展示投影、选择器关联与可见卡节点修复通过 `./scripts/macos.sh --action test`、`./scripts/collector-macos.sh --action test`、独立 `HeadlessCollector.Smoke`、两个 Mod 的 Release 构建（0 warning/0 error）、`git diff --check` 和 shell 语法检查。旧 v1/v2 combat、v1 outside 的反序列化以及可见计数 0、隐藏计数和 headless 无原生遗物字段都有 smoke 证据。在 `/private/tmp/SlayTheModel-SelectorTicketReview` 用当时 Release DLL 做临时反射回归检查：同一父动作下，A 的 Task 已完成但还没清理、B 仍在进行时，无 ID 的 Index 回执只匹配 B；A 之后仍能按精确 native ID 匹配。该 harness 不启动游戏，也不能证明所有真实 UI 时序；随后 `59261c...` 实机提供了 3 次单卡 Index 成功关联的证据。游戏内 DLL 未由 agent 安装。

2026-09-25 在 macOS ARM64、.NET SDK `9.0.306`、STS2 `v0.111.0` 上通过：

```bash
./scripts/macos.sh --action test
./scripts/collector-macos.sh --action test

dotnet build src/SlayTheModel.Sts2.DataCollector/SlayTheModel.Sts2.DataCollector.csproj \
  -c Release --no-restore -m:1 -nodeReuse:false -p:UseSharedCompilation=false

dotnet build src/SlayTheModel.Sts2.ModAdapter/SlayTheModel.Sts2.ModAdapter.csproj \
  -c Release --no-restore -m:1 -nodeReuse:false -p:UseSharedCompilation=false

git diff --check
bash -n scripts/collector-macos.sh scripts/macos.sh
```

当时的 search/protocol/outside/action/replay/collector smoke 与两个 Mod Release 构建均通过。2026-09-27 快速输入修复后，重新通过 `./scripts/collector-macos.sh --action test`（`collector_smoke=ok`）、DataCollector Release 构建（0 warnings / 0 errors）、`git diff --check` 和 `bash -n scripts/collector-macos.sh scripts/macos.sh`。这些结果不能代替新代码的游戏内验证。

2026-09-27 这轮结构化快速输入、生成卡选项与 headless 共享记录接口集成后，再次通过 `./scripts/macos.sh --action test`、`./scripts/collector-macos.sh --action test`、`HeadlessCollector.Smoke`、DataCollector 和 ModAdapter Release 构建、`git diff --check`、shell 语法检查。collector smoke 包含多 pending 的 A/B/C 点击与 A/C/B 结算、子选择 C 定向失效而 B 继续结算、生成卡同名候选不同 option index、干净取消和旧 partial 恢复。此时对已有的 7 份 JSONL 做过只读回放；随后又产生了两份实机文件。以上仍不等于新文件命名格式的游戏内验证。

本轮正式文件名改动后，重新通过 `./scripts/collector-macos.sh --action test`、`HeadlessCollector.Smoke`、DataCollector Release 构建（0 warnings / 0 errors）、`git diff --check` 与 shell 语法检查。smoke 覆盖带身份/角色/进阶/时间戳命名、缺失 metadata 占位、旧 UUID 文件读取、partial 续写及发布中断恢复。随后用户安装并实机产生了新命名的正式 JSONL；游戏内 DLL 的 SHA-256 与当前 Release build 一致。

针对 `Start` 快速输入的新代码，已重跑 `./scripts/collector-macos.sh --action test`、`./scripts/macos.sh --action test`、DataCollector 与 ModAdapter Release 构建（0 warnings / 0 errors）。独立临时 Harmony ABI harness 在本机 v0.111.0 `sts2.dll` 上成功应用 CardModel/PotionModel/NEndTurnButton 三个手动入口补丁；共享 `CombatCaptureService.BuildSnapshot` 重构编译通过。这些测试不构成 UI 手牌可见性和 `CanPlay` 在真实抽牌动画中一致的实机证据。

2026-09-26 本轮已重跑 `./scripts/macos.sh --action test`、`./scripts/collector-macos.sh --action test`、两个 Mod 的 Release build（均 0 warnings / 0 errors）。临时只读 ABI harness 在独立测试进程中对本机 `sts2.dll` 应用 Harmony patch，确认新增的手牌/牌堆/单卡输入、`ReserveChoiceId`、`GameAction.Cancel` 以及三个手动动作入口 hook 均可应用。这些测试未安装 Mod 或启动游戏，也不能代替第三份实机跑局验证。

2026-09-29 旧枚举版木札路径已通过 DataCollector Release、collector smoke、主工程测试、HeadlessCollector smoke、Harmony ABI 检查和 shell 语法检查。当时 20 张选 1–3 张被枚举为 1350 个动作；2026-09-30 模板版只保留 20 个候选和一个合法动作。这两轮离线验证均不能代替附魔页实机测试。

2026-09-29 后续 `f86...` 轨迹揭示另一个 `NDeckEnchantSelectScreen` 使用者：浸水抄写室 `PRICKLY_SPONGE`。原生 IL 表明它用 `Steady`、固定选 2 张，选满后仍须按预览页确认；`Steady` 仅给卡加保留，原生 Amount 不影响效果且不显示数值。当时的工作树增加 `Steady` 的界面标题/说明/图标核对，并以 `amount:not_applicable` 避免把原生数值作为可见特征；后续通用路径改以实际可见文案和可证数值投影所有原生附魔。旧构建的验证不能代替新路径的实机测试。

首份实机文件 `artifacts/human-dataset/episodes/1f898d5049a641ffaadaa232c214e53c.jsonl` 有 2967 条事件、480 个连续步骤，事件 SHA-256 链完整，终局为 defeat。它使用旧 `whole-run-v1`，有 19 个卡牌奖励误报 gap、935 个正常战斗中间态诊断、27 次地图楼层增量被过早记为 0，另有战斗内嵌套选择漏记 gap。该文件原样保留，不可事后伪造缺失的卡牌候选；`value_target_valid=false`，不可用作可靠整局 return 或 v2 reward 训练。

第二份实机文件 `artifacts/human-dataset/episodes/05e34e83ee474869a986c78325db9813.jsonl` 有 2460 条事件、563 个 decision/action submission、552 个 execution result、549 个 reward，使用 `whole-run-v2`。18 个 gap 为 14 次 `combat_action_without_decision`、2 次 `combat_nested_single_card_selection_not_supported`、2 次 `combat_nested_card_choice_not_supported`；其中 11 次打断待结算父动作，留下 11 个没有 result 的 submission。另有 3 个正常 cancelled result 不产生 reward。终局为 win，但 `completeness=incomplete`、`value_target_valid=false`。局级 metadata 已记录角色、进阶、时间、种子、Steam 身份；隐私值不应复制到文档。这份原始 JSONL 同样保持不可变，不能补造缺失的动作或结果。

后续实机文件 `artifacts/human-dataset/episodes/c5ff3eb971c54f1ebf22fbb15ac71a63.jsonl` 有 2614 条事件、577 条 decision/action submission/execution result、576 条 reward。60 个 gap 中 43 个为 `manual_combat_action_during_pending`、10 个为 `combat_action_without_stable_pre_state`，其余是选择器与多选缺口。终局为 win，但 `completeness=incomplete`、`value_target_valid=false`。此文件采自快速输入原始事件修复之前，不能事后补造原生动作证据。

先前实机文件 `artifacts/human-dataset/episodes/ff7431d1cf274845a82b706188025e94.jsonl` 有 1402 条事件，hash 链完整，232 个结构化决策全部配有执行结果与 reward。178 个原始手动输入全部配到原生结果，但其中 23 个非结构化：21 个是上一动作执行期间的快速点击，另 2 个发生在回合转换附近。一次 Attack Potion 产生的临时 `CARD.CINDER` 不在 `NetCombatCardDb`，使单卡选择冻结失败。终局为 defeat，24 个缺口令 `completeness=incomplete`、`value_target_valid=false`。这份旧文件保持原样，不得回填缺失数据。

随后产生的 `artifacts/human-dataset/episodes/11e8ccfd108f448abfa2e05639797785.jsonl` 有 1135 行，序号和内容哈希链完整；200 个结构化 decision/action/result/reward 全部配对，另有 2 个 `manual_combat_action_during_pending` gap；终局为 defeat、`completeness=incomplete`、`value_target_valid=false`。

先前实机文件 `artifacts/human-dataset/episodes/9ecfc38a6d1545a6afbf08c1576e0e1f.jsonl` 共 5065 行，事件序号、每行 SHA-256 和前序哈希链完整。终局为 win，但有 35 个 gap，故 `completeness=incomplete`、`value_target_valid=false`。887 个 decision 中，873 个提交动作都有 execution result，870 个成功动作都有 reward；其余 14 个 decision 对应实际点击的 `SACRIFICE` 卡牌奖励替代选项。611 次原始手动输入全部有结果，其中 604 次已结构化、80 次捕获 `queued_legal_set`；临时生成卡的 `Index` 选择已有成功关联。gap 由 14 次 `card_reward_alternative_not_supported`、7 次回合开始抽牌期间的 `manual_combat_action_during_pending`、7 次 Gambling Chip 多选 `combat_multi_card_selection_not_supported` 及其 7 次 `combat_card_choice_without_selector` 原生回执组成。那 7 次快速点击均在点击时玩家 `phase=Start`，执行时 `phase=Play`；其中 5 次在这段时间又抽到牌，不能拿执行时合法集合回填点击时的 BC 样本。旧 JSONL 保持原样。

先前一局的 episode ID 为 `39445f716b8d4dc591ed9700ee8be3db`，游戏内发布的新文件名五项均与首行 metadata 匹配。文件共 4721 行，832 个 decision/action submission/execution result 全部配对、828 个 reward、571 个原始手动输入与原生结果配对；5 个 gap 全为 `manual_combat_action_during_pending`。终局为 win、`completeness=incomplete`、`value_target_valid=false`。目录没有同局 partial。

2026-09-28 另一局的 episode ID 为 `36df5d1b03a74ca8a75c3917297b7d23`，4747 行都有终止换行，序号 0..4746、逐行 SHA-256/前序 hash 链和 episode ID 均正确。835 个 global_step 0..834，835 组 decision/submission/result 全配对；833 个成功结果有 reward，2 个 cancelled 不需 reward，568 组手动输入/原生结果配对。终局胜利但有 20 个 gap，`completeness=incomplete`、`value_target_valid=false`。其中 17 个 `combat_index_choice_without_selector` 经逐条核对都是单卡选择器回执 ID 晚绑定的误报；1 个 `manual_combat_action_during_pending` 和一组多卡选择的两条 gap 仍是真缺口。610 个战斗 observation 都有 gold/orb_capacity；853 个敌人意图显示、49 个 not_visible；普通 Play 的 461 个所选卡缺 display。原始文件不回写，也不能当作完整价值目标。

其后一局 `435800f8166e4d6ca309ce2ad251fc94` 已实机发布，4 次 `Start` 出牌全部结构化；730 个决策/提交/结果配对完整，无 coverage gap，终局 win、`value_target_valid=true`。该局采自本轮 v2 观察改动之前，不可作为新字段的实机证据。

先前一局的 episode ID 为 `59261c11694548228f801a8e6ea7970d`，正式 JSONL 有 4842 行、终止换行与完整的序号和 SHA-256 链。857 个连续 global step 的 decision、action submission、execution result、reward 全部配对，585 组原始手动输入与原生结果也全部配对；99 次捕获 `queued_legal_set`。终局 win，但 3 个真实 gap 使 `completeness=incomplete`、`value_target_valid=false`：Neow 开局卡包、事件选 2 张、事件移除 3 张。482 次实际出牌（476 次 `Play`、6 次 `Start`）所选卡均有 `display` 和说明；8 次 `Start` 输入（6 张卡、2 瓶药水）结构化；3 个单卡 Index 原生回执关联成功。615 个战斗 decision 使用内部 observation v3，242 个局外 decision 使用 observation v2；战斗和局外遗物实例分别有 6663/6663、2549/2549 个展示字段。旧 JSONL 保持不可变，不能从事件后牌组倒填 3 个局外选择的点击时合法集合。

先前一局的 episode ID 为 `fcbb45909a9044f6b696695c35439b54`，正式 JSONL 有 4200 行，事件序号与逐行 SHA-256 链完整，global step 0..749 连续。750 个 decision、749 个 action submission 和 execution result、747 个 reward；另外 2 个正常 `cancelled` 不需要 reward。491 组手动输入与原生结果全部配对，其中 1 次快速输入没有结构化 step 且有执行风险。终局 win，但 5 个 `coverage_gap` 使 `completeness=incomplete`、`value_target_valid=false`：一次 `Start` 阶段可见候选无法冻结的快速输入、一次 global step 80 的局外二张选牌回执误报、3 次尚未覆盖的 Crystal Sphere 事件小游戏交互。二张选牌已冻结候选并写出 decision；旧代码只接受原生 `Indexes`，实际收到单个 `Index`，因此没有 action submission，不得从后续结果补标签。工作树现兼容两种回执，但修复后代码未安装或实机验证；该 JSONL 不回写。

该局 519 个战斗 observation 均为 v3，231 个局外 observation 和 750 个 `context.run_context` 均为 v2，逐步信息模式全为 `no_sl`，无 save/load 或 rewind。404 次已提交出牌的所选卡均有 `display` 和说明；2 次结构化 `Start` 输入含 1 张卡和 1 瓶药水。战斗遗物 5048/5048、局外及 run context 遗物 2179/2179 个实例有 `display`；681 个敌人意图均带可见性标记，4 个不可见/未核实项没有意图内容。身份、原始种子与开局时间只在局级 metadata，不在逐步 observation/context。手牌 60 个缺失 `display` 的实例均属于排队/选择器时序，所选出牌无此缺口；这不证明所有视觉边界已覆盖。

先前一局的 episode ID 为 `dd28da34ecaf4dcda4c0abbcf5ae3bf9`，正式 JSONL 共 1590 行，279 个连续 global step 的 decision/action submission/execution result/reward 全部配对，199 次原始手动输入都有原生结果且均已结构化。终局 defeat，唯一 `coverage_gap` 在事件 1523：Gambler's Brew 触发战斗内多卡选择，5 个候选中实际选了 4 张；原生回执在事件 1524–1525 可见，但采集时的旧代码尚不能为该子选择建立完整合法集合和结构化动作。父药水动作 global step 268 有执行结果与药水减少的 reward，不能据此把包含缺失子选择的完整状态转移当作可靠监督。整局 `completeness=incomplete`、`value_target_valid=false`，原始 JSONL 不回写。两次 `Start` 快速出牌（global step 11、121）均形成排队决策、提交、执行结果与奖励；开局一次 `ChooseCardBundle` 有冻结候选、原生 `Index` 回执、提交、执行结果和牌组增加 3 张。203 个战斗 observation 为 v3、76 个局外 observation 为 v2，161 次已提交出牌的所选卡均有 `display` 与说明；未见新的 observation 契约问题。该局没有局外 `ChooseCardSet`/`RemoveCardSet` 或 Crystal Sphere，因此不验证上一局的二张选牌回执修复，也不意味着 Crystal Sphere 已支持。

其后一局 `4b3d120ce918402c936238fef818ab46` 共 2822 行，501 组 decision/submission/result/reward、335 组手动输入/结果全部配对，事件链完整，无 gap、save/load 或未结构化输入；终局 defeat，collector 标记 `complete`、`value_target_valid=true`。本局 24 个战斗内卡牌子选择全为单选，未实机验证 Gambler's Brew 多选修复。语义审计发现：359 个战斗 decision 中 116 个药水 `observation.slot_index` 错位；106 个决策的合法药水动作不能按观察中的真实槽号正确寻址，4 次实际用药（global step 207、412、495、499）选中的槽在观察中缺失。根因是 `CombatCaptureService.MapPlayer` 旧版把 `nativePlayer.potions` 压为紧密列表，`DecisionObservationProjector` 再用列表下标当槽位；合法动作始终读取真实 `Player.PotionSlots`。同一步 run context 中药水模型 ID 数量与顺序一致、槽位正确，因此旧 JSONL 应原样保留，在 assembler 中严格校验后修正派生特征或过滤受影响步骤；不能仅凭 `value_target_valid=true` 放行 observation。

2026-09-29 工作树已给快照增加可选 `PotionSlotIndexes`：只有稀疏槽位时写出，旧无空槽快照的序列化与指纹保持不变；live 快照核对原生药水模型与 `Player.PotionSlots`，局内与 run 观察共用真实槽号，采集器再对照 live 槽位。新决策写入入口调用 `ValidatePotionActionReferences` 拒绝 `UsePotion` 指向未观察槽；历史回放仍使用兼容的 `Validate`，独立临时 harness 当时只读重放了 16/16 份旧 JSONL。更新后的只读 `scripts/audit-collector-potions.py` 对当前 17 份正式 JSONL 复核：7 份的 748 个战斗决策发生观察与同一步 run context 药水 `(slot_index, model_id)` 不一致，其中 706 个合法动作集合受影响、16 个实际所选用药动作受影响、0 个无法核对。其他新局有真实稀疏槽位但两处观察一致，不能把“稀疏”计作错位。脚本退出码 2 表示发现错位或无法核对，`--json` 输出完整 global step；不修改任何原始文件。修复当时通过主工程/collector/headless smoke、DataCollector 与 ModAdapter Release 构建及 `git diff --check`，后续 `8adb...` 等实机数据已验证真实稀疏槽位可正确记录。

先前实机 `8adb3d74082043b4943d53f0199eb22a` 正式发布 2915 行，事件链与 C# 状态机回放通过，global step 0..529 连续；530 个 decision 中 529 个有提交和执行结果，525 个成功结果都有 reward、4 个正常取消没有 reward，294 次原始手动输入与结果全部配对。终局 win、无 save/load，但 6 个显式 gap 使 `completeness=incomplete`、`value_target_valid=false`：一次涅奥之怒空集战斗多选缺人工确认凭证、一次商店原生购买没有匹配到合法动作（step 216 的前后观察/动作/指纹相同，不能凭旧日志推断目标）、三次 Crystal Sphere cell 点击、一次遗物木札的 `TO_ENCHANT` 选择。木札在 20 张候选中原生 `DeckCard` 回执选中 3 张；旧 `PrepareMultiCardSelection` 只接受 `NSimpleCardSelectScreen`/`NDeckCardSelectScreen`，实际界面是 `NDeckEnchantSelectScreen`，类型检查必然拒绝，不能事后补造决策。原生 UI 实际可提交 1–3 张，20 张有 1350 个合法集合，未超 4096 上限。本局 13 次涅奥之怒多选完成结构化并与原生 `CombatCard` 回执匹配；无 Gambler's Brew，故其手牌多选路径仍未实机验证。药水稀疏槽位出现于 28 个战斗决策，观察、合法动作、run context 完全一致，4 次实际用药均能寻址；这是药水槽位修复的首份实机正面证据。248 次所选出牌有 display/说明/费用/动态数值，未选手牌仍有 18 个 display 缺失，需保留缺失 mask。该文件原样保留。

先前实机 `f86be9b6ec89451c9a6c87e1558e8e5f` 正式发布 1792 行，末尾换行、事件序号 0..1791、逐行 SHA-256 和前序链完整；global step 0..319 的 320 组 decision/action submission/execution result/reward 完全配对，217 组原始手动输入/结果配对。唯一 gap 在事件序号 348：上一步的 `EVENT.WATERLOGGED_SCRIPTORIUM` 选了 `PRICKLY_SPONGE`（扣 99 金），触发 `TO_ENCHANT`，12 张候选的原生 `DeckCard` 回执选了牌组索引 `[11,8]`，但采集器未冻结子决策。后续牌组两张卡出现 `ENCHANTMENT.STEADY`，证实这不是木札。实机安装的 DLL 缺少新附魔 hook 标识，与本地构建 SHA-256 不同，因此这局未测试先前的木札修复；当时工作树也未覆盖 `Steady`。终局 defeat、无 save/load/rewind，`completeness=incomplete`、`value_target_valid=false`；不能事后补造这 12 选 2 的训练标签。218 个战斗决策的药水槽位审计 0 错位，166 次已提交出牌的所选卡均有 display，所有 869 个手牌实例和 1377 个局内/局外遗物实例有 display。该原始文件保持不变。

先前实机 `ea59b2a19b2d44d99f5e4620df632e33` 正式发布 2382 行、14,805,888 字节，末尾换行、事件序号 0..2381、逐行 SHA-256/前序链正确，global step 0..427 连续。428 个 decision/action submission/execution result 一一配对；425 个 `observed_transition` 各有 `whole-run-v2` reward，3 个 `cancelled`（均为领取药水的原生 Task 返回 false）无 reward。274 个原始手动输入及结果全部配对且结构化。终局 defeat、无 save/load/rewind、0 个 coverage gap，`completeness=complete`、`value_target_valid=true`。281 个战斗决策的药水槽位只读审计无错位；210 次所选出牌均有 display，1273 个手牌实例中 1272 个有 display，唯一缺失位于 queued 输入步骤 204 的未选防御牌；2101 个局内/局外遗物实例有 display。游戏内 DLL 与这局采集时的本地 Release build 的 SHA-256 一致。这局没有木札、浸水抄写室或 Crystal Sphere，不能作为新增附魔/水晶球路径的实机验收。独立语义审计发现 global step 204 的 `pending_manual_actions` 已含 play card 11，合法动作却仍列同一张牌；它当时的 `display=null`，且所选是另一张牌 14。事件链完整不等于这个点击时合法集准确：旧 JSONL 不回写，后续 tensorizer 应按原生卡身份修正派生合法集并重映射所选动作，或排除该步骤及受影响窗口。本地工作树现过滤已提交的同一卡牌动作，DataCollector Release 构建（0 warnings / 0 errors）、collector smoke 和 `git diff --check` 已通过；新过滤尚未安装或实机验证。

先前实机 `24b023e841e44bb5a2dde5239e999fa2` 正式发布 3859 行，事件 JSON、哈希链和序号 0..3858 完整，global step 0..686 连续。687 个 decision/action/result 全部配对；684 个成功结果有 `whole-run-v2` reward，3 个正常取消无 reward。463 次原始手动输入及结果配对，461 次结构化、2 次未结构化且有执行风险。终局 win、无 save/load，但 4 个 gap 令 `completeness=incomplete`、`value_target_valid=false`：两次 `Start` 快速连续出牌（global step 23/94 附近）在第二次点击时模型 Hand 与 UI 可见手牌对象集合不符，原生实际执行而无法冻结点击时决策；其父动作的 transition 标为 `transition_contaminated_by_queued_manual_input`。另外两次分别为 `SELF_HELP_BOOK.READ_THE_BACK` 后的 `Sharp` 附魔选择和购买 `PUNCH_DAGGER` 后的 `Momentum` 附魔选择；当时安装版仅放行 `Adroit`/`Steady`，故子选择没有结构化。54 个带 pending 的局内决策没有已排队卡重复出现在合法动作中，377 次所选出牌都有 display；4 次 `PURITY` 手牌多选均有原生 `CombatCard` 回执。当前工作树已把附魔选择改为通用可见文案投影，原生 Amount 仅在 UI 直接显露整数时写入，否则标 `unobserved`；`MaxSelect=1` 也走原有的可见网格、点击、确认、Task 和 `DeckCard` 回执核对。最新 JSONL 不回写，新代码仍待实机验证。

2026-09-30 对该局的进一步只读审计未见新的事件配对、药水槽位、敌意图、遗物展示或逐步身份/种子泄漏问题；4 次 `PURITY` 多选时普通手牌 `display` 有缺失，现为 `active_choice.cards[]` 增加点击时可见选择器卡面的可选展示。该局 2304 个手牌展示含非空旧 `dynamic_values`，但旧代码没有逐项核对渲染文字；训练转换器必须掩码这些值。当时的工作树令 v4 新采集仅保留已渲染说明和费用，又把整手牌 UI/模型身份核对扩展到普通 `Play` 的出牌、用药和结束回合；无法验证时保留原始事件并记 gap。当时 `./scripts/macos.sh --action test`、`./scripts/collector-macos.sh --action test`、HeadlessCollector smoke、DataCollector 与 ModAdapter Release 构建、`git diff --check` 和 shell 语法检查通过。此 UI 门槛已按用户新的内部状态契约移除；历史测试和旧 JSONL 仍只说明旧版本行为，新代码尚未实机验证。


2026-09-30 最新 `ba8f9848c0804175b3c6e64f2fc03747` 跑局的 532 组 decision/submission/result 全配对，但 2 个 gap 使 `value_target_valid=false`。第二次 `Start` 快速出牌在首张牌点击后约 184ms 发生；原生两张牌最终都执行成功，但旧采集器发现内部 Hand 比 UI 可见手牌多一张，于是拒绝冻结第二步。稍后快照里有从 Draw 进入 Hand 的 `SLIMED`，但缺失点击时快照，不能断言那张就是差异来源。此处是旧版 UI/Hand 同步门槛造成的采集缺口；新契约允许记录点击时完整内部状态，无须为抽牌动画增设可见性/牌堆缺失 mask。新代码仍须实机验证，旧 JSONL 不补造。

2026-09-30 模板版离线验证：collector smoke 覆盖局外 19 选 4、局内 12/13 张候选、集合提交落盘与回放、可取消且最少选 1 张的边界；headless smoke、`./scripts/macos.sh --action test`、两个 Mod Release 构建和 `git diff --check` 通过。SpireFormer 在本机 PyTorch 2.9.1 下有 92 项 pytest 通过，tensor shard v2 读写及 v1 读取兼容。以上均不等于新选择路径的游戏内验证或 RTX 5090 BF16 测试。

其后两份正式 JSONL 的 `TO_TRANSFORM` 仍属旧路径缺口：亡灵契约师 `4be275a1f2554b938c3f90908c02ef23` 的 15 张候选和铁甲战士 `41774d4079db46029762d6b64df1a5bc` 的 29 张候选均未冻结子决策，后者在 `EVENT.TRIAL` 的原生 `DeckCard` 回执选了牌组索引 `[0,1]`。本地新增 `NDeckTransformSelectScreen` 专用入口，并通过离线 smoke/build 与独立 Harmony ABI 检查，须用新一局实机检查候选、min/max、最终确认、Task 和回执；不能从两份旧文件的回执倒填训练标签。

尚未验证：

- 普通快速输入、生成卡和单卡 `Index` 选择、`Start` 出牌/用药、所选卡 `display` 与遗物展示已有部分实机证据。局内涅奥之怒和 `PURITY` 的旧枚举版多选已有实测；2026-09-30 模板版及 Gambler's Brew 手牌多选仍未实机验证。烤面包手套的内部手牌候选及晚到 `CombatCard` 回执关联修复也待实机验证，须核对候选、人工选择 Task、原生回执、诊断和是否仍有两类旧 gap。局外二张选牌曾冻结候选，但模板版的动作标签、删牌集合和通用附魔页均待实机验证；Crystal Sphere 已有一局完整结构化与原生重放证据，尚未覆盖工具切换和快速连点。奖励替代选项、伙伴/充能球角色及所有遗物可见计数未逐类覆盖；`Start` 快速连点改用内部状态的新边界仍需实机验证，旧 Hand/UI 缺口不能用执行时状态回填。
- Windows collector 只有静态代码审查，当前机器没有 PowerShell，Windows 游戏内流程未经测试。
- 未对所有事件、角色、卡牌、遗物、药水和第三方 Mod 做覆盖测试。
- SpireFormer 尚未在用户的 RTX 5090 上完成各 preset CUDA/BF16 实测。

## 5. 下一步建议顺序

除非用户另行指定，最合理的后续顺序是：

1. 固定种子的无界面 legacy 路径已到第 7 层原生败局；同地图商店、休息点和宝箱分支已验证具体事务。默认规范化路径已有一条完整原生终端败局轨迹在无 `NGame` 探针中按同动作重放到第 17 层；三条人类 journal 回归又覆盖召唤怪目标、动画中间态选牌、奖励页弃药和 Crystal Sphere。下一步优先取得原始记录本身无 gap 的胜局并验证 `WinRun`，再扩展其他角色、未测商品、锻造、宝箱结算和更多事件，收集多种真实整局耗时。遇到 UI 回调边界应调用相同的原生逻辑入口并验证，不能跳过操作或直接改状态来制造吞吐量。
2. 在 macOS 用本轮独立采集器、Adapter `manual/manual`，完成一局短 no-SL 实机复测，优先覆盖 Gambler's Brew 手牌多选、修复后的局外二张选牌和通用附魔页；Crystal Sphere 可补测工具切换/快速连点，再测移除 3 张牌、有数字计数的遗物、伙伴与充能球角色。
3. 检查游戏日志、`dataset-manifest.json`、partial/publish、每步 decision/action/result/reward 配对、卡包和多卡的候选/人工点击/原生回执/Task 核对、Crystal Sphere 的棋盘可见性、异步点击与结果配对、v2/v3 字段的缺失标记、终局 `value_target_valid` 和所有 `coverage_gap`。
4. 再测试正常退出/续玩、明确 SL、异常退出和恢复场景。
5. 根据实机 gap 扩展缺失原生 hook，但保持协议和“不静默完整”原则。
6. BC-only `spireformer assemble` 的四局试验、独立亡灵契约师 holdout、Tiny 200 步试训和整局隔离评估已完成，证据见第 4 节。后续每批原始局仍须检查 `assembly-report.json` 的纳入/排除原因、词表哈希和 shard manifest；当前源码会对照同一步 run context 的完整药水槽号与模型 ID，排除不一致的步骤。
7. `whole-run-hp-safe-v1` 的标量 reward 与 RTG 已定义并接入 assembler；首轮 `433d...`/`32a...` Small 20 步产物因局外药水漏采而作废。Rewards 稳定边界下两次独立弃药已在 2026-10-02 新局中结构化，但三局的重叠药水与商店未匹配点击仍使整局 HP RTG 无效。本轮受控重叠边界、分项诊断及商店 `Task<bool>` 核对需在下一批新实机 JSONL 中验证；每局继续做逐步语义审计，再收集完整胜败训练局与整局隔离评估局。旧 checkpoint 不应续训或做正式评估。之后比较多合法动作、集合选择和不同目标 RTG 下的行为，再通过异步 worker 接入 `spireformer` 在线策略。
8. 扩展全局 headless runner 和事件覆盖后，复用同一个 collector writer；终端宿主可作为人工操作与原生行为对照，不作为高速训练后端，也不要创建第二套数据格式。现有改动均未提交；用户自行决定 commit/push，agent 可在用户询问时建议 commit message。
9. 数据上传、匿名化、同意与远端存储等到用户单独授权后再设计。

另外，MCTS 根节点 visits 尚未完整写入统一 episode 事件；以后做 MCTS 蒸馏时需要补齐，但不能为此改变人类示范的事件语义。

## 6. 常用命令

### 人类采集器（macOS）

先完全退出游戏：

```bash
./scripts/collector-macos.sh --action test
./scripts/collector-macos.sh --action install \
  --dataset-dir "$PWD/artifacts/human-dataset" \
  --information-mode no-sl
./scripts/collector-macos.sh --action launch \
  --dataset-dir "$PWD/artifacts/human-dataset" \
  --information-mode no-sl
```

允许回档时改成 `--information-mode sl`；不确定语义时使用 `auto`，不要猜成 no-SL。完整数据位于 `artifacts/human-dataset/episodes/*.jsonl`。

### Adapter / first-legal / MCTS

```bash
./scripts/macos.sh --action test
./scripts/macos.sh --action install

./scripts/macos.sh --action launch --run-mode play \
  --combat-policy first-legal \
  --outside-combat-policy first-legal

./scripts/native-worker-macos.sh --mode verify
./scripts/macos.sh --action launch --run-mode play \
  --combat-policy mcts \
  --outside-combat-policy manual \
  --capture-history
```

MCTS worker 需要 Steam Workshop 的 STS2-RitsuLib；不要同时启用 Combat Solver 自带自动出牌控制器。

### Headless 终端与原生速度探针（macOS）

```bash
./scripts/headless-macos.sh
python3 smoke/headless-play-client-smoke.py
./scripts/native-worker-macos.sh --mode native-throughput --timeout-seconds 120
./scripts/native-worker-macos.sh --mode whole-run-api-probe --timeout-seconds 120
./scripts/native-worker-macos.sh --mode whole-run-speed-probe --timeout-seconds 120
```

默认 `whole-run-speed-probe` 已在 macOS ARM64 以游戏规范化种子完成开局、首战、奖励和下一节点，输出 `whole-run-speed-probe.json`。设置 `STS2_PROBE_ROUTE=event` 可进入同种子的自然 `SPIRALING_WHIRLPOOL`；`STS2_PROBE_EVENT_OPTION=1` 选择 `Drink`，不设置时选择 `Observe`，各自输出 `whole-run-speed-probe-event.json` / `whole-run-speed-probe-event-1.json`。完整场景对照使用 `python3 scripts/check-headless-draw-parity.py --compare-event --probe-json <对应文件>`，详见性能文档。历史短败局及商店/休息点/宝箱分支用 `--mode whole-run-speed-probe-legacy` 复跑；设置 `STS2_PROBE_ROUTE=shop` 或 `rest` 分别输出 `whole-run-speed-probe-legacy-shop.json` 和 `whole-run-speed-probe-legacy-rest.json`。两种模式的 JSON 明确记录 `inputSeed`、实际 `seed` 与 `seedHandling`。终端宿主默认会初始化音频，速度探针不会启动 Steam；Windows 终端及 worker 命令见各自脚本和对应文档。

### SpireFormer

```bash
cd model/spireformer
python -m pip install -e '.[test]'
pytest -q
spireformer presets
spireformer smoke --preset tiny --device cuda --precision bf16 --mode train
```

历史 BC-only 四局组装命令如下。这四份原始 JSONL 目前不在 `artifacts/human-dataset/episodes`；只有恢复对应源文件后才能从仓库根目录重跑。下方两局 RTG 命令同样只作已作废的历史记录：

```bash
spireformer assemble --input artifacts/human-dataset/episodes \
  --output artifacts/tensor-v2/bc-demo-v3 \
  --train-episode ba8f9848c0804175b3c6e64f2fc03747 \
  --train-episode 148a980306c24c8aadda13cbc30f57b4 \
  --val-episode 42e3c58940b54a36908e32e28b9c893b \
  --test-episode bb42726c849b46068175a7ad7aeaf543
```

此命令需先 `cd ../..` 回到仓库根目录；输出目录必须尚不存在。当前 tensorizer 版本为 `collector-raw-bc-v3`，tensor shard 格式仍为 v2；RTG 为常数占位、value mask 全关。训练时传 `--value-weight 0`，评估使用整局隔离的 `val/` 或 `test/`，不以离线准确率代替游戏胜率。

整局 HP RTG 首轮组装与训练的历史命令如下。**其输出已作废，不得用这些旧输入原样重跑或继续训练**；局外药水独立弃药已有两次实机证据，但最新三局仍因 gap 不完整。受控重叠边界和商店 `Task<bool>` 核对须经新实机验证，随后选择经逐步审计的完整数据并使用新输出目录：

```bash
spireformer assemble --input artifacts/human-dataset/episodes \
  --output artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1 \
  --train-episode 433d5532920444a1afac0716251e12c4 \
  --train-episode 32a3822509ec4c9fa8d00017103daee6 \
  --reward-scheme whole-run-hp-safe-v1 --max-window-steps 64
spireformer train --dataset artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1/train \
  --output artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1 \
  --preset small --device cpu --precision fp32 \
  --total-steps 20 --warmup-steps 2 --batch-size 1 \
  --checkpoint-every 5 --log-every 1 \
  --value-weight 0 --entropy-weight 0 --verify-data
```

两局都训练时没有独立验证集，`evaluate --conditioning recorded --allow-training-dataset` 还使用真实未来回报；当时的数字只保留为历史链路记录。完整解释见 `model/spireformer/README.md`。

Large smoke 只建议 inference；完整 Large 训练不能直接用当前 DDP 路径假设单张 5090 可行。

## 7. 事实来源

- 总览与启动：[README.md](README.md)
- 采集器：[docs/human-data-collector-v0.1.md](docs/human-data-collector-v0.1.md)
- 训练数据协议：[docs/spireformer-training-data-v1-plan.md](docs/spireformer-training-data-v1-plan.md)
- SpireFormer：[model/spireformer/README.md](model/spireformer/README.md)
- 局外协议：[docs/outside-combat-interface-v1.md](docs/outside-combat-interface-v1.md)
- 原生 MCTS：[docs/native-mcts-v0.3.0.md](docs/native-mcts-v0.3.0.md)
- Combat Solver 桥接：[docs/combat-solver-mcts-backend.md](docs/combat-solver-mcts-backend.md)
- STS2 ABI：[docs/sts2-v0.111.0-abi.md](docs/sts2-v0.111.0-abi.md)
- 原生 Headless 终端：[docs/headless-terminal-v0.1.md](docs/headless-terminal-v0.1.md)
- Headless 事件覆盖：[docs/headless-event-coverage-v0.111.0.md](docs/headless-event-coverage-v0.111.0.md)
- 无完整界面战斗实测速率与整局门槛：[docs/headless-performance-gate-v0.1.md](docs/headless-performance-gate-v0.1.md)
- 原生交互审计：[docs/native-interaction-audit-v0.111.0.md](docs/native-interaction-audit-v0.111.0.md)

如果文档与源码冲突，先用最小只读检查确认真实实现，再修文档；不要依赖旧对话记忆直接改协议或原生 hook。
