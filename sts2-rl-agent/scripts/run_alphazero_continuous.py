"""M6.5: two seeds, default 3 rounds; freeze BOTH champions before final test."""
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.config import EpisodeLimits, atomic_json, content_hash
from sts2_env.az.content import DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT
from sts2_env.az.coordinator import Coordinator, TrainingConfig
from sts2_env.az.encoder import schema_for
from sts2_env.az.evaluation import evaluate_parallel, promotion_gate, summarize, stratified_pairs
from sts2_env.az.generation import generator_config, frozen_manifest
from sts2_env.az.network import code_digest
from sts2_env.az.rewards import V3, V4, V5, V6
from sts2_env.az.run_lock import RunLock
from sts2_env.az.scenarios import save_manifest, load_manifest
from sts2_env.az.self_play import Collector, file_digest


def frozen_json(path, document):
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != document:
            raise ValueError(f"Frozen configuration changed: {path}")
    else:
        atomic_json(path, document)


def run(output, smoke=False, workers=8, smoke_evidence=None, hard=False, iterations=3, expanded=False, g1=False, generated=False, quick=False, upgrades=False, topdeck=False, lifecycle=False, selection=False, choice_sets=False, morph=False, multi=False, summon=False, boss=False, boss_curriculum=False, boss_search=False):
    root = Path(output).resolve()
    with RunLock(root):
        return run_locked(root, smoke, workers, smoke_evidence, hard, iterations, expanded, g1, generated, quick, upgrades, topdeck, lifecycle, selection, choice_sets, morph, multi, summon, boss, boss_curriculum, boss_search)


def run_locked(root, smoke, workers, smoke_evidence, hard, iterations, expanded, g1, generated, quick, upgrades, topdeck, lifecycle, selection, choice_sets, morph, multi, summon, boss, boss_curriculum=False, boss_search=False):
    root.mkdir(parents=True, exist_ok=True)
    if boss_search:
        boss_curriculum = True
    if boss_curriculum:
        if not quick:
            raise ValueError("Boss curriculum requires the frozen quick budget")
        boss = True
    content = BOSS_CONTENT if boss else SUMMON_CONTENT if summon else MULTI_CONTENT if multi else MORPH_CONTENT if morph else SET_CONTENT if choice_sets else SEL_CONTENT if selection else LIFE_CONTENT if lifecycle else TOP_CONTENT if topdeck else UP_CONTENT if upgrades else GEN_CONTENT if generated else G1_CONTENT if g1 else EXPANDED_CONTENT if expanded else HARD_CONTENT if hard else DECK_CONTENT
    count = 180 if boss else 162 if summon else 144 if multi else 126 if expanded or g1 or generated or upgrades or topdeck or lifecycle or selection or choice_sets or morph else 60 if hard else 36
    reward = V6 if boss else V5 if summon else V4 if multi else V3
    config = TrainingConfig(workers=workers, content_version=content, reward_version=reward, iterations=iterations)
    if quick:
        config = replace(config, episodes_per_iteration=count, updates=16, batch_size=64,
                         simulations=8, eval_simulations=8)
    if boss_curriculum:
        from sts2_env.az.boss_curriculum import VERSION
        config = replace(config, sampling_version=VERSION)
    if boss_search:
        from sts2_env.az.search_config import COMBINED
        from sts2_env.az.boss_search_curriculum import VERSION
        config = replace(config, sampling_version=VERSION, search_version=COMBINED)
    long_config = config
    if smoke:
        config = replace(config, episodes_per_iteration=count, validation_count=256 if boss_curriculum else count, updates=4,
                         batch_size=32, iterations=2, simulations=4 if quick else 16, eval_simulations=4 if quick else 16)
    seeds = (42,) if smoke else (42, 43)
    evidence = None
    if not smoke:
        if smoke_evidence is None:
            raise ValueError("Long training requires --smoke-evidence from completed two-round smoke")
        evidence = json.loads(Path(smoke_evidence).read_text(encoding="utf-8"))
        if (evidence.get("status") != "passed" or evidence.get("iterations") != 2
                or evidence.get("code_digest") != code_digest()
                or evidence.get("runner_digest") != file_digest(__file__)
                or evidence.get("content_version") != content
                or evidence.get("sampling_version", "standard") != config.sampling_version
                or evidence.get("search_version", "legacy-zero-index-v1") != config.search_version):
            raise ValueError("Smoke is incomplete or belongs to different engine/trainer code")
    sources = {}
    if boss_curriculum:
        from sts2_env.az.boss_curriculum import configuration, manifest as curriculum_manifest
        source_root = Path(__file__).resolve().parents[1] / "output/az_g2_boss_v1_quick"
        if boss_search:
            from sts2_env.az.boss_search_curriculum import configuration, manifest as curriculum_manifest
            source_root = Path(__file__).resolve().parents[1] / "output/az_g2_boss_curriculum_v1_quick"
        sources = json.loads((source_root / "frozen_final_models.json").read_text(encoding="utf-8"))
        for source in sources.values():
            if file_digest(source["final"]) != source["final_sha256"]:
                raise ValueError("Curriculum source checkpoint changed")
    plan = dict(format_version=1, purpose="quick_mechanism_verification" if quick else "learning_experiment", promotion_policy="network-only-v1", search_role="observation", smoke=smoke, seeds=list(seeds), config=asdict(config),
                generator=configuration() if boss_curriculum else generator_config(content), code_digest=code_digest(), runner_digest=file_digest(__file__),
                smoke_evidence_hash=content_hash(evidence) if evidence else None,
                final_test_count=0 if smoke else (216 if boss_curriculum else 180 if summon or boss else 150),
                stopping_rule="fixed round cap; rejection continues; errors halt without test",
                initialization="same-schema previous Boss champion; fresh optimizer" if boss_curriculum else "independent random models; no historical checkpoint transfer",
                initialization_sources=sources)
    frozen_json(root / "plan.json", plan)
    manifest = root / "manifest.json"
    recipes = curriculum_manifest() if boss_curriculum else frozen_manifest(content)
    if manifest.exists():
        if load_manifest(manifest) != recipes:
            raise ValueError("Frozen manifest changed")
    else:
        save_manifest(manifest, recipes)
    schema = schema_for("observable", reward, content)
    frozen_json(root / "encoder_schema.json", dict(schema=schema, sha256=content_hash(schema)))
    coordinators = {}
    timing_path = root / "timings.json"
    timings = json.loads(timing_path.read_text()) if timing_path.exists() else []
    try:
        for seed in seeds:
            coordinators[seed] = Coordinator(root / f"seed-{seed}", manifest, replace(config, seed=seed, initial_checkpoint=sources[str(seed)]["final"] if boss_curriculum else None))
            if boss_search:
                coordinators[seed].replay.release_memory()
        with Collector(workers) as collector:
            # Interleave completed rounds, so both seeds advance during a long run.
            while any(c.state["phase"] != "done" for c in coordinators.values()):
                for seed, coordinator in coordinators.items():
                    if coordinator.state["phase"] == "done":
                        continue
                    if boss_search:
                        for other_seed, other in coordinators.items():
                            if other_seed != seed:
                                other.replay.release_memory()
                    iteration = coordinator.state["iteration"]
                    while coordinator.state["iteration"] == iteration and coordinator.state["phase"] != "done":
                        phase = coordinator.state["phase"]
                        progress = dict(stage="smoke" if smoke else "training", seed=seed, iteration=iteration, phase=phase)
                        atomic_json(root / "progress.json", progress)
                        if phase != "train":
                            print(progress, flush=True)
                        started = perf_counter()
                        try:
                            coordinator.step(collector)
                        except Exception:
                            coordinator.state["round_failed"] = True
                            coordinator.persist()
                            raise
                        timings.append(dict(seed=seed, iteration=iteration, phase=phase, seconds=perf_counter() - started))
                        atomic_json(timing_path, timings)
            actual = {str(seed): dict(iterations=c.state["iteration"], episodes=len(c.replay.committed),
                                     champion=c.state["champion"], promoted=sum(
                                         json.loads((c.root / f"evaluation-{i}.json").read_text())["promote"]
                                         for i in range(c.state["iteration"]))) for seed, c in coordinators.items()}
            # Update counts are read from completed candidate checkpoint histories, not planned budget.
            from sts2_env.az.network import load_checkpoint
            for seed, c in coordinators.items():
                actual[str(seed)]["updates"] = sum(len(load_checkpoint(c.root / f"candidate-{i}.pt", "observable", reward,
                                                    content)[1]["statistics"]["history"])
                                                   for i in range(c.state["iteration"]))
            if smoke:
                collect_seconds = sum(t["seconds"] for t in timings if t["phase"] == "collect")
                evaluate_seconds = sum(t["seconds"] for t in timings if t["phase"] == "evaluate")
                decision_count = sum(len(e["rows"]) for c in coordinators.values() for e in c.replay.episodes)
                estimate = 2 * iterations * ((collect_seconds / 2) * (long_config.episodes_per_iteration / count) * (long_config.simulations / config.simulations)
                                  + (evaluate_seconds / 2) * (long_config.validation_count / config.validation_count) * (long_config.eval_simulations / config.eval_simulations)
                                  + sum(t["seconds"] for t in timings if t["phase"] == "train") / 2 * (long_config.updates / config.updates))
                if any(c.state.get("round_failed") for c in coordinators.values()) or any(
                        json.loads((c.root / f"evaluation-{i}.json").read_text()).get("restriction") == "round_previously_failed"
                        for c in coordinators.values() for i in range(2)):
                    raise ValueError("Smoke had a failed round; preserve this run and rerun clean after repair")
                report = dict(status="passed", iterations=2, content_version=content, planned_long_iterations=iterations, actual=actual, code_digest=code_digest(), runner_digest=file_digest(__file__),
                              training_decisions=decision_count, collection_seconds=collect_seconds,
                              decisions_per_second=decision_count / collect_seconds,
                              collection_episodes_per_second=(2 * count) / collect_seconds,
                              estimated_full_training_hours=estimate / 3600,
                              estimate_caveat="Linear scaling of smoke budgets and counts; policy, fight length and cache reuse change cost; excludes final tests",
                              test_evaluated=False)
                report["sampling_version"] = config.sampling_version
                report["search_version"] = config.search_version
                atomic_json(root / "smoke_report.json", report)
                atomic_json(root / "progress.json", dict(stage="smoke_complete", **report))
                print(report, flush=True)
                return report
            frozen = {str(seed): dict(initial=str(c.root / "initial.pt"), initial_sha256=file_digest(c.root / "initial.pt"),
                                     final=str(c.root / c.state["champion"]), final_sha256=c.state["champion_hash"])
                      for seed, c in coordinators.items()}
            frozen_json(root / "frozen_final_models.json", frozen)
            if boss_search:
                for coordinator in coordinators.values():
                    coordinator.replay.release_memory()
            test = [r for r in recipes if r.split == "test"]
            reports = {}
            for seed in seeds:
                paths = frozen[str(seed)]
                for role in ("initial", "final"):
                    if file_digest(paths[role]) != paths[f"{role}_sha256"]:
                        raise ValueError("Frozen final model changed")
                reports[str(seed)] = {}
                for mode, budget in (("network", 0), ("search", config.eval_simulations)):
                    atomic_json(root / "progress.json", dict(stage="final_test", seed=seed, mode=mode))
                    old, new = [evaluate_parallel(collector.pool, paths[role], test, budget, 123, EpisodeLimits(),
                                                 root / "test_cache", reward_version=reward, search_version=config.search_version) for role in ("initial", "final")]
                    result = dict(initial=summarize(old), final=summarize(new),
                                  paired=promotion_gate(old, new, required_count=plan["final_test_count"], reward_version=reward),
                                  strata=stratified_pairs(old, new))
                    atomic_json(root / f"test-{seed}-{mode}.json", dict(summary=result, initial=old, final=new))
                    reports[str(seed)][mode] = result
            baseline = evaluate_parallel(collector.pool, frozen["42"]["initial"], test, 0, 123, EpisodeLimits(),
                                         root / "baseline_cache", policy="random", reward_version=reward, search_version=config.search_version)
            atomic_json(root / "baseline-random.json", dict(summary=summarize(baseline), rows=baseline))
            rule_baseline = "unsupported for extended pool; not evaluated"
            if boss_curriculum:
                from sts2_env.az.boss_curriculum import profile
                focused = [r for r in test if profile(r.scenario_id) == "focused"]
                rule_rows = evaluate_parallel(collector.pool, frozen["42"]["initial"], focused, 0, 123, EpisodeLimits(),
                                              root / "baseline_cache", policy="boss_block_rule", reward_version=reward, search_version=config.search_version)
                rule_baseline = summarize(rule_rows)
                atomic_json(root / "baseline-boss-block-rule.json", dict(summary=rule_baseline, rows=rule_rows))
            report = dict(engineering="passed", training="complete", actual=actual, purpose=plan["purpose"],
                          quality_acceptance="not_claimed_quick_verification" if quick else "see_learning_gain", seeds=reports,
                          learning_gain="passed" if all(s["network"]["paired"]["promote"] for s in reports.values()) else "not_met",
                          random_baseline=summarize(baseline), rule_baseline=rule_baseline,
                          generalization="same-family distribution; no held-out family claim")
            atomic_json(root / "report.json", report)
            atomic_json(root / "progress.json", dict(stage="complete", learning_gain=report["learning_gain"]))
            return report
    except BaseException as exc:
        atomic_json(root / "error.json", dict(error=repr(exc)))
        atomic_json(root / "progress.json", dict(stage="failed", error=repr(exc)))
        raise
    finally:
        for c in coordinators.values():
            c.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/az_decks_v3")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--smoke-evidence")
    parser.add_argument("--upgrades", action="store_true")
    parser.add_argument("--selection", action="store_true")
    parser.add_argument("--choice-sets", action="store_true")
    parser.add_argument("--summon", action="store_true")
    parser.add_argument("--boss", action="store_true")
    parser.add_argument("--boss-curriculum", action="store_true")
    parser.add_argument("--boss-search", action="store_true")
    parser.add_argument("--multi", action="store_true")
    parser.add_argument("--morph", action="store_true")
    parser.add_argument("--lifecycle", action="store_true")
    parser.add_argument("--topdeck", action="store_true")
    parser.add_argument("--generated", action="store_true")
    parser.add_argument("--quick", action="store_true", help="8-simulation mechanism verification; keep 256 paired validation cases")
    parser.add_argument("--g1", action="store_true")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--hard", action="store_true")
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    run(args.output, args.smoke, args.workers, args.smoke_evidence, args.hard, args.iterations, args.expanded, args.g1, args.generated, args.quick, args.upgrades, args.topdeck, args.lifecycle, args.selection, args.choice_sets, args.morph, args.multi, args.summon, args.boss, args.boss_curriculum, args.boss_search)
