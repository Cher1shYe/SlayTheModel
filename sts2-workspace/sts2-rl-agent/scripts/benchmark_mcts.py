"""Paired deterministic search benchmark; no neural-network inference included.

Run from the repository: python scripts/benchmark_mcts.py --sims 64 256
"""

import argparse
import gc
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.search.mcts import STS2CombatEnv, apply_action, legal_actions, search
from sts2_env.cards import base as card_base
import numpy as np


def tree_signature(root):
    """Include every node, so matching only the chosen action is insufficient."""
    return (root.action, root.visits, root.total_value, tuple(root.untried),
            tuple(tree_signature(child) for child in root.children))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, nargs="+", default=[64, 256])
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--depths", type=int, nargs="+", default=[40, 0])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seeds < 1 or any(n < 1 for n in args.sims) or any(n < 0 for n in args.depths):
        parser.error("seeds and sims must be positive; depths must be nonnegative")
    scenes = []
    for seed in range(args.seeds):
        for advance in (0, 8):
            env = STS2CombatEnv()
            env.reset(seed=seed)
            rng = np.random.default_rng(seed + 100)
            for _ in range(advance):
                if env.combat.is_over:
                    break
                actions = legal_actions(env.combat)
                apply_action(env.combat, actions[int(rng.integers(len(actions)))])
            if not env.combat.is_over:
                scenes.append((seed, advance, env.combat, card_base._next_instance_id))
    rows = []
    print(f"{len(scenes)} opening/mid-combat scenes; single process; safe clones; no network", flush=True)
    for depth in args.depths:
        for budget in args.sims:
            totals = {mode: dict(seconds=0.0, simulations=0, clones=0, transitions=0)
                      for mode in ("reference", "replay")}
            for index, (seed, advance, state, next_id) in enumerate(scenes):
                signatures = []
                # Alternate order to reduce warmup / load bias.
                modes = ("reference", "replay") if index % 2 == 0 else ("replay", "reference")
                for mode in modes:
                    gc.collect()
                    card_base._next_instance_id = next_id
                    result = search(state, budget, depth, seed + 999, mode=mode)
                    stats = totals[mode]
                    stats["seconds"] += result.elapsed
                    for name in ("simulations", "clones", "transitions"):
                        stats[name] += getattr(result, name)
                    signatures.append(tree_signature(result.root))
                    del result
                if signatures[0] != signatures[1]:
                    raise AssertionError(f"Search mismatch: seed={seed}, advance={advance}, depth={depth}, budget={budget}")
            for mode, stats in totals.items():
                row = dict(mode=mode, depth=depth, budget=budget, scenes=len(scenes),
                           sims_per_second=round(stats["simulations"] / stats["seconds"], 1),
                           ms_per_decision=round(1000 * stats["seconds"] / len(scenes), 1),
                           clones=stats["clones"], transitions=stats["transitions"],
                           tree_equivalence=True)
                rows.append(row)
                print(json.dumps(row), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
