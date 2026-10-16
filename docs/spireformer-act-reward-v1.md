# 首版分幕奖励：whole-run-act-v1

日期：2026-10-15。按用户确认的规则实现；不使用势函数。
本方案替代此前讨论的纯胜败奖励，旧版本保留以便读取历史产物。

## 规则

| 结算点 | 奖励 |
|---|---|
| 非 Boss 战斗结束（含普通、精英、事件战斗） | `(战后 HP − 战前 HP) / 战后最大 HP` |
| 第一幕胜利 | `+1` |
| 第二幕胜利 | `+2` |
| 第三幕胜利 | `+3` |
| 每幕首次 Boss 战开始前 | `0.05 × 当前牌组已升级牌数 + 0.1 × 当前持有遗物数` |
| 第三幕首次 Boss 战开始前，额外 | `当前 HP / 当前最大 HP` |
| 原生确认整局败北，不论位置 | `−10`，只追加一次 |

- 用户已确认 HP 公式改为“战后减战前”：掉血扣分，净回血加分。
- 用户已确认统计时点为每幕 Boss 战前；不是该幕第一场普通战斗。
- Boss 战均没有 HP 变化奖励；死亡于普通战斗时，HP 奖励与整局 `−10` 都结算。
- 三幕奖励分别追加，通关的幕奖励合计为 `6`，没有额外终局 `+1`。
- 升级牌按当前永久牌组中 `IsUpgraded` 的卡计数，每张一次，包含其他来源的升级；
  不要求升级必须发生于休息点，不累计已删除的牌，也不按升级层数重复计数。
- 遗物统计当前全部持有的遗物，包含起始遗物。每幕重新统计全部数量，
  同一张升级牌、同一件遗物可以在三个幕前分别计分。
- 双 Boss 幕在首个 Boss 前统计一次；直到原生地图的最后一个 Boss 获胜才给该幕奖励。
- 所有奖励直接相加，`gamma=1`，不截断、不归一化。`−10` 是追加惩罚，
  并不保证累计大量正奖励后的败局总回报仍然为负；胜局也可能因累计战损而为负。
- 放弃、进程中断、未知结局与缺口不自动当作败北。

## 离线重标注原则

奖励公式不属于采集器。采集器负责记录可复用的游戏事实，`assemble` 在原始 JSONL
之外生成奖励账本、RTG 和 tensor shard。源日志不改写，改权重或组合方式时删除旧的
派生目录并用新输出目录重跑即可。

`whole-run-v2` 旧日志已有以下通用证据：公开决策状态中的 HP、最大 HP、幕数、牌组和
遗物；逐动作的 HP 变化；原生 `combat_started/combat_ended` 生命周期；原生整局胜负。
离线转换器据此重建 `whole-run-act-v1`。旧日志战前 HP 使用该场战斗的**首个公开决策
状态**，战后 HP 使用整场通用 HP transition 求和，并在存在下一公开状态时交叉核对。
这是可重跑的明示口径，不把未来信息或隐藏 RNG 放进模型特征。

当前 9 局本地日志中，6 局 no-SL 日志通过这条离线路径，共 4,021 个安全动作标签：
train 4 局/2,738 步（3 胜 1 负）、val 1 局/781 步、test 1 局/502 步。局部采集 gap 会切断历史并
排除受影响动作，不再仅因 `value_target_valid=false` 否定整局中可独立核验的奖励。
另外 3 局仍因 `information_regime=unknown` 或策略来源证据不足被排除；这与奖励公式
是否离线计算无关。

Tiny 已在该 train split 上完成 1,000 个 CPU/FP32 optimizer step。真实记录 RTG 条件下，
整局隔离 val/test top-1 为 49.68%/53.98%；零 RTG 为 49.17%/53.78%。差异很小，
目前只能确认 RTG 已进入模型和数据管线，不能确认模型学会了可靠的目标回报控制。
test NLL 1.962 高于 uniform 1.600，集合选择 exact-set 为 0，均说明数据量仍不足。

只有奖励需要的数据事实从未记录时，旧日志才无法支持该奖励。例如以后若按一个未写入
日志的隐藏原生计数发奖励，就必须先补采该事实。当前方案依赖的公开事实已经存在。

## 原生精确结算边界

新采集器在原有 JSONL 中追加 `diagnostic`，`code=act_reward_boundary`，
`data.schema_version=1`。既有 `whole-run-v2` 的原始 reward 事件保持原意。

1. 战前：原生 `Hook.BeforeCombatStart(IRunState, ICombatState)` 的前置观察。
   此时尚未执行 BeforeCombatStart 效果及第一回合；读取永久牌组、遗物和 HP。
2. 胜利战后：原生 `CombatWon` 事件；已完成 `AfterCombatVictory`，因此包含
   燃烧之血等自动战后回血，尚未由玩家领取战利品、用药或进行下一次局外决策。
3. 失败战后：`CombatEnded`，或原生终局处理入口的兜底；在 episode 结束前
   关闭仍活动的战斗。两条路径去重，不能重复结算。
4. 幕胜利：以真实 Boss 胜利和原生地图最后一个 Boss 坐标确认。
   普通首领模型名称、奖励页面、楼层变化不能替代这些证据。

每个边界保存：`phase`、`combat_id`、`act`（1–3）、`is_boss`、`hp`、`max_hp`、
`upgraded_cards`、`relics`、`won`、`act_completed`。起点 `won=null`。
边界 ID 与原有 `combat_started` 一致；Python 检查原生生命周期的覆盖与对应关系。
采集失败记录 `act_reward_boundary_unavailable`；若日志声明精确边界却记录不可用，组装会
拒收，避免悄悄降级口径。没有这类新诊断的历史日志走上一节的通用事实重建路径。
这些证据仅用于计算标签和审计，不进入模型状态特征。

精确边界和旧日志的首决策锚点并非完全相同：开战自动效果可能发生在两者之间。报告会
明确写出 `evidence_mode` 与锚点，避免把旧数据描述成精确原生 BeforeCombatStart 快照。

## RTG 与训练接入

`act_rewards.py` 是纯 Python 奖励计算器，消费真实战斗起止、幕结束与整局终态。
`act_reward_journal.py` 按原始事件顺序形成奖励账本，再自动倒序累加出每步 RTG。
`assemble.py` 先执行严格整局 no-SL 审计，再生成带新 reward version 的张量缓存。

重要时序：Boss 入场奖励产生于开战前，属于之前的地图/事件动作结果。
第一步 Boss 决策发生时，这笔奖励已经获得，其 RTG 不再包含这笔入场奖励。
幕奖励与战斗 HP 奖励在战后产生；之后领奖励的动作不再包含已经获得的战斗奖励。
切训练窗口发生在整局 RTG 计算之后，窗口边缘不重置回报。

从仓库根目录使用训练入口：

```bash
spireformer assemble \
  --input artifacts/human-dataset/episodes \
  --output artifacts/spireformer/act-rtg-human-v2 \
  --train-episode TRAIN_EPISODE_ID \
  --val-episode VAL_EPISODE_ID \
  --test-episode TEST_EPISODE_ID \
  --reward-scheme whole-run-act-v1
```

默认入口仍是 `bc-only`，需显式选择新方案。输出 manifest 与 checkpoint 绑定
`reward_version=whole-run-act-v1`，包含奖励参数和每局奖励账本。旧 BC 或纯胜败
checkpoint 不能作为新任务的严格 resume。原始信息模式与 train/val/test 隔离规则不变。
所有 `value_target` 仍为空；训练使用 `--value-weight 0`。

### MCTS 与人工混合的新采集

新采集需要同时更新 **Adapter 和 DataCollector**，并从新局开始，显式配置
`information-mode no-sl`（Windows 为 `-InformationMode no-sl`）。`auto` 仍记录
`unknown`，不会因为 MCTS 打赢或没有读档事件而自动转成 no-SL。
配置的 no-SL 观察只含公开状态；MCTS 老师使用原生 checkpoint 搜索的事实另记在
`policy.teacher_information=native_checkpoint_privileged`，不代表老师仅看公开信息。
checkpoint、RNG、未来抽牌顺序与来源标记均不送入模型特征。

新来源桥在实际动作提交前冻结状态，按同一个原生动作关联 `native-mcts` 或
`first-legal`。MCTS 转交人工界面的选牌与手动配置的局外操作保留人工来源；没有可核对的
来源仍保留未知。MCTS 根节点各动作 visits 尚未录制，不生成访问次数蒸馏目标。

用户准备实机复测时，先退出游戏，再在仓库根目录更新两个模组。macOS：

```bash
./scripts/macos.sh --action install
./scripts/collector-macos.sh --action install --information-mode no-sl
SLAY_THE_MODEL_INFORMATION_MODE=no-sl ./scripts/macos.sh --action launch \
  --combat-policy mcts --outside-combat-policy manual
```

Windows PowerShell（Steam 已打开；本轮没有 Windows 实机验证）：

```powershell
.\scripts\windows.ps1 -Action Install -CombatPolicy mcts -OutsideCombatPolicy manual
.\scripts\collector-windows.ps1 -Action Install -InformationMode no-sl
.\scripts\windows.ps1 -Action Launch -CombatPolicy mcts -OutsideCombatPolicy manual
```

从新局开始，先验收一局的普通出牌、选牌/空确认和战斗奖励记录；再收集用于训练
与整局隔离评估的胜败局。上述命令是待用户执行的更新步骤，本轮未安装或启动游戏。

采集后先审计，再组装：

```bash
PYTHONPATH=model/spireformer python scripts/audit-act-reward-data.py \
  artifacts/human-dataset/episodes \
  --allow-policy native-mcts \
  --output artifacts/spireformer/act-readiness.json

spireformer assemble \
  --input /path/to/new/episodes \
  --output artifacts/spireformer/act-rtg-mcts-v1 \
  --train-episode TRAIN_EPISODE_ID \
  --val-episode VAL_EPISODE_ID \
  --test-episode TEST_EPISODE_ID \
  --reward-scheme whole-run-act-v1 \
  --allow-policy native-mcts
```

默认组装仍只监督人工动作。显式 `--allow-policy native-mcts` 要求真实
`policy_id` 与教师信息字段匹配，保留原 actor 和来源统计；它不放宽信息模式、
哈希链、缺口、战前/战后奖励边界或原生终局检查。`observed-automation` 不能靠此参数
补成 MCTS。`first-legal` 需要另行显式允许，教师信息必须为 `public_observation`。
单局不能拆成训练/验证/测试三份来冒充独立评估。

2026-10-15 新上传 `f0006360…` 铁甲 A0 胜局有 562 个决策、20 场战斗，
文件哈希链通过；但信息模式全为 `unknown`、没有新奖励边界，且有两处选牌缺口，
仍不属于本方案训练数据。它含本地此前未实现的 `mcts_card_choice` 记录，说明录制
构建与当前本地来源不同。旧文件保持原样；本轮修复须由更新后的真实新局验收。

训练 RTG 自动计算，无需手填。自主推理的目标 RTG 之后要按新回报尺度另行选择，
不能沿用旧纯胜利方案的固定目标 `1`。当前 evaluator 的 `recorded` 仅作事后诊断；
自主推理、在线收集与实际通关率仍需独立接入验证。

## 验证边界

2026-10-15：完整 Python 模型测试 **292 passed**，DataCollector Release 构建
**0 warnings / 0 errors**，隔离原生对象
采集 smoke 返回 `act_reward_capture_smoke=ok`，`git diff --check` 通过。

测试覆盖纯奖励规则、战前与战后时点、死亡叠加、三幕胜利、双 Boss 去重、
跨窗口 RTG、异常日志拒收、版本化张量读写，以及与模型训练入口的兼容。
合成胜局用于验证计算规则，不能当作真实游戏训练数据。

可重跑：

```bash
PYTHONPATH=model/spireformer python -m pytest model/spireformer/tests -q
./scripts/collector-macos.sh --action build
dotnet run --project smoke/SlayTheModel.ActRewardCapture.Smoke -c Release -p:UseSharedCompilation=false
```

采集 smoke 链接生产捕获代码，使用隔离的原生游戏数据对象和替代日志 sink，
人工调用生命周期回调，并检查真实 Harmony prefix 签名。它覆盖 HP 冻结、起止
去重、永久升级计数、单/双 Boss、无地图死亡与重置，不等于原生跑局的实机证据。
旧源文件的拒收报告位于忽略文件 `artifacts/spireformer/act-rtg-v1-source-audit.json`。

本轮不安装 Mod、不启动 Steam、不修改原始数据。离线产物位于忽略目录
`artifacts/spireformer/act-rtg-human-v2/`，报告逐局记录源 SHA-256、证据模式和奖励账本。
采集器的新精确边界仍须安装后的真实跑局复测，但不阻止旧通用日志离线重标注。

同日 MCTS 采集补齐后回归：Python 全套 **291 passed**；共享 collector smoke、
分幕奖励捕获 smoke 通过。来源桥检查当前游戏程序集中的入队/取消调用顺序，
选牌测试链接生产捕获代码并模拟完成、人工 fallback 与错误路径；这些仍是离线检查。
新增的第九局仍因 unknown 信息模式和来源证据不足而不合格；当前分幕 RTG 合格为
**6 局、4,021 步**。
