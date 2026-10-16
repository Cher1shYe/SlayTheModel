"""Paired observable evaluation and a fixed, reproducible promotion gate."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from time import perf_counter
import numpy as np

from .adapter import ObservableCombatAdapter
from .config import EpisodeLimits, atomic_json, content_hash, derive_seed
from .encoder import encode_information
from .observable_puct import plan_observable
from .rewards import V1, V2, V3, V4, V5, V6, terminal_reward, validate_reward
from .search_config import LEGACY, validate_search


def promotion_gate(champion, candidate, seed=1729, bootstrap_samples=10_000, required_count=256, reward_version=V1):
    validate_reward(reward_version)
    if len(champion) != len(candidate) or not champion:
        raise ValueError("Paired evaluation requires equal nonempty results")
    if len({r["scenario_id"] for r in champion}) != len(champion):
        raise ValueError("Duplicate validation scenario")
    for old, new in zip(champion, candidate):
        if old["scenario_id"] != new["scenario_id"]:
            raise ValueError("Unpaired validation results")
        for row in (old, new):
            expected = (terminal_reward(row["termination_reason"], row["final_hp"], row["initial_hp"],
                                       row["enemy_final_hp"], row["enemy_max_hp"], reward_version,
                                       enemy_initial_hp=row.get("enemy_initial_hp"), enemy_roster=row.get("enemy_roster"))
                        if reward_version in (V2, V3, V4, V5, V6) else row["reward"])
            if (not np.isfinite(row["reward"]) or not -1 <= row["reward"] <= 1
                    or row["reward"] != expected or (reward_version == V1 and row["reward"] not in (-1, 1))):
                raise ValueError("Invalid evaluation utility")
    delta = np.array([b["reward"] - a["reward"] for a, b in zip(champion, candidate)], dtype=float)
    wins = np.array([int(b.get("termination_reason", "win" if b["reward"] == 1 else "death") == "win")
                     - int(a.get("termination_reason", "win" if a["reward"] == 1 else "death") == "win")
                     for a, b in zip(champion, candidate)], dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(bootstrap_samples)
    win_means = np.empty(bootstrap_samples)
    groups = {}
    for i, (old, new) in enumerate(zip(champion, candidate)):
        if old.get("encounter_id") != new.get("encounter_id"):
            raise ValueError("Paired encounter mismatch")
        if reward_version in (V3, V4, V5, V6):
            stratum = tuple(old[k] for k in ("family_id", "encounter_id", "initial_hp"))
            if stratum != tuple(new[k] for k in ("family_id", "encounter_id", "initial_hp")):
                raise ValueError("Paired stratum mismatch")
        else:
            stratum = old.get("encounter_id", "legacy")
        groups.setdefault(stratum, []).append(i)
    # Bound memory for larger validation manifests.
    for start in range(0, bootstrap_samples, 256):
        size = min(256, bootstrap_samples - start)
        indices = np.concatenate([np.asarray(group)[rng.integers(len(group), size=(size, len(group)))]
                                  for group in groups.values()], axis=1)
        means[start:start + size] = delta[indices].mean(axis=1)
        win_means[start:start + size] = wins[indices].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    clean = all(not r.get("errors", 0) and not r.get("illegal_actions", 0) for r in champion + candidate)
    eligible = len(delta) == required_count
    win_low, win_high = np.percentile(win_means, [2.5, 97.5])
    win_priority = reward_version == V1 or win_low > 0 or bool(np.all(wins == 0))
    return dict(promote=bool(eligible and clean and low > 0 and win_priority), eligible=eligible,
                reward_version=reward_version, win_priority_satisfied=bool(win_priority),
                mean_win_difference=float(wins.mean()), win_difference_ci95=[float(win_low), float(win_high)],
                mean_utility_difference=float(delta.mean()), confidence_interval=[float(low), float(high)],
                scenarios=len(delta), bootstrap_samples=bootstrap_samples, statistics_seed=seed,
                clean=clean)


def evaluate(model, version, recipes, simulations=256, seed=123, limits=EpisodeLimits(),
             error_dir="output/az_errors", policy="network", start_index=0, reward_version=V1, search_version=LEGACY):
    validate_search(search_version)
    if policy not in ("network", "random", "rule", "oracle_mcts", "boss_block_rule"):
        raise ValueError("Unknown evaluation policy")
    if simulations < 0 or any(r.split not in ("validation", "test") for r in recipes):
        raise ValueError("Evaluation requires held-out recipes and nonnegative budget")
    results = []
    for index, recipe in enumerate(recipes, start=start_index):
        env = ObservableCombatAdapter(recipe, limits, error_dir, reward_version)
        latencies = []
        while not env.outcome().done:
            started = perf_counter()
            decision_seed = derive_seed(seed, 0, index, f"eval-{len(env.actions)}")
            try:
                if policy == "random":
                    action = int(np.random.default_rng(decision_seed).choice(np.flatnonzero(env.information.legal_mask)))
                elif policy == "boss_block_rule":
                    from .boss_curriculum import block_rule_action
                    action = block_rule_action(env.information)
                elif policy == "rule":
                    action = rule_action(env.information)
                elif policy == "oracle_mcts":
                    from sts2_env.search.mcts import search
                    action = search(env.world, simulations=simulations, seed=decision_seed).action
                elif simulations:
                    action = plan_observable(env.information, model, model_version=version, budget=simulations,
                                             search_seed=decision_seed, search_version=search_version).action
                else:
                    priors, _ = model.predict(encode_information(env.information))
                    action = int(np.argmax(priors))
                latencies.append(perf_counter() - started)
                env.step(action)
            except Exception as exc:
                atomic_json(Path(error_dir) / f"evaluation-{content_hash([version, index, simulations, policy])}.json",
                            dict(trace=env.trace(), error=repr(exc)))
                raise
        outcome = asdict(env.outcome())
        outcome["enemy_roster"] = list(outcome["enemy_roster"])
        results.append(dict(outcome, scenario_id=recipe.scenario_id, family_id=recipe.family_id,
                            errors=0, illegal_actions=0, decision_seconds=latencies, reward_version=reward_version,
                            encounter_id=recipe.encounter_id))
        if search_version != LEGACY:
            results[-1]["search_version"] = search_version
    return results


def rule_action(info):
    """Public-only starter rule: Bash before strikes, then defend, then end turn."""
    from sts2_env.gym_env.action_space import action_to_card_and_target
    priorities = {"BASH": 3, "STRIKE_IRONCLAD": 2, "DEFEND_IRONCLAD": 1}
    actions = np.flatnonzero(info.legal_mask)
    def rank(action):
        if action == 0:
            return (0, 0)
        slot, _ = action_to_card_and_target(int(action))
        return (priorities[info.hand[slot]], -int(action))
    return int(max(actions, key=rank))


def summarize(results):
    latencies = [s for r in results for s in r["decision_seconds"]]
    wins = [r for r in results if r["termination_reason"] == "win"]
    return dict(episodes=len(results), win_rate=len(wins) / len(results),
                mean_utility=float(np.mean([r["reward"] for r in results])),
                mean_final_hp=float(np.mean([r["final_hp"] for r in results])),
                mean_winning_hp=float(np.mean([r["final_hp"] for r in wins])) if wins else None,
                mean_turns=float(np.mean([r["turns"] for r in results])),
                mean_decisions=float(np.mean([r["decisions"] for r in results])) if all("decisions" in r for r in results) else None,
                death_rate=sum(r["termination_reason"] == "death" for r in results) / len(results),
                time_limit_rate=sum(r["termination_reason"] == "time_limit" for r in results) / len(results),
                exception_rate=sum(bool(r.get("errors")) for r in results) / len(results),
                illegal_actions=sum(r.get("illegal_actions", 0) for r in results),
                decision_seconds_p50=float(np.percentile(latencies, 50)),
                decision_seconds_p95=float(np.percentile(latencies, 95)))


def compare(champion, candidate, champion_version, candidate_version, recipes, simulations=256,
            seed=123, limits=EpisodeLimits(), error_dir="output/az_errors", evaluation_runner=None, reward_version=V1, search_version=LEGACY):
    if any(r.split != "validation" for r in recipes):
        raise ValueError("Promotion must use validation only")
    reports = {}
    for budget in (0, simulations):
        if evaluation_runner is None:
            old = evaluate(champion, champion_version, recipes, budget, seed, limits, error_dir, reward_version=reward_version, search_version=search_version)
            new = evaluate(candidate, candidate_version, recipes, budget, seed, limits, error_dir, reward_version=reward_version, search_version=search_version)
        else:
            old = evaluation_runner("champion", budget)
            new = evaluation_runner("candidate", budget)
        reports["network" if budget == 0 else "search"] = dict(champion=old, candidate=new,
            champion_summary=summarize(old), candidate_summary=summarize(new), gate=promotion_gate(old, new, reward_version=reward_version),
            by_encounter={enc: dict(champion=summarize([r for r in old if r["encounter_id"] == enc]),
                                   candidate=summarize([r for r in new if r["encounter_id"] == enc]))
                          for enc in sorted({r["encounter_id"] for r in old})})
    if reward_version in (V3, V4, V5, V6):
        for report in reports.values():
            report["by_stratum"] = stratified_pairs(report["champion"], report["candidate"])
    return dict(modes=reports, promote=reports["network"]["gate"]["promote"],
                promotion_policy="network-only-v1", search_role="observation", simulations=simulations)


def stratified_pairs(old, new):
    result = {}
    for fields in (("family_id",), ("encounter_id",), ("initial_hp",), ("family_id", "encounter_id", "initial_hp")):
        label = "/".join(fields)
        result[label] = {}
        for key in sorted({tuple(row[f] for f in fields) for row in old}):
            result[label]["/".join(map(str, key))] = dict(
                initial=summarize([r for r in old if tuple(r[f] for f in fields) == key]),
                final=summarize([r for r in new if tuple(r[f] for f in fields) == key]))
    return result


@dataclass(frozen=True)
class EvaluationJob:
    checkpoint: str
    checkpoint_hash: str
    recipe: dict
    index: int
    simulations: int
    seed: int
    limits: EpisodeLimits
    error_dir: str
    policy: str = "network"
    reward_version: str = V1
    search_version: str = LEGACY


_evaluation_models = {}


def evaluate_job(job):
    from .network import load_checkpoint
    from .scenarios import CombatScenario
    from .self_play import file_digest
    if file_digest(job.checkpoint) != job.checkpoint_hash:
        raise ValueError("Evaluation checkpoint changed")
    if job.checkpoint_hash not in _evaluation_models:
        _evaluation_models.clear()
        _evaluation_models[job.checkpoint_hash] = load_checkpoint(job.checkpoint, "observable", job.reward_version,
                                                                job.recipe["content_manifest_version"])
    model, metadata = _evaluation_models[job.checkpoint_hash]
    if metadata["reward_version"] != job.reward_version or metadata["content_manifest_version"] != job.recipe["content_manifest_version"]:
        raise ValueError("Evaluation reward mismatch")
    return evaluate(model, metadata["model_version"], [CombatScenario.from_dict(job.recipe)],
                    job.simulations, job.seed, job.limits, job.error_dir, job.policy, job.index, job.reward_version, job.search_version)[0]


def evaluate_parallel(pool, checkpoint, recipes, simulations, seed, limits, cache_dir, policy="network", reward_version=V1, search_version=LEGACY):
    """Cache complete scenario results; identities include recipes, model and code."""
    from .network import code_digest
    from .self_play import file_digest
    checkpoint = str(Path(checkpoint).resolve())
    digest = file_digest(checkpoint)
    cache_dir = Path(cache_dir)
    code = code_digest()
    jobs = [EvaluationJob(checkpoint, digest, r.to_dict(), i, simulations, seed, limits,
                          str(cache_dir / "errors"), policy, reward_version, search_version) for i, r in enumerate(recipes)]
    paths, results, pending = [], [None] * len(jobs), []
    for i, job in enumerate(jobs):
        identity = content_hash(dict(job=asdict(job), code=code))
        path = cache_dir / f"{identity}.json"
        paths.append(path)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["sha256"] != content_hash(payload["result"]):
                raise ValueError("Corrupted evaluation cache")
            results[i] = payload["result"]
        else:
            pending.append((i, job))
    for (i, _), result in zip(pending, pool.map(evaluate_job, [j for _, j in pending])):
        atomic_json(paths[i], dict(result=result, sha256=content_hash(result)))
        results[i] = result
    return results
