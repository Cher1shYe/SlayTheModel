"""Audit relic/potion identities and registry attributes, not implemented effects.

`audit(root, native)` accepts the pinned DLL registry export. Without it, the
same checks use literal declarations from the pinned decompiled source and say
so explicitly. The built C++ registry is checked separately from the JSON input.
"""
from __future__ import annotations

from collections import Counter
import importlib
import json
from pathlib import Path
import re
import sys


RELIC_RARITY = {-1: "None", 0: "Starter", 1: "Common", 2: "Uncommon",
                3: "Rare", 4: "Shop", 5: "Event", 6: "None", 7: "Ancient"}
POTION_RARITY = {0: "Common", 1: "Uncommon", 2: "Rare", 3: "Event", 4: "Token", 5: "None"}
USAGE = {0: "CombatOnly", 1: "AnyTime", 2: "Automatic"}
TARGET = {0: "Self", 1: "AnyEnemy", 2: "AllEnemies", 3: "AnyPlayer", 4: "TargetedNoCreature"}
CHARACTERS = {"Ironclad", "Silent", "Defect", "Regent", "Necrobinder"}
COMPRESSED_RARITY = {"None": 4, "Starter": 4, "Common": 1, "Uncommon": 2,
                     "Rare": 3, "Shop": 4, "Event": 4, "Ancient": 4, "Token": 4}
COMPRESSED_POOL = {"SHARED": 0, "IRONCLAD": 1, "EVENT": 2}


def slug(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2",
                  re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).upper()


def _duplicates(values):
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _source_rows(root, singular):
    core = root / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core"
    models = core / "Models"
    category = singular.upper()
    rows, pools, non_models = [], [], []
    for path in sorted((models / (singular + "Pools")).glob("*.cs")):
        source = path.read_text()
        declaration = source.split("GenerateAll" + singular + "s()", 1)[1]
        declaration = declaration.split("public override", 1)[0]
        entries = re.findall(r"ModelDb\." + singular + r"<(\w+)>\(\)", declaration)
        # Character potion pools delegate their three entries to an epoch.
        for epoch in re.findall(r"return (\w+Epoch)\.Potions;", declaration):
            entries += re.findall(r"ModelDb\.Potion<(\w+)>\(\)",
                (core / "Timeline/Epochs" / (epoch + ".cs")).read_text())
        pools.append({"id": category + "_POOL." + slug(path.stem),
                      "className": path.stem,
                      "entries": [category + "." + slug(name) for name in entries]})
    for path in sorted((models / (singular + "s")).rglob("*.cs")):
        source = path.read_text()
        if not re.search(r"class\s+" + re.escape(path.stem) + r"\s*:\s*" + singular + "Model", source):
            non_models.append(str(path.relative_to(root)))
            continue
        def literal(prop, type_name):
            match = re.search(r"override " + type_name + " " + prop + r" => " + type_name + r"\.(\w+);", source)
            if not match:
                raise ValueError(f"Unsupported literal {path}:{prop}; require DLL export")
            return match.group(1)
        ident = category + "." + slug(path.stem)
        row = {"id": ident, "className": path.stem,
               "rarityName": literal("Rarity", singular + "Rarity"),
               "poolIds": [pool["id"] for pool in pools if ident in pool["entries"]],
               "isMock": "override bool IsMock => true" in source,
               "source": str(path.relative_to(root))}
        if singular == "Potion":
            row.update(usageName=literal("Usage", "PotionUsage"),
                       targetName="TargetedNoCreature" if path.stem == "FoulPotion" else literal("TargetType", "TargetType"),
                       canBeGeneratedInCombat="override bool CanBeGeneratedInCombat => false" not in source)
            if path.stem == "FoulPotion":
                row["conditionalTargets"]={"outsideCombat":"TargetedNoCreature","inCombat":"AllEnemies"}
        rows.append(row)
    return rows, pools, non_models


def _pool_short(ident, singular):
    return ident.split(".")[-1].removesuffix("_" + singular.upper() + "_POOL")


def _runtime(root):
    path = str(root / "sim/build")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("sts2_sim"), None
    except ImportError as exc:
        return None, str(exc)


def audit(root: Path, native: dict | None = None) -> dict:
    root = Path(root).resolve()
    result = {"evidence": "native-dll-registry" if native is not None else "pinned-native-source",
              "effects_checked": False,
              "not_compared_as_registry_fields": ["effect execution", "dynamic-variable values hardcoded inside effect handlers"]}
    runtime, runtime_error = _runtime(root)
    result["runtime_registry"] = {"available": runtime is not None, "error": runtime_error,
                                  "ruleset": str(runtime.ENGINE_RULESET_ID) if runtime else None}
    for singular in ("Relic", "Potion"):
        plural = singular.lower() + "s"
        local = json.loads((root / "sim/content" / (plural + ".json")).read_text())
        source_dir = root / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models"
        if source_dir.is_dir():
            source_rows, source_pools, non_models = _source_rows(root, singular)
        elif native is not None:
            source_rows, source_pools, non_models = [], [], []
        else:
            raise FileNotFoundError("Pinned native source unavailable; pass the DLL registry export")
        def model_id(value):
            return value if "." in value else singular.upper()+"."+value
        rows = [dict(row,id=model_id(row["id"])) for row in native[plural]] if native is not None else source_rows
        pools = [dict(pool,entries=[model_id(value) for value in pool["entries"]])
                 for pool in native[singular.lower() + "Pools"]] if native is not None else source_pools
        by_class = {row["className"].split(".")[-1]: row for row in rows}
        source_by_id = {row["id"]: row for row in source_rows}
        local_names = [row["name"] if singular == "Relic" else row["id"] for row in local]
        non_game = [row for row in rows if row.get("isMock") or row["className"].split(".")[-1].startswith("Mock")]
        expected_names = set(by_class) - {row["className"].split(".")[-1] for row in non_game}
        report = {"simulator_count": len(local), "native_registered_count": len(rows),
                  "native_non_mock_count": len(expected_names),
                  "duplicate_simulator_ids": _duplicates(row["id"] for row in local),
                  "duplicate_simulator_classes": _duplicates(local_names),
                  "duplicate_native_ids": _duplicates(row["id"] for row in rows),
                  "missing": sorted(expected_names - set(local_names)),
                  "extra": sorted(set(local_names) - expected_names),
                  "excluded_native_test_models": sorted(row["id"] for row in non_game),
                  "non_model_source_helpers": non_models,
                  "identity_aliases": [], "attribute_mismatches": [],
                  "conditional_attributes": [],
                  "runtime_content_mismatches": [], "native_pool_declaration_mismatches": [],
                  "mapping": []}
        for index, (name, row) in enumerate(zip(local_names, local), 1):
            if name not in by_class:
                continue
            other = by_class[name]
            native_id = other["id"]
            legacy_key = row["id"] if singular == "Relic" else re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()
            mapping = {"simulator_id": index, "simulator_key": legacy_key,
                       "native_id": native_id, "class_name": name}
            report["mapping"].append(mapping)
            if legacy_key != native_id.split(".")[-1]:
                report["identity_aliases"].append(mapping)
            def mismatch(field, actual, expected, layer="content"):
                if actual != expected:
                    report["attribute_mismatches"].append({"id": native_id, "field": field,
                        "simulator": actual, "native": expected, "layer": layer,
                        "source": source_by_id.get(native_id, {}).get("source")})
            rarity_map = RELIC_RARITY if singular == "Relic" else POTION_RARITY
            mismatch("rarity", rarity_map.get(row["rarity"], "UNKNOWN"), other["rarityName"])
            pool_ids = other.get("poolIds", [])
            if not pool_ids:
                pool_ids = [pool["id"] for pool in pools if native_id in pool["entries"]]
            short_pools = [_pool_short(ident, singular) for ident in pool_ids]
            if singular == "Relic":
                if row["pool"] not in short_pools:
                    mismatch("pool", row["pool"], short_pools)
                if runtime:
                    actual = tuple(runtime.relic_info(index))
                    expected = (legacy_key, name, COMPRESSED_RARITY[rarity_map[row["rarity"]]],
                                COMPRESSED_POOL.get(row["pool"], 3))
                    if actual != expected:
                        report["runtime_content_mismatches"].append({"id": native_id,"actual": actual,"expected": expected})
            else:
                mismatch("usage", USAGE[row["usage"]], other["usageName"])
                mismatch("target", TARGET[row["target"]], other["targetName"])
                if name == "FoulPotion":
                    report["conditional_attributes"].append({"id":native_id,"field":"target",
                        "native":{"outsideCombat":"TargetedNoCreature","inCombat":"AllEnemies"},
                        "simulator":{"outsideCombat":TARGET[row["target"]],
                                     "inCombat":TARGET[row.get("targetInCombat",row["target"])]}})
                    mismatch("target_in_combat",TARGET[row.get("targetInCombat",row["target"])],"AllEnemies")
                mismatch("combat_generation", row["combatGen"], other["canBeGeneratedInCombat"])
                character = next((name for name in CHARACTERS if name.upper() in short_pools), None)
                mismatch("character_pool", row["char"], character)
                mismatch("ironclad_available", row["ironclad"], character is None or character == "Ironclad")
                if runtime:
                    actual = tuple(runtime.potion_def(index))
                    expected = (name, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name),
                        COMPRESSED_RARITY[rarity_map[row["rarity"]]], row["usage"], row["target"],
                        row["ironclad"], row["combatGen"])
                    if actual != expected:
                        report["runtime_content_mismatches"].append({"id": native_id,"actual": actual,"expected": expected})
                    if hasattr(runtime, "potion_target"):
                        actual_target = runtime.potion_target(index, True)
                        expected_target = row.get("targetInCombat", row["target"])
                        if actual_target != expected_target:
                            report["runtime_content_mismatches"].append({"id": native_id,
                                "field":"target_in_combat","actual":actual_target,"expected":expected_target})
        if singular == "Relic":
            generated = (root / "sim/include/sts2/native_relic_pools.inc").read_text()
            model_ids = {row["id"]: "RELIC." + slug(row["name"]) for row in local}
            for name in ("Shared", "Ironclad"):
                body = re.search(r"NATIVE_" + name.upper() + r"_RELICS\[\] = \{(.*?)\};", generated, re.S)[1]
                actual = [model_ids[key] for key in re.findall(r"RelicId::(\w+)", body)]
                expected = next(pool["entries"] for pool in pools if _pool_short(pool["id"], singular) == name.upper())
                if actual != expected:
                    report["native_pool_declaration_mismatches"].append({"pool":name,"simulator":actual,"native":expected})
        else:
            generated = (root / "sim/include/sts2/native_potion_pool.inc").read_text()
            model_ids = {entry["simulator_key"]:entry["native_id"] for entry in report["mapping"]}
            actual = [model_ids[key] for key in re.findall(r"PotionId::(\w+)", generated)]
            expected = [entry for name in ("IRONCLAD", "SHARED") for pool in pools
                        if _pool_short(pool["id"], singular) == name for entry in pool["entries"]]
            if actual != expected:
                report["native_pool_declaration_mismatches"].append({"pool":"Ironclad+Shared",
                    "simulator":actual,"native":expected})
        report["matching_identity_count"] = len(report["mapping"])
        report["status"] = "mismatch" if any(report[key] for key in (
            "duplicate_simulator_ids", "duplicate_simulator_classes", "duplicate_native_ids", "missing", "extra",
            "attribute_mismatches", "runtime_content_mismatches", "native_pool_declaration_mismatches")) else "match"
        result[plural] = report
    return result


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--native",type=Path)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    report=audit(Path(__file__).resolve().parents[2],json.loads(args.native.read_text()) if args.native else None)
    rendered=json.dumps(report,indent=2,ensure_ascii=False)+"\n"
    if args.out:args.out.write_text(rendered)
    else:print(rendered,end="")
