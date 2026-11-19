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
    parser.add_argument("--decompiled", type=Path,
                        default=ROOT.parent / "artifacts/native-source/v0.111.0")
    parser.add_argument("--out", type=Path, default=ROOT / "content/encounter_tags.json")
    args = parser.parse_args()
    source = json.loads((ROOT / "content/monsters.json").read_text(encoding="utf-8"))["encounters"]
    candidates = (args.decompiled / "MegaCrit/sts2/Core/Models/Encounters",
                  args.decompiled / "Models/Encounters",
                  args.decompiled / "MegaCrit.Sts2.Core.Models.Encounters")
    directory = next((p for p in candidates if p.is_dir()), None)
    if directory is None:
        raise ValueError(f"No native encounter directory under {args.decompiled}")
    classes = {normalized(p.stem): p for p in directory.glob("*.cs")}
    aliases = {"battleworn_dummy_v" + str(i): "BattlewornDummyEventV" + str(i) + "Encounter"
               for i in range(1, 4)}
    retained = {"doormaker_boss", "toadpoles_normal"}
    def declared_tags(path):
        text = path.read_text(encoding="utf-8")
        declaration = re.search(r"override\s+IEnumerable<EncounterTag>\s+Tags\s*=>\s*(.*?);", text, re.S)
        if declaration:
            return sorted(set(re.findall(r"EncounterTag\.(\w+)", declaration.group(1))))
        parent = re.search(r"class\s+\w+\s*:\s*(\w+)", text)
        parent_path = classes.get(normalized(parent.group(1))) if parent else None
        return declared_tags(parent_path) if parent_path else []
    tags = {}
    for key in sorted(source):
        if not key.endswith("@A0"):
            continue
        name = key[:-3]
        short = name.removeprefix("setup_")
        event = aliases.get(short, short + "_event_encounter")
        path = classes.get(normalized(short)) or classes.get(normalized(event))
        if path is None:
            if short in retained:
                continue  # reserved IDs have no active native registration
            raise ValueError(f"No C# encounter matched {name}")
        values = declared_tags(path)
        if values:
            tags[name] = values
    args.out.write_text(json.dumps(tags, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"audited {sum(k.endswith('@A0') for k in source)} encounter slots ({len(retained)} retained non-native); {len(tags)} have tags")


if __name__ == "__main__":
    main()
