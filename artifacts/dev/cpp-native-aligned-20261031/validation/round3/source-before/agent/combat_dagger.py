"""STS2 battle policy/value training using MCTS-labelled DAgger.

ArmD's policy acts greedily; a separate native MCTS labels visited decisions.
An optional teacher-behavior warmup supplies STS2-specific initialization.
Battle samples stay on disk and the replay window is limited by example count.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import shutil
import time
import uuid

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .common import ACTION_FEAT_DIM, ACTION_SCHEMA_VERSION, PUBLIC_COMBAT_OBS_DIM, PUBLIC_OBS_VERSION
from .engine_identity import current_engine_contract
from .nets import read_checkpoint

MODEL_FORMAT = 1
TRAIN_SEED_BASE = 11_000_000
DEFAULT_ARMG = "runs/armg_a0_mcts_20261029/eval_mcts10000_20261029_215142/model.pt"


class CombatPolicy(nn.Module):
    """Shared per-action 256x256 scorer with one state projection per row."""
    def __init__(self):
        super().__init__()
        self.first = nn.Linear(PUBLIC_COMBAT_OBS_DIM + ACTION_FEAT_DIM, 256)
        self.second = nn.Linear(256, 256)
        self.out = nn.Linear(256, 1)

    def forward(self, obs, actions):
        state = F.linear(obs, self.first.weight[:, :PUBLIC_COMBAT_OBS_DIM], self.first.bias)
        candidate = F.linear(actions, self.first.weight[:, PUBLIC_COMBAT_OBS_DIM:])
        return self.out(F.relu(self.second(F.relu(state.unsqueeze(1) + candidate)))).squeeze(-1)


class CombatValue(nn.Module):
    """Main battle win+HP value, with separate win and HP auxiliary heads."""
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(PUBLIC_COMBAT_OBS_DIM, 256), nn.ReLU(),
                                     nn.Linear(256, 256), nn.ReLU())
        self.main = nn.Linear(256, 1)
        self.win = nn.Linear(256, 1)
        self.hp = nn.Linear(256, 1)

    def forward(self, obs):
        h = self.encoder(obs)
        return self.main(h).squeeze(-1), self.win(h).squeeze(-1), self.hp(h).squeeze(-1)


def checkpoint_config(policy, value):
    return {"model_format": MODEL_FORMAT, "obs_version": int(PUBLIC_OBS_VERSION),
            "action_schema_version": int(ACTION_SCHEMA_VERSION),
            "obs_dim": int(PUBLIC_COMBAT_OBS_DIM), "action_dim": int(ACTION_FEAT_DIM),
            "policy_shapes": [list(p.shape) for p in policy.parameters()],
            "value_shapes": [list(p.shape) for p in value.parameters()],
            "engine_contract": current_engine_contract()}


def load_combat_checkpoint(path, policy, value=None):
    """Load only current-schema DAgger weights, including when loading policy alone."""
    data = read_checkpoint(path)
    actual_value = value if value is not None else CombatValue()
    if data.get("config") != checkpoint_config(policy, actual_value):
        raise ValueError("combat checkpoint engine identity, model or observation/action schema mismatch")
    policy.load_state_dict(data["policy_state_dict"])
    if value is not None:
        value.load_state_dict(data["value_state_dict"])
    return data


def save_checkpoint(path, policy, value, policy_opt, value_opt, progress, settings, manifest):
    data = {"config": checkpoint_config(policy, value),
            "policy_state_dict": policy.state_dict(), "value_state_dict": value.state_dict(),
            "policy_optimizer": policy_opt.state_dict(), "value_optimizer": value_opt.state_dict(),
            "progress": progress, "settings": settings, "manifest": manifest,
            "python_rng_state": random.getstate(), "numpy_rng_state": np.random.get_state(),
            "torch_rng_state": torch.get_rng_state()}
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(data, temporary)
    os.replace(temporary, path)


def restore_checkpoint(path, policy, value, policy_opt, value_opt, settings,
                       *, allow_teacher_sims_change=False):
    data = load_combat_checkpoint(path, policy, value)
    saved_settings = dict(data.get("settings", {}))
    saved_settings.setdefault("train_threads", 1)  # pre-thread-option checkpoints
    expected_settings = dict(settings)
    expected_settings.setdefault("train_threads", 1)
    old_budget = saved_settings.get("teacher_sims")
    new_budget = expected_settings.get("teacher_sims")
    changed = saved_settings != expected_settings
    if changed and allow_teacher_sims_change:
        # Keep every other training setting fixed, including the teacher's
        # information mode, frozen ArmG hash and replay capacity.
        saved_without_budget = {k: v for k, v in saved_settings.items() if k != "teacher_sims"}
        expected_without_budget = {k: v for k, v in expected_settings.items() if k != "teacher_sims"}
        if (saved_without_budget != expected_without_budget or not isinstance(old_budget, int)
                or not isinstance(new_budget, int) or min(old_budget, new_budget) < 1):
            raise ValueError("resume settings differ beyond teacher_sims")
    elif changed:
        raise ValueError("resume settings differ; use the saved training configuration")
    policy_opt.load_state_dict(data["policy_optimizer"])
    value_opt.load_state_dict(data["value_optimizer"])
    random.setstate(data["python_rng_state"])
    np.random.set_state(data["numpy_rng_state"])
    torch.set_rng_state(data["torch_rng_state"])
    progress = data["progress"]
    if changed:
        progress.setdefault("teacher_sims_changes", []).append({
            "from": old_budget, "to": new_budget,
            "at_round": progress.get("round"), "at_total_games": progress.get("total_games"),
            "source_checkpoint": str(Path(path).resolve()),
            "source_sha256": _source_hash(path),
        })
    return progress, data["manifest"]


def add_replay(manifest, shard_entries, capacity):
    """Return a bounded logical FIFO; old shard files remain for provenance."""
    if capacity < 1:
        raise ValueError("replay capacity must be positive")
    entries = [dict(item) for item in manifest]
    entries.extend({**item, "path": str(item["path"]), "count": int(item["count"]), "start": 0}
                   for item in shard_entries if int(item["count"]) > 0)
    total = sum(item["count"] - item["start"] for item in entries)
    discard = max(0, total - capacity)
    while discard:
        first = entries[0]
        take = min(discard, first["count"] - first["start"])
        first["start"] += take
        discard -= take
        if first["start"] == first["count"]:
            entries.pop(0)
    return entries


def validate_shard(data, entry=None):
    """Validate bounds and legal teacher labels before consuming a battle shard."""
    states, actions = data["states"], data["actions"]
    offsets, labels, wins, hp = data["offsets"], data["labels"], data["wins"], data["hp"]
    n = len(states)
    if (states.shape != (n, PUBLIC_COMBAT_OBS_DIM) or actions.ndim != 2 or
        actions.shape[1] != ACTION_FEAT_DIM or offsets.shape != (n + 1,) or
        labels.shape != (n,) or wins.shape != (n,) or hp.shape != (n,) or
        offsets[0] != 0 or offsets[-1] != len(actions) or
        np.any(np.diff(offsets) <= 0)):
        raise ValueError("invalid battle shard shape or action offsets")
    if (np.any(labels < -1) or np.any(labels >= np.diff(offsets)) or
        not np.isfinite(states).all() or not np.isfinite(actions).all() or
        not np.isfinite(wins).all() or not np.isfinite(hp).all() or
        np.any((wins != 0) & (wins != 1)) or np.any(hp < 0) or np.any(hp > 1)):
        raise ValueError("invalid battle shard values or teacher action")
    if entry is not None and "run_id" in entry:
        if "metadata_json" not in data:
            raise ValueError("battle shard is missing provenance")
        metadata = json.loads(str(data["metadata_json"].item()))
        for key in ("run_id", "seed", "policy_sha256", "armg_sha256", "teacher_sims",
                    "resample_hidden", "battle_mode", "obs_version", "action_schema_version"):
            if metadata.get(key) != entry.get(key):
                raise ValueError(f"battle shard provenance mismatch for {key}")
        if metadata.get("episode_status") != "terminated":
            raise ValueError("incomplete episode in replay")
    return n


def replay_batches(manifest, batch_size, rng):
    """Shuffle shards and samples while holding at most one battle plus a batch."""
    order = rng.permutation(len(manifest))
    batch = []
    for idx in order:
        entry = manifest[int(idx)]
        with np.load(entry["path"], allow_pickle=False) as data:
            n = validate_shard(data, entry)
            if n != entry["count"] or not 0 <= entry["start"] <= n:
                raise ValueError("battle shard does not match checkpoint manifest")
            states, actions = data["states"], data["actions"]
            offsets, labels = data["offsets"], data["labels"]
            wins, hp = data["wins"], data["hp"]
            for j in rng.permutation(np.arange(entry["start"], n)):
                a, b = int(offsets[j]), int(offsets[j + 1])
                batch.append((states[j].copy(), actions[a:b].copy(),
                              int(labels[j]), float(wins[j]), float(hp[j])))
                if len(batch) == batch_size:
                    yield batch
                    batch = []
    if batch:
        yield batch


def train_batch(policy, value, policy_opt, value_opt, batch, microbatch=16):
    """Accumulate one optimizer step over bounded candidate-padding chunks."""
    if not batch or microbatch < 1:
        raise ValueError("batch and microbatch must be positive")
    n = len(batch)
    labeled = sum(item[2] >= 0 for item in batch)
    policy_opt.zero_grad(set_to_none=True)
    value_opt.zero_grad(set_to_none=True)
    p_total = v_total = 0.0
    for pos in range(0, n, microbatch):
        chunk = batch[pos:pos + microbatch]
        obs = torch.from_numpy(np.stack([item[0] for item in chunk]))
        wins = torch.tensor([item[3] for item in chunk], dtype=torch.float32)
        hp = torch.tensor([item[4] for item in chunk], dtype=torch.float32)
        main, win_logits, hp_logits = value(obs)
        vloss = (F.smooth_l1_loss(main, wins + hp, beta=0.25, reduction="sum") +
                 0.5 * F.binary_cross_entropy_with_logits(win_logits, wins, reduction="sum") +
                 0.5 * F.mse_loss(torch.sigmoid(hp_logits), hp, reduction="sum")) / n
        if not torch.isfinite(vloss):
            raise RuntimeError("non-finite value loss")
        v_total += float(vloss.detach())
        vloss.backward()
        selected = [i for i, item in enumerate(chunk) if item[2] >= 0]
        if selected:
            max_actions = max(len(chunk[i][1]) for i in selected)
            candidates = np.zeros((len(selected), max_actions, ACTION_FEAT_DIM), dtype=np.float32)
            mask = np.zeros((len(selected), max_actions), dtype=np.bool_)
            labels = np.empty(len(selected), dtype=np.int64)
            for k, j in enumerate(selected):
                acts, label = chunk[j][1], chunk[j][2]
                candidates[k, :len(acts)] = acts
                mask[k, :len(acts)] = True
                labels[k] = label
            logits = policy(obs[selected], torch.from_numpy(candidates))
            logits = logits.masked_fill(~torch.from_numpy(mask), float("-inf"))
            ploss = F.cross_entropy(logits, torch.from_numpy(labels), reduction="sum") / labeled
            if not torch.isfinite(ploss):
                raise RuntimeError("non-finite policy loss")
            p_total += float(ploss.detach())
            ploss.backward()
    torch.nn.utils.clip_grad_norm_(value.parameters(), 1.0, error_if_nonfinite=True)
    value_opt.step()
    if labeled:
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0, error_if_nonfinite=True)
        policy_opt.step()
    return {"policy_loss": p_total if labeled else None, "value_loss": v_total,
            "examples": n, "policy_examples": labeled}


_worker_policy = None
_worker_armg = None
_worker_version = None


def _init_worker(armg_checkpoint):
    global _worker_policy, _worker_armg, _worker_version
    from .armg import ArmGScorer
    from deployment.evaluate_armg import load_armg_checkpoint
    torch.set_num_threads(1)
    _worker_policy = CombatPolicy().eval()
    _worker_armg = ArmGScorer().eval()
    load_armg_checkpoint(armg_checkpoint, _worker_armg)
    _worker_version = None


def _collect_worker(task):
    global _worker_version
    from .combat_dagger_collect import collect_episode
    seed, version, weights, output_dir, options, metadata = task
    if _worker_version != version:
        _worker_policy.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
        _worker_version = version
    return collect_episode(seed, _worker_policy, _worker_armg, output_dir=output_dir,
                           metadata=metadata, **options)


def _source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def train(*, out_dir, armg_checkpoint=DEFAULT_ARMG, rounds=5, first_games=400,
          games_per_round=600, warmup_games=100, teacher_sims=512,
          teacher_mode="oracle", workers=8, epochs=3, batch_size=512, microbatch=16,
          pool_capacity=100_000, collection_batch=32, max_steps=5000,
          seed=20261026, lr=3e-4, val_runs=30, train_threads=1, resume=None,
          resume_change_teacher_sims=False):
    """Train to a numbered round, with atomic checkpoints after each 32 games.

    Teacher-behavior warmup is a STS2 adaptation replacing unavailable compatible
    pretrained STS1 weights. No unlabelled state or failed episode enters replay.
    The replay capacity controls the active FIFO; archived shards stay on disk.
    With --resume-change-teacher-sims only the teacher budget may differ from
    a checkpoint; the saved manifest retains each shard's original budget.
    """
    if (min(rounds, first_games, games_per_round, teacher_sims, workers, epochs,
            batch_size, microbatch, pool_capacity, collection_batch, max_steps, val_runs, train_threads) < 1 or
            warmup_games < 0 or teacher_mode not in ("oracle", "resampled") or lr <= 0):
        raise ValueError("invalid training configuration")
    if resume_change_teacher_sims and not resume:
        raise ValueError("--resume-change-teacher-sims requires --resume")
    armg_path = Path(armg_checkpoint).resolve(strict=True)
    armg_hash = _source_hash(armg_path)
    settings = {"armg_checkpoint": str(armg_path), "armg_sha256": armg_hash,
                "first_games": first_games, "games_per_round": games_per_round,
                "warmup_games": warmup_games, "teacher_sims": teacher_sims,
                "teacher_mode": teacher_mode, "epochs": epochs, "batch_size": batch_size,
                "microbatch": microbatch, "pool_capacity": pool_capacity,
                "collection_batch": collection_batch, "max_steps": max_steps,
                "seed": seed, "lr": lr, "val_runs": val_runs,
                "train_threads": train_threads}
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not resume and (out / "latest.pt").exists():
        raise FileExistsError("existing run: choose another directory or use --resume")
    torch.set_num_threads(train_threads)
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)
    policy, value = CombatPolicy(), CombatValue()
    policy_opt = torch.optim.Adam(policy.parameters(), lr=lr)
    value_opt = torch.optim.Adam(value.parameters(), lr=lr)
    progress = {"stage": "warmup" if warmup_games else "dagger", "round": 0 if warmup_games else 1,
                "stage_games": 0, "total_games": 0, "completed": 0,
                "truncated": 0, "errors": 0, "initialization": "random STS2 weights",
                "run_id": uuid.uuid4().hex, "best_floor": None, "best_wins": None,
                "best_round": None}
    manifest = []
    if resume:
        progress, manifest = restore_checkpoint(resume, policy, value, policy_opt, value_opt, settings,
                                                 allow_teacher_sims_change=resume_change_teacher_sims)
    if progress["stage"] == "done" and progress["round"] <= rounds:
        progress["stage"] = "dagger"
    if resume and Path(resume).resolve() != (out / "latest.pt").resolve():
        # A fork gets its own checkpoints and never overwrites the source.
        # Preserve the source best when this was itself the best checkpoint;
        # otherwise find the best file alongside the source latest checkpoint.
        if (out / "latest.pt").exists() or (out / "best.pt").exists():
            raise FileExistsError("destination already contains checkpoints; resume its latest.pt instead")
        source_best = Path(resume) if Path(resume).name == "best.pt" else Path(resume).parent / "best.pt"
        if source_best.is_file():
            temporary_best = out / "best.pt.tmp"
            shutil.copyfile(source_best, temporary_best)
            os.replace(temporary_best, out / "best.pt")
        save_checkpoint(out / "latest.pt", policy, value, policy_opt, value_opt,
                        progress, settings, manifest)
    save_dir = out / "shards"
    save_dir.mkdir(exist_ok=True)
    weight_file = out / "worker_policy.pt"
    temp_weight_file = out / "worker_policy.tmp"
    with ExitStack() as stack:
        log = stack.enter_context((out / "metrics.jsonl").open("a", encoding="utf-8"))
        pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers,
                mp_context=mp.get_context("spawn"), initializer=_init_worker,
                initargs=(str(armg_path),)))
        while progress["stage"] != "done" and progress["round"] <= rounds:
            stage = progress["stage"]
            rnd = progress["round"]
            target = warmup_games if stage == "warmup" else first_games if rnd == 1 else games_per_round
            if progress["stage_games"] < target:
                count = min(collection_batch, target - progress["stage_games"])
                torch.save(policy.state_dict(), temp_weight_file)
                os.replace(temp_weight_file, weight_file)
                policy_hash = _source_hash(weight_file)
                version = f"{stage}-{rnd}-{progress['total_games']}"
                mode = "teacher" if stage == "warmup" else "student"
                options = {"teacher_sims": teacher_sims, "resample_hidden": teacher_mode == "resampled",
                           "max_steps": max_steps, "collect_labels": True, "battle_mode": mode}
                tasks = []
                for i in range(count):
                    game_seed = TRAIN_SEED_BASE + progress["total_games"] + i
                    attempt = save_dir / f"r{rnd:02d}_{game_seed}_{uuid.uuid4().hex[:12]}"
                    metadata = {"obs_version": int(PUBLIC_OBS_VERSION),
                                "action_schema_version": int(ACTION_SCHEMA_VERSION),
                                "teacher_sims": teacher_sims, "teacher_mode": teacher_mode,
                                "resample_hidden": teacher_mode == "resampled", "seed": game_seed,
                                "battle_mode": mode, "armg_sha256": armg_hash,
                                "policy_sha256": policy_hash, "run_id": progress["run_id"]}
                    tasks.append((game_seed, version, str(weight_file), str(attempt), options, metadata))
                started = time.monotonic()
                results = list(pool.map(_collect_worker, tasks, chunksize=1))
                new_entries = []
                for result, task in zip(results, tasks):
                    status = result["status"]
                    if status == "terminated":
                        progress["completed"] += 1
                        for shard in result["shards"]:
                            entry = {**shard, **task[-1]}
                            with np.load(entry["path"], allow_pickle=False) as data:
                                if validate_shard(data, entry) != int(entry["count"]):
                                    raise ValueError("battle shard count mismatch")
                            new_entries.append(entry)
                    elif status == "truncated":
                        progress["truncated"] += 1
                    else:
                        progress["errors"] += 1
                manifest = add_replay(manifest, new_entries, pool_capacity)
                progress["stage_games"] += count
                progress["total_games"] += count
                save_checkpoint(out / "latest.pt", policy, value, policy_opt, value_opt,
                                progress, settings, manifest)
                record = {"stage": stage, "round": rnd, "stage_games": progress["stage_games"],
                          "total_games": progress["total_games"], "completed": progress["completed"],
                          "errors": progress["errors"], "truncated": progress["truncated"],
                          "replay_examples": sum(e["count"] - e["start"] for e in manifest),
                          "seconds": round(time.monotonic() - started, 3),
                          "batch_errors": [r.get("error") for r in results if r["status"] != "terminated"]}
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
                log.flush()
                print(json.dumps(record, ensure_ascii=False), flush=True)
                if sum(r["status"] != "terminated" for r in results) > max(1, count * 0.02):
                    raise RuntimeError("too many incomplete episodes; inspect metrics before resuming")
                continue
            if not manifest:
                raise RuntimeError("no completed battle examples available")
            started = time.monotonic()
            stats = []
            for _ in range(epochs):
                # Parent RNG is checkpointed. A crash during this phase restarts
                # the entire phase from the preceding atomic checkpoint.
                rng = np.random.default_rng(int(np.random.randint(0, 2**31 - 1)))
                for batch in replay_batches(manifest, batch_size, rng):
                    stats.append(train_batch(policy, value, policy_opt, value_opt, batch, microbatch))
            completed_round = 0 if stage == "warmup" else rnd
            progress["stage"] = "dagger"
            progress["round"] = 1 if stage == "warmup" else rnd + 1
            progress["stage_games"] = 0
            if progress["round"] > rounds:
                progress["stage"] = "done"
            torch.save(policy.state_dict(), temp_weight_file)
            os.replace(temp_weight_file, weight_file)
            validation_tasks = []
            for i in range(val_runs):
                v_options = {"teacher_sims": teacher_sims,
                             "resample_hidden": teacher_mode == "resampled",
                             "max_steps": max_steps, "collect_labels": False,
                             "battle_mode": "student"}
                validation_tasks.append((21_000_000 + i, f"validation-{completed_round}",
                                         str(weight_file), None, v_options, {}))
            validation = list(pool.map(_collect_worker, validation_tasks, chunksize=1))
            completed_val = [r for r in validation if r["status"] == "terminated"]
            val_summary = {"runs": val_runs, "completed": len(completed_val),
                           "errors": sum(r["status"] == "error" for r in validation),
                           "truncated": sum(r["status"] == "truncated" for r in validation),
                           "wins": sum(bool(r["won"]) for r in completed_val),
                           "mean_floor": float(np.mean([r["floor"] for r in completed_val]))
                                         if completed_val else None}
            new_best = (len(completed_val) == val_runs and
                        (progress["best_floor"] is None or
                         (val_summary["mean_floor"], val_summary["wins"]) >
                         (progress["best_floor"], progress["best_wins"])))
            if new_best:
                progress["best_floor"] = val_summary["mean_floor"]
                progress["best_wins"] = val_summary["wins"]
                progress["best_round"] = completed_round
            save_checkpoint(out / f"round{completed_round}.pt", policy, value, policy_opt,
                            value_opt, progress, settings, manifest)
            if new_best:
                save_checkpoint(out / "best.pt", policy, value, policy_opt, value_opt,
                                progress, settings, manifest)
            save_checkpoint(out / "latest.pt", policy, value, policy_opt, value_opt,
                            progress, settings, manifest)
            record = {"stage": "update", "round": completed_round,
                      "total_games": progress["total_games"], "batches": len(stats),
                      "seconds": round(time.monotonic() - started, 3),
                      "replay_examples": sum(e["count"] - e["start"] for e in manifest),
                      "policy_loss": float(np.mean([s["policy_loss"] for s in stats
                                                    if s["policy_loss"] is not None]))
                                     if any(s["policy_loss"] is not None for s in stats) else None,
                      "value_loss": float(np.mean([s["value_loss"] for s in stats])),
                      "validation": val_summary, "new_best": new_best}
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()
            print(json.dumps(record, ensure_ascii=False), flush=True)
    return policy, value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--armg-checkpoint", default=DEFAULT_ARMG)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--first-games", type=int, default=400)
    parser.add_argument("--games-per-round", type=int, default=600)
    parser.add_argument("--warmup-games", type=int, default=100)
    parser.add_argument("--teacher-sims", type=int, default=512)
    parser.add_argument("--teacher-mode", choices=("oracle", "resampled"), default="oracle")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--microbatch", type=int, default=16)
    parser.add_argument("--pool-capacity", type=int, default=100000)
    parser.add_argument("--collection-batch", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261026)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--val-runs", type=int, default=30)
    parser.add_argument("--train-threads", type=int, default=1,
                        help="CPU threads for parent optimization; rollout workers use one each")
    parser.add_argument("--resume")
    parser.add_argument("--resume-change-teacher-sims", action="store_true",
                        help="explicitly allow only the teacher simulation budget to change on resume")
    train(**vars(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
