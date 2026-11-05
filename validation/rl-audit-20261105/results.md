# 验收结果（2026-11-05）

工作目录 `artifacts/dev/cpp-native-aligned-20261031`。所有命令都在此目录执行。
Python `D:/sts2_datacollection/sts2/.venv/Scripts/python.exe`（CPython 3.12）。

## 构建与身份

- 源码未变时增量重建：`simulator/build-win/_b.bat`（MSVC 14.51 + Ninja）。最后一次构建
  成功链接 `sts2_rules_test`、全部回归目标与 `simulator/sts2_sim.cp312-win_amd64.pyd`。
- 身份（`identity.json`，由 `identity_check.py` 生成）：ruleset `native-41cef1ea-port-v10`，
  公开观察 v20 / 83208（战斗 49972、局外 33236），动作 schema v17 / 729，
  卡牌特征 632，ArmG feature **v9** / obs 33236 / action 2459，
  `.pyd` SHA-256 `b3f4a31338241285c0fb0e3212f3974d7672436aa6f89ce5483fd74866719a12`。
  `PORT_SOURCE.json` 已同步这些数值、内容配置身份与 Elo 快照身份。

## 测试

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| CTest（42 个原生目标） | 42/42 通过 | `ctest.txt`；收尾复核 `ctest-final.txt`（2026-11-05 14:05，42/42） |
| Python 全套 | **438 passed / 17 skipped** | `pytest-final.txt`（2026-11-05 14:06，`pytest -q tests`，`--basetemp=D:/sts2_rl_runs/ptmp_final2`）；早先 437 行的 `pytest.txt` 保留 |
| 其中新增 | 审计回归 15、内容过滤 10、奖励 20、PPO 22、清点覆盖 3 | `tests/test_audit_rl_fixes.py` 等 |
| 整局冒烟 A0/A10 各 200 局 | 全部正常结束，0 异常 0 截断 | `smoke.json` |

新增测试文件：

- `tests/test_audit_rl_fixes.py`：审计 8 项在 Python 绑定/ArmG 层的回归。
- `tests/test_content_filtering.py`：奖励/商店/变牌/网格/牌组/战斗内生成入口 + 事件袋身份。
- `tests/test_run_reward.py`：终局奖励所有分项、4.47 示例、Elo 匹配/排除/缺失/空牌组。
- `tests/test_armg_ppo.py`：旧概率、掩码、GAE、裁剪、actor/critic 更新、强制动作、
  截断拒绝、数值有限、奖励增量和。
- `tests/test_engine_checkpoint_identity.py`：新增"改写版本号不能强行加载旧 checkpoint"。

原生回归 `simulator/tests/audit_rl_regressions.cpp`（CTest 目标 `audit_rl_regressions`）：
费用到期/保留/Sly 特征区分、MadScience rider 观察、隐藏重采样 200 种子与秘密顺序无关、
Pounce FREE_SKILL（0 能量、堆叠 ×2、正常付费路径）、药水物理槽。

跳过项（17）：缺历史训练/站点数据快照、需要配置的隔离模拟器；未删除断言或放宽容差。

## 冒烟（`smoke.json`）

| 难度 | 局数 | 完成 | 异常 | 截断 | 胜 | 平均层 | 最高层 | 局/秒 | µs/步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0 | 200 | 200 | 0 | 0 | 0 | 10.83 | 31 | 100.0 | 71.6 |
| A10 | 200 | 200 | 0 | 0 | 0 | 7.99 | 17 | 69.6 | 144.8 |

仅为引擎健康检查与吞吐，不是模型强度证据。

## 小规模真实 PPO 训练（可复现）

命令：

```sh
PYTHONPATH=. python -m agent.armg_train --games 80 --batch-size 8 --eval-every 40 \
  --eval-runs 2 --combat greedy --simulations 8 --ppo-epochs 2 --ppo-minibatch 32 \
  --max-steps 200 --out-dir D:/sts2_rl_runs/resumable_v9
PYTHONPATH=. python -m agent.armg_train --games 160 --batch-size 8 --eval-every 40 \
  --eval-runs 2 --combat greedy --simulations 8 --ppo-epochs 2 --ppo-minibatch 32 \
  --max-steps 200 --resume D:/sts2_rl_runs/resumable_v9/latest.pt \
  --out-dir D:/sts2_rl_runs/resumable_v9
```

确认：参数更新（每批 `updates` > 0）、奖励分项齐全且 `total_reward` 等于各分项之和、
0 异常、40→80 局续跑后 `progress.games`、优化器状态、torch/python/numpy RNG 一致且
训练继续。`D:/sts2_rl_runs/smoke/` 是 16 局的同类运行。

**最终 feature v9 复核（2026-11-05 下午）**：同一命令跑到 80 局后
`--resume D:/sts2_rl_runs/resumable_v9/latest.pt --games 160` 续跑；`progress.games`
80→160，`optimizer_state_dict` 与三路 RNG 状态存在并恢复，后续 10 个批次
`updates` 14–16，`truncated/errors` 全 0。旧的 `resumable/latest.pt` 是 feature v8，
不用于最终证据。

## 参考配置训练（已完成）

`D:/sts2_rl_runs/ppo_a10_ref_20261105/`（ArmG feature v9）

```
--games 1024 --batch-size 32 --eval-every 256 --eval-runs 16 --combat mcts-oracle
--simulations 5000 --floor-increment 500 --elite-simulations 5000 --boss-simulations 10000
--workers 16 --ascension 10 --ppo-epochs 4 --ppo-minibatch 128 --lr 3e-4 --seed 20261105
```

结果（`metrics.jsonl` 32 行，games 32…1024 无缺口、无重复）：

| 项 | 值 |
| --- | --- |
| 训练局数 | 1024（32 批 × 32），completed 1024、truncated 0、errors 0 |
| 计算时间 | 批次 `seconds` 合计 5911.8 s（约 98.5 min；不含两次重启与验证时间） |
| 每批平均层数 | 9.09（首批）→ 17.03（末批），最高批均值 17.91 |
| 胜率（训练批） | 0.0 |
| PPO 更新 | 共 1444 次 minibatch 更新；末批 updates 60 |
| 末批 PPO | policy_loss −0.0148、value_loss 0.0125、clip 0.051、grad_norm 0.547、exact_kl 0.0076、entropy 0.868、explained_variance 0.901、kl_early_stop false |
| 末批奖励分项 | floor 0.930、elite 0.091、boss 0.094、upgrade 0.108、removal 0.0025、Elo 2.192、合计 3.416；mean_Elo 1314.9、missing 5、excluded 39、升级 69、删牌 4、Boss 6 |
| 末次验证（20M 段） | 16 局：15 completed、1 truncated；完成局平均 25.33 层，胜率 0；`cycle_recoveries` 2614（5 局触发） |

**进程池中断**：约 games 736 之后日志出现两次 `BrokenProcessPool`，均以 `--resume`
续跑；批次原子写入，指标阶梯连续，没有重复计分或异常局写入训练。用相同种子与
16 worker 重跑首批（`D:/sts2_rl_runs/ref_repro_check/`）得到与原始 games=32 行完全
相同的指标（total_reward 2.574449266747601、mean_floor 9.09375、0 traceback），
说明批次可复现；中断根因未定位，训练代码未加自动重试。

## 独立评估（最终 checkpoint）

`deployment/evaluate_armg.py` 读取 PPO actor-critic（取 `actor.*`，仍通过引擎/schema/
形状检查），使用同一训练内容配置与搜索预算，并**传入训练同一 Elo 快照**。
评估种子为 `TEST_SEED_BASE` 段（30,000,000 起，32 个），与训练 (10M) / 验证 (20M) 不重叠。
checkpoint：`D:/sts2_rl_runs/ppo_a10_ref_20261105/latest.pt`（games=1024）。
原始输出：`D:/sts2_rl_runs/eval_ref_final2/eval.json`（1260.8 s）。

| 臂 | 完成 | 截断 | 错误 | 胜 | 平均层/最高 | 平均 R | floor | elite | boss | upgrade | removal | Elo | mean_Elo / missing / excluded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ArmG (PPO actor) | 32 | 0 | 0 | 0 | 20.41 / 33 | 3.894 | 1.239 | 0.103 | 0.188 | 0.158 | 0.000 | 2.206 | 1323.8 / 10 / 44 |
| 启发式 | 32 | 0 | 0 | 0 | 15.69 / 49 | 3.560 | 0.989 | 0.128 | 0.219 | 0.022 | 0.002 | 2.200 | 1320.2 / 6 / 44 |

配对（32 对，同种子、同战斗控制器与预算）：平均楼层差 **+4.72 ± 2.15 SE**；
0 对出现任一方通关（neither 32）。ArmG 臂有 9 局触发重复公开状态的循环保护
（共 113 次强制换动作），启发式 0 次。`evaluation_matches_training_battle=true`。

**解释边界**：战斗控制器是 `mcts-oracle`（完整模拟器状态 + 未来 RNG），不是 PPO
训练的战斗策略；32 对样本、0 胜，不能据此宣称性能提升或“纯玩家可见信息策略”
的强度。先前 07:31 的 `eval_ref/eval.json` 评估的是训练中途 checkpoint，且奖励缺
Elo 项，已在 README §5 记录并作废。