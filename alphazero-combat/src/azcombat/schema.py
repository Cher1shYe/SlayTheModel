"""Versioned policy-facing observation and hierarchical action contracts.

The observation parser is deliberately allowlist-only. Feed it the combat-only
projection, never a simulator snapshot or replay archive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ObservationError(ValueError):
    """Input violates the policy ABI or contains data outside its trust boundary."""


@dataclass(frozen=True)
class CombatObservation:
    schema_version: int
    round_number: int
    current_side: str
    players: tuple[Mapping[str, Any], ...]
    creatures: tuple[Mapping[str, Any], ...]


_TOP_LEVEL = {"schemaVersion", "roundNumber", "currentSide", "players", "creatures"}
_PLAYER_FIELDS = {
    "playerId", "characterId", "energy", "stars", "turnNumber", "phase",
    "piles", "relics", "potions", "orbs",
}
_PILE_FIELDS = {"pileType", "cards"}
_CARD_FIELDS = {
    "combatCardIndex", "modelId", "energyCost", "afflictionId", "afflictionCount", "keywords",
}
_CREATURE_FIELDS = {"combatId", "playerId", "monsterId", "currentHp", "maxHp", "block", "powers"}
_POWER_FIELDS = {"modelId", "amount"}
_RELIC_FIELDS = {"modelId"}
_POTION_FIELDS = {"slotIndex", "modelId"}
_ORB_FIELDS = {"modelId", "passive", "evoke"}


def _object(value: Any, allowed: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservationError(f"{label} must be an object")
    extra = set(value) - allowed
    missing = allowed.intersection({"schemaVersion", "roundNumber", "currentSide", "players", "creatures"}) - set(value) if label == "observation" else set()
    if extra:
        raise ObservationError(f"{label} contains forbidden fields: {', '.join(sorted(extra))}")
    if missing:
        raise ObservationError(f"{label} missing required fields: {', '.join(sorted(missing))}")
    return value


def _sequence(value: Any, label: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise ObservationError(f"{label} must be an array")
    return tuple(value)


def _project_entity_list(raw: Any, fields: set[str], label: str) -> tuple[Mapping[str, Any], ...]:
    result = []
    for index, item in enumerate(_sequence(raw, label)):
        obj = _object(item, fields, f"{label}[{index}]")
        # Validate nested model entities while copying only their documented fields.
        if label == "players":
            copied = dict(obj)
            copied["piles"] = tuple(
                dict(_object(pile, _PILE_FIELDS, f"players[{index}].piles"))
                for pile in _sequence(obj["piles"], "piles")
            )
            for pile in copied["piles"]:
                pile["cards"] = tuple(
                    dict(_object(card, _CARD_FIELDS, "card"))
                    for card in _sequence(pile["cards"], "cards")
                )
            copied["relics"] = tuple(dict(_object(x, _RELIC_FIELDS, "relic")) for x in _sequence(obj["relics"], "relics"))
            copied["potions"] = tuple(dict(_object(x, _POTION_FIELDS, "potion")) for x in _sequence(obj["potions"], "potions"))
            copied["orbs"] = tuple(dict(_object(x, _ORB_FIELDS, "orb")) for x in _sequence(obj["orbs"], "orbs"))
            result.append(copied)
        elif label == "creatures":
            copied = dict(obj)
            copied["powers"] = tuple(dict(_object(x, _POWER_FIELDS, "power")) for x in _sequence(obj["powers"], "powers"))
            result.append(copied)
    return tuple(result)


def validate_observation(raw: Mapping[str, Any]) -> CombatObservation:
    """Validate and project the strict combat observation allowlist."""
    obj = _object(raw, _TOP_LEVEL, "observation")
    if obj["schemaVersion"] != 1:
        raise ObservationError("unsupported combat observation schemaVersion")
    if not isinstance(obj["roundNumber"], int) or obj["roundNumber"] < 0:
        raise ObservationError("roundNumber must be a non-negative integer")
    if obj["currentSide"] not in {"Player", "Enemy", "Unknown", 0, 1, 2}:
        raise ObservationError("currentSide is not a known combat side")
    players = _project_entity_list(obj["players"], _PLAYER_FIELDS, "players")
    creatures = _project_entity_list(obj["creatures"], _CREATURE_FIELDS, "creatures")
    player_ids = [p["playerId"] for p in players]
    creature_ids = [c["combatId"] for c in creatures]
    if len(player_ids) != len(set(player_ids)) or len(creature_ids) != len(set(creature_ids)):
        raise ObservationError("player and creature identifiers must be unique")
    return CombatObservation(1, obj["roundNumber"], str(obj["currentSide"]), players, creatures)


@dataclass(frozen=True)
class ActionNode:
    """A node in the unified action/choice tree; children encode nested choices."""

    kind: str
    action_id: str
    payload: Mapping[str, Any] | None = None
    children: tuple["ActionNode", ...] = ()
    terminal: bool = False

    def validate(self) -> None:
        allowed = {"PlayCard", "UsePotion", "EndTurn", "Target", "Option", "CardSubset", "CardOrder", "NestedChoice"}
        if self.kind not in allowed:
            raise ValueError(f"unsupported action node kind: {self.kind}")
        if not self.action_id:
            raise ValueError("action_id must be nonempty")
        if self.kind == "EndTurn" and (self.children or not self.terminal):
            raise ValueError("EndTurn must be a terminal action")
        if self.terminal and self.children:
            raise ValueError("terminal action cannot have child choices")
        for child in self.children:
            child.validate()
