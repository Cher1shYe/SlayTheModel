"""M1 full-state-debug integration only; no evaluation, promotion or observable claims."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from sts2_env.az.adapter import CombatAdapter
from sts2_env.az.config import (ACTION_VERSION, REWARD_VERSION, RULES_VERSION, EpisodeLimits,
                                atomic_json, derive_seed)
from sts2_env.az.encoder import ENCODER_VERSION, MODE, SCHEMA_HASH, encode_debug, save_schema
from sts2_env.az.network import (PolicyValueNetwork, batch_observations, policy_value_loss,
                                 save_debug_checkpoint, load_debug_checkpoint)
from sts2_env.az.puct import plan_debug
from sts2_env.az.scenarios import load_manifest


def run(output, manifest, episodes=2, budget=8, seed=42, updates=10):
    if min(episodes, budget, updates) < 1:
        raise ValueError("Episodes, simulations and updates must be positive")
    output = Path(output) / MODE
    output.mkdir(parents=True, exist_ok=True)
    # This smoke command never resumes/overwrites a prior run.
    if any(output.iterdir()):
        raise ValueError("Debug output must be empty; choose a new output directory")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    np.random.seed(seed)
    recipes = [recipe for recipe in load_manifest(manifest) if recipe.split == "train"]
    if episodes > len(recipes):
        raise ValueError("Not enough training recipes")
    model = PolicyValueNetwork().eval()
    version = f"debug-initial-{seed}"
    config = {"information_mode": MODE, "episodes": episodes, "simulations": budget,
              "seed": seed, "updates": updates, "limits": asdict(EpisodeLimits()),
              "cpu_threads": 1, "deterministic_algorithms": True}
    save_schema(output / "encoder_schema.json")
    save_debug_checkpoint(output / "initial.pt", model, version, config, {})
    observations, targets, values = [], [], []
    episode_reports = []
    started = perf_counter()
    for job, recipe in enumerate(recipes[:episodes]):
        env = CombatAdapter(recipe, error_dir=output / "errors")
        episode_id = f"debug-{seed}-{job}"
        rows, current_observations = [], []
        while not env.outcome().done:
            step = len(env.actions)
            observation = encode_debug(env.world, step)
            try:
                result = plan_debug(env.world, model, decisions=step, limits=env.limits,
                                    model_version=version, budget=budget, training=True,
                                    temperature=1 if step < 10 else 0,
                                    search_seed=derive_seed(seed, 0, job, f"search-{step}"))
            except Exception as exc:
                atomic_json(output / "errors" / f"{episode_id}.json",
                            {"trace": env.trace(), "error": repr(exc), "stage": "planner"})
                raise
            env.step(result.action)
            current_observations.append(observation)
            rows.append({"episode_id": episode_id, "scenario_id": recipe.scenario_id,
                         "family_id": recipe.family_id, "step_index": step,
                         "information_mode": MODE, "encoder_version": ENCODER_VERSION,
                         "schema_hash": SCHEMA_HASH, "action_schema_version": ACTION_VERSION,
                         "reward_version": REWARD_VERSION, "rules_version": RULES_VERSION,
                         "model_version": version, "observation": observation.to_dict(),
                         "legal_mask": observation.legal_mask.tolist(),
                         "root_visits": result.root_visits.tolist(),
                         "policy_target": result.policy_target.tolist(), "chosen_action": result.action,
                         "search_simulations": result.simulations, "search_seconds": result.elapsed,
                         "forced_action": result.forced_action})
        outcome = asdict(env.outcome())
        z = outcome["reward"]
        for row in rows:
            row.update(z=z, termination_reason=outcome["termination_reason"], final_hp=outcome["final_hp"],
                       turns=outcome["turns"], decisions=outcome["decisions"])
        # Commit only after completion; recipes/seeds/actions are a separate debug file.
        atomic_json(output / "episodes" / f"{episode_id}.json", {"complete": True, "rows": rows})
        atomic_json(output / "traces" / f"{episode_id}.json", env.trace())
        observations.extend(current_observations)
        targets.extend(row["policy_target"] for row in rows)
        values.extend([z] * len(rows))
        episode_reports.append(outcome)
        print(f"{episode_id}: {outcome['termination_reason']}, {len(rows)} decisions", flush=True)
    batch = batch_observations(observations)
    pi = torch.tensor(targets, dtype=torch.float32)
    z = torch.tensor(values, dtype=torch.float32)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0003, weight_decay=0.0001)
    history = []
    model.train()
    for update in range(updates):
        optimizer.zero_grad(set_to_none=True)
        loss, metrics = policy_value_loss(model, batch, pi, z)
        loss.backward()
        grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        history.append({"update": update, "loss": float(loss.detach()), "gradient_norm": float(grad_norm), **metrics})
    model.eval()
    report = {"stage": "M1", "information_mode": MODE, "config": config, "episodes": episode_reports,
              "samples": len(observations), "training": history, "seconds": perf_counter() - started,
              "parameters": sum(p.numel() for p in model.parameters()), "schema_hash": SCHEMA_HASH,
              "python_version": platform.python_version(), "torch_version": str(torch.__version__),
              "numpy_version": np.__version__, "learning_acceptance": "not_evaluated",
              "engineering_training_loop": "debug_integration_only"}
    checkpoint = output / "candidate.pt"
    save_debug_checkpoint(checkpoint, model, f"debug-candidate-{seed}", config, report)
    restored, _ = load_debug_checkpoint(checkpoint)
    for before, after in zip(model.parameters(), restored.parameters()):
        if not torch.equal(before, after):
            raise RuntimeError("Checkpoint roundtrip changed weights")
    report["checkpoint_roundtrip"] = "passed"
    atomic_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_m1_smoke")
    parser.add_argument("--manifest", default="data/az/m0_manifest.json")
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--simulations", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--updates", type=int, default=10)
    args = parser.parse_args()
    report = run(args.output, args.manifest, args.episodes, args.simulations, args.seed, args.updates)
    print(json.dumps({key: report[key] for key in ("stage", "samples", "seconds", "checkpoint_roundtrip")}, indent=2))


if __name__ == "__main__":
    main()
