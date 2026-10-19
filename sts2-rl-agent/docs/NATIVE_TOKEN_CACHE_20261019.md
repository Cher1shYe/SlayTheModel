# Token哈希缓存与叶评估重复率（2026-10-19）

## 实现

`sts2_env/az/native_transformer.py` 的 `token_ids(token, buckets)` 使用65536项上限的LRU，只缓存不可变字符串到两个哈希桶ID的映射。桶数属于键；不缓存数值特征、张量、模型输出或校验结果。`validate_packed` 仍每次执行，动态数值照常编码，schema/模型权重未变化。

`scripts/native_pilot_service.py` 支持 `STS2_TOKEN_HASH_CACHE=0/1`，默认1。该开关只供同源码的性能消融，不关闭任何输入/原生契约。服务原有CPU单线程、确定性算法和模型eval保持不变。

可选 `STS2_LEAF_REPEAT_STATS=<绝对JSON输出路径>` 在进程正常结束时输出诊断。`LeafRepeatStats` 每次根策略请求开启新决策统计，以完整packed输入JSON（保留列表、字典顺序、schema及decisions字段）判定重复，模型身份在报告中固定。排除携带expected的根特征对账请求；同一决策最多保留4096个不同输入，超限明确记untracked而不伪造命中。统计每次叶请求，包括截止时可能未进入MCTS回传的最后请求，不等同于完成模拟数。统计没有复用价值结果，也没有将同HP或不同深度合并。

默认不统计，避免JSON判重影响生产计时。统计诊断运行的inferMs包含诊断开销，不能与正常计时直接比较。本轮只实现潜在命中率测量，未实现叶价值缓存。

## 测试

107 passed（39.02秒）：新增 `test_native_inference_cache.py` 加上原先 feature_regression、az_native_generic、native_collection_cache、az_native_backend、az_native_leaf 五套测试。新增覆盖三个轨迹所有输入、policy/value两种编码下缓存开关前后全部张量精确相同；暖缓存后错误schema仍拒绝；不同桶数不混用；叶统计区分decisions/HP变化、跨决策清空及容量溢出。

原生使用上一轮已构建的隔离DLL：`output/az_native_ic138_w4_20261019_174426.control/decision-root-benchmark/source/artifacts/native-host/`。本轮无C#修改或重编译，共享DLL未替换。三个固定轨迹seed2000228、37005、2000291，实机特征、完整后继、选择及终点严格校验保持开启。汇总另断言所有A/B轨迹observation/执行动作/自动选择数/HP/终局完全一致，最终完整continuation相同。诊断产物不进入训练缓存。

## 250ms串行ABBA

两组均开启决策点快照复用。唯一对照因素为token哈希缓存关闭/开启。XS、initial.pt、CPU推理、mixed=0.5、250ms；同模型SHA256为 `012b363254bbb79f8e6d08e7f06d84d8c2581f21df661b15c2c75047c7622dc4`。每组34个需要搜索的决策点重复两遍，共68次；强制动作不纳入均值。性能运行关闭叶重复统计，无并发pytest或训练任务。

| 指标 | 缓存关 | 缓存开 |
| --- | ---: | ---: |
| 平均完成模拟数/决策 | 97.43 | 101.35 |
| 模拟数中位数 | 57 | 62.5 |
| 按决策等权平均深度（动作边） | 2.6651 | 2.6988 |
| 按模拟次数加权深度 | 2.3737 | 2.4077 |
| 单次inferMs（张量构造+模型计算） | 2.1244ms | 1.8322ms |
| 单次encodeMs | 0.3545ms | 0.3571ms |
| 每决策实际计时 | 251.83ms | 251.61ms |

模拟数平均增加4.03%，深度增加1.27%；不是大幅加深。inferMs降低13.75%，其中包含哈希/张量构造，不应称为纯神经网络加速。三场景模拟均值分别88.75→91.86、113.07→120.00、98.35→101.54。

ABBA各轮模拟均值：A1=96.68、B1=103.85、B2=98.85、A2=98.18；配对增益约7.4%和0.7%，有波动，不把4%当作稳定保证。对应inferMs每调用2.1137、1.8415、1.8230、2.1352ms。只报告本轮配对；本轮关闭缓存的基线已明显快于上轮快照实验，不能把跨轮59→101的变化归因于token缓存。单worker无头结果，不外推四worker或可见游戏表现；未测GPU、胜率或自由执行策略质量。

## 叶评估潜在命中率（独立诊断）

| 场景 | 请求 | 重复 | 比率 |
| --- | ---: | ---: | ---: |
| 历史/生成费用 | 622 | 86 | 13.83% |
| 终局选择 | 354 | 78 | 22.03% |
| 回合选择器 | 665 | 45 | 6.77% |
| 总体 | 1641 | 209 | 12.74% |

untracked=0。token哈希缓存（含根策略与严格特征对账请求）547490命中、581未命中，命中率99.894%；三个进程最终分别222、126、233项。哈希命中率高不等于总耗时下降同等比例。叶重复输入约12.7%，未来可考虑只复用learned value；启发式奖励及原生完整状态校验不能用这个输入键代替。该比例来自启用统计的有限轨迹，不是全训练集保证。

## 复现和保留检查

控制目录 `output/az_native_ic138_w4_20261019_174426.control/`：

- `compare_token_cache.py benchmark`：顺序A1/B1/B2/A2，写 `decision-root-benchmark/token-{a1,b1,b2,a2}-{history,terminal,selector}/`。
- `summarize_token_cache.py`：轨迹对账与 `token-summary.json`。
- `compare_token_cache.py stats`：三个额外诊断，写 `token-stats-*/leaf-stats.json`，汇总为 `token-repeat-summary.json`。
- 每个目录保留job.json、worker.log、replay.json。脚本绑定本地配置与隔离构建，已有目录拒绝覆盖；再次复现应更换输出前缀及汇总路径。

`token-cache-preservation.json` 保存运行前清单，结束后66个state/checkpoint文件SHA256逐个相同，collection-cache/native-validation下1618个文件路径集合、大小和mtime_ns相同（缓存此项是元数据检查，不宣称逐文件内容hash）。原始模型、更新断点、运行配置与identity没有迁移或初始化。未重启训练，原候选验证root mismatch仍是独立待修问题。
