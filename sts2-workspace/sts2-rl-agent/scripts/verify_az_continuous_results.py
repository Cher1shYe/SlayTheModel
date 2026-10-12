"""Read-only verification of continuous-run artifacts; never runs combat or training."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import atomic_json
from sts2_env.az.evaluation import promotion_gate, summarize, stratified_pairs
from sts2_env.az.network import code_digest, load_checkpoint
from sts2_env.az.replay_buffer import episode_digest
from sts2_env.az.rewards import terminal_reward
from sts2_env.az.scenarios import load_manifest, balanced_selection
from sts2_env.az.self_play import file_digest


def require(ok, message):
    if not ok:
        raise ValueError(message)


def run(directory, output):
    root = Path(directory).resolve()
    hashes = {}

    def read(path):
        path = Path(path)
        hashes[str(path.relative_to(root))] = file_digest(path)
        return json.loads(path.read_text(encoding="utf-8"))

    plan, report = read(root / "plan.json"), read(root / "report.json")
    frozen = read(root / "frozen_final_models.json")
    config = plan["config"]
    reward, content = config["reward_version"], config["content_version"]
    require(plan["code_digest"] == code_digest(), "Engine/trainer source changed")
    require(plan["runner_digest"] == file_digest(Path(__file__).with_name("run_alphazero_continuous.py")), "Runner changed")
    require(plan["promotion_policy"] == "network-only-v1", "Wrong promotion policy")
    require(not (root / "error.json").exists(), "Run has recorded error")
    require(read(root / "progress.json")["stage"] == "complete", "Run incomplete")
    read(root / "manifest.json")
    recipes = load_manifest(root / "manifest.json")
    test = [r for r in recipes if r.split == "test"]
    validation = balanced_selection([r for r in recipes if r.split == "validation"], config["validation_count"])

    def check_rows(rows, expected):
        require([r["scenario_id"] for r in rows] == [r.scenario_id for r in expected], "Scenario order/pair mismatch")
        require(len({r["scenario_id"] for r in rows}) == len(rows), "Duplicate scenario")
        for row, recipe in zip(rows, expected):
            require((row["family_id"], row["encounter_id"], row["initial_hp"]) ==
                    (recipe.family_id, recipe.encounter_id, recipe.player_hp), "Stratum mismatch")
            require(row["done"] and row["reward_version"] == reward and
                    row["errors"] == row["illegal_actions"] == 0, "Invalid outcome")
            require(row["reward"] == terminal_reward(row["termination_reason"], row["final_hp"],
                    row["initial_hp"], row["enemy_final_hp"], row["enemy_max_hp"], reward,
                    enemy_initial_hp=row["enemy_initial_hp"], enemy_roster=row.get("enemy_roster")), "Reward mismatch")
            require(row["termination_reason"] != "death" or row["final_hp"] == 0, "Death HP nonzero")
            require(len(row["decision_seconds"]) == row["decisions"], "Decision count mismatch")

    actual, rounds, results = {}, [], {}
    for seed in plan["seeds"]:
        key = str(seed)
        base = root / f"seed-{seed}"
        state = read(base / "state.json")
        require(state["phase"] == "done" and state["iteration"] == config["iterations"]
                and not state["round_failed"], "Training incomplete/failed")
        require(state["code_digest"] == plan["code_digest"], "State code mismatch")
        for role in ("initial", "final"):
            path = Path(frozen[key][role])
            require(file_digest(path) == frozen[key][role + "_sha256"], "Model hash mismatch")
            load_checkpoint(path, "observable", reward, content)
            hashes[str(path.relative_to(root))] = file_digest(path)
        require(frozen[key]["final_sha256"] == state["champion_hash"], "Champion hash mismatch")
        promoted, updates, train_recipes = 0, 0, {}
        champion = "initial.pt"
        for iteration in range(config["iterations"]):
            manifest = base / "manifests" / f"train-{iteration}.json"
            read(manifest)
            batch = load_manifest(manifest)
            require(len(batch) == config["episodes_per_iteration"], "Training recipe count")
            train_recipes.update({r.scenario_id: r for r in batch})
            _, checkpoint = load_checkpoint(base / f"candidate-{iteration}.pt", "observable", reward, content)
            count = len(checkpoint["statistics"]["history"])
            require(count == config["updates"], "Update count mismatch")
            updates += count
            evaluation = read(base / f"evaluation-{iteration}.json")
            require(evaluation["promotion_policy"] == plan["promotion_policy"], "Round policy mismatch")
            for mode, payload in evaluation["modes"].items():
                for role in ("champion", "candidate"):
                    check_rows(payload[role], validation)
                    require(summarize(payload[role]) == payload[role + "_summary"], "Validation summary mismatch")
                gate = promotion_gate(payload["champion"], payload["candidate"],
                                      required_count=config["validation_count"], reward_version=reward)
                require(gate == payload["gate"], "Validation gate mismatch")
            require(evaluation["promote"] == evaluation["modes"]["network"]["gate"]["promote"], "Network-only mismatch")
            if evaluation["promote"]:
                promoted += 1
                champion = f"candidate-{iteration}.pt"
            rounds.append(dict(seed=seed, iteration=iteration, promote=evaluation["promote"]))
        require(champion == state["champion"], "Champion lineage mismatch")
        replay = read(base / "replay/manifest.json")
        decisions, seen = 0, set()
        for episode_id, digest in replay["committed"].items():
            episode = json.loads((base / "replay/episodes" / f"{episode_id}.json").read_text(encoding="utf-8"))
            require(episode_digest(episode) == digest, "Replay checksum mismatch")
            require(episode["complete"] and episode["split"] == "train", "Replay split mismatch")
            rows = episode["rows"]
            scenario = rows[0]["scenario_id"]
            require(scenario in train_recipes and scenario not in seen, "Replay recipe mismatch/duplicate")
            seen.add(scenario)
            for row in rows:
                require(row["scenario_id"] == scenario and row["z"] == terminal_reward(
                    row["termination_reason"], row["final_hp"], row["initial_hp"], row["enemy_final_hp"],
                    row["enemy_max_hp"], reward, enemy_initial_hp=row["enemy_initial_hp"], enemy_roster=row.get("enemy_roster")), "Replay label mismatch")
            decisions += len(rows)
        require(seen == set(train_recipes), "Missing training episodes")
        held = {r.environment_seed for r in test + validation}
        require(not held.intersection(r.environment_seed for r in train_recipes.values()), "Train/heldout seed overlap")
        require(not {r.environment_seed for r in test}.intersection(r.environment_seed for r in validation), "Test/validation overlap")
        actual[key] = dict(champion=champion, episodes=len(seen), iterations=state["iteration"], promoted=promoted, updates=updates)
        require(actual[key] == report["actual"][key], "Actual training counts mismatch")
        actual[key]["decisions"] = decisions
        results[key] = {}
        for mode in ("network", "search"):
            raw = read(root / f"test-{seed}-{mode}.json")
            for role in ("initial", "final"):
                check_rows(raw[role], test)
            result = dict(initial=summarize(raw["initial"]), final=summarize(raw["final"]),
                paired=promotion_gate(raw["initial"], raw["final"], required_count=plan["final_test_count"], reward_version=reward),
                strata=stratified_pairs(raw["initial"], raw["final"]))
            require(result == raw["summary"] == report["seeds"][key][mode], "Final statistics mismatch")
            results[key][mode] = result
    baseline = read(root / "baseline-random.json")
    check_rows(baseline["rows"], test)
    require(summarize(baseline["rows"]) == baseline["summary"] == report["random_baseline"], "Baseline mismatch")
    require(report["learning_gain"] == ("passed" if all(x["network"]["paired"]["promote"] for x in results.values()) else "not_met"), "Learning conclusion mismatch")
    strata = Counter((r.family_id, r.encounter_id, r.player_hp) for r in test)
    verification = dict(status="artifact_and_statistics_checks_passed", evaluation_type="simulation_only",
        independent_cross_model_audit="unavailable", actual=actual, rounds=rounds, results=results,
        random_baseline=baseline["summary"], test_strata=len(strata), stratum_sample_counts=dict(Counter(strata.values())),
        source_sha256=hashes, limitations=["No combat rerun; statistics recomputed using existing evaluator",
        "Same test recipes across seeds; not independent test sets", "Sparse within-stratum bootstrap cannot establish broad population certainty",
        "No held-out family or strong compatible rule baseline; no general combat claim"])
    atomic_json(output, verification)
    print(json.dumps(dict(status=verification["status"], actual=actual, test_strata=len(strata)), indent=2))
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="output/az_expanded_v3")
    parser.add_argument("--output", default="docs/az_expanded_verification.json")
    run(**vars(parser.parse_args()))
