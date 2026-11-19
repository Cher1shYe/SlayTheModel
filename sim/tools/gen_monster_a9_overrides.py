"""Extract direct DeadlyEnemies damage values from the decompiled C# models.

Only literal AscensionHelper properties used directly in an unambiguous attack
intent are emitted. Other expressions and move effects need separate auditing.
"""
import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROP = re.compile(
    r"\bint\s+(\w+)\s*=>\s*AscensionHelper\.GetValueIfAscension"
    r"\(\s*AscensionLevel\.DeadlyEnemies\s*,\s*(\d+)\s*,\s*(\d+)\s*\)"
)
MOVE = re.compile(r'new\s+MoveState\s*\(\s*"([^"]+)"')
ATTACK = re.compile(r"new\s+(?:SingleAttackIntent|MultiAttackIntent|DeathBlowIntent)\s*\(\s*(?:\(\s*\)\s*=>\s*)?(\w+)")
MULTI = re.compile(r"new\s+MultiAttackIntent\s*\(\s*\w+\s*,\s*(\w+)\s*\)")


def expression(text, opening):
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening, len(text)):
        c = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[opening:index + 1]
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompiled", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "content/monsters_a9_damage.json")
    parser.add_argument("--hits-out", type=Path, default=ROOT / "content/monsters_a9_hits.json")
    args = parser.parse_args()
    monsters = json.loads((ROOT / "content/monsters.json").read_text(encoding="utf-8"))["monsters"]
    overrides = {}
    hit_overrides = {}
    for path in sorted((args.decompiled / "MegaCrit.Sts2.Core.Models.Monsters").glob("*.cs")):
        mid = re.sub(r"(?<!^)(?=[A-Z])", "_", path.stem).upper()
        if mid not in monsters:
            continue
        text = path.read_text(encoding="utf-8")
        properties = {name: int(high) for name, high, low in PROP.findall(text) if high != low}
        for match in MOVE.finditer(text):
            name = match.group(1)
            if mid == "FAKE_MERCHANT_MONSTER" and name in ("SWIPE_MOVE", "THROW_RELIC_MOVE"):
                name = name.removesuffix("_MOVE")
            state = monsters[mid].get("states8", {}).get(name)
            if not state or state.get("kind") != "move":
                continue
            attacks = [intent for intent in state.get("intents", [])
                       if intent["type"] in ("ATTACK", "MULTI_ATTACK", "DEATH_BLOW")]
            expr = expression(text, text.find("(", match.start()))
            properties_used = ATTACK.findall(expr)
            if len(attacks) != 1 or len(properties_used) != 1:
                continue
            prop = properties_used[0]
            if prop in properties:
                overrides.setdefault(mid, {})[name] = properties[prop]
            multi = MULTI.findall(expr)
            if len(multi) == 1 and multi[0] in properties:
                hit_overrides.setdefault(mid, {})[name] = properties[multi[0]]
    args.out.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.hits_out.write_text(json.dumps(hit_overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {sum(map(len, overrides.values()))} A9 intent overrides for {len(overrides)} monsters")
    print(f"wrote {sum(map(len, hit_overrides.values()))} A9 hit-count overrides")


if __name__ == "__main__":
    main()
