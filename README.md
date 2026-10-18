## 最新进度：分层随机采集与冻结验证集（2026-10-18）

默认每轮 **76 种遭遇 × 4 场 = 304 场**。每场按独立坐标生成随机卡组和战斗种子，下一轮换新组合；不是反复训练固定卡组。验证集在独立种子区间生成 **304 个配方（每种遭遇 4 个）后冻结**，用于配对比较。最终测试集原有 64 个配方保持不变，未评估。

已移除 64 场限制及旧配方坐标循环：支持每轮 1～1024 场、最多 1024 轮，坐标不回绕，支持范围内战斗种子不碰撞。默认 8 轮共 2432 个训练开局与 304 个验证开局的构造／编码预检全部通过。持续学习与冠军分离、ALL 遭遇分层回放继续生效。

隔离副本专项及相关回归 **89/89 通过**。本次只改采样与验证方案，MCTS=8、每轮更新16次、batch64等其他训练参数保持原值；没有启动训练。新协议须用新目录，不能续跑旧协议结果；历史分数不能与新验证集直接比较。见 [操作手册](sts2-rl-agent/docs/AZ_ALL_XS_RUNBOOK.md)。以下为历史记录。

## 最新进度：持续学习与训练诊断（2026-10-18）

runner 升级为 v3：持续学习模型与冠军分离，跨轮保留权重、AdamW 和 RNG，候选未晋级也继续学习；冠军仍独立负责采集、晋级比较和最终评估。ALL 回放按遭遇均匀分层，避免高频遭遇占据大部分样本。

新增只读价值网络诊断（MSE／MAE／相关性／常数基线／终局分组）与训练侧配对纯网络、MCTS 8/32 诊断（效用／延迟／动作覆盖率）。只接受训练数据，最终测试集保持封存。详见 [v3 操作与诊断手册](sts2-rl-agent/docs/AZ_ALL_XS_RUNBOOK.md)。

v3 必须使用新训练目录，不能直接 resume 历史 v2 正式结果。默认更新次数、搜索预算、模型和牌池不变；本次仅实现改进并运行测试夹具，没有启动新训练。专项与相关回归 **75/75 通过**，并在不含用户未提交修改的隔离副本中复验。以下为历史记录。

## 最新进度：自进化训练准备修复（2026-10-18）

已完成 runner v2 的配置生效、整场 MCTS 契约、更新级断点恢复和冠军保留；**本次没有新增卡牌，没有启动正式训练，没有评估最终留出集**。当前准入保持 **146/151 张牌（战士 87、无色 59）和 76/81 种遭遇**，尚不能宣称支持任意卡牌、任意怪物。

默认参数现在实际生效：8 轮 × 48 场、每轮 16 次更新、batch 64、MCTS 8、value weight 0.1；采集与验证均为 40 回合／400 决策。召唤主敌、Hex 清理／升级、复活、逃跑及连续召唤槽位的公开状态契约已修复。候选只有在完整验证集上相对冠军的配对 95% 区间下界大于 0 才晋级；否则保留冠军。

更新级恢复保存权重、AdamW、采样 RNG 和 Torch RNG，使用 `state.json` 恢复；旧 checkpoint／Replay 与旧 runner 输出不能直接续跑。无更新的整场 MCTS 检查覆盖 64 个验证配方＋76 个准入遭遇；具体结果、测试证据和边界见 [修复报告](sts2-rl-agent/docs/AZ_TRAINING_READINESS.md)。

大范围回归仍有 **20 项历史失败／错误**，已在修复前提交复现（旧 T4 冻结工件与旧 EXPANSION_CONTENT 契约）；详见修复报告，不能宣称全仓测试全绿。新 runner 最终专项 **55/55**、引擎回归 **356/356**、整场 MCTS **140/140** 通过。

**下一步：先按 [运行手册](sts2-rl-agent/docs/AZ_ALL_XS_RUNBOOK.md) 用新目录做短程 smoke，经确认后再启动正式训练。** 不要从旧 v1 结果直接续训，也不要把工程契约通过当作学习效果提升。以下章节保留历史进度，以本节和修复报告为准。

## 最新机制接入：战士／无色状态、续接与原生生成池（2026-10-17）

本批新增 **50 张及升级版**，累计 **120/151**（战士 **83/87**、无色 **37/64**），剩余 **31**。补齐基础状态、选择后的结算、检索与牌堆消耗、嵌套自动打出、触发能力、实例成长，以及实体编码、动态动作和 MCTS 重建。

战士原生战斗候选 **79 个全部闭合**；Jackpot、Infernal Blade、Discovery、Calamity 保留完整原生池。**Splash、Jack of All Trades、Entropy 暂缓**，后两者依赖含 Splash 的无色生成／变换池，不做支持性裁剪。

[本批报告](sts2-rl-agent/docs/AZ_IRONCLAD_COLORLESS_FOUNDATION.md) · [逐牌清单](sts2-rl-agent/docs/IRONCLAD_COLORLESS_COVERAGE.md) · [原生池审计](sts2-rl-agent/docs/ironclad_colorless_generation_pools.json) · [测试证据](sts2-rl-agent/docs/ironclad_colorless_foundation_evidence.json)

必要测试 **5,111 项全部通过**，失败／错误／跳过均为 0；源码稳定、用例无遗漏和证据摘要校验通过。V4 内容／schema 与旧权重和 Replay 不直接兼容。没有启动训练或使用最终留出；后续继续按实际 network 整场 V7 效用验收。本批只验证工程机制，不宣称策略效用提升。下一步盘点剩余 31 张的独立机制，战士剩余 Corruption、Demonic Shield、Feed、Tank。下文为历史进度。

## 最新机制接入：战士／无色即时效果与公开计数（2026-10-17）

本批新增 **20 张及升级版**，累计 **70/151**（战士 50、无色 20），待接入 **81**。覆盖普通消耗、抽牌、随机攻击、X 费、先天、公开条件伤害／格挡，以及 Battle Trance／Stone Armor；同步补齐实体编码、动态合法动作和 MCTS 重建。

[本批报告](sts2-rl-agent/docs/AZ_IRONCLAD_COLORLESS_SIMPLE.md) · [逐牌清单](sts2-rl-agent/docs/IRONCLAD_COLORLESS_COVERAGE.md) · [测试证据](sts2-rl-agent/docs/ironclad_colorless_simple_evidence.json)

必要测试 **3,849 项通过**。新内容与 schema 升级 V3，旧权重和 Replay 不直接兼容。下一批优先补 Weak 等基础状态依赖，再处理延迟触发、回手和实例成长。本次未启动训练或使用最终留出；后续继续按实际 network 整场 V7 效用验收。下文为历史进度。

## 最新进度：战士／无色第三批（2026-10-17）

已接通 50/151 张（战士 37、无色 13），本批新增六张持久能力／触发牌及升级版，剩余 101。补齐公开能力状态、实体语义、动态动作和 MCTS 重建。详见 [第三批报告](sts2-rl-agent/docs/AZ_IRONCLAD_COLORLESS_POWERS.md) 与 [覆盖清单](sts2-rl-agent/docs/IRONCLAD_COLORLESS_COVERAGE.md)。未启动训练、未使用最终留出集；后续按 network V7 效用验收。下一批为 Dark Embrace／Rupture 延迟触发。

# SlayTheModel — STS2 战斗策略研究工作区

当前快照：2026-10-17。目标是在明确支持的游戏规则范围内，构建使用公开信息、可审计、能泛化到合法卡牌与怪物组合的战斗策略模型。

## 当前内容扩展范围（2026-10-17）

当前优先战士 87 张和无色 64 张。前两批新增 17 张及升级版，实体编码、动态动作与 MCTS 重建现接通 **44/151**；**107 张仍待接通**。修复参考工厂重复实例 ID、Dominate 力量历史与抽牌已知位置恢复。新内容版本 `ironclad-colorless-batch1-v1`。

详见 [覆盖清单](sts2-rl-agent/docs/IRONCLAD_COLORLESS_COVERAGE.md) 和 [实现／测试报告](sts2-rl-agent/docs/AZ_IRONCLAD_COLORLESS_EXPANSION.md)。本次不训练、不使用最终留出；后续继续按实际 network V7 效用验收。下文为历史阶段记录。

## 项目结构

- `sts2-rl-agent/`：Python 战斗模拟、公开信息投影、粒子搜索、AlphaZero 风格采集/Replay/训练/评估，以及新增 Transformer。
- `sts2-cli/`：C# 游戏战斗接口与工具；具体运行要求见其 README。
- `probe/`、根目录 Python 脚本：本地接口和性能诊断工具。
- `AGENTS.md`：工作区协作规则。原始本地两个子目录是独立 Git 仓库；本远程分支保存普通目录形式的发布快照。

## 开发进度

旧 MLP 链路已有公开信息边界、粒子重建、合法动作约束、逐场 Replay、恢复与结果复算；内容逐批扩展至 G2.3e。G2.3e 双 seed 各三轮已完成，但整体学习增益未通过，聚焦 Boss 仍为零胜。工程执行完成不代表策略质量通过。

新路线以 [`spec_1.md`](sts2-rl-agent/spec_1.md) 为准：机制描述 + 两级实体 Transformer + 动态合法动作评分，避免随内容 ID 增加而扩大固定输入和策略分类层。

| 阶段 | 当前状态 |
|---|---|
| T0/T1 最小切片 | starter 三种基础卡和 Shrinker 已接入公开实体编码、动态动作头、五档模型及严格 checkpoint；19 项契约测试通过 |
| T0 既有内容审计 | 已扩展至 G2.3e 冻结范围：33 基础卡牌、63 升级变体、10 遭遇、10 怪物实体；逐项支持矩阵见扩展报告 |
| T2 | 已接入 G2.3e 的机制描述、公开实体、单选/原子多选、双敌/召唤/Boss 搜索重建、紧凑 Replay 与精确恢复；必要回归见扩展报告 |
| T3 | V7 S 两轮 smoke 与双 seed 各三轮完成；1,080 场、96 更新，工程与冻结 network 效用增益门槛通过。Boss 难例及通用质量仍未通过 |
| T4 | 自然后期课程与留出已冻结；新编排固定整场/后期 3:1、分池 Replay、更新级恢复和 network 效用验收，308 项本轮测试通过；未新训练 |
| T5 | 档位比较及独立质量验收尚未完成 |

当前 v2 架构五档精确参数量为 XS 1,059,554；S 5,671,522；M 16,221,154；L 41,372,514；XL 121,264,738。XS/S 已做真实批处理与契约检查；M/L/XL 仅参数实例化和形状验证，不宣称训练性能合格。历史 schema/权重不自动迁移。

## 当前目标与边界

1. T4 新运行编排已完成：每轮 135 整场/45 后期、batch 48/16，S smoke 两轮每轮 4 更新，正式双 seed 各三轮每轮 16 更新。保持实际 network V7 效用验收，支持完整轨迹、AdamW 更新和验证缓存恢复；双冠军共同冻结后才做留出诊断。未启动新训练，下一步仅在用户授权后执行 smoke 并汇报证据。详见 [T4 编排报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T4_RUNNER.md)。
2. 每次扩展明确列出 engine、observation、action、network、belief/search 和 tests 支持状态；未知机制必须拒绝。
3. 之后再冻结训练/验证/测试配方，评估未见组合与内容 ID 的泛化。未见机制测试只验证拒绝，不混入普通胜率。

目前没有“任意卡牌/怪物均支持”或“已达到通用高质量”的结论。奖励选卡、地图、商店及整局策略不属于首批目标。未获当次明确授权不启动训练实验或定时任务。

## 安装与必要测试

Python 项目依赖见 `sts2-rl-agent/pyproject.toml` 和锁文件，可用 uv 创建环境；Torch 实验依赖按该项目说明安装。已有 Windows 开发环境可运行：

```powershell
cd sts2-rl-agent
.\.venv-az\Scripts\python.exe -m pytest tests/test_az_transformer.py tests/test_az_information.py -q
.\.venv-az\Scripts\python.exe scripts/audit_az_transformer.py
```

第二条执行参数、公开夹具和合成梯度审计，不启动自对弈。详见 [T0/T1 交付报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T0_T1.md)、[资源原始报告](sts2-rl-agent/docs/transformer_t0_t1_audit.json)、[旧规格](sts2-rl-agent/spec.md) 和 [历史规格](sts2-rl-agent/spec_0.md)。已查看的夹具不能充当未见测试集。

新增 [T2 交付报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T2.md) 与 [T2 资源审计](sts2-rl-agent/docs/transformer_t2_audit.json)。可用 `python -m pytest tests/test_az_transformer_t2.py -q` 检查 Replay、动态搜索和恢复。该阶段测试只运行固定小夹具；后续 T3 实测结果见下文。

最新交付见 [G2.3e Transformer 扩展报告](sts2-rl-agent/docs/AZ_TRANSFORMER_G23E.md)、[逐项支持与资源审计](sts2-rl-agent/docs/transformer_g23e_audit.json)、[必要测试结果](sts2-rl-agent/docs/transformer_g23e_tests.txt)。836 项测试通过，覆盖 180 个训练配方完整轨迹、选择/生成/临时费用、召唤和 Boss 后续阶段，以及动态搜索、Replay 与恢复。人工夹具不计为自然战斗胜率；后续 T3 实测结果见下文。

## 快照说明

最新 [持续结束回合诊断与 V7 修订](sts2-rl-agent/docs/AZ_TRANSFORMER_V7_DIAGNOSIS.md)：历史网络贪心评估全部结束回合，旧 MCTS 在访问次数同票时忽略更好的 Q。新版按 visits → Q → prior 选动作，截断叶节点使用用户指定风险公式；同时更新整场 value 标签及 network 验收。521 项测试通过。同权重开局诊断从几乎全部结束回合改善为 255/256 出牌，不作为学习增益结论。

最新 [T3 V7 正式结果报告](sts2-rl-agent/docs/AZ_TRANSFORMER_T3_V7_RESULTS.md)：S 两轮 smoke 和 seed 42/43 各三轮已完成，工件独立复算通过。最终 network 效用：seed 42 −1.000000→+0.325891，seed 43 +0.171655→+0.344832；均通过冻结门槛。每 seed 216 场测试中的 Boss 子集 54 场全部死亡，不能据总体提升宣称 Boss 已解决或通用质量通过。

[结果摘要与工件哈希](sts2-rl-agent/docs/transformer_t3_v7_results.json)保存逐轮晋级、network/search 分项、分遭遇结果、资源及统计局限。最终测试已查看，下一阶段需要新的独立组合/ID 留出。下一步是 T4；当前无训练任务运行，本次仅整理报告和更新文档。

本分支以当前源码、配置、测试和文档替换旧快照布局，保留 Git 提交历史。子项目来源和版权以各自 LICENSE/README 为准。虚拟环境、嵌套 `.git`、构建缓存、模型权重/训练输出、`.handoffs` 发布历史与本地任务状态不纳入本次快照。源码引用的游戏运行时资源仍需按各项目说明准备。
