# 高速模拟器第六轮审计修复结果（2026-10-29）

## 结论

第六轮审计报告的 8 组问题已经处理。修复后，原 36 项探针全部通过；正式原生规则回归
从 233 项扩展到 288 项，并全部通过。扩展后的旧审计探针、bounds 插桩矩阵、5,340 场遭遇
扫描、300 局整局扫描、1,000 局随机整局扫描和 Python 套件也未发现新的可复现失败。

本轮最终检查到的正常三幕 Power 为 27 个，均存在生产代码调用路径；109 个可执行遗物也
均存在 allow-list 之外的运行路径。`BACK_ATTACK_LEFT`、`BACK_ATTACK_RIGHT` 和 `MINION`
按反编译参考是标记型 Power，没有自身回合钩子。

该结论覆盖本轮 C# 对照、状态不变量、动作合法性和确定性重放，不等同于真实客户端逐步
差分。项目原有的近似事件、部分近似遗物、已知牌顶 16 张观察容量和 200 回合保护仍属于
已披露限制。

## 修复内容

### 卡牌与伤害

- 9 张无色攻击牌改为 `attack_from_card`，恢复 Pen Nib、卡牌加伤和倍率等 `FromCard`
  链路。
- Mummified Hand 只把本地费用大于 0 的牌作为目标；X 费牌不会再变成固定 0 费。空候选时
  仍按参考消耗一次 CombatCardSelection 查询。
- HardToKill、Slippery 和 Intangible 按参考在格挡前取最小伤害上限；Slippery 在非零伤害
  结果后减层。
- Galvanic 在战斗开始和卡牌进入战斗时施加，打出 Power 牌后按层数对玩家造成 Unpowered
  伤害。

### 怪物生命周期与 Power

- Axebot Stock 原位重生并递减 Stock。
- PhrogParasite Infested 死亡后生成 4 个初始眩晕 Wriggler。
- Decimillipede 在仍有存活分段时进入 Reattach 流程，按 25 点治疗复接。
- ThievingHopper 在第 5 次行动 Escape 后移除并正确结束单怪战斗。
- Door 半死时生成 Doormaker；Doormaker 第三次行动回到 Door，Door 复活、强化并移除
  Doormaker。
- 实现 PaperCuts、Territorial、Rampart、Slumber、VitalSpark、PersonalHive、
  Imbalanced/BowlbugRock、CrabRage、PossessSpeed 和 PossessStrength。
- 修正 minion、复活和半死实体不应错误结束战斗的条件。

### 观察与 RNG

- 公开观察新增 Automation 每实例剩余/金额、Hardened Shell 本回合已损失量、
  `unblockedHitsThisCombat` 和 `cardsPlayedThisCombat`。
- 动作特征新增 Galvanized、战斗历史计数、Automation 进度和目标 Shell 进度。
- 公开观察升级为 schema v7，动作升级为 schema v6；旧 checkpoint 会被拒绝。
- 战斗使用 Shuffle、CardGeneration、PotionGeneration、CardSelection、EnergyCosts、
  Targets 和 MonsterAI 独立流，并从整局 `RunRngSet` 续接、回写。
- 不再为了制造 battle seed 而额外推进 MonsterAI 或 PotionGeneration。

### 遗物与房间

- MembershipCard 对商店价格应用 50% 折扣。
- TheCourier 应用 80% 折扣、购买后补货，并在从商店获得时立即更新其余商品价格。
- LavaLamp 在无符合条件伤害的战斗后升级所有可升级卡奖励。
- Planisphere 每次进入原地图点类型为 UNKNOWN 的房间治疗 4。

## 验证结果

| 检查 | 结果 |
|---|---:|
| 第六轮定向探针 | 36 / 36 |
| 正式原生规则回归 | 288 / 288 |
| 第二轮探针 | 32 / 32 |
| 第三轮探针 | 41 / 41 |
| 第四轮探针 | 30 / 30 |
| 第五轮探针 | 58 / 58 |
| 全部卡牌组合矩阵 | 43,056 场、844,399 步、0 failure |
| 遗物/药水矩阵 | 12,532 场、308,946 步、0 failure |
| 遭遇扫描 | 5,340 场、189,617 步、0 failure、2 capped |
| 整局扫描 | 300 局、19,149 步、0 failure、0 capped |
| 随机整局与快照重放 | 1,000 局、194,346 步、5,740 快照、0 error |
| Python `pytest tests -q` | 83 passed, 1 skipped |
| Sozu + 战斗外 Entropic Brew | 3 秒内正常返回 |
| 正常三幕 Power 静态调用检查 | 27 / 27 |
| 可执行遗物运行路径检查 | 109 / 109 |

## 路径

- 项目：`D:\sts2_datacollection\sts2`
- 反编译参考：`D:\project\sts2_compactformer\sts2-rl-agent\decompiled`
- 第六轮基线报告：`D:\sts2_datacollection\sts2\docs\simulator-deep-audit-round6-2026-10-29.md`
- 第六轮探针与结果：`D:\sts2_datacollection\sts2\.scratch\deep-audit-round6-20261029`
- 正式规则回归：`D:\sts2_datacollection\sts2\simulator\tests\rules_regression.cpp`
- Python 测试：`D:\sts2_datacollection\sts2\tests`
- 静态覆盖检查：`.scratch\deep-audit-round6-20261029\static_coverage.py`
- 静态覆盖结果：`.scratch\deep-audit-round6-20261029\static-coverage.txt`
- 最终源码指纹：`.scratch\deep-audit-round6-20261029\source-hashes-final.json`
- 最终随机整局结果：`.scratch\deep-audit-round6-20261029\run-fuzz-final.txt`
- 编译器：`D:\sts2_datacollection\sts2_datacollectiontoolchain\Library\bin\x86_64-w64-mingw32-g++.exe`

## 复现命令

```powershell
Set-Location 'D:\sts2_datacollection\sts2'
& '.\.scratch\deep-audit-round6-20261029\reproduce.ps1'
& '.\.scratch\deep-audit-round4-20261028\reproduce.ps1'
& '.\.scratch\deep-audit-round5-20261028\reproduce.ps1'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round2-20261028\run_fuzz.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round6-20261029\static_coverage.py'
& '.\.venv\Scripts\python.exe' '.\.scratch\deep-audit-round5-20261028\timeout_check.py'
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

第四轮脚本当前还会构建并运行正式规则、第二轮、第三轮、第四轮探针以及两个 bounds
矩阵；第五轮脚本运行 5,340 场遭遇扫描和 300 局整局扫描。

## 仍保留的已披露限制

- 事件和部分遗物仍是反编译驱动的近似实现。
- 已知牌顶公开观察只完整编码前 16 张，但始终编码实际计数。
- 200 回合保护会在异常超长战斗中判负。
- 本轮没有真实客户端逐步差分 oracle，也没有重新训练或比较模型胜率。
- 观察/动作布局升级会使旧 checkpoint 不兼容，需要按 v7 / v6 重新训练。
