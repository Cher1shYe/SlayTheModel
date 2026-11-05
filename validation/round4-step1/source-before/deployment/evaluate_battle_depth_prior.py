"""Paired evaluation of network PUCT for the first n battle-tree levels.

Requires STS2_PRIOR_PYD to point to the isolated depth-enabled simulator.
The completed root-prior evaluation provides the 100 paired control runs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time

import torch

from deployment import evaluate_battle_root_prior as root
from deployment.evaluate_combat_dagger import summarize

DEPTHS = (2, 4, 8)
BASELINES = ("mcts", "puct_uniform", "puct")
_depth = None
_prior_seconds = 0.0
_prior_calls = 0
_search_seconds = 0.0
_decisions = 0
_activity_path = None
_activity_seed = None
_activity_started = None
_activity_last = 0.0


def _save_activity(force=False):
    """Persist worker activity even while a long episode is running."""
    global _activity_last
    if _activity_path is None:
        return
    now = time.perf_counter()
    if not force and now - _activity_last < 10:
        return
    data = {"seed": _activity_seed, "depth": _depth, "worker_pid": os.getpid(),
            "elapsed_seconds": now - _activity_started, "combat_decisions_started": _decisions,
            "prior_calls": _prior_calls, "prior_seconds": _prior_seconds,
            "updated_utc": datetime.now(timezone.utc).isoformat()}
    temp = _activity_path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, _activity_path)
    _activity_last = now


def _network_prior(battle):
    global _prior_seconds, _prior_calls
    start = time.perf_counter()
    if hasattr(battle, "legal_action_features_array") and hasattr(battle, "observation_public_array"):
        # The native method creates rows directly in legal_actions() order.
        feats = battle.legal_action_features_array()
        obs = battle.observation_public_array()
        if feats.ndim != 2 or feats.shape[0] == 0:
            raise RuntimeError("invalid native legal-action feature rows")
        action_count = feats.shape[0]
    else:
        actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
        rows, feats = root.combat_action_arrays(battle)
        rows = [tuple(int(x) for x in a) for a in rows]
        if rows != actions or not actions:
            raise RuntimeError("legal action/feature order changed at search node")
        obs = root.public_combat_observation(battle)
        action_count = len(actions)
    with torch.inference_mode():
        logits = root._policy(torch.from_numpy(obs)[None], torch.from_numpy(feats)[None])[0]
        if logits.shape != (action_count,) or not torch.isfinite(logits).all():
            raise RuntimeError("invalid search-node policy logits")
        priors = torch.softmax(logits, dim=0).tolist()
    _prior_calls += 1
    _prior_seconds += time.perf_counter() - start
    _save_activity()
    return priors


def _fixed_plan(battle, seed, combat, simulations, epsilon, is_boss):
    global _search_seconds, _decisions
    actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
    if not actions:
        raise RuntimeError("no legal combat action")
    if len(actions) == 1:
        return actions, 0
    if combat != "mcts-oracle" or _depth not in DEPTHS:
        raise ValueError("invalid oracle search or prior depth")
    _decisions += 1
    _save_activity()
    start = time.perf_counter()
    path, done, _ = battle.mcts_depth_priors(simulations, _network_prior, _depth,
                                              3.0, seed & 0xFFFFFFFF, False, epsilon)
    _search_seconds += time.perf_counter() - start
    path = [tuple(int(x) for x in a) for a in path]
    if not path or path[0] not in actions or int(done) != simulations:
        raise RuntimeError("search returned invalid action or incomplete simulation budget")
    return path[:1], int(done)


def _init_worker(policy_path, armg_path):
    root._init_worker(policy_path, armg_path)
    if not hasattr(root.sim.BattleContext, "mcts_depth_priors"):
        raise RuntimeError("isolated simulator does not export mcts_depth_priors")
    root.collector._mcts_plan = _fixed_plan


def _play(seed, depth, simulations, max_steps, activity_dir=None):
    global _depth, _prior_seconds, _prior_calls, _search_seconds, _decisions
    global _activity_path, _activity_seed, _activity_started, _activity_last
    _depth, _prior_seconds, _prior_calls, _search_seconds = depth, 0.0, 0, 0.0
    start = time.perf_counter()
    _decisions = 0
    _activity_started, _activity_seed, _activity_last = start, seed, 0.0
    _activity_path = Path(activity_dir) / f"worker-{os.getpid()}.json" if activity_dir else None
    try:
        _save_activity(force=True)
        result = dict(root.collector.collect_episode(seed, root._policy, root._armg,
                      battle_mode="mcts-oracle", teacher_sims=simulations,
                      collect_labels=False, max_steps=max_steps))
        result.pop("records", None)
        result.update(arm=f"puct_depth{depth}", depth=depth,
                      elapsed_seconds=time.perf_counter() - start,
                      prior_seconds=_prior_seconds, prior_calls=_prior_calls,
                      search_seconds=_search_seconds)
        return result
    finally:
        if _activity_path is not None:
            _activity_path.unlink(missing_ok=True)
        _activity_path = None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_baseline(directory, policy, armg, simulations, start, count, max_steps):
    """Refuse to compare mismatched settings or silently omit baseline seeds."""
    directory = Path(directory).resolve(strict=True)
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    expected = {"policy_sha256": _sha(policy), "armg_sha256": _sha(armg),
                "seed_base": root.SEED_BASE, "simulations_per_decision": simulations,
                "boss_multiplier": 1, "path_cache": "none", "rollout": "random, all arms",
                "information": "oracle: full future state in both arms",
                "max_steps": max_steps, "ascension": 0,
                "armg_rules": "original ArmG, no overlays"}
    for key, value in expected.items():
        if config.get(key) != value:
            raise ValueError(f"baseline mismatch {key}: {config.get(key)!r} != {value!r}")
    records = [json.loads(x) for x in (directory / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]
    wanted = set(range(root.SEED_BASE + start, root.SEED_BASE + start + count))
    records = [r for r in records if r["arm"] in BASELINES and int(r["seed"]) in wanted]
    for arm in BASELINES:
        group = [r for r in records if r["arm"] == arm]
        if len(group) != count or {int(r["seed"]) for r in group} != wanted:
            raise ValueError(f"baseline {arm} does not contain the requested unique seeds")
        if any(r["status"] != "terminated" for r in group):
            raise ValueError(f"baseline {arm} contains incomplete episodes")
    return config, records


def paired_summary(results):
    arms = (*BASELINES, *(f"puct_depth{d}" for d in DEPTHS))
    groups = {arm: {} for arm in arms}
    for row in results:
        arm, seed = row["arm"], int(row["seed"])
        if arm not in groups or seed in groups[arm]:
            raise ValueError("unexpected arm or duplicate seed")
        groups[arm][seed] = row
    summaries, paired = {}, {}
    for arm, group in groups.items():
        values = list(group.values())
        summary = summarize(values)
        complete = [v for v in values if v["status"] == "terminated"]
        for key in ("prior_seconds", "search_seconds", "prior_calls"):
            summary["mean_" + key + "_completed"] = (sum(r[key] for r in complete) / len(complete)
                                                        if complete and all(key in r for r in complete) else None)
        summaries[arm] = summary
    for depth in DEPTHS:
        treatment = f"puct_depth{depth}"
        comparisons = (*BASELINES, *(f"puct_depth{d}" for d in DEPTHS if d < depth))
        for baseline in comparisons:
            pairs = [(groups[baseline][s], p) for s, p in groups[treatment].items()
                     if s in groups[baseline] and p["status"] == groups[baseline][s]["status"] == "terminated"]
            differences = [float(p["floor"] - b["floor"]) for b, p in pairs]
            mean = sum(differences) / len(differences) if differences else None
            se = (math.sqrt(sum((d - mean)**2 for d in differences) /
                            (len(differences) * (len(differences) - 1))) if len(differences) > 1 else None)
            paired[f"{treatment}_vs_{baseline}"] = {
                "complete_pairs": len(pairs), "mean_floor_difference": mean,
                "floor_difference_se": se,
                "treatment_only_wins": sum(bool(p.get("won")) and not bool(b.get("won")) for b, p in pairs),
                "baseline_only_wins": sum(bool(b.get("won")) and not bool(p.get("won")) for b, p in pairs)}
    return {"arms": summaries, "paired": paired}


def run(policy_path, armg_path, baseline_dir, out_dir, *, start, count, workers, simulations, max_steps):
    if min(count, workers, simulations, max_steps) < 1 or start < 0:
        raise ValueError("invalid evaluation settings")
    if not root._extension or not hasattr(root.sim.BattleContext, "mcts_depth_priors"):
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated depth-enabled extension")
    policy_path, armg_path = Path(policy_path).resolve(strict=True), Path(armg_path).resolve(strict=True)
    baseline_config, baseline = load_baseline(baseline_dir, policy_path, armg_path, simulations, start, count, max_steps)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    policy_snapshot, armg_snapshot = out_dir / "policy.pt", out_dir / "armg.pt"
    shutil.copyfile(policy_path, policy_snapshot)
    shutil.copyfile(armg_path, armg_snapshot)
    activity_dir = out_dir / "active"
    activity_dir.mkdir()
    config = {"policy_path": str(policy_path), "policy_sha256": _sha(policy_snapshot),
              "armg_path": str(armg_path), "armg_sha256": _sha(armg_snapshot),
              "baseline_dir": str(Path(baseline_dir).resolve()),
              "baseline_simulator_sha256": baseline_config["simulator_sha256"],
              "simulator_path": str(Path(root._extension).resolve()),
              "simulator_sha256": _sha(root._extension), "seed_start": root.SEED_BASE + start,
              "count": count, "depths": list(DEPTHS), "depth_convention": "root is level 1",
              "simulations_per_decision": simulations, "max_steps": max_steps,
              "workers": workers, "rollout": "random, all arms",
              "information": "oracle: full future state in both arms",
              "puct_c": 3.0, "mcts_ucb_c": 3 * 2**0.5,
              "path_cache": "none", "boss_multiplier": 1,
              "ascension": 0, "started_utc": datetime.now(timezone.utc).isoformat()}
    (out_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    records, started = [], time.perf_counter()
    def save_progress(state):
        active = []
        for path in activity_dir.glob("worker-*.json"):
            try:
                active.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        progress = {"state": state, "completed_jobs": len(records), "total_jobs": count * len(DEPTHS),
                    "elapsed_seconds": time.perf_counter() - started,
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                    "active_episodes": active,
                    **paired_summary(baseline + records)}
        tmp = out_dir / "progress.tmp"
        tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(tmp, out_dir / "progress.json")
    save_progress("running")
    with (out_dir / "episodes.jsonl").open("x", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker,
                                 initargs=(str(policy_snapshot.resolve()), str(armg_snapshot.resolve()))) as pool:
            jobs = {pool.submit(_play, root.SEED_BASE + start + i, depth, simulations, max_steps, str(activity_dir.resolve())):
                    (root.SEED_BASE + start + i, depth) for i in range(count) for depth in DEPTHS}
            pending = set(jobs)
            while pending:
                finished, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                for future in finished:
                    seed, depth = jobs[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = {"seed": seed, "arm": f"puct_depth{depth}", "depth": depth,
                                  "status": "error", "won": False, "floor": 0,
                                  "error": f"{type(exc).__name__}: {exc}"}
                    records.append(record)
                    out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    out.flush()
                    if len(records) % 20 == 0 or len(records) == len(jobs):
                        print(json.dumps({"progress": len(records), "total": len(jobs)}), flush=True)
                save_progress("running")
    report = {"config": config, **paired_summary(baseline + records),
              "elapsed_seconds": time.perf_counter() - started,
              "episodes_path": str((out_dir / "episodes.jsonl").resolve())}
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    save_progress("completed")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy-checkpoint", required=True, type=Path)
    p.add_argument("--armg-checkpoint", required=True, type=Path)
    p.add_argument("--baseline-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=10000)
    p.add_argument("--max-steps", type=int, default=5000)
    a = p.parse_args(argv)
    run(a.policy_checkpoint, a.armg_checkpoint, a.baseline_dir, a.out_dir,
        start=a.start, count=a.seeds, workers=a.workers,
        simulations=a.simulations, max_steps=a.max_steps)


if __name__ == "__main__":
    main()
