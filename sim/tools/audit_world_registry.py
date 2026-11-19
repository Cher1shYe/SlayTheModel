"""Read-only registration audit; no combat-effect or whole-run parity claims.

The native DLL registry is preferred. Source fallback deliberately reports its
origin, and includes classes outside ModelDb's normal pools as named exceptions.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re


def slug(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2",
                  re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)).upper()


def entry(value):
    if isinstance(value, dict):
        value = value.get("id", value.get("modelId", ""))
    return str(value).rsplit(".", 1)[-1]


def member(source, name):
    match = re.search(r"\n\t(?:public|private|protected|internal)[^\n=]*\b" + name + r"\b", source)
    if not match:
        return ""
    end = re.search(r"\n\t(?:public|private|protected|internal)\b", source[match.end():])
    return source[match.start():match.end() + end.start()] if end else source[match.start():]


def refs(source, category):
    return [slug(x) for x in re.findall(r"\b" + category + r"<([A-Za-z0-9]+)>\(", source)]


def quoted_array(source, name):
    match = re.search(r"\b" + name + r"\[\]\s*=\s*\{(.*?)\};", source, re.S)
    if not match:
        raise ValueError(f"missing explicit array {name}")
    return re.findall(r'"([^"]+)"', match.group(1))


def result(**counts):
    return {"counts": counts, "checks": [], "differences": [], "exceptions": [], "evidence": []}


def check(out, name, actual, expected):
    out["checks"].append({"name": name, "passed": actual == expected})
    if actual != expected:
        out["differences"].append({"field": name, "simulator": actual, "native": expected})


def _native_source(root):
    core = root / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core"
    models = core / "Models"
    db = (models / "ModelDb.cs").read_text()
    source = {kind: {slug(p.stem): p.read_text() for p in (models / folder).glob("*.cs")}
              for kind, folder in (("events", "Events"), ("monsters", "Monsters"), ("encounters", "Encounters"))}
    acts = []
    for path in sorted((models / "Acts").glob("*.cs")):
        if path.stem not in ("Overgrowth", "Underdocks", "Hive", "Glory"):
            continue
        text = path.read_text()
        encounters = refs(member(text, "GenerateAllEncounters"), "Encounter")
        row = {"id": slug(path.stem), "events": refs(member(text, "AllEvents"), "Event"),
               "ancients": refs(member(text, "AllAncients"), "AncientEvent"),
               "encounters": encounters}
        for kind in ("weak", "normal", "elite", "boss"):
            row[kind] = [x for x in encounters if
                         ("boss" if x.endswith("_BOSS") else "elite" if x.endswith("_ELITE")
                          else "weak" if x.endswith("_WEAK") else "normal") == kind]
        acts.append(row)
    events = [{"id": key, "isAncient": ": AncientEventModel" in text}
              for key, text in source["events"].items()]
    ancients = []
    for row in events:
        if row["isAncient"] and not row["id"].startswith("DEPRECATED_"):
            text = source["events"][row["id"]]
            ancients.append({**row, "possibleRelics": sorted(set(refs(text, "RelicOption") + refs(text, "Relic")))})
    encounters = []
    for key, text in source["encounters"].items():
        if "abstract class" in text:
            continue
        room = re.search(r"RoomType\s*=>\s*RoomType\.(\w+)", text)
        possible = set(refs(text, "Monster"))
        # FabricatorNormal exposes both static summon sets as registry members.
        for owner, field in re.findall(r"\b([A-Z]\w*)\.(\w+Spawns)\b", member(text, "AllPossibleMonsters")):
            owner_source = source["monsters"].get(slug(owner), "")
            possible.update(refs(member(owner_source, field), "Monster"))
        encounters.append({"id": key, "roomType": room.group(1) if room else None,
                           "isWeak": bool(re.search(r"IsWeak\s*=>\s*true", text)),
                           "shouldGiveRewards": not bool(re.search(r"ShouldGiveRewards\s*=>\s*false", text)),
                           "slots": re.findall(r'"([^"]+)"', member(text, "Slots")),
                           "monsters": sorted(possible),
                           "tags": re.findall(r"EncounterTag\.(\w+)", member(text, "Tags"))})
    spec = importlib.util.spec_from_file_location("_audit_native_hp", root / "sim/tools/apply_native_monsters.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hp = module.native_hp(core)
    monsters = []
    for key, text in source["monsters"].items():
        if "abstract class" in text:
            continue
        base = "DECIMILLIPEDE_SEGMENT" if key.startswith("DECIMILLIPEDE_SEGMENT_") else key
        stats = hp.get(base)
        monsters.append({"id": key, "hpA0": stats["A0"] if stats else None,
                         "hpA10": stats["A8"] if stats else None})
    registered = [{"id": category + "." + row["id"]} for category, rows in
                  (("EVENT", events), ("MONSTER", monsters), ("ENCOUNTER", encounters)) for row in rows]
    active_encounters = {x for act in acts for x in act["encounters"]} | set(refs(member(db, "EventEncounters"), "Encounter"))
    encounters = [row for row in encounters if row["id"] in active_encounters]
    active_monsters = {x for row in encounters for x in row["monsters"]}
    monsters = [row for row in monsters if row["id"] in active_monsters]
    return {"events": events, "ancients": ancients, "monsters": monsters, "encounters": encounters,
            "acts": acts, "sharedEvents": refs(member(db, "AllSharedEvents"), "Event"),
            "sharedAncients": refs(member(db, "AllSharedAncients"), "AncientEvent"), "registered": registered}


def audit(root: Path, native: dict | None = None) -> dict:
    root = Path(root)
    oracle = "native_dll_registry" if native is not None else "decompiled_source_fallback"
    native = native if native is not None else _native_source(root)
    event_src = (root / "sim/src/events.cpp").read_text()
    monster_src = (root / "sim/src/monsters.cpp").read_text()
    run_src = (root / "sim/src/run.cpp").read_text()
    binding_src = (root / "sim/bindings/bindings.cpp").read_text()
    generated = (root / "sim/include/sts2/monsters_generated.inc").read_text()
    sim_events = {name: {"status": status, "legacyAct": int(act)} for name, status, act in
                  re.findall(r'\{"([A-Z0-9_]+)", EventStatus::(\w+), (-?\d+)\}', event_src)}
    acts = {entry(row): row for row in native["acts"]}
    sim_event_pools = {key: quoted_array(event_src, key + "_EVENT_ORDER") for key in acts}
    sim_shared = quoted_array(event_src, "SHARED_EVENT_ORDER")
    native_events = set(entry(x) for row in acts.values() for x in row["events"]) | set(map(entry, native["sharedEvents"]))
    native_ancients = {entry(x): x for x in native["ancients"] if not entry(x).startswith("DEPRECATED_")}
    events = result(simulator_slots=len(sim_events), native_active=len(native_events),
                    simulator_active_normal=len(set(sim_events) & native_events))
    for act, row in acts.items():
        check(events, act + ".event_order", sim_event_pools[act], list(map(entry, row["events"])))
    check(events, "shared_event_order", sim_shared, list(map(entry, native["sharedEvents"])))
    check(events, "active_registry_missing", sorted(native_events - sim_events.keys()), [])
    check(events, "active_pool_unsupported", sorted(k for k in native_events & sim_events.keys()
                                                   if sim_events[k]["status"] == "UNSUPPORTED"), [])
    events["exceptions"] = [
        {"id": "AROMA_PLACEHOLDER", "status": "reserved_non_native_inactive", "inActivePool": False},
        {"id": "THE_ARCHITECT", "status": "ending_event_outside_normal_pools_not_registered_in_simulator"},
        {"ids": ["DEPRECATED_EVENT", "DEPRECATED_ANCIENT_EVENT"], "status": "native_save_compatibility_only"},
        {"fields": ["vars", "isShared"], "status": "not_compared", "reason": "simulator has no standalone registry fields; isShared is multiplayer sharing, not cross-act membership"}]
    events["evidence"] = ["sim/src/events.cpp: EVENTS and *_EVENT_ORDER (legacy EventInfo.act is not pool membership)"]

    ancients = result(native_active=len(native_ancients), simulator_active=len(set(sim_events) & native_ancients.keys()))
    check(ancients, "active_registry_missing", sorted(native_ancients.keys() - sim_events.keys()), [])
    pick = event_src.split("int event_pick_ancient(", 1)[1].split("void event_begin", 1)[0]
    branches = re.split(r"\}\s*else(?: if \(rc.act == 1\))?\s*\{", pick)
    sim_ancient_pools = {"OVERGROWTH": re.findall(r"pool\[n\+\+\] = EV_(\w+)", branches[0]),
                         "HIVE": re.findall(r"pool\[n\+\+\] = EV_(\w+)", branches[1]),
                         "GLORY": re.findall(r"pool\[n\+\+\] = EV_(\w+)", branches[2].split("if (rc.act >=", 1)[0])}
    sim_ancient_pools["UNDERDOCKS"] = sim_ancient_pools["OVERGROWTH"]
    for act, row in acts.items():
        check(ancients, act + ".ancient_order", sim_ancient_pools[act], list(map(entry, row["ancients"])))
    check(ancients, "shared_ancients", re.findall(r"sharedAncientInAct\[rc.act\]\) pool\[n\+\+\] = EV_(\w+)", pick), list(map(entry, native["sharedAncients"])))
    generate = event_src.split("void generate_ancient_options(", 1)[1].split("for (int i = 0; i < 3; ++i) rc.eventRelics", 1)[0]
    cases = dict(re.findall(r"case EV_(\w+): \{(.*?)(?=\n        case EV_|\n        default:)", generate, re.S))
    relic_counts = {}
    for key, row in native_ancients.items():
        sim_relics = set(re.findall(r"RelicId::(\w+)", cases[key]))
        if key == "NEOW":
            for name in ("NEOW_CURSES", "NEOW_POSITIVES", "NEOW_EXTRA_OPTIONS"):
                body = re.search(r"\b" + name + r"\[\]\s*=\s*\{(.*?)\};", event_src, re.S).group(1)
                sim_relics.update(re.findall(r"RelicId::(\w+)", body))
        expected = sorted(set(map(entry, row["possibleRelics"])))
        check(ancients, key + ".possible_relics", sorted(sim_relics), expected)
        relic_counts[key] = len(expected)
    ancients["counts"]["possible_relics_by_ancient"] = relic_counts
    ancients["exceptions"] = [{"status": "not_compared", "fields": ["dynamic eligibility", "choice generation weights", "vars", "effects"]}]
    ancients["evidence"] = ["sim/src/events.cpp: event_pick_ancient, event_plan_shared_ancients, generate_ancient_options"]

    sim_hp = {key: {"hpA0": [int(lo0), int(hi0)], "hpA10": [int(lo8), int(hi8)]}
              for key, lo0, lo8, hi0, hi8 in re.findall(r'\{"([A-Z0-9_]+)", \{(\d+), (\d+)\}, \{(\d+), (\d+)\},', generated)}
    monsters = result(simulator_rule_ids=len(sim_hp), native_registry=len(native["monsters"]))
    native_monsters = {entry(x): x for x in native["monsters"]}
    registered_monsters = {entry(x) for x in native.get("registered", [])
                           if str(x.get("id", "")).startswith("MONSTER.")}
    legacy = {"DOOR", "DOORMAKER", "ROYAL_GUARD"}
    aliases = {"DECIMILLIPEDE_SEGMENT_" + suffix: "DECIMILLIPEDE_SEGMENT" for suffix in ("FRONT", "MIDDLE", "BACK")}
    for key, row in native_monsters.items():
        sim_key = aliases.get(key, key)
        if sim_key not in sim_hp:
            continue
        for field in ("hpA0", "hpA10"):
            expected = row.get(field)
            if isinstance(expected, dict):
                expected = [expected.get("min", expected.get("minHp")), expected.get("max", expected.get("maxHp"))]
            check(monsters, key + "." + field, sim_hp[sim_key][field], expected)
    mapped_monsters = (set(sim_hp) - {"DECIMILLIPEDE_SEGMENT"} - legacy) | set(aliases)
    possible = {entry(x) for row in native["encounters"] if not entry(row).startswith(("DEPRECATED_", "MOCK_")) for x in row["monsters"]}
    check(monsters, "encounter_monster_registry_missing", sorted(possible - mapped_monsters), [])
    if oracle == "native_dll_registry":
        check(monsters, "active_monster_registry_missing", sorted(native_monsters.keys() - mapped_monsters), [])
        check(monsters, "unexpected_native_identity", sorted(mapped_monsters - registered_monsters), [])
    monsters["counts"]["mapped_native_ids"] = len(mapped_monsters)
    monsters["counts"]["mapped_active_native_ids"] = len(mapped_monsters & native_monsters.keys())
    monsters["exceptions"] = [
        {"ids": sorted(legacy), "status": "reserved_non_native_inactive"},
        {"ids": sorted(registered_monsters - native_monsters.keys()), "status": "native_classes_outside_ModelDb_Monsters", "reason": "includes Architect ending, pets, deprecated/debug classes and currently unreferenced Adversary variants"},
        {"ids": sorted(mapped_monsters - native_monsters.keys()), "status": "simulator_implemented_native_models_outside_active_monster_registry"},
        {"implementation": "DECIMILLIPEDE_SEGMENT", "nativeAliases": aliases,
         "status": "shared_rules_concrete_identity_by_persistent_slot", "evidence": "DecimillipedeSegmentFront/Middle/Back inherit HP and AI unchanged; only SegmentAttack visual method differs"}]
    check(monsters, "concrete_identity_export", all('return "' + key + '"' in binding_src for key in aliases), True)
    monsters["evidence"] = ["sim/include/sts2/monsters_generated.inc: actual compiled HP table", "sim/bindings/bindings.cpp: native_monster_entry"]

    alias_enc = dict(re.findall(r'case Encounter::(SETUP_\w+): return "(\w+)";', monster_src))
    sim_encs = {key: {"act": int(act), "tags": int(tags)} for key, act, off, count, tags in
                re.findall(r'\{"(SETUP_\w+)", (\d+), (\d+), (\d+), (\d+)\}', generated)}
    native_encs = {entry(x): x for x in native["encounters"]}
    enc_name = lambda key: alias_enc.get(key, key.removeprefix("SETUP_"))
    encounters = result(simulator_slots=len(sim_encs), native_registry=len(native_encs))
    mapped_encounters = {enc_name(k) for k in sim_encs}
    check(encounters, "active_encounter_registry_missing", sorted(native_encs.keys() - mapped_encounters), [])
    encounters["counts"]["mapped_active_native_ids"] = len(native_encs.keys() & mapped_encounters)
    slots = {enc_name(key): re.findall(r'"([^"]+)"', body) for key, body in
             re.findall(r'case Encounter::(SETUP_\w+): return \{(.*?)\};', binding_src)}
    tag_data = json.loads((root / "sim/content/encounter_tags.json").read_text())
    tag_names = sorted({x for tags in tag_data.values() for x in tags})
    for key, row in sim_encs.items():
        name = enc_name(key)
        if name not in native_encs:
            continue
        room_type = "Boss" if "BOSS" in key else "Elite" if "ELITE" in key else "Monster"
        check(encounters, name + ".roomType", room_type, native_encs[name]["roomType"])
        check(encounters, name + ".isWeak", "WEAK" in key, native_encs[name]["isWeak"])
        check(encounters, name + ".slots", slots.get(name, []), native_encs[name]["slots"])
        tags = [tag for i, tag in enumerate(tag_names) if row["tags"] & (1 << i)]
        check(encounters, name + ".tags", tags, sorted(native_encs[name]["tags"]))
    under = re.search(r"underdocksEncounters\[\]\s*=\s*\{(.*?)\};", run_src, re.S).group(1)
    under = re.findall(r"Encounter::(SETUP_\w+)", under)
    excluded = set(re.findall(r"^\s*if \(i == static_cast<int>\(Encounter::(SETUP_\w+)\)\) continue;", run_src, re.M))
    for act, number in (("OVERGROWTH", 1), ("HIVE", 2), ("GLORY", 3), ("UNDERDOCKS", 4)):
        candidates = under if act == "UNDERDOCKS" else list(sim_encs)
        candidates = ["SETUP_AEONGLASS_BOSS" if k == "SETUP_DOORMAKER_BOSS" else k for k in candidates if k != "SETUP_AEONGLASS_BOSS"]
        candidates = [enc_name(k) for k in candidates if sim_encs[k]["act"] == number and k not in excluded]
        for kind in ("weak", "normal", "elite", "boss"):
            actual = [x for x in candidates if ("boss" if "BOSS" in x else "elite" if "ELITE" in x else "weak" if "WEAK" in x else "normal") == kind]
            check(encounters, act + "." + kind + "_order", actual, list(map(entry, acts[act][kind])))
    encounters["exceptions"] = [
        {"ids": ["DOORMAKER_BOSS", "TOADPOLES_NORMAL"], "status": "reserved_non_native_inactive"},
        {"ids": ["TUNNELER_NORMAL"], "status": "native_registered_but_excluded_from_act_pool"},
        {"ids": ["DENSE_VEGETATION_EVENT_ENCOUNTER", "PUNCH_OFF_EVENT_ENCOUNTER", "THE_ARCHITECT_EVENT_ENCOUNTER"], "status": "native_registered_outside_ModelDb_AllEncounters", "reason": "directly created event/ending encounters; not ordinary act pool omissions"},
        {"aliases": alias_enc, "status": "explicit_native_encounter_id_aliases"},
        {"status": "not_compared", "fields": ["generated initial rosters", "summoning effects", "shouldGiveRewards for event routing"], "reason": "AllPossibleMonsters is a registry, not an initial roster"}]
    encounters["evidence"] = ["sim/src/run.cpp: start_act actual ordered pools", "sim/src/monsters.cpp: encounter_native_entry", "sim/bindings/bindings.cpp: native_encounter_slots", "sim/include/sts2/monsters_generated.inc: actual tag masks"]
    out = {"events": events, "ancients": ancients, "monsters": monsters, "encounters": encounters}
    for section in out.values():
        section["oracle"] = oracle
        section["counts"]["checks"] = len(section["checks"])
        section["counts"]["differences"] = len(section["differences"])
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(Path(__file__).resolve().parents[2], json.loads(args.native.read_text()) if args.native else None), indent=2))
