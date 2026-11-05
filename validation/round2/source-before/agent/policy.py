"""Strategy entry points for every run screen.

The combat policy and the run-level policy are separate concerns:

* combat: ``greedy`` (C++ 1-ply heuristic), ``network`` (policy head argmax),
  ``search`` (root PUCT with network priors and greedy rollouts).
* cards: ``heuristic`` or the learned ``CardScorer``.
* map / shop / event / rest / treasure: the deterministic heuristics in
  :mod:`agent.heuristics` (the learned models do not cover these screens).

Search is a *root* search: every simulation picks a root action and then rolls
out greedily; there is no tree below the root and the value head is not used
inside the search. ``resample=True`` is the player-usable variant: hidden zones
(draw/discard order and the future RNG stream) are re-drawn per simulation.
``resample=False`` is an oracle search over the true state and must not be
reported as a player-usable result.  The ``heuristic`` combat strategy also
resamples before its rollouts; ``heuristic_oracle`` keeps the old behaviour and
is labelled non-player-usable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from .common import (
    RACT,
    SCREEN,
    completed_run_status,
    card_feature_array,
    combat_action_arrays,
    public_combat_observation,
    public_observation,
    sim,
    skip_card_action,
)
from .heuristics import combat_policy, run_policy
from .nets import CardScorer, CombatNet
from .run_env import RunEnv

# Disjoint fixed splits; no earlier experiment used these ranges.
TRAIN_SEED_BASE = 10_000_000
VAL_SEED_BASE = 20_000_000
TEST_SEED_BASE = 30_000_000


def split_seeds(split: str, count: int) -> list[int]:
    base = {"train": TRAIN_SEED_BASE, "val": VAL_SEED_BASE,
            "test": TEST_SEED_BASE}[split]
    return [base + i for i in range(count)]


@dataclass(frozen=True)
class Strategy:
    combat: str = "greedy"      # greedy | heuristic | heuristic_oracle | network | search
    cards: str = "heuristic"    # heuristic | network
    simulations: int = 16
    resample: bool = False
    epsilon: float = 0.0
    search_select: str = "visits"  # visits | value


def _skip_features() -> np.ndarray:
    return np.asarray(sim.card_features(0, False, -1), dtype=np.float32)


def combat_action(env: RunEnv, model: CombatNet | CardScorer | None,
                  strategy: Strategy, seed: int = 0):
    bc = env.battle
    if strategy.combat == "heuristic":
        # Player-usable heuristic: hidden zones are resampled before rollout.
        return combat_policy(env, resample=True, seed_override=seed)
    if strategy.combat == "heuristic_oracle":
        return combat_policy(env)
    if strategy.combat == "greedy":
        return tuple(bc.greedy_action(0.05, seed & 0x7FFFFFFF))
    actions, feats = combat_action_arrays(bc)
    if not actions:
        return tuple(bc.greedy_action(0.0, seed & 0x7FFFFFFF))
    if model is None:
        return tuple(bc.greedy_action(0.05, seed & 0x7FFFFFFF))
    state = public_combat_observation(bc)
    with torch.no_grad():
        logits, _value = model.policy_value(
            torch.from_numpy(state)[None], torch.from_numpy(feats)[None])
        probs = torch.softmax(logits[0], dim=-1).numpy().astype(np.float64)
    if strategy.combat == "network":
        return actions[int(np.argmax(probs))]
    s_actions, visits, _values, _done = bc.search_priors(
        strategy.simulations, probs.tolist(), 1.5, 0.05,
        seed & 0x7FFFFFFF, strategy.resample)
    if not visits or sum(visits) <= 0:
        return actions[int(np.argmax(probs))]
    if strategy.search_select == "value":
        n = np.asarray(visits, dtype=np.float64)
        mean = np.asarray(_values, dtype=np.float64) / np.maximum(n, 1.0)
        mean = np.where(n > 0, mean, -1e18)
        return s_actions[int(np.argmax(mean))]
    return s_actions[int(np.argmax(visits))]


def card_reward_action(env: RunEnv, model: CardScorer | None,
                       strategy: Strategy):
    rc = env.rc
    if not any(int(t) == int(RACT.TAKE_CARD) for t, _ in rc.legal_actions()):
        return skip_card_action(rc)
    if strategy.cards != "network" or model is None:
        return run_policy(env)
    offered = rc.offered
    cand = np.vstack([card_feature_array(offered), _skip_features()])
    obs = public_observation(rc)
    with torch.no_grad():
        logits = model.scores(torch.from_numpy(obs)[None],
                              torch.from_numpy(cand)[None])[0]
    choice = int(torch.argmax(logits))
    if choice >= len(offered):
        return skip_card_action(rc)
    return (int(RACT.TAKE_CARD), choice)


def screen_action_for(env: RunEnv, model: CardScorer | None, strategy: Strategy):
    if env.screen == SCREEN.CARD_REWARD and not env.rc.card_grid_kind:
        return card_reward_action(env, model, strategy)
    # Map, shop, event, rest and treasure use the deterministic heuristics.
    return run_policy(env)


def play_run_strategy(seed: int, model: CardScorer | CombatNet | None = None,
                      strategy: Strategy = Strategy(), max_steps: int = 20000,
                      card_model: CardScorer | None = None) -> dict:
    env = RunEnv(seed)
    steps = 0
    status = "error"
    while not env.is_terminal() and steps < max_steps:
        steps += 1
        if env.screen == SCREEN.COMBAT:
            action = combat_action(env, model, strategy, seed + steps * 7919)
        else:
            action = screen_action_for(env, card_model, strategy)
        if not env.step(action):
            status = "error"
            break
    else:
        status = completed_run_status(env.rc)
    rc = env.rc
    return {
        "seed": seed,
        "status": status,
        "won": bool(rc.won) and status == "terminated",
        "act": int(rc.act) + 1,
        "floor": int(rc.floor),
        "hp": int(rc.hp),
        "max_hp": int(rc.max_hp),
        "hp_loss": int(rc.max_hp - rc.hp),
        "combats": int(rc.combats_fought),
        "elites": int(rc.elites_fought),
        "bosses": int(rc.bosses_fought),
        "deck_size": int(rc.deck_count),
        "relics": len(rc.relics),
        "steps": steps,
    }


def summarize(results: list[dict]) -> dict:
    """Win rate, act reach, HP loss and abnormal rate with Wilson 95% CIs."""
    n = len(results)
    if n == 0:
        return {"runs": 0}
    completed = [r for r in results if r["status"] == "terminated"]
    wins = np.asarray([r["won"] for r in completed], dtype=np.float64)
    abnormal = np.asarray([r["status"] != "terminated" for r in results],
                          dtype=np.float64)
    acts = np.asarray([r["act"] for r in results], dtype=np.int64)
    floors = np.asarray([r["floor"] for r in results], dtype=np.float64)
    hp_loss = np.asarray([r["hp_loss"] for r in results], dtype=np.float64)

    def wilson(p: float, total: int) -> tuple[float, float]:
        z = 1.96
        denom = 1 + z * z / total
        centre = (p + z * z / (2 * total)) / denom
        half = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
        return float(max(0.0, centre - half)), float(min(1.0, centre + half))

    win_rate = float(wins.mean()) if completed else None
    win_ci = list(wilson(win_rate, len(completed))) if completed else None
    return {
        "runs": n,
        "completed_runs": len(completed),
        "win_rate": win_rate,
        "win_ci95": win_ci,
        "act_reach": {str(a): int((acts >= a).sum()) for a in (1, 2, 3)},
        "act_mean": float(acts.mean()),
        "floor_mean": float(floors.mean()),
        "hp_loss_mean": float(hp_loss.mean()),
        "abnormal_rate": float(abnormal.mean()),
        "truncated": int(sum(r["status"] == "truncated" for r in results)),
        "errors": int(sum(r["status"] == "error" for r in results)),
    }
