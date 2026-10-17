# 全内容 XS 自进化训练计划（P3，冻结于 2026-10-18）

状态：**配置与协议已冻结，尚未启动训练**。本文件只记录设计、生成器证据与验收口径；不宣称任何学习增益。

## 1. 范围

- 内容：`ironclad-colorless-all-v6`（战士 87 + 无色 59 = 146 张初始卡，全部升级版可用）。
- 怪物：`monster_registry` 全部 81 个 act1–act4 遭遇；只有**公开一致性扫描通过**的 71 个进入生成器（见 `docs/ALL_ENCOUNTER_PARITY.md`）；2 个召唤构造随机流不可见的遭遇归类为采样差异，1 个三形态 Boss 走专用契约，其余 7 个显式拒绝。
- 网络：**XS**（4 层、d_model 128、4 头），全新初始化，不复用任何旧内容/旧种子权重或 Replay。
- 规则与奖励：`RULES_VERSION`、`risk-terminal-v7`；搜索 `dynamic-risk-puct-v2`，预算 8。

## 2. 任意卡组生成器（`sts2_env/az/all_decks.py`）

| 项目 | 值 |
|---|---|
| 版本 | `all-decks-v1` |
| 卡池 | 146 张已准入初始卡（含升级标记），延迟卡不出现 |
| 卡组大小 | 8–30 张（任意组合，最多 4 张同名） |
| 升级概率 / 重复卡组概率 | 0.30 / 0.25 |
| 训练种子 | `[2^30, 1.5·2^30)` |
| 验证 / 测试种子 | `[1.5·2^30, 2^30+3·2^26)` / `[2^30+3·2^26, 2^31)` |
| 采样证据 | `docs/all_deck_generator.json`（192 train + 64 validation + 64 test） |

抽样覆盖：192 个训练配方覆盖 **146/146 张卡**与 **66/71 个遭遇**；卡组大小 8–30（均值 18.9）；升级率 29.4%；15 个卡组含同名多张。

`generate_recipe(split, master_seed, iteration, job_id)` 是坐标的纯函数：同坐标必得同一配方；验证/测试只允许 `iteration=0`，且与训练种子空间不相交。

## 3. 冻结配置（`configs/az_all_xs_v1/`）

- `config.json`：版本 `az-all-xs-v1`，`status=frozen-before-training`；搜索预算 8；XS 全新初始化；训练 8 轮 × 48 局；batch 64；学习率 3e-4；value 权重 0.1；目标为“搜索访问分布 + 终局 V7 效用”。
- `protocol.json`：64 个验证配方 + 64 个测试配方（完整卡组/遭遇/种子），生成器清单 SHA；训练坐标规则 `master=iteration%32, job=episode%16`。
- 测试 `tests/test_az_all_decks.py`、`tests/test_az_all_xs_config.py` 校验：确定性、池/遭遇准入、种子空间、协议可重放、训练/留出不相交。

## 4. 训练与验收流程（已实现，尚未正式运行）

1. **自对弈采集**（`all_runner.collect`）：每个训练配方在原生怪物上跑完整战斗；实体编码 + 动态动作 + 粒子信念；搜索预算 8 生成访问分布与 V7 终局标签。公开契约拒绝的配方会被**记录并跳过**（不静默转换）。
2. **网络更新**（`all_runner.update`）：XS 策略/价值联合损失；Replay 为 `typed-entity-replay-v2`，按内容/奖励版本隔离；不混用旧版本数据。
3. **验证**（`all_runner.evaluate_recipes`）：64 个验证配方整场 network-only（动作经 `action_candidates` 映射）V7 效用；契约拒绝单独计数。
4. **门槛**：验证集效用增益达到冻结门槛后才打开 64 个测试配方；测试集只用于最终一次报告。
5. **证据**：每轮 `output/<run>/iteration-NNN.json`（episode id、终局、replay 大小、损失、验证汇总、checkpoint）与 `report.json`；失败配方同样落盘。

### 4.1 冒烟结果（仅验证管线，不构成学习增益）

首轮冒烟（`iterations=1, episodes=2, budget=3, updates=1, max_turns=4`）：采集 2 局、replay 22 行、1 次更新；验证 64 配方中 34 局完成、**30 局被公开契约拒绝**。

随后补齐两类公开契约：

- 玩家侧可见能力无专用 op 时（Weak/Frail/Constrict/Hex/binding 等怪物减益）编码为显式的 `public_power` 向量（金额公开，不静默丢弃）；不影响已知能力。
- 状态相关招式转移：当前意图在**全招式表**中唯一匹配时接受该观测招式，静态图之外的转移仅在来源/目标都是合法招式时放行。

继续补齐“被击倒（STUNNED）”公开状态与零值力量/敏捷可见性后：63 局完成、1 局拒绝；再修复 Dampen 的公开降级事件（战斗内升级/降级与库存对账）后：**64/64 验证配方全部完成、0 契约拒绝**；mean V7 utility 0.334、0 非法动作。该结果只说明管线可运行；不训练、不使用最终留出、不宣称任何策略提升。

### 4.2 遭遇鲁棒性（`docs/all_encounter_robustness.json`）

对 71 个 parity 通过遭遇各用两套固定卡组随机合法动作探测 6 步：**70 个稳定**；`setup_globe_head_normal` 在第二套卡组下触发未建模的 affliction 状态，已从生成器准入集中排除（`all_decks.admitted_encounters()` 取 parity ∩ robustness）。

## 5. 诚实性约束

- 7 个未通过一致性扫描的遭遇、2 个采样差异遭遇**不进入**训练/验证/测试配方。
- 未运行训练前，不声称任何策略/效用增益；不把生成器覆盖率当作模型能力。
- 任何后续改动（卡池、遭遇、搜索预算、模型档位）都必须新版本号，不覆盖本冻结配置。
