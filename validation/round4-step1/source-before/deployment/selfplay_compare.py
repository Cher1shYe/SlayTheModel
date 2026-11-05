"""Head-to-head checkpoints and baselines on the same fixed seed list.

The old version evaluated an untrained, randomly initialised network and
labelled it a "greedy baseline". This version always reports the heuristic
baseline explicitly and names untrained networks as such.

    python -m deployment.selfplay_compare --kind combat \
        --a runs/v3/selfplay/combat.pt --b runs/v2/selfplay/combat.pt \
        --split val --seeds 500 --simulations 16 --resample
"""
from __future__ import annotations

import argparse
import json

import torch

from agent.nets import CardScorer, CombatNet, load_checkpoint
from agent.policy import Strategy, play_run_strategy, split_seeds, summarize


def evaluate(model, card_model, strategy, seeds) -> dict:
    results = [play_run_strategy(seed, model, strategy, card_model=card_model)
               for seed in seeds]
    return summarize(results)


def load(path, cls):
    model = cls()
    load_checkpoint(path, model)
    model.eval()
    return model


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["card", "combat"], default="combat")
    ap.add_argument("--a", default=None)
    ap.add_argument("--b", default=None)
    ap.add_argument("--split", choices=["train", "val", "test"], default="val")
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--simulations", type=int, default=16)
    ap.add_argument("--resample", action="store_true",
                    help="resample hidden zones (player-usable search)")
    args = ap.parse_args(argv)

    torch.set_num_threads(1)
    seeds = split_seeds(args.split, args.seeds)
    print(json.dumps({"baseline": "heuristic",
                      "result": evaluate(None, None,
                                         Strategy(combat="heuristic", cards="heuristic"),
                                         seeds)}), flush=True)

    for label, path in (("A", args.a), ("B", args.b)):
        if path is None and label == "B":
            continue
        if args.kind == "combat":
            model, card_model = (load(path, CombatNet) if path else None), None
            name = path or "untrained-network"
            strategy = Strategy(combat="search", cards="heuristic",
                                simulations=args.simulations,
                                resample=args.resample)
        else:
            model, card_model = None, (load(path, CardScorer) if path else None)
            name = path or "untrained-network"
            strategy = Strategy(combat="greedy", cards="network")
        row = evaluate(model, card_model, strategy, seeds)
        row.update({"label": label, "checkpoint": name,
                    "search_resampled": bool(args.resample and args.kind == "combat")})
        print(json.dumps(row, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
