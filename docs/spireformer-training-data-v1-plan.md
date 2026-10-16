# SpireFormer 训练数据 v1 规划

更新：2026-10-15
状态：raw JSONL v1、live collector v0.1 与共享 headless writer 已实现。2026-09-30 本地把局内/局外多卡改为候选牌、单个合法模板和提交时的真实集合；SpireFormer 共享主干新增集合选择头，tensor shard v2 支持对应训练字段。手动出牌的观察边界改为点击时游戏内部状态，live collector 的战斗 observation 升 v5：普通 Hand 每张卡只从原生 `CardModel` 投影当前费用，不再读取 UI holder/说明。JSONL → shard assembler 保留 BC-only 模式，并增加只对完整、经审计的 no-SL `whole-run-v2` 整局计算 `whole-run-hp-safe-v1` RTG 的模式；独立 value target 仍缺失。全局 headless runner 尚未实现，新采集路径未实机验证，旧 JSONL 保持原样。

## 1. 实施顺序

2026-10-15 用户确定首版分幕奖励 `whole-run-act-v1`：三幕胜利 +1/+2/+3，
非 Boss 战后净 HP 变化 / 战后 maxHP，每幕 Boss 前全量统计已升级牌与遗物，
第三幕另加 HP/maxHP，败北追加 −10。collector 新增精确原生边界 diagnostic，
Python 自动生成逐事件奖励与决策 RTG；旧日志缺少边界，不近似回填。
现有 Tiny 仍是 BC 模型。见 [分幕奖励设计与实现](spireformer-act-reward-v1.md)。

2026-10-14 历史奖励补充：曾采用 `whole-run-win-v1`（最终通关 +1、失败 0、
过程 0、折扣 1），由 Python assembler 从通过严格审计的终局自动生成 RTG。
纯终局模式无需 HP delta；保留 no-SL、开局观察、原生终局、无缺口等整局门槛，
不把缺失回报或放弃视为失败。旧 `whole-run-hp-safe-v1` 保留为可选历史方案。
RTG 从整局计算后再切窗口，value 标签继续关闭，奖励版本写入 shard/checkpoint。
当前 8 局本地日志仅有 `32a...` 的 228 步败局合格，已转换为独立 holdout 进行
校验；现有 8,717 步混合 BC 数据与 checkpoint 不冒充为 RTG 训练结果。
自主运行另需目标 RTG（本方案先设 1），不会从未知未来获得真实 RTG。
完整入口和限制见 [模型说明](../model/spireformer/README.md)。

后续严格按同一条数据链推进：

1. 固定原始轨迹事件格式与版本规则；
2. 在正常启动的游戏中实现 live collector，先验证数据完整性；
3. 用 live/golden 原始事件验证离线 tensorizer，并生成训练 shard；
4. 用现有 `HeadlessEpisodeRecorder` 将全局 headless runner 接入同一 writer，不另外发明一种格式；
5. shard 只做可重建缓存，原始 JSONL 永远是 source of truth。

这样 headless 只替换“状态从哪里产生”，不会同时重写观察、动作、reward 和训练格式。

## 2. 文件布局

```text
dataset-root/
  dataset-manifest.json
  episodes/
    <SteamID>_<character>_A<ascension>_<UTC timestamp>_<episode-id>.jsonl
    <episode-id>.jsonl  # legacy publication name
  tensors/
    <tensorizer-version>-<vocab-hash>-<reward-version>/
      manifest.json
      shard-<publication-id>-000000.pt
      shard-<publication-id>-000001.pt
```

`episodes/*.jsonl` 是协议级原始记录。新文件名提供 Steam ID、角色、进阶和 UTC 开局时间的可读索引，末尾 episode ID 防止冲突；缺失值用显式占位。文件名不参与训练样本身份或 hash 链校验，assembler 必须从已验证事件头读取 `episode_id`。旧 UUID 文件保持可读且不回写。`tensors/` 是 PyTorch 训练缓存；当前写入 schema v2，字段见 `model/spireformer/docs/tensor-shard-format-v2.md`，读取端仍兼容旧 v1 shard。

## 3. JSONL 事件公共头

每一行是独立 JSON object，并具有：

```json
{
  "schema_version": 1,
  "event_type": "decision",
  "event_id": "uuid",
  "episode_id": "uuid",
  "event_sequence": 117,
  "global_step": 42,
  "timeline_generation": 0,
  "recorded_at_utc": "2026-09-24T12:34:56.000Z",
  "source": "live",
  "previous_event_sha256": "sha256",
  "payload": {},
  "event_sha256": "sha256"
}
```

- `source` 只能是 `live` 或 `headless`；它属于环境来源审计字段，不作为模型特征，与 `action_submitted.policy.actor=human|policy|script` 正交。未来 headless 控制界面的人类操作也可保留 `actor=human`。
- `information_regime` 位于 `decision.payload`，描述观察的信息边界，只能是 `no_sl`、
  `sl` 或 `unknown`；它与 `source` 正交，例如 headless 同样可以生成严格 no-SL 观察。
- `event_sequence` 对同一 episode 的**每一行事件**从零开始严格递增，是 JSONL 的
  唯一事件顺序。时间戳只用于审计，不能代替它。
- `global_step` 对同一 episode 的**每次决策**从零开始严格递增，局内和局外共用一条
  时间轴。`decision` 分配新值；其 `action_submitted`、`execution_result` 和
  `reward` 复制该值用于关联，而不再次递增。与具体决策无关的生命周期事件可令其为
  `null`。非结构化手动战斗输入事件也使用 `null`，不能因此新增一个训练 step。
- 游戏 seed 写在 `episode_started` 的受限 metadata 中用于复现，但不能进入 policy observation 或 tensor feature。Steam 身份与时间戳遵循同一隔离规则。
- 写盘采用 append + flush；每个事件必须先完整编码为单行 UTF-8 JSON，再一次性追加
  换行。崩溃后的半局保留，但默认不产生 value label。

## 4. 事件类型

### 4.1 `episode_started`

记录协议 build、collector/reward 版本、`no_sl_expected` 和受限 metadata；角色、进阶、
原生开局时间、种子、可取得的 Steam 昵称/ID、采集标签与配置的信息模式放在 metadata 中。
事件包络的 `recorded_at_utc` 是采集时间；`run_started_at_utc` 是原生跑局创建时间。
它不包含第一步观察，`global_step` 为 `null`。Steam 身份、seed、时间戳和 run key 只能用于
来源审计、数据划分与复现，tensorizer 必须从所有 policy feature 中排除。

### 4.2 `decision`

记录一条真正暴露给人类或策略的决策边界，但不预先声称某个动作已被执行：

```json
{
  "event_type": "decision",
  "decision_id": "uuid",
  "global_step": 42,
  "domain": "combat",
  "information_regime": "no_sl",
  "state_fingerprint": "sha256",
  "observation": {},
  "legal_actions": [],
  "action_keys": [],
  "context": { "run_context": {}, "audit": {} }
}
```

- `observation` 与 `legal_actions` 必须来自过滤后的 `CombatDecisionPoint` 或 `OutsideCombatDecisionPoint`，不能直接序列化 Godot node、checkpoint、隐藏 RNG 或 `NativeMctsRequest`。
- `state_fingerprint` 只能由过滤、规范化后的 policy observation 与 legal actions
  计算。若执行器还需要包含隐藏原生状态的 stale-state guard，应另存为受限的
  `execution_guard_fingerprint`，且 tensorizer 永远不得读取它。
- 没有后续成功动作的 decision 仍然是有效审计记录，但不能成为行为克隆标签。
- `queued_combat_input=true` 表示这一战斗 decision 在较早的手动动作仍待结算时按真实点击时间创建。`observation.pending_manual_actions` 保存玩家已提交而未完成的动作描述；它是当时已知信息，不包含原生 `GameAction` ID、时间戳或未来结果。未排队的旧事件仍按原有 v1 字段回放。
- 战斗内卡牌选择使用同一 `domain=combat`：`observation.active_choice.cards` 冻结每张可见候选、原生卡实例 ID 与选择数约束；单卡仍逐个列出 `ResolveChoice`。多卡的 `legal_actions` 只列一个 `is_selection_template=true` 的 `ResolveChoice`，实际选中集合在 `action_submitted.selected_action.selected_combat_card_ids`，不枚举组合；候选缺原生 ID 或人工确认、Task、原生回执核对失败仍记 gap。最少选 0 张时空集可为成功选择；最少选 1 张且原生允许取消时，取消是单独的空选择动作，不作为模板内非法空集。选择 ID 与候选序号只用于本次核对，不作跨局模型数值。旧 `8adb...` 中 13 次涅奥之怒集合选择是旧枚举版实机证据，新模板路径与 Gambler's Brew 手牌多选仍待实机验证。
- 局外卡包动作 `ChooseCardBundle` 保留 `bundle_cards`。局外多卡 observation v5 在 `card_selection_options` 中逐项记录可见候选的 `option_index` / `model_id`，删牌还带当时的 `deck_index`；`legal_actions` 只列一个 `ChooseCardSet` / `RemoveCardSet` 模板，可取消时另列取消动作。真实 `selected_cards` 放在 `action_submitted.selected_action`；`selected_action_index` 和 key 仍指向模板。训练时候选牌作为 token，按本次真实集合监督；不把原生序号当跨局稳定特征，也不枚举 20 张选 3 张的 1350 种组合。选择数取原生约束与实际候选数，不设人为最多 3 张或 4096 个组合的预算。人工点击、UI 候选、Index/Indexes/DeckCard 回执与 Task 结果仍须一致；旧 `fcbb...` 的失败标签和其他旧 JSONL 均不回填。
- Crystal Sphere 的新采集路径使用局外 observation v3，在 `crystal_sphere` 中保存可见棋盘、剩余占卜次数、已选工具和结束状态；格子动作只用坐标，不写预置隐藏物品。`revealed_item_kind` 和可选 `revealed_visual_id` 只有在原生揭示与对应 UI 图标完整显现均核对后才出现。tensorizer 须按 v3 解析此可选结构，为旧版无棋盘、未显现物品类别或视觉资源路径分别保留缺失 mask，不得从后续揭示或结局补填旧决策。未来 headless runner 自行从其小游戏状态构造同一协议 DTO 与合法动作，复用统一 episode writer；不能依赖 live 的 Godot 节点或 shader 检查。此新路径尚未实机验证。

#### combat observation v2

JSONL 外层事件仍为 `schema_version=1`；`domain=combat` 的内部 `observation.schema_version=2` 是独立版本。它保留既有的 HP、格挡、能力、药水、无隐藏顺序的牌堆集合和充能球，同时扩充决策状态。手动战斗步骤的手牌实体、抽牌堆及弃牌堆取点击时原生内部状态；UI 抽牌动画不改变这一边界：

- `players[]` 增加 `gold` 与 `orb_capacity`。金币会影响部分战斗效果；容量与当前充能球列表分别表达槽位上限和已持有球。
- `players[].piles[].cards[]` 增加 `upgrade_level`、`enchantment_id` / `enchantment_amount`。v2–v4 的普通手牌 `display` 原本保存 UI 卡面的描述和能量/星星/X 成本，可能因动画时序为 null；这些历史字段按其原版本读取。手牌实体集合始终单独取内部 Hand，不能用 `display` 决定成员或合法动作。旧 v2/v3 还保存未经渲染核对的所有原生动态预览值。live collector v5 改为每张内部 Hand 卡从原生 `CardModel` 投影当前费用；泛协议与 headless 路径仍可为 null，具体见下文。
- `companions[]` 保存当前在场伙伴，例如 Osty 的模型 ID、所属玩家、HP、格挡与能力；战斗友方阵容与玩家宠物列表都用于核对，非阵容对象还须有同一战斗、存活、可击中且 UI 节点可见的证据，不由可能残留的旧引用推断在场状态。
- `enemy_intents[]` 只保存敌人 UI 已显示且能与原生意图对象核对的图标语义和显示文字。攻击数字须与当前显示标签一致；未显示或核对失败分别保留 `not_visible` / `unverified` 状态，不把原生 `NextMove` 当成玩家已知信息。

旧卡牌字段 `energy_cost` 是可空的当前全修正费用覆写：若与该卡标准费用相同则为 `null`，不可解释为零费用或未修正费用。v2–v4 的 `display.energy_cost` 来自 UI 卡面。旧 v2/v3 的 `display.dynamic_values` 写入所有原生 `PreviewValue`；`Damage` / `Block` 虽经战斗修正，也可能没有渲染在卡面。assembler 必须掩码这些旧值，不能作为 no-SL 可见特征。v4 live 采集将该数组置空，保留已渲染说明；空数组不代表效果数值为零。live collector v5 普通 Hand 的 `display` 使用原生当前费用、`description=null`、`dynamic_values=[]`；后两者表示该路径不采集文字和动态预览，不能解释为卡牌没有效果。

旧版普通手牌描述、当前选择器卡面描述及敌意图文字是本地化 UI 内容，不是稳定 ID；词表、跨语言归一化和特征使用必须单独处理，不能以文字替代卡牌 `model_id` 或意图 `kind`。此前 `36df5d1b...` 实机文件有 610 条 v2 战斗观察，普通 `Play` 所选卡在 461 次点击时缺少 `display`。旧版修复后 `59261c...` 实机文件的 482 次实际出牌、`fcbb...` 的 404 次以及最新 `dd28...` 的 161 次已提交出牌，所选卡均有 `display` 和说明。这些是旧 v2–v4 的历史展示证据；v5 普通 Hand 不再采集说明，也不以 UI 是否出现决定手牌或出牌标签。

未来 headless runner 仍写同一版本化 observation 与 JSONL 事件；战斗手牌、牌堆及合法动作在其对应的内部决策时点构造，和 live 手动入口的内部状态语义一致，不依赖 `NPlayerHand` 的 UI 动画。未来 headless runner 应按等价原生 `CardModel` 语义提供 v5 普通 Hand 的当前费用；当前泛协议投影与 headless writer 尚未强制，v5 手卡 `display` 可以为 null，此时应保留费用缺失 mask，不能把整张牌当作不可见。live v5 的 `description=null` 也不表示卡牌不可见。战斗多选应由 headless 的 `CardSelectCmd` 选择器构造同一 `active_choice` 与合法集合。选择器候选 `display`、敌人意图与遗物展示仍遵循各自原有的 UI 展示语义；没有等价展示证据时保持缺失并带 mask，不能把模拟器内部 `NextMove` 或预览变量直接当成已显示字段。

#### combat observation v3 与遗物可见状态

v3 在 v2 基础上给 `players[].relics[]` 增加可选 `display`：`icon_status`、`is_melted`、`is_wax`、`visible_counter` 和原生主悬停 `hover_description`。计数值仅在原生遗物栏规则应显示数字时读取；`null` 表示没有显示，`0` 表示显示了零。`display=null` 表示无展示投影，旧 v1/v2 均应映射为缺失，而不能当作“该遗物没有状态”。投影尚未逐帧核对 UI 节点是否完成刷新；原生额外提示中的动态状态说明和卡牌预览也尚未结构化，不能声称 v3 捕获了所有可见遗物信息。

局外 observation 同步升为 v2；`context.run_context` 独立升为 v2，遗物只保留 `model_id` 和同一可见展示投影。旧局外 v1、run_context v1 仍可读，但其中原生 `stack_count`、`used_up`、`status`、`display_amount` 未经 UI 可见性核验，assembler 不得将它们直接送入 no-SL 模型。Headless recorder 接受同一协议的展示字段，但未来 runner 必须提供对应的公开展示语义或保留缺失值，不能读取私有遗物计数。

#### 附魔展示与 observation v4

战斗和局外 observation v4 在已知附魔牌上增加 `enchantment_display`：原生卡牌悬停提示使用的本地化 `title` / `description`，卡面标签实际会显示的 `visible_amount`，以及 `normal` / `dimmed` 图标外观。原生 v0.111.0 `NCard.UpdateEnchantmentVisuals` 只在 `ShowAmount=true` 时显示 `DisplayAmount`；`CardModel.HoverTips` 则包含附魔的标题与动态说明。此投影按同一渲染语义读取，失败时整项为 null，不从内部字段猜测。战斗 v4 的旧 `enchantment_amount` 必须为 null；旧 v2/v3 中该字段是未经 UI 可见性检查的原生数值，不能直接进入 no-SL 特征。局外 observation v4 对牌组记录同一结构，`context.run_context` 独立升为 v3；非手牌没有当前手牌 `display`，但已知牌组/牌堆的附魔展示可供玩家查看。新路径仍待实机逐帧核验。

战斗 `active_choice.cards[].display` 是可选展示证据：live 采集只在玩家点击或确认时，按选择器中可见卡节点与原生 `CardModel` 对象身份匹配后记录说明和费用。`null` 表示没有取得唯一可见卡面，tensorizer 须保留缺失 mask；旧 observation 不得从卡牌 ID 或原生变量补造该字段。选择器展示同样不使用未核对的 `DynamicVars.PreviewValue`。

#### combat observation v5 与普通手牌费用

v5 的这次 live collector 改动只涉及普通战斗 Hand 的展示投影与点击时边界。每张已经进入原生内部 Hand 的牌均出现在 Hand 集合中，且 live collector 为每张卡生成非 null 的 `display` 对象；`energy_cost`、`star_cost` 和表示 X 消耗的 `costs_x` 从同一时点的原生 `CardModel` 计算当前值，某一费用计算异常时该子字段可为 null，不产生 UI 可见性 gap。`description=null` 和 `dynamic_values=[]` 是明确不采集普通手牌文字与动态预览，不能推断卡牌无效果，也不能解释为 UI 未显示。普通 Hand 的 `display` 不再扫描 `NPlayerHand` 或任一 holder；若其他观察字段相同，单纯的抽牌/出牌动画位置变化不会改变 observation 指纹。战斗选择器的 `active_choice.cards[].display` 仍按上述 UI 候选语义；敌人意图、伙伴与遗物的展示门槛没有改变。泛协议 `DecisionObservationProjector.ToCombat` 与当前 headless writer 仍允许 v5 Hand `display=null`；此时费用未知但 Hand 成员仍已知，未来 runner 应补齐等价费用。局外 observation v5 是独立版本，整局 `run_context` 仍为 v3。

assembler 必须按**内部 observation 版本**区分 v1/v2/v3/v4/v5；旧 JSONL 原样保留。v1 中缺失的金币、槽位容量、卡牌展示、伙伴和意图等新字段都必须设置缺失 mask，不能零填充或解释为真实的零值/空集合。v2/v3 的未经核对动态值须掩码；v2–v4 的普通手牌 `display=null` 表示当时 UI 展示未取得，不能转为 v5 的费用投影，也不能用于筛掉真实 Hand 卡。live collector v5 普通手牌 `description=null` 是按设计未采集文本，费用子字段 null 表示计算未取得，二者均不是隐藏卡或零费用。其他 v5 生产路径若整项 `display=null`，必须保留费用缺失 mask，也不能据此删除该 Hand 卡。敌人 `not_visible` / `unverified` 仍不能变成已知文字或攻击数值；v4/v5 的 `enchantment_display.visible_amount=null` 表示未显示数值，不能零填充；旧版 raw `enchantment_amount` 必须掩码。不得从执行后状态、未来抽牌或隐藏敌方动作回填旧 observation。

### 4.3 `action_submitted`

在人类操作或 policy 输出真正提交给游戏语义接口时追加新事件：

```json
{
  "event_type": "action_submitted",
  "decision_id": "uuid",
  "global_step": 42,
  "attempt_id": "uuid",
  "selected_action_index": 3,
  "selected_action_key": "stable-action-key",
  "policy": {
    "actor": "human",
    "policy_id": "human-demonstration",
    "model_revision": null,
    "logits": null,
    "mcts_visit_counts": null
  }
}
```

2026-10-15 新采集追加可选 `policy.teacher_information`：`native-mcts` 为
`native_checkpoint_privileged`，`first-legal` 为 `public_observation`；人工或未知来源
可为 null。该字段与 `policy_id` 由实际提交入口的来源桥记录，不由整局配置猜测。
它描述老师的决策信息，与 `decision.information_regime` 的学生观察边界、
`save_load` 的轨迹连续性分别审计。它不携带 checkpoint 内容，也不进入模型特征。
组装默认仍限人工；显式 `--allow-policy native-mcts` 才允许相应老师，报告保留来源统计。
旧 `observed-automation` 与缺少教师信息的日志不可自动补标签，MCTS visits 仍缺失。

- `selected_action_index` 永远以对应 `decision.legal_actions` 为基准。
- 多卡选择时，index/key 指向唯一的合法选择模板，另在同一提交事件写
  `selected_action` 具体描述符；其中局内用 `selected_combat_card_ids`，局外用
  `selected_cards`。普通动作不得带 `selected_action`。旧枚举组合的 JSONL 仍按
  旧动作列表回放，assembler 按是否为模板区分两种表示。
- outside 同时保存现有 `ActionId`；combat 保存 canonical descriptor digest。ID、digest 和
  ordinal 是冗余关联与校验字段，tensorizer 默认不把它们当特征。
- 一条 decision 可以没有 attempt，也可以在失败或 stale 后有多个 attempt；assembler
  不能假定“一条 decision 恰好一个动作”。无法映射到 legal actions 的人工战斗输入
  保留为原始输入事件及 `coverage_gap`，不能猜测最相近动作。
- MCTS 数据在此保存根节点所有合法动作的 visit counts，而不仅是最终动作；长度必须
  与对应 legal actions 完全相同。
- 将观察和提交拆开可保证 append-only：collector 无需为了等待人类点击而缓存或回写
  已经落盘的 decision。

### 4.4 `execution_result`

记录动作有没有真正生效，至少包含：

- `decision_id / global_step / attempt_id / expected_state_fingerprint`；
- action index 与冗余 ID/digest；
- `status = observed_transition | applied | cancelled | rejected | failed | timed_out | stale`；
- 可选的 `next_state_fingerprint` 与说明。terminal outcome 独立写在 `episode_finished`；
  无法归入稳定协议的原生细节写 `diagnostic`。

只有 `observed_transition` 或 `applied` 可以成为行为克隆标签。失败、取消、超时和 stale 响应必须保留用于 debug，但不能静默标成训练动作。现有 `OutsideCombatExecutionResult` 已具有大部分语义；combat 需要补同等级结果协议。
新采集器在下一条原生手动动作真正开始执行前结算上一条动作，因此快速点击本身不污染上一动作的奖励边界。旧 JSONL 若已有 `transition_contaminated_by_queued_manual_input`，assembler 仍须排除相应 transition/reward 目标；不能因为新版实现补写或重新解释旧数据。

### 4.5 `reward`

Reward 与观察分开存，允许以后在不重新跑游戏的情况下重算训练目标：

```json
{
  "event_type": "reward",
  "global_step": 42,
  "reward_version": "whole-run-v2",
  "components": {
    "terminal": 0.0,
    "hp_delta": -7.0,
    "gold_delta": 0.0,
    "floor_delta": 1.0,
    "deck_size_delta": 0.0
  }
}
```

训练时使用哪个组合由 `reward_version` 决定。禁止只写一个无法追溯来源的最终浮点数。首次实机采集的 `whole-run-v1` 在一些地图与战斗动作后过早结算，不能与 `whole-run-v2` 混用；原始文件保持不可变，由 assembler 按版本拒绝或从可信后继 observation 重算。

### 4.6 `save_load`

save/load 只记录可观测事实，不把“加载过”直接解释成作弊或 SL。当前 payload 记录：

- `kind = resume | rewind | unknown` 与明确原因；
- `from_timeline_generation / to_timeline_generation`；
- 恢复前后 fingerprint 与可选 checkpoint digest；
- 被边界打断的全部 pending decision/global step/phase，以及是否产生 data gap。

正常退出后从同一进度继续可以仍是 no-SL；只有确认发生状态回退、分叉复用或暴露了
额外隐藏信息时才使用 `rewind`。`save_load`、digest 和 continuity 都属于审计 metadata，
不进入模型特征。

### 4.7 `coverage_gap`

记录采集器已经观察到、但 v1 尚不能无歧义结构化的语义操作。它与普通 `diagnostic`
不同：`coverage_gap_count > 0` 必须令整局 `value_target_valid=false`。若缺口正好发生在一个
未完成 decision 上，payload 会显式引用并作废该 decision；多个战斗 decision 同时 pending 时，`target_decision_id` 只使指定子选择失效，其余已排队动作仍可继续结算。旧事件未指定目标时维持原有的全部 pending 失效语义。异步父动作稍后失败等与当前
decision 无关的缺口则写为 detached gap，不得误伤新的子决策。assembler 可以继续使用
缺口前后具有完整 submission/result 配对的行为克隆样本，但不能把该 episode 当完整轨迹。
若已结算的异步父动作后来报告失败，detached gap 的 `related_decision_id` / `related_attempt_id` 会指向原动作；assembler 必须排除该动作的行为克隆标签。
同样地，缺少原生人工入口证据、原生选择回执缺失或与 selector Task 不一致时，不得从相邻队列事件推断人类动作。快速连续输入只有在**点击时内部观察和合法集**均能冻结、且匹配同一原生 `GameAction` 时才成为独立结构化 step；否则留原始输入和 gap。`Start` 抽牌动画期间内部 Hand 可以领先 UI：按本契约，该牌若已进入点击时内部 Hand，就属于本步观察和牌堆集合变化，无须增设动画可见性或牌堆缺失 mask。旧 UI/Hand 校验拒绝的 JSONL 保留缺口，不补造点击时状态。多选不再有组合枚举预算，但缺候选 ID、点击/确认/Task/原生回执证据仍是 gap。

`phase=Start` 与普通 `Play` 的手动战斗入口，均冻结内部 Hand、抽牌堆、弃牌堆和当时合法动作。`Start` 合法集仅由内部 `CanPlay`/目标规则的卡与可用药水构成，不列 EndTurn；原生 v0.111.0 的正常 `Start` 阶段结束回合按钮尚未启用，异常 `Start` EndTurn 按不在合法集记 gap。`Play` 仍按其原生结束回合规则；已排队的同一原生卡 ID 不再重复成为合法动作。所点动作必须与本次真正提交的同一 `GameAction` 精确匹配。UI holder 未更新不再单独使决策失效；live collector v5 普通 Hand 的 `display` 由内部卡对象计算费用，不作为手牌实体与动作真实性依据。原始点击/执行审计观察也按各自事件发生时的内部状态记录，不用执行时状态倒填点击时状态。headless writer 接收同一协议事件，未来 runner 须在其真实内部决策边界提供完整合法集。此改动仅针对手牌和手动战斗动作，敌人意图、遗物展示及选择器候选可见性规则不变；新代码尚未实机验证。

### 4.8 `manual_combat_input` / `manual_combat_input_outcome`

这两种审计事件记录手动战斗入口实际提交的同一个原生 `GameAction`，包括前一动作仍在执行时排队的快速输入。`manual_combat_input` 记录 `intent_id`、`native_action_id`、动作类型和点击时内部观察；`data.click_observation_status` 区分 `structured_legal_set`、`queued_legal_set`、历史名称 `visible_only_unstable`、`unavailable`，前两种有点击时冻结的 `click_legal_actions`。`manual_combat_input_outcome` 用同一对 ID 记录该原生动作的执行、失败或取消，并可保存执行开始/结束时各自的内部观察。它们的 `global_step=null`，`event_sequence` 仍逐行递增；原生 ID、输入时间和执行前态只供核对与审计，不得当作策略特征。

如果输入也拥有 `decision` / `action_submitted`，原始输入事件用 `related_decision_id` / `related_attempt_id` 指向它**自己的**结构化 step。`overlaps_decision_id` / `overlaps_attempt_id` 可用于审计点击时仍在执行的父动作，但重叠本身不是缺口。点击时合法集合无法证实、动作不在合法集合或原生结果不明时才按实际情况记 detached `coverage_gap`。执行时观察即使后来能够取得，也不能替代点击时的合法动作集合。

这类原始事件允许复查“谁提交了什么、何时入队、最终是否执行”。assembler 应按 `intent_id`、`native_action_id`、`related_decision_id` 与 attempt ID 校验配对；新轨迹的结构化快速输入按正常成功结果评估 BC 资格。缺口继续使整局 `value_target_valid=false`。核心状态统计 `manual_combat_input_count`、`unresolved_manual_combat_input_count`、`unstructured_manual_combat_input_count` 和 `unstructured_unsafe_manual_combat_input_count`：后两者分别表示审计总数和其中已执行/不确定的数量。只有未配对或 unsafe 数非零时，原始输入本身会阻止整局完整；干净取消/拒绝的非结构化输入仍不能进入 BC。

### 4.9 `episode_finished`

记录胜负、最终位置与牌组摘要、终止原因、`completeness`、save/load/unknown-load/rewind/
data-gap/uncertain-execution/coverage-gap 和手动战斗输入计数、未决 decision，以及派生的
`value_target_valid`。终局 return 由此处的 outcome 计算，不要求回写已经 append 的最后一条
step reward。
正常结束且完整性合格的 episode 才生成可靠整局 return；崩溃、无法连续恢复、人工中止
或确认 rewind 的 episode 默认 `value_target_valid=false`，但其中具有成功 execution result
的动作仍可用于 policy imitation。导致 run 结束的最后一个 pending action 必须先写成功
terminal execution result，再写 `episode_finished`，不能因为 run 已 inactive 而记为 cancelled。

## 5. no-SL 信息边界

允许模型看到玩家在正常 no-SL 游玩时可知的完整集合，但不允许利用存档或模拟器额外泄露的信息：

- `information_regime=no_sl` 的原始 JSON observation 就必须去除隐藏顺序；不能先把抽牌堆
  原生顺序写进 source-of-truth，再仅依赖 tensorizer 忽略。抽牌堆、弃牌堆等以 multiset
  语义保存并规范化，只有确实对玩家可见且有语义的顺序才可保留；
- 不输入未来随机数、地图未揭示结果、隐藏敌方 roll；
- seed、Steam 身份、时间戳、checkpoint、replay prefix 只允许作为审计/复现 metadata；
- 同名卡仍通过当前状态内实体引用区分，但本地递增 ID 本身不当作可学习数值；
- `observation_fingerprint` 与可能包含隐藏原生状态的 `execution_guard_fingerprint` 必须分离；
- `information_regime` 描述单步可见信息，`save_load` 描述轨迹连续性。训练 no-SL 数据
  必须同时满足 `information_regime=no_sl`、`rewind_count=0` 且 episode 完整性合格；
- 训练、live play 和 headless 必须经过同一个 tensorizer 与 feature manifest。

## 6. partial JSONL 恢复原则

- reader 只接受以换行结束、能够完整解析且 schema 校验通过的事件。崩溃造成的最后一条
  torn line 单独隔离；此前已经 flush 的完整行不得删除或静默改写。
- 恢复时校验 `event_sequence` 从零连续、event ID 唯一、`global_step` 分配连续，并重建
  decision → attempts → results 的关联。重复、缺口或冲突进入 rejected 报告。
- 若能从最后一条完整事件和持久化 cursor 无歧义恢复同一 run，则先追加
  `save_load(kind=resume)`，从下一个 event sequence 继续；不得重用已发布序号。
- 若不能证明连续性，保留旧文件为 truncated episode，并用新 episode ID 开始采集；不得
  把两个片段靠相同 seed 或相似 fingerprint 猜测拼接。
- 缺少 `episode_finished` 的 partial episode 不产生 RTG/value target；其中
  `action_submitted` 与成功 `execution_result` 完整配对的步骤仍可用于 policy imitation。
  未决 attempt 不得在恢复时臆造为成功。

## 7. 从事件到训练样本

离线 assembler 按 `episode_id + global_step + decision_id` 关联：

1. 读取 `decision`；
2. 找到引用它的 `action_submitted`，并验证 ordinal、ID/digest 与 legal actions 一致；
3. 按 attempt ID 找到唯一成功 `execution_result`；
4. 保留 chosen action 或 MCTS visits 作为 policy target；
5. 以每条 decision 的真实观察状态为决策时刻，按选定的版本化 reward 规则计算 RTG；reward 的 `global_step` 只标识归属动作，不充当因果时间；
6. 按 episode 生成整局 `Trajectory`；
7. 使用固定 `tensorizer_version + vocabulary_hash + reward_version` 写 tensor shard。

**当前模式：**默认 `bc-only` 继续从可靠的 no-SL 人工动作构造标签，`TrajectoryStep.return_to_go=0` 只是条件输入占位。显式选择 `whole-run-hp-safe-v1` 时，只有完整、无回档、`no_sl`、`whole-run-v2`、`value_target_valid=true` 且全局与逐步语义审计通过的整局，才能得到真实 RTG。两种模式都把 `value_target` 设为缺失、value loss 掩码关闭；训练使用 `--value-weight 0`。`whole-run-v2` 的金币、楼层、牌组等分量目前不进入此标量回报；不能把这个特定版本误称为所有采集分量的通用价值函数。源码 JSONL 不修改。

**新增拒收边界（2026-10-01）：**完整事件链和原采集器的 `value_target_valid=true` 仍可能漏记局外用药/弃药。旧胜局 `433d...` step 270 在选牌时 `potion_count_delta=-1`，却没有相应药水动作；新局 `ec731...` step 79/608 的药水减少分别被领奖励/继续动作吸收。这些不是选择动作本身消耗药水的可靠证据，缺失的人工动作也不能从净变化倒填。由 `433d...` 与 `32a...` 生成的 `artifacts/tensor-v2/ironclad-hp-rtg-20261001-v1`，以及 Small 20 步 checkpoint `artifacts/train-runs/ironclad-small-hp-rtg-20261001-v1` 已作废，不得用于正式训练、续训或评估。raw auditor 会将旧文件受影响的 BC 步标为 `unexplained_outside_potion_decrease` 并排除，RTG assembler 拒收整局。`32a...` 未见此类减量，但单独只有一局败局，不构成可用的胜败训练集。

新采集器在 v0.111.0 的 Rewards 为顶层、药水栏与全部持有药水槽可核对、没有正在执行的局外父动作/selector、前一奖励已在稳定边界结算时，可将手动局外 UsePotion/DiscardPotion 记为独立 Rewards 决策。合法集同时包含 ClaimReward、Proceed 和所有合规 Use/Discard，药水动作写原生真实槽号与模型 ID，执行结果绑定同一个 `GameAction`；普通 Rewards 点击也冻结带药水候选的合法集。无法证实界面或快速并发操作时仍写 `coverage_gap`，不生成该动作的 BC 标签，整局 RTG 无效。其他局外动作若出现无法解释的药水净减少，也写关联 gap。core 已有局外排队日志 API，但 Runtime 不用它猜测不稳定决策边界。有限路径已通过离线构建/测试，尚未实机验证；旧 JSONL、shard 和 checkpoint 均不回填。

旧 JSONL 的离线检查只能发现未解释的**药水净减少**。同一结算区间内先消耗再获得药水可能相互抵消，不能仅凭未触发这条规则证明旧局没有漏采；新采集器仍要依靠原生入队入口写缺口，并用新实机轨迹验收。

### 7.1 `whole-run-hp-safe-v1` 标量回报

令 `H₀` 为本局开局最大生命上限，之后即使最大生命变化也保持不变；令 `q(H)=clip(H/(0.5H₀),0,1)`。每次实际生命变化的标量奖励是 `r_hp=0.2×[q(H_after)−q(H_before)]`；终局胜利加 `1`，败北加 `0`，折扣 `γ=1`。对一次决策，记它实际观察到的当前生命为 `H_t`，由完整整局重建的终局生命为 `H_final`，则其剩余回报精确为 `RTG_t=1{win}+0.2×[q(H_final)−q(H_t)]`。生命高于 `0.5H₀` 后再增加不会为 HP 项加分；前两幕离幕时没有单独的高血量奖金，最后是否休息仍须与其他动作对胜率的影响比较。这是手工定义的训练条件，不会由模型自行修改。

此公式对已经在状态中反映的 HP 变化给出正确截点：快速排队时，上一动作的 `reward` 事件可能晚于下一条 `decision` 写入，但下一条观察的 HP 已改变。若机械地把这个较晚的 reward 行算作下一决策的未来奖励，会重复计入已经可见的生命变化。HP 势差可望远镜求和，所以本模式直接使用每步 `context.run_context` 与 observation 互相核对后的当前 HP，以及从完整 `hp_delta` 链重建的终局 HP；不能按 reward 行的 `event_sequence` 或归属动作的 `global_step` 做简单后缀和。其他将来新增的非状态势差奖励必须单独定义因果截点。单步 RTG 可因低血量后续回血而超过 `1`；上线时也不能把常数 `1` 当成天然最优目标。

历史首轮曾选用两局通过当时完整性与已知语义检查的铁甲战士数据：胜局 `433d5532920444a1afac0716251e12c4` 有 985 个决策、983 个成功动作标签和 2 个取消动作；败局 `32a3822509ec4c9fa8d00017103daee6` 有 228 个决策和 228 个成功动作标签。胜局开局最大生命 `80`，由原始奖励 HP 增量重建终局生命 `28`，安全线 `40`，首个决策 RTG 为 `0.94`；败局终局 HP 0、RTG 范围 `−0.20–−0.05`。旧 JSONL 没有独立终局 HP 字段可交叉核验。历史组装产物记录 1211 个动作标签和 22 个最长 64 步的轨迹窗口，并曾运行 Small CPU/FP32 20 步；后续局外药水缺口审计已使该产物及 checkpoint 作废。这些统计只保留为链路执行记录，不能用于训练质量判断。

BC 样本可来自整局 value 无效但本步完整配对的 no-SL 人工动作；反过来，即使 `episode_finished.value_target_valid=true`，也不能跳过单步语义审计。旧版压缩过的药水槽位、排队输入仍留在合法集中的同一张牌，以及后到的 detached gap，都必须在派生训练数据中核验并修正或过滤。首版应记录每个被拒绝的文件和步骤的原因，不修改原始 JSONL。训练/验证按 episode ID 隔离，同一跑局的相邻步骤不得横跨两个划分。

独立 holdout 必须加载已训练组装结果的 `feature-spec.json`，不得在新跑局上重拟合词表；评估时还要提供原训练 assembly root，核对两边 episode ID 与源 JSONL SHA-256 互斥。持有局中的采集缺口会按原始事件边界切开 BC 轨迹，即使其他步骤可用，也不能把整局解释成有效 value 或多卡选择监督。

当前首版自动语义检查除验证合法用药槽、出牌卡与 Hand、已排队同卡的合法集外，还逐步比较 observation 与 `context.run_context` 的完整玩家药水 `(slot_index, model_id)` 集合。因此，旧压缩槽号即使碰巧在观察中存在、却对应另一瓶药，也会被排除；参照缺失而无法核实时，不应猜测修复。使用历史 v1–v4 episode 前仍要查看逐局排除报告；自动过滤只覆盖已知问题，不能证明所有旧观察语义安全。首轮训练使用明确列出的 episode allowlist，并在 assembly report 保留每局纳入/排除数。

任何 event sequence/global step 缺口、重复 step、action 对不上 legal list、attempt/result
歧义、fingerprint 不一致或非有限 reward 都应隔离到 rejected 数据集并给出原因，不能
“尽量猜一个值”。

对快速手动战斗输入，assembler 另需检查 `manual_combat_input` 与 `manual_combat_input_outcome` 的原生动作身份配对。缺乏点击时合法动作集合的输入不能补成 BC step；有完整点击时合法集合、原生动作精确匹配且执行成功的排队输入可成为普通 BC step。多个 pending decision 必须按 decision/attempt ID 配对，不能假定每条 reward 紧跟上一条 decision，也不能假定执行顺序与点击顺序相同：父卡牌打开子选择时，已排队的下一次点击可能先获得 global step，子选择却先于它执行。旧文件的受污染标记仍按旧语义排除。

对未来**不能写为状态势差**的奖励，RTG 的因果截点仍需按实际发生顺序定义。例如点击顺序为 A、B、C（`global_step=0,1,2`），原生结算顺序为 A、C、B：B 点击之后才发生的结果属于 B 当时尚未发生的未来；若 A 在 C 点击前已经结算，C 不应再次取得 A 的奖励。把 reward 按其归属 `global_step` 排序后做后缀和会误算这些目标。本次 HP 势差模式使用上节的决策状态闭式公式，避免落盘顺序与可见 HP 状态不一致的问题；headless writer 与后续其他 reward 模式的 golden fixture 仍须覆盖交错顺序。

第二份实机 `whole-run-v2` 文件 `05e34e83ee474869a986c78325db9813.jsonl` 有 18 个 `coverage_gap` 和 11 个没有执行结果的已提交动作，虽然终局为胜利，仍标记 `completeness=incomplete`、`value_target_valid=false`。assembler 不能用这局生成完整 RTG/value target，也不能补写原始 JSONL；只可按完整配对及后续关联缺口筛选局部行为克隆样本。

随后采得的 `c5ff3eb971c54f1ebf22fbb15ac71a63.jsonl` 有 2614 条事件和 60 个 `coverage_gap`，其中 43 个为 `manual_combat_action_during_pending`。这份文件早于快速输入原始事件修复；它保留了缺口，但不能事后补造被漏记的原生输入身份或执行结果。

先前 `59261c11694548228f801a8e6ea7970d` 文件有 4842 行，事件 SHA-256 链和 857 组 decision/action/result/reward、585 组手动输入/结果均完整配对。482 次实际出牌的所选卡有 `display` 与说明，8 次 `Start` 输入（含 2 次用药）已结构化，3 次单卡原生 `Index` 回执均关联成功；v3 战斗遗物和局外遗物实例分别有 6663/6663、2549/2549 个展示字段。3 个局外选择缺口分别来自开局卡包、事件选 2 张牌和事件移除 3 张牌；终局为胜利，但 `completeness=incomplete`、`value_target_valid=false`。因此仍不能用这局生成可靠的整局 RTG/value target；原始文件不能回填候选或动作标签。

先前 `fcbb45909a9044f6b696695c35439b54` 文件有 4200 行，事件链和 global step 0..749 连续；750 个 decision 中 749 个有 action submission/result、747 个成功结果有 reward，另 2 个结果为正常 `cancelled`。491 次手动输入全有原生结果，但 1 次未结构化且有执行风险。5 个 gap 中，1 个为 `Start` 快速输入可见性无法证明，1 个为局外二张选牌的单个 `Index` 回执误报（global step 80 没有提交动作），3 个为 Crystal Sphere 事件小游戏未支持交互。终局胜利但 `value_target_valid=false`，不能生成完整 RTG/value target；有缺口或缺少提交的步骤不能当作 BC 标签。519 个局内 observation v3、231 个局外 observation v2、750 个 run context v2；404 个已提交出牌的所选卡都有 `display` 和说明，战斗及局外遗物展示字段分别覆盖 5048/5048、2179/2179 个实例。逐步模式均为 `no_sl`，身份、种子和开局时间未进入 observation/context。原始文件不回写，修复后的局外 `Index`/`Indexes` 多卡路径与删牌集合仍须实机验证；card bundle 已在后一局成功记录。

先前 `dd28da34ecaf4dcda4c0abbcf5ae3bf9` 文件有 1590 行，global step 0..278 的 279 组 decision/action submission/execution result/reward 全部配对，199 组原始手动输入/结果全部配对。203 个战斗 observation 为 v3、76 个局外 observation 为 v2；161 次已提交出牌的所选卡均有 `display` 和说明，未见新的 observation 契约问题。两次 `Start` 快速出牌和一次 `ChooseCardBundle` 完整结构化；card bundle 有原生 `Index` 回执与牌组增加 3 张的结果。唯一 gap 是 Gambler's Brew 的战斗内多选：5 个候选中选了 4 张，虽有原生 `CombatCard` 回执，但采集时的旧代码没有对应的结构化子决策和合法动作集合。父药水步骤 global step 268 有 result/reward，不能因此将包含缺失子选择的完整状态转移用于可靠监督；整局 defeat、`completeness=incomplete`、`value_target_valid=false`，不能生成完整 RTG/value target。本局未触发局外二张选牌、删牌集合或 Crystal Sphere，故不能验证其修复或认为其已解决；原始文件不回写。

新增战斗多卡路径目前只通过 collector smoke、DataCollector Release 构建、主工程测试、直接运行的 HeadlessCollector smoke、临时 Harmony ABI 检查与 `git diff --check`；`dd28...` 使用旧代码，仍保留缺口。新路径已随 `4b3d...` 跑局安装，但未触发多选，因此不能把它计为已经获得可用的 Gambler's Brew 训练标签。未来 headless runner 应以自身 `CardSelectCmd` 的候选、约束和结果建立同一 `active_choice`/`ResolveChoice`，与 live 共用协议和 writer，但不依赖 `NPlayerHand` UI。

### 药水槽位语义审计与旧轨迹派生修正

`4b3d120ce918402c936238fef818ab46` 虽有 2822 行、501 组完整的 decision/action/result/reward、0 个 coverage gap，终局为 defeat 且 collector 标记 `value_target_valid=true`，但战斗观察存在独立于事件链的语义错误。359 个战斗决策中 116 个把非连续药水槽重新编号为 0..N-1；106 个决策的合法药水动作不能按观察正确寻址，4 个实际用药标签（global step 207、412、495、499）选中的槽在观察中缺失。该局 24 次战斗内选牌全是单选，未验证新的 Gambler's Brew 多卡路径。`next_state_fingerprint=null` 的 156 个结果分别是 142 个局外步骤和 14 个战斗结束跨域步骤，属于可选指纹边界，不是本次问题。

只读 `python3 scripts/audit-collector-potions.py` 对当前 17 份正式 JSONL 的复核发现：7 份中的 748 个战斗决策，其 observation 与同一步 `context.run_context.players[].potions` 的 `(slot_index, model_id)` 不一致；706 个决策的合法用药动作受影响，16 次实选用药动作受影响，0 个无法核对。错位决策的 run context 保有正确的真实槽号；真实槽位非连续却被正确记录的较新决策不能算作错位。原始 JSONL 和哈希链不可修改。当前 `collector-raw-bc-v3` assembler 已按 `player_id` 对照完整药水集合并过滤不一致步骤，尚不自动修正派生观察；未来如要恢复这些旧步骤，必须在模型 ID 数量及顺序一致、真实槽位唯一且动作引用可核实的前提下实施版本化修正规则。新采集文件应要求两处槽位逐项相同，任何错位都不能因 `value_target_valid=true` 而跳过。这一标记只证明连续性和回报链，不证明每个观察字段可直接作为特征。

工作树给战斗快照增加可选真实槽位信息；无空槽的旧快照 JSON/指纹保持不变，稀疏槽位从 `Player.PotionSlots` 读取并与原生药水模型序列核对。局内和 run 观察共用该映射，live 采集再次对照真实槽位，新决策写入入口拒绝 `UsePotion` 指向不存在的观察槽，历史回放保留兼容并交给只读审计识别。Protocol smoke 和两个 Mod Release 构建已通过，后续实机 `8adb...` 与 `ea59...` 的药水槽位审计也无错位。首版 BC-only assembler 已接入，对旧槽位错位的步骤按同一步完整药水集合比较后过滤，尚未自动修正原始或派生观察；使用旧局前仍须审阅排除报告。

### 最新实机轨迹的边界：木札与水晶球

`8adb3d74082043b4943d53f0199eb22a` 已发布 2915 行，事件序号与 SHA-256 链完整；530 个连续 decision 中 529 个有 action submission/execution result，525 个成功结果有 reward，4 个取消结果无需 reward，294 次手动输入与原生结果全部配对。终局为 win、无 save/load，但 6 个 coverage gap 令 `completeness=incomplete`、`value_target_valid=false`。其中一次涅奥之怒空集选择缺人工确认凭证，一次商店原生购买未匹配合法动作，三次 Crystal Sphere 格子点击尚未结构化，一次遗物木札的附魔选择未结构化。木札在 20 张候选中原生回执选择 3 张；其专用 `NDeckEnchantSelectScreen` 被旧局外多选入口的选择器类型检查拒绝，不能从回执逆推点击前合法集合。商店未匹配步骤前后观察、合法动作与指纹相同，但旧日志未记录所点目标，不能当作可信动作标签。旧 JSONL 保持不可变。

附魔网格的采集路径将选择表示为一个局外 `CardGridChoice` 决策。木札的 `Adroit` 20 张候选允许选 1–3 张；浸水抄写室的 `Steady` 12 张候选固定选 2 张。旧枚举版分别形成 1350/66 个动作；当前工作树为每个页面只写一个集合模板，并在 `action_submitted.selected_action` 中记录实选集合。通用原生附魔页仍核对界面标题、说明、图标、候选、点击、预览确认、Task 与 `DeckCard` 回执；显示不了或核对不一致仍写 gap。新模板尚无实机样本，旧 JSONL 不回填。

其后一局 `ea59b2a19b2d44d99f5e4620df632e33` 的 2382 行及 428 个决策步骤均有完整事件链；428 个提交/执行结果和 425 个成功动作奖励配对，3 个取消结果无奖励，274 次原始输入都结构化并有结果。终局 defeat、无 save/load、0 个 coverage gap，采集器标记 `value_target_valid=true`。药水槽位只读审计 0 错位，210 次所选出牌有 `display`；一个 queued 步骤的未选手牌缺 display，tensorizer 须保留 mask。该局没有触发附魔网格或 Crystal Sphere，因此只证明一般整局链路，不能作为新路径的实机验收。独立语义审计发现 global step 204 的旧合法集仍包含 `pending_manual_actions` 中已提交的 play card 11；这一步虽然选中了另一张可见卡 14，原始合法集仍不适合直接训练。assembler 应只在原生卡身份明确且所选动作可重映射时，从派生合法集中移除已提交卡；否则排除该步及受影响窗口。原始 JSONL 不回写，`value_target_valid=true` 仅证明连续性和回报链。

先前 `24b023e841e44bb5a2dde5239e999fa2` 实机文件有 3859 行、687 个连续且完整配对的决策/动作/结果，684 个成功结果有 reward，3 个取消无 reward。终局 win，但 4 个 gap 令 `value_target_valid=false`：两次 `Start` 快速连点无法核对模型 Hand 与 UI 可见手牌，实际执行的第二张牌缺结构化 step，父动作的 transition/reward 不适合直接训练；两次 `TO_ENCHANT` 因旧版白名单拒绝 `Sharp`/`Momentum`，没有子决策。54 个带 pending 的局内决策无重复排队卡，377 次所选出牌都有 display，4 次 `PURITY` 战斗多卡选择有原生回执。旧文件保持不可变；新通用附魔代码仍需真实 UI 和回执实测。

先前 `8adb...` 一局的 13 次涅奥之怒战斗多选形成完整 decision/action/result/reward，所选集合与原生 `CombatCard` 回执一致；另一次空集无人工证据，因此只记 gap。本局没有赌徒特酿，不能据此宣称药水手牌多选已实机验证。药水槽位修复首次获得实机证据：311 个战斗 decision 中 28 个出现非连续药水槽，观察、合法动作、同一步 run context 均一致；4 次实际用药的槽号也能由观察寻址。248 次实际出牌的所选卡均有 display、说明、费用和动态数值；其他可选手牌仍可能因选择器或快速输入可见性检查而缺 display，tensorizer 必须保留缺失掩码。完整整局 RTG/value target 仍不可用；局部 BC 需跳过 gap 与未成功结算的动作。

先前 `ba8f9848c0804175b3c6e64f2fc03747` 实机文件的 532 组 decision/submission/result 配对完整，但仍有 2 个 gap、`value_target_valid=false`。其中一处是旧 UI/Hand 同步门槛在第二次 `Start` 快速出牌时拒绝冻结前态；两张牌实际均执行。后续状态中的 `SLIMED` 不能反推缺失的点击时观察。按新契约可以在未来点击时记录内部 Hand 和牌堆，但旧文件没有这一步 observation，assembler 不得以执行时状态或后续事件回填。

## 8. live 与 headless 的共同验收

- 同一 decision fixture 经两条采集路径得到字节级等价的协议 observation/action；
- episode 的 event sequence 逐行连续；global step 只在新 decision 时递增，局内转局外时不归零；
- 所有已标注动作均有 action submission 和成功 execution result；
- 每个 soft policy 长度等于合法动作数且和为 1；
- tensorizer 对集合重排保持输出语义一致；
- no-SL 原始 observation 不含隐藏牌堆顺序、未来 RNG 或 guard-only 数据；
- 同一内部战斗状态在 live UI holder 动画位置不同的 fixture 中得到相同手牌集合、费用投影、合法动作及 observation 指纹；live collector v5 普通 Hand `display` 非 null，泛协议/headless v5 可为 null；费用子字段计算失败时也可为 null，且不影响出牌标签；
- save/load marker 只报告事实；确认 rewind 的 episode 不产生 value target；
- collector 崩溃不会破坏已 flush 的 JSONL；
- torn line 可隔离，未完成 episode 不会错误地产生终局 value 标签；
- manifest 能精确定位游戏 build、协议、tensorizer、词表和 reward 版本。

游戏无关的 `HeadlessEpisodeRecorder` 已通过 `CollectorStore → EpisodeSession → JsonlEpisodeJournal` 写入同一事件链；live 和 headless 共用 `WholeRunV2RewardCalculator` 及 `DatasetManifestWriter`。headless runner 仍需提供真实 observation、合法动作、状态转移和终局指标；共享记录接口已经准备好。assembler 已能生成 BC-only shard，并在完整整局上生成版本化 HP RTG shard；独立 value target、其他奖励分量的标量化及在线目标 RTG 调度仍待设计和验证。全局 headless runner 接入时应复用同一原始事件契约。
