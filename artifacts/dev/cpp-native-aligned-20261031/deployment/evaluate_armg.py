"""Paired evaluation of a learned ArmG run policy against the run heuristic.

Both arms use the same seeds and exactly the same battle controller.  Run e.g.::

    python -m deployment.evaluate_armg --checkpoint runs/armg/best.pt \
        --split test --seeds 100 --combat mcts-oracle --simulations 64

The evaluation excludes incomplete episodes from win/floor statistics and
reports them explicitly, including the number of complete pairs.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import pathlib
import time
from typing import Callable

import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM, ArmGScorer
from agent import content_profile
from agent.armg_train import FloorBudget, collect_episode
from agent.run_reward import DeckElo
from agent.nets import load_checkpoint, read_checkpoint
from agent.policy import split_seeds


def load_armg_checkpoint(path, model):
    """Reject incompatible ArmG features even when tensor shapes are equal.

    Accepts the PPO actor-critic checkpoints written by ``agent.armg_train`` by
    extracting the ``actor.*`` weights: evaluation only needs the policy, and
    the shape/engine checks below still run against the extracted weights.
    """
    payload = read_checkpoint(path)
    state = payload.get("state_dict", {})
    if state and any(key.startswith("actor.") for key in state):
        # PPO checkpoint: keep the engine/schema identity, shrink the recorded
        # shapes to the actor's, and let strict load_state_dict catch a real
        # architecture mismatch (the critic's shapes are irrelevant here).
        config = dict(payload.get("config", {}),
                      param_shapes=[list(p.shape) for p in model.parameters()])
        payload = dict(payload, state_dict={k[6:]: v for k, v in state.items()
                                             if k.startswith("actor.")},
                       config=config)
    expected = {"armg_feature_version": ARMG_FEATURE_VERSION,
                "armg_obs_dim": ARMG_OBS_DIM,
                "armg_action_dim": ARMG_ACTION_DIM}
    return load_checkpoint(_serialise(payload), model, expected_config=expected)


def _serialise(payload):
    buffer = io.BytesIO()
    torch.save(payload, buffer)
    buffer.seek(0)
    return buffer


def _summary(results: list[dict]) -> dict:
    done = [r for r in results if r["status"] == "terminated"]
    wins = sum(bool(r["won"]) for r in done)
    return {
        "episodes": len(results),
        "completed": len(done),
        "truncated": sum(r["status"] == "truncated" for r in results),
        "errors": sum(r["status"] == "error" for r in results),
        "wins": wins,
        "win_rate_completed": wins / len(done) if done else None,
        "mean_floor_completed": sum(r["floor"] for r in done) / len(done) if done else None,
        "mean_hp_completed": sum(r["hp"] for r in done) / len(done) if done else None,
        "cycle_recoveries": sum(int(r.get("cycle_recoveries", 0)) for r in results),
        "runs_with_recovery": sum(int(r.get("cycle_recoveries", 0)) > 0 for r in results),
        "mcts_searches": sum(int(r.get("mcts_searches", 0)) for r in results),
        "mcts_simulations": sum(int(r.get("mcts_simulations", 0)) for r in results),
    }


def evaluate_pairs(model, seeds: list[int], *, combat: str, simulations: int,
                   epsilon: float, max_steps: int, ascension: int = 0,
                   floor_increment: int = 0, elite_simulations: int = 0,
                   boss_simulations: int = 0, deck_elo=None,
                   play: Callable = collect_episode) -> dict:
    """Compare models with identical per-seed combat policy and budget.

    Only pairs in which both runs terminated normally contribute to paired
    statistics. All episode outcomes, including abnormal ones, are retained.
    """
    if len(set(seeds)) != len(seeds):
        raise ValueError("evaluation seeds must be unique")
    options = {"deterministic": True, "combat": combat, "simulations": simulations,
               "epsilon": epsilon, "max_steps": max_steps, "ascension": ascension,
               "content_profile": content_profile.PROFILE,
               # The terminal reward includes the permanent-deck Elo term; a
               # missing snapshot must never be reported as an Elo of zero.
               "deck_elo": deck_elo,
               "combat_budget_by_context": FloorBudget(simulations, floor_increment,
                                                       elite_simulations, boss_simulations)}
    arms: dict[str, list[dict]] = {"armg": [], "heuristic": []}
    for i, seed in enumerate(seeds):
        # Alternate order to reduce sensitivity to machine-load drift.
        order = [("armg", model), ("heuristic", None)]
        if i % 2:
            order.reverse()
        for name, policy in order:
            result = dict(play(int(seed), policy, **options))
            result.pop("records", None)
            arms[name].append(result)
    paired = [(a, b) for a, b in zip(arms["armg"], arms["heuristic"])
              if a["status"] == b["status"] == "terminated"]
    deltas = [float(a["floor"] - b["floor"]) for a, b in paired]
    mean_delta = sum(deltas) / len(deltas) if deltas else None
    se = None
    if len(deltas) > 1:
        se = math.sqrt(sum((d - mean_delta) ** 2 for d in deltas) /
                       (len(deltas) * (len(deltas) - 1)))
    paired_result = {
        "complete_pairs": len(paired),
        "mean_floor_difference": mean_delta,
        "floor_difference_se": se,
        "armg_only_wins": sum(bool(a["won"]) and not bool(b["won"]) for a, b in paired),
        "heuristic_only_wins": sum(bool(b["won"]) and not bool(a["won"]) for a, b in paired),
        "both_win": sum(bool(a["won"]) and bool(b["won"]) for a, b in paired),
        "neither_win": sum(not bool(a["won"]) and not bool(b["won"]) for a, b in paired),
    }
    return {"armg": _summary(arms["armg"]), "heuristic": _summary(arms["heuristic"]),
            "paired": paired_result, "episodes": arms}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--split", choices=("train", "val", "test"), default="test")
    ap.add_argument("--seeds", type=int, default=100)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--combat", choices=("greedy", "search", "mcts-oracle", "mcts-resampled"),
                    default="mcts-oracle")
    ap.add_argument("--simulations", type=int, default=64)
    ap.add_argument("--floor-increment", type=int, default=0)
    ap.add_argument("--elite-simulations", type=int, default=0)
    ap.add_argument("--boss-simulations", type=int, default=0)
    ap.add_argument("--epsilon", type=float, default=0.05)
    ap.add_argument("--max-steps", type=int, default=5000)
    ap.add_argument("--ascension", type=int, default=0)
    ap.add_argument("--out", default=None, help="optional JSON results path")
    args = ap.parse_args(argv)
    if args.seeds <= 0 or args.start < 0 or args.simulations < 1 or args.max_steps < 1:
        ap.error("seeds, simulations and max-steps must be positive; start must be nonnegative")
    if not 0 <= args.epsilon <= 1:
        ap.error("epsilon must be between 0 and 1")
    torch.set_num_threads(1)
    model = ArmGScorer()
    payload = load_armg_checkpoint(args.checkpoint, model)
    model.eval()
    deck_elo = DeckElo()
    seeds = split_seeds(args.split, args.start + args.seeds)[args.start:]
    start = time.perf_counter()
    report = evaluate_pairs(model, seeds, combat=args.combat, simulations=args.simulations,
                            epsilon=args.epsilon, max_steps=args.max_steps,
                            ascension=args.ascension, floor_increment=args.floor_increment,
                            elite_simulations=args.elite_simulations,
                            boss_simulations=args.boss_simulations, deck_elo=deck_elo)
    trained_settings = payload.get("settings", {})
    report["config"] = {"checkpoint": args.checkpoint, "split": args.split,
                        "start": args.start, "seeds": args.seeds,
                        "seed_base": seeds[0], "combat": args.combat,
                        "simulations": args.simulations, "epsilon": args.epsilon,
                        "max_steps": args.max_steps, "ascension": args.ascension,
                        "search_budget": FloorBudget(args.simulations, args.floor_increment,
                                                     args.elite_simulations,
                                                     args.boss_simulations).as_dict(),
                        "content_profile": content_profile.identity(),
                        "elo_snapshot": deck_elo.identity(),
                        "cycle_recovery": "Both policies use the same repeated-public-state guard; "
                                          "a different legal action is forced on repeated states.",
                        "information_mode": ("oracle: full simulator state and future RNG"
                                             if args.combat == "mcts-oracle" else
                                             "hidden state resampled" if args.combat in ("mcts-resampled", "search")
                                             else "greedy"),
                        "checkpoint_training_settings": trained_settings,
                        "evaluation_matches_training_battle": all(
                            trained_settings.get(k) == getattr(args, k)
                            for k in ("combat", "simulations", "epsilon", "ascension"))
                        and trained_settings.get("search_budget", {}).get("per_floor", 0)
                        == args.floor_increment
                        and trained_settings.get("content_profile", {}).get("sha256")
                        == content_profile.identity()["sha256"],
                        "seconds": time.perf_counter() - start}
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        path = pathlib.Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        summary = {k: v for k, v in report.items() if k != "episodes"}
        summary["episodes_path"] = str(path)
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), flush=True)
    else:
        print(text, flush=True)


if __name__ == "__main__":
    main()
