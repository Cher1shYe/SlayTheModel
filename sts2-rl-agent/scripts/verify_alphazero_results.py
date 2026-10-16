"""Recompute completed-run statistics from raw rows; not an independent model audit."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from sts2_env.az.config import CONTENT_VERSION, atomic_json
from sts2_env.az.network import load_checkpoint
from sts2_env.az.scenarios import load_manifest, balanced_selection
from sts2_env.az.rewards import V1, V2, terminal_reward


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(directory, output):
    root = Path(directory)
    report, plan = read(root / "report.json"), read(root / "plan.json")
    frozen = read(root / "frozen_final_models.json")
    reward_version = plan.get("reward_version", V1)
    content_version = plan.get("content_version", CONTENT_VERSION)
    require(report["plan"] == plan, "Report/plan mismatch")
    require(sha(plan["manifest"]) == plan["manifest_sha256"], "Manifest checksum mismatch")
    recipes = load_manifest(plan["manifest"])
    expected_ids = [r.scenario_id for r in balanced_selection([r for r in recipes if r.split == "test"], plan["test_count"])]
    results, hashes, rounds = [], {}, []
    for seed in plan["seeds"]:
        key = str(seed)
        state = read(root / f"seed-{seed}/state.json")
        replay = read(root / f"seed-{seed}/replay/manifest.json")
        require(state["phase"] == "done" and state["iteration"] == 2, "Incomplete training")
        require(len(replay["committed"]) == 512, "Wrong committed episode count")
        for role in ("initial", "final"):
            path = frozen[key][role]
            require(sha(path) == frozen[key][f"{role}_sha256"], "Frozen checkpoint mismatch")
            load_checkpoint(path, "observable", reward_version, content_version)
        for iteration in range(2):
            _, checkpoint = load_checkpoint(root / f"seed-{seed}/candidate-{iteration}.pt", "observable", reward_version, content_version)
            require(len(checkpoint["statistics"]["history"]) == 200, "Wrong update count")
            evaluation = read(root / f"seed-{seed}/evaluation-{iteration}.json")
            require(all(len(mode[role]) == plan["validation_count"] for mode in evaluation["modes"].values()
                        for role in ("champion", "candidate")), "Wrong validation count")
            rounds.append(dict(seed=seed, iteration=iteration, promote=evaluation["promote"],
                               restriction=evaluation.get("restriction")))
        for mode in ("network", "search"):
            path = root / f"test-{seed}-{mode}.json"
            raw = read(path)
            hashes[path.name] = sha(path)
            wins = {}
            for role in ("initial", "final"):
                rows = raw[role]
                require([r["scenario_id"] for r in rows] == expected_ids, "Test selection/pairing mismatch")
                require(len(set(expected_ids)) == len(expected_ids), "Duplicate test scenario")
                require(all(r["reward"] == terminal_reward(r["termination_reason"], r["final_hp"],
                            r.get("initial_hp", 80), r.get("enemy_final_hp", 0), r.get("enemy_max_hp", 40), reward_version)
                            and r["termination_reason"] in ("win", "death", "time_limit") for r in rows),
                        "Terminal utility mismatch")
                require(all(r["errors"] == 0 and r["illegal_actions"] == 0 for r in rows), "Evaluation error")
                wins[role] = sum(r["termination_reason"] == "win" for r in rows)
                claimed = report["seeds"][key][mode][role]
                require(claimed["episodes"] == len(rows) and claimed["win_rate"] == wins[role] / len(rows),
                        "Win-rate mismatch")
            difference = np.array([b["reward"] - a["reward"] for a, b in zip(raw["initial"], raw["final"])])
            win_difference = np.array([int(b["termination_reason"] == "win") - int(a["termination_reason"] == "win")
                                       for a, b in zip(raw["initial"], raw["final"])])
            rng = np.random.default_rng(plan["statistical_seed"])
            groups = {}
            for i, row in enumerate(raw["initial"]):
                groups.setdefault(row.get("encounter_id", "legacy"), []).append(i)
            samples, win_samples = [], []
            for start in range(0, 10_000, 256):
                indices = np.concatenate([np.asarray(group)[rng.integers(len(group),
                    size=(min(256, 10_000 - start), len(group)))] for group in groups.values()], axis=1)
                samples.extend(difference[indices].mean(axis=1))
                win_samples.extend(win_difference[indices].mean(axis=1))
            interval = np.percentile(samples, [2.5, 97.5])
            win_interval = np.percentile(win_samples, [2.5, 97.5])
            claimed = report["seeds"][key][mode]
            require(np.array_equal(interval, claimed["utility_difference_ci95"]), "Bootstrap CI mismatch")
            require(float(difference.mean()) == claimed["mean_utility_difference"], "Paired difference mismatch")
            win_priority = reward_version == V1 or win_interval[0] > 0 or np.all(win_difference == 0)
            require(claimed["gain_passed"] == bool(interval[0] > 0 and win_priority), "Gain flag mismatch")
            require(np.array_equal(win_interval, claimed["win_rate_difference_ci95"]), "Win-rate CI mismatch")
            results.append(dict(seed=seed, mode=mode, episodes=len(difference), wins=wins,
                                win_rate_difference_ci95=win_interval.tolist(), gain_passed=claimed["gain_passed"]))
    baselines = {}
    for policy in ("random", "rule", "oracle_mcts"):
        path = root / f"baseline-{policy}.json"
        rows = read(path)["results"]
        ids = ([r.scenario_id for r in balanced_selection([r for r in recipes if r.split == "validation"], 16)]
               if policy == "oracle_mcts" else expected_ids)
        require([r["scenario_id"] for r in rows] == ids, "Baseline scenario mismatch")
        wins = sum(r["termination_reason"] == "win" for r in rows)
        require(report["baselines"][policy]["summary"]["win_rate"] == wins / len(rows), "Baseline score mismatch")
        baselines[policy] = dict(episodes=len(rows), wins=wins)
        hashes[path.name] = sha(path)
    require(report["learning_acceptance"] == ("passed" if all(r["gain_passed"] for r in results) else "not_met"),
            "Overall learning flag mismatch")
    verification = dict(status="artifact_and_statistics_checks_passed", independent_cross_model_audit="unavailable",
                        evaluation_type="simulation_only", test_count=plan["test_count"],
                        current_spec_150_test_requirement_met=plan["test_count"] >= 150,
                        current_spec_two_seed_requirement_met=len(plan["seeds"]) == 2,
                        reward_version=reward_version,
                        training_episodes=len(plan["seeds"]) * 512, training_updates=len(plan["seeds"]) * 400, rounds=rounds,
                        results=results, baselines=baselines, source_sha256=hashes,
                        historical_run_error=read(root / "error.json") if (root / "error.json").exists() else None,
                        limitations=["No new simulator replay performed", "Cross-model reviewer backend unavailable",
                                     "Same held-out scenarios reused across training seeds; not independent scenario sets"])
    atomic_json(output, verification)
    print(json.dumps(verification, indent=2))
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="output/az_m5_experiment")
    parser.add_argument("--output", default="docs/az_m5_verification.json")
    run(**vars(parser.parse_args()))
