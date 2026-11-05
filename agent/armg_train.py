"""PPO training for the Ironclad out-of-combat (ArmG) policy.

Only non-combat decisions are learned. The battle controller is a separate,
fixed controller and is **not** trained here:

- ``mcts-oracle`` uses the simulator's full battle state and future RNG, so a
  run using it must never be described as a player-visible-information policy.
- ``mcts-resampled`` resamples hidden state and only sees public information.
- ``search`` is the older resampled root-only search; ``greedy`` is a
  player-visible greedy rollout.

The actor sees ``public_observation`` only. Runs use
``RunContentProfile.SINGLE_PLAYER_TRAINING`` so CrystalSphere and
multiplayer-only cards cannot reach a rollout; the trainer asserts this after
every step rather than trusting the pools.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import ExitStack
import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import tempfile
import time

import numpy as np
import torch

from . import content_profile as _content_profile
_PROFILE = _content_profile.PROFILE
# ArmGScorer and backward_weighted stay for the existing REINFORCE deployment
# trainers; the trainer in this module is PPO.
from .armg import (ARMG_ACTION_DIM, ARMG_FEATURE_VERSION, ARMG_OBS_DIM,
                   ArmGScorer, build_candidates)
from .armg_ppo import ArmGActorCritic, TrajectoryRecorder, update as ppo_update
from .common import (OUTCOME, PUBLIC_OBS_VERSION, RACT, SCREEN, completed_run_status,
                     new_run)
from .run_reward import DeckElo, RunRewardTracker, terminal_reward
from .heuristics import run_policy
from .nets import checkpoint_config, read_checkpoint
from .engine_identity import bind_settings
from .policy import TRAIN_SEED_BASE, VAL_SEED_BASE


_worker_model = None
_worker_version = None


def _worker_episode(task):
    """Spawn-safe worker: load weights once per batch and seed each rollout."""
    global _worker_model, _worker_version
    run_seed, sampling_seed, version, weight_path, kwargs = task
    if _worker_model is None:
        torch.set_num_threads(1)
        _worker_model = ArmGActorCritic()
        _worker_model.eval()
    kwargs = dict(kwargs)
    elo_path = kwargs.pop("deck_elo_path", None)
    if _worker_version != version:
        _worker_model.load_state_dict(torch.load(weight_path, map_location="cpu", weights_only=True))
        _worker_version = version
    torch.manual_seed(sampling_seed)
    return collect_episode(run_seed, _worker_model,
                           trajectory=TrajectoryRecorder(_worker_model),
                           deck_elo=DeckElo(elo_path) if elo_path else None, **kwargs)


class FloorBudget:
    """Reference-style search budget: base + per-floor, extra for elite/boss.

    A module-level object so ``spawn`` workers can pickle it; a closure would
    silently downgrade parallel rollouts to an error.
    """

    def __init__(self, base: int, per_floor: int = 0, elite: int = 0, boss: int = 0):
        self.base, self.per_floor, self.elite, self.boss = base, per_floor, elite, boss

    def __call__(self, floor: int, elite: bool, boss: bool) -> int:
        return (self.base + self.per_floor * max(0, int(floor) - 1)
                + (self.elite if elite else 0) + (self.boss if boss else 0))

    def as_dict(self) -> dict:
        return {"base": self.base, "per_floor": self.per_floor,
                "elite": self.elite, "boss": self.boss}


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
        simulations, 3 * 2**0.5,
        seed & 0xFFFFFFFF, combat == "mcts-resampled", False, epsilon)
    plan = [tuple(action) for action in actions]
    if not plan or plan[0] not in legal or done <= 0:
        raise RuntimeError("MCTS returned no valid action or completed simulations")
    # Resampled futures can change card identities in the same hand slot, so
    # a legal tuple alone does not make a later sampled plan safe to execute.
    return plan[:(1 if combat == "mcts-resampled" else (15 if won else 5))], int(done)


def _scored_state(rc) -> dict:
    """Counters this reward scores, read before/after a run action.

    ``cardShopRemovalsUsed`` only advances on a completed removal and the deck
    upgrade count only on a completed upgrade, so a cancelled preview or a
    no-op cannot be credited.
    """
    upgrades = sum(1 for card in rc.deck if card[1])
    return {"upgrades": upgrades, "removals": int(rc.card_shop_removals_used)}


def collect_episode(seed: int, model: "ArmGActorCritic | None", *, deterministic: bool = False,
                    combat: str = "mcts-oracle", simulations: int = 64,
                    epsilon: float = 0.05, max_steps: int = 5000,
                    ascension: int = 0, need_rules: bool = False,
                    relic_rules: bool = False, combat_budget_by_floor=None,
                    combat_budget_by_context=None, before_combat=None,
                    mcts_plan=None, trajectory=None, deck_elo=None,
                    content_profile=None) -> dict:
    """Play one run; only completed runs produce REINFORCE/PPO records.

    ``model=None`` uses the existing heuristic for non-combat decisions.
    MCTS oracle uses the full simulator state; mcts-resampled resamples hidden
    information. Evaluation is greedy and does not retain policy observations.

    ``trajectory`` (a TrajectoryRecorder) receives one row per non-combat
    decision. The run's terminal reward is split into per-decision increments,
    so the trajectory's rewards always sum to the terminal reward of a normally
    ended run; errors and truncations never produce rows.
    """
    if trajectory is not None and (model is None or deterministic):
        raise ValueError('trajectory collection needs a sampling policy and a live run')
    rc = new_run(seed, ascension, content_profile=content_profile)
    # The runtime guard only makes sense for the filtered profile; an ORIGINAL
    # run is allowed to contain the excluded event.
    content_profile_enabled = (content_profile is not None
                               and int(content_profile) == int(_PROFILE))
    reward = RunRewardTracker()
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
    visits = {}  # Whole-episode counts: long preview/cancel cycles must not age out.
    event = None            # the scored state change of the last decision
    pending_boss = False
    try:
        while rc.screen != SCREEN.RUN_OVER and steps < max_steps and not rc.truncated:
            steps += 1
            reward.observe(rc)
            if content_profile_enabled:
                _content_profile.assert_run_is_clean(rc)
            if rc.screen == SCREEN.COMBAT:
                if before_combat is not None:
                    before_combat(rc, steps)
                if combat in ("mcts-oracle", "mcts-resampled"):
                    legal = [tuple(action) for action in rc.battle.legal_actions()]
                    if not combat_plan or combat_plan[0] not in legal:
                        if combat_budget_by_context is not None:
                            # observe.cpp writes inBattle/elite/boss directly
                            # from RunContext at slots 8/9/10. Elite is not
                            # separately exported by this binding; use the
                            # public native flag, never the map room type.
                            if PUBLIC_OBS_VERSION != 20:
                                raise RuntimeError('unsupported combat classification observation version')
                            public = rc.observe_public()
                            boss = bool(rc.combat_is_boss)
                            if (len(public) < 11 or public[8] != 1 or public[9] not in (0, 1) or
                                    public[10] != int(boss) or (public[9] == 1 and boss)):
                                raise RuntimeError('invalid public combat classification')
                            budget = combat_budget_by_context(int(rc.floor), bool(public[9]), boss)
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
                # Boss/elite identity is read before the fight because the
                # room flags are only set while entering the combat.
                entering_elite = bool(rc.combat_is_elite)
                entering_boss = bool(rc.combat_is_boss)
                entering_act = int(rc.act) + 1
                if not rc.step_combat(*action):
                    raise RuntimeError(f"combat action rejected: {action}")
                if rc.screen != SCREEN.COMBAT:
                    combat_plan.clear()
                    won_fight = rc.battle.outcome == OUTCOME.PLAYER_VICTORY
                    if won_fight and entering_boss:
                        reward.boss_defeated()
                    elif won_fight and entering_elite:
                        reward.elite_defeated(entering_act)
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
            counts = visits.setdefault(key, [0] * len(actions))
            repeats = sum(counts)
            eligible = ([i for i in range(len(actions)) if bool(mask[i])]
                        if need_active else list(range(len(actions))))
            forced = repeats >= 3 and len(eligible) > 1
            if forced:
                # Fair exploration of exits from this exact public state. A
                # rolling window/modulo can repeatedly forget the same cycle.
                alternatives = [i for i in eligible if i != choice]
                choice = min(alternatives, key=lambda i: (counts[i],
                             -float(scores[i]) if scores is not None else i))
                action = actions[choice]
                cycle_recoveries += 1
            counts[choice] += 1
            # The cumulative reward is read before the action is applied: a
            # scored action (upgrade, removal) is credited to the decision that
            # chose it. Forced and single-action steps still advance the
            # timeline; their increment lands on the previous policy row.
            if trajectory is not None and not deterministic:
                trajectory.record(obs, features, choice, forced or rule_forced,
                                  reward.cumulative(),
                                  bonus=bonus if need_active else None,
                                  allowed=mask if need_active else None)
            if trajectory is None and model is not None and not deterministic and len(actions) > 1 and not forced and not rule_forced:
                # A safety-forced action is not drawn from the policy; exclude
                # its log probability from the policy-gradient trajectory.
                records.append((obs, features, choice, bonus, mask) if need_active else
                               (obs, features, choice))
            before = _scored_state(rc)
            if not rc.step(*action):
                raise RuntimeError(f"run action rejected on {rc.screen.name}: {action}")
            after = _scored_state(rc)
            # U and D count the campfire/shop action itself. An event or relic
            # that upgrades or removes a card is not a campfire upgrade or a
            # shop removal and must not be credited here.
            if action[0] == int(RACT.REST_UPGRADE) and after["upgrades"] > before["upgrades"]:
                reward.upgraded()
            elif action[0] == int(RACT.REMOVE_CARD) and after["removals"] > before["removals"]:
                reward.removed()
        status = completed_run_status(rc)
    except (RuntimeError, ValueError, OverflowError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    won = bool(rc.won) and status == "terminated"
    deck_stats = deck_elo(rc.deck) if deck_elo is not None and status == "terminated" else {}
    components = reward.components()
    total = terminal_reward(components, deck_stats.get("deck_elo_bonus", 0.0)) if status == "terminated" else None
    ppo_records = []
    if trajectory is not None and status == "terminated":
        ppo_records = trajectory.finish(total)
    return {"seed": seed, "status": status,
            "won": won,
            "floor": int(rc.floor), "hp": int(rc.hp), "steps": steps,
            "records": records if status == "terminated" and not deterministic else [],
            "ppo_records": ppo_records,
            "reward": components, "total_reward": total,
            **deck_stats,
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


def _mean_components(episodes: list[dict]) -> dict:
    """Mean of each terminal-reward component over completed runs.

    Recorded separately so a bonus cannot be double counted and a missing Elo
    card stays visible in the metrics.
    """
    if not episodes:
        return {}
    keys = ("floor_reward", "elite_bonus", "boss_bonus", "upgrade_bonus",
            "removal_bonus", "deck_elo_bonus")
    out = {key: float(np.mean([ep["reward"].get(key, 0.0) if key in ep["reward"]
                               else ep.get(key, 0.0) for ep in episodes]))
           for key in keys}
    out["total_reward"] = float(np.mean([ep["total_reward"] for ep in episodes]))
    out["deck_mean_elo"] = float(np.mean([ep["deck_mean_elo"] for ep in episodes]))
    out["deck_elo_missing"] = sum(ep["deck_elo_missing"] for ep in episodes)
    out["deck_elo_excluded"] = sum(ep["deck_elo_excluded"] for ep in episodes)
    out["campfire_upgrades"] = sum(ep["reward"]["campfire_upgrades"] for ep in episodes)
    out["shop_removals"] = sum(ep["reward"]["shop_removals"] for ep in episodes)
    out["bosses"] = sum(ep["reward"]["bosses"] for ep in episodes)
    return out


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
        # Production records are float32; keeping the input dtype lets a test
        # drive the same transform in float64 to separate arithmetic from
        # float32 accumulation-order noise.
        dtype = obs.dtype
        candidates = np.zeros((n, max_actions, ARMG_ACTION_DIM), dtype=dtype)
        choices = np.empty(n, dtype=np.int64)
        advantages = np.empty(n, dtype=dtype)
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
            "mean_reward": (float(np.mean([ep["total_reward"] for ep in completed]))
                            if completed and all(ep.get("total_reward") is not None for ep in completed) else None),
            "mean_floor": (float(np.mean([ep["floor"] for ep in completed]))
                           if completed else None),
            "win_rate": (float(np.mean([ep["won"] for ep in completed]))
                         if completed else None)}


def _save(path: Path, model, optimizer, progress: dict, settings: dict):
    settings = bind_settings(settings)
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
    payload = read_checkpoint(path)
    if payload.get("checkpoint_kind") == "weights_only_migration":
        raise ValueError("weights-only migration cannot resume training; use --init-checkpoint")
    config = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                         "armg_obs_dim": ARMG_OBS_DIM,
                                         "armg_action_dim": ARMG_ACTION_DIM}
    if payload.get("config") != config:
        raise ValueError("checkpoint engine identity, observation/action schema or model shape mismatch")
    saved_settings = dict(payload.get("settings", {}))
    saved_settings.setdefault("train_seed_offset", 0)
    saved_settings.setdefault("need_rules", False)
    saved_settings.setdefault("relic_rules", False)
    if saved_settings != bind_settings(settings):
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
    payload = read_checkpoint(io.BytesIO(content))
    expected = checkpoint_config(model) | {"armg_feature_version": ARMG_FEATURE_VERSION,
                                           "armg_obs_dim": ARMG_OBS_DIM,
                                           "armg_action_dim": ARMG_ACTION_DIM}
    if payload.get("config") != expected:
        raise ValueError("initial checkpoint engine identity, observation/action schema or model shape mismatch")
    model.load_state_dict(payload["state_dict"])
    return {"mode": "weights_only", "source": str(source),
            "sha256": hashlib.sha256(content).hexdigest(),
            "source_settings": payload.get("settings"),
            "source_progress": payload.get("progress"),
            "source_migration": payload.get("migration")}


def train(*, games: int = 8000, batch_size: int = 32, eval_every: int = 400,
          eval_runs: int = 50, out_dir: str = "runs/armg", resume: str | None = None,
          init_checkpoint: str | None = None, train_seed_offset: int = 0,
          combat: str = "mcts-oracle", simulations: int = 64, epsilon: float = 0.05,
          floor_increment: int = 0, elite_simulations: int = 0,
          boss_simulations: int = 0,
          max_steps: int = 5000, ascension: int = 0, seed: int = 1,
          lr: float = 3e-4, workers: int = 1, need_rules: bool = False,
          relic_rules: bool = False, elo_data=None, ppo_epochs: int = 4,
          ppo_minibatch: int = 128, clip_ratio: float = 0.2,
          target_kl: float = 0.02, value_coef: float = 0.5,
          entropy_coef: float = 0.01, max_grad_norm: float = 0.5,
          gamma: float = 1.0, gae_lambda: float = 0.95) -> ArmGActorCritic:
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
    model = ArmGActorCritic()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    deck_elo = DeckElo(elo_data)
    profile = _content_profile.identity()
    # Reference config: budget grows with the floor and adds a bonus for
    # elite and boss fights. Zero increments keep the flat budget.
    budget = FloorBudget(simulations, floor_increment, elite_simulations, boss_simulations)
    settings = {"combat": combat, "simulations": simulations, "epsilon": epsilon,
                "search_budget": budget.as_dict(),
                "trainer_version": 2, "rollout_mode": "episode-seeded-v2",
                "best_metric": "mean_reward",
                "max_steps": max_steps, "ascension": ascension, "seed": seed,
                "batch_size": batch_size, "eval_every": eval_every, "eval_runs": eval_runs,
                "lr": lr, "train_seed_offset": train_seed_offset,
                "need_rules": need_rules, "relic_rules": relic_rules,
                "content_profile": profile, "algorithm": "ppo",
                "battle_controller": combat,
                "battle_controller_info": ("full simulator state and future RNG"
                                           if combat == "mcts-oracle" else
                                           "resampled hidden state" if combat == "mcts-resampled"
                                           else "player-visible greedy rollout"),
                "elo_snapshot": deck_elo.identity(),
                "ppo": {"epochs": ppo_epochs, "minibatch": ppo_minibatch,
                        "clip_ratio": clip_ratio, "target_kl": target_kl,
                        "value_coef": value_coef, "entropy_coef": entropy_coef,
                        "max_grad_norm": max_grad_norm, "gamma": gamma,
                        "gae_lambda": gae_lambda}}
    settings = bind_settings(settings)
    ppo_kwargs = dict(epochs=ppo_epochs, minibatch_size=ppo_minibatch,
                      clip_ratio=clip_ratio, target_kl=target_kl, gamma=gamma,
                      gae_lambda=gae_lambda, value_coef=value_coef,
                      entropy_coef=entropy_coef, max_grad_norm=max_grad_norm)
    progress = {"games": 0, "baseline_reward": None, "best_floor": None,
                "completed": 0, "truncated": 0, "errors": 0, "best_reward": None}
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
                  need_rules=need_rules, relic_rules=relic_rules,
                  content_profile=_PROFILE,
                  combat_budget_by_context=budget)
    # Workers receive the Elo data path, not the object (spawned processes
    # cannot inherit it) and build their own recorder.
    worker_kwargs = dict(kwargs, deck_elo_path=str(deck_elo.data_dir))
    with ExitStack() as stack:
        log = stack.enter_context((out / "metrics.jsonl").open("a", encoding="utf-8"))
        worker_events = stack.enter_context((out / "worker-events.jsonl").open("a", encoding="utf-8"))
        worker_dir = (stack.enter_context(tempfile.TemporaryDirectory(prefix=".armg-workers-", dir=out))
                      if workers > 1 else None)
        pool = (stack.enter_context(ProcessPoolExecutor(max_workers=workers,
                mp_context=mp.get_context("spawn"))) if workers > 1 else None)
        while progress["games"] < games:
            start = time.monotonic()
            remaining_to_eval = eval_every - progress["games"] % eval_every
            count = min(batch_size, games - progress["games"], remaining_to_eval)
            batch_rng = torch.get_rng_state()
            sample_seeds = torch.randint(0, 2**31 - 1, (count,)).tolist()
            pool_restarts = 0
            if pool:
                # Each batch completes before the same file is atomically replaced.
                # Per-episode seeds are allocated by the checkpointed parent RNG,
                # so dispatch order and worker count do not alter rollout sampling.
                path = Path(worker_dir) / "weights.pt"
                temp_path = Path(worker_dir) / "weights.tmp"
                torch.save(model.state_dict(), temp_path)
                os.replace(temp_path, path)
                version = progress["games"]
                tasks = [(TRAIN_SEED_BASE + train_seed_offset + progress["games"] + i, sample_seeds[i],
                          version, str(path.resolve()), worker_kwargs) for i in range(count)]
                while True:
                    try:
                        episodes = list(pool.map(_worker_episode, tasks, chunksize=1))
                        break
                    except BrokenProcessPool as exc:
                        pool.shutdown(wait=True, cancel_futures=True)
                        pool_restarts += 1
                        worker_events.write(json.dumps({"event": "worker_pool_failure", "games": progress["games"],
                                              "attempt": pool_restarts, "error": str(exc)}) + "\n")
                        worker_events.flush()
                        if pool_restarts > 1:
                            # Preserve the pre-batch RNG so an explicit resume retries exactly this batch.
                            torch.set_rng_state(batch_rng)
                            _save(out / "latest.pt", model, optimizer, progress, settings)
                            raise
                        pool = stack.enter_context(ProcessPoolExecutor(max_workers=workers,
                            mp_context=mp.get_context("spawn")))
            else:
                episodes = []
                for i in range(count):
                    # Match parallel workers without consuming the parent's PPO RNG.
                    with torch.random.fork_rng(devices=[]):
                        torch.manual_seed(sample_seeds[i])
                        episodes.append(collect_episode(
                            TRAIN_SEED_BASE + train_seed_offset + progress["games"] + i, model,
                            trajectory=TrajectoryRecorder(model), deck_elo=deck_elo, **kwargs))
            progress["rollout_mode"] = "episode-seeded-v2"
            progress["workers"] = workers
            completed = [ep for ep in episodes if ep["status"] == "terminated"]
            for ep in episodes:
                progress[{"terminated": "completed", "truncated": "truncated",
                          "error": "errors"}[ep["status"]]] += 1
            # PPO only accepts complete episodes; errors/truncations are
            # reported and dropped, never scored as normal game overs. A run
            # whose every non-combat decision was forced has an empty
            # trajectory and contributes nothing to the actor.
            ppo_metrics = None
            scored = [ep for ep in completed if ep["ppo_records"]]
            if scored:
                ppo_metrics = ppo_update(model, optimizer, scored, **ppo_kwargs)
            progress["games"] += count
            rewards = [ep["total_reward"] for ep in completed]
            old = progress["baseline_reward"]
            if rewards:
                batch_mean = float(np.mean(rewards))
                progress["baseline_reward"] = (batch_mean if old is None else
                                               0.99 * old + 0.01 * batch_mean)
            record = {"games": progress["games"], "train": summarize(episodes),
                      "baseline_reward": progress["baseline_reward"],
                      "ppo": ppo_metrics, "workers": workers, "pool_restarts": pool_restarts,
                      "reward_components": _mean_components(completed),
                      "seconds": round(time.monotonic() - start, 3),
                      "errors": [ep["error"] for ep in episodes if ep["error"]]}
            if need_rules or relic_rules:
                record["train"]["need_decisions"] = sum(ep["need_decisions"] for ep in episodes)
                record["train"]["relic_decisions"] = sum(ep["relic_decisions"] for ep in episodes)
            if progress["games"] % eval_every == 0 or progress["games"] == games:
                validation = [collect_episode(VAL_SEED_BASE + i, model,
                                              deterministic=True, deck_elo=deck_elo, **kwargs)
                              for i in range(eval_runs)]
                record["validation"] = summarize(validation)
                if need_rules or relic_rules:
                    record["validation"]["need_decisions"] = sum(ep["need_decisions"] for ep in validation)
                    record["validation"]["relic_decisions"] = sum(ep["relic_decisions"] for ep in validation)
                val = record["validation"]
                # Selecting a best model from incomplete episodes biases upward.
                if val["completed"] == eval_runs and (progress["best_reward"] is None or
                                                       val["mean_reward"] > progress["best_reward"]):
                    progress["best_reward"] = val["mean_reward"]
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
    parser.add_argument("--floor-increment", type=int, default=0,
                        help="extra MCTS simulations per floor above 1")
    parser.add_argument("--elite-simulations", type=int, default=0,
                        help="extra MCTS simulations for elite fights")
    parser.add_argument("--boss-simulations", type=int, default=0,
                        help="extra MCTS simulations for boss fights")
    parser.add_argument("--epsilon", type=float, default=0.05)
    parser.add_argument("--max-steps", type=int, default=5000)
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--workers", type=int, default=1,
                        help="spawn rollout processes; episode sampling is independent of worker count")
    parser.add_argument("--elo-data", help="frozen card-Elo snapshot directory")
    # PPO hyperparameters; defaults match deployment/train_armg_a10_ppo.py.
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--ppo-minibatch", type=int, default=128)
    parser.add_argument("--clip-ratio", type=float, default=0.2)
    parser.add_argument("--target-kl", type=float, default=0.02)
    parser.add_argument("--value-coef", type=float, default=0.5)
    parser.add_argument("--entropy-coef", type=float, default=0.01)
    parser.add_argument("--max-grad-norm", type=float, default=0.5)
    parser.add_argument("--gamma", type=float, default=1.0)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--need-rules", action="store_true", help="enable STS2 deck-need reward scoring")
    parser.add_argument("--relic-rules", action="store_true", help="enable shop and Ancient relic priorities")
    args = vars(parser.parse_args(argv))
    train(**args)


if __name__ == "__main__":
    main()
