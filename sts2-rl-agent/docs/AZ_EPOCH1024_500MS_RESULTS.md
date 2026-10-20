# 1024 场 / 3 epochs / 500ms 冠军初始化独立实验（2026-10-20）

实验目录：`output/epoch1024_e3_500ms_20261020_005445`。本报告只使用该目录内 `run/report.json`、`run/dataset.json`、`run/state.json`、采集/验证原始场次和迁移记录，不依赖历史报告推断。

## 1. 设置

- 初始化模型：第一轮冠军 `iteration-000.pt`，SHA256 `b95195162750e188ecfad53d9eadcf730b18c097f60c6bc438ba5331a119d034`；原文件未修改，实验内 `models/initial.pt` 为同字节副本。
- 搜索：puct + mixed value（mix 0.5），500ms/决策，4 workers，2 场/进程，40 回合 / 100 决策；训练种子 3000000–3001023。
- 训练：全新优化器，batch 64，value weight 0.5，3 个完整打乱 epoch，无重采样、无尾部丢弃；学习率见第 7 节差异说明。
- 流程：采集 1024 场 → 296 条冻结配方基线 MCTS 验证 → 训练 → 296 条同一配方候选 MCTS 验证。验证两侧均使用 500ms 与最终隔离运行时。

## 2. 采集与数据集

| 指标 | 值 |
|---|---:|
| 采集场数 | 1024 / 1024 |
| 契约拒绝 / invalid | 0 |
| 胜负 / V7 time_limit | 800 胜 / 220 死 / 4 截断 |
| 胜率 | 78.125% |
| V7 平均效用 | 0.527439 |
| 有效决策行（进入训练） | 18,327 |
| 强制决策行 | 2,786 |
| searched decisions | 15,541 |
| 平均模拟/搜索决策 | 464.90 |
| 平均回溯深度（meanBackupDepth） | 3.2116 |
| 平均搜索耗时 | 501.96 ms |
| dataset id | `38d1010378b0d92b78b99ea7ba5681e6bbde907b16901f12c112978d22aef9c0` |

`run/dataset.json`：`samples=18327`、`epochs=3`、`updates=861`、`drop_last=false`。861 = 3 × ceil(18327/64) = 3 × 287；审计确认每个 epoch 287 步、每 epoch 恰好覆盖 18,327 个样本一次，无替换、无尾部丢弃。

## 3. 训练指标（861 updates）

| epoch | updates | samples | mean loss | policy loss | value loss | value MAE | mean grad norm |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 287 | 18,327 | 1.50939 | 1.24716 | 0.52446 | 0.52723 | 4.2232 |
| 2 | 287 | 18,327 | 1.38141 | 1.24343 | 0.27597 | 0.28112 | 5.5455 |
| 3 | 287 | 18,327 | 1.32152 | 1.24096 | 0.16111 | 0.17469 | 4.7563 |

损失下降主要来自 value 分支（0.524 → 0.161）；policy loss 基本持平（1.247 → 1.241）。断点：`run/checkpoints/update-00861.pt` 为最终优化器边界，`run/state.json` 为 `completed`，`updates=861`；`run/candidate.pt` SHA256 `9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13`。

## 4. 训练前后 296 配方 500ms 验证

| 指标 | 基线（冠军） | 候选（3 epochs） | 差值 |
|---|---:|---:|---:|
| episodes | 296 | 296 | — |
| wins / win rate | 225 / 76.01% | 238 / 80.41% | +13 胜 / +4.39 pp |
| V7 平均效用 | 0.489178 | 0.575847 | +0.086670 |
| 平均模拟/搜索决策 | 457.20 | 410.23 | -46.97（-10.3%） |
| 平均回溯深度 | 3.2261 | 3.6675 | +0.4413（+13.7%） |
| searched decisions | 4,446 | 4,521 | +75 |
| time_limit 截断 | 1 | 1 | 0 |
| 平均搜索耗时 | 501.85 ms | 501.82 ms | 同一 500ms 预算 |

配对 bootstrap（296 对）：V7 平均增益 **+0.086670**，95% CI **[0.029358, 0.145952]**，P(gain>0)=**0.9975**。两侧使用同一 296 条冻结验证配方、同一最终运行时；候选文件 SHA 与报告一致，基线模型 SHA 等于冠军 SHA。

## 5. 采集期间修复的三个严格契约故障

三个故障均以“严格契约错误即终止”的方式暴露；未跳过样本、未把异常写成截断。每次修复后都重放原失败轨迹、逐条重验缓存并做审计迁移（备份、旧/新 DLL 哈希、旧/新 identity 均保留）。

1. **VOLLEY 多段攻击死亡时点**（seed 3000393 / GREMLIN_MERC_NORMAL）：`VOLLEY+` 第 1 击击杀带 `SurprisePower` 的 Gremlin Merc 后，原生立即召唤 Sneaky/Fat Gremlin，后续命中清掉召唤物并获胜；模拟把死亡效果推迟到整张牌结束后，预测非终局。修复 `CombatPredictionSimulator.Attack.ExecuteAttack`：每次命中后立即 `ResolvePendingEnemyDeaths`。原轨迹 5 步重放通过；9 条多段/召唤回归一致；399 条缓存重验并迁移。备份：`control/before-volley-death-order/`。
2. **HAND_OF_GREED 对 Minion 的致命判定**（seed 3000432 / THE_KIN_BOSS）：击杀 9HP、带 `MinionPower` 的 KinFollower 时模拟多发 20 金（预测 gold=119、实机 99）。`ApplyCardPowers` 在伤害后才计算 `ShouldOwnerDeathTriggerFatal`，致命一击已把 Power 清零。修复 `CorePowerSupport.TargetDeathTriggersFatal`：先查模拟器存储的 `MinionPower`/`ReattachPower`（死亡后以 amount 0 保留），再回退 effective 列表。原 15 步重放 gold=99、hp=60、terminal=false；438 条缓存重验并迁移。备份：`control/before-handofgreed-minion-fatal/`。
3. **IRON_WAVE 被 Thorns 消耗后的重复格挡**（seed 3000799 / SPINY_TOAD_NORMAL）：IronWave 先得 5 格挡，攻击触发 Thorns 5 正好消耗为 0；随后 IronWave 后置兜底看到 0≤0 又补 5。修复：从 `Armaments or IronWave or Taunt` 兜底中移除 IronWave（推断式 OnPlay 已在攻击前获得格挡）。原 4 步重放 block=0、hp=60、terminal=false；805 条缓存重验并迁移。备份：`control/before-ironwave-thorns-fix/`。

## 6. 数据来源与解释边界

- 前 399 场采集于 VOLLEY 修复前，随后 39 场采集于 HAND_OF_GREED 修复前，随后 367 场在 IRON_WAVE 修复前采集，最后 219 场使用最终运行时。每条 raw 都带 `cache_origin` / `cache_migrations`，且全部通过严格原生轨迹/端点校验后才保留。
- 这些轨迹的 policy 目标由采集时的原生 PUCT 教师产生；极少数致命多段/`MinionPower` 状态的叶估计可能受旧模拟器版本影响。V7 奖励不含金币，因此 HAND_OF_GREED 的金币偏差不可能影响奖励标签。
- 训练前后验证均使用最终运行时和同一批 296 条冻结配方。
- 本实验同时改变了数据量/训练计划（1024 场、3 epochs）与搜索预算（250→500ms）；不能把收益归因于其中任一单独因素。搜索深度均指 meanBackupDepth，不是最大深度。

## 7. 需要明确的一处配置差异

目标记录写“学习率 0.003”，但冻结 `config.json`、实验 README 和冠军原训练配置均为 **0.0003**；本实验实际使用 `0.0003`，即沿用冠军学习率，而不是记录中的 `0.003`。如果 0.003 才是预期，那么本实验回答的是另一个问题，需要单独重跑；本报告不把 0.0003 的结果外推为 0.003 的结论。

## 8. 产物与复核

- 最终汇总：`run/report.json`；数据集：`run/dataset.json`；状态：`run/state.json`；候选：`run/candidate.pt`；861 个优化器断点：`run/checkpoints/`（29.2GB）。
- 独立审计：`analysis/final_report.py` 与 `analysis/final-report.json`；原始采集：`run/collection/`；基线/候选验证：`run/baseline/`、`run/candidate/`。
- 迁移与备份：三个 `control/before-*/` 目录，含 `migration.json`、旧/新运行时哈希、失败轨迹和逐条重验计数。
- 未对原冠军执行晋级，原 `az_native_ic138_w4_20261019_174426/iteration-000.pt` SHA256 仍为 `b9519516…`；候选仅保存在本实验目录。


## 后续复核更正

学习率 0.0003 符合本会话原始约定，0.003 为另一任务记录误写，无需据此重跑。本次前后验证都用500ms；不能将二者的提升归因于验证预算增加。仅跨历史250ms实验比较时有预算混杂。IRON_WAVE 与 HAND_OF_GREED 原失败轨迹实际均为未升级版本（upgrade=0）。Reattach Fatal 原生方法读取 live 状态的边界已在后续隔离对照中修复，详见 experiments/native_20261020。
