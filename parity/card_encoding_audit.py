"""Card identity and encoding audit: simulator vs native, through the shared encoder.

For every card model in the pinned native DLL registry and every upgrade level, the
simulator's public export of a fresh deck card (``sts2_sim.public_card_template``,
the same ``public_card_view`` used for real deck cards) and a native-host-shaped card
built from the DLL registry go through the same ``public_obs._card`` and the same
card-row encoder. Their public facts and encoded network rows must be identical, and
the simulator<->native identity mapping must be one-to-one, so a card the policy
picks in training is the same card in the native client.

Scope: fresh (unmodified) deck cards. Combat-time values (cost modifiers, temporary
keywords, enchantments, bonuses) are exercised by the recorded native parity frames,
not by this audit. Usage (repository root):
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=.:train python -m parity.card_encoding_audit [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sim/native-fixtures/native-registry-41cef1ea.json"
LOCK = ROOT / "sim/content/registry_identity_lock.json"

# Explicit, documented exceptions (never silently normalized).
EXCEPTIONS = {
    # The DLL template is unconfigured (type None, target Self); event-made
    # instances get their type/target from tinkerType (registry-audit.md).
    ("MAD_SCIENCE", "type"): "native unconfigured template is None; instances are configured by the event",
    ("MAD_SCIENCE", "target"): "native unconfigured template is Self; instances are configured by the event",
}
UNAVAILABLE = {
    # The registry template has type None, which no real card instance has: Tinker
    # Time configures type/target before the card exists (MadScience.TinkerTimeType).
    "MAD_SCIENCE": "native registry template is unconfigured (type None); real instances are configured by Tinker Time",
    # Unowned template getter dereferences Owner (registry-audit.md); values are
    # covered by the owner-configured DLL card fixture instead.
    "STARDUST": "native registry export has no readable variant (NullReferenceException without an owner)",
}


def native_raw(card: dict, variant: dict) -> dict:
    """The DescribePublicCard shape (NativePublicObservation.cs) of a fresh deck card."""
    keywords = sorted(variant["keywords"])
    x_cost = bool(variant["xCost"])
    return {
        "transportId": "audit", "modelId": "CARD." + card["id"], "pile": "deck", "position": None,
        "upgrade": variant["upgrade"], "maxUpgrade": card["maxUpgrade"],
        "type": card["type"], "rarity": card["rarity"], "target": card["target"],
        "costX": x_cost, "cost": -1 if x_cost else variant["cost"],
        "baseCost": variant["cost"], "localCost": variant["cost"], "costModifiers": [],
        "starCostX": bool(variant["starXCost"]), "starCost": variant["starCost"],
        "keywords": keywords, "localKeywords": keywords, "tags": sorted(card["tags"]),
        "replay": 0, "enchantedReplay": 0, "retain": "Retain" in keywords, "exhaustOnNextPlay": False,
        "retainThisTurn": False, "slyThisTurn": False, "dampened": False, "progress": 0,
        "dynamicVars": [{"name": v["name"], "value": v["value"]} for v in variant["vars"]],
        "tinkerRider": 0, "enchantment": None, "affliction": None,
    }


def audit() -> dict:
    from spire_rl import public_obs as po
    from spire_rl.sim import sim
    from parity.semantic import SimulatorCatalog

    registry = json.loads(REGISTRY.read_text())
    native = {card["id"]: card for card in registry["cards"]}
    lock = [row for row in json.loads(LOCK.read_text())["categories"]["CARD"] if row["id"]]
    catalog = po._CATALOG["simCardIds"]
    action_catalog = SimulatorCatalog.from_repo()
    issues, exceptions, compared = [], [], 0

    def issue(card, field, simulator, native_value):
        key = (card, field.split(".")[-1])
        record = {"card": card, "field": field, "simulator": simulator, "native": native_value}
        if key in EXCEPTIONS:
            exceptions.append(dict(record, reason=EXCEPTIONS[key]))
        else:
            issues.append(record)

    # 1. Identity: simulator enum -> native model ID, one-to-one.
    mapped = {}
    for row in lock:
        sim_key = "CARD." + row["key"]
        model = catalog.get(sim_key, "<missing>")
        if row["key"] == "GRAPPLE":  # reserved legacy slot, never generated
            if model is not None or sim.card_native_available(row["id"]):
                issue("GRAPPLE", "identity.reserved_slot", model, None)
            continue
        if model in (None, "<missing>"):
            issue(row["key"], "identity.mapping", model, "a native card")
            continue
        native_id = model.removeprefix("CARD.")
        if native_id not in native:
            issue(row["key"], "identity.native_exists", native_id, "registered card")
        if row["native_ids"] != [model]:
            issue(row["key"], "identity.lock", row["native_ids"], [model])
        if action_catalog.card(row["id"]) != native_id:  # action keys use this table
            issue(row["key"], "identity.action_key", action_catalog.card(row["id"]), native_id)
        mapped.setdefault(native_id, []).append(row["key"])
    for native_id in native:
        sources = mapped.get(native_id, [])
        if native_id == "DEPRECATED_CARD":  # native save-compatibility fallback only
            if sources:
                issue(native_id, "identity.deprecated_fallback", sources, [])
            continue
        if len(sources) != 1:
            issue(native_id, "identity.one_to_one", sources, "exactly one simulator card")

    # 2. Public facts and encoded rows for every card and upgrade level.
    by_native = {native_id: next(r for r in lock if r["key"] == keys[0])
                 for native_id, keys in mapped.items() if len(keys) == 1}
    for native_id, row in sorted(by_native.items()):
        card = native[native_id]
        if native_id in UNAVAILABLE:
            exceptions.append({"card": native_id, "field": "all", "reason": UNAVAILABLE[native_id]})
            continue
        for upgraded in sorted({min(1, card["maxUpgrade"]), 0}):
            variant = card["variants"][upgraded]
            label = f"{native_id}{'+' if upgraded else ''}"
            view = sim.public_card_template(row["id"], bool(upgraded))
            try:
                sim_card = po._card(view, "simulator", "simulator." + label)
                nat_card = po._card(native_raw(card, variant), "native", "native." + label)
            except po.ObservationCoverageError as exc:
                issue(label, "coverage", str(exc), "encodable")
                continue
            for field in sorted(set(sim_card) | set(nat_card)):
                if sim_card.get(field, "<missing>") != nat_card.get(field, "<missing>"):
                    issue(label, "facts." + field, sim_card.get(field, "<missing>"),
                          nat_card.get(field, "<missing>"))
            sim_row = np.zeros(po.NUM, np.float32); nat_row = np.zeros(po.NUM, np.float32)
            po._fill_card_row(sim_card, sim_row); po._fill_card_row(nat_card, nat_row)
            differing = [int(i) for i in np.nonzero(sim_row != nat_row)[0]]
            if differing:
                issue(label, "encoded_row", differing, "identical")
            # Executed numbers: the C++ card's printed Damage/Block vs the DLL value.
            variables = {v["name"]: v["value"] for v in variant["vars"]}
            for name, field in (("Damage", "damage"), ("Block", "block")):
                if name in variables and view[field] != variables[name]:
                    issue(label, "executed." + name, view[field], variables[name])
            compared += 1
    return {"schema": "sts2.card-encoding-audit/1", "ruleset": str(sim.ENGINE_RULESET_ID),
            "native_cards": len(native), "compared_variants": compared,
            "issues": issues, "exceptions": exceptions,
            "status": "pass" if not issues else "differences"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    report = audit()
    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(f"{report['status']}: {report['compared_variants']} card variants, "
          f"{len(report['issues'])} issues, {len(report['exceptions'])} documented exceptions")
    for item in report["issues"][:60]:
        print("  ", item)
    return 0 if not report["issues"] else 1


if __name__ == "__main__":
    sys.exit(main())
