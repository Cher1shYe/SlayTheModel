"""Collect public run decisions with weak priors, then train a fresh ArmG.

Battle uses pure oracle or information-resampled MCTS and independently
generated search seeds. Complete episode shards are compressed on disk;
unfinished games never become training data. Set STS2_PRIOR_PYD to the extension.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import random
import shutil
import time

# Load the isolated extension before agent.common, also in spawned workers.
from deployment import evaluate_battle_root_prior as isolated
import numpy as np
import torch
from torch.nn import functional as F

from .armg import ARMG_ACTION_DIM, ArmGScorer, build_candidates
from .armg_prior import LocalPrior
from .armg_train import _save, _warm_start
from .common import RACT, SCREEN, completed_run_status, new_run
from .hidden_mcts_controller import HiddenMctsController

SEED_BASE = 30_100_000
_prior = _behavior_model = None


def _atomic_json(path, data):
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False),
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _init_worker(data_dir, init_checkpoint=None):
    global _prior, _behavior_model
    torch.set_num_threads(1)
    _prior = LocalPrior(data_dir)
    _behavior_model = None
    if init_checkpoint:
        _behavior_model = ArmGScorer().eval()
        _warm_start(init_checkpoint, _behavior_model)


def _behavior_distribution(prior, model_probabilities=None):
    """Sampling policy, separate from the unchanged supervised prior target."""
    prior = np.asarray(prior, dtype=np.float64)
    if prior.ndim != 1 or not len(prior) or not np.isfinite(prior).all() or (prior <= 0).any():
        raise ValueError("invalid prior")
    prior = prior / prior.sum()
    if model_probabilities is None:
        return .7 * prior + .3 / len(prior)
    model_probabilities = np.asarray(model_probabilities, dtype=np.float64)
    if (model_probabilities.shape != prior.shape or not np.isfinite(model_probabilities).all()
            or (model_probabilities < 0).any() or model_probabilities.sum() <= 0):
        raise ValueError("invalid behavior-model probabilities")
    model_probabilities = model_probabilities / model_probabilities.sum()
    return .7 * model_probabilities + .2 * prior + .1 / len(prior)


def _split_records(records):
    """Whole games retain their split even when replayed in later cycles."""
    return ([r for r in records if (int(r["seed"]) - SEED_BASE) % 5],
            [r for r in records if not (int(r["seed"]) - SEED_BASE) % 5])


def _episode(task):
    seed, sample_seed, search_seed, simulations, boss_simulations, max_steps, out_dir, combat_mode = task
    rng = np.random.default_rng(sample_seed)
    rc = new_run(seed, 0)
    out = Path(out_dir)
    started = time.perf_counter()
    activity_path = out / "active" / f"worker-{os.getpid()}.json"
    steps = combat_decisions = 0
    last_activity = 0.0
    def activity(controller=None, force=False):
        nonlocal last_activity
        now = time.perf_counter()
        if not force and now - last_activity < 10:
            return
        _atomic_json(activity_path, {"seed": seed, "pid": os.getpid(),
                     "steps": steps, "combat_decisions": combat_decisions,
                     "elapsed_seconds": now-started,
                     "updated_utc": datetime.now(timezone.utc).isoformat()})
        last_activity = now
    controller = HiddenMctsController(search_seed, activity=activity,
                                      boss_simulations=boss_simulations, mode=combat_mode)
    states, features, targets, screens, strata, action_rows, metadata = [], [], [], [], [], [], []
    sources, action_sources, screen_sources, stratum_counts, recent = Counter(), Counter(), Counter(), Counter(), deque(maxlen=64)
    floor_screen_counts, event_counts, boss_counts, card_counts, relic_counts = Counter(), Counter(), Counter(), Counter(), Counter()
    action_names = {int(v): k for k, v in RACT.__members__.items()}
    status, error, recoveries = "error", None, 0
    try:
        activity(force=True)
        while rc.screen != SCREEN.RUN_OVER and steps < max_steps:
            steps += 1
            if rc.screen == SCREEN.COMBAT:
                combat = "mcts-oracle" if combat_mode == "oracle" else "mcts-resampled"
                action, _ = controller.plan(rc.battle, 0, combat,
                                            simulations, .05, rc.combat_is_boss)
                if len(rc.battle.legal_actions()) > 1:
                    combat_decisions += 1
                if not rc.step_combat(*action[0]):
                    raise RuntimeError("combat action rejected")
                activity()
                continue
            obs, actions, feats = build_candidates(rc)
            if not actions:
                raise RuntimeError("no legal run actions")
            if len(actions) == 1:
                chosen = 0
            else:
                q, source = _prior.distribution(rc, actions)
                if (q.shape != (len(actions),) or not np.isfinite(q).all()
                    or (q <= 0).any() or abs(float(q.sum()) - 1) > 1e-6):
                    raise RuntimeError("invalid legal-action prior")
                if _behavior_model is None:
                    behavior = _behavior_distribution(q)
                else:
                    with torch.inference_mode():
                        logits = _behavior_model(torch.from_numpy(obs)[None], torch.from_numpy(feats)[None])[0]
                        if logits.shape != (len(actions),) or not torch.isfinite(logits).all():
                            raise RuntimeError("invalid behavior-model logits")
                        model_probs = torch.softmax(logits, dim=0).numpy().astype(np.float64)
                    behavior = _behavior_distribution(q, model_probs)
                chosen = int(rng.choice(len(actions), p=behavior))
                key = hashlib.blake2b(obs.tobytes() + feats.tobytes(), digest_size=16).digest()
                repeats = recent.count(key)
                recent.append(key)
                if repeats >= 3:
                    candidates = [i for i in range(len(actions)) if i != chosen]
                    chosen = candidates[(repeats-3) % len(candidates)]
                    recoveries += 1
                states.append(obs.copy())
                features.append(feats.copy())
                targets.append(np.asarray(q, dtype=np.float32))
                screens.append(rc.screen.name + (":GRID" if rc.card_grid_kind else ""))
                stratum = f"act{int(rc.act)+1}:{screens[-1]}"
                strata.append(stratum)
                stratum_counts[stratum] += 1
                action_rows.append(np.asarray(actions, dtype=np.int32))
                meta = {"floor": int(rc.floor), "act": int(rc.act)+1,
                        "screen": screens[-1], "boss_encounter": int(rc.boss_encounter),
                        "second_boss_encounter": int(rc.second_boss_encounter),
                        "event_id": int(rc.event_id) if rc.screen == SCREEN.EVENT else None,
                        "deck_cards": [int(c[0]) for c in rc.deck],
                        "offered_cards": [int(c[0]) for c in rc.offered],
                        "grid_cards": [int(c[0]) for c in rc.card_grid_cards] if rc.card_grid_kind else [],
                        "shop_cards": [int(x[0]) for x in rc.shop] if rc.screen == SCREEN.SHOP else [],
                        "event_relics": [int(x) for x in rc.event_relics] if rc.screen == SCREEN.EVENT else [],
                        "reward_relics": [int(x[0]) for x in rc.reward_relics],
                        "shop_relics": [int(x[0]) for x in rc.shop_relics] if rc.screen == SCREEN.SHOP else []}
                metadata.append(json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
                floor_screen_counts[f"{meta['floor']}:{meta['screen']}"] += 1
                boss_counts[str(meta["boss_encounter"])] += 1
                if meta["event_id"] is not None:
                    event_counts[str(meta["event_id"])] += 1
                for item in meta["offered_cards"] + meta["grid_cards"] + meta["shop_cards"]:
                    card_counts[str(item)] += 1
                for item in meta["event_relics"] + meta["reward_relics"] + meta["shop_relics"]:
                    relic_counts[str(item)] += 1
                sources[source] += 1
                screen_sources[screens[-1] + ":" + source] += 1
                for action, action_source in zip(actions, _prior.action_sources(rc, actions, source)):
                    action_sources[action_names.get(int(action[0]), str(action[0])) + ":" + action_source] += 1
            if not rc.step(*actions[chosen]):
                raise RuntimeError("run action rejected")
            activity()
        status = completed_run_status(rc)
        if status == "terminated" and states:
            counts = np.asarray([len(x) for x in features], dtype=np.int64)
            offsets = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(counts)))
            path = out / "dataset" / f"episode-{seed}.npz"
            tmp = path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, states=np.stack(states), features=np.concatenate(features),
                                targets=np.concatenate(targets), offsets=offsets,
                                screens=np.asarray(screens), strata=np.asarray(strata),
                                actions=np.concatenate(action_rows), metadata=np.asarray(metadata))
            os.replace(tmp, path)
        else:
            path = None
    except Exception as exc:
        status, error, path = "error", f"{type(exc).__name__}: {exc}", None
    finally:
        try:
            activity_path.unlink(missing_ok=True)
        except OSError:
            pass
    return {"seed": seed, "status": status, "error": error, "floor": int(rc.floor),
            "won": bool(rc.won) and status == "terminated", "steps": steps,
            "mcts_searches": controller.decisions, "mcts_simulations": controller.simulations,
            "normal_decisions": controller.normal_decisions,
            "boss_decisions": controller.boss_decisions,
            "normal_simulations": controller.normal_simulations,
            "boss_simulations": controller.boss_simulations_completed,
            "records": len(states) if path else 0, "screens": dict(Counter(screens)) if path else {},
            "sources": dict(sources) if path else {}, "cycle_recoveries": recoveries,
            "action_sources": dict(action_sources) if path else {},
            "screen_sources": dict(screen_sources) if path else {},
            "stratum_counts": dict(stratum_counts) if path else {},
            "floor_screen_counts": dict(floor_screen_counts) if path else {},
            "event_counts": dict(event_counts) if path else {},
            "boss_counts": dict(boss_counts) if path else {},
            "candidate_card_counts": dict(card_counts) if path else {},
            "candidate_relic_counts": dict(relic_counts) if path else {},
            "shard": str(path.resolve()) if path else None,
            "elapsed_seconds": time.perf_counter() - started}


def _epoch(model, episodes, weights, rng, optimizer=None, reference=None, kl_weight=0.0):
    training = optimizer is not None
    model.train(training)
    total, weight_sum, count = 0.0, 0.0, 0
    order = rng.permutation(len(episodes)) if training else np.arange(len(episodes))
    for j in order:
        with np.load(episodes[int(j)]["shard"], allow_pickle=False) as f:
            states, features = f["states"], f["features"]
            targets, offsets, screens = f["targets"], f["offsets"], f["screens"]
            strata = f["strata"] if "strata" in f else screens
            indexes = rng.permutation(len(states)) if training else np.arange(len(states))
            for start in range(0, len(indexes), 16):
                idxs = indexes[start:start+16]
                n = len(idxs)
                max_a = max(int(offsets[i+1]-offsets[i]) for i in idxs)
                a = np.zeros((n, max_a, ARMG_ACTION_DIM), dtype=np.float32)
                q = np.zeros((n, max_a), dtype=np.float32)
                mask = np.zeros((n, max_a), dtype=np.bool_)
                w = np.asarray([weights.get(str(strata[i]), 1.0) for i in idxs], dtype=np.float32)
                for k, i in enumerate(idxs):
                    lo, hi = int(offsets[i]), int(offsets[i+1])
                    size = hi-lo
                    a[k, :size], q[k, :size], mask[k, :size] = features[lo:hi], targets[lo:hi], True
                if training:
                    optimizer.zero_grad()
                with torch.set_grad_enabled(training):
                    logits = model(torch.from_numpy(states[idxs]), torch.from_numpy(a))
                    logits = logits.masked_fill(~torch.from_numpy(mask), -1e9)
                    logp = F.log_softmax(logits, dim=-1)
                    loss_per = -(torch.from_numpy(q) * logp).sum(dim=-1)
                    if reference is not None and kl_weight:
                        with torch.no_grad():
                            ref_logits = reference(torch.from_numpy(states[idxs]), torch.from_numpy(a))
                            ref_logp = F.log_softmax(ref_logits.masked_fill(~torch.from_numpy(mask), -1e9), dim=-1)
                            ref_probs = ref_logp.exp()
                        loss_per = loss_per + kl_weight * (ref_probs * (ref_logp - logp)).sum(dim=-1)
                    loss = (loss_per * torch.from_numpy(w)).sum() / float(w.sum())
                    if not torch.isfinite(loss):
                        raise RuntimeError("non-finite prior loss")
                    if training:
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                        optimizer.step()
                total += float((loss_per.detach() * torch.from_numpy(w)).sum())
                weight_sum += float(w.sum())
                count += n
    if not count or not weight_sum:
        raise RuntimeError("empty prior training or validation split")
    return total / weight_sum, count


def run(data_dir, out_dir, *, games=1000, workers=8, simulations=2000, boss_simulations=10000,
        epochs=3, lr=1e-4, max_steps=5000, seed=20261030, combat_mode="oracle",
        seed_offset=0, init_checkpoint=None, replay_dirs=None, kl_weight=0.5):
    if not isolated._extension or not hasattr(isolated.sim.BattleContext, "mcts"):
        raise RuntimeError("set STS2_PRIOR_PYD to the isolated hidden MCTS extension")
    if min(games, workers, simulations, boss_simulations, epochs, max_steps) < 1 or lr <= 0:
        raise ValueError("invalid pretraining settings")
    if combat_mode not in ("oracle", "hidden") or seed_offset < 0 or kl_weight < 0 or not math.isfinite(kl_weight):
        raise ValueError("combat_mode must be oracle or hidden")
    init_path = Path(init_checkpoint).resolve(strict=True) if init_checkpoint else None
    if replay_dirs and not init_path:
        raise ValueError("replaying prior rounds requires the current RL checkpoint")
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "active").mkdir()
    (out / "dataset").mkdir()
    data_dir = Path(data_dir).resolve(strict=True)
    LocalPrior(data_dir)  # verify snapshot and interface before dispatch
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    snapshot_dir = out / "data_snapshot"
    snapshot_dir.mkdir()
    for key in ("cards", "relics", "potions", "community"):
        source = data_dir / (key + ".json")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if manifest.get("snapshots", {}).get(key, {}).get("sha256") != digest:
            raise ValueError(f"snapshot checksum mismatch for {key}")
        shutil.copyfile(source, snapshot_dir / source.name)
    shutil.copyfile(data_dir / "manifest.json", snapshot_dir / "manifest.json")
    ext_sha = hashlib.sha256(Path(isolated._extension).read_bytes()).hexdigest()
    data_sha = hashlib.sha256((data_dir/"manifest.json").read_bytes()).hexdigest()
    replay, prior_seeds = [], set()
    for directory in (replay_dirs or []):
        directory = Path(directory).resolve(strict=True)
        old_config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        wanted = {"information": combat_mode, "simulations_per_decision": simulations,
                  "boss_simulations_per_decision": boss_simulations, "path_cache": "none",
                  "simulator_sha256": ext_sha, "data_manifest_sha256": data_sha}
        if any(old_config.get(k) != v for k, v in wanted.items()):
            raise ValueError(f"incompatible prior experience in {directory}")
        old_progress = json.loads((directory / "progress.json").read_text(encoding="utf-8"))
        if old_progress.get("state") != "completed" or old_progress.get("stage") != "completed":
            raise ValueError(f"prior experience is incomplete in {directory}")
        for line in (directory / "episodes.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("status") != "terminated" or not row.get("shard") or not Path(row["shard"]).is_file():
                raise ValueError(f"invalid prior episode in {directory}")
            if row["seed"] in prior_seeds:
                raise ValueError("duplicate prior replay game seed")
            prior_seeds.add(row["seed"])
            replay.append(row)
    new_seeds = set(range(SEED_BASE + seed_offset, SEED_BASE + seed_offset + games))
    if new_seeds & prior_seeds:
        raise ValueError("new game seeds overlap previous prior experience")
    config = {"data_dir": str(data_dir), "data_snapshot": str(snapshot_dir), "data_manifest_sha256":
              hashlib.sha256((data_dir/"manifest.json").read_bytes()).hexdigest(),
              "simulator_path": str(Path(isolated._extension).resolve()),
              "simulator_sha256": ext_sha,
              "initialization": "current_model" if init_path else "random", "games": games, "workers": workers,
              "simulations_per_decision": simulations, "boss_simulations_per_decision": boss_simulations,
              "combat": "pure mcts", "information": combat_mode,
              "root_action": "best winning rollout else most visited" if combat_mode == "oracle" else "most visited",
              "path_cache": "none", "ascension": 0,
              "model_behavior_mix": .7 if init_path else 0.0,
              "prior_behavior_mix": .2 if init_path else .7,
              "uniform_behavior_mix": .1 if init_path else .3,
              "training_seed_base": SEED_BASE + seed_offset, "seed_offset": seed_offset,
              "source_rl_sha256": hashlib.sha256(init_path.read_bytes()).hexdigest() if init_path else None,
              "source_rl_path": str(init_path) if init_path else None,
              "replay_dirs": [str(Path(p).resolve()) for p in replay_dirs or []],
              "replay_episodes": len(replay), "kl_weight": kl_weight if init_path else 0.0,
              "seed": seed, "epochs": epochs,
              "learning_rate": lr, "max_steps": max_steps,
              "validation": "episode index divisible by 5"}
    (out/"config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    records, started = [], time.perf_counter()
    stage, epoch, extra = "collecting", 0, {}
    def save(state="running"):
        active = []
        for p in (out/"active").glob("worker-*.json"):
            try:
                active.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        coverage = {}
        for key in ("stratum_counts", "floor_screen_counts", "event_counts", "boss_counts",
                    "candidate_card_counts", "candidate_relic_counts"):
            count = Counter()
            for rec in records:
                count.update(rec.get(key, {}))
            coverage[key] = dict(count)
        result = {"state": state, "stage": stage, "epoch": epoch, "games_completed": len(records),
                  "games_total": games, "terminated": sum(r["status"] == "terminated" for r in records),
                  "errors": sum(r["status"] == "error" for r in records),
                  "truncated": sum(r["status"] == "truncated" for r in records),
                  "active_episodes": active, "elapsed_seconds": time.perf_counter()-started,
                  "updated_utc": datetime.now(timezone.utc).isoformat(), **coverage, **extra}
        _atomic_json(out/"progress.json", result)
    try:
        save()
        random_seeds = np.random.default_rng(seed)
        seeds = random_seeds.integers(0, 2**32, size=(games, 2), dtype=np.uint32)
        with (out/"episodes.jsonl").open("x", encoding="utf-8") as log:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"),
                                     initializer=_init_worker, initargs=(str(snapshot_dir), str(init_path) if init_path else None)) as pool:
                def submit(i):
                    return pool.submit(_episode, (SEED_BASE+seed_offset+i, int(seeds[i, 0]), int(seeds[i, 1]),
                                                  simulations, boss_simulations, max_steps, str(out), combat_mode))
                next_index = min(workers, games)
                futures = {submit(i): i for i in range(next_index)}
                pending = set(futures)
                while pending:
                    done, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
                    for future in done:
                        try:
                            record = future.result()
                        except Exception as exc:
                            record = {"seed": SEED_BASE + seed_offset + futures[future], "status": "error",
                                      "error": f"{type(exc).__name__}: {exc}"}
                        records.append(record)
                        log.write(json.dumps(record, ensure_ascii=False) + "\n")
                        log.flush()
                    bad = [r for r in records if r["status"] != "terminated" or not r.get("shard")]
                    if bad:
                        for future in pending:
                            future.cancel()
                        save()
                        raise RuntimeError(f"prior collection stopped on incomplete episode: {bad[0]}")
                    for _ in done:
                        if next_index < games:
                            future = submit(next_index)
                            futures[future] = next_index
                            pending.add(future)
                            next_index += 1
                    save()
        complete = replay + [r for r in records if r["status"] == "terminated" and r.get("shard")]
        training, validation = _split_records(complete)
        if not training or not validation:
            raise RuntimeError("insufficient completed episodes for train/validation")
        counts = Counter()
        source_counts = Counter()
        action_source_counts = Counter()
        screen_source_counts = Counter()
        for r in training:
            counts.update(r.get("stratum_counts", r["screens"]))
            source_counts.update(r["sources"])
            action_source_counts.update(r["action_sources"])
            screen_source_counts.update(r["screen_sources"])
        mean_count = sum(counts.values()) / len(counts)
        weights = {k: float(np.clip(mean_count / v, .25, 3.0)) for k, v in counts.items()}
        stage = "pretraining"
        extra = {"training_episodes": len(training), "validation_episodes": len(validation),
                 "training_stratum_counts": dict(counts), "source_counts": dict(source_counts),
                 "action_source_counts": dict(action_source_counts),
                 "screen_source_counts": dict(screen_source_counts),
                 "stratum_weights": weights, "replay_episodes": len(replay)}
        save()
        torch.set_num_threads(1)
        torch.manual_seed(seed)
        model = ArmGScorer()
        if init_path:
            _warm_start(str(init_path), model)
        reference = None
        if init_path:
            reference = ArmGScorer().eval()
            _warm_start(str(init_path), reference)
            for param in reference.parameters():
                param.requires_grad_(False)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        rng = np.random.default_rng(seed ^ 0x2142)
        best = math.inf
        for epoch in range(1, epochs+1):
            train_loss, train_count = _epoch(model, training, weights, rng, optimizer, reference, kl_weight)
            val_loss, val_count = _epoch(model, validation, {}, rng, reference=reference, kl_weight=kl_weight)
            extra.update(train_loss=train_loss, validation_loss=val_loss,
                         train_decisions=train_count, validation_decisions=val_count)
            if val_loss < best:
                best = val_loss
                _save(out/"prior.pt", model, optimizer,
                      {"stage": "prior_complete", "epoch": epoch,
                       "validation_loss": val_loss, "initialization": config["initialization"],
                       "source_rl_sha256": config["source_rl_sha256"],
                       "source_rl_path": config["source_rl_path"]}, config)
            save()
        if not (out/"prior.pt").is_file():
            raise RuntimeError("prior checkpoint missing")
        stage = "completed"
        extra["best_validation_loss"] = best
        save("completed")
        return out/"prior.pt"
    except Exception as exc:
        extra["error"] = f"{type(exc).__name__}: {exc}"
        save("failed")
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--games", type=int, default=1000)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--simulations", type=int, default=2000)
    p.add_argument("--boss-simulations", type=int, default=10000)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--max-steps", type=int, default=5000)
    p.add_argument("--seed", type=int, default=20261030)
    p.add_argument("--combat-mode", choices=("oracle", "hidden"), default="oracle")
    p.add_argument("--seed-offset", type=int, default=0)
    p.add_argument("--init-checkpoint")
    p.add_argument("--replay-dirs", nargs="*", default=[])
    p.add_argument("--kl-weight", type=float, default=0.5)
    run(**vars(p.parse_args(argv)))


if __name__ == "__main__":
    main()
