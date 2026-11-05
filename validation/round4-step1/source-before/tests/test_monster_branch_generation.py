import json
import re
from pathlib import Path


def test_generated_monster_branches_match_source_fields():
    root = Path(__file__).resolve().parents[1] / "simulator"
    source = json.loads((root / "content/monsters.json").read_text(encoding="utf-8"))
    generated = (root / "include/sts2/monsters_generated.inc").read_text(encoding="utf-8")
    table = generated.split("constexpr MonBranchDef MON_BRANCHES[] = {", 1)[1].split("};", 1)[0]
    actual = [tuple(map(int, match)) for match in re.findall(
        r"\{(\d+), (\d+), (\d+), (\d+), (\d+)\}", table
    )]
    repeats = {"CAN_REPEAT_FOREVER": 0, "CANNOT_REPEAT": 1,
               "CAN_REPEAT_X_TIMES": 2, "USE_ONLY_ONCE": 3}
    expected = []
    for monster_id in sorted(source["monsters"]):
        states = source["monsters"][monster_id]["states"]
        indexes = {name: index for index, name in enumerate(states)}
        for state in states.values():
            if state["kind"] != "random":
                continue
            for branch in state["branches"]:
                expected.append((indexes.get(branch["state"], 0),
                                 repeats.get(branch["repeat"], 0),
                                 int(branch["max"]), int(branch["cooldown"]),
                                 round(float(branch["weight"]) * 10)))
    assert expected
    assert actual == expected
