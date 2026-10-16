# Spire Codex 回放重建格式 v1

日期：2026-10-11

## 目标

`scripts/convert-spire-codex-replays.py` 将本地保留的 166 份 Spire Codex
回放转换为可审计的中间 JSONL。转换器不会把 Spire Codex 回放冒充成本项目
原生 collector journal：两者的决策边界和完整性证据不同。

当前版本完成三件事：

1. 重建每个动作前的公开跑局状态，以及可可靠还原的无序战斗状态；
2. 只把原日志同时记录了完整可选项和真实选择的局外步骤标为 BC 可用；
3. 用固定游戏版本的原生 worker 重放一小批完整战斗，在真正的输入边界重新投影
   observation、合法动作和所选动作。

战斗日志有出牌、目标、费用、抽弃牌与状态变化，但没有输入瞬间的完整合法动作
集合。转换器保留这些战斗步骤供后续原生重放，并明确令
`legal_actions_complete=false`、`bc_eligible=false`。不得用实际动作反推一个只含
正确答案的“合法集”。

## 运行

在仓库根目录执行：

```bash
python3 scripts/convert-spire-codex-replays.py
```

默认读取：

```text
artifacts/reference/spire-codex/bulk/v1.2.1/manifest.jsonl
```

默认一次性发布到：

```text
artifacts/reference/spire-codex/reconstructed-v1/
```

输出目录已存在时命令会拒绝覆盖。每局输出为
`episodes/<角色>/<run_hash>.jsonl.gz`；根 `manifest.jsonl` 保存源文件和输出文件的
SHA-256、步骤数量与排除原因；`by-character/<角色>/manifest.jsonl` 是角色索引；
`summary.json` 是全量汇总。`bc-eligible-index.jsonl` 只索引首版可训练的局外步骤；
`native-replay-index.jsonl` 只索引下一阶段可交给原生 runner 的战斗步骤。两个索引
在 `by-character/<角色>/` 下也有角色分表，索引引用原 episode 和 `step_index`，不
复制 observation。

## 输出记录

每局第一行为 `record_type=episode`，保存格式版本、来源文件哈希、角色、进阶和
录制段边界。中间行为 `record_type=step`：

- `observation`：动作前的公开状态；牌堆只输出无序列表；
- `action`：实际选择的结构化动作；
- `legal_actions`：只在原日志提供完整候选时填充；
- `set_candidates` / `selection_bounds`：卡牌集合选择的候选和数量约束；
- `bc_eligible` / `bc_exclusion_reasons`：首版行为克隆门禁；
- `native_replay_eligible`：战斗动作是否有足够证据进入下一阶段原生重放；
- `segment_index` / `source_sequence`：只用于审计和恢复因果顺序，不作模型特征。

末行为 `record_type=episode_end`，只保存终止原因、是否真正 game over、录制状态和
最终 HP。转换器不生成 RTG 或 value target。

## 信息边界

输出采用 allowlist，并在每条记录发布前递归检查。以下来源信息不会进入结果：

- run seed；
- `rng_state`；
- `draw_order`、shuffle 顺序和任何未来抽牌次序；
- UTC/墙钟/毫秒时间；
- Steam 或平台身份；
- 本地化 `label` / `desc`；
- 原生 card/creature instance ID。

转换器会在内部读取 opening/shuffle 顺序来恢复**当前抽牌堆成员集合**，但输出只
保留无序 multiset。该集合可由玩家已知牌组与已公开区域推导，符合项目 no-SL
边界；顺序本身不会写出。

重复打开同一局产生的多个 header/end 段被拆为独立 `segment_index`。首段之后的
238 个 `resume` 段虽然保留用于审计，但目前没有足够证据证明它们与前段之间的
牌组、地图和 RNG 连续性，因此统一标为 `resumed_segment_unverified`，不进入 BC
或原生重放索引。录制中断段的步骤也不会进入 BC。

## 2026-10-11 实际转换结果

166 局全部完成逐行解析、源 SHA-256、输出 SHA-256 和递归禁用字段检查：

| 指标 | 数量 |
|---|---:|
| episode | 166 |
| 录制段 | 404 |
| 总动作步骤 | 56,160 |
| 局外步骤 | 7,537 |
| 原日志候选与选择结构完整的局外步骤 | 7,341 |
| 排除恢复段后安全 BC 局外步骤 | 4,603 |
| 战斗步骤 | 48,623 |
| 排除恢复段后可进入原生顺序重放的战斗步骤 | 24,856 |

各角色安全 BC 局外步骤：IRONCLAD 915、SILENT 1,065、DEFECT 719、
NECROBINDER 1,284、REGENT 620。

这里的 BC 可用表示动作候选集合和真实选择完整。原日志不会在 header 直接记录
初始金币；严格语料全部是 `v0.111.0`、无 modifier 的标准单人新局，因此转换器按
原生规则把新局初始金币恢复为 99。134 个后来出现可逆金币锚点的新局都反推得到
99；恢复段则使用 `resume.gold`。全量 BC observation 的上述公开跑局字段已无缺失，
`summary.json` 的 `bc_observation_missing_fields` 为空。

局外排除的主要来源是未验证的恢复段、未完成选择、重新掷取标志与候选不一致，
以及商店购买缺少同段 shop offer。战斗步骤统一因缺少完整合法动作集合而暂不直接
进入 BC；另有部分生成牌/快速输入无法仅靠事件流恢复到手牌。这些排除都保留在
逐步和汇总报告中。

结束回合需要单独说明：Spire Codex 的 `end_turn` 行位于玩家点击之后，甚至晚于
充能球被动等回合结束效果，因此 raw 行附近的战斗状态不能当作人工点击时的
observation。转换器仍可把 5,274 个结束回合作为顺序重放动作，但令
`reconstructed_observation_valid=false`；原生 worker 在执行前自行投影真实决策
状态。另有 10 个缺少必要边界的结束回合继续排除。

## 原生战斗重放试点

`scripts/extract-spire-codex-combat-plan.py` 为单场战斗生成内部重放计划，
`spire-codex-combat-replay` worker 模式再用本项目固定的 `v0.111.0` 原生逻辑执行
已记录动作。计划为了恢复相同战斗会包含 seed、RNG counter 和 opening draw
order，因此明确标记 `replay_only_hidden_state=true`，只能留在忽略目录，不能进入
模型输入。报告只保存原生 policy observation、完整合法动作和实际动作，并记录
计划文件 SHA-256；tensor loader 会再次验证哈希、来源、动作数、原生胜利状态及
所选动作确实属于合法集。

目前选取五个角色各一场完整首战，逐动作重放均到达原生胜利：

| 角色 | 回放 | 原生决策数 |
|---|---|---:|
| DEFECT | `48605d6475cb9a0a` | 12 |
| IRONCLAD | `c56ce53a1d2877a7` | 11 |
| NECROBINDER | `3b8384565fffcd99` | 13 |
| REGENT | `127f08acbd253317` | 14 |
| SILENT | `104ccab8777cf3e5` | 20 |

另对铁甲样本 `a8d7ab6d08211e91` 做了连续双战验证：从正常新局开始，经涅奥取得
`LEAD_PAPERWEIGHT` 和 `FLASH_OF_STEEL`，首战 `FUZZY_WURM_CRAWLER_WEAK`
11 个决策全部一致；原生领取 12 金币和 `DEXTERITY_POTION`、跳过卡牌奖励后，
第二战 `NIBBITS_WEAK` 12 个决策也全部一致。7 场战斗合计 93 个 BC 决策；Silent
样本包含两次 `Survivor` 的原生弃牌选择。亡灵契约师的 Osty 已按 companion 投影，
储君样本验证了敌人死亡后仍按初始槽位寻址。

直接从第二战快照重建时，即使把日志中的 RNG counter 调到相同数值，起手牌仍然
不同；counter 不是完整 RNG state，不能作为中途跳转的充分条件。改为从新局顺序
执行涅奥、首战和奖励后，第二战逐步吻合。因此后续扩展必须顺序执行此前所有会
消耗 RNG 的战斗和局外结果，或使用经原生序列化验证的 checkpoint。

公开回放 header 没有玩家解锁状态；同 seed、同坐标在全解锁隔离 profile 中曾生成
不同 encounter。连续试点因此按记录指定原生 encounter model，只验证该遭遇进入后
的原生状态和决策序列，不把地图遭遇选择算作一致。这 93 步仍只是安全试点，不代表
24,856 个候选已经全部通过；尚有 24,763 步待原生验证。

## SpireFormer tensor bridge

`scripts/assemble-spire-codex-dataset.py` 将安全局外步骤和通过验证的原生战斗报告
映射到现有 `sts2-raw-features-v2` 特征协议，并写出 tensor shard v2：

```bash
python3 scripts/assemble-spire-codex-dataset.py \
  --native-replays artifacts/reference/spire-codex/native-replay-pilot
```

转换遵守以下约束：

- 只读取 `bc_eligible=true` 的 4,603 个局外步骤，并合并 6 份经哈希绑定的原生
  报告、7 场战斗共 93 步；恢复段不会被重新放行；
- 词表只在 train episode 上拟合；
- 按完整 episode、角色分层做确定性的约 80/10/10 划分；
- 多卡选择保留一个集合模板和逐候选标签；28 次合法取消保留模板与取消两个动作，
  但不伪造集合选择标签；
- 相邻安全局外步骤只有在同一 segment 且 `step_index` 连续时才共享时序窗口，跨过
  缺失的战斗或被排除步骤就切断轨迹；每场原生战斗作为独立连续轨迹；
- `return_to_go=0` 只是 BC 条件占位，`value_target` 全部缺失。

2026-10-11 本地发布结果位于忽略目录
`artifacts/reference/spire-codex/tensor-bc-v3/`，大小约 881 MB。特征缓存使用 FP16
存储，训练器会提升为 FP32；词表上限 512，实际特征宽度为 entity 609、action
560。数据集 ID 为 `afecb42485a472e6f97ce8d6baa08650`，词表 SHA-256 为
`83f4c23b1ccc004eacbb51354c2eff7a4417241b3b3b431805680b17de1f0aae`。划分如下：

| split | episode | 总 step | 战斗 | 局外 | trajectory |
|---|---:|---:|---:|---:|---:|
| train | 126 | 3,788 | 43 | 3,745 | 1,069 |
| val | 17 | 497 | 36 | 461 | 139 |
| test | 17 | 411 | 14 | 397 | 120 |

其余 6 局没有安全 BC 步骤。三个 split 都含五个原版角色，episode ID 不重叠；
总计 476 个集合选择界面步骤，其中 448 个有实际选牌集合标签，28 个为合法取消。
所有 shard 已按 manifest SHA-256 重读；Tiny（本数据宽度下 3,199,107 参数）已完成
一次 CPU/FP32 AdamW 更新。组装后首次跑 evaluator 暴露 FP16 shard 在评估路径没有
提升到 FP32，导致 Set Transformer 的 query/key/value dtype 不一致；现已与 trainer
统一为 FP32 master input，并增加 FP16 shard 回归测试。修复后 evaluator 对 val/test
都返回 `episode_split_verified=true`。

## 下一步

沿同一原生 `RunState` 顺序扩展奖励、事件和更多战斗，再分批扩大原生重放覆盖；每一
批都必须在每个手动输入边界重新投影 observation 与合法动作集合，并通过计划哈希和
完整战斗结果校验。当前 4,696 个安全 BC 步骤已经完成特征编码和 episode 隔离划分，可用于
第一版局外为主、含少量战斗样本的行为克隆；它不代表整局模型数据已经齐全。
