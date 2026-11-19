"""Audit basic registrations against frozen DLL exports; never assert effect parity.

Run from any directory. The optional --create-lock is a one-time initialization;
normal audits never rewrite the append-only numeric identity baseline.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = Path("sim/native-fixtures/native-registry-41cef1ea.json")
REGISTRY_SHA256 = "2fff4579c9fcb9c8eba920a6316ca711267529e041a858d49c9100773caa2969"
CARD_METADATA_PATH = Path("sim/native-fixtures/native-round4-step2-card-reward-fixtures/content-metadata.json")
CARD_METADATA_SHA256 = "18290c28fe26184c533f4d18b0199d6ba7fef92a745eb8024d2d5f798e10cdb4"
DLL_SHA256 = "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4"
LOCK_PATH = Path("sim/content/registry_identity_lock.json")


def module(root, name):
    spec = importlib.util.spec_from_file_location(name, root / "sim/tools" / (name + ".py"))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def enum_rows(source, name):
    body = re.search(r"enum\s+(?:class\s+)?" + name + r"\b[^\{]*\{(.*?)\};", source, re.S).group(1)
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.S)
    out, number = [], 0
    for token in body.split(","):
        token = token.strip()
        if not token:
            continue
        parts = token.split("=")
        key = parts[0].strip()
        if key in ("COUNT", "EV_COUNT"):
            continue
        if len(parts) > 1:
            number = int(parts[1].strip(), 0)
        out.append((number, key))
        number += 1
    if len({key for _, key in out}) != len(out) or len({n for n, _ in out}) != len(out):
        raise ValueError("duplicate numeric/key identity in " + name)
    return out


def current_identities(root, native):
    """Bind actual C++ enum values to real native IDs, including named reserves."""
    read = lambda path: (root / path).read_text()
    registry = {row["id"] for row in native["registered"]}
    cards = json.loads(read("sim/content/cards.json"))
    card_ids = {row["id"]: row.get("native_id", row["id"]) for row in cards}
    relics = json.loads(read("sim/content/relics.json"))
    native_relics = {row["className"]: row["id"] for row in native["relics"]}
    relic_ids = {row["id"]: native_relics[row["name"]] for row in relics}
    potion_ids = {"FAIRY_IN_ABOTTLE": "FAIRY_IN_A_BOTTLE", "GHOST_IN_AJAR": "GHOST_IN_A_JAR",
                  "SHIP_IN_ABOTTLE": "SHIP_IN_A_BOTTLE"}
    encounter_ids = dict(re.findall(r'case Encounter::(SETUP_\w+): return "(\w+)";', read("sim/src/monsters.cpp")))
    definitions = [
        ("CARD", "CardId", "sim/include/sts2/cards_generated.inc", card_ids),
        ("RELIC", "RelicId", "sim/include/sts2/relics_generated.inc", relic_ids),
        ("POTION", "PotionId", "sim/include/sts2/potions_generated.inc", potion_ids),
        ("MONSTER", "MonsterId", "sim/include/sts2/monsters_generated.inc", {}),
        ("ENCOUNTER", "Encounter", "sim/include/sts2/monsters_generated.inc", encounter_ids),
        ("EVENT", "EventId", "sim/src/events.cpp", {}),
    ]
    result = {}
    for category, name, path, aliases in definitions:
        rows = []
        for number, key in enum_rows(read(path), name):
            short = aliases.get(key, key.removeprefix("SETUP_") if category == "ENCOUNTER"
                                else key.removeprefix("EV_") if category == "EVENT" else key)
            ident = category + "." + short
            native_ids = [ident] if ident in registry else []
            if category == "MONSTER" and key == "DECIMILLIPEDE_SEGMENT":
                native_ids = ["MONSTER.DECIMILLIPEDE_SEGMENT_" + suffix for suffix in ("FRONT", "MIDDLE", "BACK")]
            rows.append({"id": number, "key": key, "native_ids": native_ids})
        result[category] = rows
    return result


def compare_lock(current, locked):
    """Existing indices and aliases cannot change; new slots may only append."""
    differences = []
    for category, baseline in locked.items():
        rows = current.get(category, [])
        if len({row["key"] for row in rows}) != len(rows):
            differences.append({"category": category, "reason": "duplicate local keys"})
        if any(a["id"] >= b["id"] for a, b in zip(rows, rows[1:])):
            differences.append({"category": category, "reason": "numeric IDs must be strictly increasing"})
        for index, expected in enumerate(baseline):
            actual = rows[index] if index < len(rows) else None
            if actual != expected:
                differences.append({"category": category, "index": index, "locked": expected, "current": actual})
        if len(rows) > len(baseline) and baseline:
            if any(row["id"] <= baseline[-1]["id"] for row in rows[len(baseline):]):
                differences.append({"category": category, "reason": "new slots must append with increasing IDs"})
    for category in current.keys() - locked.keys():
        differences.append({"category": category, "reason": "category absent from baseline"})
    return differences


def audit(root=ROOT):
    root = Path(root)
    raw = (root / REGISTRY_PATH).read_bytes()
    native = json.loads(raw)
    errors = []
    if hashlib.sha256(raw).hexdigest() != REGISTRY_SHA256:
        errors.append("frozen native registry SHA-256 mismatch")
    if native["gameDllSha256"] != DLL_SHA256:
        errors.append("native DLL identity mismatch")
    if hashlib.sha256((root / CARD_METADATA_PATH).read_bytes()).hexdigest() != CARD_METADATA_SHA256:
        errors.append("frozen complete native card metadata SHA-256 mismatch")
    cards = module(root, "audit_cards_registry").audit(root, native)
    items = module(root, "audit_relics_registry").audit(root, native)
    world = module(root, "audit_world_registry").audit(root, native)
    categories = {"cards": cards, "relics": items["relics"], "potions": items["potions"], **world}
    for category, result in categories.items():
        if result.get("differences") or result.get("status") == "mismatch":
            errors.append(category + " has unexplained differences")
    if not items["runtime_registry"]["available"]:
        errors.append("C++ registry extension unavailable; runtime metadata not verified")
    elif items["runtime_registry"]["ruleset"] != json.loads((root / "sim/PORT_SOURCE.json").read_text())["engine_ruleset"]:
        errors.append("compiled extension ruleset differs from PORT_SOURCE")
    identities = current_identities(root, native)
    lock_path = root / LOCK_PATH
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else None
    lock_errors = compare_lock(identities, lock["categories"]) if lock else [{"reason": "identity lock missing"}]
    if lock and (lock.get("version") != 1 or lock.get("native_registry_sha256") != REGISTRY_SHA256):
        lock_errors.append({"reason": "identity lock version/provenance mismatch"})
    if lock_errors:
        errors.append("numeric identity lock mismatch")
    catalog = json.loads((root / "train/spire_rl/public_catalog.json").read_text())
    catalog_errors = []
    generator = module(root, "gen_public_catalog")
    missing_relic_sources = [row["id"] for row in native["relics"]
                            if not (generator.NATIVE / "Relics" / (row["className"] + ".cs")).is_file()]
    expected_catalog = generator.build_catalog(include_relic_traits=not missing_relic_sources)
    if set(catalog["models"]) != set(expected_catalog["models"]):
        catalog_errors.append({"reason": "missing or extra public model categories"})
    for category, ids in catalog["models"].items():
        expected = sorted(row["id"] for row in native["registered"] if row["id"].startswith(category + ".")
                          and ".Mocks" not in row["namespaceName"] and not row["className"].startswith("Mock"))
        if ids != expected:
            catalog_errors.append({"category": category, "expected": expected, "actual": ids})
    if catalog.get("registrySha256") != REGISTRY_SHA256:
        catalog_errors.append({"reason": "public catalog provenance mismatch"})
    for key in expected_catalog.keys() | catalog.keys():
        if key == "relicTraits" and missing_relic_sources:
            continue
        if key != "models" and catalog.get(key) != expected_catalog.get(key):
            catalog_errors.append({"field": key, "reason": "public catalog differs from regenerated metadata"})
    if catalog_errors:
        errors.append("public model vocabulary differs from real non-mock registration")
    return {"schema": "sts2.registry-audit/1", "scope": "registration and selected base metadata, not effects or complete native parity",
            "status": "pass_with_documented_exceptions" if not errors else "fail",
            "errors": errors, "native_fixture": str(REGISTRY_PATH), "native_fixture_sha256": hashlib.sha256(raw).hexdigest(),
            "native_dll_sha256": native["gameDllSha256"], "runtime": items["runtime_registry"],
            "categories": categories, "identity_lock": {"path": str(LOCK_PATH), "differences": lock_errors,
                "slots": {key: len(rows) for key, rows in identities.items()}},
            "public_catalog": {"differences": catalog_errors, "counts": {k: len(v) for k, v in catalog["models"].items()},
                "relic_ui_traits": {"checked": not missing_relic_sources, "missing_source_count": len(missing_relic_sources),
                    "reason": "source not shipped; outside the DLL registration audit" if missing_relic_sources else None}},
            "unverified": ["card/relic/potion/event/ancient effect execution", "all dynamic eligibility and choice weights",
                           "all monster AI and combat transitions", "whole-run native parity"] +
                          (["relic UI traits source regeneration"] if missing_relic_sources else [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write complete machine-readable report")
    parser.add_argument("--create-lock", action="store_true", help="create initial lock; refuses to overwrite")
    args = parser.parse_args()
    if args.create_lock:
        native = json.loads((ROOT / REGISTRY_PATH).read_text())
        data = {"version": 1, "base_ruleset": "native-41cef1ea-port-v13", "native_registry_sha256": REGISTRY_SHA256,
                "policy": "existing numeric IDs, keys, and native mappings are immutable; only append new entries",
                "categories": current_identities(ROOT, native)}
        with (ROOT / LOCK_PATH).open("x") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    result = audit()
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "errors", "runtime", "identity_lock", "public_catalog")}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
