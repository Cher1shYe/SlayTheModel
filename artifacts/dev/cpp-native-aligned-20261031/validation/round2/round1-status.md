# C++ 原生规则对齐：第一批修复

日期：2026-10-31。开发基线为 `origin/alphazero` 的
`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`，没有改动主工作区分支、提交或推送。
保留 C++ 执行内核，目标为本机探针实际使用的游戏 DLL：
`v0.111.0 / 41cef1ea`，SHA-256
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。

## 已完成

- 种子及随机数：xxHash64、64 位种子、Xoshiro256**、原生浮点与计数、玩家槽位 0、洗牌方向、弃牌稳定排序，以及地图中已确认的随机调用顺序。
- Cinder：18/24 伤害，随机消耗手牌，正确触发消耗后的抽牌。
- Anger：复制完整牌状态并分配独立身份，保留附魔及费用状态。
- Thrash：消耗前计算动态攻击值，保留小数成长，处理力量、虚弱、钢笔尖及 Gigantification 的结算时点。
- 七种遗物选择：Precise Scissors、Empty Cage、Biiig Hug、Precarious Shears、Preserved Fog、New Leaf、Astrolabe。新增删牌、变化、变化并升级选择；支持确认、重选、快照恢复。选择者由策略提供。
- Fragrant Mushroom：移除事件重复扣血，改为升级两张；致死后仍消耗相应 RNG，但不升级。Beautiful Bracelet：真实随机附魔四张符合条件的牌。
- 修正 Book of Five Rings 回血 20、相关战斗外伤害与复活顺序，死亡不会因离开事件而恢复到地图。
- ArmG feature v2 能识别新增选择及其后续扣血/诅咒。新 checkpoint 绑定环境身份；旧权重须显式迁移。
- 快照版本改为 5，旧二进制快照不能继续使用。

## 验证结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 实际原生 DLL 卡牌场景 | 12 个通过 | `native-card-fixtures/results.json` |
| 实际原生 DLL 遗物/选牌场景 | 15 个通过 | `native-run-fixtures/results.json` |
| 原生 RNG 数学对照 | 424 次混合调用，以及 hash/状态/边界向量通过 | `simulator/tests/fixtures/native_rng_41cef1ea.json` |
| C++ 回归 | 15 个程序全部通过，含 447 项原有规则、44 项卡牌、61 项局外对齐检查 | `validation/native-tests.json` |
| 快照/隐藏状态 | 6,861 个快照、6,000 次隐藏状态重采样通过 | 同上 |
| Python 接口、候选、身份与迁移 | 69 项通过 | `validation/python-integration.txt` |
| 整局冒烟 | 1,000 局正常终止，0 异常、0 截断 | `validation/benchmark-new-1000.txt` |

冒烟使用简单贪心策略，平均层数 9.6、胜率 0；测得约 **113.5 局/秒**。
原始参考版同类测量约 112 局/秒。随机数和规则变更后轨迹已不同，这只是同类工作负载的吞吐观察，不能解释为严格的同轨迹速度比较，更不是 MCTS 或神经网络训练速度。

上传的原始 `latest.pt` 保持不变。另生成
`validation/weights/armg-native-port-init.pt`，完整迁移来源见
`validation/weight-migration.json`；其新环境训练局数为 **0**。
实际权重已通过普通严格加载器，并在三类新选择上完成有限值前向推理
（`validation/weight-inference.json`）。这不证明新增选择已经学好。

## 当前边界与后续顺序

`NATIVE_PARITY_COMPLETE=false`。这一批是可运行的规则对齐开发版，尚未完成整局原生一致性验收。

1. 补齐 Golden Compass 黄金路径、Prismatic Gem 的其他角色牌池、Underdocks 替代第一幕等已知内容缺口；EVENT 池中仍有无效果/近似实现的遗物。
2. 对齐账号解锁、历史遭遇和全部内容池；随后做相同种子、相同选择下的长路径逐步原生对照。目前随机数原语一致不等于整局地图、奖励、抽牌已经完全一致。
3. 继续覆盖其他卡牌、附魔和遗物组合。当前 `double` 能保留已测试的小数伤害，但不是 .NET `decimal` 的全数域等价实现；相同 ID/升级等级的牌排序仍需更多身份敏感的夹具。
4. 牌组、牌堆、遗物数量仍有 C++ 固定容量。新增选择会在超容量前拒绝获得，避免死锁；这些容量限制本身并非原生规则。连续获得多个会打开选择界面的遗物也还需专门覆盖。

旧模型只能作为初始化；新环境上的胜率和训练收敛尚未测试。完整 PUCT 续训仍需要对应的战斗先验权重与配套输入，当前迁移文件不伪造这些状态。

## 使用与代码交付

当前独立副本包含所有修改。`validation/native-rules-port.patch` 是相对
`be401e8` 的源码补丁；`validation/changed-files.json` 列出文件及校验值。
补丁只包含源码、测试、文档与对照数据，不包含游戏 DLL、原生宿主程序或模型权重。
先在干净的该基线副本上运行 `git apply --check`，再由使用者决定应用；主工作区没有自动切分支或合并。

本机可用安装了 Python 开发头文件的环境重新构建：

```sh
python validation/build_local.py
python -m pytest -q tests/test_engine_checkpoint_identity.py tests/test_native_seed_identity.py tests/test_binding_schema_contract.py tests/test_card_grid.py tests/test_armg_features.py
validation/bench run 1000
```

也保留 `simulator/CMakeLists.txt` 构建入口，修正了 macOS 不适用的 MinGW 静态链接参数；本轮实际编译用的是 Apple clang 直接构建脚本，未验证 Windows 构建。
重新编译后必须重新启动 Python 进程，并显式迁移绑定旧二进制的 checkpoint。
迁移说明见 `docs/native-engine-checkpoints.md`；随机数接口变更见
`docs/native-rng-alignment-20261031.md`。
