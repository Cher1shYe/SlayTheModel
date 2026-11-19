"""Apply the native v0.111.0 monster state machines and attack numbers to content/monsters.json
and the A9 tables, then regenerate the C++ tables (gen_monsters.py).

For every monster whose move states match native after the reviewed renames below:
* random branches: native order, repeat rule, max repeats, float weight, cooldown;
* conditional branches: native targets, conditions mapped to the C++ condition codes;
* move follow-ups (kept when native has none, e.g. a move after which the monster dies);
* the initial state (native MoveState / branch state; StarterMoveIdx-style expressions are set
  by the encounter, monsters.cpp native_roster);
* attack damage and hit counts at A0 and, through monsters_a9_*.json, at A9 (DeadlyEnemies).
Monsters whose states differ (new or removed moves) are listed and must be ported by hand.
Existing state order is kept: C++ special cases refer to local state indices.

Usage: python sim/tools/apply_native_ai.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import native_monster_ai as nai  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"

# Same move, different name (checked against the native intents and move bodies).
RENAMES = {
    "BOWLBUG_SILK": {"TRASH_MOVE": "THRASH_MOVE"},
    "EXOSKELETON": {"MANDIBLE_MOVE": "MANDIBLES_MOVE"},
    "SLITHERING_STRANGLER": {"TWACK": "THWACK"},
    "TERROR_EEL": {"ThrashMove": "THRASH_MOVE"},
    "QUEEN": {"YOUR_MINE_MOVE": "YOU_ARE_MINE_MOVE"},
    "THE_INSATIABLE": {"THRASH_MOVE_1": "THRASH_MOVE"},
    "TUNNELER": {"BELOW_MOVE_1": "BELOW_MOVE"},
    "TURRET_OPERATOR": {"UNLOAD_MOVE_1": "UNLOAD_MOVE"},
    "MAGI_KNIGHT": {"FIRST_POWER_SHIELD_MOVE": "POWER_SHIELD_MOVE"},
    "NIBBIT": {"INITIAL": "INIT_MOVE"},
    "LEAF_SLIME_S": {"RANDOM": "RAND", "BUTT_MOVE": "TACKLE_MOVE"},
    "TWIG_SLIME_S": {"BUTT_MOVE": "TACKLE_MOVE"},
    "CUBEX_CONSTRUCT": {"REPEATER_MOVE": "REPEATER_BLAST_MOVE", "REPEATER_MOVE_2": "REPEATER_BLAST_MOVE_2",
                        "EXPEL_BLAST": "EXPEL_MOVE"},
    "TWIG_SLIME_M": {"RANDOM": "RAND", "CLUMP_SHOT_MOVE": "POKEY_POUNCE_MOVE"},   # native fn ClumpShotMove
    "TORCH_HEAD_AMALGAM": {"TACKLE_1_MOVE": "STRONG_TACKLE_MOVE"},
    "BYGONE_EFFIGY": {"INITIAL_SLEEP_MOVE": "SLEEP_MOVE", "SLEEP_MOVE": "SLEEP_MOVE_2"},  # fns InitialSleepMove / SleepMove
    "TEST_SUBJECT": {"BIG_POUNCE_MOVE": "BIG_POUNCE"},
    "SKULKING_COLONY": {"SUPER_CRAB_MOVE": "PIERCING_STABS_MOVE", "SMASH_MOVE": "ZOOM_MOVE_2"},  # rewritten below
    "FAKE_MERCHANT_MONSTER": {"SWIPE": "SWIPE_MOVE", "SPEW_COINS": "SPEW_COINS_MOVE",
                              "THROW_RELIC": "THROW_RELIC_MOVE", "ENRAGE": "ENRAGE_MOVE",
                              "RAND": "RAND_MOVE", "RAND_ATTACK": "RAND_ATTACK_MOVE"},
}

# Native condition lambda -> C++ condition code (monsters.cpp eval_cond). Mutually exclusive
# pairs (X, !X) are emitted as (X, ALWAYS), which picks the same branch.
ALWAYS = 0
COND = {
    "() => ((Nibbit)base.Creature.Monster).IsAlone": 1,
    "() => ((Nibbit)base.Creature.Monster).IsFront": 2,
    "() => !((Nibbit)base.Creature.Monster).IsFront": 10,
    "() => ((Toadpole)base.Creature.Monster).IsFront": 2,
    "() => !((Toadpole)base.Creature.Monster).IsFront": 10,
    "() => IsOffBalance": 3,
    "() => base.Creature.HasPower<SlumberPower>()": 4,
    "() => GetAllyCount() > 0": 6,
    "() => GetAllyCount() == 0": 7,
    "() => CanFabricate": 21,   # COND_CAN_FABRICATE: living teammates < 4
    "() => CanLay": 22,         # COND_CAN_LAY: living teammates <= 3
    "() => !HasAmalgamDied": 9,
    "() => base.Creature.SlotName == \"first\"": 11,
    "() => base.Creature.SlotName == \"second\"": 12,
    "() => base.Creature.SlotName == \"third\"": 13,
    "() => base.Creature.SlotName == \"fourth\"": 14,
    "() => base.Creature.SlotName == \"wriggler1\"": 11,
    "() => base.Creature.SlotName == \"wriggler2\"": 12,
    "() => base.Creature.SlotName == \"wriggler3\"": 13,
    "() => base.Creature.SlotName == \"wriggler4\"": 14,
    "() => base.Creature.HasPower<AsleepPower>()": 15,
    "() => _curseOfKnowledgeCounter < 3": 16,
    "() => Respawns < 2": 17,
    "() => !HasBeetleCharged && base.Creature.CurrentHp < base.Creature.MaxHp / 2": 18,
}
NEGATIONS = {
    "() => !IsOffBalance": "() => IsOffBalance",
    "() => !base.Creature.HasPower<SlumberPower>()": "() => base.Creature.HasPower<SlumberPower>()",
    "() => !CanFabricate": "() => CanFabricate",
    "() => !CanLay": "() => CanLay",
    "() => HasAmalgamDied": "() => !HasAmalgamDied",
    "() => !base.Creature.HasPower<AsleepPower>()": "() => base.Creature.HasPower<AsleepPower>()",
    "() => _curseOfKnowledgeCounter >= 3": "() => _curseOfKnowledgeCounter < 3",
    "() => Respawns >= 2": "() => Respawns < 2",
    "() => HasBeetleCharged || base.Creature.CurrentHp >= base.Creature.MaxHp / 2":
        "() => !HasBeetleCharged && base.Creature.CurrentHp < base.Creature.MaxHp / 2",
}
# Initial state set by a field (StarterMoveIdx, StartsWithFastPunch, ...): the encounter sets
# it (monsters.cpp native_roster); the table holds the field's default.
EXPR_DEFAULT_INITIAL = {
    "CORPSE_SLUG": "WHIP_SLAP_MOVE",          # _starterMoveIdx = 0
    "DECIMILLIPEDE_SEGMENT": "WRITHE_MOVE",   # _starterMoveIdx = 0
    "SCROLL_OF_BITING": "CHOMP",              # _starterMoveIdx = 0
    "TWO_TAILED_RAT": "RAND",                 # _starterMoveIndex = -1
    "PUNCH_CONSTRUCT": "READY_MOVE",          # _startsWithFastPunch = false
    "INKLET": "JAB_MOVE",                     # _middleInklet = false
}
# Monsters whose moves changed (not just names): every native move's intents and effects
# are rewritten from the native source. Dynamic parts are handled in monsters.cpp.
FULL_PORT = {"AXEBOT", "HAUNTED_SHIP", "SKULKING_COLONY", "CUBEX_CONSTRUCT",
             # effects differ: Radiate block / Pulsate Vital Spark; Fast Punch Frail; Thrash
             # Vigor 6; Spike Spit Thorns -2; Fossil Stalker has Suck (not flat Strength)
             "INFESTED_PRISM", "PUNCH_CONSTRUCT", "TERROR_EEL", "TOADPOLE", "FOSSIL_STALKER",
             "MECHA_KNIGHT"}   # Flamethrower also attacks
# Summon moves implemented in monsters.cpp with the native slot rules and choices (Fabricator
# picks bots on MonsterAi); their table ops (recorded summons) are cleared.
CPP_SUMMON_MOVES = {("FABRICATOR", "FABRICATE_MOVE"), ("FABRICATOR", "FABRICATING_STRIKE_MOVE"),
                    ("OVICOPTER", "LAY_EGGS_MOVE"), ("LIVING_FOG", "BLOAT_MOVE"),
                    ("FOGMOG", "ILLUSION_MOVE"), ("THE_OBSCURA", "ILLUSION_MOVE")}
# Innate powers applied natively in AfterAddedToRoom that the table lacked.
INNATE_POWERS = {"FOSSIL_STALKER": [["SUCK", 3]]}   # FossilStalker.AfterAddedToRoom: SuckPower 3
# AfterAddedToRoom power amounts (A0, A8, A9) that the table had wrong (2026-11-18 audit):
# Vantom.SlipperyAmt (ToughEnemies 9/8), InfestedPrism.VitalSparkAmount (DeadlyEnemies 3/2),
# GlobeHead.GalvanicPowerAmount (DeadlyEnemies 8/6).
INNATE_AMOUNTS = {"VANTOM": {"SLIPPERY": (8, 9, 9)},
                  "INFESTED_PRISM": {"VITAL_SPARK": (2, 2, 3)},
                  "GLOBE_HEAD": {"GALVANIC": (6, 6, 8)}}
# Effect ops whose amount is computed at run time in monsters.cpp (dropped from the table).
CPP_DYNAMIC_OPS = {("AXEBOT", "BOOT_UP_MOVE"): "STRENGTH"}   # BootUpStrGain x RespawnCount
# Effects replaced from native even though handled partly in C++ elsewhere: none by default.
INTENT_TYPES = {"SingleAttack": "ATTACK", "MultiAttack": "MULTI_ATTACK", "DeathBlow": "DEATH_BLOW",
                "Buff": "BUFF", "Debuff": "DEBUFF", "Defend": "DEFEND", "Status": "STATUS_CARD",
                "Summon": "SUMMON", "Stun": "STUN", "Sleep": "SLEEP", "Hidden": "UNKNOWN",
                "Heal": "HEAL", "CardDebuff": "CARD_DEBUFF", "Escape": "ESCAPE"}
# Dynamic weights handled in C++ (monsters.cpp) -- the table keeps the listed default.
DYNAMIC_WEIGHT_MONSTERS = {"TWO_TAILED_RAT"}


def rename_monster(key: str, mon: dict, a9: list[dict]) -> None:
    ren = RENAMES.get(key)
    if not ren or not all(src in mon["states"] for src in ren):
        return                                    # already renamed (the tool is re-runnable)
    r = lambda s: ren.get(s, s)
    for field in ("states", "states8"):
        if field not in mon:
            continue
        mon[field] = {r(k): v for k, v in mon[field].items()}
        for st in mon[field].values():
            if st.get("follow"):
                st["follow"] = r(st["follow"])
            for b in st.get("branches", []):
                b["state"] = r(b["state"])
    for field in ("initial", "initial8"):
        if field in mon:
            mon[field] = [[r(s), w] for s, w in mon[field]]
    mon["moves"] = {f"{r(k.split('@')[0])}@{k.split('@')[1]}": v for k, v in mon.get("moves", {}).items()}
    for table in a9:
        if key in table:
            table[key] = {r(k): v for k, v in table[key].items()}


def native_reachable(n: dict, key: str) -> set:
    init = n["initial"]
    if isinstance(init, str):
        todo = [init]
    else:
        todo = list(init.get("vars", {}).values())
    if key in EXPR_DEFAULT_INITIAL:
        todo.append(EXPR_DEFAULT_INITIAL[key])
    for sid, st in n["states"].items():      # DeadState-style entries reached from C# code
        if sid in ("RESPAWN_MOVE", "DEAD_MOVE", "REATTACH_MOVE"):
            todo.append(sid)
    seen = set()
    while todo:
        sid = todo.pop()
        if sid in seen or sid not in n["states"]:
            continue
        seen.add(sid)
        st = n["states"][sid]
        if st.get("follow"):
            todo.append(st["follow"])
        todo += [b["state"] for b in st.get("branches", [])]
    return seen


def native_intents(st: dict, props: dict, asc: int) -> list:
    out = []
    for i in st["intents"]:
        t = INTENT_TYPES.get(i["type"], "UNKNOWN")
        if "damage" in i:
            d = nai.resolve(i["damage"], props, asc)
            h = nai.resolve(i.get("hits", 1), props, asc) if i["type"] == "MultiAttack" else 1
            if d is None or h is None:
                raise SystemExit(f"unresolved attack intent {i}")
            out.append({"type": t, "damage": d, "hits": h})
        elif t == "STATUS_CARD":
            n = nai.resolve((i.get("args") or ["1"])[0], props, asc)
            out.append({"type": t, "damage": 0, "hits": n if n is not None else 1})
        else:
            out.append({"type": t, "damage": 0, "hits": 1})
    return out


def native_ops(src: str, st: dict, props: dict, asc: int, drop_power: str | None = None) -> list:
    body = nai.method_text(src, st["fn"]) if st.get("fn") else None
    if body is None:
        raise SystemExit(f"no native body for {st.get('fn')}")
    ops = []
    for op in nai.native_effects(body, props, asc):
        if drop_power and op[0] == "power" and op[2] == drop_power:
            continue
        if any(isinstance(v, str) and not v.isupper() and v not in ("discard", "draw", "hand", "S", "P", "O")
               for v in op[1:]):
            raise SystemExit(f"unresolved native effect {op} in {st.get('fn')}")
        if op[0] == "card":
            ops += [["card", op[1], op[2], 1]] * int(op[3])
        else:
            ops.append(op)
    return ops


def numeric(w):
    try:
        return float(w)
    except (TypeError, ValueError):
        return None


def apply(dry: bool) -> None:
    native = nai.parse_all()
    data = json.loads((CONTENT / "monsters.json").read_text())
    a9d = json.loads((CONTENT / "monsters_a9_damage.json").read_text())
    a9h = json.loads((CONTENT / "monsters_a9_hits.json").read_text())
    a9e = json.loads((CONTENT / "monsters_a9_effects.json").read_text())
    applied, manual, log = [], [], []
    for key, mon in data["monsters"].items():
        rename_monster(key, mon, [a9d, a9h, a9e["moves"]])
        n = native.get(key)
        if n is None:
            continue
        ns = n["states"]
        reach = native_reachable(n, key)
        missing = [sid for sid in ns if sid in reach and sid not in mon["states"]]
        unported = [sid for sid in missing if ns[sid]["kind"] == "MoveState" and key not in FULL_PORT]
        if unported:
            manual.append((key, sorted(set(mon["states"]) - set(ns)), unported))
            continue
        for sid in missing:                       # new branch states (no effects) or FULL_PORT moves
            kind = {"MoveState": "move", "RandomBranchState": "random", "ConditionalBranchState": "cond"}[ns[sid]["kind"]]
            for field in ("states", "states8"):
                if field in mon:
                    mon[field][sid] = ({"kind": "move", "intents": [], "follow": None, "once": False}
                                       if kind == "move" else {"kind": kind, "branches": []})
            log.append(f"{key}: added native state {sid} ({kind})")
        if key in FULL_PORT:
            src = (nai.NATIVE / "Models" / "Monsters").glob("*.cs")
            src = next(f.read_text() for f in src if nai.slug(f.stem) == key)
            for sid, nst in ns.items():
                if nst["kind"] != "MoveState" or sid not in mon["states"]:
                    continue
                drop = CPP_DYNAMIC_OPS.get((key, sid))
                for field, lvl, tag in (("states", 0, "A0"), ("states8", 8, "A8")):
                    if field in mon:
                        mon[field][sid]["intents"] = native_intents(nst, n["props"], lvl)
                        mon[field][sid]["follow"] = nst.get("follow")
                    mon.setdefault("moves", {})[f"{sid}@{tag}"] = native_ops(src, nst, n["props"], lvl, drop)
                ops9 = native_ops(src, nst, n["props"], 9, drop)
                ops8 = mon["moves"][f"{sid}@A8"]
                deltas = {str(i): o9[-1] for i, (o8, o9) in enumerate(zip(ops8, ops9)) if o8 != o9}
                if deltas:
                    a9e["moves"].setdefault(key, {})[sid] = deltas
                elif sid in a9e["moves"].get(key, {}):
                    del a9e["moves"][key][sid]
                log.append(f"{key}.{sid}: full port {mon['states'][sid]['intents']} ops {mon['moves'][sid + '@A0']}")
        props = n["props"]
        for field in ("states", "states8"):
            for sid, st in (mon.get(field) or {}).items():
                if sid not in ns or sid not in reach:
                    continue                      # ours only, or unreachable in native: left as is
                nst = ns[sid]
                kind = {"MoveState": "move", "RandomBranchState": "random", "ConditionalBranchState": "cond"}[nst["kind"]]
                if kind != st["kind"]:
                    log.append(f"{key}.{sid}: kind {st['kind']} -> {kind} (left for manual port)")
                    continue
                if kind == "move":
                    if nst.get("follow") and nst["follow"] != st.get("follow"):
                        log.append(f"{key}.{sid}: follow {st.get('follow')} -> {nst['follow']}")
                        st["follow"] = nst["follow"]
                    attacks = [i for i in nst["intents"] if "damage" in i]
                    ours = [i for i in st.get("intents", []) if "ATTACK" in i["type"] or i["type"] == "DEATH_BLOW"]
                    lvl = 8 if field == "states8" else 0
                    for a, o in zip(attacks, ours):
                        d = nai.resolve(a["damage"], props, lvl)
                        h = nai.resolve(a.get("hits", 1), props, lvl) if a["type"] == "MultiAttack" else 1
                        if d is not None and d != o["damage"]:
                            log.append(f"{key}.{sid}@A{lvl}: damage {o['damage']} -> {d}")
                            o["damage"] = d
                        if h is not None and h != o["hits"]:
                            log.append(f"{key}.{sid}@A{lvl}: hits {o['hits']} -> {h}")
                            o["hits"] = h
                        if field == "states":
                            # roll_intent uses the A9 table at A9+, else the A8 intents
                            d8, d9 = nai.resolve(a["damage"], props, 8), nai.resolve(a["damage"], props, 9)
                            h8 = nai.resolve(a.get("hits", 1), props, 8) if a["type"] == "MultiAttack" else 1
                            h9 = nai.resolve(a.get("hits", 1), props, 9) if a["type"] == "MultiAttack" else 1
                            if d9 is not None and d9 != d8:
                                if a9d.get(key, {}).get(sid) != d9:
                                    log.append(f"{key}.{sid}: A9 damage {a9d.get(key, {}).get(sid)} -> {d9}")
                                a9d.setdefault(key, {})[sid] = d9
                            elif d9 is not None and sid in a9d.get(key, {}):
                                log.append(f"{key}.{sid}: A9 damage override {a9d[key][sid]} removed (A9 = A8 = {d9})")
                                del a9d[key][sid]
                            if h9 is not None and h9 != h8:
                                a9h.setdefault(key, {})[sid] = h9
                            elif h9 is not None and sid in a9h.get(key, {}):
                                del a9h[key][sid]
                elif kind == "random":
                    new = []
                    for b in nst["branches"]:
                        w = numeric(b["weight"])
                        if w is None and key in DYNAMIC_WEIGHT_MONSTERS:
                            w = 1.0                   # placeholder: monsters.cpp computes it
                        if w is None:
                            raise SystemExit(f"{key}.{sid}: non-numeric weight {b['weight']!r}")
                        new.append({"state": b["state"], "repeat": b["repeat"], "max": b["max"],
                                    "weight": w, "cooldown": b["cooldown"]})
                    old = [(b["state"], b["repeat"], b["max"] if b["repeat"] == "CAN_REPEAT_X_TIMES" else 1,
                            float(b["weight"]), b["cooldown"]) for b in st["branches"]]
                    if old != [(b["state"], b["repeat"], b["max"] if b["repeat"] == "CAN_REPEAT_X_TIMES" else 1,
                                b["weight"], b["cooldown"]) for b in new]:
                        log.append(f"{key}.{sid}: branches {old} -> {[(b['state'], b['repeat'], b['max'], b['weight'], b['cooldown']) for b in new]}")
                    st["branches"] = new
                else:
                    new = []
                    for b in nst["branches"]:
                        c = b["cond"]
                        if c in COND:
                            new.append({"state": b["state"], "cond_code": COND[c], "cond": c})
                        elif c in NEGATIONS and NEGATIONS[c] in [x["cond"] for x in nst["branches"]]:
                            new.append({"state": b["state"], "cond_code": ALWAYS, "cond": c})
                        else:
                            raise SystemExit(f"{key}.{sid}: unmapped condition {c!r}")
                    # (!X, X) pairs: X first, then ALWAYS for !X (exclusive, same choice)
                    new.sort(key=lambda x: x["cond_code"] == ALWAYS)
                    if [b["state"] for b in st["branches"]] != [b["state"] for b in new]:
                        log.append(f"{key}.{sid}: cond targets {[b['state'] for b in st['branches']]} -> {[b['state'] for b in new]}")
                    st["branches"] = new
        init = n["initial"] if isinstance(n["initial"], str) else EXPR_DEFAULT_INITIAL.get(key)
        if init:
            for field in ("initial", "initial8"):
                if field in mon and mon[field] != [[init, 1]]:
                    if field == "initial":
                        log.append(f"{key}: initial {mon[field]} -> {[[init, 1]]}")
                    mon[field] = [[init, 1]]
        for (mk, sid) in CPP_SUMMON_MOVES:
            if mk == key:
                for tag in ("A0", "A8"):
                    if mon["moves"].get(f"{sid}@{tag}"):
                        log.append(f"{key}.{sid}@{tag}: summon ops {mon['moves'][f'{sid}@{tag}']} -> [] (monsters.cpp)")
                    mon["moves"][f"{sid}@{tag}"] = []
                a9e["moves"].get(key, {}).pop(sid, None)
        for pname, amount in INNATE_POWERS.get(key, []):
            for anc in ("A0", "A8"):
                pw = mon.setdefault("powers", {}).setdefault(anc, [])
                if [pname, amount] not in pw:
                    pw.append([pname, amount])
                    log.append(f"{key}: innate {pname} {amount} at {anc}")
        for pname, (a0, a8, a9) in INNATE_AMOUNTS.get(key, {}).items():
            for anc, amount in (("A0", a0), ("A8", a8)):
                pw = mon.setdefault("powers", {}).setdefault(anc, [])
                for entry in pw:
                    if entry[0] == pname and entry[1] != amount:
                        log.append(f"{key}: innate {pname} {entry[1]} -> {amount} at {anc}")
                        entry[1] = amount
            inn = a9e.setdefault("innate", {})
            if a9 != a8:
                inn.setdefault(key, {})[pname] = a9
            elif pname in inn.get(key, {}):
                del inn[key][pname]
        applied.append(key)
    print(f"applied to {len(applied)} monsters; manual port needed for {len(manual)}:")
    for m in manual:
        print("  ", m)
    print("\n".join(log))
    if dry:
        return
    (CONTENT / "monsters.json").write_text(json.dumps(data, indent=1) + "\n")
    for name, table in (("monsters_a9_damage.json", a9d), ("monsters_a9_hits.json", a9h), ("monsters_a9_effects.json", a9e)):
        (CONTENT / name).write_text(json.dumps({k: v for k, v in table.items() if v != {}} if name != "monsters_a9_effects.json" else table, indent=2, sort_keys=True) + "\n")
    subprocess.run([sys.executable, str(ROOT / "tools" / "gen_monsters.py")], check=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    apply(ap.parse_args().dry_run)
