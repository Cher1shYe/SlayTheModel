# SlayTheModel

Trains one neural network to play whole runs of *Slay the Spire 2* (map, rewards, shops, events, rest sites and every combat turn) on a C++ simulator of the game's v0.111.0 rules. Ironclad, Ascension 10, single player, using only information a human player can see. No search at play time; trained from scratch with PPO.

Current ruleset: `native-41cef1ea-port-v21` (content audit: run odds, events, monsters; see [content audit](docs/content-audit.md)). Basic registrations and selected metadata have been audited against a frozen real DLL export, with explicit legacy/dynamic exceptions and an append-only numeric identity lock; see the [registry audit](docs/registry-audit.md). The [monster number audit](docs/monster-number-audit.md) covers all 107 active monster models: static HP and attack values are checked against real DLL getters, while selected dynamic rules have source-derived C++ execution tests. Getter agreement does not establish native combat execution parity.

Both backends connect to the shared `spire.public/1` observation and action contract; comparison checks every encoded policy input and stops on missing coverage or differences. A real Ironclad A10 replay passes all 32 full-interface decisions across 31 actions, including the first combat and rewards. Other scenarios, individual effects and whole-run equivalence remain unverified. See [the comparison guide](parity/README.md), [handoff](AGENTS.md) and [development log](docs/DEVLOG.md).

| Path | Contents |
| --- | --- |
| `sim/` | C++ simulator and its Python extension `sts2_sim`; C++ tests and native reference fixtures |
| `train/` | Python package `spire_rl`: public observation encoding, network, AI driver layer, PPO training (`python -m spire_rl.ppo`; first version, see AGENTS.md 2.2–2.3) |
| `parity/` | Headless host that runs the real game DLL, for whole-run comparison with the simulator |
| `docs/` | Development log, plan, observation design |

Build and test:

```sh
python sim/build.py --test        # CXX=g++ on Linux; see AGENTS.md for macOS
pip install -e train
python -m pytest -q train/tests
```

History and lessons from the earlier versions (out-of-combat policy with MCTS combat): `docs/DEVLOG.md`; the code is on branch `v111_SF1`.
