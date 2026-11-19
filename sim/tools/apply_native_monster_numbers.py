"""Apply reviewed v14 numeric corrections from immutable DLL getter exports.

Keeps all monster/state IDs and unrelated data. Dynamic DreadDamage is the one
explicit source formula: base 13/15 plus live Dexterity, evaluated in C++.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "sim/native-fixtures/native-monster-numbers-41cef1ea"


def apply(write=False):
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    phases = {}
    for filename, digest in manifest["files"].items():
        raw = (FIXTURES / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("native fixture bytes changed: " + filename)
        native = json.loads(raw)
        for key in ("beforeRun", "run"):
            phase = native[key]
            phases[phase["ascension"]] = {row["id"]: row for row in phase["monsters"]}
    source = ROOT / "sim/content/monsters.json"
    data = json.loads(source.read_text())
    effects_path = ROOT / "sim/content/monsters_a9_effects.json"
    effects = json.loads(effects_path.read_text())
    damage_path = ROOT / "sim/content/monsters_a9_damage.json"
    damage = json.loads(damage_path.read_text())
    changes = []
    bindings = [
        ("CRUSHER", "ADAPT_MOVE", ["power", "S", "STRENGTH"], "Crusher.AdaptStrengthGain"),
        ("ROCKET", "CHARGE_UP_MOVE", ["power", "S", "STRENGTH"], "Rocket.ChargeUpStrengthGain"),
        ("LOUSE_PROGENITOR", "CURL_AND_GROW_MOVE", ["power", "S", "STRENGTH"], "LouseProgenitor.GrowStrength"),
        ("NIBBIT", "HISS_MOVE", ["power", "S", "STRENGTH"], "Nibbit.HissStrengthGain"),
        ("NIBBIT", "SLICE_MOVE", ["block"], "Nibbit.SliceBlock"),
        ("WATERFALL_GIANT", "SIPHON_MOVE", ["heal"], "WaterfallGiant.SiphonHeal"),
    ]
    for monster, move, prefix, member in bindings:
        for ascension, tag in ((0, "A0"), (8, "A8")):
            ops = data["monsters"][monster]["moves"][move + "@" + tag]
            indices = [i for i, op in enumerate(ops) if op[:-1] == prefix]
            if len(indices) != 1:
                raise ValueError(f"ambiguous op {monster}.{move}: {prefix}")
            index = indices[0]
            value = phases[ascension][monster]["members"][member]
            if type(value) is not int:
                raise ValueError(f"unreadable native getter {member}")
            if ops[index][-1] != value:
                changes.append({"monster": monster, "move": move, "ascension": ascension,
                                "before": ops[index][-1], "after": value, "native_member": member})
                ops[index][-1] = value
            if ascension == 8:
                high = phases[9][monster]["members"][member]
                if high != value:
                    row = effects["moves"].setdefault(monster, {}).setdefault(move, {})
                    if row.get(str(index)) != high:
                        changes.append({"monster": monster, "move": move, "ascension": 9,
                                        "before": row.get(str(index), value), "after": high, "native_member": member})
                    row[str(index)] = high
    native_source = ROOT / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models/Monsters/TheForgotten.cs"
    text = native_source.read_text()
    formula = re.search(r"int valueIfAscension = AscensionHelper.GetValueIfAscension\(AscensionLevel.DeadlyEnemies, (\d+), (\d+)\);\s*return valueIfAscension \+ base.Creature.GetPowerAmount<DexterityPower>\(\);", text)
    if not formula:
        raise ValueError("TheForgotten reviewed source formula changed")
    high, low = map(int, formula.groups())
    for key in ("states", "states8"):
        for intent in data["monsters"]["THE_FORGOTTEN"][key]["DREAD"]["intents"]:
            if intent["type"] == "ATTACK" and intent["damage"] != low:
                changes.append({"monster": "THE_FORGOTTEN", "field": key + ".DREAD.base_damage", "before": intent["damage"], "after": low, "evidence": "source formula; live Dexterity added by move_attack_damage"})
                intent["damage"] = low
    if damage["THE_FORGOTTEN"]["DREAD"] != high:
        changes.append({"monster": "THE_FORGOTTEN", "field": "A9.DREAD.base_damage", "before": damage["THE_FORGOTTEN"]["DREAD"], "after": high})
        damage["THE_FORGOTTEN"]["DREAD"] = high
    # This is only the initial value; actual Pressure Gun grows by five per use.
    pressure = phases[9]["WATERFALL_GIANT"]["members"]["WaterfallGiant.BasePressureGunDamage"]
    row = damage.setdefault("WATERFALL_GIANT", {})
    if row.get("PRESSURE_GUN_MOVE") != pressure:
        changes.append({"monster": "WATERFALL_GIANT", "field": "A9.PRESSURE_GUN_MOVE.base_damage",
                        "before": row.get("PRESSURE_GUN_MOVE", 20), "after": pressure})
        row["PRESSURE_GUN_MOVE"] = pressure
    if write:
        for path, value in ((source, data), (effects_path, effects), (damage_path, damage)):
            path.write_text(json.dumps(value, indent=2) + "\n")
        subprocess.run([sys.executable, str(ROOT / "sim/tools/gen_monsters.py")], check=True)
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply(args.apply), indent=2))
