# ArmG 局外实机接入

组合版 Mod 接入从局外真实观察到 ArmG 的异步推理，并使用游戏内原有的战斗 MCTS。局外网络开启时，单人战士的普通卡牌奖励和地图选择使用 ArmG；商店、事件、休息点、多选、未知卡牌和缺少必要状态的界面由原有 `first-legal` 策略自动处理。原控制器未识别的界面仍可能需要人工处理，完整整局尚未实机验收。

真实观察不能完整还原模拟器的地图节点顺序、Boss、事件及遗物计数等特征。评分使用明确标记的近似编码，不能视为模拟器评测结果；历史采样没有候选牌升级信息，离线样本中补零仅是测试假设。真实场景尚需在游戏中验收。

游戏未运行时，在 PowerShell 中执行：

```powershell
cd D:\project\sts2_compactformer\sts2_datacollection\SlayTheModel
.\scripts\launch-installed-armg.ps1
```

建议写入已配置的采集目录 `latest-armg-suggestion.json`，包含当前动作、分数、近似标记与缺失项；以现有游戏配置中的 `SLAY_THE_MODEL_EXPORT_DIR` 为准。本次为保留已有配置，采集目录仍是 `D:\sts2_datacollection\SlayTheModel\artifacts\live-capture`。模型不支持、出错或超时时，控制器会从当前合法动作中选择 first-legal。

游戏右上角在 MCTS 按钮下方另有“局外网络”按钮，可独立开启或关闭 ArmG，状态会保存；关闭网络后局外继续使用 first-legal，战斗 MCTS 不受影响。启动脚本默认采用 `auto` 和允许近似。如需只看建议，可使用 `-Mode shadow`，此模式需要玩家处理可由网络评分的界面。实际执行前会检查请求 ID、状态指纹和合法动作。

当前安装基于 `artifacts/armg-network-combined-auto-20261031` 的组合 DLL；此项目的普通 `scripts/windows.ps1 -Action Install` 会覆盖组合安装及其配置，不要用它覆盖组合安装。原 `sts2-native/scripts/play.ps1` 也不接受 `armg` 策略参数，使用本页启动脚本或直接通过 Steam 启动。原安装 DLL 和 runtime 配置保存在组合产物目录的 `installed-backup-*`。SDK 9.0.306 位于 `C:\Users\15808\.codex\tmp\sts2-armg-sdk\dotnet`，构建时可将该目录临时加入 PATH。
