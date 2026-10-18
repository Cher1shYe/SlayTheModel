# All-content XS runner v3 操作手册

本轮仅完成修复、工程测试和无更新的 MCTS 契约检查；没有启动正式训练，也没有评估最终测试集。卡牌准入仍为 146 张，遭遇准入仍为 76 个。

从 `sts2-rl-agent/` 运行以下命令，Python 使用 `.venv-az/Scripts/python.exe`。

## 1. 开训前检查（不训练）

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --preflight-only
.\.venv-az\Scripts\python.exe scripts/check_training_readiness_mcts.py --workers 4
```

第一条检查冻结计划的 2432 个训练开局与 304 个验证开局构造／编码，不打开测试集；其 `ready` 仅代表开局检查。
第二条以新初始化 XS、MCTS=8、40 回合／400 决策检查 304 个验证配方和覆盖 76 个准入遭遇的固定卡组夹具。胜、负和达到预算都是合法终止；异常不是输局，也不会被隐藏。该诊断不进行梯度更新，不证明任意组合都可解或策略已有学习增益。

## 2. 下一步：用户授权后进行短程 smoke

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --iterations 1 --episodes 2 --updates 1 --budget 2 --batch-size 8 --max-turns 4 --max-decisions 24 --eval-max-turns 4 --eval-max-decisions 24 --out output/az_all_xs_v3_smoke
```

这是独立输出目录的管线检查，不复用旧权重。所有缩短预算都显式写出；smoke 结果不作为整场学习证据。先检查报告中的实际参数、零契约拒绝、有限 loss、checkpoint 和冠军选择。

## 3. 正式训练（本次未运行；另行授权）

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --workers 2 --out output/az_all_xs_v3_stratified
```

未指定的参数全部来自冻结配置：8 轮，每轮 304 场（76 种遭遇各 4 场）、16 次更新，batch 64，MCTS=8，学习率 0.0003，value weight=0.1；采集和验证均为 40 回合／400 决策。旧 v1 的短截断吞吐估算不适用于本次正式预算。

默认每轮以当前冠军采集并训练一个候选；可按第 10 节显式改用最新学习者。候选必须完成全部验证配方、无契约拒绝，且相对冠军的配对 bootstrap 95% 区间下界大于 0 才晋级；否则保留冠军。持续学习模型跨轮保留权重、AdamW 和采样／Torch RNG；候选不晋级也继续学习。冠军独立保存，负责晋级比较和最终评估；是否用于采集由 collection_model 决定。ALL 回放按遭遇均匀分层，再在该遭遇内抽取 episode 和状态。置信区间是冻结工程晋级规则，不替代独立多 seed 泛化验收。

## 4. 中断恢复

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --workers 2 --resume --out output/az_all_xs_v3_stratified
```

保持原来的所有有效参数；仅允许增加总轮数或改变 worker 数。`state.json` 是权威提交点，`report.json` 是派生汇总。每次 AdamW 更新后保存候选权重、优化器、采样 RNG、Torch RNG 和已完成更新数。已缓存的采集结果重放入 Replay 时按 episode id 幂等提交；已完成轮次不重新采集。汇总报告缺失不影响恢复。

初始化／初始基线完成并写出 `state.json` 后支持恢复；在此前失败，应使用新输出目录重做初始化。不接受 v1/v2 输出续跑（v3 增加独立 learner 恢复指针），也不接受修改过的源码、配置或协议续跑。普通启动拒绝覆盖非空输出目录。

## 5. 查看结果与最后留出

```powershell
.\.venv-az\Scripts\python.exe scripts/summarize_all_xs_run.py output/az_all_xs_v3_stratified/report.json --out docs/AZ_ALL_XS_V3_RESULTS.md
```

`effective_settings` 记录全部实际参数；`history` 保留各轮候选及 `promoted`，`champion_checkpoint` 和 `final_validation` 指向保留冠军，不能把最后候选当成冠军。`learner_checkpoint` 指向最后一次已提交轮次的更新 checkpoint，保存持续学习状态；`pending.update_checkpoint` 是未完成轮次的恢复点。

只有明确传入 `--include-test` 且冠军相对初始化的完整验证配对区间下界大于 0 才评估最终测试集。门槛不可用 `--force-test` 或 `--no-baseline` 绕过。本次不运行这一阶段。

## 6. 范围与兼容性

单人 Ironclad、进阶 0、无遗物药水；不新增牌池或遭遇。生命周期升级为 `initial-primary-budget-v6`：奖励预算只来自初始主敌，追加召唤物不增加预算；原生终局和逃跑事件负责结算。稳定出生槽位上限 128，超过原先 5 个的敌人仍可通过动态动作选择；超出容量显式失败。

实体 schema 已重新哈希，旧 checkpoint／Replay 拒绝加载。历史 v1 诊断保留为历史，不与修复后奖励或长程验证混算。契约检查仍是有限样本；正式采集或验证遇到新异常会停机并保存错误，而不是跳过后继续宣称成功。


## 7. 价值网络与 MCTS 诊断（显式运行，无训练更新）

以下仅为命令示例，本次开发没有运行新训练或正式诊断实验。每次使用新的 JSON 输出文件，工具拒绝覆盖已有结果。命令中的 checkpoint 请替换为实际存在的文件。

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.training_diagnostics --checkpoint output/az_all_xs_v2_formal/iteration-001.pt --out output/diagnostics/value-champion.json value --collection output/az_all_xs_v2_formal/collection-000.json --max-rows 256
.\.venv-az\Scripts\python.exe -m sts2_env.az.training_diagnostics --checkpoint output/az_all_xs_v2_formal/iteration-001.pt --out output/diagnostics/search-champion.json search --iteration 0 --episodes 8 --budgets 0 8 32 --max-turns 40 --max-decisions 400
```

价值诊断固定使用同一 collection 文件的确定性状态子集；比较不同 checkpoint 时保持文件和 max-rows 一致。输出 MSE、MAE、相关性、预测／目标均值、零预测和样本均值常数基线，并按终局 win/death/time_limit 分组。常数均值是诊断样本上拟合的参考，不是独立训练的基线；这些同局相关状态不能当作独立泛化样本。

搜索诊断对相同训练配方分别执行纯网络、无探索噪声 MCTS 8/32，记录效用、胜率、配对增益区间、决策延迟、合法动作访问覆盖率和逐局结果。只接收 train 配方，不读取验证／测试协议；异常直接失败，不能把异常记成输局。预算 0 表示纯网络，其他预算必须为正且不能重复。

诊断报告记录源码、checkpoint 和 collection 摘要。旧 v2 checkpoint 在 schema 相容时可以只读诊断，但不可以作为 v3 的完整续训状态；`checkpoint_source_matches=false` 表示当前环境源码与保存时不同，比较时应在同一环境下重新测量双方。诊断结果不参与冠军选择，不改变正式训练参数。


## 8. 持续学习改动的历史测试验收

在仅含本次拟提交改动、排除用户未提交卡牌修复的隔离源码副本中，以下 7 个文件合计 **75 passed（77.70 秒）**：

```powershell
python -m pytest tests/test_az_training_improvements.py tests/test_az_training_readiness.py tests/test_az_all_runner.py tests/test_az_replay.py tests/test_az_all_mcts.py tests/test_az_all_xs_config.py tests/test_az_status_report.py -q
```

覆盖持续两轮拒绝晋级后学习权重／AdamW 继续累积、冠军采集不被候选污染、第二轮更新中断后的逐参数精确恢复、99:1 遭遇分布的均匀分层抽样、价值基线与退化相关性、无更新诊断、测试集拒绝、诊断 CLI 参数／来源／防覆盖，以及原有训练恢复、MCTS、回放与状态报告回归。测试中的少量优化步和短战斗均为临时目录夹具，不是新训练实验。本次未重跑全仓历史失败集合，不宣称全仓全绿。


## 9. 分层随机采样协议

训练默认每轮 304 场：按排序后的 76 个准入遭遇循环 4 次，每次独立随机抽取 8～30 张卡（原有重复牌及升级概率不变）。卡组随机数由 split、iteration、job_id 和采样版本派生；不同轮次使用新卡组。战斗种子以唯一坐标进行幂次模数上的双射映射，支持范围内无种子碰撞。随机卡组不保证可解或构筑合理。

验证集使用独立 split、独立种子区间生成每种遭遇 4 个随机卡组，共 304 场，然后写入 protocol.json 冻结。每轮评估相同配方，不重抽验证题目。最终测试集保持原有 64 个配方。prepare_all_xs_protocol.py 可确定性重建本协议，且保留恢复、预算和晋级配置。

默认 8×304=2432 个训练配方；--episodes 可在 1～1024 范围内缩小用于 smoke 或扩大，只有场数为76的倍数时所有遭遇完全均衡，304时各4场。最多1024轮，越界显式报错，不循环复用坐标。新配置／协议摘要阻止旧输出误续训。训练参数中的 updates 仍为16，本次不顺带调整优化强度。


本批验收：隔离副本（不含用户未提交卡牌修改）中 **89 passed，78.61 秒**。命令如下；这是工程测试，不是训练实验。

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
python -m pytest tests/test_az_all_decks.py tests/test_az_all_runner.py tests/test_az_all_xs_config.py tests/test_az_training_readiness.py tests/test_az_training_improvements.py tests/test_az_stratified_plan.py tests/test_az_replay.py tests/test_az_all_mcts.py tests/test_az_status_report.py -q
```

构造／编码预检：training planned=2432、ok=2432；validation checked=304、ok=304；errors=[]、test=null。新增断言覆盖默认每遭遇4场、8轮场景ID／种子／实际卡组无重复、1024场边界无回绕、验证与训练隔离、冻结文件可确定性重建、重复验证配方拒绝、原有最终测试配方不变。短运行重复性测试使用4个验证配方的临时夹具，完整304配方由独立协议和预检测试覆盖。没有做整场304配方的学习效果评估。


## 10. MCTS 叶子估值与采集模型选择

本节为新增选项的使用说明，不代表已运行实验。当前 v3 运行继续使用原目录中的代码；本次提交在独立工作树完成，勿在运行期间拉取到训练目录。后续新方案用新输出目录，不将新源码或模式强行续接当前 v3；旧权重在 schema 相容时仍可只读诊断。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--leaf-mode` / `search.leaf_mode` | `heuristic` | `heuristic` 手写评分，`learned` 网络价值，`mixed` 加权混合 |
| `--value-mix` / `search.value_mix` | `0.5` | mixed 的网络价值权重，有限数且在 [0,1]；其他模式不使用它 |
| `--collection-model` / `training.collection_model` | `champion` | `learner` 最新已提交学习者，`champion` 保留冠军 |

非终局叶子的 mixed 回传为 `(1-value_mix)*heuristic + value_mix*network_value`，新节点与深度上限使用同一规则。三种模式均使用策略头的合法动作先验。胜利、死亡和环境时间上限使用既有 V7 搜索评分，不参与混合；时间上限沿用搜索根节点相对 HP 的截断语义。网络价值标签仍是完整 episode 的 V7 终局效用。手写评分与网络价值虽同在 [-1,1]，含义和校准程度不同，混合比例需要后续对照实验验证。

采集使用每轮开始时的冻结模型。learner 模式第 0 轮使用 initial.pt，此后使用上一轮 learner_checkpoint；候选未晋级不会让学习者回退。冠军仅在完整冻结验证集上通过既有配对置信区间规则后替换，最终验证／测试仍使用冠军。验证仍为纯网络，搜索估值选项只影响 MCTS。

未来显式启动命令示例（本次未执行）：

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --iterations 8 --episodes 304 --updates 64 --budget 8 --batch-size 64 --workers 2 --leaf-mode mixed --value-mix 0.5 --collection-model learner --out output/az_all_xs_value_mixed_new
```

纯学习价值改为 `--leaf-mode learned`；手写对照使用 `--leaf-mode heuristic`，其他条件保持相同。新开训练仍从随机初始化开始，此选项不隐含加载旧冠军。

无更新诊断也支持三种模式（每个模式用独立输出文件；本次未执行）：

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.training_diagnostics --checkpoint output/az_all_xs_v2_formal/iteration-001.pt --out output/diagnostics/search-learned-new.json search --episodes 16 --budgets 0 8 32 --leaf-mode learned
```

比较时保持 checkpoint、iteration、episodes、seed、预算与环境源码一致。报告记录 leaf_mode/value_mix。直接调用 evaluate 的 MCTS 路径也接受这两个参数。

`effective_settings` 和恢复 identity 包括全部新参数；即使改动的是当前模式不使用的 value_mix，也拒绝续跑。每轮 history/pending 记录 collection_model、collection_checkpoint 和 SHA256，避免把学习者采集误写成冠军采集。Replay compatibility 隔离不同模式和 mixed 权重，默认 heuristic 数据保持旧兼容格式。原始冻结配置文件没有新增默认值，缺省值由 runner 解析，不重写运行中的配置。


本批测试：隔离工作树、不包含原训练目录未提交的引擎修复，**315 passed，113.63 秒**。仅运行临时目录测试夹具，没有启动新训练或正式诊断，没有监控现有 v3。

```powershell
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
python -m pytest tests/test_az_leaf_modes.py tests/test_az_training_improvements.py tests/test_az_training_readiness.py tests/test_az_all_runner.py tests/test_az_replay.py tests/test_az_all_mcts.py tests/test_az_all_xs_config.py tests/test_az_status_report.py tests/test_az_stratified_plan.py tests/test_az_risk_reward.py tests/test_az_transformer_t2.py -q
```

新增测试覆盖实际 PUCT 回传、混合权重 0/1 边界、新叶子与深度截断、终局不调用网络、无效参数拒绝、CLI／评估透传、三模式串行与真实 spawn 一致性、回放跨模式／权重拒绝；两轮拒绝晋级时比对实际采集权重，确认 learner 更新而 champion 不变，第二轮更新中断恢复后权重逐参数和 AdamW 步数一致。原 runner mock checkpoint 夹具改为写文件，以匹配新增来源摘要审计。未运行全仓历史失败集合，不宣称全仓测试全绿。
