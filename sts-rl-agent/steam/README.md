# Real Steam bridge

This adapter drives the real Steam game through CommunicationMod:

- Arm G or a random baseline handles non-combat choices.
- Both groups use the same exact-state MCTS combat search.
- `state_export_mod/` adds exact Java RNG states and energy-per-turn to combat JSON.
- `steam_mcts.py` rebuilds a simulator `BattleContext` and maps its action back to a
  CommunicationMod command.

## Prerequisites

1. Slay the Spire, ModTheSpire, BaseMod, and CommunicationMod.
2. `sts_lightspeed` checked out at the commit documented in `sim_patch/`.
3. Apply `sim_patch/sim_rl_hooks.patch` and build the Python module.
4. Install Python dependencies used by the training code (`torch`; `tensorboard` only
   for training).

## Setup

```bash
cp .env.example .env
# edit STS_LIGHTSPEED_BUILD and optional game paths

cd steam/state_export_mod
./build.sh
```

Point CommunicationMod's external-process command at:

```text
/absolute/path/to/sts-rl-agent/steam/run_live_bridge.sh
```

Then launch the modded game. Runtime JSONL files are written under `runs/` by default
and are ignored by Git.

## Evidence boundary

The learned network does not choose combat cards. Combat is online MCTS planning.
The real-Steam adapter is an integration and sim-to-real validation layer; aggregate
performance numbers come from the controlled simulator evaluation.
