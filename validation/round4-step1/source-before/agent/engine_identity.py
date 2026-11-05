"""Exact environment identity for new checkpoints; no permissive hash override.

The source digest identifies the checked-out rules/content and feature code.
Binding counts, enum entries and schema dimensions are checked against that
source. This is not proof of all feature mappings or native-game equivalence.
"""
from __future__ import annotations

import ast
import hashlib
import json
import operator
from pathlib import Path
import re

RULESET_ID = "native-41cef1ea-port-v3"
TARGET_GAME_DLL_SHA256 = "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4"
ROOT = Path(__file__).resolve().parents[1]
_PROCESS_CONTRACT_DIGEST = None
_IDS = ("CardId", "CardType", "TargetType", "Rarity", "CardPool", "PowerId",
        "EnchantmentId", "RelicId", "PotionId", "PotionUsage", "PotionTarget",
        "MonsterId", "Encounter", "Outcome", "ActionType", "ChoiceKind",
        "ChoiceOp", "ChoicePile", "RunActionType", "RunScreen", "MapPointType",
        "RoomType", "EventStatus")
_SCHEMA = ("RUN_OBS_DIM", "CARD_FEAT_DIM", "COMBAT_OBS_DIM", "ACTION_FEAT_DIM",
           "PUBLIC_OBS_DIM", "PUBLIC_COMBAT_OBS_DIM", "PUBLIC_OBS_VERSION",
           "ACTION_SCHEMA_VERSION", "MAX_DECK", "MAP_MAX_POINTS")


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def _integer(expression: str, names: dict[str, int]) -> int:
    expression = re.sub(r"static_cast<int>\(([^()]*)\)", r"\1", expression)
    expression = expression.replace("::", "__")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.floordiv, ast.LShift: operator.lshift, ast.BitOr: operator.or_}

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name):
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            return operations[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        raise ValueError(f"unsupported source constant: {expression}")

    return int(visit(ast.parse(expression.strip(), mode="eval").body))


def source_layout(root: Path) -> dict:
    """Read explicit source IDs and dimension formulas, without importing it."""
    headers = root / "simulator/include/sts2"
    texts = {p.name: _clean(p.read_text()) for p in sorted(headers.iterdir())
             if p.suffix in (".h", ".inc")}
    ids, names = {}, {}
    for text in texts.values():
        for name, body in re.findall(r"enum\s+(?:class\s+)?(\w+)\s*:[^{]+\{([^}]*)\}", text):
            if name not in _IDS:
                continue
            values, value = {}, -1
            for item in body.split(","):
                if not item.strip():
                    continue
                parts = item.strip().split("=", 1)
                value = _integer(parts[1], names | values) if len(parts) == 2 else value + 1
                values[parts[0].strip()] = value
                names[f"{name}__{parts[0].strip()}"] = value
            ids[name] = values
    if set(ids) != set(_IDS):
        raise ValueError("incomplete source ID layout")
    declarations = {}
    for text in texts.values():
        for name, expr in re.findall(r"constexpr\s+int\s+(\w+)\s*=\s*([^;]+);", text):
            declarations[name] = re.sub(r"\s+", "", expr)
    for _ in range(len(declarations)):
        updated = False
        for name, expr in declarations.items():
            if name in names:
                continue
            try:
                names[name] = _integer(expr, names)
                names[f"BattleContext__{name}"] = names[name]
                updated = True
            except (KeyError, ValueError, SyntaxError):
                pass
        if not updated:
            break
    dimensions = {key: names[key] for key in _SCHEMA}
    dimensions["CARD_COUNT"] = ids["CardId"]["COUNT"]
    boundaries = {key: names[key] for key in ("PUBLIC_RUN_DIM", "PUB_RUN_BOSS_OFFSET", "PUB_RUN_EXTENSION") if key in names}
    observation_layout = re.findall(r"constexpr\s+int\s+(\w+)\s*=\s*([^;]+);", texts["observe.h"])
    # Potion bindings use content keys (AttackPotion), not C++ enum spellings.
    potion_names = {"INVALID": ids["PotionId"]["INVALID"]}
    for enum_name, content_key in re.findall(r'\{PotionId::(\w+),\s*"([^"]*)"', texts["potions_generated.inc"]):
        if content_key:
            potion_names[content_key] = ids["PotionId"][enum_name]
    binding_names = {"PotionId": potion_names}
    return {"ids": ids, "binding_names": binding_names, "dimensions": dimensions, "boundaries": boundaries,
            "id_layout_sha256": _digest({"enums": ids, "binding_names": binding_names}),
            "schema_layout_sha256": _digest([(k, re.sub(r"\s+", "", v)) for k, v in observation_layout])}


def source_content_digest(root: Path) -> str:
    paths = []
    for directory in ("simulator/src", "simulator/include/sts2", "simulator/bindings"):
        paths.extend(p for p in (root / directory).rglob("*")
                     if p.is_file() and p.suffix in (".cpp", ".h", ".inc"))
    paths.extend(root / p for p in ("simulator/CMakeLists.txt", "agent/armg.py", "agent/common.py"))
    return _digest({str(p.relative_to(root)): sha256_file(p) for p in sorted(paths)})


def current_engine_contract() -> dict:
    global _PROCESS_CONTRACT_DIGEST
    from .common import LOADED_SIMULATOR_SHA256, sim

    binary_digest = sha256_file(sim.__file__)
    if binary_digest != LOADED_SIMULATOR_SHA256:
        raise ValueError("simulator binary changed after import; restart the process after rebuilding")
    if (getattr(sim, "ENGINE_RULESET_ID", None) != RULESET_ID or
            getattr(sim, "TARGET_GAME_DLL_SHA256", None) != TARGET_GAME_DLL_SHA256 or
            getattr(sim, "NATIVE_PARITY_COMPLETE", None) is not False):
        raise ValueError("loaded simulator is not the declared native rules port; rebuild its binding")
    layout = source_layout(ROOT)
    for name, expected in layout["dimensions"].items():
        if int(getattr(sim, name)) != expected:
            raise ValueError(f"binding/source schema mismatch: {name}")
    for name, expected in layout["boundaries"].items():
        if int(getattr(sim, name)) != expected:
            raise ValueError(f"binding/source boundary mismatch: {name}")
    for name, expected in layout["ids"].items():
        binding = getattr(sim, name, None)
        if binding is None:
            continue
        actual = {key: int(value) for key, value in binding.__members__.items()}
        exported = layout["binding_names"].get(name, expected)
        if any(exported.get(key) != value for key, value in actual.items()):
            raise ValueError(f"binding/source ID mismatch: {name}")
        if name in ("RelicId", "PotionId", "Encounter") and len(actual) != expected["COUNT"]:
            raise ValueError(f"binding/source ID count mismatch: {name}")
    contract = {"version": 2, "ruleset_id": RULESET_ID,
            "target_game_dll_sha256": TARGET_GAME_DLL_SHA256, "native_parity_complete": False,
            "simulator_sha256": binary_digest,
            "source_content_sha256": source_content_digest(ROOT),
            "id_layout_sha256": layout["id_layout_sha256"],
            "schema_layout_sha256": layout["schema_layout_sha256"],
            "dimensions": layout["dimensions"], "boundaries": layout["boundaries"],
            "feature_sources": {p: sha256_file(ROOT / p) for p in
                                ("simulator/src/observe.cpp", "agent/armg.py", "agent/common.py")}}
    digest = _digest(contract)
    if _PROCESS_CONTRACT_DIGEST is not None and digest != _PROCESS_CONTRACT_DIGEST:
        raise ValueError("engine source/features changed after identity check; restart after rebuilding")
    _PROCESS_CONTRACT_DIGEST = digest
    return contract


def validate_engine_contract(config: dict, path) -> None:
    if config.get("engine_contract") != current_engine_contract():
        raise ValueError(f"{path}: engine identity mismatch; use explicit weights-only migration for an old environment")


def bind_settings(settings: dict) -> dict:
    current = current_engine_contract()["simulator_sha256"]
    if settings.get("simulator_sha256", current) != current:
        raise ValueError("training settings simulator_sha256 does not match the loaded engine")
    return dict(settings, simulator_sha256=current)
