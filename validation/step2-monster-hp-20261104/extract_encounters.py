"""Compare sampled encounter rosters with decompiled GenerateMonsters bodies.

Read-only audit helper.  For deterministic encounters (no `base.Rng` in
GenerateMonsters) the ModelDb.Monster<...>() order is the native roster and is
compared with every sampled roster in content/monsters.json.  Random
encounters are listed with their RNG call sites for manual mapping.

Usage: python -I extract_encounters.py <decompiled.cs> <monsters.json>
"""
from __future__ import annotations

import json
import re
import sys


def class_blocks(src: str):
    pat = re.compile(r"^(\t)public (?:sealed |abstract |static |partial )*class (\w+)(?:<[^>]*>)? : ([\w.]+)", re.M)
    for m in pat.finditer(src):
        i = src.index("{", m.end())
        depth = 0
        j = i
        while j < len(src):
            c = src[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        yield m.group(2), m.group(3), src[m.start():j + 1]


def camel_to_snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.upper()


def generate_body(body: str) -> str | None:
    m = re.search(r"GenerateMonsters\(\)\s*\{", body)
    if not m:
        return None
    i = body.index("{", m.end() - 1)
    depth = 0
    j = i
    while j < len(body):
        c = body[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return body[i + 1:j]


def monsters_in_order(gen: str) -> list[str]:
    return re.findall(r"ModelDb\.Monster<(\w+)>\(\)", gen)


def main() -> None:
    src = open(sys.argv[1], encoding="utf-8-sig").read()
    dm = json.load(open(sys.argv[2], encoding="utf-8"))
    encs = dm["encounters"]
    classes = {name: body for name, _b, body in class_blocks(src)}
    bases = {name: b for name, b, _body in class_blocks(src)}

    def is_enc(c):
        seen = set()
        while c and c not in seen:
            seen.add(c)
            if c == "EncounterModel":
                return True
            c = bases.get(c)
        return False

    # setup key -> class through slug normalization
    def norm(s):
        return "_".join(x for x in s.split("_") if x not in ("EVENT", "ENCOUNTER"))

    bynorm = {}
    for name in classes:
        if is_enc(name) and name != "EncounterModel":
            bynorm.setdefault(norm(camel_to_snake(name)), name)

    keys = sorted({k[:-3] for k in encs if k.endswith("@A0")})
    for key in keys:
        cname = bynorm.get(norm(key.upper().replace("SETUP_", "")))
        if cname is None:
            print(f"{key}: no native class")
            continue
        gen = generate_body(classes[cname])
        if gen is None:
            print(f"{key}: no GenerateMonsters")
            continue
        native = [camel_to_snake(m) for m in monsters_in_order(gen)]
        random = "base.Rng" in gen
        sampled = [r[0] for r in encs[key + "@A0"]["rosters"]]
        ok = all(sorted(r) == sorted(native) for r in sampled) if not random else None
        if random:
            calls = len(re.findall(r"base\.Rng\.(NextItem|NextInt|NextBool|NextFloat)", gen))
            print(f"RANDOM {key}: native_calls={calls} candidates={native} sampled={len(sampled)}")
        elif not ok:
            print(f"MISMATCH {key}: native={native} sampled={sampled}")


if __name__ == "__main__":
    main()
