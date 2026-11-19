"""Dump STS2 monster AI graphs + move effects from the reference Python engine.

Run with the reference venv:
    python simulator/tools/dump_monsters.py --ref <sts2-rl-agent> --out simulator/content/monsters.json

The reference monster AI is data (states/intents/branches) plus per-move Python
closures.  This script serialises the data and *records* each move's primitive
effects (damage comes from the intent, effects from these ops) so the C++ port
can replay them without hand-translating 106 monsters.
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import re
import sys
import textwrap
from collections import Counter, defaultdict


def collect_setups(act_mods):
    out = {}
    for act_name, mod in act_mods.items():
        for name in dir(mod):
            if not name.startswith("setup_"):
                continue
            fn = getattr(mod, name)
            if callable(fn):
                out[name] = (act_name, mod, fn)
    return out


def state_spec(state):
    from sts2_env.monsters.state_machine import (
        ConditionalBranchState, MoveState, RandomBranchState,
    )

    if isinstance(state, MoveState):
        return {
            "kind": "move",
            "intents": [
                {"type": i.intent_type.name, "damage": int(i.damage), "hits": int(i.hits)}
                for i in state.intents
            ],
            "follow": state.follow_up_id,
            "once": bool(state.must_perform_once),
        }
    if isinstance(state, RandomBranchState):
        branches = []
        for b in state.branches:
            weight = b.base_weight
            if callable(weight):
                try:
                    weight = float(weight())
                except Exception:
                    weight = 1.0
            branches.append({
                "state": b.state_id,
                "repeat": b.repeat_type.name,
                "max": int(b.max_times),
                "weight": float(weight),
                "cooldown": int(b.cooldown),
            })
        return {"kind": "random", "branches": branches}
    if isinstance(state, ConditionalBranchState):
        branches = []
        for cond, target in state.branches:
            try:
                src = inspect.getsource(cond).strip()
            except Exception:
                src = ""
            branches.append({"cond": src, "state": target})
        return {"kind": "cond", "branches": branches}
    return {"kind": "other"}


def _resolve_const(node, mod):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return node.value
    if isinstance(node, ast.Name):
        return getattr(mod, node.id)
    raise ValueError(f"cannot resolve {ast.dump(node)}")


def _asc_pair(expr, mod):
    """(A0, A8) for an HP expression: literal/constant or _ascension_value(...)."""
    if isinstance(expr, ast.Call) and getattr(expr.func, "id", None) == "_ascension_value":
        base = int(_resolve_const(expr.args[3], mod))
        tough = int(_resolve_const(expr.args[2], mod))
        return base, tough
    value = int(_resolve_const(expr, mod))
    return value, value


def static_hp(fn, mod):
    """Exact (A0 min, A0 max, A8 min, A8 max) parsed from the creator source.

    The reference writes HP as literals or module constants, so sampling is
    unnecessary and cannot miss range endpoints.
    """
    try:
        src = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(src)
    except Exception:
        return None
    assigns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(
            node.targets[0], ast.Name
        ):
            assigns[node.targets[0].id] = node.value
    try:
        if "hp" in assigns:
            a0, a8 = _asc_pair(assigns["hp"], mod)
            return a0, a0, a8, a8
        if "min_hp" in assigns and "max_hp" in assigns:
            lo0, lo8 = _asc_pair(assigns["min_hp"], mod)
            hi0, hi8 = _asc_pair(assigns["max_hp"], mod)
            return lo0, hi0, lo8, hi8
    except Exception:
        return None
    return None


def creator_monster_id(fn, mod):
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except Exception:
        return None
    m = re.search(r"monster_id\s*=\s*([A-Za-z0-9_]+|\"[^\"]+\"|'[^']+')", src)
    if not m:
        return None
    token = m.group(1)
    if token[0] in "\"'":
        return token[1:-1]
    return getattr(mod, token, None)


def classify_condition(src: str) -> str:
    s = src.replace(" ", "")
    if "is_alone" in s:
        return "alone"
    if "is_front" in s:
        return "front"
    if "off_balance" in s or "offbalance" in s:
        return "off_balance"
    if "SLUMBER" in s:
        return "slumber"
    if "max_hp//2" in s or "max_hp//2" in s or "max_hp/2" in s:
        return "half_hp"
    if "ally_count_fn()>0" in s:
        return "has_ally"
    if "ally_count_fn()==0" in s:
        return "no_ally"
    if "can_lay" in s or "can_summon" in s or "_can_fabricate" in s:
        return "can_summon"
    return "always"


def install_recorders(world, enemy):
    from sts2_env.core import combat as combat_mod
    from sts2_env.core import creature as creature_mod

    ops = []
    originals = {}

    def role(c):
        if c is world.primary_player:
            return "P"
        if c is enemy:
            return "S"
        return "O"

    def wrap_apply_power(orig):
        def wrapper(self, power_id, amount, *a, **k):
            try:
                name = getattr(power_id, "name", str(power_id))
                ops.append(["power", role(self), name, int(amount)])
            except Exception:
                pass
            return orig(self, power_id, amount, *a, **k)
        return wrapper

    def wrap_gain_block(orig):
        def wrapper(self, amount, *a, **k):
            if role(self) == "S" and int(amount) > 0:
                ops.append(["block", int(amount)])
            return orig(self, amount, *a, **k)
        return wrapper

    def wrap_heal(orig):
        def wrapper(self, amount, *a, **k):
            if role(self) == "S":
                ops.append(["heal", int(amount)])
            return orig(self, amount, *a, **k)
        return wrapper

    def wrap_lose_hp(orig):
        def wrapper(self, amount, *a, **k):
            if role(self) == "S":
                ops.append(["lose_hp", int(amount)])
            return orig(self, amount, *a, **k)
        return wrapper

    def wrap_add_card(kind):
        def wrap(orig):
            def wrapper(self, target, card, *a, **k):
                try:
                    if card is not None and role(target) == "P":
                        ops.append(["card", kind, str(card.card_id.name), 1])
                except Exception:
                    pass
                return orig(self, target, card, *a, **k)
            return wrapper
        return wrap

    def wrap_add_enemy(orig):
        def wrapper(self, creature, ai, *a, **k):
            try:
                ops.append(["summon", str(creature.monster_id)])
            except Exception:
                pass
            return orig(self, creature, ai, *a, **k)
        return wrapper

    targets = [
        (creature_mod.Creature, "apply_power", wrap_apply_power),
        (creature_mod.Creature, "gain_block", wrap_gain_block),
        (creature_mod.Creature, "heal", wrap_heal),
        (creature_mod.Creature, "lose_hp", wrap_lose_hp),
        (combat_mod.CombatState, "add_generated_card_to_creature_discard", wrap_add_card("discard")),
        (combat_mod.CombatState, "add_generated_card_to_creature_hand", wrap_add_card("hand")),
        (combat_mod.CombatState, "add_generated_card_to_creature_draw_pile", wrap_add_card("draw")),
        (combat_mod.CombatState, "add_enemy", wrap_add_enemy),
    ]
    for cls, name, make in targets:
        orig = getattr(cls, name)
        originals[(cls, name)] = orig
        setattr(cls, name, make(orig))
    return ops, originals


def restore(originals):
    for (cls, name), orig in originals.items():
        setattr(cls, name, orig)


def record_move(asc, setup, seed, slot, move_id):
    from sts2_env.core.combat import CombatState
    from sts2_env.core.rng import Rng

    world = CombatState(80, 80, [], seed, relics=[], potions=[], character_id="Ironclad",
                        ascension_level=asc)
    setup(world, Rng(seed))
    world.start_combat()
    if slot >= len(world.enemies):
        return ["unsupported"]
    enemy = world.enemies[slot]
    ai = world.enemy_ais[enemy.combat_id]
    state = ai.states[move_id]
    ops, originals = install_recorders(world, enemy)
    try:
        state.perform(world)
    except Exception as exc:  # noqa: BLE001 - report unsupported effects
        ops.append(["error", type(exc).__name__])
    finally:
        restore(originals)
    # Attacks are driven by the intent table; drop recorded HP loss from attacks.
    cleaned = []
    for op in ops:
        if op[0] == "power" and op[1] == "S" and op[2] in ("STRENGTH",):
            pass
        cleaned.append(op)
    return cleaned


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=512)
    args = ap.parse_args()
    sys.path.insert(0, args.ref)

    from sts2_env.core.rng import Rng
    from sts2_env.encounters import act1 as _act1  # noqa: F401 - fixes import order
    from sts2_env.core.combat import CombatState
    from sts2_env.encounters import act1, act2, act3, act4, events as event_encounters
    from sts2_env.monsters import act1 as m1, act1_weak, act2 as m2, act3 as m3, act4 as m4

    act_mods = {"act1": act1, "act2": act2, "act3": act3, "act4": act4, "act0": event_encounters}
    setups = collect_setups(act_mods)

    # Exact HP ranges from the creator source (no sampling of endpoints).
    hp_variants = defaultdict(list)
    for mod in (m1, act1_weak, m2, m3, m4):
        for name in dir(mod):
            if not name.startswith("create_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            mid = creator_monster_id(fn, mod)
            hp = static_hp(fn, mod)
            if mid and hp:
                hp_variants[mid].append((name, hp))


    monsters = {}
    encounters = {}

    for setup_name, (act_name, mod, setup) in sorted(setups.items()):
        for asc in (0, 8):
            rosters = Counter()
            for seed in range(args.seeds):
                try:
                    world = CombatState(80, 80, [], seed, relics=[], potions=[], character_id="Ironclad",
                                        ascension_level=asc)
                    setup(world, Rng(seed))
                    world.start_combat()
                except Exception as exc:
                    if setup_name.endswith("shrinker_beetle_weak") and seed == 0:
                        print("setup failed", setup_name, repr(exc))
                    continue
                roster = tuple(enemy.monster_id for enemy in world.enemies)
                if not roster:
                    continue
                rosters[roster] += 1
                for slot, enemy in enumerate(world.enemies):
                    mid = enemy.monster_id
                    info = monsters.setdefault(mid, {
                        "id": mid, "hp": {}, "states": {}, "states8": {},
                        "initial": Counter(), "initial8": Counter(),
                        "moves": {}, "variants": set(), "powers": {},
                    })
                    try:
                        info["powers"][f"A{asc}"] = [
                            [getattr(p.power_id, "name", str(p.power_id)), int(p.amount)]
                            for p in enemy.powers.values()
                        ]
                    except Exception:
                        pass
                    key = f"A{asc}"
                    lo, hi = info["hp"].get(key, (10**9, 0))
                    info["hp"][key] = (min(lo, enemy.current_hp), max(hi, enemy.current_hp))
                    ai = world.enemy_ais[enemy.combat_id]
                    if asc == 0:
                        info["initial"][ai._current_state_id] += 1
                        for sid, st in ai.states.items():
                            info["states"].setdefault(sid, state_spec(st))
                    else:
                        info["initial8"][ai._current_state_id] += 1
                        for sid, st in ai.states.items():
                            info["states8"].setdefault(sid, state_spec(st))
            if rosters:
                key = f"{setup_name}@A{asc}"
                encounters[key] = {
                    "act": act_name,
                    "asc": asc,
                    "samples": args.seeds,
                    "rosters": [[list(r), c] for r, c in rosters.most_common()],
                }

    # Record move effects once per move (asc-specific).
    for mid, info in monsters.items():
        for sid, st in info["states"].items():
            if st.get("kind") != "move":
                continue
            info["moves"].setdefault(sid + "@A0", None)
        info["variants"] = sorted(info["variants"])

    # discover a (setup, slot) that spawns each monster, per ascension
    spawn_site = {}
    for setup_name, (act_name, mod, setup) in sorted(setups.items()):
        for asc in (0, 8):
            for seed in range(3):
                try:
                    world = CombatState(80, 80, [], seed, relics=[], potions=[], character_id="Ironclad",
                                        ascension_level=asc)
                    setup(world, Rng(seed))
                    world.start_combat()
                except Exception as exc:
                    if setup_name.endswith("shrinker_beetle_weak") and seed == 0:
                        print("setup failed", setup_name, repr(exc))
                    continue
                for slot, enemy in enumerate(world.enemies):
                    spawn_site.setdefault((enemy.monster_id, asc), (setup, seed, slot))

    for mid, info in monsters.items():
        for sid, st in list(info["states"].items()):
            if st.get("kind") != "move":
                continue
            for asc in (0, 8):
                site = spawn_site.get((mid, asc))
                if site is None:
                    continue
                setup, seed, slot = site
                info["moves"][f"{sid}@A{asc}"] = record_move(asc, setup, seed, slot, sid)

    # Summoned monsters never appear in a roster: build them from their creators.
    missing = set()
    for info in monsters.values():
        for ops in info["moves"].values():
            for op in ops or []:
                if op[0] == "summon":
                    missing.add(op[1])
    missing -= set(monsters)
    missing |= {"WRIGGLER", "GUARDBOT", "ZAPBOT", "ROYAL_GUARD",
                "MYSTERIOUS_KNIGHT", "DOORMAKER"}

    from sts2_env.monsters import act1 as m_act1, act1_weak, act2 as m_act2, act3 as m_act3, act4 as m_act4
    creature_mods = [m_act1, act1_weak, m_act2, m_act3, m_act4]
    creators = {}
    for mod in creature_mods:
        for name in dir(mod):
            if not name.startswith("create_"):
                continue
            fn = getattr(mod, name)
            if callable(fn):
                creators[name] = fn

    def first_creator(mid):
        target = mid.lower()
        if "create_" + target in creators:
            return creators["create_" + target]
        for name, fn in creators.items():
            if target in name:
                return fn
        return None

    for mid in sorted(missing):
        creator = first_creator(mid)
        if creator is None:
            print("no creator for summoned", mid)
            continue
        info = {"id": mid, "hp": {}, "states": {}, "states8": {},
                "initial": Counter(), "initial8": Counter(),
                "moves": {}, "variants": set(), "powers": {}}
        real_mid = mid
        for asc in (0, 8):
            for seed in range(4):
                enemy = ai = world = None
                for kwargs in ({"ascension_level": asc}, {"slot": 0, "ascension_level": asc},
                               {"slot": 0}, {}):
                    try:
                        enemy, ai = creator(Rng(seed), **kwargs)
                        break
                    except TypeError:
                        continue
                    except Exception:
                        enemy = ai = None
                        break
                if enemy is None:
                    continue
                try:
                    world = CombatState(80, 80, [], seed, relics=[], potions=[],
                                        character_id="Ironclad", ascension_level=asc)
                    world.add_enemy(enemy, ai)
                    world.start_combat()
                except Exception:
                    continue
                real_mid = enemy.monster_id
                key = f"A{asc}"
                lo, hi = info["hp"].get(key, (10**9, 0))
                info["hp"][key] = (min(lo, enemy.current_hp), max(hi, enemy.current_hp))
                info["powers"][key] = [
                    [getattr(p.power_id, "name", str(p.power_id)), int(p.amount)]
                    for p in enemy.powers.values()
                ]
                if asc == 0:
                    info["initial"][ai._current_state_id] += 1
                    for sid, st in ai.states.items():
                        info["states"].setdefault(sid, state_spec(st))
                else:
                    info["initial8"][ai._current_state_id] += 1
                    for sid, st in ai.states.items():
                        info["states8"].setdefault(sid, state_spec(st))
        def make_setup(_c=creator, _a=0):
            def setup(w, r):
                for kwargs in ({"ascension_level": _a}, {"slot": 0, "ascension_level": _a},
                               {"slot": 0}, {}):
                    try:
                        w.add_enemy(*_c(Rng(0), **kwargs))
                        return
                    except TypeError:
                        continue
            return setup

        for sid, st in info["states"].items():
            if st.get("kind") != "move":
                continue
            for asc in (0, 8):
                info["moves"][f"{sid}@A{asc}"] = record_move(asc, make_setup(creator, asc), 0, 0, sid)
        monsters[real_mid] = info
        if real_mid != mid:
            monsters.pop(mid, None)

    out = {
        "monsters": {},
        "encounters": encounters,
    }
    for mid, info in monsters.items():
        variants = hp_variants.get(mid, [])
        hp_values = {v[1] for v in variants}
        if len(hp_values) == 1:
            lo0, hi0, lo8, hi8 = hp_values.pop()
            info["hp"] = {"A0": (lo0, hi0), "A8": (lo8, hi8)}
            hp_source = "static"
        else:
            hp_source = "sampled" if variants else "sampled_only"
            if variants:
                print(f"HP variants disagree for {mid}: {variants[:3]}")
        out["monsters"][mid] = {
            "hp": {k: list(v) for k, v in info["hp"].items()},
            "hp_source": hp_source,
            "states": info["states"],
            "states8": info["states8"],
            "initial": info["initial"].most_common(),
            "initial8": info["initial8"].most_common(),
            "moves": info["moves"],
            "powers": info.get("powers", {}),
        }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print(f"wrote {args.out}: {len(out['monsters'])} monsters, {len(encounters)} encounter entries")


if __name__ == "__main__":
    main()
