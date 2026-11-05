"""Pure MCTS battle controller for oracle or sampled hidden state.

Construct one controller per episode.  It deliberately ignores the game seed
and never caches a line from a sampled future. The same controller can be used
while collecting prior demonstrations and while training ArmG with REINFORCE.
"""
from __future__ import annotations

import math


class HiddenMctsController:
    def __init__(self, search_seed: int, activity=None, boss_simulations: int = 10000,
                 mode: str = "hidden"):
        if not 0 <= int(search_seed) <= 0xFFFFFFFF:
            raise ValueError("search_seed must be a 32-bit unsigned integer")
        if int(boss_simulations) < 1:
            raise ValueError("boss_simulations must be positive")
        if mode not in ("hidden", "oracle"):
            raise ValueError("mode must be hidden or oracle")
        self.search_seed = int(search_seed)
        self.boss_simulations = int(boss_simulations)
        self.mode = mode
        self.decisions = 0
        self.boss_decisions = 0
        self.normal_decisions = 0
        self.boss_simulations_completed = 0
        self.normal_simulations = 0
        self.simulations = 0
        self.activity = activity
        # None preserves the native search default and works with older
        # extensions; specialized controllers may set a per-search override.
        self.potion_weight = None

    def plan(self, battle, _game_derived_seed: int, combat: str, simulations: int,
             epsilon: float, is_boss: bool):
        expected = "mcts-resampled" if self.mode == "hidden" else "mcts-oracle"
        if combat != expected or simulations < 1:
            raise ValueError("MCTS combat mode must match controller and budget must be positive")
        legal = [tuple(int(x) for x in action) for action in battle.legal_actions()]
        if not legal:
            raise RuntimeError("no legal battle action")
        if len(legal) == 1:
            return legal, 0
        # Per-episode seed is supplied independently of the environment seed.
        seed = (self.search_seed + 7919 * self.decisions) & 0xFFFFFFFF
        self.decisions += 1
        if is_boss:
            self.boss_decisions += 1
        else:
            self.normal_decisions += 1
        if self.activity is not None:
            self.activity(self)
        budget = self.boss_simulations if is_boss else simulations
        args = (budget, 3.0 * math.sqrt(2.0), seed,
                self.mode == "hidden", False, epsilon)
        if self.potion_weight is None:
            path, done, _ = battle.mcts(*args)
        else:
            path, done, _ = battle.mcts(*args, potion_weight=self.potion_weight)
        path = [tuple(int(x) for x in action) for action in path]
        if not path or path[0] not in legal or int(done) != budget:
            raise RuntimeError("pure MCTS returned an illegal action or incomplete budget")
        self.simulations += int(done)
        if is_boss:
            self.boss_simulations_completed += int(done)
        else:
            self.normal_simulations += int(done)
        return path[:1], int(done)
