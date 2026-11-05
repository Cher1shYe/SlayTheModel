"""Generate C++ monster/encounter tables from content/monsters.json.

    python simulator/tools/gen_monsters.py

Output is included twice by common.h (enums) and monsters.cpp (tables) behind
STS2_MONSTER_CONTENT_ENUMS.
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "content" / "monsters.json"
OUT = ROOT / "include" / "sts2" / "monsters_generated.inc"

INTENT_CODES = {
    "ATTACK": 0, "MULTI_ATTACK": 0, "DEATH_BLOW": 0,
    "DEFEND": 1, "BUFF": 2, "DEBUFF": 3, "DEBUFF_STRONG": 3, "CARD_DEBUFF": 3,
    "STATUS_CARD": 4, "SLEEP": 5, "SUMMON": 6, "HEAL": 7, "STUN": 8,
    "ESCAPE": 9, "UNKNOWN": 2,
}
REPEAT_CODES = {
    "CAN_REPEAT_FOREVER": 0, "CANNOT_REPEAT": 1,
    "CAN_REPEAT_X_TIMES": 2, "USE_ONLY_ONCE": 3,
}


def cond_code(src: str) -> int:
    s = src.replace(" ", "")
    # Specific conditions first: some of them also contain "max_hp//2".
    if "FROG_KNIGHT_BEETLE_CHARGED_KEY" in s:
        return 18
    if "KNOWLEDGE_DEMON_CURSE_COUNTER_KEY" in s:
        return 16
    if "TEST_SUBJECT_RESPAWNS_KEY" in s:
        return 17
    if "WRIGGLER_BITE_SLOTS" in s:
        return 19
    if "WRIGGLER_WRIGGLE_SLOTS" in s:
        return 20
    if "PowerId.ASLEEP" in s:
        return 15
    if "is_alone" in s:
        return 1
    if "notis_front" in s:
        return 10
    if "is_front" in s:
        return 2
    if "off_balance" in s:
        return 3
    if "SLUMBER" in s:
        return 4
    if "max_hp//2" in s or "max_hp/2" in s:
        return 5
    if "ally_count_fn()>0" in s:
        return 6
    if "ally_count_fn()==0" in s:
        return 7
    if "can_lay" in s or "can_summon" in s or "_can_fabricate" in s:
        return 8
    if "TORCH_HEAD_AMALGAM" in s:
        return 9
    if 'slot=="first"' in s:
        return 11
    if 'slot=="second"' in s:
        return 12
    if 'slot=="third"' in s:
        return 13
    if 'slot=="fourth"' in s:
        return 14
    # Explicit "always" branches are only the literal True predicates.
    if "lambda:True" in s and "add_branch" in s:
        return 0
    raise ValueError(f"unrecognised monster branch condition: {src!r}")


def cstr(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    monsters = data["monsters"]
    deadly_damage = json.loads((ROOT / "content" / "monsters_a9_damage.json").read_text(encoding="utf-8"))
    deadly_hits = json.loads((ROOT / "content" / "monsters_a9_hits.json").read_text(encoding="utf-8"))
    deadly_effects = json.loads((ROOT / "content" / "monsters_a9_effects.json").read_text(encoding="utf-8"))
    encounter_tags = json.loads((ROOT / "content" / "encounter_tags.json").read_text(encoding="utf-8"))
    tag_names = sorted({tag for tags in encounter_tags.values() for tag in tags})
    if len(tag_names) > 16:
        raise ValueError("encounter tag mask exceeds 16 bits")
    tag_bits = {name: 1 << i for i, name in enumerate(tag_names)}
    ids = sorted(monsters)
    index = {name: i + 1 for i, name in enumerate(ids)}

    # encounters: merge the A0/A8 probes, keeping distinct roster patterns
    encs = {}
    for key, info in data["encounters"].items():
        if not key.endswith("@A0"):
            continue
        name = key[:-3]
        encs[name] = info
    enc_order = sorted(encs, key=lambda n: (encs[n]["act"], n))
    # Current native 41cef1ea has this Underdocks encounter; the historical
    # extracted table did not. Append to preserve every existing encounter ID.
    encs["setup_seapunk_normal"] = {
        "act": "act4", "rosters": [[["CALCIFIED_CULTIST", "SEAPUNK"], 1]]
    }
    encounter_tags["setup_seapunk_normal"] = ["Seapunk"]
    enc_order.append("setup_seapunk_normal")
    enc_index = {n: i + 1 for i, n in enumerate(enc_order)}

    intents = []
    ops = []
    branches = []
    conds = []
    states = []
    defs = []
    innate = []
    initials = []
    patterns = []

    for mid in ids:
        m = monsters[mid]
        names = list(m["states"].keys())
        sidx = {n: i for i, n in enumerate(names)}
        state_off = len(states)
        hp0 = m["hp"].get("A0") or m["hp"].get("A8") or [20, 20]
        hp8 = m["hp"].get("A8") or hp0
        pow_off = [len(innate), len(innate)]
        pow_n = [0, 0]
        for ai, anc in enumerate(("A0", "A8")):
            pow_off[ai] = len(innate)
            entries = m.get("powers", {}).get(anc) or m.get("powers", {}).get("A0") or []
            for pname, amount in entries:
                innate.append((pname, int(amount), deadly_effects["innate"].get(mid, {}).get(pname, -1)))
                pow_n[ai] += 1
        init_off = len(initials)
        observed = [sidx.get(sname, 0) for sname, _w in m["initial"]]
        follows = {st.get("follow") for st in m["states"].values() if st["kind"] == "move"}
        override = None
        for sname, st in m["states"].items():
            if st["kind"] != "cond" or sname in follows:
                continue
            targets = [b["state"] for b in st["branches"]]
            if any(t in m["states"] and sidx.get(t) in observed for t in targets):
                override = sidx[sname]
                break
        if override is not None:
            initials.append((override, 1))
        else:
            for sname, weight in m["initial"]:
                initials.append((sidx.get(sname, 0), int(weight)))
        init_n = len(initials) - init_off

        for sname in names:
            st = m["states"][sname]
            kind = st["kind"]
            if kind == "move":
                upper = sname.upper()
                aux_code = 0
                if upper == "CURSE_OF_KNOWLEDGE_MOVE":
                    aux_code = 1
                elif upper == "BEETLE_CHARGE":
                    aux_code = 2
                elif upper == "MULTI_CLAW_MOVE":
                    aux_code = 3
                elif upper == "RESPAWN_MOVE":
                    aux_code = 4
                intent_off = [0, 0]
                intent_n = [0, 0]
                a9 = deadly_damage.get(mid, {}).get(sname, -1)
                hits9 = deadly_hits.get(mid, {}).get(sname, -1)
                intent_off[0] = len(intents)
                for it in st["intents"]:
                    intents.append((INTENT_CODES.get(it["type"], 2),
                                    int(it["damage"]), int(it["hits"]),
                                    a9 if INTENT_CODES.get(it["type"], 2) == 0 else -1,
                                    hits9 if INTENT_CODES.get(it["type"], 2) == 0 else -1))
                intent_n[0] = len(intents) - intent_off[0]
                st8 = (m.get("states8") or {}).get(sname)
                src8 = st8["intents"] if st8 and st8.get("kind") == "move" else st["intents"]
                intent_off[1] = len(intents)
                for it in src8:
                    intents.append((INTENT_CODES.get(it["type"], 2),
                                    int(it["damage"]), int(it["hits"]),
                                    a9 if INTENT_CODES.get(it["type"], 2) == 0 else -1,
                                    hits9 if INTENT_CODES.get(it["type"], 2) == 0 else -1))
                intent_n[1] = len(intents) - intent_off[1]
                op_off = [len(ops), len(ops)]
                op_n = [0, 0]
                for ai, anc in enumerate(("A0", "A8")):
                    op_off[ai] = len(ops)
                    for op_index, op in enumerate(m["moves"].get(f"{sname}@{anc}") or []):
                        if op[0] == "block":
                            ops.append((1, int(op[1]), 0))
                        elif op[0] == "power":
                            role = {"P": 3, "S": 2, "O": 9}.get(op[1], 9)
                            power = op[2]
                            ops.append((role, power, int(op[3])))
                        elif op[0] == "card":
                            pile = {"discard": 4, "draw": 5, "hand": 6}[op[1]]
                            ops.append((pile, op[2], 1))
                        elif op[0] == "heal":
                            ops.append((7, int(op[1]), 0))
                        elif op[0] == "summon":
                            ops.append((8, op[1], 0))
                        elif op[0] == "lose_hp":
                            ops.append((10, int(op[1]), 0))
                        else:
                            continue
                        value9 = deadly_effects["moves"].get(mid, {}).get(sname, {}).get(str(op_index), -1)
                        ops[-1] = (*ops[-1], value9)
                        op_n[ai] += 1
                states.append({
                    "kind": 0, "once": 1 if st.get("once") else 0,
                    "follow": sidx.get(st.get("follow"), 255),
                    "intent_off": intent_off, "intent_n": intent_n,
                    "branch_off": 0, "branch_n": 0,
                    "op_off": op_off, "op_n": op_n,
                    "aux_code": aux_code,
                })
            elif kind in ("random", "cond"):
                br_off = len(branches if kind == "random" else conds)
                for b in st["branches"]:
                    if kind == "random":
                        branches.append((sidx.get(b["state"], 0),
                                         REPEAT_CODES.get(b["repeat"], 0),
                                         int(b["max"]),
                                         int(round(float(b["weight"]) * 10)),
                                         int(b["cooldown"])))
                    else:
                        conds.append((cond_code(b["cond"]),
                                      sidx.get(b["state"], 0)))
                states.append({
                    "kind": 1 if kind == "random" else 2, "once": 0,
                    "follow": 255, "intent_off": [0, 0], "intent_n": [0, 0],
                    "branch_off": br_off, "branch_n": len(st["branches"]),
                    "op_off": [0, 0], "op_n": [0, 0], "aux_code": 0,
                })
            else:
                raise SystemExit(f"unknown state kind {kind} in {mid}/{sname}")

        revive_state = next((sidx[sname] for sname in names
                             if "RESPAWN" in sname.upper()), 255)
        multi_claw_state = next((sidx[sname] for sname in names
                                 if sname.upper() == "MULTI_CLAW_MOVE"), 255)
        defs.append((mid, hp0, hp8, state_off, len(names),
                     pow_off, pow_n, init_off, init_n, revive_state,
                     multi_claw_state))

    for ename in enc_order:
        info = encs[ename]
        pat_off = len(patterns)
        for roster, count in info["rosters"]:
            if len(roster) > 4 or len(roster) == 0:
                continue
            patterns.append((tuple(index[i] for i in roster), int(count)))
        defs.append(("__enc__", ename, int(str(info["act"])[-1]), pat_off,
                     len(patterns) - pat_off))

    lines = ["// generated by simulator/tools/gen_monsters.py -- do not edit", ""]
    lines.append("#ifdef STS2_MONSTER_CONTENT_ENUMS")
    lines.append("enum class MonsterId : std::uint16_t {")
    lines.append("    INVALID = 0,")
    for mid in ids:
        lines.append(f"    {mid},")
    lines.append("    COUNT")
    lines.append("};")
    lines.append("")
    lines.append("enum class Encounter : std::uint16_t {")
    lines.append("    INVALID = 0,")
    for ename in enc_order:
        lines.append(f"    {ename.upper()},")
    lines.append("    COUNT")
    lines.append("};")
    lines.append("#else")
    lines.append("// clang-format off")

    lines.append("constexpr MonIntentDef MON_INTENTS[] = {")
    for t, d, h, a9, h9 in intents:
        lines.append(f"    {{{t}, {d}, {h}, {a9}, {h9}}},")
    if not intents:
        lines.append("    {0, 0, 0, -1, -1},")
    lines.append("};")

    def op_expr(code, a):
        if isinstance(a, str):
            if code in (2, 3, 9):
                return f"static_cast<int>(PowerId::{a})"
            if code in (4, 5, 6):
                return f"static_cast<int>(CardId::{a})"
            if code == 8:
                return f"static_cast<int>(MonsterId::{a})"
        return str(a)

    lines.append("constexpr MonOpDef MON_OPS[] = {")
    for op, a, b, a9 in ops:
        lines.append(f"    {{{op}, {op_expr(op, a)}, {b}, {a9}}},")
    if not ops:
        lines.append("    {0, 0, 0, -1},")
    lines.append("};")

    lines.append("constexpr MonBranchDef MON_BRANCHES[] = {")
    for st, rep, mx, w, cd in branches:
        lines.append(f"    {{{st}, {rep}, {mx}, {cd}, {w}}},")
    if not branches:
        lines.append("    {0, 0, 1, 0, 10},")
    lines.append("};")

    lines.append("constexpr MonCondDef MON_CONDS[] = {")
    for cd, st in conds:
        lines.append(f"    {{{cd}, {st}}},")
    if not conds:
        lines.append("    {0, 0},")
    lines.append("};")

    lines.append("constexpr MonStateDef MON_STATES[] = {")
    for s in states:
        lines.append(
            "    {%d, %d, %d, {%d, %d}, {%d, %d}, {%d, %d}, {%d, %d}, %d, %d, %d},"
            % (s["kind"], s["once"], s["follow"],
               s["intent_off"][0], s["intent_off"][1],
               s["intent_n"][0], s["intent_n"][1],
               s["op_off"][0], s["op_off"][1],
               s["op_n"][0], s["op_n"][1],
               s["branch_off"], s["branch_n"], s.get("aux_code", 0)))
    lines.append("};")

    lines.append("constexpr MonPowerDef MON_INNATE[] = {")
    for name, amount, a9 in innate:
        lines.append(f"    {{PowerId::{name}, {amount}, {a9}}},")
    if not innate:
        lines.append("    {PowerId::COUNT, 0, -1},")
    lines.append("};")

    lines.append("constexpr MonInitialDef MON_INITIALS[] = {")
    for st, w in initials:
        lines.append(f"    {{{st}, {w}}},")
    if not initials:
        lines.append("    {0, 1},")
    lines.append("};")

    lines.append("constexpr MonsterDef MONSTER_DEFS[] = {")
    lines.append("    {nullptr, {0, 0}, {0, 0}, {0, 0}, {0, 0}, 0, 0, 0, 0, 255, 255},")
    for d in defs:
        if len(d) != 11:
            continue
        mid, hp0, hp8, soff, scount, poff, pn, ioff, inum, revive, multi = d
        lines.append(
            "    {%s, {%d, %d}, {%d, %d}, {%d, %d}, {%d, %d}, %d, %d, %d, %d, %d, %d},"
            % (cstr(mid), hp0[0], hp8[0], hp0[1], hp8[1],
               poff[0], poff[1], pn[0], pn[1], soff, scount, ioff, inum,
               revive if revive is not None else 255,
               multi if multi is not None else 255))
    lines.append("};")

    lines.append("constexpr EncounterPattern ENC_PATTERNS[] = {")
    for ids_t, weight in patterns:
        pad = list(ids_t) + [0] * (4 - len(ids_t))
        lines.append("    {%d, {%s}, %d}," % (len(ids_t), ", ".join(map(str, pad)), weight))
    if not patterns:
        lines.append("    {0, {0, 0, 0, 0}, 1},")
    lines.append("};")

    lines.append("constexpr EncounterDef ENCOUNTER_DEFS[] = {")
    lines.append("    {nullptr, 0, 0, 0, 0},")
    for _tag, ename, act, poff, pnum in [d for d in defs if d[0] == "__enc__"]:
        tags = sum(tag_bits[tag] for tag in encounter_tags.get(ename, []))
        lines.append("    {%s, %d, %d, %d, %d}," % (cstr(ename.upper()), act, poff, pnum, tags))
    lines.append("};")

    lines.append("static_assert(sizeof(MONSTER_DEFS) / sizeof(MONSTER_DEFS[0]) =="
                 " static_cast<int>(MonsterId::COUNT), \"monster table size\");")
    lines.append("static_assert(sizeof(ENCOUNTER_DEFS) / sizeof(ENCOUNTER_DEFS[0]) =="
                 " static_cast<int>(Encounter::COUNT), \"encounter table size\");")
    lines.append("// clang-format on")
    lines.append("#endif")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(ids)} monsters, {len(enc_order)} encounters")


if __name__ == "__main__":
    main()
