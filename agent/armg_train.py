"""ArmG-style REINFORCE for all supported non-combat decisions.

The battle controller is fixed during training. ``mcts-oracle`` is a native
multi-level MCTS with access to the simulator's full battle state and future
RNG; ``mcts-resampled`` samples hidden state instead. Neither uses a network.
``search`` remains the older, resampled root-only baseline.
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import tempfile
import time

import numpy as np
import torch

from .armg import (ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM,
                   ArmGScorer, build_candidates)
from .common import PUBLIC_OBS_VERSION, SCREEN, completed_run_status, new_run
from .heuristics import run_policy
from .nets import checkpoint_config
from .policy import TRAIN_SEED_BASE, VAL_SEED_BASE


_worker_model = None
_worker_version = None


def _worker_episode(task):
    """Spawn-safe worker: load weights once per batch and seed each rollout."""
    global _worker_model, _worker_version
    run_seed, sampling_seed, version, weight_path, kwargs = task
    if _worker_model is None:
        torch.set_num_threads(1)
        _worker_model = ArmGScorer()
        _worker_model.eval()
    if _worker_version != version:
        _worker_model.load_state_dict(torch.load(weight_path, map_location="cpu", weights_only=True))
        _worker_version = version
    torch.manual_seed(sampling_seed)
    return collect_episode(run_seed, _worker_model, **kwargs)


def _combat_action(battle, seed: int, combat: str, simulations: int, epsilon: float):
    if combat == "greedy":
        return battle.greedy_action(epsilon, seed & 0xFFFFFFFF)
    if combat != "search":
        raise ValueError(f"unknown combat strategy: {combat}")
    actions, visits, values, _ = battle.search(
        simulations, 1.5, epsilon, seed & 0xFFFFFFFF, True)
    if not actions:
        raise RuntimeError("no legal combat action")
    if len(actions) == 1:
        return actions[0]
    means = [v / n if n else float("-inf") for n, v in zip(visits, values)]
    if not any(n > 0 for n in visits):
        raise RuntimeError("search completed no simulations")
    return actions[int(np.argmax(means))]


def _mcts_plan(battle, seed: int, combat: str, simulations: int,
               epsilon: float, is_boss: bool):
    """Return a checked search path and the number of completed simulations."""
    if combat not in ("mcts-oracle", "mcts-resampled"):
        raise ValueError(f"unknown MCTS mode: {combat}")
    legal = [tuple(action) for action in battle.legal_actions()]
    if not legal:
        raise RuntimeError("no legal combat action")
    if len(legal) == 1:
        return legal, 0
    actions, done, won = battle.mcts(
        simulations * (3 if is_boss else 1), 3 * 2**0.5,
        seed & 0xFFFFFFFF, combat == "mcts-resampled", False, epsilon)
    plan = [tuple(action) for action in actions]
    if not plan or plan[0] not in legal or done <= 0:
        raise RuntimeError("MCTS returned no valid action or completed simulations")
    # Resampled futures can change card identities in the same hand slot, so
    # a legal tuple alone does not make a later sampled plan safe to execute.
    return plan[:(1 if combat == "mcts-resampled" else (15 if won else 5))], int(done)


def collect_episode(seed: int, model: ArmGScorer | None, *, deterministic: bool = False,
                    combat: str = "mcts-oracle", simulations: int = 64,
                    epsilon: float = 0.05, max_steps: int = 5000,
                    ascension: int = 0, need_rules: bool = False,
                    relic_rules: bool = False, combat_budget_by_floor=None,
                    combat_budget_by_context=None, before_combat=None,
                    mcts_plan=None) -> dict:
    """Play one run; only completed runs produce REINFORCE records.

    ``model=None`` uses the existing heuristic for non-combat decisions.
    MCTS oracle uses the full simulator state; mcts-resampled resamples hidden
    information. Evaluation is greedy and does not retain policy observations.
    """
    rc = new_run(seed, ascension)
    records = []
    steps = 0
    status = "error"
    error = None
    cycle_recoveries = 0
    combat_plan = []
    mcts_searches = 0
    mcts_simulations = 0
    need_decisions = 0
    relic_decisions = 0
    recent = deque(maxlen=64)
    try:
        while rc.screen != SCREEN.RUN_OVER and steps < max_steps:
            steps += 1
            if rc.screen == SCREEN.COMBAT:
                if before_combat is not None:
                    before_combat(rc, steps)
                if combat in ("mcts-oracle", "mcts-resampled"):
                    legal = [tuple(action) for action in rc.battle.legal_actions()]
                    if not combat_plan or combat_plan[0] not in legal:
                        if combat_budget_by_context is not None:
                            # Public observation v10 exposes the actual combat
                            # flags, including elite encounters in unknown rooms.
                            if PUBLIC_OBS_VERSION != 10:
                                raise RuntimeError('unsupported combat classification observation version')
                            public = rc.observe_public()
                            if public[8] != 1 or public[9] not in (0, 1) or public[10] != int(rc.combat_is_boss):
                                raise RuntimeError('invalid public combat classification')
                            budget = combat_budget_by_context(int(rc.floor), bool(public[9]),
                                                              bool(rc.combat_is_boss))
                        else:
                            budget = (simulations if combat_budget_by_floor is None else
                                      combat_budget_by_floor(int(rc.floor)))
                        if int(budget) != budget or budget < 1:
                            raise ValueError("invalid floor-dependent combat budget")
                        combat_plan, done = (mcts_plan or _mcts_plan)(
                            rc.battle, seed + 7919 * steps, combat,
                            int(budget), epsilon, rc.combat_is_boss)
                        if done:
                            mcts_searches += 1
                            mcts_simulations += done
                    action = combat_plan.pop(0)
                else:
                    action = _combat_action(rc.battle, seed + 7919 * steps,
                                            combat, simulations, epsilon)
                if not rc.step_combat(*action):
                    raise RuntimeError(f"combat action rejected: {action}")
                if rc.screen != SCREEN.COMBAT:
                    combat_plan.clear()
                continue
            obs, actions, features = build_candidates(rc)
            if not actions:
                raise RuntimeError(f"no legal action on {rc.screen.name}")
            choice = 0
            scores = None
            bonus = mask = None
            need_active = False
            rule_forced = False
            if model is None:
                action = tuple(run_policy(rc))
                choice = actions.index(action)
            elif len(actions) == 1:
                action = actions[0]
            else:
                with torch.no_grad():
                    logits = model(torch.from_numpy(obs)[None],
                                   torch.from_numpy(features)[None])[0]
                    if not torch.isfinite(logits).all():
                        raise RuntimeError("non-finite policy logits")
                    if need_rules:
                        from .armg_need import need_overlay, apply_need_to_logits
                        bonus, mask, need_active = need_overlay(rc, actions)
                        if need_active:
                            logits = apply_need_to_logits(logits, bonus, mask, True)
                            need_decisions += 1
                    scores = logits.cpu().numpy()
                    rule_action = None
                    if relic_rules:
                        from .armg_relic import relic_action
                        rule_action = relic_action(rc, actions, logits)
                    if rule_action is not None:
                        if tuple(rule_action) not in actions:
                            raise RuntimeError("relic rule returned an illegal action")
                        choice = actions.index(tuple(rule_action))
                        rule_forced = True
                        relic_decisions += 1
                    else:
                        choice = (int(torch.argmax(logits)) if deterministic else
                                  int(torch.multinomial(torch.softmax(logits, 0), 1)))
                action = actions[choice]

            # A legal deselection or cancelled preview can return to the same
            # public state forever under argmax. Keep all legal actions, but
            # after three repeats choose a different legal action and report it.
            fingerprint = hashlib.blake2b(digest_size=16)
            fingerprint.update(obs.tobytes())
            fingerprint.update(features.tobytes())
            fingerprint.update(repr(actions).encode("utf-8"))
            key = fingerprint.digest()
            repeats = recent.count(key)
            recent.append(key)
            eligible = ([i for i in range(len(actions)) if bool(mask[i])]
                        if need_active else list(range(len(actions))))
            forced = repeats >= 3 and len(eligible) > 1
            if forced:
                if scores is None:
                    order = [choice] + [i for i in eligible if i != choice]
                else:
                    order = sorted(eligible, key=lambda i: -scores[i])
                    # A sampled action may differ from argmax; always force a
                    # different action, so this recovery can make progress.
                    order = [choice] + [i for i in order if i != choice]
                choice = order[1 + ((repeats - 3) % (len(order) - 1))]
                action = actions[choice]
                cycle_recoveries += 1
            if model is not None and not deterministic and len(actions) > 1 and not forced and not rule_forced:
                # A safety-forced action is not drawn from the policy; exclude
                # its log probability from the policy-gradient trajectory.
                records.append((obs, features, choice, bonus, mask) if need_active else
                               (obs, features, choice))
            if not rc.step(*action):
                raise RuntimeError(f"run action rejected on {rc.screen.name}: {action}")
        status = completed_run_status(rc)
    except (RuntimeError, ValueError, OverflowError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {"seed": seed, "status": status,
            "won": bool(rc.won) and status == "terminated",
            "floor": int(rc.floor), "hp": int(rc.hp), "steps": steps,
            "records": records if status == "terminated" and not deterministic else [],
            "error": error, "cycle_recoveries": cycle_recoveries,
            "mcts_searches": mcts_searches, "mcts_simulations": mcts_simulations,
            "need_decisions": need_decisions, "relic_decisions": relic_decisions}


def game_loss(model: ArmGScorer, records: list, advantage: float):
    """Sum decision log probabilities per run, as in STS1 ArmG."""
    logs = []
    for record in records:
        obs, features, choice = record[:3]
        logits = model(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])[0]
        if len(record) > 3:
            from .armg_need import apply_need_to_logits
            logits = apply_need_to_logits(logits, record[3], record[4], True)
        logs.append(torch.log_softmax(logits, dim=0)[choice])
    return -float(advantage) * torch.stack(logs).sum() if logs else None


def backward_weighted(model: ArmGScorer, weighted: list, chunk_size: int = 16) -> float:
    """Accumulate mean per-run REINFORCE gradients using bounded decision batches.

    ``weighted`` is [(records, advantage), ...]; each record has a different
    number of legal actions. Padding is masked before the softmax. The per-run
    denominator stays unchanged even when a run spans multiple chunks.
    """
    if not weighted:
        return 0.0
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    decisions = [(record, advantage) for records, advantage in weighted for record in records]
    loss_value = 0.0
    for start in range(0, len(decisions), chunk_size):
        chunk = decisions[start:start + chunk_size]
        n = len(chunk)
        max_actions = max(len(record[0][1]) for record in chunk)
        obs = np.stack([record[0][0] for record in chunk])
        candidates = np.zeros((n, max_actions, ARMG_ACTION_DIM), dtype=np.float32)
        choices = np.empty(n, dtype=np.int64)
        advantages = np.empty(n, dtype=np.float32)
        for i, (record, advantage) in enumerate(chunk):
            _, features, choice = record[:3]
            candidates[i, :len(features)] = features
            choices[i] = choice
            advantages[i] = advantage
        logits = model(torch.from_numpy(obs), torch.from_numpy(candidates))
        # Preserve the exact per-decision transform used for sampling. Padded
        # values must not participate in the z-score normalization.
        rows = []
        for i, (record, _) in enumerate(chunk):
            count = len(record[1])
            row = logits[i, :count]
            if len(record) > 3:
                from .armg_need import apply_need_to_logits
                row = apply_need_to_logits(row, record[3], record[4], True)
            rows.append(torch.nn.functional.pad(row, (0, max_actions - count), value=float("-inf")))
        logits = torch.stack(rows)
        log_probs = torch.log_softmax(logits, dim=1)
        chosen = log_probs[torch.arange(n), torch.from_numpy(choices)]
        loss = -(chosen * torch.from_numpy(advantages)).sum() / len(weighted)
        if not torch.isfinite(loss):
            raise RuntimeError("non-finite loss")
        loss_value += float(loss.detach())
        loss.backward()
    return loss_value


def summarize(episodes: list[dict]) -> dict:
    completed = [ep for ep in episodes if ep["status"] == "terminated"]
    return {"runs": len(episodes), "completed": len(completed),
            "truncated": sum(ep["status"] == "truncated" for ep in episodes),
            "errors": sum(ep["status"] == "error" for ep in episodes),
            "cycle_recoveries": sum(ep.get("cycle_recoveries", 0) for ep in episodes),
            "runs_with_recovery": sum(ep.get("cycle_recoveries", 0) > 0 for ep in episodes),
            "mcts_searches": sum(ep.get("mcts_searches", 0) for ep in episodes),
            "mcts_simulations": sum(ep.get("mcts_simulations", 0) for ep in episodes),
            "mean_floor": (float(np.mean([ep["floor"] for ep in completed]))
                           if completed else None),
            "win_rate": (float(np.mean([ep["won"] for ep in completed]))
                         if completed else None)}


def _save(path: Path, model, optimizer, progress: dict, settings: dict):
    config = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                         "armg_obs_dim": ARMG_OBS_DIM,
                                         "armg_action_dim": ARMG_ACTION_DIM}
    payload = {"state_dict": model.state_dict(), "config": config,
               "optimizer_state_dict": optimizer.state_dict(), "progress": progress,
               "settings": settings, "torch_rng_state": torch.get_rng_state(),
               "python_rng_state": random.getstate(), "numpy_rng_state": np.random.get_state()}
    temp = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temp)
    os.replace(temp, path)


def _restore(path: str, model, optimizer, settings: dict) -> dict:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    config = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                         "armg_obs_dim": ARMG_OBS_DIM,
                                         "armg_action_dim": ARMG_ACTION_DIM}
    if payload.get("config") != config:
        raise ValueError("checkpoint observation/action schema or model shape mismatch")
    saved_settings = dict(payload.get("settings", {}))
    saved_settings.setdefault("train_seed_offset", 0)
    saved_settings.setdefault("need_rules", False)
    saved_settings.setdefault("relic_rules", False)
    if saved_settings != settings:
        raise ValueError("checkpoint training settings differ; resume with matching settings")
    model.load_state_dict(payload["state_dict"])
    optimizer.load_state_dict(payload["optimizer_state_dict"])
    torch.set_rng_state(payload["torch_rng_state"])
    random.setstate(payload["python_rng_state"])
    np.random.set_state(payload["numpy_rng_state"])
    return payload["progress"]


def _warm_start(path: str, model) -> dict:
    """Initialize model weights only and record the source for a new run."""
    source = Path(path).resolve()
    content = source.read_bytes()
    payload = torch.load(source, map_location="cpu", weights_only=False)
    expected = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                           "armg_obs_dim": ARMG_OBS_DIM,
                                           "armg_action_dim": ARMG_ACTION_DIM}
    if payload.get("config") != expected:
        raise ValueError("initial checkpoint observation/action schema or model shape mismatch")
    model.load_state_dict(payload["state_dict"])
    return {"mode": "weights_only", "source": str(source),
            "sha256": hashlib.sha256(content).hexdigest(),
            "source_settings": payload.get("settings"),
            "source_progress": payload.get("progress")}


def train(*, games: int = 8000, batch_size: int = 32, eval_every: int = 400,
          eval_runs: int = 50, out_dir: str = "runs/armg", resume: str | None = None,
          init_checkpoint: str | None = None, train_seed_offset: int = 0,
          combat: str = "mcts-oracle", simulations: int = 64, epsilon: float = 0.05,
          max_steps: int = 5000, ascension: int = 0, seed: int = 1,
          lr: float = 1e-3, workers: int = 1, need_rules: bool = False,
          relic_rules: bool = False) -> ArmGScorer:
    if games < 1 or batch_size < 1 or eval_every < 1 or eval_runs < 1:
        raise ValueError("games, batch size, evaluation interval and count must be positive")
    if simulations < 1 or max_steps < 1 or workers < 1 or not 0 <= epsilon <= 1:
        raise ValueError("invalid combat simulation count, step limit or epsilon")
    if resume and init_checkpoint:
        raise ValueError("--resume and --init-checkpoint are mutually exclusive")
    if train_seed_offset < 0 or train_seed_offset + games > VAL_SEED_BASE - TRAIN_SEED_BASE:
        raise ValueError("training seeds would overlap validation seeds")
    torch.set_num_threads(1)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = ArmGScorer()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    settings = {"combat": combat, "simulations": simulations, "epsilon": epsilon,
                "max_steps": max_steps, "ascension": ascension, "seed": seed,
                "batch_size": batch_size, "eval_every": eval_every, "eval_runs": eval_runs,
                "lr": lr, "train_seed_offset": train_seed_offset,
                "need_rules": need_rules, "relic_rules": relic_rules}
    progress = {"games": 0, "baseline": None, "best_floor": None,
                "completed": 0, "truncated": 0, "errors": 0}
    if resume:
        progress = _restore(resume, model, optimizer, settings)
    elif init_checkpoint:
        progress["initialization"] = _warm_start(init_checkpoint, model)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not resume and (out / "latest.pt").exists():
        raise FileExistsError(f"{out} already contains a run; use --resume or a new directory")
    kwargs = dict(combat=combat, simulations=simulations, epsilon=epsilon,
                  max_steps=max_steps, ascension=ascension,
                  need_rules=need_rules, relic_rules=relic_rules)
    with ExitStack() as stack:
        log = stack.enter_context((out / "metrics.jsonl").open("a", encoding="utf-8"))
        worker_dir = (stack.enter_context(tempfile.TemporaryDirectory(prefix=".armg-workers-", dir=out))
                      if workers > 1 else None)
        pool = (stack.enter_context(ProcessPoolExecutor(max_workers=workers,
                mp_context=mp.get_context("spawn"))) if workers > 1 else None)
        while progress["games"] < games:
            start = time.monotonic()
            remaining_to_eval = eval_every - progress["games"] % eval_every
            count = min(batch_size, games - progress["games"], remaining_to_eval)
            if pool:
                # Each batch completes before the same file is atomically replaced.
                # Per-episode seeds are allocated by the checkpointed parent RNG,
                # so dispatch order and worker count do not alter rollout sampling.
                path = Path(worker_dir) / "weights.pt"
                temp_path = Path(worker_dir) / "weights.tmp"
                torch.save(model.state_dict(), temp_path)
                os.replace(temp_path, path)
                sample_seeds = torch.randint(0, 2**31 - 1, (count,)).tolist()
                version = progress["games"]
                tasks = [(TRAIN_SEED_BASE + train_seed_offset + progress["games"] + i, sample_seeds[i],
                          version, str(path.resolve()), kwargs) for i in range(count)]
                episodes = list(pool.map(_worker_episode, tasks, chunksize=1))
                progress["rollout_mode"] = "parallel-seeded-v1"
            else:
                episodes = [collect_episode(TRAIN_SEED_BASE + train_seed_offset + progress["games"] + i,
                                            model, **kwargs) for i in range(count)]
                progress["rollout_mode"] = "serial-global-v1"
            weighted = []
            for ep in episodes:
                key = {"terminated": "completed", "truncated": "truncated", "error": "errors"}[ep["status"]]
                progress[key] += 1
                if ep["status"] != "terminated":
                    continue
                reward = ep["floor"] / 50.0
                old = progress["baseline"]
                progress["baseline"] = reward if old is None else 0.99 * old + 0.01 * reward
                if ep["records"]:
                    weighted.append((ep["records"], reward - progress["baseline"]))
            optimizer.zero_grad()
            loss_value = None
            if weighted:
                loss_value = backward_weighted(model, weighted)
                optimizer.step()
            progress["games"] += count
            record = {"games": progress["games"], "train": summarize(episodes),
                      "baseline": progress["baseline"],
                      "loss": loss_value,
                      "seconds": round(time.monotonic() - start, 3),
                      "errors": [ep["error"] for ep in episodes if ep["error"]]}
            if need_rules or relic_rules:
                record["train"]["need_decisions"] = sum(ep["need_decisions"] for ep in episodes)
                record["train"]["relic_decisions"] = sum(ep["relic_decisions"] for ep in episodes)
            if progress["games"] % eval_every == 0 or progress["games"] == games:
                validation = [collect_episode(VAL_SEED_BASE + i, model,
                                              deterministic=True, **kwargs)
                              for i in range(eval_runs)]
                record["validation"] = summarize(validation)
                if need_rules or relic_rules:
                    record["validation"]["need_decisions"] = sum(ep["need_decisions"] for ep in validation)
                    record["validation"]["relic_decisions"] = sum(ep["relic_decisions"] for ep in validation)
                val = record["validation"]
                # Selecting a best model from incomplete episodes biases upward.
                if val["completed"] == eval_runs and (progress["best_floor"] is None or
                                                       val["mean_floor"] > progress["best_floor"]):
                    progress["best_floor"] = val["mean_floor"]
                    _save(out / "best.pt", model, optimizer, progress, settings)
            _save(out / "latest.pt", model, optimizer, progress, settings)
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()
            print(json.dumps(record, ensure_ascii=False), flush=True)
    return model


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=8000, help="total training runs, including restored progress")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--eval-every", type=int, default=400)
    parser.add_argument("--eval-runs", type=int, default=50)
    parser.add_argument("--out-dir", default="runs/armg")
    parser.add_argument("--resume")
    parser.add_argument("--init-checkpoint", help="start a separate run from these model weights only")
    parser.add_argument("--train-seed-offset", type=int, default=0,
                        help="offset from training seed base; use a disjoint range for warm starts")
    parser.add_argument("--combat", choices=("mcts-oracle", "mcts-resampled", "search", "greedy"),
                        default="mcts-oracle")
    parser.add_argument("--simulations", type=int, default=64)
    parser.add_argument("--epsilon", type=float, default=0.05)
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--workers", type=int, default=1,
                        help="spawn rollout processes; 1 uses the original serial sampler")
    parser.add_argument("--need-rules", action="store_true", help="enable STS2 deck-need reward scoring")
    parser.add_argument("--relic-rules", action="store_true", help="enable shop and Ancient relic priorities")
    args = vars(parser.parse_args(argv))
    train(**args)


if __name__ == "__main__":
    main()
