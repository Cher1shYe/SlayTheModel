#!/usr/bin/env python3
"""Print a native model class next to every simulator line that handles it.

For line-by-line audits of relics, cards and potions (DEVLOG 57+): one call shows the
decompiled C# class (boilerplate removed) and each `RelicId::X` / `CardId::X` / `PotionId::X`
use in sim/src and sim/include with its enclosing function and nearby lines.

    python sim/tools/item_side_by_side.py relic AKABEKO [--context 6] [--native-only|--sim-only]
    python sim/tools/item_side_by_side.py card BASH
    python sim/tools/item_side_by_side.py power STRENGTH_POWER   # native Powers/<Class>.cs + PowerId uses
    python sim/tools/item_side_by_side.py list relic             # sim key, native class, pool

Native ids are the registry ids (AKABEKO, CARD.BASH -> BASH); the simulator key comes from
sim/content/registry_identity_lock.json. Needs artifacts/native-source/v0.111.0 locally.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core/Models"
REGISTRY = ROOT / "sim/native-fixtures/native-registry-41cef1ea.json"
LOCK = ROOT / "sim/content/registry_identity_lock.json"
SIM_DIRS = [ROOT / "sim/src", ROOT / "sim/include/sts2", ROOT / "sim/bindings"]
SKIP = re.compile(r"_generated\.inc$|relic_raw_rarity\.h$|native_relic_pools\.inc$|native_potion_pool\.inc$")
KIND = {"relic": ("relics", "RELIC", "Relics", "RelicId"), "card": ("cards", "CARD", "Cards", "CardId"),
        "potion": ("potions", "POTION", "Potions", "PotionId")}
BOILER = re.compile(r"^\s*(using |namespace |\[(CompilerGenerated|DebuggerBrowsable|DebuggerHidden|"
                    r"AsyncStateMachine|DebuggerStepThrough|Nullable|NullableContext)|#)")


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).upper()


def table(kind: str) -> list[dict]:
    reg_key, lock_key, _, _ = KIND[kind]
    reg = {e["id"]: e for e in json.loads(REGISTRY.read_text())[reg_key]}
    lock = json.loads(LOCK.read_text())["categories"][lock_key]
    rows = []
    for e in lock:
        for nid in e["native_ids"]:
            bare = nid.split(".", 1)[1]
            if bare in reg:
                rows.append({"key": e["key"], "native": bare, "class": reg[bare]["className"],
                             "pools": reg[bare].get("poolIds", []), "rarity": reg[bare].get("rarityName", reg[bare].get("rarity")),
                             "vars": reg[bare].get("vars", [])})
    return rows


def find(kind: str, name: str) -> dict:
    name = name.upper()
    for r in table(kind):
        if name in (r["key"], r["native"], r["class"].upper()):
            return r
    raise SystemExit(f"no {kind} named {name}")


def native_source(folder: str, cls: str) -> str:
    path = NATIVE / folder / f"{cls}.cs"
    if not path.exists():
        hits = list(NATIVE.rglob(f"{cls}.cs"))
        if not hits:
            return f"(no native file for {cls})"
        path = hits[0]
    out = [l.rstrip() for l in path.read_text(encoding="utf-8-sig").splitlines() if not BOILER.match(l) and l.strip()]
    return f"// {path.relative_to(ROOT)}\n" + "\n".join(out)


NOISE = {"relic_implemented"}      # plain "is supported" case lists
FUNC = re.compile(r"^(?:static\s+|inline\s+)*[\w:<>,\s\*&]+?\b([\w:]+)\s*\([^;]*\)\s*(?:const\s*)?\{?\s*$")


def sim_uses(token: str, context: int, skip=()) -> str:
    pat = re.compile(rf"\b{re.escape(token)}\b")
    out = []
    for d in SIM_DIRS:
        for path in sorted(list(d.glob("*.cpp")) + list(d.glob("*.h")) + list(d.glob("*.inc"))):
            if SKIP.search(path.name) or path.name in skip:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            hits = [i for i, l in enumerate(lines) if pat.search(l)]
            if not hits:
                continue
            shown = -1
            for i in hits:
                if i <= shown:
                    continue
                func = next((FUNC.match(lines[j]).group(1) for j in range(i, -1, -1)
                             if not lines[j].startswith((" ", "\t", "}", "/", "#")) and FUNC.match(lines[j])), "?")
                if func in NOISE:
                    continue
                lo, hi = max(0, i - context, shown + 1), min(len(lines), i + context + 1)
                out.append(f"--- {path.relative_to(ROOT)}:{i + 1} in {func}")
                out += [f"{k + 1:5d} {lines[k]}" for k in range(lo, hi)]
                shown = hi - 1
    return "\n".join(out) if out else f"(no simulator use of {token})"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["relic", "card", "potion", "power", "list"])
    ap.add_argument("name")
    ap.add_argument("--context", type=int, default=6)
    ap.add_argument("--native-only", action="store_true")
    ap.add_argument("--sim-only", action="store_true")
    ap.add_argument("--skip", default="", help="comma-separated simulator file names to leave out (e.g. card_preview.cpp)")
    a = ap.parse_args(argv)
    if a.kind == "list":
        for r in table(a.name):
            print(f"{r['key']:32s} {r['class']:32s} {r['rarity']!s:10s} {','.join(r['pools'])}")
        return
    if a.kind == "power":
        cls = "".join(w.capitalize() for w in a.name.upper().split("_"))
        if not a.sim_only:
            print(native_source("Powers", cls))
        if not a.native_only:
            print(sim_uses(a.name.upper().removesuffix("_POWER"), a.context))
        return
    r = find(a.kind, a.name)
    print(f"== {a.kind} {r['key']} (native {r['native']}, class {r['class']}, {r['rarity']}, {','.join(r['pools'])})")
    if r["vars"]:
        print("vars: " + ", ".join(f"{v['name']}={v['value']}" for v in r["vars"]))
    if not a.sim_only:
        print(native_source(KIND[a.kind][2], r["class"]))
    if not a.native_only:
        print(f"== simulator uses of {KIND[a.kind][3]}::{r['key']}")
        print(sim_uses(f"{KIND[a.kind][3]}::{r['key']}", a.context, tuple(x for x in a.skip.split(",") if x)))


if __name__ == "__main__":
    sys.exit(main())
