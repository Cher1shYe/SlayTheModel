"""Floor-dependent budgets and card-skip prior, opt-in for a new run."""
from __future__ import annotations

import math

from .armg_site_prior_loss import CardSkipPrior
from .hidden_mcts_controller import HiddenMctsController


def floor_number(value):
    """Use floor 1 as the baseline, including any pre-floor-1 observation."""
    if not math.isfinite(float(value)) or int(value) != value or value < 0:
        raise ValueError('floor must be a nonnegative integer')
    return max(1, int(value))


def combat_budget(floor, start=2000, increment=200, *, elite=False, boss=False,
                  elite_bonus=1000, boss_bonus=2000):
    if start < 1 or increment < 0 or elite_bonus < 0 or boss_bonus < 0 or elite and boss:
        raise ValueError('invalid MCTS budget schedule')
    return (start + increment * (floor_number(floor) - 1) +
            (boss_bonus if boss else elite_bonus if elite else 0))


def skip_elo_from_obs(obs, start=1350, increment=10):
    # armg observation index 3 is the global floor divided by 49.
    floor = int(round(float(obs[3]) * 49))
    return start + increment * (floor_number(floor) - 1)


def is_final_boss(rc):
    """True only for the last boss, including the second boss at A10."""
    if not rc.combat_is_boss or int(rc.act) != 2:
        return False
    last_row = int(rc.map_length) + int(rc.second_boss_encounter > 0)
    return int(rc.current_row) == last_row


class FloorCardSkipPrior(CardSkipPrior):
    def __init__(self, data_dir, start=1350, increment=10):
        super().__init__(data_dir, skip_elo_fn=lambda obs: skip_elo_from_obs(obs, start, increment))


class FloorMctsController(HiddenMctsController):
    def __init__(self, search_seed, activity=None, start=2000, increment=200,
                 elite_bonus=1000, boss_bonus=2000):
        super().__init__(search_seed, activity, boss_simulations=start, mode='oracle')
        self.start = start
        self.increment = increment
        self.elite_bonus = elite_bonus
        self.boss_bonus = boss_bonus
        self.current_floor = None
        self.current_elite = False
        self.current_boss = False
        self.floor_decisions = {}
        self.elite_decisions = 0
        self.elite_simulations = 0

    def prepare_combat(self, rc, _steps):
        # Reset on every decision so neither earlier bosses nor later runs
        # inherit a previous final fight's override.
        self.potion_weight = 0.0 if is_final_boss(rc) else None

    def budget_for_context(self, floor, elite, boss):
        self.current_floor = floor_number(floor)
        self.current_elite, self.current_boss = elite, boss
        return combat_budget(floor, self.start, self.increment, elite=elite, boss=boss,
                             elite_bonus=self.elite_bonus, boss_bonus=self.boss_bonus)

    def plan(self, battle, seed, combat, simulations, epsilon, is_boss):
        if self.current_floor is None or bool(is_boss) != self.current_boss or simulations != combat_budget(
            self.current_floor, self.start, self.increment, elite=self.current_elite, boss=self.current_boss,
            elite_bonus=self.elite_bonus, boss_bonus=self.boss_bonus):
            raise ValueError('missing or inconsistent floor-dependent budget')
        self.boss_simulations = simulations
        result = super().plan(battle, seed, combat, simulations, epsilon, is_boss)
        if result[1]:
            key = (self.current_floor, self.current_elite, self.current_boss)
            self.floor_decisions[key] = self.floor_decisions.get(key, 0) + 1
            if self.current_elite:
                self.elite_decisions += 1
                self.elite_simulations += int(result[1])
        return result
