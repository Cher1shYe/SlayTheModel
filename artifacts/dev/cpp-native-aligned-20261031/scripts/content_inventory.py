"""Fresh content inventory for the C++ port.

Parses the generated content tables and cross-references the port sources and
tests.  Outputs Markdown (docs/content-inventory-20261104.md) plus a JSON
summary.  Counts come from the current source tree, not from older reports.

Evidence levels recorded here:
  * data      - entry present in simulator/include/sts2/*_generated.inc
  * effect    - the id is referenced by a port source file (effect dispatch,
                hook table, acquisition path)
  * tested    - the id/name is referenced by an automated test in
                simulator/tests or artifacts tests
This is a coverage map, not a native-differential result.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "simulator"
DOCS = ROOT / "docs"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_cards(text: str):
    out = []
    for m in re.finditer(r'\{CardId::([A-Z0-9_]+),\s*"([^"]*)",\s*"([^"]*)",\s*CardPool::([A-Z]+),'
                         r'\s*(-?\d+),\s*(-?\d+),\s*CardType::([A-Z]+),\s*TargetType::([A-Z_]+),'
                         r'\s*Rarity::([A-Z]+),[^}]*\},\s*\{[^}]*\},\s*(\d+),\s*(\d+),', text):
        out.append(dict(id=m.group(1), key=m.group(2), name=m.group(3), pool=m.group(4),
                        cost=int(m.group(5)), type=m.group(7), target=m.group(8),
                        rarity=m.group(9), flags=int(m.group(10))))
    return out


def parse_potions(text: str):
    out = []
    for m in re.finditer(r'\{PotionId::([A-Z0-9_]+),\s*"([^"]*)",\s*"([^"]*)",\s*Rarity::([A-Z]+),'
                         r'\s*PotionUsage::([A-Z_]+),\s*PotionTarget::([A-Z_]+),', text):
        out.append(dict(id=m.group(1), key=m.group(2), name=m.group(3),
                        rarity=m.group(4), usage=m.group(5), target=m.group(6)))
    return out


def parse_relics(text: str):
    out = []
    for m in re.finditer(r'\{RelicId::([A-Z0-9_]+),\s*"([^"]*)",\s*"([^"]*)",\s*Rarity::([A-Z]+),'
                         r'\s*RelicPool::([A-Z]+),\s*(true|false)\}', text):
        out.append(dict(id=m.group(1), key=m.group(2), name=m.group(3),
                        rarity=m.group(4), pool=m.group(5), implemented=m.group(6) == "true"))
    return out


def reference_index(prefix: str):
    refs = {}
    for path in list(SIM.glob("src/*.cpp")) + list(SIM.glob("tests/*.cpp")) + \
            list(ROOT.glob("tests/*.py")):
        text = read(path)
        for m in re.finditer(re.escape(prefix) + r"::([A-Z0-9_]+)", text):
            refs.setdefault(m.group(1), set()).add(path.name)
        # Python tests usually refer to display names, handled separately.
    return refs


def name_refs(names):
    hits = {}
    for path in list(SIM.glob("tests/*.cpp")) + list(ROOT.glob("tests/*.py")):
        text = read(path)
        for ident, name in names.items():
            if name and (name in text or f'"{name}"' in text):
                hits.setdefault(ident, set()).add(path.name)
    return hits


CARD_FLAG = {"MULTIPLAYER_ONLY": 128, "UNPLAYABLE": 16, "CANNOT_GENERATE": 256,
             "ETHEREAL": 1, "EXHAUST": 2, "INNATE": 4, "RETAIN": 8,
             "ETERNAL": 1024}


def main() -> int:
    cards = parse_cards(read(SIM / "include/sts2/cards_generated.inc"))
    potions = parse_potions(read(SIM / "include/sts2/potions_generated.inc"))
    relics = parse_relics(read(SIM / "include/sts2/relics_generated.inc"))
    card_refs = reference_index("CardId")
    potion_refs = reference_index("PotionId")
    relic_refs = reference_index("RelicId")
    card_name_hits = name_refs({c["id"]: c["name"] for c in cards})

    effect_files = {"cards.cpp", "cards_colorless.cpp", "cards_defect.cpp",
                    "cards_ironclad.cpp", "cards_necrobinder.cpp", "cards_regent.cpp",
                    "cards_silent.cpp", "cards_status.cpp", "battle.cpp",
                    "battle_flow.cpp", "battle_turns.cpp", "battle_damage.cpp",
                    "battle_powers.cpp", "potions.cpp", "defect.cpp", "necrobinder.cpp",
                    "regent.cpp", "silent.cpp", "relics.cpp", "relic_lifecycle.cpp",
                    "relic_persistent.cpp", "run.cpp", "events.cpp",
                    "relic_card_rewards.cpp"}

    cpp_tests = {p.name for p in SIM.glob("tests/*.cpp")}
    py_tests = {p.name for p in ROOT.glob("tests/*.py")}
    for c in cards:
        f = card_refs.get(c["id"], set())
        c["effect_files"] = sorted(f & effect_files)
        c["data"] = True
        # Intersect with both suites separately: the previous `a & b | c`
        # prececedence made every card "tested" by every Python file.
        seen = card_name_hits.get(c["id"], set()) | f
        c["tested"] = sorted((seen & cpp_tests) | (seen & py_tests))
    for p in potions:
        f = potion_refs.get(p["id"], set())
        p["effect_files"] = sorted(f & effect_files)
        p["tested"] = sorted({q.name for q in SIM.glob("tests/*.cpp")} & f) + \
            sorted({q.name for q in ROOT.glob("tests/*.py")} & f)
    for r in relics:
        f = relic_refs.get(r["id"], set())
        r["effect_files"] = sorted(f & effect_files)
        r["tested"] = sorted((f) & ({q.name for q in SIM.glob("tests/*.cpp")} |
                                    {q.name for q in ROOT.glob("tests/*.py")}))

    untested_cards = [c for c in cards if not c["tested"]]
    no_effect_cards = [c for c in cards if not c["effect_files"]]
    untested_potions = [p for p in potions if not p["tested"]]
    no_effect_potions = [p for p in potions if not p["effect_files"]]
    untested_relics = [r for r in relics if not r["tested"]]
    no_effect_relics = [r for r in relics if not r["effect_files"]]

    lines = ["# Content inventory (generated " + "2026-11-04" + ")", "",
             "Ruleset `native-41cef1ea-port-v10`; source = current tree. "
             "Reference game build on this machine: local DLL sha256 `0861bfa1...` "
             "(target `9cb4f1ad...` unavailable). Evidence is port self-test "
             "coverage, not native differential.", ""]
    for kind, items in (("cards", cards), ("potions", potions), ("relics", relics)):
        lines.append(f"## {kind}: {len(items)} entries")
        lines.append(f"- no source-effect reference: {len(no_effect_cards if kind=='cards' else no_effect_potions if kind=='potions' else no_effect_relics)}")
        lines.append(f"- no automated test reference: {len(untested_cards if kind=='cards' else untested_potions if kind=='potions' else untested_relics)}")
        lines.append("")

    def table(title, items, cols, fmt):
        lines.append(f"### {title}")
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * len(cols))
        for it in items:
            lines.append("| " + " | ".join(fmt(it)) + " |")
        lines.append("")

    for pool in ("IRONCLAD", "SILENT", "DEFECT", "REGENT", "NECROBINDER", "COLORLESS",
                 "EVENT", "CURSE", "STATUS", "TOKEN", "QUEST"):
        group = [c for c in cards if c["pool"] == pool]
        if not group:
            continue
        table(f"{pool} cards ({len(group)})", group,
              ["id", "name", "type", "rarity", "flags", "effect files", "tests"],
              lambda c: [c["id"], c["name"], c["type"], c["rarity"],
                         ",".join(k for k, v in CARD_FLAG.items() if c["flags"] & v) or "-",
                         ",".join(c["effect_files"]) or "-",
                         ",".join(c["tested"]) or "-"])
    table(f"potions ({len(potions)})", potions,
          ["id", "name", "rarity", "usage", "target", "effect files", "tests"],
          lambda p: [p["id"], p["name"], p["rarity"], p["usage"], p["target"],
                     ",".join(p["effect_files"]) or "-", ",".join(p["tested"]) or "-"])
    table(f"relics ({len(relics)})", relics,
          ["id", "name", "rarity", "pool", "effect files", "tests"],
          lambda r: [r["id"], r["name"], r["rarity"], r["pool"],
                     ",".join(r["effect_files"]) or "-", ",".join(r["tested"]) or "-"])

    lines.append("## Gaps (no source-effect reference)")
    for label, items in (("cards", no_effect_cards), ("potions", no_effect_potions),
                         ("relics", no_effect_relics)):
        lines.append(f"- {label}: " + (", ".join(x["id"] for x in items) or "none"))
    out = Path(os.environ.get("CONTENT_INVENTORY_OUT", DOCS))
    out.mkdir(parents=True, exist_ok=True)
    (out / "content-inventory-20261104.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "cards": len(cards), "potions": len(potions), "relics": len(relics),
        "cards_no_effect": [c["id"] for c in no_effect_cards],
        "potions_no_effect": [p["id"] for p in no_effect_potions],
        "relics_no_effect": [r["id"] for r in no_effect_relics],
        "cards_untested": len(untested_cards), "potions_untested": len(untested_potions),
        "relics_untested": len(untested_relics),
        "multiplayer_only": [c["id"] for c in cards
                             if c["flags"] & CARD_FLAG["MULTIPLAYER_ONLY"]],
        "deprecated": [c["id"] for c in cards if c["id"] == "GRAPPLE"],
    }
    (out / "content-inventory-20261104.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
