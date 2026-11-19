# PARITY0001：真实原生首战完整轨迹

来源：`parity/stage/reports/first-combat-fixed/20261118T142940Z-PARITY0001-980679`，2026-11-18 14:29:40 UTC 的真实 HeadlessHost / v0.111.0 DLL HTTP 记录。动作文件原样取自 `parity/stage/first-combat-actions.json`。不是模拟器生成样例或训练模型对局。

铁甲 A10，输入种子 `PARITY0001`（原生规范化为 `PAR1TY0001`）。新存档、全部 epoch 解锁；完整模拟器进度上下文在 `config.json`。

轨迹经过 Neow 选择 Golden Pearl、独立 Proceed、地图 (0,1)、两只 Toadpole 的首战。**决策 0–23 共24个决策、24个明确动作**在当时支持的公共状态/合法动作子集上通过在线对照，包括击杀第一只怪后剩余敌人的原生目标序号压缩。

`decision-0024-native.json` 是战斗结束后的 `NRewardsScreen`；双方玩家均为 **51/80 HP、249金币**。奖励界面尚未支持，工具按约定停止，**没有领取、跳过或代选任何奖励**。因此 `summary.json` 的最终状态是 `unsupported`，不是整局成功或完整观察吻合。

25份原生状态、config、summary、actions均按字节复制，`manifest.json` 给出来源和 SHA-256。不要为迎合模拟器改写原始记录。离线回归逐项核对24个决策后，只断言最终双方都到奖励页及血量/金币，不扩展奖励动作支持。
