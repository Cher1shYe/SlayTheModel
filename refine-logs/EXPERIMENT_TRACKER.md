# 实验跟踪表

日期：2026-09-24
以下全部为拟执行项，本轮未启动。已存在报告仅作输入证据，不改写为本轮成功结果。

| Run ID | 阶段 | 目的 | 系统/变体 | 数据切分 | 关键指标 | 优先级 | 状态 |
|---|---|---|---|---|---|---|---|
| R001 | M0 | 修正并测试 ABI / 模式 / cap 端到端传递 | 当前 ONNX v4/checkpoint v3 + 旧版负例 | 合成合同测试 | 合法接受，错误拒绝 | 必须 | TODO |
| R002 | M1 | 8 条真实波次接口验收 | pure/tree × full/mid | 2 个开发 seed × 1 encounter | provenance、实际模式、调用、完整审计 | 必须 | TODO |
| R003 | M1 | 当前发布选择/嵌套/死亡语义 | PURITY/Burning Pact/CASCADE/death | 专用 regression-only fixtures | 真到节点、live 对账、训练隔离 | 必须 | TODO |
| R004 | M1 | 复查三 seed 退化及非 cap 性能 | pure/tree | 开发集，不作终验 | prior/value 误差、决策、active/wall 吞吐 | 必须 | TODO |
| R005 | M2 | 冷启动/未晋级 bootstrap 数据 | 当前 ABI pure teacher；可另立 tree bootstrap | 新训练/验证 seed，20×5×2 为预算例 | 完整轨迹、非法/异常率、类覆盖 | 必须 | TODO |
| R006 | M3 | 训练候选并对账 Native | 保持 1,970 参数 candidate | 固定按 seed 切分 | policy/value loss、ABI、ONNX 数值 | 必须 | TODO |
| R007 | M4 | 全登记技术配对矩阵 | pure/tree | 3×5×5×2 = 150 次示例 | gate、fallback、合法率、覆盖、>=100/s | 必须 | TODO |
| R008 | M4 | 质量与不退化评估 | pure/tree；已有 champion 后另加入 | 独立未见 seed，数量由精度目标决定 | 配对胜负/reward/战损、不确定性 | 必须 | TODO |
| R009 | M5 | 一代受控闭环 | 只有通过 M4 的 champion | 全新采集 seed + 隔离评估 | 采集—训练—审核—保留/替换可恢复 | 必须 | TODO |
| R010 | M5 | 温度/根噪声与历史回放扩展 | 明确训练模式，评估关闭探索 | 已登记训练样本；禁用 eval/validation 回流 | 多样性、lineage、退化 | 后续 | TODO |

R001-R003 是首先开展的三组工作。任何一步失败先保留诊断并修复，不绕过门禁推进 champion。

