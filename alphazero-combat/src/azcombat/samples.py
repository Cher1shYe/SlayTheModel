"""Versioned JSONL training samples for AlphaZero combat data."""
from __future__ import annotations
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from .schema import ActionNode, validate_observation
from .versions import SEARCH_SEMANTICS_VERSION

SAMPLE_SCHEMA_VERSION = 1
_START_TYPES = {"full_combat", "mid_combat_verified"}
_OUTCOMES = {"win", "loss", "unresolved"}

def _node_from_dict(raw: Mapping[str, Any]) -> ActionNode:
    if not isinstance(raw, Mapping) or set(raw) - {"kind", "actionId", "payload", "children", "terminal"}:
        raise ValueError("action node contains forbidden fields")
    node = ActionNode(str(raw.get("kind", "")), str(raw.get("actionId", "")), raw.get("payload"), tuple(_node_from_dict(x) for x in raw.get("children", ())), bool(raw.get("terminal", False)))
    node.validate()
    return node

def _node_to_dict(node: ActionNode) -> dict[str, Any]:
    value = {"kind": node.kind, "actionId": node.action_id, "terminal": node.terminal}
    if node.payload is not None: value["payload"] = dict(node.payload)
    if node.children: value["children"] = [_node_to_dict(x) for x in node.children]
    return value

def _action_ids(nodes: Iterable[ActionNode]) -> set[str]:
    result: set[str] = set()
    def visit(items: Iterable[ActionNode]) -> None:
        for node in items:
            if node.action_id in result: raise ValueError(f"duplicate actionId: {node.action_id}")
            result.add(node.action_id)
            visit(node.children)
    visit(nodes)
    return result

def _field(obj: Mapping[str, Any], name: str) -> Any:
    return obj[name] if name in obj else obj[name[0].upper() + name[1:]]

def _strict_keys(obj: Mapping[str, Any], names: tuple[str, ...], label: str) -> None:
    if not isinstance(obj, Mapping):
        raise ValueError(f"{label} must be an object")
    allowed = {name for key in names for name in (key, key[0].upper() + key[1:])}
    extra = set(obj) - allowed
    if extra:
        raise ValueError(f"{label} contains forbidden fields: {sorted(extra)}")
    for name in names:
        variants = (name, name[0].upper() + name[1:])
        if sum(key in obj for key in variants) != 1:
            raise ValueError(f"{label} requires exactly one spelling of {name}")

def _strict_observation(raw: Mapping[str, Any]) -> None:
    _strict_keys(raw, ("schemaVersion", "roundNumber", "currentSide", "players", "creatures", "choice"), "observation")
    for player in _field(raw, "players"):
        _strict_keys(player, ("playerId", "characterId", "energy", "stars", "turnNumber", "phase",
                              "piles", "relics", "potions", "orbs"), "player")
        for pile in _field(player, "piles"):
            _strict_keys(pile, ("pileType", "cards"), "pile")
            for card in _field(pile, "cards"):
                _strict_keys(card, ("combatCardIndex", "modelId", "energyCost", "afflictionId",
                                    "afflictionCount", "keywords"), "card")
        for relic in _field(player, "relics"):
            _strict_keys(relic, ("modelId",), "relic")
        for potion in _field(player, "potions"):
            _strict_keys(potion, ("slotIndex", "modelId"), "potion")
        for orb in _field(player, "orbs"):
            _strict_keys(orb, ("modelId", "passive", "evoke"), "orb")
    for creature in _field(raw, "creatures"):
        _strict_keys(creature, ("combatId", "playerId", "monsterId", "currentHp", "maxHp", "block", "powers", "currentIntent"), "creature")
        for power in _field(creature, "powers"):
            _strict_keys(power, ("modelId", "amount"), "power")
    choice = _field(raw, "choice")
    if choice is not None:
        _strict_keys(choice, ("triggerCardId", "effect", "sourcePile", "minCount", "maxCount",
                              "ordered", "candidates", "completedSelections"), "choice")
        for candidate in _field(choice, "candidates"):
            _strict_keys(candidate, ("combatCardIndex", "modelId", "upgradeLevel"), "choice candidate")
        for completed in _field(choice, "completedSelections"):
            _strict_keys(completed, ("effect", "combatCardIndices"), "completed selection")

def _normalize_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    _strict_observation(raw)
    players = []
    for p in _field(raw, "players"):
        players.append({"playerId": _field(p,"playerId"), "characterId": _field(p,"characterId"), "energy": _field(p,"energy"), "stars": _field(p,"stars"), "turnNumber": _field(p,"turnNumber"), "phase": _field(p,"phase"), "piles": [{"pileType": _field(q,"pileType"), "cards": [{"combatCardIndex": _field(c,"combatCardIndex"), "modelId": _field(c,"modelId"), "energyCost": _field(c,"energyCost"), "afflictionId": _field(c,"afflictionId"), "afflictionCount": _field(c,"afflictionCount"), "keywords": _field(c,"keywords")} for c in _field(q,"cards")]} for q in _field(p,"piles")], "relics": [{"modelId": _field(x,"modelId")} for x in _field(p,"relics")], "potions": [{"slotIndex": _field(x,"slotIndex"), "modelId": _field(x,"modelId")} for x in _field(p,"potions")], "orbs": [{"modelId": _field(x,"modelId"), "passive": _field(x,"passive"), "evoke": _field(x,"evoke")} for x in _field(p,"orbs")]})
    creatures = [{"combatId": _field(c,"combatId"), "playerId": _field(c,"playerId"), "monsterId": _field(c,"monsterId"), "currentHp": _field(c,"currentHp"), "maxHp": _field(c,"maxHp"), "block": _field(c,"block"), "currentIntent": _field(c,"currentIntent"), "powers": [{"modelId": _field(x,"modelId"), "amount": _field(x,"amount")} for x in _field(c,"powers")]} for c in _field(raw,"creatures")]
    source_choice = _field(raw, "choice")
    choice = None if source_choice is None else {
        "triggerCardId": _field(source_choice,"triggerCardId"), "effect": _field(source_choice,"effect"),
        "sourcePile": _field(source_choice,"sourcePile"), "minCount": _field(source_choice,"minCount"),
        "maxCount": _field(source_choice,"maxCount"), "ordered": _field(source_choice,"ordered"),
        "candidates": [{"combatCardIndex": _field(c,"combatCardIndex"), "modelId": _field(c,"modelId"),
                        "upgradeLevel": _field(c,"upgradeLevel")} for c in _field(source_choice,"candidates")],
        "completedSelections": [{"effect": _field(c,"effect"), "combatCardIndices": _field(c,"combatCardIndices")}
                                for c in _field(source_choice,"completedSelections")]}
    return {"schemaVersion": _field(raw,"schemaVersion"), "roundNumber": _field(raw,"roundNumber"), "currentSide": _field(raw,"currentSide"), "players": players, "creatures": creatures, "choice": choice}

@dataclass(frozen=True)
class TrainingSample:
    seed: str
    start_type: str
    observation: Mapping[str, Any]
    legal_actions: tuple[ActionNode, ...]
    visit_policy: Mapping[str, float]
    value_target: float
    outcome: str
    schema_version: int = SAMPLE_SCHEMA_VERSION

    def validate(self) -> "TrainingSample":
        if self.schema_version != SAMPLE_SCHEMA_VERSION: raise ValueError("unsupported training sample schemaVersion")
        if not self.seed: raise ValueError("seed must be nonempty")
        if self.start_type not in _START_TYPES: raise ValueError(f"unsupported startType: {self.start_type}")
        validate_observation(self.observation)
        ids = _action_ids(self.legal_actions)
        if not ids: raise ValueError("legalActions must not be empty")
        if not isinstance(self.visit_policy, Mapping) or not set(self.visit_policy).issubset(ids): raise ValueError("visitPolicy contains unknown action ids")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in self.visit_policy.values()) or not math.isfinite(sum(self.visit_policy.values())) or sum(self.visit_policy.values()) <= 0: raise ValueError("invalid visitPolicy")
        if not math.isfinite(self.value_target) or not -1 <= self.value_target <= 1: raise ValueError("valueTarget must be finite and in [-1,1]")
        if self.outcome not in _OUTCOMES: raise ValueError(f"unsupported outcome: {self.outcome}")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schemaVersion": self.schema_version, "seed": self.seed, "startType": self.start_type, "observation": self.observation, "legalActions": [_node_to_dict(x) for x in self.legal_actions], "visitPolicy": dict(self.visit_policy), "valueTarget": self.value_target, "outcome": self.outcome}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TrainingSample":
        required = {"schemaVersion","seed","startType","observation","legalActions","visitPolicy","valueTarget","outcome"}
        if not required.issubset(raw) or set(raw) - required - {"simulations","stateKey","provenance"}: raise ValueError("training sample fields do not match schema")
        if type(raw["valueTarget"]) not in (int, float) or type(raw["schemaVersion"]) is not int:
            raise ValueError("valueTarget and schemaVersion must be numeric")
        sample = cls(str(raw["seed"]), str(raw["startType"]), _normalize_observation(raw["observation"]), tuple(_node_from_dict(x) for x in raw["legalActions"]), raw["visitPolicy"], float(raw["valueTarget"]), str(raw["outcome"]), raw["schemaVersion"])
        return sample.validate()

def write_jsonl(samples: Iterable[TrainingSample], path: Path) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples: handle.write(json.dumps(sample.to_dict(), ensure_ascii=False, separators=(",",":")) + "\n"); count += 1
    return count

def read_jsonl(path: Path, *, allow_regression: bool = False,
               require_current_search_semantics: bool = False) -> list[TrainingSample]:
    result = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip(): continue
            try:
                raw = json.loads(line)
                sample = TrainingSample.from_dict(raw)
                provenance = raw.get("provenance", {})
                if not allow_regression and (provenance.get("regressionOnly")
                        or provenance.get("forcedFixtureCard") is not None):
                    raise ValueError("regression-only forced trajectory is not training data")
                if require_current_search_semantics and any(key in provenance for key in
                        ("requestedSearchMode", "searchMode", "decisionMetrics", "assemblies")) \
                        and provenance.get("searchSemanticsVersion") != SEARCH_SEMANTICS_VERSION:
                    raise ValueError("Native training sample searchSemanticsVersion is missing or obsolete")
                result.append(sample)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc: raise ValueError(f"invalid training sample at line {line_number}: {exc}") from exc
    return result



