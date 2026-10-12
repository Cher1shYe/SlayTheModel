#!/usr/bin/env python3
"""Report card effects that read effect_vars keys absent from their factories."""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.cards.factory import create_card
from sts2_env.cards.registry import _CARD_EFFECTS


CARD_MODULES = (
    "sts2_env.cards.ironclad_basic",
    "sts2_env.cards.ironclad",
    "sts2_env.cards.silent",
    "sts2_env.cards.defect",
    "sts2_env.cards.necrobinder",
    "sts2_env.cards.regent",
    "sts2_env.cards.colorless",
    "sts2_env.cards.status",
)


def _effect_var_keys_read(func) -> set[str]:
    tree = ast.parse(inspect.getsource(func))
    constants = _string_constants(tree) | _global_string_constants(func)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "effect_vars"
            and node.args
        ):
            key = _string_key(node.args[0], constants)
            if key is not None:
                keys.add(key)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "effect_vars"
        ):
            key = _string_key(node.slice, constants)
            if key is not None:
                keys.add(key)
    return keys


def _string_constants(tree: ast.AST) -> dict[str, str]:
    return {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _global_string_constants(func) -> dict[str, str]:
    return {
        name: value
        for name, value in func.__globals__.items()
        if isinstance(value, str)
    }


def _string_key(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def main() -> int:
    for module_name in CARD_MODULES:
        importlib.import_module(module_name)

    mismatches: list[tuple[str, list[str], list[str], list[str]]] = []
    for card_id, func in sorted(_CARD_EFFECTS.items(), key=lambda item: item[0].name):
        read_keys = _effect_var_keys_read(func)
        if not read_keys:
            continue
        try:
            base_card = create_card(card_id, upgraded=False)
            upgraded_card = create_card(card_id, upgraded=True)
        except Exception:
            continue
        available_keys = set(base_card.effect_vars) | set(upgraded_card.effect_vars)
        missing_keys = sorted(read_keys - available_keys)
        if missing_keys:
            mismatches.append(
                (
                    card_id.name,
                    sorted(read_keys),
                    sorted(available_keys),
                    missing_keys,
                )
            )

    for card_name, read_keys, available_keys, missing_keys in mismatches:
        print(
            f"{card_name}: missing={missing_keys} "
            f"read={read_keys} available={available_keys}"
        )

    if mismatches:
        print(f"{len(mismatches)} card effect var mismatch(es) found")
        return 1
    print("card effect var audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
