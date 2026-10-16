# G1.5：生成、变形与已知堆底

2026-10-11。工程回归、两轮 smoke、双 seed 各三轮、最终测试与产物统计复算全部完成，双 seed 学习增益通过。本批为快速工程验证，不代表 G1 全部完成或通用策略质量验收。

## 冻结范围

- Primal Force／Primal Force+：将手牌中的攻击逐位置替换为 Giant Rock／Giant Rock+；结果升级由来源 Primal Force 决定，旧攻击的升级、临时费用不转移。
- Reave／Reave+：攻击后向抽牌堆底生成 Soul／Soul+；致死短路不凭空记生成事件。
- Soul／Soul+：零费抽 2／3 张并消耗；可抽过未知中段、已知堆底并继续洗牌。
- Giant Rock／Giant Rock+：1 费单体攻击，16／20 基础伤害，可继续被 Armaments 升级或再次变形。

初始池 28 个 ID，加 2 个仅生成 token，共支持 30 个 ID、60 个升级变体。初始牌组禁止 Soul、Giant Rock。原有 7 种单敌、6 家族、126 层保持不变；cycle 必含 Reave，strength 必含 Primal Force，其他非 starter 家族允许抽到二者。

Reave 属于 Necrobinder；本批审计它的独立伤害／生成机制，在 Ironclad 场景中受控混合，不接入 Necrobinder 角色、Osty 或 Doom。随机卡池、随机变形、其他生成来源、任意能力与遗物仍不在本批范围。

原生依据：`sts2_env/cards/ironclad.py`、`necrobinder.py`、`status.py`、`core/combat.py`；对照 `decompiled/MegaCrit.Sts2.Core.Models.Cards/{PrimalForce,GiantRock,Reave,Soul}.cs` 与 `MegaCrit.Sts2.Core.Commands/CardPileCmd.cs`。后者生成入牌堆的默认位置为 Bottom；CardModel 的战斗手牌可变形。依赖审计针对这些效果，不扩张为完整原游戏一致性声明。

## 状态与隔离

`CardTransformation` 独立记录决策号、手牌位置、旧 token、新 token 和原因。守恒检查按时间合并生成、升级、变形：生成增加一张，升级和变形减去旧 token、加入新 token；重复牌和再次变形分别记账。变形不等于额外生成一张牌。历史来源校验拒绝未登记变形、缺失来源和错误升级结果。

Reave 生成记为 `reave-soul-v1`，目标 `draw_bottom`，与旧 Anger 记录区别；每次至多生成一张，所以初始最多 20 张、400 个决策的总卡牌上限仍为 420。手牌一次最多变形 9 张。

公开记忆保存互不重叠的堆顶前缀和堆底后缀；整个剩余牌堆已知时合并成一个前缀。抽牌只根据旧公开组成、动作与新可见手牌推导消费位置，未知中间顺序不进入观察。抽空并洗牌后旧位置失效。粒子固定前缀／后缀，仅打乱未知中段。Soul、Headbutt、保留容量、Burning Pact 选择后抽牌均走同一语义。

剩余 Stomp 仍依据公开攻击历史恢复临时费用；Primal Force 可把它变成 Rock，但没有新生成 Stomp 的来源。Purity 继续使用上一批完整集合动作，保留一次提交、原生结算的循环修复。

## 版本与运行预算

- content：`g1-morph-v1`；information：`morph-information-v1`；encoder：`az-morph-encoder-v1`。
- 卡词表 61（含 PAD），卡特征 24，numeric 1744，动作仍 `combat-set512-v2`／512。
- Reward v3 不变；network-only 晋级，search 只观测。独立随机初始化，无旧权重迁移。
- train seed `[13*2^27,14*2^27)`；validation／test master 183／281，新目录、新 Replay、新测试。旧模型、数据、编码与报告保留。
- 两轮 smoke 后，双 seed 各 3 轮，每轮 126 场、16 更新、batch 64，训练／search 8 simulations。network 晋级 256 场配对验证，最终测试每 seed 150 场。不因无增益增加轮数。

```powershell
.venv-az/Scripts/python.exe scripts/prepare_az_morph.py
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --morph --quick --smoke --iterations 3 --output output/az_g1_morph_v1_smoke --workers 8
.venv-az/Scripts/python.exe scripts/run_alphazero_continuous.py --morph --quick --iterations 3 --output output/az_g1_morph_v1_quick --workers 8 --smoke-evidence output/az_g1_morph_v1_smoke/smoke_report.json
.venv-az/Scripts/python.exe scripts/verify_az_continuous_results.py --directory output/az_g1_morph_v1_quick --output docs/az_morph_verification.json
```

## 验证范围

`tests/test_az_morph.py` 覆盖 126 层完整战斗逐步真实／粒子对齐、串并行采样与 Replay 学习、反复变形和升级顺序、Stomp 属性清除、Anger 守恒、Purity、不同 Soul 升级的堆底顺序、Headbutt 前后缀并存、隐藏中段扰动下搜索不变、空堆规范化、抽穿堆底后洗牌、保留满手导致的实际抽牌限制、致死生成短路、伪造来源／位置拒绝、版本及 seed 隔离。全量回归另含历史 AZ 与适用 Ironclad、Necrobinder 原生效果测试。

定向测试先通过 135 项；新增边界用例 3 项另行通过。最终全量回归包含全部 138 项新测试，详细日志与正式实际结果在下方记录。

## 已完成结果

全量回归 **2,364 项测试及 8 个子测试通过**，267.19 秒，见 `az_morph_tests.txt`。旧批次冻结 encoder schema 保持一致。

两轮 smoke 通过：252 场、3,654 决策、8 更新；采样 36.48 秒、6.91 场／秒。线性估计正式训练 8.13 分钟、不含最终测试；后续策略与对局长度变化，实际正式运行含最终测试为 **684.07 秒（11 分 24 秒）**，不含开发、测试、smoke 和复算。所有运行已完成，不重新启动。

| seed | 轮数 | 场数 | 决策 | 更新 | 晋级次数 | 最终模型 |
|---|---:|---:|---:|---:|---:|---|
| 42 | 3 | 378 | 6,575 | 48 | 1 | candidate-0.pt |
| 43 | 3 | 378 | 6,567 | 48 | 2 | candidate-1.pt |

共 756 场、13,142 决策、96 更新。seed 42 后两轮、seed 43 第三轮未达到 network 晋级门槛，保留已有冠军，不以 search 改善替代晋级条件。

### 训练机制覆盖

| 观察计数 | seed 42 | seed 43 |
|---|---:|---:|
| Primal Force（含升级）出牌 | 84 | 73 |
| 已观察到的牌变形数 | 153 | 137 |
| Reave（含升级）出牌 | 75 | 74 |
| 已观察到的 Soul 生成数 | 69 | 67 |
| Giant Rock（含升级）出牌 | 92 | 73 |
| Soul（含升级）出牌 | 25 | 26 |
| 带已知堆底的决策 | 216 | 221 |
| 最大已观察堆底张数 | 2 | 1 |
| Purity 集合提交／已观察退出选择 | 73／73 | 76／76 |

两组训练均无超时。两个 seed 都实际打出了全部四种新 ID 的普通版和升级版。生成／变形计数来自决策前公开记录，不推断终局后的未记录事件；不要求出牌次数与生成数相等，致死攻击会短路生成。覆盖证明链路使用过这些机制，不等于已学到最优变形或抽牌策略。证据见 `az_morph_mechanism_evidence.json`。

### 最终测试

每行 150 场，search 为 8 simulations，仅作观测。

| seed／模式 | 初始胜率 | 最终胜率 | 超时率 | 平均决策 | 最终平均效用 |
|---|---:|---:|---:|---:|---:|
| 42 network | 70.7% | 79.3%（119/150） | 0 | 16.76 | 0.5506 |
| 43 network | 1.3% | 78.0%（117/150） | 0 | 15.10 | 0.5276 |
| 42 search | 22.7% | 35.3%（53/150） | 0 | 18.66 | -0.2785 |
| 43 search | 0.7% | 34.7%（52/150） | 0 | 17.61 | -0.2888 |

所有正式验证、初始／最终测试、两模式均 **0 异常、0 非法动作、0 超时**，检查记录见 `az_morph_timeout_checks.json`。最终 network 单场最多 33／28 次决策，search 为 42／34。随机合法基线胜率 34.7%；旧规则基线不适用。低预算 search 仍明显弱于 network，不将其改善设为晋级条件，也不称为高预算搜索成绩。

network 效用差 95% 区间分别为 `[0.12582, 0.19287]`、`[1.45449, 1.51924]`；胜率差区间分别为 `[0.06667, 0.10667]`、`[0.74667, 0.78667]`，双 seed 冻结学习增益检验 `passed`。两种初始化的初始成绩差异很大，不能把 seed 43 的大幅提升直接解释为广泛泛化能力。

弱项仍集中于 Bygone Effigy（network 42.9%／33.3%）和 Byrdonis（52.4%／57.1%），每个 seed 每种遭遇只有 21 场。新旧批次内容、初始化、测试 seed 不同，不能用跨批总分做严格难度或学习效果归因。

### 复算与边界

`az_morph_verification.json` 为 `artifact_and_statistics_checks_passed`：复算原始统计、核对晋级链、checkpoint／代码／运行器摘要、Replay 标签与 seed 空间。未重跑最终模拟，且复用项目统计实现，不是独立跨模型审查。

150 场覆盖 126 层，其中 102 层单样本、24 层双样本；分层 bootstrap 无法估计单样本层内部变异。两 seed 使用相同测试配方，未留出整类构筑。不将这些区间或零超时推广到任意卡牌、遗物、怪物。

后续优先进入 G2 的多敌、目标选择、群攻与奖励聚合基础；G1 的随机生成、其他变形和逐卡临时状态仍未开放，继续按依赖审计，不标记 G1 全量完成。
