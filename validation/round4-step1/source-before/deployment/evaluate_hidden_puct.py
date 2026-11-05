"""Evaluate public-information PUCT with an independently seeded search RNG.

Set STS2_PRIOR_PYD to a simulator extension with hidden-state depth PUCT.
The episode seed controls the environment only; search seeds use a separate,
fixed stream indexed by decision, and never include that environment seed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import time

from deployment import evaluate_battle_depth_prior as depth_eval
from deployment import evaluate_battle_root_prior as root
from deployment.evaluate_combat_dagger import summarize

_depth = 1
_search_seed = 0
_decisions = 0
_activity_path = None
_activity_seed = None
_started = 0.0
_activity_last = 0.0


def _activity(force=False):
    """Best-effort reporting: Windows file sharing must never fail a game."""
    global _activity_last
    now = time.perf_counter()
    if _activity_path is None or (not force and now - _activity_last < 10):
        return
    data = {"seed": _activity_seed, "depth": _depth, "worker_pid": os.getpid(),
            "elapsed_seconds": now - _started, "combat_decisions_started": _decisions,
            "prior_calls": depth_eval._prior_calls,
            "updated_utc": datetime.now(timezone.utc).isoformat()}
    temp = _activity_path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temp, _activity_path)
        _activity_last = now
    except OSError:
        # Activity is observational, so failure cannot affect search or outcome.
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _network_prior(battle):
    priors = depth_eval._network_prior(battle)
    _activity()
    return priors


def _plan(battle, _game_derived_seed, combat, simulations, epsilon, _is_boss):
    """Return only the freshly searched root action, never a future plan."""
    global _decisions
    if combat != "mcts-resampled":
        raise ValueError("hidden PUCT requires the resampled combat mode")
    actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
    if not actions:
        raise RuntimeError("no legal combat action")
    if len(actions) == 1:
        return actions, 0
    seed = (_search_seed + 7919 * _decisions) & 0xFFFFFFFF
    _decisions += 1
    _activity()
    path, done, _ = battle.mcts_depth_priors(simulations, _network_prior, _depth,
                                              3.0, seed, False, epsilon, True)
    path = [tuple(int(x) for x in a) for a in path]
    if not path or path[0] not in actions or int(done) != simulations:
        raise RuntimeError("hidden PUCT returned an illegal action or incomplete budget")
    return path[:1], int(done)


def _init_worker(policy_path, armg_path):
    depth_eval._init_worker(policy_path, armg_path)
    depth_eval._activity_path = None
    root.collector._mcts_plan = _plan


def _play(seed, depth, simulations, max_steps, search_seed, activity_dir):
    global _depth, _search_seed, _decisions, _activity_path, _activity_seed, _started, _activity_last
    _depth, _search_seed, _decisions = depth, search_seed, 0
    depth_eval._prior_calls = 0
    depth_eval._prior_seconds = 0.0
    _started, _activity_seed, _activity_last = time.perf_counter(), seed, 0.0
    _activity_path = Path(activity_dir) / f"worker-{os.getpid()}.json"
    try:
        _activity(force=True)
        result = dict(root.collector.collect_episode(seed, root._policy, root._armg,
                      battle_mode="mcts-resampled", teacher_sims=simulations,
                      resample_hidden=True, collect_labels=False, max_steps=max_steps))
        result.pop("records", None)
        result.update(arm=f"hidden_puct_depth{depth}", depth=depth,
                      elapsed_seconds=time.perf_counter() - _started,
                      prior_calls=depth_eval._prior_calls,
                      prior_seconds=depth_eval._prior_seconds)
        return result
    finally:
        try:
            _activity_path.unlink(missing_ok=True)
        except OSError:
            pass
        _activity_path = None


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(policy_path, armg_path, out_dir, *, start=0, count=1, depths=(1,), workers=8,
        simulations=1024, max_steps=5000, search_seed=0x4B19A37D):
    if min(count, workers, simulations, max_steps) < 1 or start < 0:
        raise ValueError("invalid evaluation settings")
    if not depths or any(d < 1 for d in depths) or len(set(depths)) != len(depths):
        raise ValueError("depths must be distinct positive integers")
    if not 0 <= search_seed <= 0xFFFFFFFF:
        raise ValueError("search seed must be a 32-bit unsigned integer")
    if not root._extension or not hasattr(root.sim.BattleContext, "mcts_depth_priors"):
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated hidden PUCT extension")
    policy_path, armg_path = Path(policy_path).resolve(strict=True), Path(armg_path).resolve(strict=True)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    policy_snapshot, armg_snapshot = out_dir / "policy.pt", out_dir / "armg.pt"
    shutil.copyfile(policy_path, policy_snapshot)
    shutil.copyfile(armg_path, armg_snapshot)
    activity_dir = out_dir / "active"
    activity_dir.mkdir()
    config = {"policy_path": str(policy_path), "policy_sha256": _sha(policy_snapshot),
              "armg_path": str(armg_path), "armg_sha256": _sha(armg_snapshot),
              "simulator_path": str(Path(root._extension).resolve()), "simulator_sha256": _sha(root._extension),
              "seed_start": 35_000_000 + start, "count": count, "depths": list(depths),
              "depth_convention": "root is level 1", "simulations_per_decision": simulations,
              "max_steps": max_steps, "workers": workers, "ascension": 0,
              "information": "resampled hidden state; public-observation policy; approximate belief",
              "root_action": "most visited root action across sampled states", "path_cache": "none",
              "rollout": "random", "puct_c": 3.0, "boss_multiplier": 1,
              "armg_rules": "original ArmG, no overlays",
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
        by_depth = {f"depth{d}": summarize([r for r in records if r["depth"] == d]) for d in depths}
        result = {"state": state, "completed_jobs": len(records), "total_jobs": count * len(depths),
                  "elapsed_seconds": time.perf_counter() - started,
                  "updated_utc": datetime.now(timezone.utc).isoformat(),
                  "active_episodes": active, "arms": by_depth}
        tmp = out_dir / "progress.tmp"
        try:
            tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(tmp, out_dir / "progress.json")
        except OSError:
            # A reader may temporarily prevent replacement on Windows. Progress
            # reporting cannot change game outcomes or stop the experiment.
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
            jobs = {pool.submit(_play, 35_000_000 + start + i, depth, simulations, max_steps,
                                search_seed, str(activity_dir.resolve())): (35_000_000 + start + i, depth)
                    for i in range(count) for depth in depths}
            pending = set(jobs)
            while pending:
                finished, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                for future in finished:
                    seed, depth = jobs[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = {"seed": seed, "arm": f"hidden_puct_depth{depth}", "depth": depth,
                                  "status": "error", "won": False, "floor": 0,
                                  "error": f"{type(exc).__name__}: {exc}"}
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
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--depths", type=int, nargs="+", default=[1])
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=1024)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--search-seed", type=int, default=0x4B19A37D)
    a = p.parse_args(argv)
    run(a.policy_checkpoint, a.armg_checkpoint, a.out_dir, start=a.start, count=a.seeds,
        depths=tuple(a.depths), workers=a.workers, simulations=a.simulations,
        max_steps=a.max_steps, search_seed=a.search_seed)


if __name__ == "__main__":
    main()
