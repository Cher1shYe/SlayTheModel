# 2026-11-05 训练问题跟进修复

工作副本：`artifacts/dev/cpp-native-aligned-20261031`。保留本轮前全部用户改动、历史验证和训练权重；未提交、未推送。本目录记录本轮验证，不覆盖前轮证据。

## 修复内容

1. **隐藏顺序影响观察/重采样**：`card_public_key` 补齐观察已暴露的单回合 Retain、Sly、MadScience 类型/Rider、费用修正到期计数。相同公开牌集合反转隐藏顺序后应有相同公开观察，固定采样种子得到相同公开牌序列。新增 7 类状态 × 200 种子回归，不使用 UID 做排序兜底。
2. **异常局使训练器 KeyError**：修正 `error` / `errors` 映射，错误局只记录并计数，不进入 PPO。
3. **need-rules 概率错误**：轨迹保存实际 bonus/mask；记录旧概率、PPO 更新与 KL/熵诊断均重放同一变换。变长动作先变换再补齐，禁止 padding 影响 z-score；被屏蔽动作概率为零，计算避免 `0 * inf`。
4. **Boss 搜索预算叠乘**：删除 `_mcts_plan` 的隐式三倍。预算严格为 base + per_floor × (floor−1) + elite/boss 显式增量；例如 floor 8、base 2000、per_floor 200、boss 2000，应传入 5400。
5. **进程池与复现**：每局独立分配采样种子，串行与并行使用相同方案，worker 数写入日志/进度。BrokenProcessPool 重建一次并重试原批次；再次失败保存批次前 RNG 和未前进的进度后报错。故障单独写 `worker-events.jsonl`，不污染正常批次指标。自动重试不代表已定位过去两次 worker 崩溃的底层原因。
6. **长决策循环**：64 步滑动窗口改为整局公开状态访问计数，恢复优先尝试较少访问的合法出口。强制动作仍排除 actor loss，保留 critic 轨迹与恢复计数；保留所有合法动作，不自动删除选牌/取消操作。新增 70 状态循环回归。该改动消除了窗口遗忘缺陷，不保证任意旧策略都无需恢复或永不截断。
7. **验证奖励与最佳模型**：内部验证传入同一冻结 Elo，汇报完整 `mean_reward`，best.pt 按完整奖励选取，仅在所有验证局正常结束时更新。

## 验证

最终：CTest **42/42**（41.54 秒）；Python **444 passed / 17 skipped**（85.51 秒）。17 个跳过仍为可选历史资产缺失。新二进制 SHA256：`cd1f7896069085c1dd369b94b9a696d66c2809a5cd856c71e74d6eb8448b4e53`。

- `build-final.txt`：完整目标构建成功。第一次 `build.txt` 链接失败是并发 Python 测试占用 `.pyd`，测试退出后完成链接，未忽略编译错误。
- `targeted.txt`：初步 39 项针对性测试通过；最终源码以全量日志为准。
- `ctest-final.txt` / `pytest-final.txt` 是中断的首轮全量测试日志，**不算通过证据**。最终采用 `ctest-complete.txt` / `pytest-complete.txt`。
- `smoke.json` / `smoke.txt`：训练过滤配置，A0、A10 各 202 局（1..200、367、466），总计 404 局，0 异常、0 截断。启发式局外 + greedy 战斗，0 胜，不代表训练强度。
- `ppo-smoke/metrics.jsonl`：独立新建模型，2 workers，need-rules 开启，8 局训练、2 局验证；全部正常结束；两批共 22 次 need 决策，PPO 更新与 KL 早停正常工作。不是正式长程训练。
- 回归覆盖故障注入、连续两次池损坏的保存、错误局丢弃、含屏蔽动作的概率一致性、1/2/3 workers 参数与 RNG 一致性、断点恢复一致性、奖励与楼层排序相反时的 best 选择。

复现：在工作副本运行：

```powershell
& simulator/build-win/_b.bat
& D:/sts2_datacollection/sts2/.venv/Lib/site-packages/cmake/data/bin/ctest.exe --test-dir simulator/build-win --output-on-failure
& D:/sts2_datacollection/sts2/.venv/Scripts/python.exe -m pytest -q tests
```

`smoke.py` 默认向本目录 `ppo-smoke` 新建训练记录，已有目录会拒绝覆盖；复跑时改用新的独立输出目录。

## 身份与剩余边界

- 布局未变：观察 v20、动作 v17、ArmG feature v9、snapshot v14。源代码摘要及二进制摘要已变化，`PORT_SOURCE.json` 同步新二进制 SHA256；训练器增加 `trainer_version=2`、`episode-seeded-v2`、`best_metric=mean_reward`。
- 旧权重文件完整保留。旧环境/训练配置 checkpoint 不得伪造身份直接 resume；兼容迁移须另行显式审核，本轮不替换正式权重。
- 水晶球事件和多人专用卡继续由训练内容配置排除，未扩展水晶球事件。
- 未重跑旧 1024 局训练或旧模型的长程验证；不能将新冒烟结果外推为旧模型循环全部消失。
- 复杂费用修正栈的完整可观察性、长组合及原生整局等价仍未穷举。此次隐藏排序只补齐当前已编码公开状态，不声称解决所有状态混叠。
- `mcts-oracle` 仍读取完整战斗状态和未来 RNG，这是标明的信息边界，不是本轮改成 PPO 战斗策略。缺少目标 DLL 不作为本轮本地修复验收阻塞，也不宣称做了原生差分。
