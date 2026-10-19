# C# 采集后端 v2：扩展范围与现有生命周期接线

## 支持范围

当前明确准入六种未升级、无附魔／灾厄的牌：STRIKE_IRONCLAD、DEFEND_IRONCLAD、BASH、IRON_WAVE、POMMEL_STRIKE、TWIN_STRIKE；遭遇为 BYRDONIS_ELITE、NIBBITS_WEAK（单个 Nibbit）。随机牌组包含六种牌，再随机加入 4–8 张并打乱，初始 HP 从 40/60/80 选取。没有宣称支持全部 76 个遭遇。

直接复用原项目的 `expanded_mechanics.describe_card`、`expanded_entities.card_entity/pile_state`、`all_entities.enemy_entities`、实体序列化和现有 Learner。C# 不重写卡牌效果，调用原来的 Combat Solver。原生导出的卡牌费用与 Damage/Block/Cards 基础值必须与已有 Python 描述逐项一致，防止两个后端同名牌数值不同却被当作相同特征。完整原生 successor 对账负责实际结算；这不是把整场 Python 模拟器与 C# 模拟器判定为等价。

## 数据契约

- 每次决策独立捕获原生 live 状态，与搜索影子状态的特征、合法动作表严格比较。累计决策数来自实际执行输入，伤害计数来自实际原生历史事件。
- 非终局动作核对完整 continuation key；终局核对胜负、HP 和奖励。继续保留终局清理时完整 continuation 无法直接比较的边界，不把终局 HP 相同称为所有终局字段相同。
- 原生当前 intent 数值为权威；目前 Python 的 BYRDONIS 单次伤害登记仍与原生有差异，适配保留原生值。Nibbit 只准入能从当前回合／可见行动唯一还原的确定性循环，歧义拒绝。
- 原生把等效重复牌合并为合法动作类；映射核对费用、目标、实例状态键、动作覆盖与一一对应。零访问合法动作保留，访问数总和等于已完成模拟数，策略标签归一化。
- 每场牌组库存必须与配方一致、相邻 HP 连续；终局标签使用既有 V7 胜利 `.9 + .1 * final_hp / max_hp`、死亡 `-1`。未结束或被截断战斗拒绝入库。
- 搜索端先除后乘与 Python 标签先乘后除在部分 HP 下相差一个浮点末位。保留 `searchReward`，与标签差异必须 ≤ `1e-15`；标签自身与 Python V7 严格相等，不放宽状态、动作或实际奖励公式。
- `native-collection-v2` 回放与旧 observable 回放、v1 试点回放严格隔离。教师依然使用完整信息 rollout；模型输入不含抽牌顺序、原生状态指纹或 RNG。value head 接收终局标签，但未用于 C# 搜索叶子评分。
- 暂不准入升级、选牌、多怪、遗物、药水、玩家能力、星能、消耗／生成牌等。原 Python 已有实现是后续扩展参考，不等于 C# 采集适配已验证。

## 冻结验证集

`configs/az_native_xs_v2/protocol.json` 保存 24 个独立随机配方，每个遭遇 12 个；固定牌组、HP、种子、scenario_id 及整个清单的 SHA256。训练种子低于 10 亿，验证种子从 15 亿开始，两域不相交。训练按轮次／场次产生新配方并交替覆盖遭遇，不再复用少量固定牌组。

加载时核对内容清单、配方指纹、清单指纹、唯一种子／配方、分层数量与 split；验证数据禁止进入训练回放。验证始终为纯网络，候选与冠军采用同一冻结配方。尚未建立原生测试集，`--include-test` 会明确拒绝。

## 与 ALL runner 的接线

仍使用 `python -m sts2_env.az.all_runner`，由配置中的 `backend.kind=native-collection-v2` 选择后端；原配置继续走 Python 默认路径。新增后端只负责配方、采集、原生网络验证和专用回放，更新／逐更新恢复／冠军判定仍由原 ALL runner 负责。

- 每轮采集使用 `collection_model` 指定的 learner 或 champion；示例配置为 learner。候选未晋级也继续推进 learner，冠军保持原权重。
- 每场原子写入独立缓存，原生批次最多四场。失败续跑只补缺失场次；模型、代码、构建输入、搜索预算、协议或配方变化会拒绝旧缓存。
- 整轮采集成功才进入 pending/update；沿用 optimizer、sample RNG、torch RNG、更新历史的逐步 checkpoint。
- 基线验证前额外保存初始模型与初始化身份，基线验证失败也能 `--resume`。候选验证失败保留更新断点，恢复后不会重新采集或重复更新。
- 原生验证也逐场缓存，缓存同时绑定评估模型。原冠军晋级规则仍为完整验证、零拒绝、配对 bootstrap 95% 区间下界大于零。
- 原生路径目前单 worker，40 回合／100 决策是完整对局保护上限；超限是错误，不产生 time-limit 标签。`search.budget` 与 `backend.budget_ms` 必须相等，此后端单位是每次决策毫秒，**不是模拟次数**。不接受 learned/mixed leaf mode。
- `collection-cache/<轮次>/progress.json` 和各 `native-validation/<版本>/fights/progress.json` 在批次完成／失败时更新；每场 JSON 在战斗结束时落盘。没有定时监视任务。

## 复现入口

只做配置／配方检查，不启动战斗或训练：

```powershell
.\.venv-az\Scripts\python.exe -m sts2_env.az.all_runner `
  --config configs/az_native_xs_v2/config.json `
  --protocol configs/az_native_xs_v2/protocol.json --preflight-only
```

有界工程检查入口：4 场训练侧采集、完整 24 配方网络验证，可选两步更新及精确恢复检查；不调用正式多轮训练：

```powershell
.\.venv-az\Scripts\python.exe scripts/check_native_backend.py `
  --checkpoint '<现有 XS ALL/V7 模型>' --out 'output/<新目录>' --smoke-update
```

失败后使用相同参数加 `--resume`。省略 `--smoke-update` 不执行更新。修改源码之后不能沿用旧缓存，应新建目录。配置中的原生仓库与游戏路径需要匹配本机；首次实际调用自动构建正确 worker，不部署游戏 Mod、不启动可见 Steam。

本轮没有启动正式训练。测试与实际有界检查结果见下方验收记录。

## 本轮验收

- Release 原生 worker 构建及实际 headless 检查完成，输出 `output/native_backend_v2_verified_20261019/`。仅使用已有冻结模型与受限验收脚本，未启动正式 ALL 多轮训练。
- 4 场训练侧采集全部完成，生成 41 行；24 场独立验证全部完成，224 次决策。合计 265 次状态／动作检查，无契约拒绝。三种新增牌均实际打出；DEFEND 的合法动作与数值在新集检查，实际打出回归由旧原生夹具覆盖。
- 验证纯网络 21/24 胜，平均 V7 效用 0.7075；这是该受限冻结集的基线，不是学习增益或跨后端强度对比。
- 两步真实 Learner 工程更新完成，恢复 optimizer／sample RNG／torch RNG 后权重与更新历史精确一致，原冠军未变；没有对更新后模型运行晋级评估。
- 实际 `--resume` 复用全部 28 场，逐场文件、worker 日志及 checkpoint 的 SHA256 和 mtime 全部不变，新增更新为零。初次检查完整报告保存在 `first-run-report.json`，续跑检查为 `resume-check.json`；`report.json` 描述最后一次调用。
- `test_az_native_backend.py`、`test_az_native_pilot.py`、`test_az_training_improvements.py`、`test_az_leaf_modes.py`、`test_az_episode_cache.py`：**88 passed（50.24 s）**。覆盖记录轨迹、所有新增牌、数据腐坏、冻结集重复／泄漏、部分采集失败复用，以及原 runner 基线／更新／候选验证失败后的两轮恢复和冠军保留。故障注入用的是测试替身，不计入真实原生战斗数。
- C# `SlayTheModel.ReplaySearch.Smoke` 通过原奖励／超时／取消／续用与 PUCT 归一化、先验缓存、错误概率拒绝检查。配置 preflight 检查 160 个计划训练配方与 24 个验证配方通过，只构造／验证配方，不执行训练。
- 暴露并修复两个接线问题：旧种子整数校验上限过小；原生先除后乘与 Python 先乘后除的奖励舍入不同。实际最大差 `1.1102230246251565e-16`，没有改变奖励数学定义或原搜索评分。早期失败产物保留在 `native_backend_expansion_20261019` 与 `native_backend_expansion_final_20261019`，不计入最终通过结果。
