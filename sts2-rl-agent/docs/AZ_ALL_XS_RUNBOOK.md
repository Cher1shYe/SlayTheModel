# All-content XS runner v2 操作手册

本轮仅完成修复、工程测试和无更新的 MCTS 契约检查；没有启动正式训练，也没有评估最终测试集。卡牌准入仍为 146 张，遭遇准入仍为 76 个。

从 `sts2-rl-agent/` 运行以下命令，Python 使用 `.venv-az/Scripts/python.exe`。

## 1. 开训前检查（不训练）

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --preflight-only
.\.venv-az\Scripts\python.exe scripts/check_training_readiness_mcts.py --workers 4
```

第一条检查冻结计划的 384 个训练开局与 64 个验证开局构造／编码，不打开测试集；其 `ready` 仅代表开局检查。
第二条以新初始化 XS、MCTS=8、40 回合／400 决策检查 64 个验证配方和覆盖 76 个准入遭遇的固定卡组夹具。胜、负和达到预算都是合法终止；异常不是输局，也不会被隐藏。该诊断不进行梯度更新，不证明任意组合都可解或策略已有学习增益。

## 2. 下一步：用户授权后进行短程 smoke

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --iterations 1 --episodes 2 --updates 1 --budget 2 --batch-size 8 --max-turns 4 --max-decisions 24 --eval-max-turns 4 --eval-max-decisions 24 --out output/az_all_xs_v2_smoke
```

这是独立输出目录的管线检查，不复用旧权重。所有缩短预算都显式写出；smoke 结果不作为整场学习证据。先检查报告中的实际参数、零契约拒绝、有限 loss、checkpoint 和冠军选择。

## 3. 正式训练（本次未运行；另行授权）

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --workers 2 --out output/az_all_xs_v2_formal
```

未指定的参数全部来自冻结配置：8 轮，每轮 48 场、16 次更新，batch 64，MCTS=8，学习率 0.0003，value weight=0.1；采集和验证均为 40 回合／400 决策。旧 v1 的短截断吞吐估算不适用于本次正式预算。

每轮以当前冠军采集并训练一个候选。候选必须完成全部验证配方、无契约拒绝，且相对冠军的配对 bootstrap 95% 区间下界大于 0 才晋级；否则保留冠军。每轮候选从冠军权重与新的 AdamW 开始，轮内更新保持优化器状态。置信区间是冻结工程晋级规则，不替代独立多 seed 泛化验收。

## 4. 中断恢复

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner --workers 2 --resume --out output/az_all_xs_v2_formal
```

保持原来的所有有效参数；仅允许增加总轮数或改变 worker 数。`state.json` 是权威提交点，`report.json` 是派生汇总。每次 AdamW 更新后保存候选权重、优化器、采样 RNG、Torch RNG 和已完成更新数。已缓存的采集结果重放入 Replay 时按 episode id 幂等提交；已完成轮次不重新采集。汇总报告缺失不影响恢复。

初始化／初始基线完成并写出 `state.json` 后支持恢复；在此前失败，应使用新输出目录重做初始化。不接受 v1 的 weights-only 输出，也不接受修改过的源码、配置或协议续跑。普通启动拒绝覆盖非空输出目录。

## 5. 查看结果与最后留出

```powershell
.\.venv-az\Scripts\python.exe scripts/summarize_all_xs_run.py output/az_all_xs_v2_formal/report.json --out docs/AZ_ALL_XS_V2_RESULTS.md
```

`effective_settings` 记录全部实际参数；`history` 保留各轮候选及 `promoted`，`champion_checkpoint` 和 `final_validation` 指向保留冠军，不能把最后候选当成冠军。

只有明确传入 `--include-test` 且冠军相对初始化的完整验证配对区间下界大于 0 才评估最终测试集。门槛不可用 `--force-test` 或 `--no-baseline` 绕过。本次不运行这一阶段。

## 6. 范围与兼容性

单人 Ironclad、进阶 0、无遗物药水；不新增牌池或遭遇。生命周期升级为 `initial-primary-budget-v6`：奖励预算只来自初始主敌，追加召唤物不增加预算；原生终局和逃跑事件负责结算。稳定出生槽位上限 128，超过原先 5 个的敌人仍可通过动态动作选择；超出容量显式失败。

实体 schema 已重新哈希，旧 checkpoint／Replay 拒绝加载。历史 v1 诊断保留为历史，不与修复后奖励或长程验证混算。契约检查仍是有限样本；正式采集或验证遇到新异常会停机并保存错误，而不是跳过后继续宣称成功。
