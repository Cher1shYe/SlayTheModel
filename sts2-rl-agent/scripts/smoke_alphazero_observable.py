"""M2 integration: frozen random observable network + particle search, no learning claims."""
import argparse
from dataclasses import asdict
from pathlib import Path
import platform
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import ACTION_VERSION, REWARD_VERSION, RULES_VERSION, atomic_json, content_hash, derive_seed
from sts2_env.az.encoder import OBSERVABLE_SCHEMA, encode_information
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.scenarios import load_manifest


def run(output, manifest, episodes=2, budget=64, seed=42):
    if min(episodes, budget) < 1:
        raise ValueError("Positive episodes and budget required")
    output = Path(output) / "observable"
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Choose an empty output directory")
    recipes = [r for r in load_manifest(manifest) if r.split == "train"]
    if episodes > len(recipes):
        raise ValueError("Not enough training recipes")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    model = PolicyValueNetwork("observable").eval()
    version = f"observable-random-{seed}"
    config = dict(seed=seed, episodes=episodes, simulations=budget, cpu_threads=1, deterministic_algorithms=True)
    schema_hash = content_hash(OBSERVABLE_SCHEMA)
    atomic_json(output / "encoder_schema.json", {"schema": OBSERVABLE_SCHEMA, "sha256": schema_hash})
    save_checkpoint(output / "initial.pt", model, version, config, {})
    restored, _ = load_checkpoint(output / "initial.pt", "observable")
    if any(not torch.equal(a, b) for a, b in zip(model.parameters(), restored.parameters())):
        raise RuntimeError("Checkpoint roundtrip mismatch")
    outcomes, latencies, simulations, branches = [], [], 0, 0
    started = perf_counter()
    for job, recipe in enumerate(recipes[:episodes]):
        env = ObservableCombatAdapter(recipe, error_dir=output / "errors")
        episode_id = f"observable-{seed}-{job}"
        rows = []
        while not env.outcome().done:
            step = len(env.actions)
            info = env.information
            try:
                result = plan_observable(info, model, model_version=version, budget=budget,
                                         search_seed=derive_seed(seed, 0, job, f"search-{step}"))
                observation = encode_information(info)
                env.step(result.action)
            except Exception as exc:
                atomic_json(output / "errors" / f"{episode_id}.json", {"trace": env.trace(), "error": repr(exc)})
                raise
            latencies.append(result.elapsed)
            simulations += result.simulations
            branches += sum(len(edge.outcomes) > 1 for edge in result.root.edges.values())
            rows.append({"episode_id": episode_id, "scenario_id": recipe.scenario_id,
                         "family_id": recipe.family_id, "step_index": step,
                         "information_mode": "observable", "model_version": version,
                         "encoder_version": OBSERVABLE_SCHEMA["encoder_version"], "schema_hash": schema_hash,
                         "action_schema_version": ACTION_VERSION, "reward_version": REWARD_VERSION,
                         "rules_version": RULES_VERSION, "observation": observation.to_dict(),
                         "legal_mask": list(info.legal_mask), "root_visits": result.root_visits.tolist(),
                         "policy_target": result.policy_target.tolist(), "chosen_action": result.action,
                         "search_simulations": result.simulations, "search_seconds": result.elapsed,
                         "forced_action": result.forced_action})
        outcome = asdict(env.outcome())
        outcomes.append(outcome)
        for row in rows:
            row.update(z=outcome["reward"], termination_reason=outcome["termination_reason"],
                       final_hp=outcome["final_hp"], turns=outcome["turns"], decisions=outcome["decisions"])
        atomic_json(output / "episodes" / f"{episode_id}.json", {"complete": True, "rows": rows})
        atomic_json(output / "traces" / f"{episode_id}.json", env.trace())
        print(f"{episode_id}: {outcome['termination_reason']}, {len(rows)} decisions", flush=True)
    elapsed = perf_counter() - started
    report = {"stage": "M2", "information_mode": "observable", "model_version": version,
              "config": config, "schema_hash": schema_hash, "episodes": outcomes,
              "samples": len(latencies), "simulations": simulations, "elapsed_seconds": elapsed,
              "decision_seconds_p50": float(np.percentile(latencies, 50)),
              "decision_seconds_p95": float(np.percentile(latencies, 95)),
              "root_action_edges_with_multiple_outcomes": branches,
              "checkpoint_roundtrip": "passed", "learning_acceptance": "not_evaluated",
              "training_updates": 0, "python_version": platform.python_version(),
              "torch_version": str(torch.__version__), "numpy_version": np.__version__}
    atomic_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_m2_smoke")
    parser.add_argument("--manifest", default="data/az/m0_manifest.json")
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--simulations", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args.output, args.manifest, args.episodes, args.simulations, args.seed)
