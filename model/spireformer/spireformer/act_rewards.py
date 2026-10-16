"""Pure, versioned rewards from verified whole-run battle and terminal facts.

The caller supplies native boundary observations and verifies episode continuity.
This module neither infers missing outcomes nor reads game state. Rewards are
unclipped, have discount 1, and are separate from observation/policy features.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Sequence
from typing import Any


ACT_RTG_SCHEME = "whole-run-act-v1"


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _boundary(combat_id: str, act: int, hp: float, max_hp: float) -> None:
    if not isinstance(combat_id, str) or not combat_id.strip():
        raise ValueError("combat_id must be a nonempty string")
    if type(act) is not int or act not in (1, 2, 3):
        raise ValueError("act must be 1, 2, or 3")
    hp_value = _number(hp, "hp")
    max_value = _number(max_hp, "max_hp")
    if max_value <= 0 or not 0 <= hp_value <= max_value:
        raise ValueError("require max_hp > 0 and 0 <= hp <= max_hp")


def _count(value: int | None, name: str, *, required: bool) -> None:
    if value is None and not required:
        return
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    _number(value, name)


@dataclass(frozen=True)
class BattleStart:
    """State immediately before a battle, with acts numbered from one.

    For bosses, ``upgraded_cards`` counts currently upgraded permanent deck
    cards once each, regardless of upgrade level. ``relics`` counts all relics
    currently held, including the starting relic. Both are full current counts.
    """

    combat_id: str
    act: int
    is_boss: bool
    hp: float
    max_hp: float
    upgraded_cards: int | None = None
    relics: int | None = None

    def __post_init__(self) -> None:
        _boundary(self.combat_id, self.act, self.hp, self.max_hp)
        if type(self.is_boss) is not bool:
            raise ValueError("is_boss must be a boolean")
        _count(self.upgraded_cards, "upgraded_cards", required=self.is_boss)
        _count(self.relics, "relics", required=self.is_boss)


@dataclass(frozen=True)
class BattleEnd:
    """Verified battle end, before subsequent reward/event/healing actions.

    ``act_completed`` must reflect an actual act completion. A first boss in a
    double-boss act does not complete the act merely because it was defeated.
    The HP normalization uses this boundary's ``max_hp``, not the start value.
    """

    combat_id: str
    act: int
    hp: float
    max_hp: float
    won: bool
    act_completed: bool = False

    def __post_init__(self) -> None:
        _boundary(self.combat_id, self.act, self.hp, self.max_hp)
        if type(self.won) is not bool or type(self.act_completed) is not bool:
            raise ValueError("won and act_completed must be booleans")


class EpisodeRewardAccumulator:
    """Validate a run's event order and emit additive scalar components.

    Sum each returned dictionary's values for that event's reward. Preparation
    is emitted by ``begin_battle`` once per act, immediately before its first
    boss. Nonboss HP and completed-act rewards are emitted by ``end_battle``.
    Only ``finish`` emits the defeat penalty, including deaths outside combat.
    A battle death must still have a matching end before the episode finishes.
    """

    def __init__(self) -> None:
        self._active: BattleStart | None = None
        self._combat_ids: set[str] = set()
        self._prepared_acts: set[int] = set()
        self._completed_acts: set[int] = set()
        self._defeated = False
        self._outcome: str | None = None
        self._total_reward = 0.0

    @property
    def total_reward(self) -> float:
        return self._total_reward

    @property
    def completed_acts(self) -> frozenset[int]:
        return frozenset(self._completed_acts)

    @property
    def outcome(self) -> str | None:
        return self._outcome

    def _require_open(self) -> None:
        if self._outcome is not None:
            raise ValueError("episode already finished")

    def _record(self, components: dict[str, float]) -> dict[str, float]:
        for name, value in components.items():
            _number(value, name)
        total = self._total_reward + sum(components.values())
        _number(total, "total_reward")
        self._total_reward = total
        return components

    def begin_battle(self, start: BattleStart) -> dict[str, float]:
        self._require_open()
        if not isinstance(start, BattleStart):
            raise ValueError("start must be a BattleStart")
        if self._active is not None:
            raise ValueError("a battle is already active")
        if self._defeated:
            raise ValueError("cannot start a battle after defeat")
        if start.combat_id in self._combat_ids:
            raise ValueError("duplicate combat_id")
        if start.act != len(self._completed_acts) + 1:
            raise ValueError("battle act does not follow completed act milestones")

        components: dict[str, float] = {}
        if start.is_boss and start.act not in self._prepared_acts:
            # BattleStart validation guarantees both counts are present.
            assert start.upgraded_cards is not None and start.relics is not None
            components["upgraded_cards"] = start.upgraded_cards * 0.05
            components["relics"] = start.relics * 0.1
            if start.act == 3:
                components["act3_entry_hp"] = start.hp / start.max_hp
        result = self._record(components)
        self._active = start
        self._combat_ids.add(start.combat_id)
        if start.is_boss:
            self._prepared_acts.add(start.act)
        return result

    def end_battle(self, end: BattleEnd) -> dict[str, float]:
        self._require_open()
        if not isinstance(end, BattleEnd):
            raise ValueError("end must be a BattleEnd")
        start = self._active
        if start is None:
            raise ValueError("battle end has no matching start")
        if end.combat_id != start.combat_id or end.act != start.act:
            raise ValueError("battle end does not match active combat_id and act")
        if end.act_completed and (not start.is_boss or not end.won):
            raise ValueError("act completion requires a won boss battle")
        if end.act_completed and end.act in self._completed_acts:
            raise ValueError("act milestone already awarded")

        components: dict[str, float] = {}
        if not start.is_boss:
            components["combat_hp"] = (end.hp - start.hp) / end.max_hp
        if end.act_completed:
            components["act_completion"] = float(end.act)
        result = self._record(components)
        self._active = None
        if end.act_completed:
            self._completed_acts.add(end.act)
        if not end.won:
            self._defeated = True
        return result

    def finish(self, outcome: str) -> dict[str, float]:
        """Finish with a caller-verified native outcome; never infer a defeat."""

        self._require_open()
        if outcome not in ("win", "defeat"):
            raise ValueError("finish requires a verified terminal win or defeat")
        if self._active is not None:
            raise ValueError("cannot finish with an unclosed battle")
        if outcome == "win" and (
            self._defeated or self._completed_acts != {1, 2, 3}
        ):
            raise ValueError("win requires all three act milestones and no battle defeat")
        result = self._record({"defeat": -10.0} if outcome == "defeat" else {})
        self._outcome = outcome
        return result


def undiscounted_returns(rewards: Sequence[float]) -> tuple[float, ...]:
    """Realized return before each step, with gamma=1 and no clipping."""

    values = [_number(reward, "reward") for reward in rewards]
    total = 0.0
    for index in range(len(values) - 1, -1, -1):
        total += values[index]
        _number(total, "return_to_go")
        values[index] = total
    return tuple(values)


def act_reward_parameters() -> dict[str, Any]:
    """Serialization-ready semantics for dataset manifests and audit reports."""

    return {
        "nonboss_combat_hp": "(post_hp - pre_hp) / post_max_hp",
        "boss_combat_hp": 0.0,
        "act_completion": {"1": 1.0, "2": 2.0, "3": 3.0},
        "before_boss_upgraded_card": 0.05,
        "before_boss_relic": 0.1,
        "preparation_counting": "full_current_counts_once_per_act",
        "upgraded_card_counting": "each_upgraded_permanent_deck_card_once",
        "relic_counting": "all_currently_held_including_starting_relic",
        "act3_entry_hp": "pre_hp / pre_max_hp_once_before_first_boss",
        "terminal_win": 0.0,
        "terminal_defeat": -10.0,
        "discount": 1.0,
        "clipping": None,
        "incomplete_outcome": "reject",
    }


__all__ = [
    "ACT_RTG_SCHEME", "BattleStart", "BattleEnd", "EpisodeRewardAccumulator",
    "undiscounted_returns", "act_reward_parameters",
]
