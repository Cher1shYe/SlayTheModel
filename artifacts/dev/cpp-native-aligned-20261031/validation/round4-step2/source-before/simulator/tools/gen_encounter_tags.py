"""Extract encounter tags from the local decompiled C# encounter models."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalized(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompiled", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "content/encounter_tags.json")
    args = parser.parse_args()
    source = json.loads((ROOT / "content/monsters.json").read_text(encoding="utf-8"))["encounters"]
    directory = args.decompiled / "MegaCrit.Sts2.Core.Models.Encounters"
    classes = {normalized(p.stem): p for p in directory.glob("*.cs")}
    tags = {}
    for key in sorted(source):
        if not key.endswith("@A0"):
            continue
        name = key[:-3]
        short = name.removeprefix("setup_")
        event = re.sub(r"_v[123]$", "", short) + "_event_encounter"
        path = classes.get(normalized(short)) or classes.get(normalized(event))
        if path is None:
            raise ValueError(f"No C# encounter matched {name}")
        text = path.read_text(encoding="utf-8")
        if not re.search(r"class\s+\w+\s*:\s*EncounterModel\b", text):
            raise ValueError(f"Unexpected encounter inheritance: {path}")
        declaration = re.search(r"override\s+IEnumerable<EncounterTag>\s+Tags\s*=>\s*(.*?);", text, re.S)
        values = sorted(set(re.findall(r"EncounterTag\.(\w+)", declaration.group(1)))) if declaration else []
        if values:
            tags[name] = values
    args.out.write_text(json.dumps(tags, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"matched {sum(k.endswith('@A0') for k in source)} encounters; {len(tags)} have tags")


if __name__ == "__main__":
    main()
