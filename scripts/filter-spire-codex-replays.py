#!/usr/bin/env python3
"""Create reproducible candidate lists from the archived Spire Codex replays.

These are header-level filters, not a decision coverage or no-SL audit. The
output manifests refer to existing archived files and never copy replay data.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter
from pathlib import Path


CHARACTERS = frozenset({"IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT"})
CORE_MODS = frozenset({"BaseLib", "SpireCodex"})
VERSION = "v1.2.1"
BUILD = "v0.111.0"
STRICT_NAME = "current-build-core-standard-solo-complete-no-reload"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def read_header(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        header = json.loads(handle.readline())
    if header.get("t") != "header":
        raise ValueError(f"missing header: {path}")
    return header


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("artifacts/reference/spire-codex/bulk"),
        help="Archive produced by fetch-spire-codex-replays.py",
    )
    args = parser.parse_args()
    archive = args.archive.resolve()
    summary_path = archive / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("kind") == "curated_spire_codex_replays":
            print(f"archive already curated: {summary['replay_count']} replays in {archive}")
            return
    version_dir = archive / VERSION
    rows = [json.loads(line) for line in (version_dir / "manifest.jsonl").open(encoding="utf-8")]
    selected: dict[str, list[dict]] = {
        "original-no-gameplay-mods": [],
        "original-core-mods-only": [],
        "current-build-no-gameplay-mods": [],
        "current-build-core-mods-only": [],
        STRICT_NAME: [],
    }
    stages = Counter()
    by_build = Counter()
    by_role = Counter()
    for row in rows:
        if row.get("mod_version") != VERSION:
            raise ValueError(f"unexpected recorder version: {row.get('run_hash')}")
        stages["recorder_version"] += 1
        group = row["character"] if row["character"] in CHARACTERS else "OTHER"
        archive_file = row.get("archive_file", row["run_hash"] + ".ndjson")
        relative_path = Path(VERSION) / group / archive_file
        header = read_header(archive / relative_path)
        if any(header.get(key) != row.get(key) for key in ("mod_version", "character", "build_id")):
            raise ValueError(f"header/manifest mismatch: {row['run_hash']}")
        mods = header.get("mods")
        if not isinstance(mods, list) or not all(
            isinstance(mod, dict)
            and isinstance(mod.get("id"), str)
            and isinstance(mod.get("affects_gameplay"), bool)
            for mod in mods
        ):
            raise ValueError(f"unknown loaded mod list: {row['run_hash']}")
        mod_ids = sorted({mod["id"] for mod in mods})
        gameplay_mod_ids = sorted({mod["id"] for mod in mods if mod["affects_gameplay"]})
        output_row = {
            **row,
            "archive_path": str(relative_path),
            "loaded_mod_ids": mod_ids,
            "declared_gameplay_mod_ids": gameplay_mod_ids,
            "game_mode": header.get("game_mode"),
            "modifiers": header.get("modifiers"),
            "player_count": header.get("player_count"),
            "reloads": header.get("reloads"),
        }
        if group == "OTHER":
            continue
        stages["original_roles"] += 1
        by_build[row["build_id"]] += 1
        by_role[row["character"]] += 1
        no_gameplay = not gameplay_mod_ids
        core_only = set(mod_ids) == CORE_MODS
        current = row["build_id"] == BUILD
        strict = (
            core_only
            and current
            and row.get("capture_status") == "complete"
            and header.get("game_mode") == "standard"
            and header.get("modifiers") == []
            and header.get("player_count") == 1
            and header.get("reloads") == 0
        )
        if no_gameplay:
            stages["original_no_gameplay_mods"] += 1
            selected["original-no-gameplay-mods"].append(output_row)
        if core_only:
            stages["original_core_mods_only"] += 1
            selected["original-core-mods-only"].append(output_row)
        if no_gameplay and current:
            stages["current_build_no_gameplay_mods"] += 1
            selected["current-build-no-gameplay-mods"].append(output_row)
        if core_only and current:
            stages["current_build_core_mods_only"] += 1
            selected["current-build-core-mods-only"].append(output_row)
        if strict:
            stages["current_build_core_standard_solo_complete_no_reload"] += 1
            selected[STRICT_NAME].append(output_row)

    output = version_dir / "filtered"
    for name, matches in selected.items():
        write_jsonl(output / f"{name}.jsonl", matches)
    strict_by_character = {
        character: [row for row in selected[STRICT_NAME] if row["character"] == character]
        for character in sorted(CHARACTERS)
    }
    for character, matches in strict_by_character.items():
        write_jsonl(output / "strict-by-character" / character / "manifest.jsonl", matches)
    if sum(map(len, strict_by_character.values())) != len(selected[STRICT_NAME]):
        raise AssertionError("strict role partition does not match total")
    archive_summary = json.loads((archive / "summary.json").read_text(encoding="utf-8"))
    summary = {
        "catalog_size": archive_summary["catalog_size"],
        "downloaded_valid": archive_summary["downloaded"],
        "target_mod_version": VERSION,
        "target_game_build": BUILD,
        "stages": dict(stages),
        "original_roles_by_build": dict(by_build),
        "original_roles_by_character": dict(by_role),
        "strict_by_character": {character: len(matches) for character, matches in strict_by_character.items()},
        "manifests": {name: {"count": len(matches), "file": name + ".jsonl"} for name, matches in selected.items()},
        "limits": [
            "affects_gameplay is declared by each mod and is not independently verified",
            "complete means recorder ended normally, not that every decision was captured",
            "header filters do not certify no-SL observations or training readiness",
        ],
    }
    summary_path = output / "summary.json"
    temporary = summary_path.with_name(f".{summary_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
