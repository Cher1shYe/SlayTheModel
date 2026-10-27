# 选牌模型与 40 ms 战斗代理：实验报告（2026-10-27）

**目标**：在 armD round-4 网络 + 40 ms/战斗决策（Ironclad A0，51 层）下把全流程通关率提到 80%。
**结论**：**70.0%（420/600，两个全新留出集）**，未达成。本报告汇总本轮所有**可复现**的实验与结论，
包括 2 项真实正收益和 20+ 项证伪。

评测入口：`deployment/probe8.py`，**必须** `STS_SO_DIR=simulator/build_det`（否则静默回落到旧的
`simulator/build312`，所有配置会跑出一模一样的数字）。除特别注明外所有数字都是**同 batch 配对**
（300 seeds；单批次 300 seeds 的配对差值仍有 ±7 胜噪声，故关键结论都做了留出集复现）。

---

## 1. 交付配置与数字

```json
{"scorer":"need","need_w":{"sustain":0.5,"balance":0.5,"block_act3":1.3},
 "boss_rest":0.95,"playout_target":1,"final_pot_w":0.0,"smith_target":"tier",
 "boss_relic_mode":2,"cfg":{"playout_variants":8}}
```

| 留出集（各 300 seeds，未参与调参） | 上一轮最好 | 本轮交付 | Δ |
|---|---|---|---|
| seeds 1500–1799 | 203 (67.7%) | 208 (69.3%) | +5 |
| seeds 2100–2399 | 205 (68.3%) | 212 (70.7%) | +7 |
| **合计 600 局** | **408 (68.0%)** | **420 (70.0%)** | **+12 胜 / +2.0pp** |

## 2. 本轮有效的两项（各 +1.8pp）

| 改动 | 做法 | 证据 |
|---|---|---|
| **rollout 策略组合** `sts.set_playout_variants(8)` | 每次仿真按 `simIdx % 8` 轮换 8 种 rollout 策略（默认打最低 HP / 打最大进伤 / 打 HP 比例最低 / 打最高序号 / 无穿伤先攻 / 致命回合守卫 / 有穿伤先防 / 补刀） | 6 个 300-seed 批次（1800 局）**1180→1213 胜（+1.8pp）**，层 +0.34±0.12；两个留出集 +9 / +4 |
| **能量遗物优先** `sts.set_boss_relic_mode(2)` | Boss 遗物取所有能量遗物优先（Dome/Coffee Dripper/Ectoplasm/Fusion Hammer/Cursed Key/Philosopher's Stone/Velvet Choker/Snecko 前置） | tuning +7、留出集 +4 → **+11/600（+1.8pp）** |

对照：`mode=1`（Runic Pyramid/Snecko 优先、能量降档）= −17 胜 → 本环境中该代理**极度缺能量**。

## 3. 为什么 40 ms 是"策略族"瓶颈，而不是算力/选牌

- **算力饱和**：40/100/200/400 ms = 66.7/68.0/66.7/66.7%（150 seeds）。40 ms 中位 **5058 次仿真/决策**
  （p05 1817，p95 30351）；共享树多线程实测只有单线程 0.65–0.84× 仿真数（树下降占 94% 时间）。
- **确定性 rollout**：给定真实抽牌顺序，greedy rollout 是确定性的 → 5000 次仿真 ≈ 在一族线里取最好的一条。
  对 rollout 重洗抽牌堆（PIMC 确定性化）在 40 ms 下 **−32 胜/150**，40→200 ms 也只有 44.7/48.7%：
  agent 的强项正是"用真实抽牌顺序找到一条确定能赢的线"。
- **搜索的形态**：根先验 PUCT + expert-greedy rollout，取"最佳完整线"的第一个动作（best-line）。
  改成按平均 Q / 访问数 / 根边胜率选择都远差（−7 层 / −7 层 / −20.7 层）；"承诺整条线"（commit-to-line
  2/5/全部动作 = 5.8%/6.7%/13.3%，对照 65%）是灾难性的——恢复能力比最优线更重要。
- **失败结构**（150 seeds，3290 场战斗）：每场战斗败率 1.52%；floor16 到达 99.3%、floor33 91.1%、
  floor50 81.7%；**BOSS 入口 HP 是最强判别因子（赢 0.96 vs 输 0.70）**；50 场致命战斗分散在 14 种遭遇
  （Collector 9、Awakened One 7、Time Eater 7、Donu&Deca 6、Champ 5…），无单点可调。
  80% 等价于把致命战斗从 50 压到 30（败率 1.52%→0.9%）。
- **选牌维度的天花板**：`net_w=0`（完全去掉 ArmG 网络、只用 junk 过滤 + need 规则）与 `net_w=1` 胜场
  **完全相同**（100/150 vs 100/150）；用强战斗代理自对弈微调选牌网 +2/300；need 权重各项 ≤0；
  tier/syn/skip_deck/deck_pen 全为 0 或负。**选牌不是本轮的瓶颈。**
- **遗物 >> 卡牌**：商店"先买遗物"比"让网络在过滤垃圾牌后自己挑"高 **9.7pp**（−29 胜/300）。这解释了
  为什么选牌维度已饱和、而 Boss 遗物排序能拿 +1.8pp。

## 4. 负结果清单（全部同 batch 配对；除注明外 300 seeds）

**战斗 / 搜索**

| 实验 | 结果 |
|---|---|
| rollout 确定性化（重洗剩余抽牌堆） | **−32 胜/150** |
| commit-to-line（执行最佳线的 2/5/全部动作） | 5.8% / 6.7% / 13.3%（对照 65%） |
| 根动作改成平均 Q / 访问数 / 胜率 | −7 层 / −7 层 / −20.7 层 |
| cpuct 1.0 / 2.0 / 4.5 / 6.0 | 61.3 / 65.3 / 65.3 / 61.3%（3.0 = 67.3%） |
| 先验温度 0.5（更尖锐） | 更差 |
| 战斗策略再自对弈一轮（armD_need2） | −11 胜/300 |
| portfolio K=12（原成分）/ 随机抖动成分 / 只在没赢线时轮换 | −3 / −2 / −8 |
| 单策略牌序：无穿伤先攻 / 有穿伤先防 / 补刀先出 / 伤害每能量 | −4 / (+7 tuning, **−5 留出**) / −2 / **−19** |
| `playout_eps=0.05`（130 ms 时代的最优值）/ 0.02 | **−6** / +4（噪声） |
| value-greedy rollout（clone 后逐牌试打、按伤害+格挡−能量打分） | **−28**（K=11）/ −11（K=12）；耗时 40.7→45.8 ms |
| potion rescue（必死回合在 rollout 里喝药） | +3 胜、层 +0.01 = 0 |

**非战斗 / 选牌**

| 实验 | 结果 |
|---|---|
| Boss 遗物 mode=1（Pyramid/Snecko 优先） | **−17** |
| 商店买药水（每层 / act3+） | −7 / +1 |
| 商店让网络挑（不先买遗物） | **−29** |
| 删牌门槛 `remove_min=2` | −2 |
| `save_potions=1`（非 BOSS 战不喝药、留给 BOSS，400 seeds） | −6 胜、层 −1.28 |
| need 权重 energy / draw / aoe | +1 / −3 / −6 |
| 选牌网 `net_w=0` / 自对弈微调 / tier_w / syn_w / skip_deck | 0 / +2 / −1 / −5~−10 / −6 |
| 地图启发式 `map_pick='heur'` / 强制精英 / 避精英 | **−16** / −1~−2 / −1~−2 |
| `rest_smith=0.55` | +4（噪声） |

## 5. 论文阅读（`paper/`，10 篇）

只有 **SpireBench（arXiv 2610.12596）** 给出可直接改代码的结论：强弱差距在"怎么打每一场架"——
不在无攻击回合格挡（6% vs 31%）、每点能量打出更多伤害（7.5 vs 5.8）、不错过斩杀、少休息多升级、
act1 多拿 AOE。逐条实测：`playout_order=1`（无穿伤先攻）−4、按伤害/能量排序 **−19**、补刀排序 −2、
`rest_smith=0.55` +4（噪声）、`need_w.aoe=1.0` −6、强制精英 −1/−2 → **全部不迁移**。
原因明确：这些判别量描述"弱 LLM（全程 0–10%）→ 普通人类"的差距，本代理（64–70%）已在它之上。

其余 9 篇（DraftFM / Drafted deck strength / Contextual card preference / AI drafting MTG / Active Genes /
Rule synergy LLM / LoCM / UrzaGPT）要么是预测**人类选牌**、要么需要上亿条人类 pick，与已被证伪的行为克隆
路线重合。

## 6. 下一步（若继续）

1. **逐卡审计 `Expert::getPlayOrdering`**：rollout 的牌表是全部实力的来源，但 50 余张在役牌的排序值从没
   按卡做过消融。便宜，预期 1–2pp。
2. **叶节点价值网**：把 `evaluateEndState` 换成学出来的胜率，让同样的 40 ms 少依赖 rollout 线（需要把
   推理接进 C++ 搜索）。
3. **用 40 ms 搜索当教师做 DAgger**：目前 pure 策略网只到 ~24 层，而 40 ms greedy 搜索在 ~48 层，
   蒸馏目标是对的，但需要训练 + 集成进 C++ rollout，属天级工程。

## 7. 复现

```bash
# 编译（本轮的 C++ 开关都在这个目录）
cd simulator/build_det && ../../.venv/bin/cmake --build . --target slaythespire -j 16

# 交付配置 vs 上一轮最好配置，全新留出集（seeds 2100–2399）
cd /home/doulingfeng/idea/sts
STS_SO_DIR=simulator/build_det .venv/bin/python deployment/probe8.py \
  --policies "$(cat deployment/results_card_model/policies_final.json)" \
  --seeds 300 --seed-offset 2100 --out /tmp/final.json
```

结果文件见 `deployment/results_card_model/`；完整逐节长报告（含每一节的原始命令与表格）
在 `deployment/runs_v2/card_model_report.md`（该目录不进 git）。
