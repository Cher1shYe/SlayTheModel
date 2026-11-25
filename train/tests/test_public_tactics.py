"""Checklist A3 / A4 / B (train/spire_rl/public_tactics.py) against the simulator.

The tactical summaries are computed from public facts only; here they are compared with
what the engine actually does when the turn is ended / the card is played. States where
the summary is by design incomplete are skipped explicitly (listed below), so every
compared case must match exactly. B is checked for every card (not a whitelist): whatever it
marks known must equal the engine.
"""
from itertools import combinations
import random

import pytest

from spire_rl import public_obs as p
from spire_rl import public_tactics as t
from spire_rl.sim import sim

# Enemy-turn behaviour outside the A4 model: intents that change the player or the
# battle before/while others attack, and HP effects at the start of the next player turn.
SIMPLE_INTENTS = {"Attack", "DeathBlow", "Defend", "Sleep", "Stun"}
# Next-turn-start HP effects are outside A4 by definition; the measurement below includes them.
TURN_START_HP_POWERS = {"POWER.POISON_POWER", "POWER.REGEN_POWER", "POWER.INFERNO_POWER"}


def simple_enemy_turn(facts):
    if {pw[0] for pw in facts["powers"]} & TURN_START_HP_POWERS:
        return False
    return all(e["intentsVisible"] and all(i[0] in SIMPLE_INTENTS for i in e["intents"])
               for e in facts["enemies"] if e["alive"])


def hp_after_end_turn(rc, state):
    """HP lost by ending the turn now (until the next decision), or None if not observable."""
    end = next((i for i, a in enumerate(state.actions) if a.key.kind == "end_turn"), None)
    if end is None:
        return None
    copy = rc.clone()
    p.step_simulator(copy, state, end)
    if copy.is_terminal:
        return state.facts["player"]["hp"]  # died
    if copy.screen != sim.RunScreen.COMBAT:
        return None
    after = p.from_simulator(copy).facts
    if after["combat"]["turn"] != state.facts["combat"]["turn"] + 1:
        return None
    return state.facts["player"]["hp"] - after["player"]["hp"]


def random_combat_states(seeds, steps=1500, play_bias=0.85):
    rng = random.Random(seeds[0])
    for seed in seeds:
        rc = sim.RunContext(); rc.init(seed, 10)
        for _ in range(steps):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            if s.facts["screen"] == "combat":
                yield rc, s
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            pool = plays if plays and rng.random() < play_bias else range(len(s.actions))
            p.step_simulator(rc, s, rng.choice(list(pool)))


def test_end_turn_loss_matches_engine():
    checked = nonzero = 0
    for rc, s in random_combat_states(list(range(6100, 6160))):
        if not simple_enemy_turn(s.facts):
            continue
        loss, unknown, _, _ = t.end_turn(s.facts)
        if unknown:
            continue
        actual = hp_after_end_turn(rc, s)
        if actual is None:
            continue
        expected = min(loss, s.facts["player"]["hp"])
        assert actual == expected, (s.facts["player"], [e["intents"] for e in s.facts["enemies"]], loss, actual)
        checked += 1
        nonzero += actual > 0
    assert checked > 400 and nonzero > 150, (checked, nonzero)


# Enemy powers inside B's definition (no reaction to being hit that changes the numbers compared).
QUIET_FOR_B = {"POWER.VULNERABLE_POWER", "POWER.WEAK_POWER", "POWER.STRENGTH_POWER", "POWER.ARTIFACT_POWER",
               "POWER.RITUAL_POWER", "POWER.PLATING_POWER"}
CARD_ID = {sim.card_name(i).upper().replace(" ", "_").replace("'", "").replace("-", "_"): i for i in range(sim.card_count())}
# Cards and relics whose player-side effects B resolves; injected so the random games reach them.
SPECIAL_CARDS = ("BLOODLETTING OFFERING SECOND_WIND HEMOKINESIS FEEL_NO_PAIN RAGE TRUE_GRIT JUGGERNAUT INFERNO "
                 "DARK_EMBRACE CORRUPTION ONE_TWO_PUNCH POMMEL_STRIKE STONE_ARMOR BATTLE_TRANCE ENTRENCH "
                 "FORGOTTEN_RITUAL DRUM_OF_BATTLE EVIL_EYE BRAND BLOOD_WALL PACTS_END BURNING_PACT STOKE").split()
PLAY_RELICS = ("ORNAMENTAL_FAN KUSARIGAMA LETTER_OPENER NUNCHAKU TUNING_FORK DAUGHTER_OF_THE_WIND LOST_WISP "
               "CHARONS_ASHES FORGOTTEN_SOUL IRON_CLUB GAME_PIECE GREMLIN_HORN").split()


def injected_combat_states(seeds, cards=(), relics=(), steps=1500, play_bias=0.9):
    for seed in seeds:
        rng = random.Random(seed)
        rc = sim.RunContext(); rc.init(seed, 10)
        for name in cards:
            for _ in range(2):
                rc.add_card(CARD_ID[name], rng.random() < 0.5)
        for name in relics:
            rc.add_relic(int(getattr(sim.RelicId, name)))
        for _ in range(steps):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            if s.facts["screen"] == "combat":
                yield rc, s
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            pool = plays if plays and rng.random() < play_bias else range(len(s.actions))
            p.step_simulator(rc, s, rng.choice(list(pool)))


def audit_previews(states):
    """Every play B marks known must match the engine: energy, block, HP lost, damage (enemies
    without reacting powers); and, when nothing is unknown, the end-turn loss after it."""
    checked = {"play": 0, "end_turn_after": 0}
    for rc, s in states:
        f = s.facts
        if not all({pw[0] for pw in e["powers"]} <= QUIET_FOR_B for e in f["enemies"] if e["alive"]):
            continue
        previews = t.action_preview(s)
        for index, card, target in t._plays(s):
            pv = previews[index]
            if not pv["known"]:
                continue
            copy = rc.clone()
            p.step_simulator(copy, s, index)
            if copy.is_terminal or copy.screen != sim.RunScreen.COMBAT:
                continue
            after = p.from_simulator(copy)
            a = after.facts
            if a["screen"] != "combat":
                continue
            tag = (card["modelId"], pv)
            assert a["player"]["energy"] == pv["energy_after"], tag
            assert a["player"]["block"] - f["player"]["block"] == pv["block"], tag
            assert f["player"]["hp"] - a["player"]["hp"] == pv["self_hp_loss"], tag
            dmg = t._Play(card, target, f).run().damage
            killed = [e for e in f["enemies"] if e["hittable"] and dmg.get(e["order"], 0) >= e["hp"] + e["block"]]
            revived = any(x["alive"] and x["order"] == e["order"] for e in killed for x in a["enemies"])
            randomized = card["target"] == "RandomEnemy" or any(
                r["modelId"] in ("RELIC.KUSARIGAMA", "RELIC.FORGOTTEN_SOUL") for r in f["relics"]) or any(
                pw[0] == "POWER.JUGGERNAUT_POWER" for pw in f["powers"]) or card["modelId"] == "CARD.JUGGERNAUT"
            if len(a["enemies"]) == len(f["enemies"]) and not revived and (
                    not randomized or sum(e["hittable"] for e in f["enemies"]) == 1):
                total = sum((e["hp"] + e["block"]) - (max(x["hp"], 0) + x["block"])
                            for e in f["enemies"] for x in a["enemies"] if x["order"] == e["order"] and e["hittable"])
                assert abs(total - pv["total_damage"]) < 1e-6, tag
            checked["play"] += 1
            # Next-turn-start effects (Inferno, Crimson Mantle, Poison ...) are outside A4 by definition.
            starts = {"CARD.INFERNO", "CARD.CRIMSON_MANTLE"}
            if not pv["unknown"] and simple_enemy_turn(f) and card["modelId"] not in starts and \
                    not any(pw[0] == "POWER.CRIMSON_MANTLE_POWER" for pw in f["powers"]) and \
                    any(x.key.kind == "end_turn" for x in after.actions):
                actual = hp_after_end_turn(copy, after)
                if actual is not None:
                    assert actual == min(pv["end_turn_loss"], a["player"]["hp"]), tag + (actual,)
                    checked["end_turn_after"] += 1
    return checked


def test_action_preview_matches_engine_in_random_games():
    checked = audit_previews(random_combat_states(list(range(6200, 6215))))
    assert checked["play"] > 1500 and checked["end_turn_after"] > 600, checked


def test_action_preview_matches_engine_with_special_cards_and_relics():
    checked = audit_previews(injected_combat_states(range(8000, 8006), SPECIAL_CARDS))
    assert checked["play"] > 600 and checked["end_turn_after"] > 150, checked
    # Intimidating Helmet / Throwing Axe left out: the simulator fires the helmet once per card,
    # native once per replayed play (DEVLOG 35). Seeds avoid the Fake Merchant finished-page export
    # error (DEVLOG 35, open).
    checked = audit_previews(injected_combat_states((8100, 8102, 8104, 8105), SPECIAL_CARDS, PLAY_RELICS))
    assert checked["play"] > 300, checked


def test_bloodletting_hemokinesis_second_wind_examples():
    for name in ("BLOODLETTING", "HEMOKINESIS", "SECOND_WIND", "OFFERING"):
        found = False
        for rc, s in injected_combat_states(range(8300, 8310), [name], play_bias=0.0, steps=400):
            previews = t.action_preview(s)
            for index, card, target in t._plays(s):
                if card["modelId"] != "CARD." + name or not previews[index]["known"]:
                    continue
                pv = previews[index]
                f = s.facts
                hand = [c for c in f["cards"] if c["pile"] == "hand" and c is not card]
                if name in ("BLOODLETTING", "OFFERING"):     # unblockable HP loss, then energy
                    assert pv["self_hp_loss"] == int(t._var(card, "HpLoss"))
                    assert pv["energy_after"] == f["player"]["energy"] - card["cost"] + int(t._var(card, "Energy"))
                elif name == "HEMOKINESIS":
                    assert pv["self_hp_loss"] == int(t._var(card, "HpLoss"))
                elif name == "SECOND_WIND":                   # one block per exhausted non-Attack
                    if not any(pw[0] == "POWER.FEEL_NO_PAIN_POWER" for pw in f["powers"]):
                        assert pv["block"] == card["displayBlock"] * sum(c["type"] != "Attack" for c in hand)
                # lethal_after counts the HP lost during the play as well.
                assert pv["lethal_after"] == (pv["self_hp_loss"] + pv["end_turn_loss"] >= f["player"]["hp"])
                found = True
                break
            if found:
                break
        assert found, name


def test_max_damage_is_the_best_affordable_subset():
    checked = 0
    for _, s in random_combat_states(list(range(6300, 6320)), steps=600):
        plays = t._plays(s)
        energy = s.facts["player"]["energy"]
        reach = t.max_damage(s)
        for enemy in t._hittable(s.facts):
            best_per_card = {}
            for _, card, target in plays:
                dmg = t.play_damage(card, s.facts, target)
                if dmg:
                    v = dmg.get(enemy["order"], 0)
                    if v > best_per_card.get(id(card), (0, 0))[0]:
                        best_per_card[id(card)] = (v, t._energy_cost(card, s.facts))
            items = list(best_per_card.values())
            brute = 0
            for r in range(len(items) + 1):
                for combo in combinations(items, r):
                    if sum(c for _, c in combo) <= energy:
                        brute = max(brute, sum(v for v, _ in combo))
            total, kills, _ = reach[enemy["order"]]
            assert total == pytest.approx(brute)
            assert kills == (total >= enemy["hp"] + enemy["block"])
            checked += 1
    assert checked > 200


def test_end_turn_rules_on_constructed_facts():
    """Native ordering details that random games rarely reach."""
    def facts(block=0, hand=(), powers=(), relics=(), intents=((("Attack", 10, 1),),), hp=50, lost=0, osty=0):
        return {"player": {"block": block, "hp": hp, "energy": 3, "ostyHp": osty, "ostyMaxHp": osty},
                "powers": tuple((k, v, v, ()) for k, v in powers),
                "relics": [{"modelId": r, "position": i, "status": "Normal"} for i, r in enumerate(relics)],
                "combat": {"hpLostTurn": lost, "attacksPlayedTurn": 1},
                "cards": [dict(c, pile="hand", position=i) for i, c in enumerate(hand)],
                "enemies": [{"order": i, "alive": True, "hittable": True, "hp": 30, "block": 0, "intentsVisible": True,
                             "intents": its, "powers": ()} for i, its in enumerate(intents)]}
    burn = {"modelId": "CARD.BURN", "keywords": ("Unplayable",), "dynamicVars": (("Damage", 2),)}
    regret = {"modelId": "CARD.REGRET", "keywords": ("Unplayable",), "dynamicVars": ()}
    strike = {"modelId": "CARD.STRIKE_IRONCLAD", "keywords": (), "dynamicVars": (("Damage", 6),)}
    ghost = {"modelId": "CARD.DAZED", "keywords": ("Ethereal", "Unplayable"), "dynamicVars": ()}
    # Orichalcum checks Block == 0 first (VeryEarly), then +6: 10 - 6 = 4.
    assert t.end_turn(facts(relics=["RELIC.ORICHALCUM"]))[0] == 4
    assert t.end_turn(facts(block=1, relics=["RELIC.ORICHALCUM"]))[0] == 9
    # Burn 2 is blockable; Regret = hand size at BeforeSideTurnEnd (3) unblockable.
    assert t.end_turn(facts(block=12, hand=[burn, regret, strike]))[0] == 3 + 0
    # Feel No Pain 3 on the Ethereal Dazed exhaust before the attack: 10 - 3 = 7.
    assert t.end_turn(facts(hand=[ghost], powers=[("POWER.FEEL_NO_PAIN_POWER", 3)]))[0] == 7
    # Intangible: every hit at most 1. Buffer 1 cancels the first HP loss.
    assert t.end_turn(facts(powers=[("POWER.INTANGIBLE_POWER", 1)], intents=((("Attack", 10, 3),),)))[0] == 3
    assert t.end_turn(facts(powers=[("POWER.BUFFER_POWER", 1)], intents=((("Attack", 10, 2),),)))[0] == 10
    # Tungsten Rod -1 per loss; Beating Remnant caps the turn at 20 including earlier losses.
    assert t.end_turn(facts(relics=["RELIC.TUNGSTEN_ROD"], intents=((("Attack", 5, 2),),)))[0] == 8
    assert t.end_turn(facts(relics=["RELIC.BEATING_REMNANT"], lost=15, intents=((("Attack", 10, 1),),)))[0] == 5
    # Constrict (blockable) and Demise (unblockable) at AfterSideTurnEnd.
    assert t.end_turn(facts(block=5, powers=[("POWER.CONSTRICT_POWER", 4), ("POWER.DEMISE_POWER", 2)], intents=()))[0] == 2
    # Osty absorbs unblocked powered attack damage first (not Burn): block 3, Osty 4, hit 10 -> 3.
    assert t.end_turn(facts(block=3, osty=4))[0] == 3
    assert t.end_turn(facts(osty=4, hand=[burn], intents=()))[0] == 2
    # Hidden intents are unknown, never zero.
    assert t.end_turn(facts(intents=((("Hidden", 0, 0),),)))[1]


def test_channeled_orbs_are_public_and_counted_at_turn_end():
    found = 0
    for rc, s in injected_combat_states(range(8300, 8306), ("COLD_SNAP", "ZAP", "GLACIER")):
        f = s.facts
        orbs = f["player"]["orbs"]
        if not orbs:
            continue
        found += 1
        row = p.encode(s).player_row
        assert row[107] == 1 and row[108] == pytest.approx(f["player"]["orbCapacity"] / 10)
        for slot, orb in enumerate(orbs):
            base = 109 + 7 * slot
            assert row[base + p.ORB_KINDS.index(orb["modelId"])] == 1 and row[base:base + 5].sum() == 1
            assert row[base + 5] == pytest.approx(orb["passive"] / 20)
            assert row[base + 6] == pytest.approx(orb["evoke"] / 20)
        assert row[109 + 7 * len(orbs):109 + 70].sum() == 0
        if all(orb["modelId"] == "ORB.FROST_ORB" for orb in orbs):
            without = dict(f, player=dict(f["player"], orbs=[]))
            assert t.end_turn(f)[0] <= t.end_turn(without)[0]
        if found >= 60:
            break
    assert found
