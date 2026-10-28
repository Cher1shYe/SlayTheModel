"""Free-form evaluation on fixed, disjoint seeds.

    python -m deployment.evaluate --split test --seeds 1000 \
        --combat-checkpoint runs/v3/selfplay/combat.pt \
        --card-checkpoint runs/v3/card/card.pt \
        --strategies heuristic,network,search,search_resampled

Every strategy runs the same seed list. ``search`` is oracle root search over
the true draw order; ``search_resampled`` re-draws hidden zones per simulation
and is the only search variant that may be quoted as player-usable.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch

from agent.nets import CardScorer, CombatNet, load_checkpoint
from agent.policy import Strategy, play_run_strategy, split_seeds, summarize


def build_models(combat_path: str | None, card_path: str | None):
    combat = card = None
    if combat_path:
        combat = CombatNet()
        load_checkpoint(combat_path, combat)
        combat.eval()
    if card_path:
        card = CardScorer()
        load_checkpoint(card_path, card)
        card.eval()
    return combat, card


def run_strategy(name: str, seeds: list[int], combat, card,
                 simulations: int, workers: int) -> dict:
    if name == "heuristic":
        strategy = Strategy(combat="heuristic", cards="heuristic")
    elif name == "network":
        strategy = Strategy(combat="network", cards="network")
    elif name == "network_combat":
        strategy = Strategy(combat="network", cards="heuristic")
    elif name == "network_cards":
        strategy = Strategy(combat="heuristic", cards="network")
    elif name == "search":
        strategy = Strategy(combat="search", cards="network",
                            simulations=simulations, resample=False)
    elif name == "search_resampled":
        strategy = Strategy(combat="search", cards="network",
                            simulations=simulations, resample=True)
    elif name == "search_value":
        strategy = Strategy(combat="search", cards="network",
                            simulations=simulations, resample=False,
                            search_select="value")
    elif name == "search_value_resampled":
        strategy = Strategy(combat="search", cards="network",
                            simulations=simulations, resample=True,
                            search_select="value")
    else:
        raise ValueError(name)

    def one(seed: int) -> dict:
        return play_run_strategy(seed, combat, strategy, card_model=card)

    start = time.perf_counter()
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, seeds))
    else:
        results = [one(seed) for seed in seeds]
    seconds = time.perf_counter() - start
    summary = summarize(results)
    summary["strategy"] = name
    summary["seconds"] = round(seconds, 3)
    summary["runs_per_second"] = round(len(seeds) / seconds, 2)
    summary["player_usable"] = name != "search"
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["train", "val", "test"], default="test")
    ap.add_argument("--seeds", type=int, default=1000)
    ap.add_argument("--start", type=int, default=0,
                    help="offset within the split seed list")
    ap.add_argument("--strategies", default="heuristic,network,search,search_resampled")
    ap.add_argument("--simulations", type=int, default=16)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--combat-checkpoint", default=None)
    ap.add_argument("--card-checkpoint", default=None)
    ap.add_argument("--tag", default="eval")
    args = ap.parse_args(argv)

    torch.set_num_threads(1)
    seeds = split_seeds(args.split, args.start + args.seeds)[args.start:]
    combat, card = build_models(args.combat_checkpoint, args.card_checkpoint)
    if any(s in ("network", "search", "search_resampled", "search_value",
                 "search_value_resampled")
           for s in args.strategies.split(",")) and (combat is None or card is None):
        print("warning: a requested neural strategy has no checkpoint; the "
              "greedy/heuristic fallbacks will be used", flush=True)

    rows = []
    for name in [s.strip() for s in args.strategies.split(",") if s.strip()]:
        row = run_strategy(name, seeds, combat, card, args.simulations, args.workers)
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    out_dir = pathlib.Path("runs/eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.tag}.json"
    path.write_text(json.dumps({
        "split": args.split, "start": args.start, "seeds": args.seeds,
        "seed_base": seeds[0] if seeds else None,
        "simulations": args.simulations,
        "combat_checkpoint": args.combat_checkpoint,
        "card_checkpoint": args.card_checkpoint,
        "results": rows,
    }, indent=1), encoding="utf-8")
    print(f"wrote {path}", flush=True)


if __name__ == "__main__":
    main()
