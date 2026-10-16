"""Frozen two-seed/two-round experiment, resumable through final held-out tests."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import CONTENT_VERSION, EpisodeLimits, atomic_json, content_hash
from sts2_env.az.content import M6_CONTENT
from sts2_env.az.coordinator import Coordinator, TrainingConfig
from sts2_env.az.evaluation import evaluate_parallel, promotion_gate, summarize
from sts2_env.az.network import code_digest
from sts2_env.az.scenarios import load_manifest, balanced_selection
from sts2_env.az.self_play import Collector, file_digest
from sts2_env.az.rewards import V1, V2


def paired_report(initial, final, test_count=150, reward_version=V1):
    gate = promotion_gate(initial, final, required_count=test_count, reward_version=reward_version)
    return dict(initial=summarize(initial), final=summarize(final),
                mean_utility_difference=gate["mean_utility_difference"],
                utility_difference_ci95=gate["confidence_interval"],
                win_rate_difference=gate["mean_win_difference"],
                win_rate_difference_ci95=gate["win_difference_ci95"], reward_version=reward_version,
                gain_passed=gate["promote"], bootstrap_samples=10_000, statistics_seed=1729,
                by_family={family: dict(initial=summarize([r for r in initial if r["family_id"] == family]),
                                       final=summarize([r for r in final if r["family_id"] == family]))
                           for family in sorted({r["family_id"] for r in initial})})


def run(output, manifest, seeds=(42, 43), workers=8, test_count=150, reward_version=V2, content_version=CONTENT_VERSION):
    if type(test_count) is not int or test_count != 150:
        raise ValueError("Current experiment requires 150 test scenarios")
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = str(Path(manifest).resolve())
    plan = dict(format_version=1, seeds=list(seeds), workers=workers,
                iterations_per_seed=2, episodes_per_iteration=256, updates_per_iteration=200,
                train_simulations=64, eval_simulations=256, validation_count=256, test_count=test_count,
                statistical_seed=1729, evaluation_seed=123, information_mode="observable", reward_version=reward_version,
                content_version=content_version,
                manifest=manifest, manifest_sha256=file_digest(manifest), code_digest=code_digest(),
                oracle_scope="16 balanced validation scenarios, 256 simulations, rollout depth 40; separate privileged reference",
                stopping_rule="exactly two training rounds per seed; no tuning based on final test",
                learning_rule="positive utility CI and win-priority gate for both modes in each of two seeds")
    plan_path = root / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise ValueError("Experiment plan/code/manifest changed")
    else:
        if any(root.iterdir()):
            raise ValueError("New experiment requires an empty directory")
        atomic_json(plan_path, plan)
    def progress(stage, **details):
        payload = dict(stage=stage, **details)
        atomic_json(root / "progress.json", payload)
        print(payload, flush=True)
    recipes = load_manifest(manifest)
    # Fixed manifest prefix selected before evaluation, never selected by outcomes.
    test = balanced_selection([r for r in recipes if r.split == "test"], test_count)
    validation = balanced_selection([r for r in recipes if r.split == "validation"], 256)
    if len(test) != test_count or len(validation) != 256 or len(seeds) != 2 or len(set(seeds)) != 2:
        raise ValueError("Experiment requires two independent seeds, 256 validation and 150 test scenarios")
    try:
        for seed in seeds:
            progress("training", seed=seed)
            config = TrainingConfig(seed=seed, workers=workers, iterations=2, reward_version=reward_version,
                                    content_version=content_version)
            run_dir = root / f"seed-{seed}"
            coordinator = Coordinator(run_dir) if (run_dir / "state.json").exists() else Coordinator(run_dir, manifest, config)
            coordinator.run()
        # Both final champions are frozen before any final test is run.
        frozen = {}
        for seed in seeds:
            run_dir = root / f"seed-{seed}"
            state = json.loads((run_dir / "state.json").read_text())
            if state["phase"] != "done":
                raise ValueError("Training is incomplete")
            frozen[str(seed)] = dict(initial=str(run_dir / "initial.pt"),
                                    final=str(run_dir / state["champion"]), final_sha256=state["champion_hash"],
                                    initial_sha256=file_digest(run_dir / "initial.pt"))
        freeze_path = root / "frozen_final_models.json"
        if freeze_path.exists() and json.loads(freeze_path.read_text()) != frozen:
            raise ValueError("Final checkpoint selection changed after test freeze")
        atomic_json(freeze_path, frozen)
        results = {}
        with Collector(workers) as collector:
            for seed in seeds:
                paths = frozen[str(seed)]
                for role in ("initial", "final"):
                    if file_digest(paths[role]) != paths[f"{role}_sha256"]:
                        raise ValueError("Frozen checkpoint modified")
                modes = {}
                for label, budget in (("network", 0), ("search", 256)):
                    progress("final_test", seed=seed, mode=label)
                    started = perf_counter()
                    old = evaluate_parallel(collector.pool, paths["initial"], test, budget, 123, EpisodeLimits(),
                                            root / "test_cache", reward_version=reward_version)
                    new = evaluate_parallel(collector.pool, paths["final"], test, budget, 123, EpisodeLimits(),
                                            root / "test_cache", reward_version=reward_version)
                    modes[label] = dict(paired_report(old, new, test_count, reward_version), elapsed_seconds=perf_counter() - started)
                    modes[label]["by_encounter"] = {enc: paired_report(
                        [r for r in old if r["encounter_id"] == enc], [r for r in new if r["encounter_id"] == enc],
                        sum(r["encounter_id"] == enc for r in old), reward_version)
                        for enc in sorted({r["encounter_id"] for r in old})}
                    atomic_json(root / f"test-{seed}-{label}.json", dict(summary=modes[label], initial=old, final=new))
                results[str(seed)] = modes
            baselines = {}
            for policy in ("random", "rule", "oracle_mcts"):
                progress("baselines", policy=policy)
                subset = balanced_selection(validation, 16) if policy == "oracle_mcts" else test
                budget = 256 if policy == "oracle_mcts" else 0
                rows = evaluate_parallel(collector.pool, frozen[str(seeds[0])]["initial"], subset, budget, 123,
                                         EpisodeLimits(), root / "baseline_cache", policy=policy, reward_version=reward_version)
                baselines[policy] = dict(summary=summarize(rows), split=subset[0].split,
                                        by_encounter={enc: summarize([r for r in rows if r["encounter_id"] == enc])
                                                      for enc in sorted({r["encounter_id"] for r in rows})},
                                        information_mode="full_state_oracle" if policy == "oracle_mcts" else "observable")
                atomic_json(root / f"baseline-{policy}.json", dict(metadata=baselines[policy], results=rows))
        report = dict(plan=plan, seeds=results, baselines=baselines, engineering_acceptance="passed",
                      learning_acceptance="passed" if all(m["gain_passed"] for r in results.values() for m in r.values()) else "not_met")
        atomic_json(root / "report.json", report)
        progress("complete", learning_acceptance=report["learning_acceptance"])
        return report
    except Exception as exc:
        atomic_json(root / "error.json", dict(error=repr(exc)))
        progress("failed", error=repr(exc))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_hp_v2_experiment")
    parser.add_argument("--manifest", default="data/az/hp_v2_manifest.json")
    parser.add_argument("--seeds", nargs=2, type=int, default=[42, 43])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--test-count", type=int, default=150)
    parser.add_argument("--reward-version", choices=[V1, V2], default=V2)
    parser.add_argument("--content-version", choices=[CONTENT_VERSION, M6_CONTENT], default=CONTENT_VERSION)
    run(**vars(parser.parse_args()))
