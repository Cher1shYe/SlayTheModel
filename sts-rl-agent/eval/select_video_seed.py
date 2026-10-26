#!/usr/bin/env python3
"""Rank held-out seeds for a visually rich learned-vs-random recording case."""

import argparse
import json
import os
import random
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
SIM = Path(os.environ.get(
    "STS_LIGHTSPEED_BUILD", ROOT.parent / "sts_lightspeed/build312")).expanduser()
sys.path[:0] = [str(SIM), str(ROOT / "agent")]

import slaythespire as sts  # noqa: E402
import armG_train as AG  # noqa: E402
from neow_setup import max_hp_option  # noqa: E402

MODEL = ROOT / "weights/armG_model_G128x128_15k.pt"
NONCOMBAT = {sts.ScreenState.REWARDS, sts.ScreenState.MAP_SCREEN, sts.ScreenState.REST_ROOM,
             sts.ScreenState.SHOP_ROOM, sts.ScreenState.EVENT_SCREEN}


def load_model():
    model = AG.Scorer((128, 128))
    model.load_state_dict(torch.load(MODEL, weights_only=True))
    model.eval()
    return model


def play(seed, model, simulations, learned, neow_index=None):
    game = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    agent = sts.Agent(); agent.simulation_count_base = simulations
    agent.pause_on_card_reward = agent.pause_on_map = agent.pause_on_rest = True
    agent.pause_on_shop = agent.pause_on_event = True
    agent.pause_on_battle = True
    rng = random.Random(seed ^ 0xA11CE)
    kinds, rests, decisions = {}, [], 0
    bosses, current_act = [str(game.boss).split(".")[-1]], game.act
    for _ in range(600):
        agent.playout(game)
        if game.act != current_act:
            current_act = game.act
            bosses.append(str(game.boss).split(".")[-1])
        if game.outcome != sts.GameOutcome.UNDECIDED: break
        if game.screen_state == sts.ScreenState.BATTLE:
            battle = sts.BattleContext(); battle.init(game)
            for _ in range(800):
                if battle.outcome != sts.Outcome.UNDECIDED: break
                actions = sts.get_legal_actions(battle)
                action = actions[0] if len(actions) == 1 else sts.mcts_recommend(battle, simulations)
                action.execute(battle)
            battle.exit_battle(game)
            continue
        if game.screen_state not in NONCOMBAT: break
        kind, descriptors, executors = AG.build_choices(game)
        if not descriptors:
            if game.screen_state == sts.ScreenState.REWARDS: game.skip_reward_cards()
            continue
        actions = sts.get_legal_game_actions(game) if kind != "card" else []
        if kind == "event" and game.floor_num == 0:
            if neow_index is None:
                before_deck, before_relics, before_gold = list(game.deck), len(game.relics), game.gold
                executors[max_hp_option(sts, AG, seed)](game)
                game.cur_hp = game.max_hp
                assert len(game.deck) == len(before_deck) and len(game.relics) == before_relics
                assert game.gold == before_gold
            else:
                executors[neow_index](game)
            continue
        if learned:
            with torch.no_grad():
                scores = model.score(torch.tensor(AG.obs_vec(game), dtype=torch.float32), descriptors)
            selected = int(torch.argmax(scores).item())
        else:
            selected = rng.randrange(len(descriptors))
        decisions += 1; kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "rest":
            options = [int(action.idx1) for action in actions]
            rests.append({"floor": game.floor_num, "hp": game.cur_hp, "max_hp": game.max_hp,
                          "options": options, "selected": options[selected]})
        executors[selected](game)
    return {"floor": game.floor_num, "win": game.outcome == sts.GameOutcome.PLAYER_VICTORY,
            "bosses": bosses,
            "decisions": decisions, "kinds": kinds, "rests": rests}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim", type=int, default=400)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--seeds", help="comma-separated numeric seeds")
    args = parser.parse_args()
    seeds = ([int(seed) for seed in args.seeds.split(",")]
             if args.seeds else AG.read_seeds("eval_seeds_50.txt")[:args.limit])
    model = load_model(); ranked = []
    for index, seed in enumerate(seeds, 1):
        try:
            learned = play(seed, model, args.sim, True)
            random_result = play(seed, model, args.sim, False)
        except ValueError as exc:
            print(f"[{index}/{len(seeds)}] {seed} SKIP {exc}", flush=True)
            continue
        smiths = [rest for rest in learned["rests"]
                  if 0 in rest["options"] and 1 in rest["options"] and rest["selected"] == 1]
        coverage = len(learned["kinds"])
        ranked.append({"seed": seed, "steam_token": sts.get_seed_str(seed),
                       "delta": learned["floor"] - random_result["floor"],
                       "win_contrast": learned["win"] and not random_result["win"],
                       "smiths": smiths, "coverage": coverage,
                       "learned": learned, "random": random_result})
        print(f"[{index}/{len(seeds)}] {seed} L{learned['floor']}{'W' if learned['win'] else ''} "
              f"R{random_result['floor']}{'W' if random_result['win'] else ''} smith={len(smiths)}", flush=True)
    ranked.sort(key=lambda row: (row["win_contrast"], row["learned"]["win"],
                                 not row["random"]["win"], row["delta"], row["coverage"]), reverse=True)
    print(json.dumps(ranked[:args.top], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
