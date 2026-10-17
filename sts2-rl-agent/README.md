# STS2 RL Agent

A reinforcement learning agent for **Slay the Spire 2**, built on a high-performance headless combat simulator and a Gymnasium training environment. Includes a C# bridge mod for connecting the trained agent to the real game.

## 战士与无色牌内容扩展（2026-10-17）

按最新范围完成 151 张卡牌的分层盘点，并接通前两批 17 张基础牌及升级版。当前实体／动态动作／MCTS 链路覆盖战士 33/87、无色 11/64，合计 **44/151**；其余 **107 张仍待实现，不能按全覆盖使用**。修复参考工厂重复实例 ID、Dominate 跨回合力量历史及新增抽牌的已知顺序恢复。新内容版本 `ironclad-colorless-batch1-v1`，旧冻结实验不可直接续跑。

- [逐牌覆盖清单](docs/IRONCLAD_COLORLESS_COVERAGE.md)
- [分批实现、测试与剩余工作报告](docs/AZ_IRONCLAD_COLORLESS_EXPANSION.md)

本次未启动训练，未使用最终留出集；后续仍按实际 network V7 效用验收。当前优先继续补齐持久能力和触发器，再处理逐卡变化、复杂选择与自动出牌。以下为历史阶段记录。

## T4 多 seed 短程确认已完成（2026-10-17）

value=0.1、MCTS=8 的新 seed 44/45 两轮确认及证据复核完成，共 720 条轨迹、16 次更新。最终冠军 network 效用分别 0.322412 / 0.123696，均通过相对初始化的增益门槛，但第二轮均未晋级。Boss 各 84 场验证全部死亡；seed 45 采集到一条合法获胜后缀，却未在第二轮四次更新中抽到。下一步优先版本化成功轨迹的训练覆盖，正式训练未启动。详见 [确认结果与建议](docs/AZ_TRANSFORMER_T4_VALUE01_CONFIRMATION_RESULTS.md)。以下章节保留历史进度。

## T4 最新状态与多 seed 确认（2026-10-17）

T4 两轮 smoke 已完成，第一轮冠军 network 效用 0.252700；第二轮候选退步，未晋级。单因素消融独立审计通过：value=0.1 为 0.235308、search=32 为 0.237246，均改善失败第二轮的 0.152759，但均未超过第一轮冠军，Boss 仍未通过。详见 [消融结果](docs/AZ_TRANSFORMER_T4_ABLATION_RESULTS.md)。以下旧章节保留阶段历史，以本节为当前状态。

用户决定跳过 value=0.1/search=32 组合补测，采用 value=0.1、MCTS=8 开展全新 seed 44/45 的 S 两轮短程确认。每 seed 每轮 135 整场＋45 后期、4 次更新，batch 48/16，CPU 单线程；总计 720 条记录、16 次更新。课程与 network 效用门槛保持不变。新配置 configs/az_transformer_t4_value01_confirmation_v1/execution.json，入口 scripts/run_t4_value_confirmation.py；实时进度 T4_VALUE_CONFIRMATION_PROGRESS.md。没有授权或启动正式训练，不自动打开最终留出。

## Transformer T3 当前进度（2026-10-17）

V7 S 两轮 smoke 与正式 seed 42/43 各三轮已完成：正式采集 1,080 场、30,557 个决策、96 次更新。工程工件及最终评估已复算；两个 seed 均通过冻结的 network 终局效用增益门槛。

| seed | 最终测试初始效用 | 最终冠军效用 | 增益 |
|---|---:|---:|---:|
| 42 | −1.000000 | +0.325891 | +1.325891 |
| 43 | +0.171655 | +0.344832 | +0.173177 |

每 seed 最终测试 216 场。Boss 子集各 54 场全部死亡；未见组合、未见 ID 与通用质量尚未验收。冻结分层 bootstrap 出现零宽度，报告提供补充敏感性分析并明确其局限。V7 同时改变了奖励和搜索，不能据此归因为 Transformer 相对旧 MLP 的架构收益。

完整结果见 [T3 V7 结果报告](docs/AZ_TRANSFORMER_T3_V7_RESULTS.md) 与 [可复算结果摘要](docs/transformer_t3_v7_results.json)；修订背景见 [持续结束回合诊断](docs/AZ_TRANSFORMER_V7_DIAGNOSIS.md)。T4 当前审计进展与后续任务见下一节。当前无训练运行，不自动追加轮数或启动 M/L/XL。

## T4 / G2.3f 审计进度（2026-10-17）

已重放核对全部 594 场训练 Boss、21,933 个决策，并复跑冻结冠军的 188 场验证 Boss：两 seed 的 network 效用仍为 −1，但均没有只结束回合的战斗，也没有在可出牌时结束回合。固定规则策略在 540 场原训练配方中找到 2 场合法胜利；同一个可解案例中，seed 43 network 出现 7 次零格挡 Body Slam，说明仍有明确的出牌顺序问题。

自然第三形态已有 147 场、2,309 个决策，但所有 Boss 训练 value 标签都是 −1，缺少成功轨迹。798 项测试与 605 个源工件 / 6 条合法见证复算通过。详见 [G2.3f 审计报告](docs/AZ_TRANSFORMER_G23F_AUDIT.md)。下一步实现版本化自然后期课程、组合顺序搜索诊断及组合/ID 留出；T4 整体尚未完成，未启动新训练。

## T4 自然后期课程与留出冻结（2026-10-17）

已实现 `natural-late-course-v1`：8 个第二/第三形态、Burn 与 Purity 自然起点，支持完整合法前缀恢复、可重复采样、独立后缀采集/校验及现有实体 learner 数据接口。保留原始整场 HP 和预算；快照结果不参与整场验收。

冻结 48 train、256 validation、24 未见组合、24 完整 ID 留出配方；BLUDGEON 及升级版只在 ID 留出中出现，未来必须从全新模型开始。组合诊断复现 Armaments→Body Slam 的 5 对 0 伤害、Iron Wave→Body Slam 的 14 对 7；旧 seed 43 的 8 次搜索仍可选零格挡 Body Slam。822 项测试及独立证据复算通过。

详见 [T4 课程与留出报告](docs/AZ_TRANSFORMER_T4_COURSE.md)。验收入口继续采用 256 场实际 network V7 效用；本轮未启动新训练，新增学习增益未评估。新 runner 的课程混合比例与运行预算仍需在启动前冻结。

## T4 新运行编排（2026-10-17）

已实现并冻结 `transformer-t4-run-v1`：每轮 135 整场＋45 自然后期，batch 为 48＋16，均为 3:1；两类 Replay 分池、完整记录 FIFO、原子提交与摘要校验，最多常驻 16 条轨迹。恢复覆盖采集、参数＋AdamW 更新边界及逐场验证缓存。

S smoke 固定 seed 41 两轮、每轮 4 更新；正式 seed 42/43 各三轮、每轮 16 更新。晋级与最终冠军增益均采用 network V7 效用；正式必须先通过 smoke，双冠军共同冻结后才评估 192 场初始/最终留出战斗。308 项必要测试与冻结校验通过，**本轮未启动新训练**。入口与预算详见 [T4 编排报告](docs/AZ_TRANSFORMER_T4_RUNNER.md)。

## Architecture

```
+-----------------------------------------------------------------------+
|  Headless Python Simulator (sts2_env/)                                |
|                                                                       |
|  +----------------+  +----------------+  +---------------------------+|
|  | Core Engine    |  | Game Content   |  | Gym Environments          ||
|  | combat.py      |  | 577 cards      |  | combat_env.py  (single)  ||
|  | creature.py    |  | 260 powers     |  | run_env.py     (full run)||
|  | hooks.py       |  | 121 monsters   |  | observation.py (131-dim) ||
|  | damage.py      |  | 290 relics     |  | action_space.py(61/100)  ||
|  | rng.py         |  | 63 potions     |  | reward.py                ||
|  +-------+--------+  +-------+--------+  +-----------+--------------+|
|          |                    |                        |              |
|          +--------------------+------------------------+              |
+-----------------------------------------------------------------------+
           |                                             |
           v                                             v
+---------------------+                  +--------------------------+
| Training Pipeline   |                  | Bridge to Real Game      |
| MaskablePPO (SB3)   |                  | bridge_mod/ (C#/Godot)|
| train_combat.py     |------model------>| agent_runner.py (Python) |
| train_full_run.py   |                  | TCP JSON protocol        |
+---------------------+                  +--------------------------+
```

## Project Stats

| Metric | Value |
|--------|-------|
| Source files | 133 Python + C# |
| Lines of code | ~50,000 |
| Test functions | 408 |
| Cards implemented | 577 |
| Powers implemented | 260 |
| Monsters implemented | 121 |
| Relics implemented | 290 |
| Potions implemented | 63 |
| Playable characters | 5 (Ironclad, Silent, Defect, Necrobinder, Regent) |
| Simulation speed | ~1,200 combats/sec, ~28,000 steps/sec |
| Combat win rate (trained PPO) | ~92% (Act 1 Ironclad) |

## Quick Start

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **pip** (included with Python)
- For training: a CUDA-capable GPU is recommended but not required
- For real-game bridge: .NET 9 SDK, Godot 4.5.1 Mono, Slay the Spire 2 (Steam)

### Install

```bash
git clone <repo-url>
cd sts2-rl-agent

# Core simulator only
pip install -e .

# With training dependencies (PyTorch, SB3, sb3-contrib)
pip install -e ".[train]"

# With dev dependencies (pytest)
pip install -e ".[dev]"
```

### Run Benchmark

Measure simulation throughput with random actions:

```bash
python scripts/benchmark.py
```

Expected output on a modern CPU:

```
Episodes:       1000
Total steps:    28101
Time:           0.78s
Episodes/sec:   1276
Steps/sec:      28101
```

### Play a Full Run in the Terminal

Start from the opening event, choose map nodes, fight combats, collect rewards,
and continue the run from the command line:

```bash
python -m sts2_env.cli.play_run
```

Useful options:

```bash
python -m sts2_env.cli.play_run --character Silent --seed 123 --ascension 0
```

Without `--character`, the CLI asks you to pick a character first. Inside the
game, enter the number beside an action. Shortcuts: `a` takes the first listed
action, `c` confirms or skips, and `q` quits.

### Play a Full Run in the Browser

Run the local web UI:

```bash
python -m sts2_env.web.play_run --port 8765
```

Then open <http://127.0.0.1:8765/>. The browser UI uses the same `RunManager`
logic as the terminal version, but presents the run as clickable screens for
map, combat, events, rewards, shop, rest sites, treasure, and boss relics.

### Train a Combat Agent

Train a MaskablePPO agent on single-combat encounters:

```bash
python scripts/train_combat.py \
    --total-timesteps 500000 \
    --n-envs 4 \
    --output-dir output/combat_ppo
```

Key flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--total-timesteps` | 500,000 | Total environment steps |
| `--n-envs` | 4 | Parallel environments (use CPU cores) |
| `--lr` | 3e-4 | Learning rate |
| `--batch-size` | 256 | Minibatch size |
| `--n-steps` | 2048 | Steps per rollout per env |
| `--output-dir` | output/combat_ppo | Where to save models and logs |

### Train a Full-Run Agent

Train an agent that handles an entire run (combat + map + rewards + events):

```bash
python scripts/train_full_run.py \
    --total-timesteps 1000000 \
    --act-count 1 \
    --n-envs 4 \
    --output-dir output/run_ppo
```

The `--act-count` flag controls how many acts per episode (1 = Act 1 only, 3 = full game).

### Connect to Real Game

After training, run the agent against the actual game:

1. Build and install the bridge mod (see [docs/MOD_BUILD_GUIDE.md](docs/MOD_BUILD_GUIDE.md))
2. Start Slay the Spire 2
3. Run the agent:

```bash
python -m sts2_env.bridge.agent_runner \
    --model-path output/combat_ppo/best_model/best_model.zip \
    --verbose
```

See [docs/AGENT_USAGE_GUIDE.md](docs/AGENT_USAGE_GUIDE.md) for details.

## Project Structure

```
sts2-rl-agent/
|-- pyproject.toml                 # Package config, dependencies
|-- scripts/
|   |-- benchmark.py               # Throughput benchmark
|   |-- train_combat.py            # Combat-only training
|   +-- train_full_run.py          # Full-run training
|
|-- sts2_env/                      # Python package (headless simulator)
|   |-- core/                      # Combat engine
|   |   |-- combat.py              # CombatState (turn flow, card play)
|   |   |-- creature.py            # Creature (HP, block, powers)
|   |   |-- hooks.py               # Central hook dispatch (~25 hooks)
|   |   |-- damage.py              # Damage/block calculation pipelines
|   |   |-- enums.py               # CardId, PowerId, IntentType, etc.
|   |   |-- constants.py           # Game constants from decompiled source
|   |   +-- rng.py                 # Seeded RNG
|   |
|   |-- cards/                     # Card definitions (577 cards)
|   |   |-- base.py                # CardInstance class
|   |   |-- effects.py             # 12 composable effect primitives
|   |   |-- registry.py            # Card ID -> effect dispatch
|   |   |-- ironclad.py            # Ironclad cards
|   |   |-- silent.py              # Silent cards
|   |   |-- defect.py              # Defect cards
|   |   |-- necrobinder.py         # Necrobinder cards
|   |   |-- regent.py              # Regent cards
|   |   |-- colorless.py           # Colorless cards
|   |   +-- status.py              # Status/Curse cards
|   |
|   |-- powers/                    # Status effects (260 powers)
|   |   |-- base.py                # PowerInstance base class
|   |   |-- common.py              # Core powers (Strength, Vulnerable, etc.)
|   |   |-- damage_modifiers.py    # Damage pipeline hooks
|   |   |-- block_modifiers.py     # Block pipeline hooks
|   |   |-- card_play_effects.py   # On-card-play triggers
|   |   |-- damage_reactions.py    # Thorns, reactive powers
|   |   |-- duration.py            # Tick-down / duration powers
|   |   |-- turn_effects.py        # Start/end of turn triggers
|   |   +-- monster.py             # Monster-specific powers
|   |
|   |-- monsters/                  # Monster AI (121 monsters)
|   |   |-- state_machine.py       # MoveState, RandomBranch, ConditionalBranch
|   |   |-- intents.py             # Intent types
|   |   |-- act1_weak.py           # Act 1 weak encounters
|   |   |-- act1.py                # Act 1 monsters
|   |   |-- act2.py                # Act 2 monsters
|   |   |-- act3.py                # Act 3 monsters
|   |   +-- act4.py                # Act 4 monsters
|   |
|   |-- relics/                    # Relic effects (290 relics)
|   |-- potions/                   # Potion effects (63 potions)
|   |-- orbs/                      # Orb mechanics (Defect)
|   |-- characters/                # Character starting states
|   |-- encounters/                # Encounter definitions (88 encounters)
|   |-- events/                    # Event decision trees (68 events)
|   |-- map/                       # Map generation algorithm
|   |-- run/                       # Full-run state management
|   |   |-- run_manager.py         # Run loop (map -> room -> rewards)
|   |   |-- run_state.py           # Persistent run state
|   |   |-- rewards.py             # Card/gold/potion rewards
|   |   |-- shop.py                # Shop system
|   |   |-- rest_site.py           # Rest site (heal/upgrade)
|   |   +-- events.py              # Event handler
|   |
|   |-- gym_env/                   # Gymnasium environments
|   |   |-- combat_env.py          # Single-combat env (Discrete(61))
|   |   |-- run_env.py             # Full-run env (Discrete(100))
|   |   |-- observation.py         # State -> 131-dim float32 vector
|   |   |-- action_space.py        # Action encoding + masking
|   |   +-- reward.py              # Reward shaping
|   |
|   +-- bridge/                    # Real-game connection
|       |-- client.py              # TCP client
|       |-- protocol.py            # Message types, phases
|       |-- state_adapter.py       # Game JSON -> observation vector
|       +-- agent_runner.py        # Main agent loop
|
|-- bridge_mod/                    # C# Bridge Mod (Godot project)
|   |-- STS2BridgeMod.csproj       # Build config (Godot.NET.Sdk/4.5.1)
|   |-- MainFile.cs                # Entry point, Harmony patches
|   |-- BridgeServer.cs            # TCP server
|   |-- RlAutoSlayer.cs            # AutoSlay-based automation
|   |-- RlCombatHandler.cs         # Combat decision handler
|   |-- RlMapHandler.cs            # Map navigation handler
|   |-- RlCardSelector.cs          # Card selection handler
|   +-- RlCardRewardScreenHandler.cs
|
|-- tests/                         # 14 test files, 408 test functions
|-- docs/                          # Documentation
|   |-- GAME_BRIDGE_REFERENCE.md   # Bridge architecture and protocol
|   |-- AUTOSLAY_BRIDGE.md         # AutoSlay-based bridge design
|   |-- GAME_SYSTEMS_REFERENCE.md  # Game mechanics reference
|   |-- CARDS_REFERENCE.md         # All 577 cards
|   |-- POWERS_REFERENCE.md        # All 260 powers
|   |-- MONSTERS_REFERENCE.md      # All 121 monsters
|   +-- RELICS_REFERENCE.md        # All 290 relics
|
|-- RESEARCH.md                    # Research notes and prior work
+-- DECOMPILED_ARCHITECTURE.md     # Decompiled C# architecture analysis
```

## Game Content Coverage

| Content Type | Game Total | Implemented | Coverage |
|-------------|-----------|-------------|----------|
| Cards | 577 | 577 | 100% |
| Powers (status effects) | 260 | 260 | 100% |
| Monsters | 121 | 121 | 100% |
| Relics | 290 | 290 | 100% |
| Potions | 63 | 63 | 100% |
| Encounters | 88 | 88 | 100% |
| Events | 68 | 68 | 100% |
| Characters | 5 + 2 | 5 | 100% (playable) |
| Acts | 4 | 4 | 100% |

## How It Works

### Two-Phase Approach

Following lessons from the STS1 RL community, this project uses a two-phase strategy:

1. **Headless Simulator** (for training): A pure-Python reimplementation of STS2 combat and run mechanics, verified against the decompiled C# source. Runs at ~1,200 combats/second -- fast enough for millions of training episodes.

2. **Bridge Mod** (for validation): A C# mod that hooks into the real game via Harmony, exposes state over TCP, and injects agent decisions. Includes 5-10x speed patches for faster real-game evaluation.

### RL Algorithm

- **MaskablePPO** from sb3-contrib (Stable Baselines 3)
- **Invalid action masking**: Each step, the environment provides a boolean mask indicating which actions are legal (playable cards, valid targets). Illegal actions are zeroed out before policy sampling.
- **Observation**: 131-dimensional float32 vector encoding player state, hand cards, pile summaries, and enemy state
- **Action space**: Discrete(61) for combat (end turn + 10 self-target + 50 targeted), Discrete(100) for full run

### Reward Design

**Combat environment:**
- Win: +1.0
- Loss: -1.0
- HP loss: small negative penalty (encourages efficient play)

**Full-run environment:**
- Win the run: +1.0
- Death: -1.0
- Optional shaping: small bonuses for floor progression and act completion

## Documentation

| Document | Description |
|----------|-------------|
| [README.md](README.md) | This file |
| [RESEARCH.md](RESEARCH.md) | Research notes, prior work, algorithm selection |
| [DECOMPILED_ARCHITECTURE.md](DECOMPILED_ARCHITECTURE.md) | Decompiled C# analysis for simulator |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guide, dev setup, adding content |
| [docs/SIMULATOR_ARCHITECTURE.md](docs/SIMULATOR_ARCHITECTURE.md) | Python simulator internal architecture |
| [docs/TRAINING_GUIDE.md](docs/TRAINING_GUIDE.md) | Comprehensive RL training guide |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | TCP bridge communication protocol |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Current known issues and limitations |
| [docs/MOD_BUILD_GUIDE.md](docs/MOD_BUILD_GUIDE.md) | How to build and install the bridge mod |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems and solutions |
| [docs/GAME_BRIDGE_REFERENCE.md](docs/GAME_BRIDGE_REFERENCE.md) | Bridge architecture and design notes |
| [docs/AUTOSLAY_BRIDGE.md](docs/AUTOSLAY_BRIDGE.md) | AutoSlay-based bridge design |
| [docs/GAME_SYSTEMS_REFERENCE.md](docs/GAME_SYSTEMS_REFERENCE.md) | Game mechanics reference |

## License

This project is for research and educational purposes. Slay the Spire 2 is the property of Mega Crit Games.

## Acknowledgments

- [decapitate-the-spire](https://github.com/jahabrewer/decapitate-the-spire) -- STS1 headless simulator, architectural inspiration
- [spire-codex](https://github.com/ptrlrd/spire-codex) -- STS2 data extraction pipeline
- [CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod) -- STS1 game bridge protocol design
- [BaseLib-StS2](https://github.com/Alchyr/BaseLib-StS2) -- STS2 mod framework
- [Stable Baselines 3](https://github.com/DLR-RM/stable-baselines3) -- RL training framework
