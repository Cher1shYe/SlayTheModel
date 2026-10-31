"""Extract source-exact act fixtures from the local native 41cef1ea decompile.

This does not execute the game or establish end-to-end simulation parity.
"""
from pathlib import Path
import hashlib
import json
import re

DEV = Path(__file__).resolve().parents[1]
CORE = DEV.parents[2] / "artifacts/native-source/v0.111.0/MegaCrit/sts2/Core"
FILES = ["Map/GoldenPathActMap.cs", "Models/Relics/GoldenCompass.cs",
         "Odds/UnknownMapPointOdds.cs", "Models/ActModel.cs"]
FILES += [f"Models/Acts/{name}.cs" for name in ["Overgrowth", "Underdocks", "Hive", "Glory"]]
texts = {name: (CORE / name).read_text() for name in FILES}
golden = texts["Map/GoldenPathActMap.cs"].split("_defaultPointTypes", 1)[1].split("};", 1)[0]
bosses = {}
for name in ["Overgrowth", "Underdocks", "Hive", "Glory"]:
    section = texts[f"Models/Acts/{name}.cs"].split("BossDiscoveryOrder", 1)[1].split("});", 1)[0]
    bosses[name] = re.findall(r"ModelDb\.Encounter<(\w+)>\(\)", section)
under = texts["Models/Acts/Underdocks.cs"].split("GenerateAllEncounters", 1)[1].split("});", 1)[0]
fixture = {
    "provenance": {
        "kind": "source-exact (not a dynamic full-run oracle)",
        "native_release_commit": "41cef1ea",
        "native_dll_sha256": "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4",
        "source_sha256": {name: hashlib.sha256((CORE / name).read_bytes()).hexdigest() for name in FILES},
    },
    "golden_path_rooms": re.findall(r"MapPointType\.(\w+)", golden),
    "boss_discovery_order": bosses,
    "underdocks_encounters": re.findall(r"ModelDb\.Encounter<(\w+)>\(\)", under),
    "golden_unknown_roll": {"consumes_next_float": True, "result": "Event", "changes_non_event_odds": False},
    "first_run_unknowns": ["Event", "Event", "Monster"],
}
out = DEV / "simulator/tests/fixtures/native_act_41cef1ea.json"
out.write_text(json.dumps(fixture, indent=2) + "\n")
print(out)
