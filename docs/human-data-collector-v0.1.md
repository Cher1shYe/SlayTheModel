# 人类整局轨迹采集 Mod v0.1

更新：2026-10-12

`SlayTheModelDataCollector` 是与自动打牌 Adapter 分离的只读 Mod。它观察玩家在单人跑局中的局内、局外决策，把一局数据持续写入本地 JSONL；它不会替玩家点击、不会启动 MCTS，也没有上传或网络代码。

## 数据生命周期

一局游戏对应一个 `episode_id` 和一条统一时间线。每个决策在逻辑上经历以下阶段；快速排队时，不同决策的事件行可以交错，须按 decision/attempt ID 关联：

1. `decision`：玩家操作前的 observation、合法动作和信息模式；
2. `action_submitted`：玩家实际选择的动作及 actor；
3. `execution_result`：原生游戏是否执行成功；
4. `reward`：执行前与下一个稳定语义边界之间的 HP、金币、楼层、牌组、遗物和药水数量变化；
5. 游戏结算时写入 `episode_finished`，包含胜负或放弃结果。

很多 STS2 接口返回时只是把 `GameAction` 放入队列，并不代表效果已经结算。采集器在确认下一个可靠决策、子选择器、排队的下一条原生手动动作开始执行或终局状态后，才把已接受动作的 `execution_result/reward` 连续写入。仅开始战斗或触发 `SaveRun` 不保证楼层与战斗效果已更新。终局胜负以 `episode_finished.outcome` 为准。

战斗动作的人工归属以原生手动入口为证据：`CardModel.EnqueueManualPlay`、`PotionModel.EnqueueManualUse` 和结束回合按钮只标记各自提交的 `GameAction`。卡牌效果也会向同一个队列加入动作，因此单凭 `RequestEnqueue` 不能生成玩家标签。采集器在手动入口的 Prefix 中尝试冻结当前前态和合法动作，再把证据绑定到实际提交的同一个 `GameAction`；这也避开药水入口先设置 `IsQueued`、随后才发入队事件的时序。执行中的自动或来源不明动作写诊断；没有父动作可归属且缺少手动证据的动作写独立 `coverage_gap`，不猜测它是玩家所为。原生队列可能在通知入队后取消动作；采集器观察 `GameAction.Cancel`，执行前取消写 `cancelled`，执行已开始时按不确定失败处理，避免提交记录永久悬挂。

连续快速出牌时，玩家可能在上一动作仍执行期间再次提交手动动作。采集器在每次原生手动入口冻结**点击时游戏内部状态**、由该状态得到的合法集合和已经排队的手动动作；只要提交的同一个 `GameAction` 能与合法动作精确匹配，就立即写独立的 `decision` / `action_submitted`。这些 decision 按点击顺序获得递增 `global_step`，后续结果按各自的 decision/attempt ID 关联。`observation.pending_manual_actions` 是玩家自己已提交、尚在队列中的动作，不含原生动作 ID 或时间戳。前一动作的奖励在下一动作真正开始执行前结算，后一动作的指标从其实际执行开始采样。

每个被识别的手动 `GameAction` 还会写 `manual_combat_input` 和同一 `intent_id`、`native_action_id` 的 `manual_combat_input_outcome`，用于核对点击、排队、执行和取消。原始事件的 `global_step=null`；已结构化的点击以 `related_decision_id` / `related_attempt_id` 指向自己的 step。点击时不能取得可核实的合法集合，或提交动作不在该集合中时，仍只写原始输入；若原生实际执行或执行结果不确定，再记 detached `coverage_gap`，不能拿稍后的执行前态补造行为标签。执行前干净取消或拒绝的非结构化输入保留审计记录，但不单独使整局无效。终局会同时统计原始输入总数、未配对数、未结构化总数及其中有执行风险的数量；未配对或有执行风险的输入会使完整性失效。

回合开始抽牌动画期间，玩家可能在 `phase=Start` 就提交卡牌或药水。当前契约以原生手动入口的内部 Hand、抽牌堆和弃牌堆为点击时前态，只按当时卡牌的 `CanPlay`/目标规则与药水可用条件构造 `Start` 候选，不列 EndTurn。原生 v0.111.0 的正常 `Start` 阶段结束回合按钮尚未启用；异常收到 `Start` EndTurn 时，它不在合法集中并记 gap。内部 Hand 已有的新抽牌即使仍在飞行动画中，也进入本步 observation；无需记录它何时在 UI holder 中显现。已经提交的同一原生卡 ID 仍不能再次列为合法出牌。只有点击时内部状态和合法集能够冻结、所选动作与本次提交的同一 `GameAction` 匹配，才写结构化 step；否则留原始输入和 gap，绝不以稍后执行时 `Play` 状态倒填。自动策略仍只在 `Play` 阶段获得普通合法动作。

普通 `Play` 阶段的手动出牌、用药和结束回合也采用相同的内部状态边界。UI holder 与内部 Hand 暂时不一致，不再单独阻止行为标签。live collector 产出的战斗 observation v5 对每张内部 Hand 卡均写一个 `display` 对象，仅从原生 `CardModel` 计算当前能量、星星和 X 费用；单项计算失败可为 null，但不触发 gap，也不表示 UI 不可见。普通手牌的 `description=null`、`dynamic_values=[]`，不扫描 UI holder 或记录卡面动画进度。手牌成员资格与出牌合法性仍由内部状态和原生规则确定；敌方意图、遗物展示和选择器候选的既有可见性规则保持不变。新代码尚未安装或实机验证，历史 JSONL 的缺口不回填。

战斗中打开卡牌选择器时，采集器冻结玩家可见候选卡和原生选择数约束；在原生选择输入发生时创建子 `decision`，根据选择器完成结果提交 `ResolveChoice`，并与原生 `CombatCard` 或单卡 `Index` 回执核对。单卡临时生成、尚无网络卡牌 ID 的候选以选择器内序号标识，再用实际 `CardModel` 对象身份与原生回执核对，不能凭同名卡猜测。多卡选择的 `legal_actions` 只包含一个 `is_selection_template=true` 的 `ResolveChoice`，候选仍保存在 `active_choice.cards`，实际卡实例 ID 集合在核对完成后写入 `action_submitted.selected_action.selected_combat_card_ids`；不再枚举所有组合。原生卡实例 ID 区分同名卡，缺失 ID 的多卡仍记 gap。手牌多选从 `NPlayerHand.SelectCards` 获取候选与 `CardSelectorPrefs`，确认时冻结原生 `_selectedCards`，再与 selector Task 和 `CombatCard` 回执逐项核对；即使选满上限，也要有原生确认入口证据。Gambler's Brew 的原生上限 `999999999` 由 5 张候选裁剪为 5；当最少选择数为 0，成功确认 0 张是合法空集动作。最少选择数大于 0 时，原生取消与成功选择分开记录，不把取消当作空集训练标签。Task 取消仍按失败或缺口审计，不形成 BC 标签。父出牌或药水动作在子选择边界结算；若父动作后来失败，会留下指向该动作的独立缺口，供转换器排除相应行为标签。子选择失败时只定向作废子 decision，先前排队的其他动作仍可独立结算。候选集合无法取得、原生卡实例 ID 缺失、结果不一致、原生 `Index` 回执没有对应 selector 或缺少人工输入证据时，仍以 `coverage_gap` 标记不完整。旧 `4b3d...` 跑局中的战斗多卡证据保留原样；新模板仍待实机验证。

原生 `CardSelectCmd.FromHand` 在没有合格手牌时会直接返回空结果，并不会打开手牌选择 UI。如果采集器已经观察到 `NPlayerHand.SelectCards`，却冻结到零个候选，这表示 UI 状态与采集投影不一致；该情况会记缺口，不能当成自动选择或零张成功确认。

修正结算时机后的奖励版本为 `whole-run-v2`。此前采得的 `whole-run-v1` 原始 JSONL 不改写；其 reward 可能过早采样，转换器须按版本筛选或重新从可信边界计算。若终局指标无法取得，采集器会记 `coverage_gap`，不会把缺失指标假装成零变化。

**2026-10-01 新发现的局外药水缺口：**旧胜局 `433d5532920444a1afac0716251e12c4` 的 global step 270 选牌后 `potion_count_delta=-1`，但没有独立的局外用药或弃药 decision。新局 `ec731...` 的 step 79 领奖励、step 608 点击继续后也各记录 `potion_count_delta=-1`，同样缺少药水动作；这些减少被相邻的结构化动作 reward 吸收。事件链完整和原采集器的 `episode_finished.value_target_valid=true` 不能证明所有人工操作都已采集。离线 auditor 对旧 JSONL 标记 `unexplained_outside_potion_decrease`、排除受影响 BC 步，RTG assembler 拒收整局。旧 JSONL 不补造操作或改写。使用 `433d...` 生成的首版 HP RTG shard 与 Small 20 步 checkpoint 已作废，不得继续正式训练或评估；`32a...` 败局未见同类药水减量，但一局败局不足以构成可用的胜败数据集。

**2026-10-02 三局实机复查：**`2085af58548044b9b192db449a6dbbf0`、`1ddd1912ef634cbeb9d331f52b79cf24`、`2d9fc925402f440eaba2c30e5c214966` 均为 no-SL 铁甲胜局，事件序号与 SHA-256 链完整。各有 932/787/508 个决策，922/781/502 个步骤可进入 BC-only。`2085...` 有 3 次在上一局外动作尚未结算时发生的药水点击；`2d9...` 有 1 次买遗物期间的弃药；`1ddd...` 的 step 701 有 1 次商店购买点击未匹配合法动作，前后金币、卡组、遗物和药水未变化，但旧日志缺点击对象和原生返回值，不能断言游戏拒绝了该点击。三局都因显式 gap 为 `completeness=incomplete`、`value_target_valid=false`，不能生成整局 HP RTG。Rewards 顶层的独立弃药在 `2085...` step 408 和 `2d9...` step 404 结构化成功，槽位与下一步库存一致；局外用药尚无成功样本。原始 JSONL 不回填。

**当前工作树的有限结构化路径：**在 v0.111.0 的 Rewards 屏幕位于顶层、药水栏可交互且所有持有药水槽均可与原生状态核对时，普通 ClaimReward/Proceed 决策会同时列出合规的 UsePotion/DiscardPotion。手动局外用药或弃药会冻结点击时的合法集，为药水候选写真实槽号与模型 ID，并将提交和执行结果绑定同一个原生 `GameAction`。Use 只列原生允许的任意时机药水及有效目标；Discard 按原生弹窗允许的持有槽列出。为处理三局中观察到的重叠输入，本轮新增受控的父步结算边界：若存在未结父动作，它必须唯一且已被原生接受；当前还须没有选择器，执行器空闲且原生动作队列为空，并且顶部 Rewards 或商店页面与药水栏均可核对。满足全部条件时，药水点击可先结算父步，再成为新的独立决策；不满足时继续写 `coverage_gap`，用分项诊断说明阻挡条件，不从后续库存净减少倒补行为标签。其他局外动作若发生无法解释的药水净减少，也写关联 gap。core 的局外排队日志 API 已存在，但 Runtime 不靠它推断不稳定的决策前态。Rewards 独立弃药已有两次实机证据；新增重叠路径和商店药水路径尚未安装或实机验证。旧 shard 和 checkpoint 仍作废。

商店购买点击若未匹配冻结的合法动作，采集器会等原生 `Task<bool>` 结果及前后状态、库存核对。仅当点击与结果边界都稳定、没有其他待处理操作、明确返回 `false` 且状态和库存不变时，写只读 `diagnostic`；返回成功、任务结果不明、状态发生变化或边界无法核实时保留 `coverage_gap`。旧 `1ddd...` 文件未保存这些证据，不能回头改判为完整。这条新判定同样需要实机验证。

战斗与局外决策共享递增的 `global_step`。原生 observation 保持局内/局外协议结构；整局牌组、遗物、地图等额外信息单独存放在 `context.run_context`，便于之后按需构造 SpireFormer tensor，而不会污染策略协议。

每局第一行 `episode_started` 的 `recorded_at_utc` 是采集器开始记录该 episode 的 UTC 时间；`payload.metadata.run_started_at_utc` 是游戏原生跑局创建时间，两者在从存档开始采集时可能不同。metadata 还包含 `character_id`、`ascension`（`0` 为普通难度，`1`、`2` 等为对应进阶）、`game_mode`、`run_seed`，以及可取得时的 `steam_persona_name` 与字符串形式的 `steam_id64`。缺失时分别查看 `run_start_time_status`、`run_seed_status` 和 `steam_identity_status`；Steam 不可用时不会拿系统用户名冒充。昵称可能变动，Steam ID 用于稳定区分玩家。种子、身份和时间只在局级 metadata 中，不能进入 `decision.observation`、`context.run_context` 或模型特征。

新采集的单人局还在 metadata 中记录 `episode_start_current_hp` / `episode_start_max_hp`（采集段开始时的生命，字符串）。只有原生新开局入口和同一个 `RunState` 均得到确认时，`observed_from_run_start=True` 并额外记录 `run_start_current_hp` / `run_start_max_hp`；从存档进入或入口证据缺失时不能把采集段起点冒充跑局起点。`episode_finished.payload.summary` 记录可取得时的 `terminal_current_hp` / `terminal_max_hp`（数字）及 `terminal_hp_status=available`，原生终局状态不可得时标 `unavailable`，不可得字段为 `null`。这些锚点供离线 RTG 转换交叉核验；旧 JSONL 没有新字段，仍可按原始决策和奖励链审计，但不能获得独立的终局生命核对。

每条 JSONL 都包含 `event_sequence`、`timeline_generation`、前一条记录的 SHA-256 和当前记录的 SHA-256。写入后立即刷新到磁盘。进程意外退出时保留 `.jsonl.partial`；采集器只在游戏的实际 `SaveRun` 成功后保存恢复游标，并在再次加载时同时核对 episode 游标和规范化原生存档指纹。只有二者精确一致才续写；无法证明连续时会发布旧片段为 incomplete 并开始新片段。完整结算后才原子发布为不可变 `.jsonl`。

## 紧凑事件视图

从 2026-10-12 的工作树开始，每局原始文件成功发布后，采集器会在 `episodes/_compact/` 自动生成同名的 `*.compact.jsonl`。这个文件借鉴 Spire Codex 的可读事件流形式，但由本项目自己的完整日志确定性派生：`episodes/*.jsonl` 仍是唯一事实源，现有审计器和训练转换器仍读取原始文件。紧凑视图生成失败只记录 warning，不会让已经安全发布的原始 episode 失败或重复写终局事件。

紧凑行用短事件名 `episode / decision / action / result / reward / manual_input / manual_result / gap / diagnostic / save_load / finish`。`q` 对应原始 `event_sequence`，`s` 对应 `global_step`。每个 `decision` 仍完整保留当步 `legal_actions`；普通动作由 `selected_action_index` 指回该集合，集合选择还会保留提交时的具体 `selected_action`，因此不会丢失多选标签。

为了避免每一步重复整份状态，`observation` 和 `context` 使用可逆的 JSON Pointer 差量：首个决策、每 64 个决策以及 save/load 后写 `mode=full`，其余写 `mode=delta`、`base_step`、`set` 和 `remove`。同长度数组会按索引比较，只有逐项差量更小时才采用；否则替换整个数组。每个差量在发布前都会立即套用到基准状态，并与原始事件中的 JSON 逐项比较；决策还保存还原后 observation/context 的 SHA-256，末行写 `delta_round_trip_verified=true` 和原始文件 SHA-256。

`manual_combat_input` 中的点击观察、合法集、指纹和动作若与其关联 decision/attempt 完全一致，紧凑视图写 `decision_evidence=exact`、`action_evidence=selected` 和步骤引用，不再复制同一大段 JSON；任何不一致字段都会原样保留。少数执行前后观察按关联 decision 保存可逆差量。这样减少的是已经核对过的重复表示，不会把缺口、拒绝、取消或未结构化输入伪装成训练步骤。

已发布的旧文件可用 `CollectorStore.ExportCompactEpisode(episodeId, overwrite: true)` 回填。离线回归对当前目录 6 份历史实机 episode 全部读取、回放并完成逐差量还原；总大小从 156,638,021 字节降到 29,624,597 字节，减少 81.1%。其中 `2085af58...` 保留 5,516 条事件和 932 个 decision，由 35,405,881 字节降到 6,675,823 字节。该结果验证的是离线派生与可逆性；自动生成路径尚未安装进游戏做新一局实机复测。

## 战斗 observation v2 / v3 / v4 / v5

JSONL 事件包络仍为 schema v1。战斗 observation v2 保留原有的玩家/敌人 HP、格挡、能力，药水、无隐藏顺序的牌堆集合，以及已持有的充能球，并增加：

- 玩家当前金币与充能球槽位容量；
- 卡牌的升级与附魔状态。v2–v4 的普通手牌 `display` 取 UI 卡面费用与已渲染描述，可能因动画时序为 null；这些旧观察原样保留。live collector 产出的 v5 **手牌实体集合取点击时内部 Hand**，每张内部卡的 `display` 由原生 `CardModel` 投影当前能量、星星和 X 费用，`description=null`、`dynamic_values=[]`；不以 UI 卡面是否出现决定成员或动作。旧 v2/v3 还写入所有原生动态预览值；有些值并未出现在卡面，转换时不能把它们当作精确伤害/格挡；
- 当前战场上的玩家伙伴，例如 Osty 的生命、格挡和能力；先按战斗友方阵容采集，玩家宠物列表中暂时不在阵容的对象还须核对同一战斗、存活、可击中且 UI 节点可见，不把已离场引用当作在场；
- 敌人 UI 已显示且与原生意图对象核对的意图图标及文字、可验证的攻击数值；图标尚未显示或核对失败时记录 `not_visible` / `unverified`，不从隐藏的下一招推测意图。

卡牌旧字段 `energy_cost` 是原生快照里的可空费用覆写：当前全修正费用与卡牌标准费用相同时为 `null`，不能读成 0 费或未修正。v2–v4 的 `display.energy_cost` 来自 UI 展示；旧 v2/v3 的 `display.dynamic_values` 无条件保存原生 `PreviewValue`，其中 `Damage` / `Block` 会经过战斗伤害/格挡修正，但未逐项核对是否真正渲染到说明文字，必须由训练转换器掩码。v4 已将动态数组置空，仅保留 UI 已渲染说明和费用。live collector 产出的 v5 `display` 对每张内部 Hand 卡非 null，费用单项从原生 `CardModel` 计算且可因计算异常为 null；`description=null` 是按设计不采集普通手牌说明，`dynamic_values=[]` 是按设计不采集动态预览，均不能解释为卡牌没有效果。

此前 `36df5d1b...` 跑局首次提供 v2 实机证据：610 条局内观察都有金币和充能球容量，902 个敌人观察都有意图可见性标记。该局普通 `Play` 中 461 次被点击的卡牌因已离开手牌 holder 而缺少 `display`。旧版修复后，`59261c...` 跑局的 482 次实际出牌（含 6 次 `Start` 出牌）、`fcbb...` 跑局的 404 次已提交出牌（含 1 次 `Start` 出牌），以及最新 `dd28...` 跑局的 161 次已提交出牌，所选卡均有 `display` 和说明。这些是旧 v2–v4 展示字段的覆盖证据；live collector v5 的普通手牌 `display` 不再表示 UI 是否显示，训练转换器必须按内部 observation 版本分别解释。

v3 为每个战斗决策的 `players[].relics[]` 增加可选 `display`：图标状态、融化/蜡化视觉状态、按原生遗物栏规则当步应显示的 `visible_counter` 和原生主悬停说明。`display=null` 表示未取得展示投影；`display.visible_counter=null` 表示该步 UI 规则不显示数字，`0` 则是应显示的零。计数是否显示按原生 `ShowCounter && RunManager.IsInProgress` 每步判断，不能直接把 `DisplayAmount` 或 `StackCount` 当作 UI 数值。该投影按 UI 规则从原生模型读取，尚未逐帧核对遗物栏节点是否已刷新。主悬停说明是本地化文本；原生额外提示还可能包含动态状态说明和卡牌预览，目前没有完整结构化记录，不能称为所有可见遗物信息。没有 UI 展示依据的遗物私有字段不进入 no-SL observation。

同一遗物展示投影也用于局外 observation v2 和 `context.run_context` v2；新数据不再无条件写原生 `stack_count`、`used_up`、`status`、`display_amount`。旧 JSONL 保持原样，其 run_context v1 遗物字段未经 UI 可见性核验，转换器不得直接用作 no-SL 特征。旧版普通手牌描述、当前选择器卡面描述、遗物说明和意图显示文字可能随游戏语言与界面刷新变化，是辅助证据，**不是稳定 ID**；v5 普通 Hand 不记录卡面描述。旧 observation v1/v2 中缺失的新字段必须带缺失 mask，不能零填充或解释为真实 0；v2 中缺失的伙伴/意图字段也不能解释成“没有伙伴/意图”。先前 `fcbb...` 实机的战斗与局外观察中，遗物实例分别有 5048/5048 和 2179/2179 个 `display`；这证明字段入盘，尚不能证明所有遗物的计数、额外提示与逐帧 UI 一致。

战斗 observation v4、局外 observation v4 和 `context.run_context` v3 对已知附魔牌增加 `enchantment_display`：原生卡牌悬停提示使用的本地化标题、动态说明，卡面标签按 `ShowAmount` 规则实际会显示的 `visible_amount`，以及正常/灰暗的图标外观。`visible_amount=null` 表示卡面没有显示附魔数值，不能读取原生 `Amount` 补全；`enchantment_display=null` 表示未能取得展示语义。战斗旧字段 `enchantment_amount` 在 v4 必须为 null，旧 v2/v3 中的同名字段曾是原生值，assembler 不得直接当成 no-SL 可见强度。非手牌的牌不生成当前手牌 `display`，但它们的附魔悬停与标签语义可由玩家查看已知牌组/牌堆时取得。此路径按 v0.111.0 原生卡面渲染代码投影，尚未通过新的实机局逐帧核对。

战斗选择器的 `active_choice.cards[].display` 在人工点击或确认时，从当时真正可见的手牌、网格或候选行卡节点按 `CardModel` 对象身份读取说明与费用；找不到唯一可见节点时保留 `null`。选择器卡面沿用 v4 的 UI 展示与动态值掩码语义，**不同于 v5 普通 Hand 的原生费用投影**，不能用卡牌定义或选择后的状态补填缺失展示。该新增展示字段尚未经过新实机验证。

## no-SL 与 SL

启动时必须明确数据语义，不能仅凭“读取了存档”猜测玩家是否 SL：

- `auto`：信息模式写为 `unknown`，适合第一次试用；如果中途加载存档，采集器无法证明这是正常续玩还是回档，因此会保留轨迹但把整局标为不完整，避免误用 value target；
- `no-sl`：声明玩家不回到更早状态。只有原生存档指纹与采集器已完整结算的持久游标精确匹配，正常续玩才记为 `resume`；
- `sl`：把加载存档记为明确 `rewind`，保留时间线分支证据并使整局 value target 标记为不可直接使用。

如果加载发生在尚未完整写完一个 decision/action/result/reward 事务时，采集器会保留 data-gap/uncertain 计数并自动令 value target 失效，而不是伪造完整样本。从中途存档才开始采集或玩家主动放弃的跑局也会正常发布，但 `completeness=incomplete`、`value_target_valid=false`。一旦 no-SL 连续性无法证明，之后的单步 `information_regime` 也会降为 `unknown`，不会继续把潜在 SL 数据标成 no-SL；当前 BC-only assembler 只保留逐步确认的 no-SL 人工动作，其他模式不进入首轮训练。

地图移动时游戏可能在 `TotalFloor` 增加前先保存。采集器会跳过这种未结算动作上的恢复游标；若玩家此时退出再读取存档，整局 value target 会保守失效，原始事件仍保留。

## 本地目录

假设 `--dataset-dir` 为 `artifacts/human-dataset`：

```text
artifacts/human-dataset/
├── dataset-manifest.json
├── active-runs/
│   └── <run-key>.json
└── episodes/
    ├── _open/
    │   └── <episode-id>.jsonl.partial
    ├── _quarantine/
    │   └── <episode-id>-<timestamp>.jsonl.partial
    ├── <SteamID>_<角色>_A<进阶>_<UTC时间戳>_<episode-id>.jsonl
    └── <episode-id>.jsonl                         # 旧版文件仍可读
```

`active-runs` 只用于本机恢复，不是训练数据。`_quarantine` 保存未通过 JSON/schema/hash/state replay 校验的损坏 partial，避免一条坏文件令以后每次启动都停止采集；它同样不能进入训练。原始 seed 只写在 `episode_started` 的局级 metadata；原生 save payload 不写入 episode；v2 战斗 observation 可以保存已经显示的本地化 UI 文本。run key 是本地恢复用的单向哈希。训练数据的事实来源是已完成的 `episodes/*.jsonl`，未完成文件应由后续 assembler 按完整性字段过滤。JSONL 中的 Steam 身份与 seed 均保存在本机，目前没有上传路径。

正式文件名的时间优先使用 `run_started_at_utc`，缺失时使用 `episode_started.recorded_at_utc`，始终按 UTC 格式化。Steam ID、角色或进阶缺失时使用明确的 unavailable/unknown 占位；角色字段会过滤路径特殊字符。末尾 episode ID 保证同一玩家同一时间戳也不会覆盖另一局。文件名只是索引，训练与校验仍以 JSONL 内的 `episode_id`、事件链和 metadata 为准；旧 UUID 文件不改名、不改内容。

## macOS

完全退出游戏后，在仓库根目录执行：

```bash
./scripts/collector-macos.sh --action test
./scripts/collector-macos.sh --action install \
  --dataset-dir "$PWD/artifacts/human-dataset" \
  --information-mode no-sl
./scripts/collector-macos.sh --action launch \
  --dataset-dir "$PWD/artifacts/human-dataset" \
  --information-mode no-sl
```

要采集允许回档的跑局，把两处 `no-sl` 改为 `sl`。配置会同时写到独立 Mod 目录的 `SlayTheModelDataCollector.runtime.json`，所以也可以在安装后从 Steam 启动；修改目录或模式时重新运行 `install` 或 `launch`。

安装脚本会持久写入 `SLAY_THE_MODEL_COLLECTOR_ENABLED=1`，因此以后直接从 Steam 启动也会继续采集。要停用，可把该 runtime JSON 中的值改为 `0`，或在游戏完全退出后移除整个 `SlayTheModelDataCollector` Mod 目录；已有 dataset 不会被删除。

采集人类示范时，请把同仓库的 Adapter 局内、局外策略都设为 `manual`。采集器会读取相邻 Adapter 的 runtime JSON，并兼容检查旧版 `SLAY_THE_MODEL_LIVE_POLICY`；若发现 `first-legal` 或 `mcts`，会把动作标为 `automation_or_unknown/policy`，不会伪装成人类示范。

## Windows（未经游戏内测试）

```powershell
./scripts/collector-windows.ps1 -Action Test
./scripts/collector-windows.ps1 -Action Install `
  -DatasetDir "$PWD\artifacts\human-dataset" `
  -InformationMode no-sl
./scripts/collector-windows.ps1 -Action Launch `
  -DatasetDir "$PWD\artifacts\human-dataset" `
  -InformationMode no-sl
```

Windows 脚本沿用主工程的 Steam 路径发现逻辑，但 v0.1 尚未做 Windows 游戏内交互验证。

## v0.1 覆盖范围与边界

当前结构化记录包括：

- 战斗中的出牌、目标、药水和结束回合；
- 地图路线、事件、休息点、宝箱遗物、奖励领取与卡牌奖励；
- 宝箱开启/离开、奖励页离开、商店卡牌/遗物/药水购买、删牌入口和离开商店；
- 原生单卡、牌组网格和遗物选择页面；工作树已新增卡包、有边界的局外多卡和战斗多卡选择、木札专用附魔网格，以及 Crystal Sphere 工具、格子和离开操作；
- 跑局开始、战斗边界、存读档边界和最终胜负。

v0.1 仅支持单人。主菜单、角色选择等跑局开始前操作不属于 episode。普通卡牌奖励的选牌与 `Skip` 已按原生索引结构化；可见 reroll/其他 alternative 会进入合法动作集合，但实际选择它们仍记缺口。战斗内单卡选择路径覆盖手牌、战斗牌堆和原生单卡选择器。局外卡包在实际点击时冻结 UI 可见卡包与内容，以 `ChooseCardBundle` 表示一次选择；局外多卡在原生选择器打开时冻结候选。新的局外 observation v5 用 `card_selection_options` 按当时选择器顺序列出候选，用 `choice_context.min_selections/max_selections` 保存原生约束；`legal_actions` 只有一个 `ChooseCardSet` 或 `RemoveCardSet` 模板，可能另有取消动作。确认并核对原生结果后，实际所选集合以 `action_submitted.selected_action.selected_cards` 保存，`selected_action_index` 仍指向模板。选牌张数不再受采集器的三张上限或组合枚举预算限制；19 张中选 4 张只产生 19 个候选和一个模板。新路径继续核对点击或确认状态、原生回执和选择器 Task 结果，失败则记 `coverage_gap`；普通网格多卡点击时核对网格候选身份、顺序和所点卡的可见节点，界面重排后按卡牌对象身份映射到原生回执序号。Task 先完成而回执尚未到达时会延后一轮核验。`fcbb...` 实机部分验证了局外二张选牌候选冻结，但旧代码将 NSimple 的单个 `Index` 回执误判为类型不符；工作树现接受 `Index` 与 `Indexes`，修复后尚未实机验证。`dd28...` 已完整验证一次 card bundle；删牌集合仍未实机覆盖。新的集合模板已经通过 19 选 4 的离线 smoke，尚未安装或实机验证；旧局的缺口不可回填。其他复杂事件小游戏和未知 Mod 页面仍不能无歧义映射。快速输入只有在点击时合法集合完整、原生提交动作可精确匹配时才生成结构化 step；其他实际执行的输入会写 `coverage_gap`，令整局 `value_target_valid=false`。纯审计信息写 `diagnostic`。上传、匿名化服务和用户同意流程留到后续版本；当前已有首版 BC-only JSONL → tensor shard 转换器。

`TO_TRANSFORM` 使用独立的 `NDeckTransformSelectScreen`。当前工作树从原生 `CardSelectCmd` 过滤后的选择器 `_cards` 和 `_prefs` 冻结候选顺序、最少/最多张数；点击时按 `CardModel` 对象身份与选择器选中集合核对，预览页最终确认后再核对选择器 Task 和原生 `DeckCard` 回执。该路径不以动画中 UI holder 是否已出现或可见为候选门槛；证据不足仍写 `coverage_gap`。目前已通过 build、collector smoke 和独立 Harmony ABI 检查，尚无新代码的实机轨迹。

战斗内手牌选择（包括烤面包手套）现在从单人玩家的内部 `PlayerCombatState.Hand.Cards` 读取候选，再应用原生 `NPlayerHand.SelectCards` 收到的筛选条件；UI holder 的数量和抽牌动画不决定候选集合。冻结时仍要求每张候选能映射到唯一原生 `CombatCardIndex`；失败就记缺口，不补造合法动作。候选卡面的 `display` 仍在人工输入时按 UI 可见卡对象尝试补充，读不到时为 null。人工点击或确认、Task 选择结果与原生 `CombatCard` 回执继续分开核验：优先用精确原生 choice ID 关联；ID 未绑定时只接受同一 run generation、同一战斗、同一非空父动作下唯一未绑定选择，并要求已完成 Task 的卡牌对象映射到冻结候选后与原生卡 ID 完全一致。已完成的选择器 ticket 也可等待回执；同一父动作打开后续选择器时，先前无 ID ticket 失去兜底资格，即使后续选择器的候选冻结失败。歧义、缺人工证据、Task 未完成或不匹配仍写 `coverage_gap`。预留 ID、选择器打开以及 reservation 被 guard 忽略时新增只读诊断，用于下一局排查时序。缺原生 ID 时 `active_choice.choice_id` 是合成的协议标识；未来在线执行器必须从原生选择上下文绑定真实 ID，不能直接拿该字段执行。该路径尚未安装或实机验证，headless runner 将来应直接从同一内部选择语义构造 `active_choice`，无需 `NPlayerHand`。

Crystal Sphere 的工作树采集路径基于原生 `SetSmallDivination`、`SetBigDivination`、`OnCellClicked` 和 `OnProceedButtonPressed`。点击前冻结整块可见棋盘、剩余次数、当前工具，以及所有当时可点的工具、隐藏格和离开按钮；局外 observation v3 仅用于此页面，其他局外页面仍写 v2。格子动作只含坐标；原生预先放好的隐藏 `Item` 不进入观察、动作或状态标记。物品类别须同时满足原生已揭示、格子已翻开、对应 UI 图标材质已显示，才写入 `revealed_item_kind`；可见图标、卡框和横幅的资源路径还会在可取得时写入 `revealed_visual_id`，无法读取时为 null。异步翻格 Task 成功后，下一次稳定决策或跑局边界才结算动作和奖励；所有未完成的翻格 Task 都是采集屏障，提前重叠的点击或无法核对的 UI 仍记 `coverage_gap` 并排除不可靠标签。未来 headless runner 从自己的小游戏观察构造同一协议与动作，复用统一 writer，不依赖 live 的 Godot UI。这条新路径已通过离线 ABI/协议测试，该局采集时安装的 DLL 已包含它，但尚未实机触发验证；旧 `8adb...` 的三次 Crystal Sphere gap 不回填。

附魔网格在原生 `NDeckEnchantSelectScreen` 打开后冻结牌组候选，并核对屏幕显示的附魔标题、说明和图标。旧代码仅放行木札的 `Adroit` 和浸水抄写室的 `Steady`；最新 `24b...` 实机的 `Sharp`、`Momentum` 因此被明确记为缺口。工作树现按同一原生附魔页的可见信息通用记录效果 ID 和实际显示的标题、说明；只有能证明原生强度整数直接出现在界面文字时才记录数值，否则标为 `unobserved`，不把隐藏的 `_enchantmentAmount` 写入选择上下文。单卡和多卡附魔均走 `ChooseCardSet` 及同一套可见网格、人工点击、预览页确认、Task 结果和原生 `DeckCard` 回执核对；附魔页的 `requires_confirmation` 固定为 true。木札 20 张候选选 1–3 张、浸水抄写室 12 张候选恰选 2 张，都会只列一个合法集合模板，具体所选卡随动作提交写入。可见性不足、回执不一致时仍写 `coverage_gap`。新模板已通过离线构建，尚未安装或实机验证；旧文件的缺口不回填。

## 实机文件审计

`artifacts/human-dataset/episodes/05e34e83ee474869a986c78325db9813.jsonl` 是修复前的第二份实机文件，共 2460 条事件，使用 `whole-run-v2`。局级 metadata 已记录角色、进阶、开局时间、种子及 Steam 身份；这些值没有写入逐步观察。文件中有 563 条 `decision`、563 条 `action_submitted`、552 条 `execution_result` 和 549 条 `reward`。18 个缺口分为：14 次 `combat_action_without_decision`、2 次 `combat_nested_single_card_selection_not_supported`、2 次 `combat_nested_card_choice_not_supported`。其中 11 次战斗缺口打断了待结算父动作，留下 11 个没有执行结果的已提交动作；另有 3 条正常的 `cancelled` 执行结果没有 reward。终局为胜利，但 `completeness=incomplete`、`value_target_valid=false`，不能直接生成可靠的整局 return。

这份 JSONL 保持原样，不能在事后补造缺失的选择候选、动作结果或 reward。新增原生人工动作归属与战斗单卡选择采集是针对这些缺口的代码修复；需要重新完成实机跑局，检查新的 `coverage_gap`、动作配对和终局有效性。

随后采得的 `artifacts/human-dataset/episodes/c5ff3eb971c54f1ebf22fbb15ac71a63.jsonl` 共 2614 条事件，含 577 条 `decision`、577 条 `action_submitted`、577 条 `execution_result` 和 576 条 `reward`。60 个 `coverage_gap` 中，43 个是 `manual_combat_action_during_pending`：玩家在前一动作尚未稳定结算时快速输入，旧采集器只记录缺口，无法保留该输入的原生动作身份与独立结果。另有 10 个 `combat_action_without_stable_pre_state`，其余为选择器和多选等缺口。终局为胜利，但 `completeness=incomplete`、`value_target_valid=false`。这份文件早于上述快速输入原始事件修复，必须原样保留；新修复是否正确仍需新的实机 JSONL 验证。

先前的 `artifacts/human-dataset/episodes/ff7431d1cf274845a82b706188025e94.jsonl` 有 1402 条事件，终局失败，hash 链完整；232 个结构化 decision 都有对应的执行结果和 reward。178 个原始手动输入均有原生结果，其中 23 个没有结构化 step：21 个是前一动作执行期间的快速点击，另 2 个发生在回合转换附近（一个实际执行、一个执行前取消）。另有一次 Attack Potion 的临时 `CARD.CINDER` 候选不在 `NetCombatCardDb`，使单卡选择冻结失败。全局 24 个缺口令 `completeness=incomplete`、`value_target_valid=false`。这份旧 JSONL 不能回填成完整轨迹。

之后的 `artifacts/human-dataset/episodes/11e8ccfd108f448abfa2e05639797785.jsonl` 有 1135 行，序号和内容哈希链完整；200 个结构化 decision/action/result/reward 全部配对，另有 2 个 `manual_combat_action_during_pending` 缺口；终局失败、`completeness=incomplete`、`value_target_valid=false`。

先前的 `artifacts/human-dataset/episodes/9ecfc38a6d1545a6afbf08c1576e0e1f.jsonl` 终局胜利，共 5065 行；`event_sequence`、每行内容 SHA-256 和前序哈希链均完整。887 个 decision 中，873 个 action submission 都有 execution result，870 个成功动作都有 reward；14 个未提交的 decision 对应玩家实际点击但尚不支持结构化执行的 `SACRIFICE` 卡牌奖励替代选项。611 次原始手动输入均有原生结果，其中 604 次已结构化，80 次捕获 `queued_legal_set`；临时生成卡 `Index` 选择也有成功关联。35 个缺口包括 14 次 `SACRIFICE` 替代选项、7 次回合开始阶段的快速出牌、7 次 Gambling Chip 多选及其 7 次未结构化原生回执。7 次快速出牌都有 `observed_transition` 原生结果，但没有结构化 BC 标签：点击时玩家处于 `Start` 阶段，到原生执行时才进入 `Play`；其中 5 次之间又抽到牌，不能把执行时的合法动作集倒填为点击时观察。整局为 `completeness=incomplete`、`value_target_valid=false`；这份已发布 JSONL 必须原样保留。

此前一局的 episode ID 为 `39445f716b8d4dc591ed9700ee8be3db`，已按新格式发布正式 JSONL。文件名的 Steam ID、角色、进阶、UTC 开局时间和 episode ID 均与首行 metadata 一致；全文件 4721 行，832 个提交动作均有 execution result，571 次原始手动输入均有原生结果。5 个缺口均为 `manual_combat_action_during_pending`；终局胜利，但仍为 `completeness=incomplete`、`value_target_valid=false`。

2026-09-28 另一局的 episode ID 为 `36df5d1b03a74ca8a75c3917297b7d23`，发布文件有 4747 行，事件序号、逐行 SHA-256 链及 835 个决策步骤都连续；835 条 decision、action submission 和 execution result 全部配对，833 个成功结果有 reward，2 个取消结果没有 reward，568 次原始输入各有原生结果。终局胜利，但 20 个 gap 使它仍为 `incomplete`、`value_target_valid=false`：17 个单卡 `Index` 回执是选择器 ID 晚绑定导致的误报，另外有 1 次快速输入和 1 组多卡选择产生的 2 个真实缺口。原始文件不回写。该局遗物上下文虽然每步都有原生字段，但显示计数均为 0，不能证明所有遗物计数器已正确采集。

先前一局的 episode ID 为 `59261c11694548228f801a8e6ea7970d`，正式文件有 4842 行，终止换行、事件序号、逐行 SHA-256 与前序哈希链均完整。857 个连续决策的 decision/action submission/execution result/reward 全部配对，585 次手动战斗输入均有原生结果；终局胜利。3 个真实缺口分别是开局卡包 `card_bundle_selection_not_supported`、事件一次选 2 张牌和一次移除 3 张牌的 `unsupported_multi_card_selection`。因此仍是 `completeness=incomplete`、`value_target_valid=false`，不能当作完整整局 return。该局还验证了 482 次实际出牌所选卡的 `display` 与说明、8 次结构化 `Start` 输入（含 2 次用药），以及 3 次单卡 `Index` 原生回执的正确关联。新 card bundle/多卡代码针对这 3 个缺口；旧 JSONL 不回写，也不能用选择后的牌组变化倒推点击时的合法候选。

先前一局的 episode ID 为 `fcbb45909a9044f6b696695c35439b54`，正式 JSONL 有 4200 行，终止换行、事件序号、逐行 SHA-256 与前序哈希链均完整；global step 0..749 连续。750 个 decision 中，749 个有 action submission 与 execution result，747 个成功结果有 reward，另 2 个 `cancelled` 正常没有 reward。491 次手动输入均有原生结果，但 1 次快速输入没有结构化 step 且有执行风险。终局胜利，5 个 gap 分别是：一次 `Start` 快速出牌时可见候选无法冻结；二张局外选牌在 global step 80 收到单个原生 `Index`，旧代码误判 `multi_card_native_result_mismatch`，对应 decision 没有 action submission；三次 Crystal Sphere 事件小游戏交互尚未支持。该局仍为 `completeness=incomplete`、`value_target_valid=false`，不可生成完整整局 return。519 个战斗 decision 使用 observation v3，231 个局外 decision 使用 observation v2，750 个 run context 为 v2；404 次已提交出牌的所选卡均有 `display` 和说明，2 次 `Start` 输入（1 张卡、1 瓶药水）成功结构化。战斗遗物 5048/5048、局外遗物 2179/2179 个实例有展示字段；681 个敌意图有可见性标记，4 个不可见或未核实项没有意图内容。逐步信息模式全为 `no_sl`，无 save/load；局级身份、种子和开局时间没有进入逐步 observation/context。原始 JSONL 不回写；新 `Index`/`Indexes` 局外多卡修复及删牌集合仍需新的实机轨迹验证；card bundle 已由后续 `dd28...` 实机验证一次。

先前一局的 episode ID 为 `dd28da34ecaf4dcda4c0abbcf5ae3bf9`，正式 JSONL 共 1590 行，global step 0..278 的 279 组 decision/action submission/execution result/reward 全部配对；199 组手动输入与原生结果也全部配对，且没有未结构化输入。终局 defeat，唯一缺口是事件 1523 的 `combat_multi_card_selection_not_supported`：Gambler's Brew 在战斗中提供 5 个候选，玩家选择 4 张；事件 1524–1525 有原生 `CombatCard` 回执，但该子选择没有完整合法集合或结构化动作标签。父药水动作（global step 268）虽有执行结果和药水数量奖励，包含缺失子选择的完整转移仍不应作为可靠监督。整局 `completeness=incomplete`、`value_target_valid=false`。两次 `Start` 快速出牌（global step 11、121）和一次 `ChooseCardBundle`（global step 1，原生 `Index` 回执、牌组增加 3 张）均完整结构化。203 个战斗 observation 使用 v3，76 个局外 observation 使用 v2；161 次已提交出牌的所选卡都有 `display` 和说明，没有发现新的观察契约问题。本局未触发局外二张选牌、删牌集合或 Crystal Sphere，故不能据此验证上一局的回执修复或宣称后两条路径已解决；原始 JSONL 保持不变。

这份 `dd28...` 文件是修复前的事实记录，不能通过更新代码补成完整轨迹。战斗多卡修复已通过 collector smoke、DataCollector Release 构建、主工程测试、直接运行的 HeadlessCollector smoke 和临时 Harmony ABI 检查；`git diff --check` 通过。这些离线结果只说明协议、构建和补丁入口可用，仍需安装当前构建并用真实手牌多选检查候选、确认时已选集、Task、`CombatCard` 回执和子决策配对。

下一局 `4b3d120ce918402c936238fef818ab46` 有 2822 行，501 组 decision/action/result/reward 和 335 组原始手动输入/结果全部配对，事件链完整、无 coverage gap；终局 defeat，标记为 `complete`、`value_target_valid=true`。本局 24 次战斗内卡牌选择均为单选，不能验证新的 Gambler's Brew 多选路径。独立语义核对揭示药水槽位错位：359 个战斗决策中 116 个 `observation.players[].potions` 的 `slot_index` 与同一步 `context.run_context.players[].potions` 不一致；其中 106 个的合法药水动作不能在观察中按真实槽位正确寻址，4 次实际用药直接选中了观察中缺失的槽（global step 207、412、495、499）。模型 ID 数量与顺序一致，错误来自把原生紧密药水列表重新编号为 0..N-1；该局的完整事件链和回报不等于观察特征可直接训练。

工作树现给战斗快照附加可选真实药水槽号，按原生 `Player.PotionSlots` 核对，再投影到局内及 run 观察；局内采集额外核对观察与原生槽位，新数据写入入口拒绝 `UsePotion` 引用观察中不存在的槽，历史事件回放仍允许读出旧错位以便审计。无空槽时保留旧快照序列化和指纹；新修复已通过离线测试和 Release 构建，并在后续 `8adb...` 实机的稀疏槽位中验证。旧 JSONL 不改写。`python3 scripts/audit-collector-potions.py` 是只读审计，退出码 2 表示发现错位或无法核对；`--json` 输出每局完整 global step。对当前 17 份正式文件的复核发现 7 份的 748 个战斗决策存在 observation 与同一步 run context 药水 `(slot_index, model_id)` 不一致，其中 706 个合法动作集合、16 个实际所选用药动作受影响，0 个无法核对。真实稀疏槽位本身不是错误，较新文件可同时记录稀疏槽位和正确观察。当前 `collector-raw-bc-v3` assembler 会对照同一步完整药水集合并过滤错位步骤；尚未自动修正原始或派生观察，不能把旧错误步骤直接作为 BC/value 输入。

最新实机 `8adb3d74082043b4943d53f0199eb22a` 有 2915 行，530 个连续 decision 中 529 个有提交和执行结果；终局 win，但 6 个 coverage gap 令 `value_target_valid=false`。其中 Crystal Sphere 的三次格子点击与木札附魔选择均由旧版采集器明确记为缺口；木札在 20 张候选中原生回执选 3 张，专用 `NDeckEnchantSelectScreen` 被旧版选择器类型限制拒绝。另有一次涅奥之怒空集缺人工确认证据、一次商店购买动作无法匹配。28 个稀疏药水槽位决策与 4 次实际用药均核对正确；13 次其他涅奥之怒多卡选择已有结构化动作和原生回执。旧文件不回填；新 Crystal Sphere 与木札路径仍需一局实测。

后一局 `f86be9b6ec89451c9a6c87e1558e8e5f` 有 1792 行，完整事件哈希链与 320 组 decision/action/result/reward，217 组原始输入/结果均配对。唯一缺口在事件序号 348：`WaterloggedScriptorium.PRICKLY_SPONGE` 的 `TO_ENCHANT` 有 12 张候选，原生 `DeckCard` 回执选择牌组索引 `[11,8]`，但未建立子决策。这次不是木札；实机安装的 DLL 不含新增附魔界面补丁，且其效果 `Steady` 在当时的工作树也尚未支持。终局 defeat、`completeness=incomplete`、`value_target_valid=false`。218 个战斗 decision 的药水槽位审计无错位；166 次所选出牌均有手牌 `display`；新版本的附魔路径仍需重新安装和实机测试，旧文件不回填。

先前一局 `ea59b2a19b2d44d99f5e4620df632e33` 有 2382 行，哈希链和 428 个连续 global step 完整；428 组 decision/action/result 配对，425 个成功结果有 reward，3 个原生领取药水取消不需 reward。274 组原始手动输入与结果全部配对，终局 defeat、无 save/load、无 gap，`completeness=complete`、`value_target_valid=true`。281 个战斗 decision 的药水槽位审计为 0 错位；210 次所选出牌都有 `display`，一张未选手牌在 queued 输入步骤缺少 display，需保留缺失掩码。该局采集时的游戏内 DLL 与当时本地构建一致，但没有触发木札、浸水抄写室或 Crystal Sphere，新路径仍未得到实机事件证据。queued 输入的 global step 204 将已提交的卡 11 再次列入合法动作，且该卡当时无 display；所选卡 14 有 display。原始文件不改写，派生训练数据必须按 `pending_manual_actions` 修正合法集并重映射标签，或排除该步及受影响窗口。本地工作树已过滤这类重复候选，尚未实机验证。

再后一局 `24b023e841e44bb5a2dde5239e999fa2` 有 3859 行、687 个连续 global step，全部 decision/action/result 配对；684 个成功动作有 reward，3 个取消无 reward。463 次原始手动输入及结果配对，461 次结构化。终局 win，但 4 个 gap 令 `completeness=incomplete`、`value_target_valid=false`。global step 23/94 附近的两次 `Start` 快速连点因模型 Hand 与 UI 可见手牌集合不符，第二次出牌实际执行却没有结构化决策，父动作转移也标为 contaminated；点击时可见快照缺失，不能断言具体是哪张牌造成差异。另两次 `TO_ENCHANT` 分别来自 `SELF_HELP_BOOK.READ_THE_BACK` 的 `Sharp` 和购买 `PUNCH_DAGGER` 的 `Momentum`，当时安装版的 `Adroit`/`Steady` 白名单直接拒绝。54 个带 pending 的决策均无已排队卡重复进入合法动作，377 次所选出牌均有 display；4 次 `PURITY` 手牌多选已成功核对原生回执。新通用附魔路径尚未安装或实机验证，本文件不回填。

先前 `ba8f9848c0804175b3c6e64f2fc03747` 文件有 2987 行、532 组 decision/submission/result 配对；2 个 gap 令败局的 `value_target_valid=false`。其中第二次 `Start` 快速出牌在第一张牌点击约 184 毫秒后发生，原生两张牌最终都执行成功。旧采集器发现点击时内部 Hand 比 UI 可见手牌多一张，因旧 UI 核对门槛拒绝冻结第二步；后续快照出现从 Draw 进入 Hand 的 `SLIMED`，但缺少点击时完整快照，不能确定差异牌身份。新契约按点击时内部状态记录，此旧 JSONL 不补造决策，修复仍需新一局实机验证。

`4be275a1f2554b938c3f90908c02ef23` 的 `TO_TRANSFORM` 有 15 张原生候选，`41774d4079db46029762d6b64df1a5bc` 在 `EVENT.TRIAL` 中有 29 张；两份旧 JSONL 都报 `multi_card_selection_options_unavailable`，未冻结子决策。后一局原生 `DeckCard` 回执选了牌组索引 `[0,1]`，仍不能倒推出完整点击时动作标签。新 `NDeckTransformSelectScreen` 路径只修改后续采集，旧文件不回填。

同一铁甲胜局还记录了 97 次烤面包手套单卡选择。每次已有冻结候选、结构化选择动作和原生 `CombatCard` 回执；逐次对照后，所选卡 ID 与回执 97/97 一致，但旧采集器的 ticket 没绑定原生 choice ID，因此每次各报一次 `combat_card_choice_without_selector` 与 `combat_choice_native_result_missing`。这些缺口使整局 `completeness=incomplete`、`value_target_valid=false`，BC-only 转换器继续排除受影响的选择标签；旧 JSONL 不回写。新的内部手牌候选和回执关联路径只能由后续实机轨迹验证。

## headless 共用记录接口

未来 headless runner 应为每张内部手牌提供等价的原生当前费用投影，`description=null`、`dynamic_values=[]`，以便与 live collector v5 训练特征对齐；不能因为没有 UI 就把整张牌删除。当前泛协议 `DecisionObservationProjector.ToCombat` 与 `HeadlessEpisodeRecorder` 尚未强制这一投影，仍可写出 v5 且 Hand `display=null`；assembler 必须保留费用缺失 mask，不能假定所有 v5 都有费用。选择器候选、敌意图和遗物展示仍按各自原有契约处理。

未来全局 headless runner 或其控制界面可构造协议层的 `CombatDecisionPoint` 或 `OutsideCombatDecisionPoint`，通过 `HeadlessEpisodeRecorder` 写 `source=headless` 的 episode。`source` 表示环境来源，`policy.actor` 仍可独立表示人类、策略或脚本。这个封装使用与 live 相同的 `CollectorStore`、`EpisodeSession`、`JsonlEpisodeJournal`、dataset manifest 和 `whole-run-v2` 奖励计算器；不另建 JSONL writer。headless 战斗多选应从其 `CardSelectCmd` 选择器取得候选、约束与完成结果，构造同一协议 `active_choice`/`ResolveChoice` 集合动作，不能依赖 live 的 `NPlayerHand` UI。runner 仍须自行提供真实的状态、合法动作、执行结果、指标和终局；目前尚未实现全局模拟器。现有 JSONL → tensor shard assembler 支持 no-SL BC-only 和完整整局的 HP RTG，两者均须通过对应审计门槛。
