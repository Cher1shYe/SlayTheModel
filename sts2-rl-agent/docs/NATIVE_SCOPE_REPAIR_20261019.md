# 单人原生采集修复与升级牌回归（2026-10-19）

本轮修复原生价值输入、外部搜索诊断和选牌边界对账，按原生元数据排除多人专用卡，并加入升级牌。累计完成 **7 个固定回归配方、7 个对应升级配方、8 个新种子配方，共 22 场、424 个有效决策**。未更新模型、未替换冠军、未启动正式训练。

## 修复内容

1. **动态费用字段**：当前游戏的 `NetFullCombatState.CardState.From` 在费用不同于 canonical 值时写入 `energyCost`。分支投影此前始终写 null，现通过已有分支 `GetEnergyCostValueWithModifiers` 计算局部和全局修正，按原生条件输出；不调用 live Hook。涵盖 STOMP 的回合内减费及升级改变的基础费用。
2. **召唤后实体顺序**：分支实体与原生一样按 `CombatId` 排序，保留实体身份、数值及动作目标。THE_OBSCURA 与 PARAFRIGHT 不再因阵容顺序误判。
3. **单人卡池**：从原生 `MultiplayerConstraint` 排除 17 张多人专用卡，155 张总卡池剩 138 张。配方层同时支持基础牌和一级升级牌，共 276 个 token；原生 worker 再次拒绝多人专用卡（包括 `+` 版本），并校验可升级性。没有实现多人语义，也没有按名字手写逐卡支持表。
4. **外部搜索异常诊断**：外部 MCTS 的节点保留绝对动作计数，但路线由外部拥有，没有 Beam 父链。显式标记所有权，失败诊断输出 `prefix=null` 和所有权标志，避免物化不存在的父链覆盖原始异常；普通 Beam 的非法动作链仍严格报错，没有伪造历史或跳过失败候选。
5. **新增发现的选牌边界问题**：升级／新种子检查发现，原生已执行到选牌位置（可能已经受伤），而 MCTS 待选择节点仍持有动作前快照，不能直接比较 HP。现在明确区分 `selector_boundary` 和 `complete_continuation`：前者要求双方均挂起、均未终局，并保留完整合法选项校验；选择完成后继续严格比较完整 continuation、HP、胜负和奖励。Python 验证边界标记必须与下一步真实 choice 状态一致，不能用标记绕过完整后继校验。

## 固定配方的可比性

保留原模型 checkpoint、遭遇、种子、HP、其余卡牌顺序，以及 mixed=0.5、250 ms/决策。依据用户要求只移除多人专用卡，不补入其他牌：

| 配方 | 移除的多人卡 |
|---|---|
| LIVING_FOG_NORMAL | BELIEVE_IN_YOU |
| GLOBE_HEAD_NORMAL | 无，原配方不变 |
| THE_OBSCURA_NORMAL | 无，原配方不变 |
| SLIMES_WEAK | MIMIC、TAG_TEAM |
| SEAPUNK_WEAK | BELIEVE_IN_YOU |
| OWL_MAGISTRATE_NORMAL | GANG_UP |
| OVERGROWTH_CRAWLERS | RALLY |

因此这 7 场是单人范围内的固定回归，不声称验证了原多人卡语义。每项保留 `original`、移除列表和新配方指纹。对应升级组将保留牌全部升级一级；新种子组从基础／升级混合 token 池抽样，seed 为 `19190000..19190007`。

## 实际验收

| 组别 | 最终通过 | 有效决策 |
|---|---:|---:|
| 原失败配方的单人回归 | 7/7 | 133 |
| 对应的全升级版本 | 7/7 | 130 |
| 新随机种子、混合升级版本 | 8/8 | 161 |
| 合计 | 22/22 | 424 |

这些配方共含 93 个不同基础卡 ID、77 种升级牌、106 个初始升级牌实例。所有成功轨迹均通过当前 Python 原始轨迹校验，包括实际初始卡组／升级等级、合法动作、访问分布、HP 连续性和终局奖励。

升级与新种子首轮有两场 endpoint 失败，日志未覆盖；仅对相关配方补充失败上下文和边界修复后重跑。最终两场含 2 次待选牌边界与 35 次完整后继。累计统计保留各场来源与版本，不假称所有场次均在同一次最终构建上运行。墙钟搜索可能选择不同路线；固定配方不等于逐动作路径恒定。

新增 C# CollectionContracts smoke 直接验证：选牌中间态／完整后继的区别、HP 和胜负失配拒绝、真实编译程序集的外部路线诊断、普通 Beam 坏父链仍拒绝。另以真实 worker 验证 `BELIEVE_IN_YOU+` 在战斗开始前被拒绝，不产生轨迹。

Python 新增卡池元数据、多人升级排除、固定配方最小修改、升级指纹、真实录制轨迹与损坏边界／升级信息拒绝测试；最终 **137 项通过**（63.16 秒），见 `tests.log`。

## 产物与边界

- `output/native_scope_repair_20261019/`：固定 7 场及首次回归日志。
- `output/native_scope_upgrades_20261019/`：升级／新种子首轮，保留两场失败。
- `output/native_scope_endpoint_20261019/`：失败端点取证，含 FOGMOG 原生 HP 57／待选牌节点旧 HP 66 的证据。
- `output/native_scope_final_20261019/aggregate-report.json`：22 场累计清单、每场完整路径与 provenance。
- `output/native_scope_final_20261019/`：最终两场、升级多人卡拒绝证据和最终 Python 测试日志。
- `tests/fixtures/native_scope_upgraded_v1.json.gz`：两场真实升级／选牌录制数据。

`scripts/check_native_scope_repair.py` 支持 `--only fixed upgraded fresh`、`--index` 与 `--failed-from <report.json>`；每批使用新目录，进度写 `progress.json`。先用原生目录导出任务构建 worker 和生成 catalog，再运行检查；严禁在采集中改换二进制。

本次是有界完整战斗兼容性验收，不是自进化收益证据，也不是 138 张卡所有组合均已验证。旧清单中缺失的两个遭遇 ID 仍未替换；同伴／球及多攻击意图分组等既有明确拒绝边界仍存在。遗物、药水组合及多级升级不在本批范围。
