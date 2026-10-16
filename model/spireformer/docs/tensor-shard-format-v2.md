# SpireFormer Tensor Shard Format v2

日期：2026-09-30

Tensor shard 是从可审计 raw JSONL 重建的训练缓存。`TensorShardWriter` 写入 `.pt` shard schema v2；`TensorShardDataset` 仍可读取 [v1 shard](tensor-shard-format-v1.md)。目录、原子发布、哈希校验和 manifest schema v1 不变。下文区分首版行为克隆转换与后续整局回报目标，避免把原始 reward 组件误当作已定义的训练标量。

## raw JSONL 转换的首版目标

首版转换只生成 no-SL **行为克隆（BC）**标签：先逐行校验事件序号、episode ID、timeline generation、前序 SHA-256 与当前事件 SHA-256，再按 decision、action submission、原生 execution result 和后到的关联 coverage gap 判断每一步。只有合法动作索引/key 与决策相符、实际执行状态为 `applied` 或 `observed_transition`，且没有指向该动作的失效证据，才可进入 BC。`cancelled`、`failed`、`stale`、未决输入、身份不明的动作以及语义校验失败的旧观察必须被排除并报告。文件名只供查找，不作为 episode 身份；旧 JSONL 原样保留。

当前自动语义检查会对照同一步 observation 与 `context.run_context` 中玩家药水的完整 `(slot_index, model_id)` 集合，因此也能拒绝历史压缩槽号虽存在、却指向另一瓶药的步骤；另外检查出牌卡是否在 Hand，以及已排队同卡是否仍列为合法动作。两处药水信息缺失或不一致时拒绝该步骤，源 JSONL 不修改。此检查只覆盖已知的观察语义问题，使用历史 episode 仍应查看排除报告；`episode_finished.value_target_valid=true` 不能代替逐步审计。

现有 `TrajectoryStep` 要求一个数值 `return_to_go`，但 `whole-run-v2` 的 `reward.components` 是可追溯的**分量**，尚无经过验证的标量权重、终局奖励和事件时序折算规则。因此 BC-only shard 暂用常数 `return_to_go=0` 作为模型输入占位，并令每步 `value_target=None` / `value_target_mask=false`。这个零不是“真实回报为零”，训练或评估不能从它推断价值函数已经学到跑局收益。后续启用 return/value 前，须确定版本化标量 reward 公式，并按真实 `event_sequence` 而非 `global_step` 排序计算因果 RTG。

训练与验证数据应按 **episode ID** 划分，不能把同一跑局的相邻步骤分别放进训练和验证。首版 loss/离线准确率只衡量对人工动作的模仿，不能据此宣称游戏策略具有泛化能力；真正的策略强度仍需未见过的整局评估。

当前转换器的 manifest 使用 `tensorizer_version=collector-raw-bc-v3`、`reward_version=bc-only-v1`；tensor shard 的磁盘 schema 仍为 v2。v3 比先前试验版 v2 多了同一步完整药水集合对照，因此旧 v2 试验缓存不能冒充新筛选规则的产物。`bc-only-v1` 明确表示 **没有**把 raw `whole-run-v2` 分量转换成标量 reward。特征编码版本仍为 `sts2-raw-features-v2`：在训练集决策中确定语义词表，超出词表的 ID 归入 `UNK`；数值特征保存经固定尺度变换的值及独立的存在位。可用特征包括局内/局外公开状态、玩家与敌人、手牌及牌堆集合、药水/遗物/充能球/能力、可见意图、路线、已揭示的 Crystal Sphere 格子及冻结的集合选择候选。Steam 身份、seed、时间戳、指纹、原生对象 ID、未经展示核对的旧动态值和本地化说明均不作模型输入。集合动作的已执行向量额外汇总实际选中张数、升级与可取得的费用，使下一个决策看到的上一动作区别于空模板。

`feature-spec.json` 的词表只从 train split 纳入的决策拟合，再用于 val/test，防止验证集信息进入训练词表；它也记录实际实体/动作特征宽度，可能不同于 preset 参数量表采用的 48/32 参考宽度。独立 holdout 模式用 `--feature-spec` 读取训练组装结果的词表，不在 holdout 上重新拟合；评估时用 `--training-assembly-root` 比较两个组装报告的 episode ID 和原始 SHA-256。`assembly-report.json` 保存源文件哈希、每局原始/纳入/排除步数、排除原因、集合标签数和分段数；普通组装生成 train/val/test 各自的 shard manifest，独立模式生成 holdout manifest。跨 `coverage_gap` 或 `save_load`、不可靠动作及固定长度窗口时切开轨迹，保留原始 `global_step` 作为 timestep。输出目录必须是新目录，转换完成后一次发布；源 JSONL 不回写。

## 一次多卡选择只占一个决策步

局外 `card_selection_options` 或局内 `active_choice.cards` 给出可见候选、局部 `option_index` 和 `min/max` 约束。`legal_actions` 包含一个集合动作模板，允许取消时另有取消动作。`action_submitted.selected_action` 给出实际选中卡牌的具体 descriptor。tensorizer 必须核对候选身份、option index、合法张数和执行结果，仅对可靠的已执行选择写集合标签。`selected_action_index` 仍指向模板动作的局部 ordinal。

`TrajectoryStep` 的集合字段：

| 字段 | 含义 |
| --- | --- |
| `set_candidate_features [C, Fe]` | 可见候选牌的语义特征；候选按局部 option index 对齐 |
| `set_min_select`, `set_max_select` | 可选择的张数范围，`0 <= min <= max <= C` |
| `set_selected_mask [C]` | 实际选中集合；取消或缺少可靠结果时为 `None` |
| `executed_action_features [Fa]` | 具体已执行动作的特征，供下一步因果历史使用；有集合标签时必填 |

`option_index` 只用于对齐标签，原生卡 ID 只用于审计身份；这些 ID、Steam 身份、seed、时间戳和未来随机状态不能直接编码成模型特征。候选若有同名牌，也必须作为两个实例槽位保存。

## v2 packed 字段

v2 包含 [v1 的全部字段](tensor-shard-format-v1.md)，另增：

| 字段 | dtype / shape | 含义 |
| --- | --- | --- |
| `set_candidate_offsets` | int64 `[S+1]` | 每步候选范围；无集合决策时相邻 offset 相等 |
| `set_candidate_features` | float `[sum(C), Fe]` | 所有可见候选牌特征 |
| `set_selected_mask` | bool `[sum(C)]` | 与候选对齐的实际选中标签；无标签时全 false |
| `set_min_select`, `set_max_select` | int64 `[S]` | 选择张数边界；非集合步存零 |
| `set_step_mask` | bool `[S]` | 当前步是否有集合选择界面 |
| `set_target_mask` | bool `[S]` | 当前步是否有可靠的集合行为标签 |
| `executed_action_features` | float `[S, Fa]` | 已执行具体动作；普通步可等于所选合法动作特征 |

读取端严格检查 dtype、offset、边界、标签张数和有限浮点值。`set_target_mask=false` 时对应 `set_selected_mask` 必须全 false。v1 shard 不含这些字段，读取时按普通动作轨迹处理；不能从旧 v1 的模板 ordinal 凭空恢复集合标签。

Collator 将候选 padding 到 `[B,T,C,Fe]`，只在集合步启用 `set_step_mask`；普通动作仍是 `[B,T,A,Fa]`。19 选 4 的典型张量为 `A=1`、`C=19`，不是 `A=3876`。同一整局时间步只出现一次，价值目标也只归属这次选择。

## 模型目标与成本

共享 Set Transformer 对候选牌进行上下文编码；同一因果主干输出用于模板动作、候选牌和张数。对目标张数 `k`，候选 logits 的无序集合似然以 log-space 动态规划计算第 `k` 个 elementary symmetric polynomial，复杂度 `O(C × k)`；张数使用合法范围内交叉熵。固定张数、可变张数及合法的零张选择均适用。模型不显式枚举任何卡牌组合。当前解码先选概率最高的张数，再取该张数下分数最高的牌；可变张数时这是两阶段贪心解码，未必是联合 MAP 集合。

候选自注意力可让每张牌的分数感知其他候选，但集合分布仍由逐牌分数和张数构成，不能精确表达“选中 A 后 B 才有价值”的任意依赖已选集合的搭配。若后续需要更强交互，可沿用同一原始候选与真实集合契约，将输出头换成条件化逐卡选择；不需要回到组合枚举。
