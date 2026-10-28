"""Training-facing run environment for the native STS2 simulator.

One ``RunEnv`` owns one ``sts2_sim.RunContext`` (no globals), so any number of
environments can run concurrently on separate threads. Public observations only
expose information a player can see: deck contents, run resources, visible map
nodes and in-combat state (hand, piles counts, intents).
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from agent.common import (
    CARD_FEAT_DIM,
    COMBAT_OBS_DIM,
    RUN_OBS_DIM,
    RACT,
    SCREEN,
    new_run,
    run_observation,
    sim,
)

ACT = sim.ActionType


class RunEnv:
    """Gym-like wrapper around one native run."""

    def __init__(self, seed: int = 1, ascension: int = 0):
        self.seed = int(seed)
        self.ascension = int(ascension)
        self.rc = new_run(self.seed, self.ascension)

    # -- core API ---------------------------------------------------------
    def reset(self, seed: int | None = None) -> np.ndarray:
        if seed is not None:
            self.seed = int(seed)
        self.rc = new_run(self.seed, self.ascension)
        return self.observe()

    def observe(self) -> np.ndarray:
        return run_observation(self.rc)

    def observe_public(self) -> np.ndarray:
        return np.asarray(self.rc.observe_public(), dtype=np.float32)

    def observe_public_combat(self) -> np.ndarray:
        return np.asarray(self.rc.observe_public_combat(), dtype=np.float32)

    def legal_actions(self) -> list[tuple[int, int]]:
        if self.rc.screen == SCREEN.COMBAT:
            return self.rc.battle.legal_actions()
        return [(int(t), int(i)) for t, i in self.rc.legal_actions()]

    def action_mask(self) -> list[bool]:
        return [True] * len(self.legal_actions())

    def step(self, action: tuple) -> bool:
        if self.rc.screen == SCREEN.COMBAT:
            return bool(self.rc.step_combat(*action))
        return bool(self.rc.step(int(action[0]), int(action[1])))

    def is_terminal(self) -> bool:
        return bool(self.rc.is_terminal)

    def terminal_reward(self) -> float:
        return float(self.rc.terminal_reward())

    def state_hash(self) -> int:
        return int(self.rc.state_hash())

    def snapshot(self) -> bytes:
        return bytes(self.rc.snapshot())

    def restore(self, blob: bytes) -> None:
        if not self.rc.restore(blob):
            raise ValueError("snapshot restore failed")

    # -- convenience ------------------------------------------------------
    @property
    def screen(self):
        return self.rc.screen

    @property
    def battle(self):
        return self.rc.battle


def play_run(
    env: RunEnv,
    run_policy: Callable[[RunEnv], tuple],
    combat_policy: Callable[[RunEnv], tuple],
    max_steps: int = 20000,
) -> dict:
    """Drive one run to termination (or the step cap) and return metrics."""
    steps = 0
    status = "error"
    while not env.is_terminal() and steps < max_steps:
        steps += 1
        if env.screen == SCREEN.COMBAT:
            action = combat_policy(env)
        else:
            action = run_policy(env)
        if not env.step(action):
            break
    else:
        status = "terminated" if env.is_terminal() else "truncated"
    rc = env.rc
    return {
        "seed": env.seed,
        "status": status,
        "won": bool(rc.won) and status == "terminated",
        "act": int(rc.act),
        "floor": int(rc.floor),
        "hp": int(rc.hp),
        "max_hp": int(rc.max_hp),
        "gold": int(rc.gold),
        "combats": int(rc.combats_fought),
        "elites": int(rc.elites_fought),
        "bosses": int(rc.bosses_fought),
        "deck_size": int(rc.deck_count),
        "relics": len(rc.relics),
        "steps": steps,
        "terminal_reward": float(rc.terminal_reward()),
        "state_hash": int(rc.state_hash()),
    }


def play_and_log(seed: int, run_policy, combat_policy, path: str | Path) -> dict:
    """Play one run and append a compact JSONL trajectory of the public states."""
    env = RunEnv(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "error"
    with path.open("a", encoding="utf-8") as fh:
        steps = 0
        while not env.is_terminal() and steps < 20000:
            steps += 1
            action = combat_policy(env) if env.screen == SCREEN.COMBAT else run_policy(env)
            record = {
                "seed": seed,
                "step": steps,
                "screen": env.screen.name,
                "obs_version": int(sim.PUBLIC_OBS_VERSION),
                "obs": [round(float(x), 4) for x in env.observe_public()],
                "action": [int(a) for a in action],
            }
            fh.write(json.dumps(record) + "\n")
            if not env.step(action):
                break
        else:
            status = "terminated" if env.is_terminal() else "truncated"
        result = {
            "seed": seed,
            "status": status,
            "won": bool(env.rc.won) and status == "terminated",
            "act": int(env.rc.act),
            "floor": int(env.rc.floor),
            "steps": steps,
        }
        fh.write(json.dumps({"seed": seed, "result": result}) + "\n")
    return result


def run_batch(
    seeds: Iterable[int],
    run_policy,
    combat_policy,
    workers: int = 4,
) -> list[dict]:
    """Run many seeds in a thread pool (each thread owns its RunContext)."""
    seeds = list(seeds)

    def one(seed: int) -> dict:
        return play_run(RunEnv(seed), run_policy, combat_policy)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, seeds))


def action_feature_dim() -> int:
    return sim.ACTION_FEAT_DIM


def card_feature_dim() -> int:
    return CARD_FEAT_DIM


def run_obs_dim() -> int:
    return RUN_OBS_DIM


def combat_obs_dim() -> int:
    return COMBAT_OBS_DIM
