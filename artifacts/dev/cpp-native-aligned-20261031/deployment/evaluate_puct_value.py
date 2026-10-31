"""Paired 512-simulation hidden-information PUCT rollout versus value test.

Set STS2_PRIOR_PYD to the isolated value-enabled simulator before starting.
All expanded nodes use the same policy prior; a game and its search use
independent seeds. The only deliberate treatment change is the leaf/terminal
evaluation method. Each decision searches again and executes one root action.
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

# Import the root helper first: it preloads the isolated extension before
# agent.common imports sts2_sim (including in spawned worker processes).
from deployment import evaluate_battle_root_prior as root
from deployment import evaluate_battle_depth_prior as depth_eval
from agent.combat_dagger import CombatValue, load_combat_checkpoint
from deployment.evaluate_combat_dagger import summarize

ARMS = ("rollout", "value")
SEED_BASE = 36_020_000
# The simulator caps a tree traversal at 500 actions; this enables PUCT at
# every expanded tree node, including beyond the previous 8-level experiment.
ALL_DEPTH = 500
_value = None
_arm = None
_search_seed = 0
_decisions = 0
_value_calls = 0
_value_seconds = 0.0
_search_seconds = 0.0
_activity_path = None
_activity_seed = None
_started = 0.0
_activity_last = 0.0


def _activity(force=False):
    global _activity_last
    now = time.perf_counter()
    if _activity_path is None or (not force and now - _activity_last < 10):
        return
    data = {"seed": _activity_seed, "arm": _arm, "worker_pid": os.getpid(),
            "elapsed_seconds": now - _started, "combat_decisions_started": _decisions,
            "policy_calls": depth_eval._prior_calls, "value_calls": _value_calls,
            "updated_utc": datetime.now(timezone.utc).isoformat()}
    temp = _activity_path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temp, _activity_path)
        _activity_last = now
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _network_prior(battle):
    priors = depth_eval._network_prior(battle)
    _activity()
    return priors


def _network_value(battle):
    global _value_calls, _value_seconds
    start = time.perf_counter()
    obs = battle.observation_public_array() if hasattr(battle, "observation_public_array") else root.public_combat_observation(battle)
    with torch.inference_mode():
        main, _, _ = _value(torch.from_numpy(obs)[None])
        if main.numel() != 1 or not torch.isfinite(main).all():
            raise RuntimeError("invalid value estimate")
        result = float(main.item())
    _value_calls += 1
    _value_seconds += time.perf_counter() - start
    _activity()
    return result


def _plan(battle, _game_derived_seed, combat, simulations, epsilon, _is_boss):
    global _decisions, _search_seconds
    if combat != "mcts-resampled" or _arm not in ARMS:
        raise ValueError("invalid hidden PUCT evaluation mode")
    actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
    if not actions:
        raise RuntimeError("no legal combat action")
    if len(actions) == 1:
        return actions, 0
    seed = (_search_seed + 7919 * _decisions) & 0xFFFFFFFF
    _decisions += 1
    _activity()
    start = time.perf_counter()
    path, done, _ = battle.mcts_depth_priors(
        simulations, _network_prior, ALL_DEPTH, 3.0, seed, False, epsilon, True,
        _network_value if _arm == "value" else None)
    _search_seconds += time.perf_counter() - start
    path = [tuple(int(x) for x in a) for a in path]
    if not path or path[0] not in actions or int(done) != simulations:
        raise RuntimeError("invalid action or incomplete search budget")
    return path[:1], int(done)


def _init_worker(policy_path, armg_path):
    global _value
    depth_eval._init_worker(policy_path, armg_path)
    depth_eval._activity_path = None
    _value = CombatValue().eval()
    load_combat_checkpoint(policy_path, root._policy, _value)
    root.collector._mcts_plan = _plan


def _play(seed, arm, simulations, max_steps, search_seed, activity_dir):
    global _arm, _search_seed, _decisions, _value_calls, _value_seconds, _search_seconds
    global _activity_path, _activity_seed, _started, _activity_last
    _arm, _search_seed, _decisions = arm, search_seed, 0
    _value_calls, _value_seconds, _search_seconds = 0, 0.0, 0.0
    depth_eval._prior_calls, depth_eval._prior_seconds = 0, 0.0
    _started, _activity_seed, _activity_last = time.perf_counter(), seed, 0.0
    _activity_path = Path(activity_dir) / f"worker-{os.getpid()}.json"
    try:
        _activity(force=True)
        result = dict(root.collector.collect_episode(seed, root._policy, root._armg,
                      battle_mode="mcts-resampled", teacher_sims=simulations,
                      resample_hidden=True, collect_labels=False, max_steps=max_steps))
        result.pop("records", None)
        result.update(arm=arm, elapsed_seconds=time.perf_counter() - _started,
                      prior_calls=depth_eval._prior_calls, prior_seconds=depth_eval._prior_seconds,
                      value_calls=_value_calls, value_seconds=_value_seconds,
                      search_seconds=_search_seconds)
        return result
    finally:
        try:
            _activity_path.unlink(missing_ok=True)
        except OSError:
            pass
        _activity_path = None


def paired_summary(records):
    groups = {a: {} for a in ARMS}
    for item in records:
        arm, seed = item["arm"], int(item["seed"])
        if arm not in groups or seed in groups[arm]:
            raise ValueError("unexpected arm or duplicated seed")
        groups[arm][seed] = item
    summaries = {}
    for arm, group in groups.items():
        rows = list(group.values())
        result = summarize(rows)
        done = [r for r in rows if r["status"] == "terminated"]
        for key in ("prior_calls", "prior_seconds", "value_calls", "value_seconds", "search_seconds"):
            result["mean_" + key + "_completed"] = (sum(r[key] for r in done) / len(done)
                                                       if done and all(key in r for r in done) else None)
        summaries[arm] = result
    pairs = [(r, groups["value"][seed]) for seed, r in groups["rollout"].items()
             if seed in groups["value"] and r["status"] == groups["value"][seed]["status"] == "terminated"]
    ds = [float(v["floor"] - r["floor"]) for r, v in pairs]
    mean = sum(ds) / len(ds) if ds else None
    se = math.sqrt(sum((d - mean) ** 2 for d in ds) / (len(ds) * (len(ds) - 1))) if len(ds) > 1 else None
    paired = {"complete_pairs": len(ds), "mean_floor_difference": mean,
              "floor_difference_se": se,
              "value_only_wins": sum(bool(v.get("won")) and not bool(r.get("won")) for r, v in pairs),
              "rollout_only_wins": sum(bool(r.get("won")) and not bool(v.get("won")) for r, v in pairs)}
    return {"arms": summaries, "paired_value_vs_rollout": paired}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(policy_path, armg_path, out_dir, *, start=0, count=100, workers=8,
        simulations=512, max_steps=5000, search_seed=0x4B19A37D):
    if min(count, workers, simulations, max_steps) < 1 or start < 0:
        raise ValueError("invalid evaluation settings")
    if not 0 <= search_seed <= 0xFFFFFFFF:
        raise ValueError("search seed must be a 32-bit unsigned integer")
    if not root._extension or not hasattr(root.sim.BattleContext, "mcts_depth_priors"):
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated value-enabled extension")
    policy_path, armg_path = Path(policy_path).resolve(strict=True), Path(armg_path).resolve(strict=True)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    policy_snapshot, armg_snapshot = out_dir / "policy.pt", out_dir / "armg.pt"
    shutil.copyfile(policy_path, policy_snapshot)
    shutil.copyfile(armg_path, armg_snapshot)
    activity_dir = out_dir / "active"
    activity_dir.mkdir()
    config = {"policy_path": str(policy_path), "policy_sha256": _sha(policy_snapshot),
              "value_checkpoint": str(policy_path), "armg_path": str(armg_path), "armg_sha256": _sha(armg_snapshot),
              "simulator_path": str(Path(root._extension).resolve()), "simulator_sha256": _sha(root._extension),
              "seed_start": SEED_BASE + start, "count": count, "arms": list(ARMS),
              "depth": ALL_DEPTH, "depth_convention": "all expanded tree nodes, max traversal 500 actions",
              "simulations_per_decision": simulations, "max_steps": max_steps, "workers": workers,
              "ascension": 0, "information": "resampled hidden state; public-observation policy; approximate belief",
              "root_action": "most visited root action across sampled states", "path_cache": "none",
              "rollout_evaluation": "random rollout; existing terminal_score",
              "value_evaluation": "main value at nonterminal expanded leaf; terminal win + remaining HP/maxHP",
              "puct_c": 3.0, "boss_multiplier": 1, "armg_rules": "original ArmG, no overlays",
              "search_rng": "(search_seed + 7919 * decision_index) mod 2^32; independent of game seed",
              "search_seed": search_seed, "started_utc": datetime.now(timezone.utc).isoformat()}
    (out_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    records, started = [], time.perf_counter()
    def save(state):
        active = []
        for path in activity_dir.glob("worker-*.json"):
            try:
                active.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        result = {"state": state, "completed_jobs": len(records), "total_jobs": count * len(ARMS),
                  "elapsed_seconds": time.perf_counter() - started,
                  "updated_utc": datetime.now(timezone.utc).isoformat(),
                  "active_episodes": active, **paired_summary(records)}
        tmp = out_dir / "progress.tmp"
        try:
            tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(tmp, out_dir / "progress.json")
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return result
    save("running")
    with (out_dir / "episodes.jsonl").open("x", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker,
                                 initargs=(str(policy_snapshot.resolve()), str(armg_snapshot.resolve()))) as pool:
            jobs = {pool.submit(_play, SEED_BASE + start + i, arm, simulations, max_steps,
                                search_seed, str(activity_dir.resolve())): (SEED_BASE + start + i, arm)
                    for i in range(count) for arm in ARMS}
            pending = set(jobs)
            while pending:
                finished, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                for future in finished:
                    seed, arm = jobs[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = {"seed": seed, "arm": arm, "status": "error", "won": False,
                                  "floor": 0, "error": f"{type(exc).__name__}: {exc}"}
                    records.append(record)
                    out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    out.flush()
                save("running")
    report = {"config": config, **save("completed"),
              "episodes_path": str((out_dir / "episodes.jsonl").resolve())}
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy-checkpoint", required=True, type=Path)
    p.add_argument("--armg-checkpoint", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=512)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--search-seed", type=int, default=0x4B19A37D)
    a = p.parse_args(argv)
    run(a.policy_checkpoint, a.armg_checkpoint, a.out_dir, start=a.start, count=a.seeds,
        workers=a.workers, simulations=a.simulations, max_steps=a.max_steps, search_seed=a.search_seed)


if __name__ == "__main__":
    main()
