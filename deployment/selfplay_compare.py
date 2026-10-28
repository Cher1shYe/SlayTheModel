"""Head-to-head evaluation of two trained checkpoints.

    python -m deployment.selfplay_compare --kind card --a runs/card/a.pt --b runs/card/b.pt
    python -m deployment.selfplay_compare --kind combat --a runs/selfplay/a.pt --b runs/selfplay/b.pt
"""
from __future__ import annotations

import argparse

import numpy as np

from agent.card_train import collect_episode
from agent.nets import CardScorer, CombatNet, load_checkpoint
from agent.selfplay import play_episode


def eval_card(path: str | None, runs: int, seed: int) -> dict:
    model = CardScorer()
    if path:
        load_checkpoint(path, model)
    results = [collect_episode(seed + i, model, deterministic=True) for i in range(runs)]
    return {"winrate": float(np.mean([r["won"] for r in results])),
            "avg_floor": float(np.mean([r["floor"] for r in results]))}


def eval_combat(path: str | None, runs: int, simulations: int, seed: int) -> dict:
    model = CombatNet()
    if path:
        load_checkpoint(path, model)
    results = [play_episode(seed + i, model, simulations, sample=False) for i in range(runs)]
    return {"winrate": float(np.mean([r["won"] for r in results])),
            "avg_floor": float(np.mean([r["floor"] for r in results]))}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["card", "combat"], default="card")
    parser.add_argument("--a", default=None, help="checkpoint A (None = untrained)")
    parser.add_argument("--b", default=None, help="checkpoint B (None = greedy baseline)")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--simulations", type=int, default=16)
    parser.add_argument("--seed", type=int, default=1000)
    args = parser.parse_args(argv)
    if args.kind == "card":
        print("A", eval_card(args.a, args.runs, args.seed), flush=True)
        print("B", eval_card(args.b, args.runs, args.seed), flush=True)
    else:
        print("A", eval_combat(args.a, args.runs, args.simulations, args.seed), flush=True)
        print("B", eval_combat(args.b, args.runs, args.simulations, args.seed), flush=True)


if __name__ == "__main__":
    main()
