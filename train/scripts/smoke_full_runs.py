"""Whole-run smoke test through the training path (DEVLOG 48).

Each seed starts an A10 Ironclad run, injects random Ironclad-obtainable relics, cards and
potions (test setup only, like ``add_relic`` in the audits), optionally jumps to act 2 or 3,
then plays with a play-biased random policy through ``public_obs.from_simulator`` and the
training ``Driver`` (same guards, same encoding). Random play rarely leaves act 1, so the jump
is what reaches the act 2/3 rooms, encounters and Ancients.

Checks every decision: no exception (seed + floor + screen + traceback on failure); finite
encoding; 0 <= HP <= max HP; the encounter actually entered next had positive probability in
checklist D; and records the most plays in one player turn (the unexplained run-1 error was a
turn with more than 160 distinct cards, DEVLOG 39).

    cd train && PYTHONPATH=.:.. python scripts/smoke_full_runs.py FIRST_SEED COUNT [--plain]

``--plain`` injects nothing and starts in act 1 (the training distribution).
"""
from __future__ import annotations

import collections
import json
import re
import random
import sys
import time
import traceback
from pathlib import Path

import numpy as np

from spire_rl import public_derived as derived
from spire_rl import public_obs as p
from spire_rl import public_tactics as tactics
from spire_rl.driver import Driver
from spire_rl.sim import sim

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "train/spire_rl/public_catalog.json").read_text())
ACTS, TAGS = CATALOG["acts"], CATALOG["encounterTags"]
# Upgraded starters of the other characters: not reachable as Ironclad, effects not checked (AGENTS 0.3.1).
OTHER_STARTERS = {"RING_OF_THE_DRAKE", "INFUSED_CORE", "PHYLACTERY_UNBOUND", "DIVINE_DESTINY"}
# Only obtainable through the Ancient that prepares its card first; the test hook cannot do that.
NEEDS_EVENT = {"DUSTY_TOME", "NEOWS_BONES", "BLACK_BLOOD"}   # Neow-only, or only via Touch of Orobas


def _relic_pool():
    out = []
    for name, rid in sim.RelicId.__members__.items():
        if name == "INVALID" or name in OTHER_STARTERS or name in NEEDS_EVENT:
            continue
        _, _, rarity, pool = sim.relic_info(int(rid))
        if pool in (0, 1, 2):           # shared, Ironclad, special (event / Ancient / boss swaps)
            out.append(int(rid))
    return out


def _card_pool():
    text = (ROOT / "sim/include/sts2/cards_generated.inc").read_text()
    table = text[text.index("CARD_DEFS[] = {"):]
    rows = re.findall(r"\{CardId::(\w+), \"\w*\", \"[^\"]*\", CardPool::(\w+), [^{]*?Rarity::(\w+)", table)
    ids = []
    for index, (name, pool, rarity) in enumerate(rows):
        if name not in ("INVALID", "GRAPPLE") and pool in ("IRONCLAD", "COLORLESS") and rarity in ("COMMON", "UNCOMMON", "RARE"):
            ids.append(index)
    return ids


RELICS, CARDS = _relic_pool(), _card_pool()
POTIONS = [i for i in range(1, 64)]


def setup(seed: int, plain: bool):
    rng = random.Random(seed)
    rc = sim.RunContext()
    rc.init(seed, 10)
    note = {"seed": seed, "relics": [], "cards": [], "act": 0}
    if plain:
        return rc, rng, note
    for _ in range(200):        # finish Neow and its reward screens first: its offers were rolled
        if rc.screen == sim.RunScreen.MAP or rc.is_terminal:    # before the injection, and Neow's
            break                                               # Bones keeps its own reward state
        s = p.from_simulator(rc)
        if not s.actions:
            break
        p.step_simulator(rc, s, rng.randrange(len(s.actions)))
    def back_to_map():      # resolve any screen a relic opened, so obtains happen one at a time as in play
        for _ in range(300):
            if rc.screen == sim.RunScreen.MAP or rc.is_terminal:
                return
            s = p.from_simulator(rc)
            if not s.actions:
                return
            p.step_simulator(rc, s, rng.randrange(len(s.actions)))

    for rid in rng.sample(RELICS, rng.randint(3, 12)):
        back_to_map()
        if rc.screen != sim.RunScreen.MAP:
            break
        if rc.add_relic(rid):
            note["relics"].append(sim.relic_name(rid))
    back_to_map()
    for cid in rng.sample(CARDS, rng.randint(3, 10)):
        up = rng.random() < 0.5
        rc.add_card(cid, up)
        note["cards"].append(sim.card_name(cid) + ("+" if up else ""))
    for _ in range(rng.randint(0, 2)):
        try:
            rc.add_potion(rng.choice(POTIONS))
        except Exception:
            pass
    act = rng.choice((0, 1, 1, 2, 2))
    if act and rc.screen == sim.RunScreen.MAP:
        rc.start_act(act)
    else:
        act = 0
    note["act"] = act
    return rc, rng, note


def play(seed: int, plain: bool, max_decisions: int = 6000):
    try:
        rc, rng, note = setup(seed, plain)
    except Exception as exc:        # the random setup walk can hit the same errors as play
        return ({"seed": seed, "relics": [], "cards": [], "act": 0}, collections.Counter(),
                {"where": "setup", "history": [], "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]})
    driver = Driver()
    stats = collections.Counter()
    prev = None
    plays_this_turn = 0
    where = "setup"
    history = collections.deque(maxlen=12)     # recent non-combat actions, shown on failure
    try:
        for _ in range(max_decisions):
            if rc.is_terminal:
                stats["won" if rc.won else "died"] += 1
                break
            state = p.from_simulator(rc)
            f = state.facts
            where = f"floor {f['run']['floor']} act {f['run']['act']} screen {f['screen']}"
            pl = f["player"]
            if not 0 <= pl["hp"] <= pl["maxHp"]:
                raise AssertionError(f"hp {pl['hp']} / {pl['maxHp']}")
            if not state.actions:        # a live state with nothing to do ends a training game early
                raise AssertionError(f"no legal action on a non-terminal {f['screen']} screen")
            run = f["run"]                              # checklist D in every act
            if prev is not None and prev[0]["currentAct"] == run["currentAct"]:
                for kind, key, col in (("normal", "actNormalEncounters", 5), ("elite", "actEliteEncounters", 6)):
                    before, after = prev[0][key], run[key]
                    if len(after) == len(before) + 1:
                        odds = {k: v[col] for k, v in prev[1].items()}
                        if odds and abs(sum(odds.values()) - 1.0) > 1e-6:
                            raise AssertionError(f"D {kind} odds sum {sum(odds.values())}")
                        if odds and odds.get(after[-1], 0.0) <= 0:
                            raise AssertionError(f"D {kind}: entered {after[-1]} predicted 0 after {before}")
                        stats[f"d_{kind}_{run['currentAct']}"] += 1
            prev = (run, derived.act_encounters(run, ACTS, TAGS)[1])
            d = driver.decide(state)
            if d.verdict:
                stats[d.verdict] += 1
                break
            if d.forced is not None:
                index = d.forced
            else:
                for k in ("num", "cand_num", "global_row", "player_row"):
                    if not np.isfinite(np.asarray(getattr(d.obs, k))).all():
                        raise AssertionError(f"non-finite {k}")
                allowed = np.flatnonzero(d.allowed)
                plays = [i for i in allowed if state.actions[i].key.kind == "play"]
                if plays and f["screen"] == "combat" and rng.random() < 0.7:
                    preview = tactics.action_preview(state)     # greedy on the B preview: go deeper
                    score = lambda i: (preview[i]["total_damage"] + 0.7 * preview[i]["block"]) if preview.get(i) and preview[i]["known"] else -1
                    index = int(max(plays, key=lambda i: (score(i), rng.random())))
                else:
                    index = int(rng.choice(plays if plays and rng.random() < 0.85 else list(allowed)))
            kind = state.actions[index].key.kind
            if f["screen"] != "combat":
                history.append(f"{f['screen']}:{kind}{state.actions[index].key.args[:2]} [bones {rc.neows_bones_stage}]")
            if kind == "play":
                plays_this_turn += 1
                stats["max_plays_turn"] = max(stats["max_plays_turn"], plays_this_turn)
            elif kind == "end_turn":
                plays_this_turn = 0
            if f["screen"] == "combat":
                stats[f"combat_{run['currentAct']}"] += 1
            driver.chose(index)
            handle = p.candidate_handle(state, index)
            ok = rc.step_combat(*handle) if f["combat"] is not None else rc.step(*handle)
            if not ok:
                raise RuntimeError(f"simulator rejected {state.actions[index].key}")
            stats["decisions"] += 1
        else:
            stats["cap"] += 1
    except Exception as exc:
        play.last_rc = rc
        return note, stats, {"where": where, "history": list(history), "error": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]}
    stats["floor"] = int(rc.floor)
    return note, stats, None


def main():
    first, count = int(sys.argv[1]), int(sys.argv[2])
    plain = "--plain" in sys.argv
    total = collections.Counter()
    failures = []
    t0 = time.time()
    for seed in range(first, first + count):
        note, stats, fail = play(seed, plain)
        for k, v in stats.items():
            if k == "max_plays_turn":
                total[k] = max(total[k], v)
            elif k != "floor":
                total[k] += v
        total[f"start_act{note['act']}"] += 1
        if fail:
            failures.append({**note, **fail})
            print(f"FAIL seed {seed} at {fail['where']}\n  relics {note['relics']}\n  cards {note['cards']}\n  recent "
                  + "\n    ".join(fail["history"]) + f"\n{fail['error']}", flush=True)
    print(f"{count} runs in {time.time() - t0:.0f}s, {len(failures)} failures")
    print(json.dumps(dict(sorted(total.items()))))


if __name__ == "__main__":
    main()
