"""Audit registered card identity and static metadata against the pinned DLL export.

This checks content and the generated C++ table, not execution of card effects.
The old Grapple enum slot is reserved; DeprecatedCard is a native save fallback.
MadScience's unconfigured template is explicitly distinct from its event-created
Attack/Skill/Power instances, and that difference is reported, never normalized.
"""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile

DLL_SHA256 = "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4"


def audit_fresh_export(oracle: dict, fresh: dict, check) -> dict:
    """Cross-check the owner-configured card fixture against ModelDb export.

    The fresh exporter reads unowned templates. Stardust's X-star-cost getter
    dereferences Owner, so its two failed reads remain explicit unavailable
    evidence; the owner-configured fixture still checks its simulator values.
    """
    def compare(identity, field, previous, current, *, exception=None):
        check(identity, "fresh_registry." + field, previous, current,
              exception=exception, actual_label="native_metadata",
              expected_label="native_registry")

    compare("registry", "dll_identity", oracle.get("gameAssemblySha256"), fresh.get("gameDllSha256"))
    rows = fresh["cards"]
    previous = {row["id"]: row for row in oracle["results"]}
    current = {row["id"]: row for row in rows}
    compare("registry", "duplicate_id", [], sorted(key for key, count in
            Counter(row["id"] for row in rows).items() if count > 1))
    compare("registry", "identities", sorted(previous), sorted(current))
    # ModelDb also registers test mocks; those are not production card content.
    registered = sorted(row["id"].removeprefix("CARD.") for row in fresh["registered"]
                        if row["id"].startswith("CARD.") and ".Mocks" not in row["namespaceName"])
    compare("registry", "modeldb_identities", sorted(current), registered)
    compare("registry", "pool_order", [pool["id"] for pool in oracle["pools"]],
            [pool["id"] for pool in fresh["cardPools"]])
    old_pools = {pool["id"]: pool["cards"] for pool in oracle["pools"]}
    for pool in fresh["cardPools"]:
        compare(pool["id"], "pool_entries", old_pools.get(pool["id"]), pool["entries"])

    readable, unavailable = 0, 0
    static_fields = {"className": "className", "type": "type", "rarity": "rarity",
                     "target": "target", "multiplayerConstraint": "multiplayerConstraint",
                     "maxUpgrade": "maxUpgradeLevel", "canBeGeneratedInCombat": "generated"}
    variant_fields = {"upgrade": "actualUpgradeLevel", "cost": "cost", "xCost": "xCost",
                      "starCost": "starCost", "starXCost": "starCostX"}
    for identity in sorted(previous.keys() & current.keys()):
        old, new = previous[identity], current[identity]
        for field, old_field in static_fields.items():
            compare(identity, field, old[old_field], new[field])
        compare(identity, "tags", sorted(old["tags"]), sorted(new["tags"]))
        compare(identity, "pools", [old["pool"]], new["poolIds"])
        compare(identity, "variant_count", len(old["variants"]), len(new["variants"]))
        for index, (before, after) in enumerate(zip(old["variants"], new["variants"])):
            key = "upgraded" if index else "base"
            if "error" in after:
                unavailable += 1
                known_context_limit = identity == "STARDUST" and after["error"] == "NullReferenceException"
                compare(identity, key + ".readable", "readable", after,
                        exception=("Unowned native template export: Stardust.HasStarCostX is true, and "
                                   "CardModel.GetStarCostWithModifiers dereferences Owner.PlayerCombatState. "
                                   "Both variants are present in the separate owner-configured DLL fixture "
                                   "and checked against the simulator there. No missing value is replaced by zero.")
                        if known_context_limit else None)
                continue
            readable += 1
            for field, old_field in variant_fields.items():
                compare(identity, key + "." + field, before[old_field], after[field])
            # Keywords and tags are sets; pool ordering above is not.
            compare(identity, key + ".keywords", sorted(before["keywords"]), sorted(after["keywords"]))
            variables = {item["name"]: item["value"] for item in after["vars"]}
            compare(identity, key + ".variable_names", sorted(before["vars"]), sorted(variables))
            for name in sorted(before["vars"].keys() | variables.keys()):
                compare(identity, key + ".vars." + name, before["vars"].get(name), variables.get(name))
    return {"fresh_registered": len(rows), "fresh_readable_variants": readable,
            "fresh_unavailable_variants": unavailable}


def snake(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2",
                  re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)).lower()


def audit(root: Path, native: dict | None = None) -> dict:
    root = Path(root).resolve()
    metadata_path = root / "sim/native-fixtures/native-round4-step2-card-reward-fixtures/content-metadata.json"
    fresh_path = root / "sim/native-fixtures/native-registry-41cef1ea.json"
    provided = native is not None and "results" in native and "pools" in native
    fresh_provided = native is not None and "cards" in native and "cardPools" in native
    oracle = native if provided else json.loads(metadata_path.read_text())
    fresh = native if fresh_provided else json.loads(fresh_path.read_text())
    cards = json.loads((root / "sim/content/cards.json").read_text())
    rows = oracle["results"]
    differences, exceptions, aliases = [], [], []
    checks = Counter()

    def check(identity, field, simulated, expected, *, exception=None,
              actual_label="simulator", expected_label="native"):
        checks[field.split(".")[0]] += 1
        if simulated == expected:
            return
        finding = {"id": identity, "field": field, actual_label: simulated, expected_label: expected}
        if exception is not None:
            finding["reason"] = exception
            exceptions.append(finding)
        else:
            differences.append(finding)

    check("registry", "dll_identity", oracle.get("gameAssemblySha256"), DLL_SHA256)
    fresh_counts = audit_fresh_export(oracle, fresh, check)
    local_ids = [card["id"] for card in cards]
    identities = [card.get("native_id") or card["id"] for card in cards]
    for label, values in (("local_id", local_ids), ("mapped_native_id", identities),
                          ("native_id", [row["id"] for row in rows])):
        check("registry", "duplicate_" + label, sorted(k for k, n in Counter(values).items() if n > 1), [])
    native_by_id = {row["id"]: row for row in rows}
    sim_by_id = dict(zip(identities, cards))
    for identity in sorted(sim_by_id.keys() - native_by_id.keys()):
        check(identity, "registration", "simulator-only", "absent",
              exception="Reserved legacy enum slot, excluded by card_native_available; not a native card."
              if identity == "GRAPPLE" else None)
    for identity in sorted(native_by_id.keys() - sim_by_id.keys()):
        check(identity, "registration", "absent", "native-only",
              exception="Native DeprecatedCard save-migration fallback, not a playable content pool."
              if identity == "DEPRECATED_CARD" else None)

    rank = {identity: group * 1000 + index for group, pool in enumerate(oracle["pools"])
            for index, identity in enumerate(pool["cards"])}
    native_pools = {pool["id"]: pool["cards"] for pool in oracle["pools"]}
    stored_pools = json.loads((root / "sim/content/native_card_pools.json").read_text())
    check("registry", "pool_manifest", stored_pools, oracle["pools"])
    dynamic_reason = ("Unconfigured native MadScience has TinkerTimeType=None and Target=Self; "
                      "the legacy table defaults to Attack/AnyEnemy. Event-created instances carry "
                      "tinkerType and card_type/card_target select Attack/Skill/Power. "
                      "This template difference is not asserted equal.")
    for identity in sorted(sim_by_id.keys() & native_by_id.keys()):
        card, model = sim_by_id[identity], native_by_id[identity]
        if card["id"] != identity:
            aliases.append({"simulator_id": card["id"], "native_id": identity})
        fields = {
            "native_identity": (card.get("native_id"), model["id"]),
            "class_name": (card.get("native_class"), model["className"]),
            "type": (card["type"].lower(), model["type"].lower()),
            "target": (card["target"].lower(), snake(model["target"])),
            "rarity": (card["rarity"].lower(), model["rarity"].lower()),
            "pool": (card["pool"], model["pool"].lower().removesuffix("_card_pool")),
            "multiplayer_only": (card["multiplayer_only"], model["multiplayerConstraint"] == "MultiplayerOnly"),
            "max_upgrade": (card.get("max_upgrade_level", 1), model["maxUpgradeLevel"]),
            "combat_generation": (card.get("can_be_generated_in_combat", True), model["generated"]),
            "tags": (sorted(card["tags"]), sorted(tag.upper() for tag in model["tags"])),
            "pool_order": (card.get("native_pool_order", 99999), rank[identity]),
        }
        for field, (simulated, expected) in fields.items():
            check(identity, field, simulated, expected,
                  exception=dynamic_reason if identity == "MAD_SCIENCE" and field in ("type", "target") else None)
        for index, variant in enumerate(model["variants"]):
            key = "upgraded" if index else "base"
            local = card["variants"][key]
            fields = {
                "cost": (local["cost"], variant["cost"]),
                "x_cost": (local["x_cost"], variant["xCost"]),
                "star_cost": (local.get("star_cost", -1), variant["starCost"]),
                "star_cost_x": (local.get("star_cost_x", False), variant["starCostX"]),
                "keywords": (sorted(word.lower() for word in local["keywords"]),
                             sorted(word.lower() for word in variant["keywords"])),
            }
            for field, (simulated, expected) in fields.items():
                check(identity, key + "." + field, simulated, expected)
            variables = dict(local["effect_vars"])
            for field in ("damage", "block"):
                variables[field] = local.get("base_" + field) or variables.get(field, 0)
            for name, expected in variant["vars"].items():
                check(identity, key + ".vars." + name, variables.get(snake(name), 0), expected)
            # Generator reads these redundant base fields directly; checking
            # only variants would miss divergence between JSON and the table.
            if not index:
                for field in ("cost", "x_cost", "base_damage", "base_block", "effect_vars", "keywords"):
                    check(identity, "base_storage." + field, card.get(field), local.get(field))

    # Regenerate into a temporary file without touching the working table.
    generator_path = root / "sim/tools/gen_cards.py"
    spec = importlib.util.spec_from_file_location("_registry_audit_gen_cards", generator_path)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    with tempfile.TemporaryDirectory(prefix="sts2-card-registry-") as directory:
        generator.OUT = Path(directory) / "cards_generated.inc"
        with redirect_stdout(io.StringIO()):
            generator.main()
        actual = (root / "sim/include/sts2/cards_generated.inc").read_bytes()
        check("registry", "generated_table", hashlib.sha256(actual).hexdigest(),
              hashlib.sha256(generator.OUT.read_bytes()).hexdigest())

    match_count = sum(checks.values()) - len(differences) - len(exceptions)
    return {
        "category": "cards",
        "counts": {"native_registered": len(rows), "simulator_content_rows": len(cards),
                   "simulator_enum_slots_including_invalid": len(cards) + 1,
                   "matched_identities": len(sim_by_id.keys() & native_by_id.keys()),
                   "native_pool_counts": {pool: len(values) for pool, values in native_pools.items()},
                   **fresh_counts,
                   "field_checks": sum(checks.values()), "checks_by_family": dict(checks)},
        "matches": match_count,
        "differences": differences,
        "exceptions": exceptions,
        "aliases": aliases,
        "evidence": {
            "native_metadata": "provided card metadata object" if provided else str(metadata_path.relative_to(root)),
            "native_metadata_sha256": hashlib.sha256(
                json.dumps(oracle, sort_keys=True, separators=(",", ":")).encode() if provided else metadata_path.read_bytes()).hexdigest(),
            "native_metadata_digest_format": "canonical JSON" if provided else "original file bytes",
            "game_dll_sha256": oracle.get("gameAssemblySha256"),
            "fresh_registry": "provided ModelDb registry object" if fresh_provided else str(fresh_path.relative_to(root)),
            "fresh_registry_sha256": hashlib.sha256(
                json.dumps(fresh, sort_keys=True, separators=(",", ":")).encode() if fresh_provided else fresh_path.read_bytes()).hexdigest(),
            "fresh_registry_digest_format": "canonical JSON" if fresh_provided else "original file bytes",
            "fresh_registry_exception_source": "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models/CardModel.cs:GetStarCostWithModifiers; Cards/Stardust.cs:HasStarCostX",
            "simulator_content": "sim/content/cards.json",
            "generated_cpp_table": "sim/include/sts2/cards_generated.inc",
            "mad_science_instance_rules": ["sim/src/cards.cpp:card_type/card_target",
                                           "sim/src/events.cpp:TinkerTime", "sim/tests/native_step3_events.cpp"],
            "scope": "Identity, pool membership/order, static base/upgraded properties and native dynamic variables; not card-effect execution parity.",
        },
    }


if __name__ == "__main__":
    result = audit(Path(__file__).resolve().parents[2])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result["differences"]))
