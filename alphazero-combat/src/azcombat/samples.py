"""Versioned JSONL training samples for AlphaZero combat data."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from .schema import ActionNode, validate_observation

SAMPLE_SCHEMA_VERSION = 1
_START_TYPES = {"full_combat", "mid_combat_verified"}
_OUTCOMES = {"win", "loss", "unresolved"}

def _node_from_dict(raw: Mapping[str, Any]) -> ActionNode:
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
    for node in nodes:
        if node.action_id in result: raise ValueError(f"duplicate actionId: {node.action_id}")
        result.add(node.action_id); result.update(_action_ids(node.children))
    return result

def _field(obj: Mapping[str, Any], name: str) -> Any:
    return obj[name] if name in obj else obj[name[0].upper() + name[1:]]

def _normalize_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    players = []
    for p in _field(raw, "players"):
        players.append({"playerId": _field(p,"playerId"), "characterId": _field(p,"characterId"), "energy": _field(p,"energy"), "stars": _field(p,"stars"), "turnNumber": _field(p,"turnNumber"), "phase": _field(p,"phase"), "piles": [{"pileType": _field(q,"pileType"), "cards": [{"combatCardIndex": _field(c,"combatCardIndex"), "modelId": _field(c,"modelId"), "energyCost": _field(c,"energyCost"), "afflictionId": _field(c,"afflictionId"), "afflictionCount": _field(c,"afflictionCount"), "keywords": _field(c,"keywords")} for c in _field(q,"cards")]} for q in _field(p,"piles")], "relics": [{"modelId": _field(x,"modelId")} for x in _field(p,"relics")], "potions": [{"slotIndex": i, "modelId": x} for i,x in enumerate(_field(p,"potions"))], "orbs": [{"modelId": _field(x,"modelId"), "passive": _field(x,"passive"), "evoke": _field(x,"evoke")} for x in _field(p,"orbs")]})
    creatures = [{"combatId": _field(c,"combatId"), "playerId": _field(c,"playerId"), "monsterId": _field(c,"monsterId"), "currentHp": _field(c,"currentHp"), "maxHp": _field(c,"maxHp"), "block": _field(c,"block"), "powers": [{"modelId": _field(x,"modelId"), "amount": _field(x,"amount")} for x in _field(c,"powers")]} for c in _field(raw,"creatures")]
    return {"schemaVersion": _field(raw,"schemaVersion"), "roundNumber": _field(raw,"roundNumber"), "currentSide": _field(raw,"currentSide"), "players": players, "creatures": creatures}

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
        if not set(self.visit_policy).issubset(ids): raise ValueError("visitPolicy contains unknown action ids")
        if any(not isinstance(v,(int,float)) or v < 0 for v in self.visit_policy.values()) or sum(self.visit_policy.values()) <= 0: raise ValueError("invalid visitPolicy")
        if not -1 <= self.value_target <= 1: raise ValueError("valueTarget must be in [-1,1]")
        if self.outcome not in _OUTCOMES: raise ValueError(f"unsupported outcome: {self.outcome}")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {"schemaVersion": self.schema_version, "seed": self.seed, "startType": self.start_type, "observation": self.observation, "legalActions": [_node_to_dict(x) for x in self.legal_actions], "visitPolicy": dict(self.visit_policy), "valueTarget": self.value_target, "outcome": self.outcome}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TrainingSample":
        required = {"schemaVersion","seed","startType","observation","legalActions","visitPolicy","valueTarget","outcome"}
        if not required.issubset(raw) or set(raw) - required - {"simulations","stateKey","provenance"}: raise ValueError("training sample fields do not match schema")
        sample = cls(str(raw["seed"]), str(raw["startType"]), _normalize_observation(raw["observation"]), tuple(_node_from_dict(x) for x in raw["legalActions"]), raw["visitPolicy"], float(raw["valueTarget"]), str(raw["outcome"]), int(raw["schemaVersion"]))
        return sample.validate()

def write_jsonl(samples: Iterable[TrainingSample], path: Path) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples: handle.write(json.dumps(sample.to_dict(), ensure_ascii=False, separators=(",",":")) + "\n"); count += 1
    return count

def read_jsonl(path: Path) -> list[TrainingSample]:
    result = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip(): continue
            try: result.append(TrainingSample.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc: raise ValueError(f"invalid training sample at line {line_number}: {exc}") from exc
    return result



