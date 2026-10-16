#!/usr/bin/env python3
"""Read-only audit of combat potion slots in published collector episodes.

The raw JSONL remains the source of truth. This tool reports steps whose
combat observation cannot address the same potion slots as the native run
context and legal actions; it never rewrites an episode or its hash chain.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def potion_map(player: dict[str, Any]) -> dict[int, str] | None:
    potions = player.get("potions")
    if not isinstance(potions, list):
        return None
    result: dict[int, str] = {}
    for potion in potions:
        if not isinstance(potion, dict):
            return None
        slot = potion.get("slot_index")
        model = potion.get("model_id")
        if not isinstance(slot, int) or slot < 0 or not isinstance(model, str) or not model:
            return None
        if slot in result:
            return None
        result[slot] = model
    return result


def players_by_id(value: Any) -> dict[int, dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    players: dict[int, dict[str, Any]] = {}
    for player in value:
        if not isinstance(player, dict):
            return None
        player_id = player.get("player_id")
        if not isinstance(player_id, int) or player_id in players:
            return None
        players[player_id] = player
    return players


def potion_action_mismatch(
    action: dict[str, Any],
    observed: dict[int, dict[int, str]],
    native: dict[int, dict[int, str]],
) -> bool:
    player_id = action.get("actor_player_id")
    slot = action.get("potion_index")
    return (
        action.get("kind") == "use_potion"
        and (
            not isinstance(player_id, int)
            or not isinstance(slot, int)
            or slot not in native.get(player_id, {})
            or observed.get(player_id, {}).get(slot) != native[player_id][slot]
        )
    )


def audit(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "episode_id": None,
        "combat_decisions": 0,
        "slot_mismatch_steps": [],
        "recoverable_from_same_step_context_steps": [],
        "unverifiable_steps": [],
        "legal_action_mismatch_steps": [],
        "selected_potion_mismatch_steps": [],
    }
    decisions: dict[str, tuple[int | None, dict[int, dict[int, str]],
                                dict[int, dict[int, str]], list[dict[str, Any]]]] = {}
    submissions: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            event = json.loads(line)
            report["episode_id"] = report["episode_id"] or event.get("episode_id")
            kind = event.get("event_type")
            if kind == "action_submitted":
                submissions.append(event)
                continue
            if kind != "decision":
                continue
            payload = event.get("payload") or {}
            if payload.get("domain") != "combat":
                continue
            report["combat_decisions"] += 1
            step = event.get("global_step")
            decision_id = payload.get("decision_id")
            observation = payload.get("observation") or {}
            context = (payload.get("context") or {}).get("run_context") or {}
            observed_players = players_by_id(observation.get("players"))
            context_players = players_by_id(context.get("players"))
            if observed_players is None or context_players is None or not decision_id:
                report["unverifiable_steps"].append(step)
                continue
            if observed_players.keys() != context_players.keys():
                report["unverifiable_steps"].append(step)
                continue
            observed: dict[int, dict[int, str]] = {}
            native: dict[int, dict[int, str]] = {}
            recoverable = True
            for player_id in observed_players:
                observed_map = potion_map(observed_players[player_id])
                native_map = potion_map(context_players[player_id])
                if observed_map is None or native_map is None:
                    report["unverifiable_steps"].append(step)
                    break
                observed[player_id] = observed_map
                native[player_id] = native_map
                if list(observed_map.values()) != list(native_map.values()):
                    recoverable = False
            else:
                actions = payload.get("legal_actions") or []
                if not isinstance(actions, list):
                    report["unverifiable_steps"].append(step)
                    continue
                decisions[decision_id] = (step, observed, native, actions)
                if observed != native:
                    report["slot_mismatch_steps"].append(step)
                    if recoverable:
                        report["recoverable_from_same_step_context_steps"].append(step)
                if any(
                    potion_action_mismatch(action, observed, native)
                    for action in actions
                    if isinstance(action, dict)
                ):
                    report["legal_action_mismatch_steps"].append(step)
    for event in submissions:
        payload = event.get("payload") or {}
        decision = decisions.get(payload.get("decision_id"))
        if decision is None:
            continue
        step, observed, native, actions = decision
        index = payload.get("selected_action_index")
        if not isinstance(index, int) or not 0 <= index < len(actions):
            report["unverifiable_steps"].append(step)
            continue
        action = actions[index]
        if isinstance(action, dict) and potion_action_mismatch(action, observed, native):
            report["selected_potion_mismatch_steps"].append(step)
    for key, value in report.items():
        if key.endswith("_steps"):
            report[key] = sorted(set(value), key=lambda item: (-1 if item is None else item))
    return report


def episode_files(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        if path.is_dir():
            found.extend(path.glob("*.jsonl"))
        else:
            found.append(path)
    return sorted(set(found))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", type=Path,
        default=[Path("artifacts/human-dataset/episodes")],
        help="Published JSONL file or directory; defaults to the local episodes directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print complete machine-readable reports.")
    args = parser.parse_args()
    paths = episode_files(args.paths)
    if not paths:
        parser.error("No published JSONL files found.")
    try:
        reports = [audit(path) for path in paths]
    except (OSError, ValueError, TypeError) as error:
        print(f"Potion audit failed: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            episode = str(report["episode_id"] or "unknown").replace("-", "")[:12]
            print(
                f"{episode}: combat={report['combat_decisions']} "
                f"slot_mismatch={len(report['slot_mismatch_steps'])} "
                f"same_step_context_recoverable="
                f"{len(report['recoverable_from_same_step_context_steps'])} "
                f"legal_action_mismatch={len(report['legal_action_mismatch_steps'])} "
                f"selected_potion_mismatch={len(report['selected_potion_mismatch_steps'])} "
                f"unverifiable={len(report['unverifiable_steps'])}"
            )
        if len(reports) > 1:
            print(
                f"total: episodes={len(reports)} "
                f"combat={sum(report['combat_decisions'] for report in reports)} "
                f"slot_mismatch={sum(len(report['slot_mismatch_steps']) for report in reports)} "
                f"same_step_context_recoverable="
                f"{sum(len(report['recoverable_from_same_step_context_steps']) for report in reports)} "
                f"legal_action_mismatch="
                f"{sum(len(report['legal_action_mismatch_steps']) for report in reports)} "
                f"selected_potion_mismatch="
                f"{sum(len(report['selected_potion_mismatch_steps']) for report in reports)} "
                f"unverifiable={sum(len(report['unverifiable_steps']) for report in reports)}"
            )
    return 2 if any(
        report["slot_mismatch_steps"] or report["unverifiable_steps"]
        or report["legal_action_mismatch_steps"]
        or report["selected_potion_mismatch_steps"]
        for report in reports
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
