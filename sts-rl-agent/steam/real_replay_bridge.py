#!/usr/bin/env python3
"""Replay the first model+MCTS encounter into the real Steam game via CommunicationMod."""

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE = Path(os.environ.get("STS_TRACE_PATH", ROOT / "materials/raw/run-24242-real-compatible.jsonl"))
LOG = Path(os.environ.get("STS_REAL_REPLAY_LOG", ROOT / "materials/raw/real-replay-smoke.jsonl"))
SEED = 24242
DELAY = float(os.environ.get("STS_REPLAY_DELAY", "0.8"))
CARD_ALIASES = {"Strike": "打击", "Defend": "防御", "Bash": "痛击"}


def normalize(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def load_plan():
    events = [json.loads(line) for line in TRACE.read_text(encoding="utf-8").splitlines()]
    first_battle = next(index for index, event in enumerate(events) if event["type"] == "battle_start")
    first_end = next(index for index, event in enumerate(events[first_battle:], first_battle)
                     if event["type"] == "battle_end")
    decisions = [event for event in events[:first_battle] if event["type"] == "decision"]
    actions = [event for event in events[first_battle:first_end] if event["type"] == "battle_action"]
    return decisions, actions


def battle_command(description, combat_state):
    if "end turn" in description.lower():
        return "END"
    match = re.search(r"use card \((\d+)\) \(([^,]+),.*?(?: -> \((\d+)\) ([^ }]+))? ?}", description)
    if not match:
        raise ValueError(f"unsupported battle action: {description}")
    expected_card = match.group(2)
    hand = combat_state.get("hand") or []
    matching_cards = [
        index for index, card in enumerate(hand)
        if normalize(card.get("name")) in {
            normalize(expected_card), normalize(CARD_ALIASES.get(expected_card, expected_card))
        } and card.get("is_playable", True)
    ]
    if not matching_cards:
        raise ValueError(f"card missing: expected {expected_card}, hand={[card.get('name') for card in hand]}")
    hand_index = matching_cards[0]
    target_index = match.group(3)
    if target_index is None:
        return f"PLAY {hand_index + 1}"
    monsters = combat_state.get("monsters") or []
    expected_monster = match.group(4)
    matching_monsters = [
        (index, monster) for index, monster in enumerate(monsters)
        if normalize(expected_monster) in normalize(monster.get("name"))
        and not (monster.get("is_gone") or monster.get("is_dead"))
    ]
    if not matching_monsters:
        raise ValueError(f"monster missing: expected {expected_monster}, monsters={[m.get('name') for m in monsters]}")
    list_index, monster = matching_monsters[0]
    target_index = monster.get("monster_index", list_index)
    return f"PLAY {hand_index + 1} {target_index}"


def broll_battle_command(combat_state):
    hand = combat_state.get("hand") or []
    monsters = [
        (index, monster) for index, monster in enumerate(combat_state.get("monsters") or [])
        if not (monster.get("is_gone") or monster.get("is_dead"))
    ]
    playable = [(index, card) for index, card in enumerate(hand) if card.get("is_playable")]
    attacks = [(index, card) for index, card in playable if card.get("type") == "ATTACK"]
    if attacks and monsters:
        card_index, card = attacks[0]
        if card.get("has_target"):
            list_index, monster = min(monsters, key=lambda pair: pair[1].get("current_hp") or 10**9)
            return f"PLAY {card_index + 1} {monster.get('monster_index', list_index)}"
        return f"PLAY {card_index + 1}"
    if playable:
        card_index, card = playable[0]
        if card.get("has_target") and monsters:
            list_index, monster = min(monsters, key=lambda pair: pair[1].get("current_hp") or 10**9)
            return f"PLAY {card_index + 1} {monster.get('monster_index', list_index)}"
        return f"PLAY {card_index + 1}"
    return "END"


def emit(command):
    sys.stdout.write(command + "\n")
    sys.stdout.flush()


def log(record):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    decisions, actions = load_plan()
    decision_index = 0
    action_index = 0
    started = False
    entered_combat = False
    broll_mode = False
    if LOG.exists():
        LOG.unlink()

    emit("ready")
    for line in sys.stdin:
        try:
            state = json.loads(line)
        except json.JSONDecodeError:
            emit("WAIT 20")
            continue
        if not state.get("ready_for_command"):
            emit("WAIT 20")
            continue

        available = set(state.get("available_commands") or [])
        game_state = state.get("game_state") or {}
        combat_state = game_state.get("combat_state")
        command = None
        reason = None

        try:
            if not state.get("in_game"):
                if "start" in available and not started:
                    command = f"START IRONCLAD 0 {SEED}"
                    reason = "start fixed-seed replay"
                    started = True
                else:
                    command = "WAIT 100"
                    reason = "waiting for game"
            elif combat_state:
                entered_combat = True
                if not broll_mode:
                    if action_index >= len(actions):
                        raise ValueError("real battle requested more actions than the simulator trace")
                    try:
                        command = battle_command(actions[action_index]["action"], combat_state)
                        reason = f"trace battle action {action_index + 1}/{len(actions)}"
                        action_index += 1
                    except ValueError as exc:
                        broll_mode = True
                        log({"ts": time.time(), "status": "broll_switch", "reason": str(exc),
                             "floor": game_state.get("floor")})
                if broll_mode:
                    command = broll_battle_command(combat_state)
                    reason = "real-game B-roll heuristic (not model/MCTS evidence)"
            elif entered_combat and (broll_mode or action_index == len(actions)):
                log({"ts": time.time(), "status": "first_battle_replay_complete",
                     "decisions": decision_index, "battle_actions": action_index,
                     "broll_mode": broll_mode,
                     "floor": game_state.get("floor"), "screen": game_state.get("screen_type")})
                break
            elif "choose" in available and decision_index < len(decisions):
                event = decisions[decision_index]
                choices = game_state.get("choice_list") or []
                selected = event["selected"]
                expected_screen = {"event": "EVENT", "map": "MAP", "card": "CARD_REWARD",
                                   "shop": "SHOP_SCREEN", "rest": "REST"}.get(event["kind"])
                actual_screen = game_state.get("screen_type")
                if event["kind"] == "event" and event["floor"] == 0 and choices == ["对话"]:
                    command = "CHOOSE 0"
                    reason = "open Neow dialogue"
                elif actual_screen != expected_screen and len(choices) == 1:
                    command = "CHOOSE 0"
                    reason = f"open single transition: {choices[0]}"
                elif actual_screen != expected_screen:
                    raise ValueError(f"expected {expected_screen}, got {actual_screen}: {choices}")
                elif event["kind"] == "event" and event["floor"] == 0:
                    keyword = "最大生命值" if event.get("selected_by") == "fixed_setup" else "初始遗物"
                    matches = [
                        index for index, choice in enumerate(choices)
                        if keyword in choice
                    ]
                    if len(matches) != 1:
                        raise ValueError(f"cannot find Neow choice {keyword!r} in {choices}")
                    selected = matches[0]
                    command = f"CHOOSE {selected}"
                    reason = f"model Neow choice: {choices[selected]}"
                    decision_index += 1
                elif selected >= len(choices):
                    raise ValueError(f"choice diverged: need index {selected}, have {choices}")
                else:
                    command = f"CHOOSE {selected}"
                    reason = f"model {event['kind']} choice: {event['choices'][selected]['label']}"
                    decision_index += 1
            elif "proceed" in available:
                command = "PROCEED"
                reason = "advance transition"
            elif "confirm" in available:
                command = "CONFIRM"
                reason = "confirm transition"
            elif game_state.get("screen_type") == "GRID":
                raise ValueError(f"unexpected GRID screen: {game_state.get('choice_list') or []}")
            elif "key" in available:
                command = "KEY Confirm"
                reason = "dismiss popup"
            else:
                command = "WAIT 60"
                reason = "wait for next actionable state"
        except Exception as exc:
            log({"ts": time.time(), "status": "diverged", "error": str(exc),
                 "decision_index": decision_index, "action_index": action_index,
                 "floor": game_state.get("floor"), "screen": game_state.get("screen_type"),
                 "combat_state": combat_state})
            emit("WAIT 100")
            return 2

        log({"ts": time.time(), "status": "command", "command": command, "reason": reason,
             "floor": game_state.get("floor"), "screen": game_state.get("screen_type"),
             "choices": game_state.get("choice_list") or [], "available": sorted(available),
             "decision_index": decision_index, "action_index": action_index})
        time.sleep(DELAY)
        emit(command)
    return 0


def self_test():
    combat = {
        "hand": [{"name": "Strike"}],
        "monsters": [{"name": "Spike Slime (S)"}],
    }
    assert battle_command("{ use card (0) (Strike,0,1,1) -> (0) SPIKE_SLIME_S }", combat) == "PLAY 1 0"
    assert battle_command("{ end turn }", combat) == "END"
    assert broll_battle_command({
        "hand": [{"name": "打击", "type": "ATTACK", "is_playable": True, "has_target": True}],
        "monsters": [{"name": "虱虫", "current_hp": 10}],
    }) == "PLAY 1 0"
    assert broll_battle_command({
        "hand": [{"name": "观察弱点", "type": "SKILL", "is_playable": True, "has_target": True}],
        "monsters": [{"name": "守护者", "current_hp": 145}],
    }) == "PLAY 1 0"
    decisions, actions = load_plan()
    assert [event["kind"] for event in decisions] == ["event", "map"]
    assert actions
    print("SELF_TEST_OK")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        raise SystemExit(main())
