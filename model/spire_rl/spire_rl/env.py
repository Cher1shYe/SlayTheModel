"""Macro environment: one transition = one real out-of-combat choice.

Between two choices the environment advances on its own:
  * combats are played to the end by the fixed C++ hidden-state MCTS;
  * screens with exactly one legal action are executed (no choice exists);
so every stored transition is a decision the policy actually made.

Menu loops: a multi-select card grid can be toggled forever (run main-a0-s1
spent 2,900+ decisions in Sea Glass three times). After ``max_grid_steps``
consecutive decisions inside one open grid the episode ends as a TRUNCATED
``menu_loop`` with its last state kept for bootstrap. Nothing is chosen,
confirmed or removed on the policy's behalf.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

import numpy as np

from .config import CombatConfig, RewardConfig
from .sim import sim

SCREEN = sim.RunScreen


class Outcome(enum.IntEnum):
    RUNNING = 0
    WIN = 1          # real run victory (terminal)
    DEATH = 2        # normal game loss (terminal)
    TRUNCATED = 3    # macro step cap or simulator stalemate cutoff (bootstrap)
    FAILURE = 4      # engineering failure: excluded from learning, reported


@dataclass
class Observation:
    """Arrays from RunContext.macro_observation() for one decision point."""
    kind: np.ndarray        # [N] int32
    id: np.ndarray          # [N] int32
    num: np.ndarray         # [N, F] float32
    edges: np.ndarray       # [E, 2] int32
    cand_type: np.ndarray   # [C] int32
    cand_index: np.ndarray  # [C] int32 (execution descriptor)
    cand_target: np.ndarray
    cand_target2: np.ndarray
    cand_num: np.ndarray    # [C, K] float32
    phase: int

    @staticmethod
    def capture(rc) -> "Observation":
        o = rc.macro_observation()
        return Observation(o["kind"], o["id"], o["num"], o["edges"], o["cand_type"], o["cand_index"],
                           o["cand_target"], o["cand_target2"], o["cand_num"], int(o["phase"]))

    @property
    def num_candidates(self) -> int:
        return int(self.cand_type.shape[0])


@dataclass
class StepResult:
    reward_raw: float
    components: np.ndarray            # [floors, act entries, win] counted in this step
    outcome: Outcome
    next_obs: Observation | None      # next decision (None when the episode ended)
    final_obs: Observation | None = None   # last state, for truncation bootstrap
    failure_reason: str = ""


@dataclass
class CombatEvent:
    after_decision: int   # index of the last decision taken before this combat
    survived: bool
    hp_ratio: float       # HP / max HP after combat, before rewards and act healing
    act: int


@dataclass
class EpisodeLog:
    combats: list[CombatEvent] = field(default_factory=list)
    act_at_decision: list[int] = field(default_factory=list)
    max_act: int = 0
    forced_steps: int = 0
    menu_loops: int = 0
    mcts_decisions: int = 0
    mcts_simulations: int = 0
    combat_seconds: float = 0.0


class MacroEnv:
    def __init__(self, combat: CombatConfig, reward: RewardConfig, ascension: int = 0,
                 max_macro_steps: int = 600, max_grid_steps: int = 64):
        self.combat = combat
        self.reward = reward
        self.ascension = ascension
        self.max_macro_steps = max_macro_steps
        self.max_grid_steps = max_grid_steps
        self.rc = None

    # -- episode lifecycle -------------------------------------------------
    def reset(self, game_seed: int, search_seed: int) -> StepResult:
        """Start a run and advance to its first real decision."""
        self.rc = sim.RunContext()
        self.rc.init(int(game_seed), int(self.ascension))
        self.game_seed = int(game_seed)
        self.search_seed = int(search_seed) & 0xFFFFFFFF
        self.decisions = 0
        self.macro_steps = 0
        self.combat_index = 0
        self.mcts_decision_counter = 0
        self.log = EpisodeLog()
        self.credited_floor = 0
        self.max_act = 0
        self.grid_phase = -1      # phase of the open grid being counted (-1 = none)
        self.grid_steps = 0       # consecutive decisions inside it
        result = self._advance()
        # Progress made before the first decision is not credited later.
        self.credited_floor = self._completed_floor()
        self.max_act = int(self.rc.act)
        return StepResult(0.0, np.zeros(3, np.float32), result[0], result[1], result[2], result[3])

    def step(self, candidate: int, obs: Observation, alpha: float) -> StepResult:
        """Execute candidate ``candidate`` of ``obs`` and advance to the next decision."""
        if not 0 <= candidate < obs.num_candidates:
            raise IndexError("candidate outside the current request")
        self.log.act_at_decision.append(int(self.rc.act))
        self.decisions += 1
        self.macro_steps += 1
        if obs.phase % 2:                                   # a card grid is open
            self.grid_steps = self.grid_steps + 1 if obs.phase == self.grid_phase else 1
            self.grid_phase = obs.phase
        else:
            self.grid_phase, self.grid_steps = -1, 0
        ok = self.rc.step(int(obs.cand_type[candidate]), int(obs.cand_index[candidate]))
        if not ok:
            return StepResult(0.0, np.zeros(3, np.float32), Outcome.FAILURE, None, None,
                              "legal candidate rejected by the simulator")
        outcome, next_obs, final_obs, reason = self._advance()
        if (outcome == Outcome.RUNNING and next_obs.phase == self.grid_phase
                and self.grid_steps >= self.max_grid_steps):
            self.log.menu_loops += 1
            outcome, final_obs, next_obs, reason = Outcome.TRUNCATED, next_obs, None, "menu_loop"
        components = self._collect_progress(outcome)
        return StepResult(raw_reward(components, alpha, self.reward), components, outcome, next_obs,
                          final_obs, reason)

    def fork(self, search_seed: int) -> "MacroEnv":
        """Independent copy at the current decision (run state cloned, fresh log).

        ``search_seed`` replaces the combat-search seed base; branches of one paired
        fork share it, so their fights use the same search random numbers.
        """
        env = MacroEnv(self.combat, self.reward, self.ascension, self.max_macro_steps, self.max_grid_steps)
        env.rc = self.rc.clone()
        env.game_seed = self.game_seed
        env.search_seed = int(search_seed) & 0xFFFFFFFF
        for name in ("decisions", "macro_steps", "combat_index", "mcts_decision_counter", "credited_floor",
                     "max_act", "grid_phase", "grid_steps"):
            setattr(env, name, getattr(self, name))
        env.log = EpisodeLog(max_act=self.max_act)
        return env

    # -- internals ---------------------------------------------------------
    def _completed_floor(self) -> int:
        rc = self.rc
        if rc.won or rc.screen == SCREEN.MAP:
            return int(rc.floor)
        return max(0, int(rc.floor) - 1)

    def _collect_progress(self, outcome: Outcome) -> np.ndarray:
        rc = self.rc
        floors = acts = 0
        if outcome != Outcome.FAILURE:
            completed = self._completed_floor()
            floors = max(0, completed - self.credited_floor)
            self.credited_floor = max(self.credited_floor, completed)
            act = int(rc.act)
            acts = max(0, act - self.max_act)
            self.max_act = max(self.max_act, act)
            self.log.max_act = self.max_act
        win = 1 if outcome == Outcome.WIN else 0
        return np.array([floors, acts, win], np.float32)

    def _advance(self):
        """Run combats and forced steps until a real decision or the end."""
        rc = self.rc
        c = self.combat
        while True:
            if rc.is_terminal:
                if rc.won:
                    return Outcome.WIN, None, None, ""
                if rc.truncated:
                    return Outcome.TRUNCATED, None, Observation.capture(rc), "simulator cutoff"
                return Outcome.DEATH, None, None, ""
            if self.macro_steps >= self.max_macro_steps:
                return Outcome.TRUNCATED, None, Observation.capture(rc), "macro step cap"
            if rc.screen == SCREEN.COMBAT:
                import time
                act = int(rc.act)
                started = time.perf_counter()
                seed = (self.search_seed + 104729 * self.combat_index) & 0xFFFFFFFF
                decisions, forced, sims, ok = rc.play_combat_mcts(
                    c.normal_simulations, c.boss_simulations, c=c.exploration, seed=seed,
                    decision_start=self.mcts_decision_counter, epsilon=c.rollout_epsilon,
                    potion_weight=c.potion_weight)
                self.combat_index += 1
                self.mcts_decision_counter += decisions
                self.log.mcts_decisions += decisions
                self.log.mcts_simulations += sims
                self.log.combat_seconds += time.perf_counter() - started
                if not ok:
                    return Outcome.FAILURE, None, None, "combat driver failed"
                died = rc.is_terminal and not rc.won
                hp_ratio = 0.0 if died else (rc.hp / rc.max_hp if rc.max_hp > 0 else 0.0)
                self.log.combats.append(CombatEvent(self.decisions - 1, not died, float(hp_ratio), act))
                continue
            obs = Observation.capture(rc)
            if obs.num_candidates == 0:
                return Outcome.FAILURE, None, None, "no legal candidate on a non-terminal screen"
            if obs.num_candidates == 1:
                self.macro_steps += 1
                self.log.forced_steps += 1
                if not rc.step(int(obs.cand_type[0]), int(obs.cand_index[0])):
                    return Outcome.FAILURE, None, None, "forced action rejected"
                continue
            return Outcome.RUNNING, obs, None, ""


def raw_reward(components: np.ndarray, alpha: float, r: RewardConfig) -> float:
    """r_raw = win * 5 + alpha * (0.05 * new floors + 0.5 * new act entries).

    Resources, card picks, upgrades and menu actions earn nothing directly.
    """
    floors, acts, win = (float(x) for x in components)
    return r.win * win + alpha * (r.floor * floors + r.act_entry * acts)


def aux_labels(log: EpisodeLog, num_decisions: int, outcome: Outcome) -> np.ndarray:
    """Per-decision auxiliary targets [survive, hp_ratio, act_done] and masks.

    Returns float32 [T, 6]: three labels followed by three validity masks.
    A label is masked when the episode ended without observing it
    (truncation or engineering failure), never filled in as a loss.
    """
    out = np.zeros((num_decisions, 6), np.float32)
    observed_end = outcome in (Outcome.WIN, Outcome.DEATH)
    combats = log.combats
    final_act = log.max_act
    for t in range(num_decisions):
        nxt = next((ev for ev in combats if ev.after_decision >= t), None)
        if nxt is not None:
            out[t, 0] = 1.0 if nxt.survived else 0.0
            out[t, 1] = nxt.hp_ratio
            out[t, 3] = out[t, 4] = 1.0
        elif outcome == Outcome.DEATH:
            # Died outside combat before the next fight: survival/HP are 0.
            out[t, 3] = out[t, 4] = 1.0
        act = log.act_at_decision[t] if t < len(log.act_at_decision) else final_act
        if final_act > act or outcome == Outcome.WIN:
            out[t, 2], out[t, 5] = 1.0, 1.0
        elif observed_end:
            out[t, 5] = 1.0  # died in this act
    return out
