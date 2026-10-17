"""Strict world execution boundary. This is not an InformationState/planner API."""
from dataclasses import asdict, dataclass
from numbers import Integral
from pathlib import Path
import uuid

import numpy as np

from .actions import action_size, action_version, public_mask
from .decks import card_token
from .content import G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
from .content import BOSS_CONTENT, EXPANSION_CONTENT
from .config import ACTION_VERSION, REWARD_VERSION, EpisodeLimits, atomic_json
from .scenarios import make_scenario
from .rewards import terminal_reward, validate_reward
from sts2_env.core.constants import ACTION_SPACE_SIZE, MAX_HAND_SIZE, MAX_ENEMIES, POTION_ACTION_START
from sts2_env.gym_env.action_space import get_action_mask, action_to_card_and_target


class CombatInterfaceError(RuntimeError):
    """A failed world/adapter interaction, never a game loss."""


@dataclass(frozen=True)
class Transition:
    reward: float
    done: bool
    termination_reason: str | None
    final_hp: int
    turns: int
    decisions: int
    initial_hp: int = 80
    enemy_final_hp: int = 0
    enemy_max_hp: int = 40
    enemy_initial_hp: int | None = None
    enemy_roster: tuple = ()
    player_max_hp: int = 80
    incoming_risk: float = 0.0


class CombatAdapter:
    def __init__(self, recipe, limits=None, error_dir="output/az_errors", reward_version=REWARD_VERSION):
        self.reward_version = validate_reward(reward_version)
        self.recipe = recipe
        self.limits = limits or EpisodeLimits()
        self.error_dir = Path(error_dir)
        self.actions = []
        self.failed = False
        self.world = make_scenario(recipe)
        self.enemy_initial_hp = self.world.enemies[0].current_hp
        self.initial_roster = tuple((e.monster_id, e.current_hp, e.max_hp) for e in self.world.enemies)
        self.enemy_slots = tuple(self.world.enemies)
        self.initial_hp_roster = tuple(max(0, e.current_hp) for e in self.world.enemies)
        if recipe.content_manifest_version in (BOSS_CONTENT, EXPANSION_CONTENT):
            from .rewards import V6, V7
            if self.reward_version not in (V6, V7):
                raise ValueError("Boss content requires reward V6")
        if recipe.content_manifest_version == MULTI_CONTENT:
            from .rewards import V4
            if self.reward_version != V4:
                raise ValueError("Multi content requires fixed-roster reward v4")
            self.enemy_initial_hp = sum(e.current_hp for e in self.world.enemies)
        elif recipe.content_manifest_version == SUMMON_CONTENT:
            from .rewards import V5
            if self.reward_version != V5:
                raise ValueError("Summon content requires primary-roster reward v5")
            self.enemy_initial_hp = sum(self.initial_hp_roster)

    def outcome(self):
        world = self.world
        reason = None
        if world.is_over:
            reason = "win" if world.player_won else "death"
        elif len(self.actions) >= self.limits.max_decisions or world.turn_count > self.limits.max_turns:
            # Turns 1..max_turns are playable; stop before making a decision in the next turn.
            reason = "time_limit"
        enemy = world.enemies[0]
        roster = ()
        enemy_hp, enemy_max = max(0, enemy.current_hp), enemy.max_hp
        if self.recipe.content_manifest_version in (BOSS_CONTENT, EXPANSION_CONTENT):
            from .boss import capture_reward, rows_summary
            if tuple(world.enemies)[:len(self.enemy_slots)] != self.enemy_slots:
                raise CombatInterfaceError("Boss roster identity changed")
            roster = capture_reward(world, self.initial_hp_roster)
            self.enemy_initial_hp, enemy_hp, enemy_max = rows_summary(roster)
        elif self.recipe.content_manifest_version == SUMMON_CONTENT:
            from .summon import capture_ledger, ledger_rows, primary_summary
            if (len(world.enemies) < len(self.enemy_slots) or len(world.enemies) > len(self.enemy_slots) + 1
                    or tuple(world.enemies)[:len(self.enemy_slots)] != self.enemy_slots):
                raise CombatInterfaceError("Summon roster was removed, reordered or replaced")
            ledger = capture_ledger(world, self.initial_hp_roster)
            roster = ledger_rows(ledger)
            # Scalars summarize primary obligations only; minion HP never enters.
            self.enemy_initial_hp, enemy_hp, enemy_max = primary_summary(ledger)
        elif self.recipe.content_manifest_version == MULTI_CONTENT:
            from .multi import capture_health, validate_health
            if tuple(world.enemies) != self.enemy_slots:
                raise CombatInterfaceError("Fixed enemy slots changed")
            roster = capture_health(world, self.initial_roster)
            _, enemy_hp, enemy_max = validate_health(roster)
        from .rewards import V7
        from .risk_reward import world_risk
        risk = world_risk(world, self.recipe.content_manifest_version) if self.reward_version == V7 else 0.0
        reward = terminal_reward(reason, world.player.current_hp, self.recipe.player_hp,
                                 enemy_hp, enemy_max, self.reward_version,
                                 enemy_initial_hp=self.enemy_initial_hp, enemy_roster=roster,
                                 player_max_hp=world.player.max_hp, incoming_risk=risk)
        return Transition(reward,
                          reason is not None, reason, max(0, world.player.current_hp),
                          min(world.turn_count, self.limits.max_turns), len(self.actions), self.recipe.player_hp,
                          enemy_hp, enemy_max, self.enemy_initial_hp, roster, world.player.max_hp, risk)

    def legal_mask(self):
        if self.failed:
            raise CombatInterfaceError("Adapter failed; replay the recorded recipe after fixing the error")
        if self.outcome().done:
            return np.zeros(action_size(self.recipe.content_manifest_version), dtype=np.int8)
        if self.world.pending_choice is not None and self.recipe.content_manifest_version not in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT):
            raise CombatInterfaceError("Choice phase is not supported by the M0 content contract")
        if len(self.world.hand) > MAX_HAND_SIZE or len(self.world.enemies) > MAX_ENEMIES:
            raise CombatInterfaceError("Action schema capacity exceeded")
        mask = public_mask(self.world, self.recipe.content_manifest_version)
        if mask.shape != (action_size(self.recipe.content_manifest_version),) or not mask.any() or (self.world.pending_choice is None and mask[POTION_ACTION_START:].any()):
            raise CombatInterfaceError("Invalid mask for the no-potion action contract")
        return mask.copy()

    def step(self, action):
        try:
            if self.failed or self.outcome().done:
                raise CombatInterfaceError("Cannot step a finished or failed episode")
            mask = self.legal_mask()
            if isinstance(action, bool) or not isinstance(action, Integral) or not 0 <= action < len(mask) or not mask[action]:
                raise CombatInterfaceError(f"Illegal action: {action!r}")
            action = int(action)
            if self.world.pending_choice is not None:
                from .choice_sets import resolve_choice
                if not resolve_choice(self.world, action, self.recipe.content_manifest_version):
                    raise CombatInterfaceError("Engine rejected choice")
            elif action == 0:
                self.world.end_player_turn()
            else:
                hand, target = action_to_card_and_target(action)
                if not self.world.play_card(hand, target):
                    raise CombatInterfaceError(f"Engine rejected masked-legal action {action}")
            self.actions.append(action)
            result = self.outcome()
            if not result.done:
                self.legal_mask()
            return result
        except Exception as exc:
            self.failed = True
            atomic_json(self.error_dir / f"{uuid.uuid4().hex}.json", {
                "scenario": self.recipe.to_dict(), "actions": self.actions,
                "attempted_action": repr(action), "error": repr(exc), "limits": asdict(self.limits),
                "action_schema_version": action_version(self.recipe.content_manifest_version), "reward_version": self.reward_version,
            })
            raise

    def trace(self):
        return {"scenario": self.recipe.to_dict(), "actions": list(self.actions),
                "limits": asdict(self.limits), "outcome": asdict(self.outcome()),
                "failed": self.failed, "action_schema_version": action_version(self.recipe.content_manifest_version),
                "reward_version": self.reward_version}


def replay(recipe, actions, limits=None, error_dir="output/az_errors"):
    env = CombatAdapter(recipe, limits, error_dir)
    for action in actions:
        env.step(action)
    return env


class ObservableCombatAdapter(CombatAdapter):
    """Own the real world and explicit public memory; hand only .information to planners."""
    def __init__(self, recipe, limits=None, error_dir="output/az_errors", reward_version=REWARD_VERSION):
        from .information import PublicHistory, observe
        super().__init__(recipe, limits, error_dir, reward_version)
        from .content import DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
        from .decks import deck_tokens
        self.public_initial = ((deck_tokens(recipe.deck), tuple(e[1] for e in self.initial_roster)
                               if recipe.content_manifest_version in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT) else self.enemy_initial_hp)
                               if recipe.content_manifest_version in (DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT) else ((), None))
        self._information = observe(self.world, PublicHistory(), self.limits, recipe.player_hp, self.reward_version,
                                    recipe.content_manifest_version, *self.public_initial)

    @property
    def information(self):
        if self.failed:
            raise CombatInterfaceError("Failed episode has no actionable information state")
        return self._information

    def step(self, action):
        from .information import observe
        before = self._information
        result = super().step(action)
        try:
            if self.recipe.content_manifest_version in (BOSS_CONTENT, EXPANSION_CONTENT):
                from .boss import check_transition
                check_transition(before, self.world, self.enemy_slots)
                self.enemy_slots = tuple(self.world.enemies)
            elif self.recipe.content_manifest_version == MULTI_CONTENT:
                from .multi import check_transition
                check_transition(before, self.world, self.enemy_slots)
            elif self.recipe.content_manifest_version == SUMMON_CONTENT:
                from .summon import check_transition
                check_transition(before, self.world, self.enemy_slots)
                self.enemy_slots = tuple(self.world.enemies)
            history = before.history.after_action(before, int(action), combat_ended=self.world.is_over, after_hand=tuple(card_token(c) for c in self.world.hand))
            if self.recipe.content_manifest_version in (BOSS_CONTENT, EXPANSION_CONTENT):
                from .boss import finish_history
                history = finish_history(before, self.world, history, action)
            self._information = observe(self.world, history, self.limits, self.recipe.player_hp, self.reward_version,
                                        self.recipe.content_manifest_version, *self.public_initial)
            return result
        except Exception as exc:
            self.failed = True
            atomic_json(self.error_dir / f"{uuid.uuid4().hex}.json",
                        {"trace": self.trace(), "error": repr(exc), "stage": "observer"})
            raise
