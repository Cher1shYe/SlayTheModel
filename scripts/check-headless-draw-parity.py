#!/usr/bin/env python3
"""Replay the worker's first combat and optional natural event in the scene-backed host."""

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path


def request(base, method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def ready_state(base, timeout=45):
    deadline = time.monotonic() + timeout
    stable_revision = None
    while time.monotonic() < deadline:
        state = request(base, "GET", "/api/state")
        if state["status"] == "error":
            raise RuntimeError(state.get("error") or "Host capture failed")
        if state["status"] == "ready" and any(not a["disabled"] for a in state["actions"]):
            if stable_revision == state["revision"]:
                return state
            stable_revision = state["revision"]
        else:
            stable_revision = None
        time.sleep(0.2)
    raise TimeoutError(f"Host did not reach a ready decision: {state['screen']} {state['status']}")


def submit(base, state, action):
    request(base, "POST", "/api/action", {
        "revision": state["revision"], "actionId": action["id"],
    })


def enter_first_combat(base, seed):
    state = request(base, "GET", "/api/state")
    if state.get("player") is None and state["screen"] in ("startup", "transition"):
        request(base, "POST", "/api/new", {
            "character": "IRONCLAD", "ascension": 0, "seed": seed, "language": "eng",
        })
    for _ in range(10):
        state = ready_state(base)
        actions = [action for action in state["actions"] if not action["disabled"]]
        if state["screen"] == "combat":
            return state
        if state["screen"] == "NEventRoom":
            selected = next((action for action in actions if action["kind"] == "event"), None)
        elif state["screen"] == "card_bundle":
            selected = next((action for action in actions if action["kind"] == "choose_bundle"), None)
            if selected is None:
                selected = next((action for action in actions if action.get("enLabel") == "Confirm"), None)
        elif state["screen"] == "map":
            selected = min((action for action in actions if action["kind"] == "map"),
                           key=lambda action: (action["y"], action["x"]), default=None)
        else:
            selected = None
        if selected is None:
            raise RuntimeError(f"Unexpected pre-combat surface {state['screen']}: "
                               f"{[(a['kind'], a['label']) for a in actions]}")
        submit(base, state, selected)
    raise RuntimeError("First combat was not reached within ten native inputs")


def snapshot(state):
    piles = {}
    for entity in state["entities"]:
        if entity.get("pile") in ("hand", "draw", "discard", "exhaust", "play"):
            piles.setdefault(entity["pile"], []).append(entity["modelId"])
    for pile in ("hand", "draw", "discard", "exhaust", "play"):
        piles.setdefault(pile, [])
        piles[pile].sort()
    enemies = [entity for entity in state["entities"]
               if entity["kind"] == "enemy" and entity.get("hp", 0) > 0]
    round_match = re.search(r"回合\s+(\d+)", state.get("description", ""))
    return {
        "round": int(round_match.group(1)) if round_match else None,
        "playerHp": state["player"]["hp"],
        "energy": state["player"]["energy"],
        "piles": piles,
        "enemies": [{"modelId": enemy["modelId"], "hp": enemy["hp"]} for enemy in enemies],
    }


def matching_action(state, decision):
    spec = decision["action"]
    actions = [action for action in state["actions"] if not action["disabled"]]
    if spec["kind"] == "EndTurn":
        return next((action for action in actions if action["kind"] == "endTurn"), None)
    if spec["kind"] != "PlayCard":
        raise RuntimeError(f"Unsupported worker action {spec['kind']}")
    hand = {entity["id"]: entity["modelId"] for entity in state["entities"]
            if entity.get("pile") == "hand"}
    enemies = [entity for entity in state["entities"]
               if entity["kind"] == "enemy" and entity.get("hp", 0) > 0]
    target_index = spec["targetEnemyIndex"]
    if target_index is not None and not 0 <= target_index < len(enemies):
        raise RuntimeError(f"Worker target enemy index is unavailable in host: {target_index}")
    target_id = None if target_index is None else enemies[target_index]["id"]
    return next((action for action in actions if action["kind"] == "play"
                 and hand.get(action.get("entityId")) == spec["cardModelId"]
                 and action.get("targetId") == target_id), None)


def choose(base, state, predicate, label):
    action = next((action for action in state["actions"]
                   if not action["disabled"] and predicate(action)), None)
    if action is None:
        raise RuntimeError(f"{label} unavailable on {state['screen']}: "
                           f"{[(a['kind'], a['label']) for a in state['actions']]}")
    submit(base, state, action)
    return ready_state(base)


def deck_details(state):
    return sorted((entity["modelId"], entity.get("upgradeLevel", 0),
                   entity.get("enchantmentId") or "")
                  for entity in state["entities"] if entity.get("pile") == "deck")


def compare_event_route(base, probe, state):
    reward = next(stage for stage in probe["stages"] if stage["stage"] == "combat-rewards")
    event_before = next(stage for stage in probe["stages"]
                        if stage["stage"] == "first-unknown-event-options")
    event_after = next(stage for stage in probe["stages"]
                       if stage["stage"] == "first-unknown-event-choice")
    next_room = next(stage for stage in probe["stages"]
                     if stage["stage"] == "enter-after-first-unknown-event")
    if state["screen"] != "NRewardsScreen":
        raise RuntimeError(f"Expected native reward screen, got {state['screen']}")
    state = choose(base, state, lambda action: action["kind"] == "reward"
                   and "Gold" in action["label"], "gold reward")
    state = choose(base, state, lambda action: action["kind"] == "reward"
                   and "Potion" in action["label"], "potion reward")
    state = choose(base, state, lambda action: action["kind"] == "reward"
                   and "card" in action["label"].lower(), "card reward")
    if state["screen"] != "card_reward":
        raise RuntimeError(f"Expected native card reward choices, got {state['screen']}")
    offered = [choice["card"]["modelId"] for choice in state["choices"]]
    if offered != reward["rewardCardCandidates"]:
        raise RuntimeError(f"Card reward candidates differ: worker={reward['rewardCardCandidates']} host={offered}")
    selected_reward = "CARD." + reward["rewardCardSelections"][0]
    reward_index = offered.index(selected_reward)
    actions = [action for action in state["actions"] if action["kind"] == "choose_reward_card"]
    state = choose(base, state, lambda action: action is actions[reward_index], "selected card reward")
    if state["player"]["hp"] != event_before["playerHp"] or state["player"]["gold"] != event_before["gold"]:
        raise RuntimeError("Player HP or gold differs after native combat rewards")
    if sorted(entity["modelId"] for entity in state["entities"] if entity.get("pile") == "deck") != event_before["deck"]:
        raise RuntimeError("Deck differs after native combat rewards")
    state = choose(base, state, lambda action: action["kind"] == "button"
                   and action["label"] in ("继续", "Proceed"), "reward proceed")
    if state["screen"] != "map":
        raise RuntimeError(f"Expected map after rewards, got {state['screen']}")
    state = choose(base, state, lambda action: action["kind"] == "map"
                   and action.get("x") == 1 and action.get("y") == 2, "first unknown map point")
    if state["screen"] != "NEventRoom" or state.get("surfaceModelId") != "EVENT." + event_before["eventId"]:
        raise RuntimeError(f"Event differs: worker={event_before['eventId']} "
                           f"host={state.get('surfaceModelId')} screen={state['screen']}")
    event_actions = [action for action in state["actions"] if action["kind"] == "event"]
    titles = [action["label"] for action in event_actions]
    expected_titles = [option["title"] for option in event_before["options"]]
    if titles != expected_titles:
        raise RuntimeError(f"Event options differ: worker={expected_titles} host={titles}")
    if state["player"]["hp"] != event_before["playerHp"] or state["player"]["gold"] != event_before["gold"]:
        raise RuntimeError("Player HP or gold differs on native event entry")
    if sorted(entity["modelId"] for entity in state["entities"] if entity.get("pile") == "deck") != event_before["deck"]:
        raise RuntimeError("Deck differs on native event entry")
    print(f"event entry: {event_before['eventId']} options={titles} match", flush=True)
    index = event_after["eventOptionIndex"]
    state = choose(base, state, lambda action: action is event_actions[index], "selected event option")
    if event_after["selectionOffers"]:
        if state["screen"] != "card_selection":
            raise RuntimeError(f"Expected event card selection, got {state['screen']}")
        offer = event_after["selectionOffers"][0]
        candidates = sorted(choice["card"]["modelId"] for choice in state["choices"])
        if candidates != sorted(offer["Candidates"]):
            raise RuntimeError(f"Event card candidates differ: worker={offer['Candidates']} host={candidates}")
        selected_model = event_after["selectedCards"][0]["modelId"]
        choice_index = next(choice["index"] for choice in state["choices"]
                            if choice["card"]["modelId"] == selected_model)
        actions = [action for action in state["actions"] if action["kind"] == "select_card"]
        state = choose(base, state, lambda action: action is actions[choice_index], "selected event card")
        state = choose(base, state, lambda action: action.get("enLabel") == "Confirm"
                       or action["label"] == "确认", "event card confirmation")
    if state["screen"] != "NEventRoom" or state.get("surfaceModelId") != "EVENT." + event_after["eventId"]:
        raise RuntimeError(f"Expected resolved native event, got {state['screen']}")
    expected_deck = sorted((card["modelId"], card["upgradeLevel"], card["enchantmentId"] or "")
                           for card in event_after["deckDetails"])
    observed_deck = deck_details(state)
    expected_potions = sorted(event_after["potions"])
    observed_potions = sorted(entity["modelId"] for entity in state["entities"] if entity["kind"] == "potion")
    expected_relics = sorted(event_after["relics"])
    observed_relics = sorted(entity["modelId"] for entity in state["entities"] if entity["kind"] == "relic")
    matched = (state["player"]["hp"] == event_after["playerHp"]
               and state["player"]["gold"] == event_after["gold"]
               and observed_deck == expected_deck
               and observed_potions == expected_potions
               and observed_relics == expected_relics)
    print(f"event choice {index}: " + ("match" if matched else "DIFFER"), flush=True)
    state = choose(base, state, lambda action: action["kind"] in ("event", "button")
                   and action["label"] in ("Proceed", "继续"), "event proceed")
    if state["screen"] != "map":
        raise RuntimeError(f"Expected map after event, got {state['screen']}")
    state = choose(base, state, lambda action: action["kind"] == "map"
                   and action.get("x") == next_room["col"]
                   and action.get("y") == next_room["row"], "post-event map point")
    next_enemies = [{"modelId": entity["modelId"], "hp": entity["hp"]}
                    for entity in state["entities"] if entity["kind"] == "enemy" and entity["hp"] > 0]
    expected_next_enemies = next_room["enemies"] or []
    next_matched = (state["screen"] == "combat"
                    and state.get("surfaceModelId") == next_room["encounter"]
                    and state["player"]["hp"] == next_room["playerHp"]
                    and state["player"]["gold"] == next_room["gold"]
                    and deck_details(state) == sorted(
                        (card["modelId"], card["upgradeLevel"], card["enchantmentId"] or "")
                        for card in next_room["deckDetails"])
                    and next_enemies == expected_next_enemies)
    print("post-event encounter: " + ("match" if next_matched else "DIFFER"), flush=True)
    return {"eventId": event_before["eventId"], "options": titles, "selectedOption": titles[index],
            "rewardCandidates": offered, "selectedReward": selected_reward,
            "selectionCandidates": event_after["selectionOffers"],
            "worker": {"hp": event_after["playerHp"], "gold": event_after["gold"],
                       "deck": expected_deck, "potions": expected_potions, "relics": expected_relics},
            "host": {"hp": state["player"]["hp"], "gold": state["player"]["gold"],
                     "deck": observed_deck, "potions": observed_potions, "relics": observed_relics},
            "nextRoom": {"point": [next_room["col"], next_room["row"]],
                         "workerEncounter": next_room["encounter"],
                         "hostEncounter": state.get("surfaceModelId"),
                         "workerEnemies": expected_next_enemies, "hostEnemies": next_enemies,
                         "matches": next_matched},
            "matches": matched and next_matched}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18777")
    parser.add_argument("--probe-json", default="artifacts/native-host/whole-run-speed-probe.json")
    parser.add_argument("--output", default="artifacts/headless/first-combat-draw-parity.json")
    parser.add_argument("--start-decision", type=int, default=0,
                        help="Resume a stopped comparison at this decision in the same host run")
    parser.add_argument("--compare-event", action="store_true",
                        help="Continue through matching rewards and the first natural unknown event")
    args = parser.parse_args()
    probe = json.loads(Path(args.probe_json).read_text())
    if probe["error"] is not None or probe["seedHandling"] != "native-canonicalized":
        raise ValueError("Expected a completed canonical worker probe")
    if args.compare_event and not any(stage["stage"] == "first-unknown-event-choice" for stage in probe["stages"]):
        raise ValueError("--compare-event requires a canonical probe run with STS2_PROBE_ROUTE=event")
    trace = next(stage["decisions"] for stage in probe["stages"]
                 if stage["stage"] == "first-combat-decision-trace")
    state = enter_first_combat(args.url.rstrip("/"), probe["inputSeed"])
    comparisons = []
    for decision in trace[args.start_decision:]:
        if state["screen"] != "combat":
            raise RuntimeError(f"Combat stopped before worker decision {decision['decision']}: {state['screen']}")
        observed = snapshot(state)
        expected_piles = {pile["pile"]: pile["cards"] for pile in decision["piles"]}
        differences = {}
        for name, expected, actual in (
            ("round", decision["round"], observed["round"]),
            ("playerHp", decision["playerHp"], observed["playerHp"]),
            ("energy", decision["energy"], observed["energy"]),
            ("piles", expected_piles, observed["piles"]),
            ("enemies", [enemy for enemy in decision["enemies"] if enemy["alive"]], observed["enemies"]),
        ):
            if name == "enemies":
                expected = [{"modelId": enemy["modelId"], "hp": enemy["hp"]} for enemy in expected]
            if expected != actual:
                differences[name] = {"worker": expected, "host": actual}
        comparisons.append({"decision": decision["decision"], "action": decision["action"],
                            "host": observed, "differences": differences})
        print(f"decision {decision['decision']}: " + ("match" if not differences else f"DIFFER {list(differences)}"), flush=True)
        if differences:
            break
        action = matching_action(state, decision)
        if action is None:
            raise RuntimeError(f"Worker action is unavailable in host: {decision['action']}")
        submit(args.url.rstrip("/"), state, action)
        if decision is not trace[-1]:
            state = ready_state(args.url.rstrip("/"))
    terminal = None
    event_route = None
    event_error = None
    if comparisons and not comparisons[-1]["differences"] and comparisons[-1]["decision"] == len(trace) - 1:
        state = ready_state(args.url.rstrip("/"))
        victory = next(stage for stage in probe["stages"] if stage["stage"] == "combat-victory")
        terminal = {"hostScreen": state["screen"], "hostHp": state["player"]["hp"],
                    "workerHp": victory["hp"], "matches":
                    state["screen"] == "NRewardsScreen" and state["player"]["hp"] == victory["hp"]}
        print("victory: " + ("match" if terminal["matches"] else "DIFFER"), flush=True)
        if args.compare_event and terminal["matches"]:
            try:
                event_route = compare_event_route(args.url.rstrip("/"), probe, state)
            except Exception as error:
                event_error = str(error)
                print("event route: DIFFER " + event_error, flush=True)
    result = {"inputSeed": probe["inputSeed"], "seed": probe["seed"],
              "startDecision": args.start_decision,
              "matchedDecisions": sum(not item["differences"] for item in comparisons),
              "expectedDecisions": len(trace) - args.start_decision,
              "comparisons": comparisons, "terminal": terminal,
              "eventRoute": event_route, "eventError": event_error}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {output}")
    if (result["matchedDecisions"] != len(trace) - args.start_decision
            or terminal and not terminal["matches"]
            or args.compare_event and (event_route is None or not event_route["matches"])):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
