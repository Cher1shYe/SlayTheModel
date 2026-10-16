#!/usr/bin/env python3
"""Build an internal native-replay plan for one Spire Codex combat.

The plan intentionally contains seed, RNG counters, and opening draw order.
It is a reconstruction input and must never be used as a model observation.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path, help="Curated v1.2.1 .ndjson.gz replay")
    parser.add_argument("reconstructed", type=Path, help="Matching reconstructed episode .jsonl.gz")
    parser.add_argument("output", type=Path, help="Internal replay-plan JSON")
    parser.add_argument("--combat-index", type=int, default=0)
    args = parser.parse_args()

    raw = _rows(args.raw)
    reconstructed = _rows(args.reconstructed)
    if not raw or raw[0].get("t") != "header":
        raise SystemExit("raw replay has no header")
    header = raw[0]
    if header.get("build_id") != "v0.111.0" or header.get("mod_version") != "v1.2.1":
        raise SystemExit("replay version does not match the pinned native worker")
    starts = [index for index, row in enumerate(raw) if row.get("t") == "combat_start"]
    if args.combat_index < 0 or args.combat_index >= len(starts):
        raise SystemExit(f"combat index {args.combat_index} is out of range (found {len(starts)})")
    start = starts[args.combat_index]
    stop = next(
        (index + 1 for index in range(start + 1, len(raw)) if raw[index].get("t") == "combat_end"),
        None,
    )
    if stop is None:
        raise SystemExit("selected combat has no combat_end")
    combat_start = raw[start]
    draw_order = next((row for row in raw[start:stop] if row.get("t") == "draw_order"), None)
    if draw_order is None:
        raise SystemExit("selected combat has no opening draw order")

    latest_deck = next((row for row in reversed(raw[:start]) if row.get("t") == "deck"), None)
    if latest_deck is None:
        raise SystemExit("selected combat has no preceding deck snapshot")
    deck_by_ref = {
        row["c"]: row
        for row in latest_deck.get("cards", [])
        if isinstance(row, dict) and type(row.get("c")) is int and isinstance(row.get("id"), str)
    }
    opening_deck_refs = draw_order.get("order_deck_c")
    if not isinstance(opening_deck_refs, list) or any(type(value) is not int for value in opening_deck_refs):
        raise SystemExit("opening draw order has no complete deck-card mapping")
    try:
        opening_cards = [deck_by_ref[ref] for ref in opening_deck_refs]
    except KeyError as error:
        raise SystemExit(f"opening draw order references unknown deck card {error.args[0]}") from error
    replay_deck = [
        {
            "deck_ref": card["c"],
            "model_id": card["id"],
            "upgrade": card.get("up", 0),
            **({"enchantment": card["enchantment"]} if isinstance(card.get("enchantment"), str) else {}),
            **({"enchantment_amount": card["amount"]} if type(card.get("amount")) is int else {}),
            **({"state": card["state"]} if isinstance(card.get("state"), dict) else {}),
        }
        for card in latest_deck.get("cards", [])
        if isinstance(card, dict)
        and type(card.get("c")) is int
        and isinstance(card.get("id"), str)
    ]
    if len(replay_deck) != len(opening_deck_refs):
        raise SystemExit("opening draw order and latest deck have different card counts")
    if not isinstance(combat_start.get("rng_state"), dict):
        raise SystemExit("selected combat has no RNG counter snapshot")

    source_steps = {
        row["source_sequence"]: row
        for row in reconstructed
        if row.get("record_type") == "step"
        and row.get("domain") == "combat"
        and type(row.get("source_sequence")) is int
    }
    actions: list[dict[str, Any]] = []
    for row in raw[start:stop]:
        kind = row.get("t")
        if kind == "play" and row.get("auto") is not True:
            action: dict[str, Any] = {
                "kind": "play_card",
                "card_model_id": row.get("id"),
                "upgrade": row.get("up", 0),
            }
            if row.get("target") is not None:
                enemies = combat_start.get("enemies", [])
                slot = next(
                    (enemy.get("i") for enemy in enemies if enemy.get("cid") == row.get("target_cid")),
                    None,
                )
                action["target_slot"] = slot
                action["target_model_id"] = row.get("target")
        elif kind == "potion_start":
            action = {"kind": "use_potion", "model_id": row.get("id")}
            if row.get("target") is not None:
                enemies = combat_start.get("enemies", [])
                action["target_slot"] = next(
                    (enemy.get("i") for enemy in enemies if enemy.get("cid") == row.get("target_cid")),
                    None,
                )
                action["target_model_id"] = row.get("target")
        elif kind == "end_turn" and row.get("side") == "player":
            action = {"kind": "end_turn"}
        elif kind == "pick" and row.get("selector") == "human":
            action = {
                "kind": "resolve_choice",
                "selected_cards": [
                    {"model_id": card.get("id"), "upgrade": card.get("up", 0)}
                    for card in row.get("cards", [])
                    if isinstance(card, dict) and isinstance(card.get("id"), str)
                ],
            }
        else:
            continue
        source_sequence = row.get("s")
        converted = source_steps.get(source_sequence)
        if converted is None and action["kind"] != "resolve_choice":
            raise SystemExit(f"reconstructed combat step is missing for source sequence {source_sequence}")
        actions.append(
            {
                "source_sequence": source_sequence,
                "action": action,
                "expected_combat": converted["observation"]["combat"] if converted is not None else None,
                "reconstruction_replay_eligible": converted is not None and converted.get("native_replay_eligible") is True,
                "reconstruction_exclusion_reasons": converted.get("native_replay_exclusion_reasons", []) if converted is not None else ["combat_choice_requires_native_projection"],
            }
        )

    episode = reconstructed[0]
    first_step = next(
        (source_steps.get(action["source_sequence"]) for action in actions
         if source_steps.get(action["source_sequence"]) is not None),
        None,
    )
    if first_step is None:
        raise SystemExit("selected combat has no reconstructable player decision")
    plan = {
        "format_version": "stm-spire-codex-native-combat-plan-v1",
        "replay_only_hidden_state": True,
        "source": {
            "run_hash": args.raw.name.split(".", 1)[0],
            "episode_id": episode.get("episode_id"),
            "combat_index": args.combat_index,
            "build_id": header.get("build_id"),
            "mod_version": header.get("mod_version"),
        },
        "run": {
            "seed": header.get("seed"),
            "character": header.get("character"),
            "ascension": header.get("ascension"),
        },
        "combat": {
            "encounter": combat_start.get("encounter"),
            "floor": combat_start.get("floor"),
            "act": combat_start.get("act"),
            "rng_counters": combat_start.get("rng_state"),
            "enemies": combat_start.get("enemies", []),
            "run_snapshot": first_step["observation"]["run"],
            "replay_deck": replay_deck,
            "opening_draw_order": [
                {
                    "model_id": card["id"],
                    "upgrade": card.get("up", 0),
                    "deck_ref": ref,
                }
                for ref, card in zip(opening_deck_refs, opening_cards, strict=True)
            ],
            "actions": actions,
        },
    }
    _write(args.output, plan)
    print(json.dumps({"output": str(args.output), "actions": len(actions)}, sort_keys=True))


if __name__ == "__main__":
    main()
