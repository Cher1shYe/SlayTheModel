"""Extract directly verifiable A9 move/power amounts from decompiled C#."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPERTY = re.compile(
    r"\bint\s+(\w+)\s*=>\s*AscensionHelper\.GetValueIfAscension"
    r"\(\s*AscensionLevel\.DeadlyEnemies\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)
MOVE = re.compile(r'new\s+MoveState\s*\(\s*"([^"]+)"\s*,\s*(\w+)\s*,')
METHOD = re.compile(r"\b(?:async\s+)?Task\s+(\w+)\s*\([^)]*\)\s*\{")
POWER = re.compile(r"PowerCmd\.Apply<(\w+)Power>\s*\(\s*(base\.Creature|targets?)\s*,\s*(\w+)\b")
BLOCK = re.compile(r"CreatureCmd\.GainBlock\s*\(\s*base\.Creature\s*,\s*(\w+)\b")


def method_bodies(text):
    result = {}
    for match in METHOD.finditer(text):
        start = match.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{": depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    result[match.group(1)] = text[start:i + 1]
                    break
    return result


def enum_name(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompiled", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "content/monsters_a9_effects.json")
    args = parser.parse_args()
    monsters = json.loads((ROOT / "content/monsters.json").read_text(encoding="utf-8"))["monsters"]
    result = {"moves": {}, "innate": {}}
    directory = args.decompiled / "MegaCrit.Sts2.Core.Models.Monsters"
    for path in sorted(directory.glob("*.cs")):
        mid = enum_name(path.stem)
        if mid not in monsters:
            continue
        text = path.read_text(encoding="utf-8")
        properties = {name: (int(high), int(low)) for name, high, low in PROPERTY.findall(text) if high != low}
        methods = method_bodies(text)
        model = monsters[mid]
        for state, handler in MOVE.findall(text):
            body = methods.get(handler, "")
            ops = model.get("moves", {}).get(state + "@A8", []) or []
            for power, target, prop in POWER.findall(body):
                if prop not in properties:
                    continue
                high, low = properties[prop]
                role = "S" if target == "base.Creature" else "P"
                indexes = [i for i, op in enumerate(ops)
                           if len(op) == 4 and op[:3] == ["power", role, enum_name(power)] and op[3] == low]
                if len(indexes) == 1:
                    result["moves"].setdefault(mid, {}).setdefault(state, {})[str(indexes[0])] = high
            for prop in BLOCK.findall(body):
                if prop not in properties:
                    continue
                high, low = properties[prop]
                indexes = [i for i, op in enumerate(ops) if op == ["block", low]]
                if len(indexes) == 1:
                    result["moves"].setdefault(mid, {}).setdefault(state, {})[str(indexes[0])] = high
        for power, target, prop in POWER.findall(methods.get("AfterAddedToRoom", "")):
            if target != "base.Creature" or prop not in properties:
                continue
            high, low = properties[prop]
            name = enum_name(power)
            if model.get("powers", {}).get("A8", []).count([name, low]) == 1:
                result["innate"].setdefault(mid, {})[name] = high
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    count = sum(len(ops) for states in result["moves"].values() for ops in states.values())
    print(f"wrote {count} move-effect and {sum(map(len, result['innate'].values()))} innate A9 overrides")


if __name__ == "__main__":
    main()
