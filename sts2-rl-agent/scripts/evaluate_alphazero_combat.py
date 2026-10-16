"""Evaluate a frozen observable checkpoint; oracle results remain separately labeled."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import atomic_json
from sts2_env.az.evaluation import evaluate, summarize
from sts2_env.az.network import load_checkpoint
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import file_digest, initialize_worker
from sts2_env.az.rewards import V1, V2
from sts2_env.az.config import CONTENT_VERSION
from sts2_env.az.content import M6_CONTENT


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--simulations", type=int, default=256)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-oracle", action="store_true")
    parser.add_argument("--reward-version", choices=[V1, V2], default=V2)
    parser.add_argument("--content-version", choices=[CONTENT_VERSION, M6_CONTENT], default=CONTENT_VERSION)
    args = parser.parse_args()
    if Path(args.output).exists():
        raise ValueError("Evaluation output already exists")
    initialize_worker()
    model, metadata = load_checkpoint(args.checkpoint, "observable", args.reward_version, args.content_version)
    recipes = [r for r in load_manifest(args.manifest) if r.split == args.split]
    if not recipes:
        raise ValueError("No requested held-out scenarios")
    report = dict(checkpoint_sha256=file_digest(args.checkpoint), manifest_sha256=file_digest(args.manifest),
                  split=args.split, simulations=args.simulations, seed=args.seed, results={})
    modes = [("network", 0), ("network", args.simulations), ("random", 0), ("rule", 0)]
    if args.include_oracle:
        modes.append(("oracle_mcts", args.simulations))
    for policy, budget in modes:
        rows = evaluate(model, metadata["model_version"], recipes, budget, args.seed, policy=policy,
                        reward_version=args.reward_version)
        label = f"{policy}-{budget}"
        report["results"][label] = dict(information_mode="full_state_oracle" if policy == "oracle_mcts" else "observable",
                                        episodes=rows, summary=summarize(rows))
        atomic_json(args.output, report)
        print(f"{label}: {report['results'][label]['summary']}", flush=True)
