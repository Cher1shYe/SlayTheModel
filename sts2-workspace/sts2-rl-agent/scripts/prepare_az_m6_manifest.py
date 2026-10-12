"""Freeze balanced three-weak recipes on unused environment seed bands."""
from dataclasses import replace
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.content import M6_CONTENT, PROFILES
from sts2_env.az.scenarios import starter_scenario, balanced_selection, save_manifest


if __name__ == "__main__":
    output = Path("data/az/m6_manifest.json")
    if output.exists():
        raise ValueError("Refusing to overwrite a frozen manifest")
    records = []
    for split, base, count in (("train", 80_000, 256), ("validation", 90_000, 256), ("test", 100_000, 150)):
        candidates = []
        for index, profile in enumerate(PROFILES.values()):
            for i in range((count + 2) // 3):
                r = starter_scenario(base + index * 1000 + i, split=split, hp=40)
                candidates.append(replace(r, scenario_id=f"m6-{split}-{base + index * 1000 + i}",
                                          encounter_id=profile["encounter"], content_manifest_version=M6_CONTENT))
        records.extend(balanced_selection(candidates, count))
    save_manifest(output, records)
    print(f"Saved {len(records)} recipes; test outcomes not evaluated")
