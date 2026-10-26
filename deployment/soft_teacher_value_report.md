# 两条路线验证报告：soft-visit 教师蒸馏 与 价值目标替换

日期：2026-10-27　机器：ts8　仓库：/home/doulingfeng/idea/sts（snapshot/sts2-workspace-20261012）
所有评估均为 **同一批 150 个种子、逐种子配对**；搜索预算 130 ms（部署口径）或 40 ms（先验敏感对照），
cPuct=3、playoutMode=1（专家贪心 rollout）、playoutEps=0.05、priorMode=0、best-line 选根。

## 0. 结论摘要

**思路 1（soft 访问蒸馏把先验做尖做准）：闭环跑通、机制生效，但目标未达成。**
- 先验确实变尖、也更贴近教师：熵 0.847→0.719，top-1 0.357→0.464，与教师访问 argmax 一致率 59.4%→62.5%。
- 但 130 ms 下绝对层数持平（46.51 → 46.70，配对 +0.19±0.32），先验贡献 +0.91→+1.74（双差 +0.83±0.54，t=1.53，不显著）。
- 在 40 ms（先验真正起作用的区间）先验贡献反而从 +2.28 掉到 +0.80（双差 −1.48±0.70，t=−2.12）；温度 T=2.0 只到 +0.88，T=0.5 为 −1.37。
- 校准曲线显示：每一个置信度档位的实际正确率都低于原先验（0.63 档 75.0% vs 81.8%；0.8 档 88.2% vs 100%），高置信样本占比 3.6%→17.7%。**先验被教尖的速度快于教准。**
- one-hot 对照（同一教师、同一执行动作，只把目标从访问分布换成 best-line one-hot）：130 ms 先验贡献 +1.59±0.52（vs armD +0.91，DiD +0.68±0.51，t=1.33），绝对层数 46.59（≈46.51）；40 ms 先验贡献 +0.85±0.61（vs armD +2.28，DiD −1.43±0.64，t=−2.24）。**soft 与 one-hot 之间差异 ≈0**（130 ms DiD −0.15±0.50；40 ms +0.05±0.61），即目标类型不是问题所在，蒸馏本身让先验在低预算下变差。
  （30 种子训练内评估：one-hot 第 2 轮 puct 36.87 / pure 23.07，soft 版 34.23 / 24.77，父代 36.47 / 25.93。）

**思路 2（换价值目标）：run-level 目标离线排序强、进搜索即崩；标量配对版 GAZ PTP 同样失败。**
- 战斗 z 并非“几乎恒定”：均值 1.412、std 0.586，57.8% 落在 [1.5,2]；现有 value net 在战斗状态的 R² 0.63–0.74。
- 离线（300 局，225/75 划分）：floor_reg run-level Spearman 0.695 / run 配对 0.746；floor_pair 0.580 / 0.702；z_reg/base/z_pair ≈0。
- 搜索（PUCT@512，30 种子，policy 固定 armD r4）：base 36.47；z_reg −1.10（ns）；floor_reg **−6.70（t=−4.70）**；floor_pair **−5.53（t=−3.67）**；z_pair +1.10（ns，输出 std 仅 0.11）。
- 双 actor GAZ PTP（current=armD r4 vs historical=armD r0，同种子同决策步 k 配对，sign(floor)，Bradley-Terry，3397 训练对/781 验证对）：验证配对准确率 55.2%→58.4%，run Spearman 0.445；但 PUCT@512 配对 **−5.83±1.63（t=−3.57）**；把输出尺度校准到 base 的 std（0.097→0.452）后仍 **−5.30±1.85（t=−2.87，3W/18L/9T）**。
- 真正未验证的是 GAZ 的**联合 V(s,s′) 网络 + 在线双 actor 循环**；本报告的标量 V + 配对损失是其廉价近似，已被证伪。

## 1. 思路 1 的实验设置

- 驱动：`deployment/selfplay_v3_soft.py`（v2 + `--teacher-cpp` 分支）。每步用当前 policy 给 C++ 搜索做根先验，
  `mcts_stats_ex_timed`（130 ms 扣除 policy 前向）返回 best-line 动作与根访问数；执行 best-line 动作，目标为根访问分布（soft target）。
- 训练：`runs_v2/softB`，从 armD r4 续训；2 轮 × 400 局 fresh run；48 workers；lr_policy=1e-4，lr_value=0（value 冻结）；每轮 ~15.5 万样本。
- 对照：`runs_v2/onehotB`，完全相同，只把目标换成 best-line 动作的 one-hot（`--teacher-onehot 1`）。
- 崩溃修复：种子 381834348 在第 48 层商店买第 97 张牌触发 `Deck::MAX_SIZE=96` 的 `fixed_list` 溢出（原来是 stack smashing）。
  已把 `Deck::MAX_SIZE` 提到 128 并重编译；训练驱动把单局异常改为写 `errors.jsonl` 并继续（>2% 才中止）。

## 2. 先验机制诊断（192 个 held-out 战斗状态，10 种子）

| 指标 | armD r4 | softB r6 |
|---|---|---|
| 先验归一化熵 | 0.847 | 0.719 |
| 先验 top-1 | 0.357 | 0.464 |
| 教师访问熵 / top-1 | 0.344 / 0.772 | 0.309 / 0.797 |
| KL(访问‖先验) | 0.715 | 0.661 |
| KL(先验‖访问) | 6.21 | 5.55 |
| argmax 与教师一致 | 59.4% | 62.5% |
| 与父代 argmax 相同 | — | 89.6%（KL 0.078） |

置信度-正确率曲线（先验 top-1 分箱 → 与教师 argmax 一致率）：

| 置信度 | armD r4 | softB r6 |
|---|---|---|
| 0.00–0.25 | 44.6%（n=56） | 45.2%（n=31） |
| 0.25–0.40 | 57.3%（n=75） | 57.6%（n=59） |
| 0.40–0.55 | 65.6%（n=32） | 54.5%（n=44） |
| 0.55–0.70 | 81.8%（n=22） | 75.0%（n=24） |
| 0.70–1.00 | 100%（n=7） | 88.2%（n=34） |

## 3. 搜索结果（150 种子）

130 ms：

| 指标 | armD r4 | softB r6 |
|---|---|---|
| pure | 24.13 | 23.92（−0.21±0.60） |
| native_greedy_timed | 45.59 | 44.96 |
| puct_greedy_timed | 46.51 | 46.70 |
| 先验贡献（puct−native） | +0.91±0.41 | +1.74±0.57 |
| 双差（逐种子配对） | — | +0.83±0.54（t=1.53） |

40 ms：

| 先验 | native | puct_greedy | 先验贡献 |
|---|---|---|---|
| armD r4 T=1 | 43.72 | 46.00 | +2.28±0.58 |
| softB r6 T=1 | 44.55 | 45.35 | +0.80±0.53 |
| softB r6 T=2.0 | 44.21 | 45.09 | +0.88±0.53 |
| softB r6 T=0.5 | 44.60 | 43.23 | −1.37±0.67 |

one-hot 150 种子 bench：

| 预算 | native | puct_greedy | 先验贡献 | 与 armD 的双差 |
|---|---|---|---|---|
| 130 ms | 45.00 | 46.59 | +1.59±0.52 | +0.68±0.51（t=1.33） |
| 40 ms | 44.25 | 45.10 | +0.85±0.61 | −1.43±0.64（t=−2.24） |

soft 与 one-hot 的直接对比：130 ms −0.15±0.50，40 ms +0.05±0.61，均 ≈0。

## 4. 思路 2 的数据

- 数据采集：`deployment/value_target_collect.py`（300 局，每 2 步一状态），离线对比 `value_target_offline.py`，搜索评估 `value_puct_eval.py`。
- 离线结果：`deployment/runs_v2/value_diag/offline_results.json`；搜索评估：`.../puct_eval.json`。
- 双 actor GAZ PTP：`deployment/gaz_ptp.py`、`deployment/gaz_scale_eval.py`；结果 `deployment/runs_v2/gaz_diag/gaz_ptp_results.json`、`gaz_ptp_sm_eval.json`。

## 5. 解读与建议

**思路 1**
1. 130 ms / ~27k sims 下，搜索会纠正先验的小偏差；先验从“还准”被教到“更尖但更不准”，绝对层数不动。
2. 40 ms 下先验主导，退化显著；压平温度（T=2.0）只回到 +0.88，说明不只是置信度标定问题。
3. **one-hot 对照与 soft 无差异**（40 ms DiD +0.05±0.61，130 ms −0.15±0.50）：不是“用访问分布当目标”把先验教坏，而是“把这个教师的搜索动作蒸馏进 reactive policy”这一过程本身让先验在低预算下变差。教师动作依赖 policy 看不到的搜索结果；两轮 1e-4 fine-tune 也可能破坏了 armD r4 先验原有的校准。
4. 不建议放大当前配方；若要继续，需要先解释/修复“蒸馏后低预算先验贡献下降”，并在 40–130 ms 两个预算上同时验收。
5. 更根本的观察：在这个搜索预算下，**先验不是瓶颈**——40 ms 下 puct_greedy 已有 46.0，130 ms 也只到 46.5；提升更可能来自搜索/rollout/价值本身。

**思路 2**
1. “win+HP 在战斗内几乎恒定”并不成立：z 有 std 0.59，价值网 R² 0.69–0.74；价值网在搜索里的战术区分是有用的。
2. run-level 目标（回归或配对）学到的是“哪一局更好”，不是“哪一步更好”；放进搜索直接损失 5–7 层。
3. 标量 V + 配对损失（GAZ 的廉价近似）同样失败，即使把尺度校准到与 base 一致。配对信号只体现在 run 排序（Spearman 0.445），没有转成战术区分。
4. 若继续走 GAZ 路线，必须实现论文原版的**联合 V(s,s′) 网络**，且比较参照应当是**同一战斗内的状态**（同一时间步的不同动作线），而不是另一局的同 k 状态；否则目标仍然是 run-level 的。

## 6. 复现命令

```bash
# soft 教师闭环
.venv/bin/python -X utf8 deployment/selfplay_v3_soft.py \
  --out deployment/runs_v2/softB --rounds 2 --episodes 400 --epochs 2 --workers 48 \
  --eval-count 30 --eval-sims 512 --resume deployment/runs_v2/armD --resume-round 4 \
  --teacher-cpp 1 --teacher-ms 130 --teacher-cpuct 3 --teacher-eps 0.05 \
  --teacher-prior-mode 0 --teacher-playout-mode 1 \
  --lr-policy 0.0001 --lr-value 0.0 --fresh-prob 1.0 --p-full 1.0 --batch 512 --buffer-cap 100000

# one-hot 对照：同上 + --teacher-onehot 1 --out deployment/runs_v2/onehotB

# 150 种子配对 bench
.venv/bin/python -X utf8 deployment/final_bench.py \
  --run deployment/runs_v2/softB --round 6 --workers 48 --extra-seeds 100 \
  --timed-ms 130 --cpuct 3 --prior-mode 0 --anneal 0 \
  --playout-mode 1 --playout-eps 0.05 \
  --modes native_greedy_timed,puct_greedy_timed \
  --out deployment/runs_v2/bench150_softB_r6.json

# 双 actor GAZ PTP
.venv/bin/python -X utf8 deployment/gaz_ptp.py 120
.venv/bin/python -X utf8 deployment/gaz_scale_eval.py
```
