"""Paired pure-MCTS versus root-prior PUCT battle evaluation.

Set STS2_PRIOR_PYD to an isolated sts2_sim extension *before* launching.  Both
arms use the same frozen ArmG and simulator, oracle information, fixed rollout
type and exactly the requested number of simulations per non-forced decision.
The prior is computed once per root and the returned plan is never cached.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import sys
import time

# agent.common ordinarily imports the production extension. Preload the
# independently built evaluation extension, without modifying a running trainer.
_extension = os.environ.get("STS2_PRIOR_PYD")
if _extension:
    _extension_path = Path(_extension).resolve(strict=True)
    _existing = sys.modules.get("sts2_sim")
    if _existing is not None:
        _loaded_path = getattr(_existing, "__file__", None)
        if not _loaded_path or Path(_loaded_path).resolve() != _extension_path:
            raise RuntimeError("sts2_sim is already loaded from a different extension; start a fresh process")
    else:
        _spec = importlib.util.spec_from_file_location("sts2_sim", str(_extension_path))
        if _spec is None or _spec.loader is None:
            raise RuntimeError("invalid isolated STS2_PRIOR_PYD extension")
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["sts2_sim"] = _module
        _spec.loader.exec_module(_module)

import torch

from agent.armg import ArmGScorer
from agent.combat_dagger import CombatPolicy, load_combat_checkpoint
import agent.combat_dagger_collect as collector
from agent.common import combat_action_arrays, public_combat_observation, sim
from deployment.evaluate_armg import load_armg_checkpoint
from deployment.evaluate_combat_dagger import summarize

SEED_BASE = 31_010_000
ARMS = ("mcts", "puct_uniform", "puct")
_policy = _armg = None
_current_arm = None
_prior_seconds = 0.0
_search_seconds = 0.0


def _fixed_plan(battle, seed, combat, simulations, epsilon, is_boss):
    """One root search per decision, with no boss multiplier or cached plan."""
    global _prior_seconds, _search_seconds
    actions = [tuple(int(x) for x in a) for a in battle.legal_actions()]
    if not actions:
        raise RuntimeError("no legal combat action")
    if len(actions) == 1:
        return actions, 0
    if combat != "mcts-oracle":
        raise ValueError("this comparison fixes oracle information")
    if _current_arm in ("puct", "puct_uniform"):
        start = time.perf_counter()
        if _current_arm == "puct":
            action_rows, feats = combat_action_arrays(battle)
            action_rows = [tuple(int(x) for x in a) for a in action_rows]
            if action_rows != actions:
                raise RuntimeError("legal action/feature order changed before search")
            state = public_combat_observation(battle)
            with torch.inference_mode():
                logits = _policy(torch.from_numpy(state)[None], torch.from_numpy(feats)[None])[0]
                if logits.shape != (len(actions),) or not torch.isfinite(logits).all():
                    raise RuntimeError("invalid root-policy logits")
                priors = torch.softmax(logits, dim=0).tolist()
        else:
            priors = [1.0 / len(actions)] * len(actions)
        _prior_seconds += time.perf_counter() - start
        start = time.perf_counter()
        path, done, _ = battle.mcts_priors(simulations, actions, priors, 3.0,
                                            seed & 0xFFFFFFFF, False, False, epsilon)
    elif _current_arm == "mcts":
        start = time.perf_counter()
        path, done, _ = battle.mcts(simulations, 3 * 2**0.5,
                                    seed & 0xFFFFFFFF, False, False, epsilon)
    else:
        raise ValueError(f"unknown search arm {_current_arm}")
    _search_seconds += time.perf_counter() - start
    path = [tuple(int(x) for x in a) for a in path]
    if not path or path[0] not in actions or int(done) != simulations:
        raise RuntimeError("search returned invalid action or incomplete simulation budget")
    return path[:1], int(done)


def _init_worker(policy_path, armg_path):
    global _policy, _armg
    torch.set_num_threads(1)
    _policy = CombatPolicy().eval()
    load_combat_checkpoint(policy_path, _policy)
    _armg = ArmGScorer().eval()
    load_armg_checkpoint(armg_path, _armg)
    if not hasattr(sim.BattleContext, "mcts_priors"):
        raise RuntimeError("isolated simulator does not export mcts_priors")
    collector._mcts_plan = _fixed_plan


def _play(seed, arm, simulations, max_steps):
    global _current_arm, _prior_seconds, _search_seconds
    _current_arm = arm
    _prior_seconds = _search_seconds = 0.0
    start = time.perf_counter()
    result = dict(collector.collect_episode(seed, _policy, _armg, battle_mode="mcts-oracle",
                                            teacher_sims=simulations, collect_labels=False,
                                            max_steps=max_steps))
    result.pop("records", None)
    result.update(arm=arm, elapsed_seconds=time.perf_counter() - start,
                  prior_seconds=_prior_seconds, search_seconds=_search_seconds)
    return result


def paired_summary(results):
    groups = {arm: {} for arm in ARMS}
    for item in results:
        arm, seed = item["arm"], int(item["seed"])
        if arm not in groups or seed in groups[arm]:
            raise ValueError("unexpected arm or duplicate seed")
        groups[arm][seed] = item
    comparisons = {}
    for treatment, baseline in (("puct", "mcts"), ("puct", "puct_uniform"),
                                ("puct_uniform", "mcts")):
        pairs = [(groups[baseline][s], p) for s, p in groups[treatment].items()
                 if s in groups[baseline] and p["status"] == groups[baseline][s]["status"] == "terminated"]
        ds = [float(p["floor"] - b["floor"]) for b, p in pairs]
        mean = sum(ds) / len(ds) if ds else None
        se = math.sqrt(sum((d - mean)**2 for d in ds) / (len(ds)*(len(ds)-1))) if len(ds) > 1 else None
        comparisons[f"{treatment}_vs_{baseline}"] = {
            "complete_pairs": len(pairs), "mean_floor_difference": mean,
            "floor_difference_se": se,
            "treatment_only_wins": sum(bool(p.get("won")) and not bool(b.get("won")) for b, p in pairs),
            "baseline_only_wins": sum(bool(b.get("won")) and not bool(p.get("won")) for b, p in pairs)}
    summaries = {}
    for arm, group in groups.items():
        values = list(group.values())
        summary = summarize(values)
        complete = [r for r in values if r["status"] == "terminated"]
        for key in ("prior_seconds", "search_seconds"):
            summary["mean_" + key + "_completed"] = (sum(r.get(key, 0) for r in complete) / len(complete)
                                                         if complete else None)
        summaries[arm] = summary
    return {"arms": summaries, "paired": comparisons}


def run(policy_path: Path, armg_path: Path, out_dir: Path, *, start: int, count: int,
        workers: int, simulations: int, max_steps: int):
    if min(count, workers, simulations, max_steps) < 1 or start < 0:
        raise ValueError("invalid evaluation settings")
    if not _extension or not hasattr(sim.BattleContext, "mcts_priors"):
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated extension with mcts_priors")
    policy_path, armg_path = policy_path.resolve(strict=True), armg_path.resolve(strict=True)
    out_dir.mkdir(parents=True, exist_ok=False)
    policy_snapshot, armg_snapshot = out_dir / "policy.pt", out_dir / "armg.pt"
    shutil.copyfile(policy_path, policy_snapshot)
    shutil.copyfile(armg_path, armg_snapshot)
    torch.set_num_threads(1)
    policy, armg = CombatPolicy(), ArmGScorer()
    policy_data = load_combat_checkpoint(policy_snapshot, policy)
    armg_data = load_armg_checkpoint(armg_snapshot, armg)
    del policy, armg
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    config = {"policy_path": str(policy_path), "policy_snapshot": str(policy_snapshot.resolve()),
              "policy_sha256": sha(policy_snapshot), "policy_progress": policy_data.get("progress"),
              "policy_training_settings": policy_data.get("settings"),
              "armg_path": str(armg_path), "armg_snapshot": str(armg_snapshot.resolve()),
              "armg_sha256": sha(armg_snapshot), "armg_progress": armg_data.get("progress"),
              "simulator_path": str(Path(_extension).resolve()), "simulator_sha256": sha(Path(_extension)),
              "seed_base": SEED_BASE, "seed_start": SEED_BASE + start, "count": count,
              "arms": list(ARMS), "simulations_per_decision": simulations, "boss_multiplier": 1,
              "path_cache": "none", "information": "oracle: full future state in both arms",
              "mcts_ucb_c": 3 * 2**0.5, "puct_root_c": 3.0,
              "rollout": "random, all arms", "max_steps": max_steps, "workers": workers,
              "ascension": 0, "armg_rules": "original ArmG, no overlays",
              "torch": torch.__version__, "cuda_available": bool(torch.cuda.is_available()),
              "started_utc": datetime.now(timezone.utc).isoformat()}
    (out_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    records, started = [], time.perf_counter()
    def save_progress(state):
        progress = {"state": state, "completed_jobs": len(records), "total_jobs": count * len(ARMS),
                    "elapsed_seconds": time.perf_counter() - started,
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                    **paired_summary(records)}
        tmp = out_dir / "progress.tmp"
        tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(tmp, out_dir / "progress.json")
    save_progress("running")
    with (out_dir / "episodes.jsonl").open("x", encoding="utf-8") as out:
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                 initializer=_init_worker,
                                 initargs=(str(policy_snapshot.resolve()), str(armg_snapshot.resolve()))) as pool:
            jobs = {pool.submit(_play, SEED_BASE + start + i, arm, simulations, max_steps):
                    (SEED_BASE + start + i, arm) for i in range(count) for arm in ARMS}
            for future in as_completed(jobs):
                seed, arm = jobs[future]
                try:
                    record = future.result()
                except Exception as exc:
                    record = {"seed": seed, "arm": arm, "status": "error", "won": False,
                              "floor": 0, "error": f"{type(exc).__name__}: {exc}"}
                records.append(record)
                out.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                out.flush()
                save_progress("running")
                if len(records) % 20 == 0 or len(records) == len(jobs):
                    print(json.dumps({"progress": len(records), "total": len(jobs)}), flush=True)
    report = {"config": config, **paired_summary(records), "elapsed_seconds": time.perf_counter()-started,
              "episodes_path": str((out_dir / "episodes.jsonl").resolve())}
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    save_progress("completed")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy-checkpoint", required=True, type=Path)
    p.add_argument("--armg-checkpoint", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=10000)
    p.add_argument("--max-steps", type=int, default=5000)
    a = p.parse_args(argv)
    run(a.policy_checkpoint, a.armg_checkpoint, a.out_dir, start=a.start, count=a.seeds,
        workers=a.workers, simulations=a.simulations, max_steps=a.max_steps)


if __name__ == "__main__":
    main()
