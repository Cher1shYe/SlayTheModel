# PARITY0001：真实原生开局记录

来源：`parity/stage/reports/opening/20261118T141057Z-PARITY0001-892e4e`，2026-11-18 14:10:57 UTC 的真实 HeadlessHost / v0.111.0 DLL HTTP 记录。不是模拟器生成样例。

铁甲、A10、新存档并解锁全部 epoch；输入种子 `PARITY0001`，原生规范化为 `PAR1TY0001`。具体进度上下文见 `config.json`。

| 决策 | 原生状态 | 随后明确选择 |
| --- | --- | --- |
| 0 | Neow：New Leaf / Golden Pearl / Silken Tress | Golden Pearl |
| 1 | 金币 249，独立 Proceed 选项 | Proceed |
| 2 | 地图 | 前往 (0,1) |
| 3 | `ENCOUNTER.TOADPOLES_WEAK`，两个 Toadpole | 停止，没有继续出牌 |

捕获时前三个决策在已覆盖的状态/动作子集上通过；第四个决策发现当时模拟器选择了 SEAPUNK，且适配器尚不支持多敌人，所以停止。`summary.json` 是当时结果，不是当前模拟器应当持续返回的结果。

修正规则与位置契约后，离线回归现已逐项比较这四个决策，全部在已支持子集上吻合，首战两只 Toadpole 血量为 25/26。该回归尚未覆盖出牌后的战斗状态或完整观察。

六份来源 JSON 按字节复制。`manifest.json` 的校验和用于验证保真；GUID等执行路由信息未删改。后续改模拟器或适配器不能据此改写原生期望值。`actions.json` 是根据真实执行记录单独整理的可重放语义动作序列。
