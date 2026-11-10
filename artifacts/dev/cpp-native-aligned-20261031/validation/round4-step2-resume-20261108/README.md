# 第二部分恢复工作记录（2026-11-08）

接续 `docs/native-port-step2-wip-20261031.md` 的断点。仍是 **WIP**：C++ 已闭环，Python 扩展、Python 回归、快照/观察接口版本升级和整局冒烟都未完成。

## 结果

- 33 个 C++ 程序全部通过（`cpp-tests.json`、`cpp-logs/`），回归断言开启。
- 三个新角色的原生差分：静默猎手 240 例 / 242956 项、故障机器人 176 例 / 193195 项、亡灵契约师 198 例 / 3357 项，均 0 失败。
- 原生样例结果文件未修改。
- 储君没有原生样例，`regent.cpp` 仅按原生源码实现，未经差分验证。

## 第一段（同日 19:35–20:17 会话）

- 新增 `simulator/src/regent.cpp`：星星费用、锻造、Void Form、Conqueror、Reflect 等。回合开始改为可恢复的分阶段流程；三角色选牌接入 `resolve_choice`，未知选牌类型直接报错。
- 三角色伤害、格挡、可打出、抽牌、能量、初始化钩子接入主流程；生成牌通知区分是否由玩家生成。
- 修复：卡牌 UID 分配、Ruined Helmet、Grapple 减益标记、怪物 Ritual 首回合时序、回合结束弃牌顺序及 Well-Laid Plans / Blur / Tools of the Trade。
- 测试侧：第三轮变量表重新生成、Quest/Tank 表补充、两个旧测试按队列语义更新、故障机器人卡名映射、亡灵契约师种子推导。

## 第二段（本记录）

引擎规则（均按 v0.111.0 原生源码）：

- `draw_cards` 维护嵌套层数：Scrape 只弃自身抽到的牌。
- 随机插入抽牌堆（`CardPilePosition.Random`）改用洗牌随机流 `Rng.Shuffle`，位置从牌堆顶计数。**影响铁甲**：怪物塞入抽牌堆的状态牌、Metamorphosis 等的随机序列会变化。
- 从抽牌堆手选（`FromCombatPile`）不再消耗选择随机流；候选按卡牌 ID / 升级 / uid 排序，不暴露牌堆顺序。
- 选择必选且候选数 ≤ 必选数时自动全选（原生 CardSelectCmd 规则；抽牌堆从顶往下，其余按牌堆顺序）。**影响铁甲**：Armaments、Headbutt、Burning Pact 等只有一个候选时不再出现只有一种结果的决策步骤。目前只在出牌循环内生效，见下方缺口。
- `card_has(CF_ETHEREAL)` 识别加上的虚无（Ghost Seed、Music Box 复制、Sculpting Strike）。
- White Noise 随机能力牌排除基础/Ancient/事件稀有度（如铁甲 Corruption）。
- Quasar 改为整池洗牌后取前 3 张。
- Delay、Invoke、Outmaneuver、Relax 改用原生的下回合能量/抽牌能力。
- Enfeebling Touch 改为真实 `ENFEEBLING_TOUCH` 临时减力量能力（敌方回合结束还原）；Misery 按原生规则复制临时减力量。

测试装载修正（不改原生结果）：

- 故障机器人/亡灵契约师：原生把 X 费记为 0；C++ 以 -1 表示，装载和比较按此对应。
- 故障机器人：样例布置时的"本次打出前"费用变化（Rocket Punch）装入；邪教徒初始意图改为原生首招 Incantation（增益）。
- 亡灵契约师 redirect_buffer：原生 before 快照已含 Buffer，不再重复添加。
- rules_regression / enchantment_contract：单候选场景按自动全选更新，并新增多候选与单候选两种检查。

## 第三段：版本与观察布局升级

- 版本：ruleset `native-41cef1ea-port-v5`、公开观察 v14、动作 v13、快照 v9、ArmG 特征 5。旧权重/快照会被明确拒绝，没有迁移适配。
- 选择类型独热编码从 13 类扩到全部 23 类；此前新增的角色选择在观察和动作特征里都编成 0，无法区分。
- 卡牌特征与卡牌实例特征各补 4 项：额外格挡、本回合保留、本回合 Sly、本战斗 Sly。
- 战斗观察末尾追加 111 维公开角色状态：角色独热、充能球（类型+数值）和槽位、故障机器人计数、Osty 存在/血量/力量/虚弱/易伤及相关计数、星星与储君计数、静默猎手计数。
- 新维度：公开观察 71232（战斗 47626、局外 23606），卡牌特征 629，动作特征 727。上一版分别为 46082 / 29691 / 251 / 343；增量主要来自卡牌词表从 223 扩到 597。
- 新增 `simulator/tests/observation_v14_character.cpp`；`native_seed_integration`、`native_step1_state_contract` 按快照 v9 和新尾段更新；Python 两个 schema 测试更新期望值，`agent/armg_train.py` 的观察版本检查改为 14（局外第 8–10 位含义未变）。
- 快照仍是 POD 整块复制，新角色状态会原样保存；`snapshot_battle` 的字段校验尚未覆盖新状态。
- 1000 局贪心冒烟（`bench-1000.txt`，版本升级前）：0 异常、0 截断，平均 9.4 层，约 172 局/秒；单步战斗耗时由 1.1 µs 升至约 2.5 µs。

## 第四段：Python 扩展与不依赖 torch 的测试（同日 22:40 会话）

- 用 `~/micromamba/envs/sts2/bin/python validation/build_local.py` 完整构建，生成 `simulator/sts2_sim.cpython-311-darwin.so`。numpy 2.4.6、pytest 9.2.0。
- C++ 回归重跑：35 个程序全部通过（`cpp-tests.json` 已按本次构建重写）。
- 整局冒烟（版本升级后）：`bench-1000-v14.txt`，1000 局、0 异常、0 截断、平均 9.4 层、约 172 局/秒、2.5 µs/步，与升级前一致。
- Python 全目录（`python-no-torch/full-suite.txt`）：167 通过；34 个文件收集失败、9 项失败均为缺 torch；另 1 项 `test_native_rule_regressions` 去 `simulator/rules_test` 找 cmake 产物，本机构建产物是 `validation/rules_regression`，直接运行为 453 项、0 失败。
- 第一部分核心选集中不依赖 torch 的部分见 `python-no-torch/core-selection.txt`（修正前记录）。
- 修正 `tests/test_native_step1_state.py` 两处过期期望（原文件备份 `python-no-torch/test_native_step1_state.py.before`）：Crimson Mantle / Inferno 三个值在 v14 后面接了 111 维角色状态，改为取尾段之前的 3 位；快照版本期望 8→9，被拒绝的旧版本 7→8。引擎和原生结果未改。
- 未跑（需 torch）：`test_engine_checkpoint_identity`、`test_armg_features`、`test_armg_native_bridge`、`test_armg_floor_*` 等 ArmG/训练相关测试，包括引擎身份绑定检查。

## 已知缺口

- 自动全选尚未覆盖出牌循环以外的选择：回合流程（Stratagem）、药水、遗物独立入口。
- 抽牌堆选择候选的原生 UI 排序是 Rarity、Id；C++ 只是动作编号顺序，桥接如依赖位置需要核对。
- `nextTurnEnergy` / `nextTurnDraw` 字段已无卡牌写入，仍在观察布局中，待布局统一时处理。
- Royalties 需改局外奖励结构，未实现。
- Dark Shackles 仍用通用 `tempStrengthLoss`，没有独立可见能力。
- Python 扩展：已在新环境 `~/micromamba/envs/sts2`（Python 3.11.18，conda-forge）构建，见第四段。torch 尚未装好，依赖 torch 的测试未跑。

## 复现

```sh
python3 validation/build_local.py              # C++ 部分可完成；Python 扩展一步需要带头文件的 Python 3.11
python3 validation/round4-step2-resume-20261108/build_one.py native_step2_defect   # 仅重链单个测试
python3 validation/round4-step2-resume-20261108/run_cpp_tests.py                   # 会重写本目录日志
```
