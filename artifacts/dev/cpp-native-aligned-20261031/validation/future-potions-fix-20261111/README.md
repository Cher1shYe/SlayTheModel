# The Future of Potions：Event / Token 药水（ruleset v8）

日期：2026-11-11。起因：第三轮（0.2B + 分叉）在训练机上第 7 次更新时崩溃：

```
File ".../spire_rl/env.py", line 134, in step
    ok = self.rc.step(int(obs.cand_type[candidate]), int(obs.cand_index[candidate]))
RuntimeError: The Future of Potions reward pool is too small
```

## 原因

原生 `Models/Events/TheFutureOfPotions.cs`：

- 卡牌稀有度 `GetCardRarity`：Rare / **Event** 药水 → Rare；Uncommon → Uncommon；Common / **Token** → Common。
- 卡牌类型 `PotionToCardType`：每瓶药水从 [Attack, Skill, Power] 里 `Rng.NextItem`；Common / Token 药水先去掉 Power。
- 奖励：角色牌池里该稀有度、该类型的 3 张不同的牌，全部升级。

C++ 的药水表由 `simulator/tools/gen_potions.py` 生成，它把原生的 Event、Token、None 三种稀有度都写成 `Rarity::SPECIAL`。事件代码按 `Rarity::EVENT` / `Rarity::TOKEN` 判断，这两个值在药水表里从不出现，于是对这 4 瓶药水：

| 药水 | 原生稀有度 | 修复前 C++ 的处理 | 后果 |
| --- | --- | --- | --- |
| Foul Potion、Glowwater Potion | Event | 3 种类型、Common 牌 | 给了 Common 牌（应为 Rare）；抽到 Power 时铁甲没有 Common Power，`made != 3` 抛异常 |
| Potion Shaped Rock | Token | 3 种类型、Common 牌 | 抽到 Power 时抛异常（应只在 Attack / Skill 里抽） |
| Deprecated Potion | None | 同上 | 游戏中不会生成 |

铁甲牌池按（稀有度，类型）的数量：Common Attack 13、Common Skill 7、**Common Power 0**、Uncommon 16 / 14 / 9、Rare 8 / 9 / 10。所以只有“Common + Power”会失败，概率是持有上述药水并选它时的 1/3。Foul Potion 来自事件（一次给 3 瓶），Glowwater 来自事件，Potion Shaped Rock 来自遗物，所以平时少见；第一、二轮 16,001 局没有碰到。

## 改动

| 文件 | 内容 |
| --- | --- |
| `simulator/src/events.cpp` | 新增 `future_potion_native_rarity`：对表里是 SPECIAL 的药水按原生模型还原（Foul、Glowwater → Event；其余 → Token）。`future_potion_card_rarity` 与事件开始时的类型抽取都改用它 |
| `simulator/bindings/bindings.cpp`、`agent/engine_identity.py`、`PORT_SOURCE.json` | ruleset `native-41cef1ea-port-v8` |

没有改生成器和药水表（其他代码只把 SPECIAL 当作“不进随机药水池”和定价用）。Deprecated Potion 原生会在 `GetCardRarity` 抛异常；它不会被生成，这里按 Token 处理，只为保证事件不会失败，不是原生行为。

**规则与随机序列变化（需记录）**：持有 Foul / Glowwater 并在该事件中交出时，现在得到 Rare 牌（v7 是 Common 牌或崩溃）。持有 Potion Shaped Rock 进入该事件时，类型从 2 种里抽（v7 是 3 种），该事件之后的事件随机数序列与 v7 不同。其余情况与 v7 逐位相同（见下面 1000 局冒烟）。**按源码实现，未用目标 DLL 执行验证。**

## 验证（本机 macOS arm64，Command Line Tools clang，Python 3.11.18）

| 项 | 结果 | 文件 |
| --- | --- | --- |
| 复现（v7 构建，每种药水 200 个种子，持有 2 瓶并交出第 1 瓶） | Foul / Glowwater / Rock 各 68/200 抛出同一异常；Block Potion 0/200 | 见会话记录，脚本即 `probe.py` 的前身 |
| 修复后探针（v8，每种 300 个种子） | 6 种药水 0 异常；Foul、Glowwater → Rare 的 Attack 309 / Skill 303 / Power 288；Rock → Common 的 Attack 456 / Skill 444，无 Power；对照 Block（Common）、Clarity（Uncommon）、Cosmic Concoction（Rare）与其表中稀有度一致；900/900 张牌已升级，每次 3 张互不相同 | `probe.py`、`probe.txt` |
| C++ 全部回归程序（保留断言） | 36 个，0 失败 | `cpp-tests.json`、`cpp-logs/` |
| Python（torch 桩） | 167 通过、10 失败、34 错误，失败与错误集合与 `../nosl-fix-20261110/pytest-no-torch.txt` 逐项相同 | `pytest-no-torch.txt` |
| 1000 局贪心冒烟 | 1000 完成、0 错误、平均层数 9.6、5570 场战斗、85525 步，与 v7 记录相同（仅耗时不同） | `bench-1000.txt` |
| 地图对照 | 6/6 相同 | `map-parity.txt` |
| `model/spire_rl` 测试 | 45 项通过，含本事件的回归测试 `test_future_of_potions_accepts_event_and_token_potions` | 仓库根 `model/spire_rl/tests/` |

## 复现（副本根目录）

构建方法同 `../nosl-fix-20261110/README.md` 的“复现”节（Command Line Tools 包装脚本）。然后：

```sh
PY=~/micromamba/envs/sts2/bin/python
$PY validation/future-potions-fix-20261111/probe.py 300
$PY validation/future-potions-fix-20261111/run_cpp_tests.py      # 会重写本目录 cpp-tests.json 与 cpp-logs/
./validation/bench run 1000
```

构建后扩展 SHA-256：`fa3041fbea51ece6757f1f66c0dc9991e036b746bab06d8f4b3e0ffe5471de60`（本机，跨平台不同）。

训练机需要重新编译：`CXX=g++ python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py`，然后确认 `sts2_sim.ENGINE_RULESET_ID == "native-41cef1ea-port-v8"`。v7 的检查点（第二轮 `best.pt` / `last.pt`）在 v8 上会被 `checkpoint.load` 拒绝；第二轮的归档仍可读取（离线蒸馏、离线 critic 只读归档）。

## 未做

- 没有目标 DLL 的执行对照。
- 没有审计其他按 `Rarity::EVENT` / `Rarity::TOKEN` 判断药水稀有度的地方；`grep` 结果里药水相关的只有本事件这两处。
