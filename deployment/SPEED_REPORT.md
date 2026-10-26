# STS1 本机速度实测

2026-10-26，Intel Core Ultra X7 358H，Windows，MSVC Release，Python 3.12.13。单进程串行、未绑定 CPU 核心；PyTorch 设为单线程，搜索本身不调用网络。没有启动 STS2 实验。

| 测量项 | 吞吐 |
|---|---:|
| C++ 原生随机战斗推进 | 1,603,277 动作/秒 |
| C++ 随机 rollout 到终局 | 98,111 rollout/秒 |
| Python 枚举合法动作、随机选取、调用 C++ 执行 | 133,939 动作/秒 |

原生 rollout 平均 16.34 动作，计时包含根状态复制、动作生成、随机选择、执行、终局判断及路径记录；不是只测裸 execute 函数。Python 与原生使用不同随机数/候选生成路径，因此吞吐差不能全部归因于跨语言开销。

| 每次决策 MCTS 预算 | 总模拟数/总耗时 | 平均决策耗时 | 不同局面的中位耗时范围 |
|---:|---:|---:|---:|
| 100 | 87,218 simulation/s | 1.15 ms | 0.25–2.13 ms |
| 2,000 | 91,941 simulation/s | 21.75 ms | 5.02–42.12 ms |
| 50,000 | 94,529 simulation/s | 528.94 ms | 104.11–1,072.10 ms |

MCTS 计时覆盖 Python 的 mcts_recommend 调用全程，包括新建搜索器、状态复制、树选择/扩展、随机 rollout、回传、动作提取和树析构。代码 search(N) 精确执行 N 次 step()，没有按胜利提前退出；已到终局的树路径可直接回传，因此并非每个 simulation 都新增一次随机 rollout。simulation 不是一个动作，也不是一个新对局。

样本：种子 1/2/3 用附带非战斗模型和 MCTS=2000 走完整局；取每个到达章节的首场战斗开局与第 8 次动作后的可决策状态（若尚未终局且多于一个合法动作）。共 16 个状态，覆盖第 1/18/35 层的 Cultist、Chosen、Spheric Guardian、Three Shapes、Three Darklings、Small Slimes。不是随机全分布，也没有专门覆盖 Boss、超长/复杂卡组。

每个状态预热 50 次原生 rollout + 100 次 MCTS；原生测 5×2000 rollout，每档 MCTS 测 5 次，共 80 次调用/档。Python 测每状态 100 次随机战斗。根状态检查排除 repr 中明确为 static 的全局 sum 计数，其他输出保持不变。

纯原生测速只新增 benchmark_native_rollouts 诊断绑定，调用与 MCTS 相同的 playoutRandom；未改搜索算法或战斗规则。完整差异更新至 simulator-local.patch。17 项原生规则回归仍通过。

复现：

```powershell
& D:\project\sts\.venv\Scripts\python.exe D:\project\sts\deployment\benchmark_speed.py
```

原始明细：speed_benchmark.json。脚本：benchmark_speed.py。结果不包括进程启动、模型加载、样本收集时间，不代表多进程总吞吐；不能直接与带神经网络叶评估的 STS2 MCTS 历史速度做公平倍数比较。
