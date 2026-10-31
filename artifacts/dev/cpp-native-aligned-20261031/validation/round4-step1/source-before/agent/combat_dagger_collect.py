"""Collect STS2 battle decisions in the style of the STS1 armD run.

The student acts from public observations. A native MCTS labels each state,
but never supplies the student's action unless ``battle_mode='teacher'`` is
explicitly selected for bootstrap data. No incomplete run publishes shards.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import torch

from .armg import build_candidates
from .armg_train import _mcts_plan
from .common import (ACTION_FEAT_DIM, ACTION_SCHEMA_VERSION, OUTCOME,
                     PUBLIC_COMBAT_OBS_DIM, PUBLIC_OBS_VERSION, SCREEN,
                     combat_action_arrays, completed_run_status, new_run,
                     public_combat_observation)


def _run_action(rc, armg, recent):
    """Original ArmG, including its observable-state cycle recovery."""
    obs, actions, features = build_candidates(rc)
    if not actions:
        raise RuntimeError(f"no legal run action on {rc.screen.name}")
    if len(actions) == 1:
        choice, scores = 0, None
    else:
        with torch.inference_mode():
            logits = armg(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])[0]
        if logits.shape != (len(actions),) or not torch.isfinite(logits).all():
            raise RuntimeError("invalid ArmG logits")
        scores = logits.cpu().numpy()
        choice = int(torch.argmax(logits))
    digest = hashlib.blake2b(digest_size=16)
    digest.update(obs.tobytes())
    digest.update(features.tobytes())
    digest.update(repr(actions).encode("utf-8"))
    key = digest.digest()
    repeats = recent.count(key)
    recent.append(key)
    forced = repeats >= 3 and len(actions) > 1
    if forced:
        order = sorted(range(len(actions)), key=lambda i: -scores[i]) if scores is not None else list(range(len(actions)))
        order = [choice] + [i for i in order if i != choice]
        choice = order[1 + ((repeats - 3) % (len(order) - 1))]
    return actions[choice], int(forced)


def _write_battle(path, records, won, hp, metadata):
    counts = np.asarray([len(r[1]) for r in records], dtype=np.int64)
    offsets = np.concatenate((np.zeros(1, dtype=np.int64), np.cumsum(counts)))
    states = np.stack([r[0] for r in records]).astype(np.float32, copy=False)
    candidates = np.concatenate([r[1] for r in records], axis=0).astype(np.float32, copy=False)
    action_ids = np.concatenate([np.asarray(r[2], dtype=np.int32) for r in records], axis=0)
    labels = np.asarray([r[3] for r in records], dtype=np.int64)
    n = len(records)
    np.savez_compressed(path, states=states, actions=candidates, action_ids=action_ids,
                        offsets=offsets, labels=labels,
                        wins=np.full(n, float(won), dtype=np.float32),
                        hp=np.full(n, hp, dtype=np.float32),
                        metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)))


def collect_episode(seed: int, policy, armg, *, teacher_sims: int = 512,
                    resample_hidden: bool = False, max_steps: int = 5000,
                    output_dir=None, collect_labels: bool = True,
                    battle_mode: str = "student", metadata=None):
    """Play one A0 run and optionally save supervised battle shards.

    Modes are student, teacher (for bootstrapping), greedy, mcts-oracle and
    mcts-resampled. The latter two reuse the existing controller's checked
    search paths. To compare the student without teacher overhead use
    ``collect_labels=False`` and ``output_dir=None``.

    A battle's samples receive value labels only after victory or death. All
    shards are staged until the *whole run* terminates; errors, step-limit
    truncation and battle truncation publish none. The output directory must
    be unique per episode or have no existing files for that seed.
    """
    modes = ("student", "teacher", "greedy", "mcts-oracle", "mcts-resampled")
    if battle_mode not in modes or teacher_sims < 1 or max_steps < 1:
        raise ValueError("invalid battle mode, teacher budget or step limit")
    if collect_labels and output_dir is None:
        raise ValueError("output_dir is required when collecting labels")
    if battle_mode == "student" and policy is None:
        raise ValueError("student mode requires a policy")
    if armg is None:
        raise ValueError("a frozen original ArmG is required")

    output = Path(output_dir).resolve() if output_dir is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
    rc = new_run(seed, 0)
    status, error = "error", None
    steps = battles = battle_wins = combat_decisions = cycle_recoveries = 0
    teacher_searches = teacher_simulations = teacher_unmatched = 0
    mcts_searches = mcts_simulations = 0
    battle_hp_sum = 0.0
    recent, combat_recent = deque(maxlen=64), deque(maxlen=64)
    records, staged = [], []
    active_battle = False
    combat_plan = []
    # Stage the whole run on the same volume; publishing the directory is a
    # single atomic rename after all battle and run outcomes are known.
    with tempfile.TemporaryDirectory(prefix=f".episode-{seed}-", dir=output) as stage:
        try:
            while rc.screen != SCREEN.RUN_OVER and steps < max_steps:
                steps += 1
                if rc.screen != SCREEN.COMBAT:
                    action, recovered = _run_action(rc, armg, recent)
                    cycle_recoveries += recovered
                    if not rc.step(*action):
                        raise RuntimeError(f"run action rejected on {rc.screen.name}: {action}")
                    continue

                if not active_battle:
                    active_battle = True
                    records = []
                    combat_recent.clear()
                    combat_plan.clear()
                bc = rc.battle
                actions, features = combat_action_arrays(bc)
                actions = [tuple(int(x) for x in action) for action in actions]
                if not actions:
                    raise RuntimeError("live battle has no legal actions")
                if len(actions) == 1:
                    action = actions[0]
                    if combat_plan:
                        if combat_plan[0] == action:
                            combat_plan.pop(0)
                        else:
                            combat_plan.clear()
                else:
                    combat_decisions += 1
                    obs = public_combat_observation(bc)
                    if obs.shape != (PUBLIC_COMBAT_OBS_DIM,) or features.shape != (len(actions), ACTION_FEAT_DIM):
                        raise RuntimeError("battle observation/action shape mismatch")
                    if not np.isfinite(obs).all() or not np.isfinite(features).all():
                        raise RuntimeError("non-finite battle observation/action")

                    teacher_idx = -1
                    if collect_labels or battle_mode == "teacher":
                        plan, done, _ = bc.mcts(teacher_sims, 3 * 2**0.5,
                            (seed + 7919 * steps) & 0xFFFFFFFF, resample_hidden, False, 0.05)
                        teacher_searches += 1
                        teacher_simulations += int(done)
                        if plan and int(done) > 0:
                            candidate = tuple(int(x) for x in plan[0])
                            if candidate in actions:
                                teacher_idx = actions.index(candidate)
                        if teacher_idx < 0:
                            teacher_unmatched += 1
                            if battle_mode == "teacher":
                                raise RuntimeError("teacher returned no legal action")

                    if battle_mode == "student":
                        with torch.inference_mode():
                            logits = policy(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])[0]
                        if logits.shape != (len(actions),) or not torch.isfinite(logits).all():
                            raise RuntimeError("invalid student logits")
                        action = actions[int(torch.argmax(logits))]
                    elif battle_mode == "teacher":
                        action = actions[teacher_idx]
                    elif battle_mode == "greedy":
                        action = tuple(bc.greedy_action(0.0, (seed + 7919 * steps) & 0xFFFFFFFF))
                    else:
                        if not combat_plan or combat_plan[0] not in actions:
                            combat_plan, done = _mcts_plan(bc, seed + 7919 * steps,
                                battle_mode, teacher_sims, 0.05, rc.combat_is_boss)
                            if done:
                                mcts_searches += 1
                                mcts_simulations += int(done)
                        action = tuple(combat_plan.pop(0))
                    if action not in actions:
                        raise RuntimeError("battle controller returned an illegal action")
                    if collect_labels:
                        records.append((obs, features, actions, teacher_idx))

                    # The public observation may collide, so use full engine
                    # state only to detect deterministic student loops, never
                    # as a policy feature or a teacher input. Repeating the
                    # exact state/action cannot progress under this policy.
                    if battle_mode == "student":
                        token = (int(rc.state_hash()), action)
                        if combat_recent.count(token) >= 2:
                            status, error = "truncated", "deterministic combat cycle"
                            break
                        combat_recent.append(token)

                if not rc.step_combat(*action):
                    raise RuntimeError(f"combat action rejected: {action}")
                if rc.screen != SCREEN.COMBAT:
                    if bc.outcome not in (OUTCOME.PLAYER_VICTORY, OUTCOME.PLAYER_LOSS):
                        status, error = "truncated", "battle did not terminate normally"
                        break
                    won = bc.outcome == OUTCOME.PLAYER_VICTORY
                    hp = float(bc.player_hp) / max(1, float(bc.player_max_hp))
                    if not np.isfinite(hp):
                        raise RuntimeError("non-finite terminal HP")
                    battle_hp_sum += hp
                    battles += 1
                    battle_wins += int(won)
                    if collect_labels and records:
                        path = Path(stage) / f"battle-{battles:04d}.npz"
                        info = dict(metadata or {})
                        info.update(seed=int(seed), battle=battles, episode_status="terminated",
                                    obs_version=int(PUBLIC_OBS_VERSION),
                                    action_schema_version=int(ACTION_SCHEMA_VERSION),
                                    obs_dim=int(PUBLIC_COMBAT_OBS_DIM), action_dim=int(ACTION_FEAT_DIM),
                                    teacher_sims=int(teacher_sims), resample_hidden=bool(resample_hidden),
                                    battle_mode=battle_mode, win=bool(won), hp=hp)
                        _write_battle(path, records, won, hp, info)
                        staged.append((path, len(records)))
                    records = []
                    active_battle = False
                    combat_plan.clear()
            else:
                status = completed_run_status(rc)

            if status == "terminated" and collect_labels:
                if staged:
                    dest = output / f"seed-{seed}"
                    if dest.exists():
                        raise FileExistsError(f"shards already exist for seed {seed}")
                    os.rename(stage, dest)
                    shards = [{"path": str(dest / path.name), "count": count}
                              for path, count in staged]
                else:
                    shards = []
            else:
                shards = []
        except (RuntimeError, ValueError, OverflowError, OSError) as exc:
            status, error, shards = "error", f"{type(exc).__name__}: {exc}", []

    return {"seed": int(seed), "status": status, "won": bool(rc.won) and status == "terminated",
            "floor": int(rc.floor), "hp": int(rc.hp), "steps": steps, "error": error,
            "battles": battles, "battle_wins": battle_wins, "battle_hp_sum": battle_hp_sum,
            "combat_decisions": combat_decisions, "teacher_searches": teacher_searches,
            "teacher_simulations": teacher_simulations, "teacher_unmatched": teacher_unmatched,
            "cycle_recoveries": cycle_recoveries, "mcts_searches": mcts_searches,
            "mcts_simulations": mcts_simulations, "shards": shards}
