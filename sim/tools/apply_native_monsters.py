"""Bring content/monsters.json in line with the native v0.111.0 source for monster HP ranges
and fixed encounter rosters, then regenerate the C++ tables with gen_monsters.py.

The monster data was originally exported from a third-party Python re-implementation
(dump_monsters.py; HP was "sampled_only"). The 2026-11-18 audit found 24 monsters whose HP
range differs from native and 7 fixed encounter rosters that differ (docs/DEVLOG.md
section 7). This tool reads the native source directly:

* HP: ``MinInitialHp`` / ``MaxInitialHp`` of each Models/Monsters/<Name>.cs, either a constant
  or ``AscensionHelper.GetValueIfAscension(AscensionLevel.ToughEnemies, <A8+>, <A0-7>)``
  (``MaxInitialHp => MinInitialHp`` and Axebot's ``+ RespawnMaxHpBonus``, zero at spawn,
  are handled). Monsters with no native class keep their values and are listed.
* Rosters: fixed encounters whose native ``GenerateMonsters`` list differs (listed below,
  each checked by hand against the native file). Encounters whose roster is random in
  native are generated in C++ (monsters.cpp, ``native_roster``); their JSON patterns only
  list the possible monsters for the generator's tables.

Usage: python sim/tools/apply_native_monsters.py [--native <.../MegaCrit/sts2/Core>]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SRC = ROOT / "content" / "monsters.json"
DEFAULT_NATIVE = REPO / "artifacts" / "native-source" / "v0.111.0" / "MegaCrit" / "sts2" / "Core"

# Fixed rosters that differ from native GenerateMonsters (native order = creation order).
NATIVE_FIXED_ROSTERS = {
    "setup_axebots_normal": ["AXEBOT"],                                     # AxebotsNormal.cs
    "setup_exoskeletons_normal": ["EXOSKELETON"] * 4,                       # ExoskeletonsNormal.cs
    "setup_exoskeletons_weak": ["EXOSKELETON"] * 3,                         # ExoskeletonsWeak.cs
    "setup_gremlin_merc_normal": ["GREMLIN_MERC"],                          # GremlinMercNormal.cs (others spawn on its death)
    "setup_slumbering_beetle_normal": ["BOWLBUG_ROCK", "BOWLBUG_SILK", "SLUMBERING_BEETLE"],
    "setup_tunneler_normal": ["CHOMPER", "TUNNELER"],                       # TunnelerNormal.cs (Chomper.ScreamFirst)
}
# Random in native: the table keeps one pattern listing creation slots; C++ picks the monsters.
NATIVE_RANDOM_PLACEHOLDER = {
    "setup_slimes_weak": ["LEAF_SLIME_S", "LEAF_SLIME_M", "TWIG_SLIME_S"],
    "setup_slimes_normal": ["TWIG_SLIME_M", "LEAF_SLIME_M", "LEAF_SLIME_S", "TWIG_SLIME_S"],
    "setup_bowlbugs_weak": ["BOWLBUG_ROCK", "BOWLBUG_EGG"],
    "setup_bowlbugs_normal": ["BOWLBUG_ROCK", "BOWLBUG_EGG", "BOWLBUG_SILK"],
    "setup_flyconid_normal": ["LEAF_SLIME_M", "FLYCONID"],
    "setup_ruby_raiders_normal": ["AXE_RUBY_RAIDER", "ASSASSIN_RUBY_RAIDER", "BRUTE_RUBY_RAIDER"],
    "setup_slithering_strangler_normal": ["SNAPPING_JAXFRUIT", "SLITHERING_STRANGLER"],
}


def slug(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and name[i - 1].isalnum():
            out.append("_")
        out.append(ch)
    return re.sub(r"[^A-Z0-9_]", "", "".join(out).upper())


def parse_hp(expr: str):
    expr = expr.strip().replace(" + RespawnMaxHpBonus", "")
    m = re.fullmatch(r"AscensionHelper\.GetValueIfAscension\(AscensionLevel\.ToughEnemies,\s*(-?\d+),\s*(-?\d+)\)", expr)
    if m:
        return int(m.group(2)), int(m.group(1))          # (A0-7, A8+)
    if re.fullmatch(r"-?\d+", expr):
        return int(expr), int(expr)
    return None


def native_hp(native: pathlib.Path) -> dict:
    out = {}
    parents = {}
    for f in sorted((native / "Models" / "Monsters").glob("*.cs")):
        s = f.read_text()
        parent = re.search(r"class\s+\w+\s*:\s*(\w+)", s)
        if parent:
            parents[slug(f.stem)] = slug(parent.group(1))
        lo = re.search(r"override int MinInitialHp\s*=>\s*(.*?);", s)
        hi = re.search(r"override int MaxInitialHp\s*=>\s*(.*?);", s)
        if not lo:
            continue
        lo_v = parse_hp(lo.group(1))
        if lo_v is None:                                   # e.g. TestSubject: => FirstFormHp
            ref = re.search(r"int " + re.escape(lo.group(1).strip()) + r"\s*=>\s*(.*?);", s)
            lo_v = parse_hp(ref.group(1)) if ref else None
        hi_v = lo_v if (hi is None or hi.group(1).strip() == "MinInitialHp") else parse_hp(hi.group(1))
        if lo_v is None or hi_v is None:
            print(f"  cannot parse HP of {f.name}: {lo.group(1)!r} / {hi.group(1) if hi else None!r}")
            continue
        out[slug(f.stem)] = {"A0": [lo_v[0], hi_v[0]], "A8": [lo_v[1], hi_v[1]]}
    # Concrete variants can inherit their entire HP declaration. In particular
    # MysteriousKnight inherits FlailKnight's A8+ 108, not its A0 101.
    for _ in range(len(parents)):
        inherited = {key: out[parent] for key, parent in parents.items()
                     if key not in out and parent in out}
        if not inherited:
            break
        out.update(inherited)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", type=pathlib.Path, default=DEFAULT_NATIVE)
    args = ap.parse_args()
    data = json.loads(SRC.read_text())
    hp = native_hp(args.native)
    changed, missing = [], []
    for key, mon in data["monsters"].items():
        native_key = "DECIMILLIPEDE_SEGMENT" if key == "DECIMILLIPEDE_SEGMENT" else key
        if native_key not in hp:
            missing.append(key)
            continue
        if mon["hp"] != hp[native_key]:
            changed.append((key, mon["hp"], hp[native_key]))
        mon["hp"] = hp[native_key]
        mon["hp_source"] = "native-41cef1ea"
    for key, roster in {**NATIVE_FIXED_ROSTERS, **NATIVE_RANDOM_PLACEHOLDER}.items():
        for asc in ("A0", "A8"):
            e = data["encounters"][f"{key}@{asc}"]
            e["rosters"] = [[roster, 1]]
            e["roster_source"] = ("native-41cef1ea" if key in NATIVE_FIXED_ROSTERS
                                  else "native-41cef1ea: random, generated in C++ (monsters.cpp native_roster)")
    SRC.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for key, old, new in changed:
        print(f"  HP {key}: {old} -> {new}")
    print(f"HP changed for {len(changed)} monsters; kept (no native class): {missing}")
    subprocess.run([sys.executable, str(ROOT / "tools" / "gen_monsters.py")], check=True)


if __name__ == "__main__":
    main()
