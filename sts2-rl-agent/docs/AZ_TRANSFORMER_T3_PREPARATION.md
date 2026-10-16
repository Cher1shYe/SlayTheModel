# T3 准备与 network 效用验收

2026-10-16。状态：**配置准备完成，实验尚未启动，T3 尚未验收**。

本轮继续 `spec_1.md`，落实用户新增要求：以 network 终局效用验收，胜率仅作诊断。此前“暂不启动训练实验”仍有效。

## 冻结配置

配置目录：`configs/az_transformer_t3_v1/`。准备方案已更新至 `transformer-t3-preparation-v3`；目录 v1 表示首批实验，v2 引入效用门槛，v3 接入专用运行入口。均为启动前修订，没有改动已运行结果。

| 项目 | S smoke | S 正式验证 |
|---|---|---|
| seed / 轮数 | 42 / 2 轮 | 42、43 / 各 3 轮 |
| 每轮场数 | 180 | 180 |
| 更新数 / 有效 batch | 4 / 32 | 16 / 64 |
| microbatch | 8 | 8 |
| 采集/search simulations | 4 | 8 |
| network 配对验证 | 256 场，不使用搜索 | 256 场，不使用搜索 |
| 初始化 | 独立随机 S | 每 seed 独立随机 S，不继承 smoke 权重 |

共同设置：G2.3e 冻结内容、原 V6 奖励；AdamW，学习率 0.0003、weight_decay 0.0001、betas=(0.9,0.999)、eps=1e-8，无 scheduler，梯度范数裁剪 1.0，FP32，CE+value MSE。CPU、2 workers、每 worker 1 thread。已识别本机 Intel Core Ultra X7 358H、16 逻辑处理器、33,873,752,064 字节物理内存；完整运行峰值和时长尚未测量，不能由此宣称满足资源门槛。OOM 时停止，记录后显式调整 microbatch，保持有效 batch。

`transformer_course.py` 保留 G2.3e 牌组、升级、HP、遭遇和 90 retained / 90 focused 配方；仅替换环境 RNG 与场景标识。训练 namespace 96 为 smoke，97/98 为正式 seed 42/43；与既有 G2.3e seed 42/43 三轮坐标逐项检查无交集。smoke/正式验证分别使用 master 190/189。最终 216 场仅保留 master 287 坐标，准备脚本不生成、不读取最终测试配方。

这些仍是既有配方分布上的新环境种子，不称为未见组合或未见 ID 泛化测试。

## 验收和晋级

`TrainingConfig.promotion_policy = network-utility-v1`，对应 `utility-only-v1` 门槛：

1. 对相同 256 个验证场景，分别运行 champion/candidate 的 **network-only** 策略。
2. 以实际 V6 终局奖励均值为主指标，计算 candidate − champion 的逐场配对差；不使用价值头预测值。
3. 沿用现有分层配对 bootstrap，10,000 次、统计 seed 1729、95% 区间。效用差区间下界严格大于 0 才晋级；平局或不确定提升不晋级。
4. 胜率、保血、timeout、Boss 阶段和 search 单独报告。胜率不否决效用提升、不裁决平局；search 结果不决定晋级。
5. 结果完整、配对一致、奖励复算有效、无异常或非法动作的要求继续保留；失败轮或非标准 episode limits 仍禁止晋级。timeout 正常计入效用，不删除。

工程完成（smoke/固定轮数、恢复与工件复算）和学习增益分开判定。后续学习增益也以 network 相对冻结初始基线的终局效用变化为主；最终测试须在两个冠军哈希共同冻结后才允许生成和评估。现有细分层中部分样本很少，bootstrap 区间只作为此次固定工程晋级规则，不宣称独立配方上的统计显著性或通用质量达标。

历史策略 `network-only-v1` 保留原胜率优先约束，供旧配置复现；本轮 T3 配置强制显式选择新策略，不追溯重算历史实验。用户补充已写入 `spec_1.md`。

## 准备入口和检查

```powershell
.\.venv-az\Scripts\python.exe scripts/prepare_az_transformer_t3.py
```

此命令只写配置、train/validation manifest、各轮配方摘要和代码/schema 摘要，不构造模型、不创建 Coordinator、不采集或更新。重复执行应完全相同；已冻结文件不同则拒绝覆盖。

本轮 **295 项测试通过（55.11 秒）**，结果见 `transformer_t3_preparation_tests.txt`：准备幂等/防覆盖、最终测试未访问、配方不变与 seed 隔离、配置拒绝、协调器课程接线、新效用门槛、search 不影响晋级，以及 T2/G2.3e/恢复/旧效用契约回归。特别验证效用提升而胜率下降仍可晋级，胜率增加而效用下降不能晋级。

## 后续运行入口（2026-10-16 补充）

- 已补齐 `run_az_transformer_t3.py` 的专用编排、smoke 底层工件复算及联合冠军冻结后的最终评估，详见 `AZ_TRANSFORMER_T3_RUNNER.md`。旧 `run_alphazero_continuous.py` 不用于这批配置。
- 用户明确要求启动实验后，才运行两轮 S smoke；正式训练还需 smoke 通过。当前准备文件不是实验通过证据。
