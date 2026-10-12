"""G2 fixed-roster boundary: public ordered slots, no summons or revival.

Native action target indices refer to the original enemy list, including dead
slots. Two Nibbits have different public starting phases (front Slice/back Hiss).
Only complete enemy rounds are stored; terminal partial rounds are not sampled.
"""
from dataclasses import dataclass

from .content import EXPANDED_PROFILES, intent_after, moves, expected_strength, mawler_move, validate_mawler_history
from sts2_env.core.enums import PowerId
from sts2_env.core.rng import Rng

MAX_ROSTER = 2
INTENTS = ("ATTACK", "DEBUFF_STRONG", "BUFF", "SLEEP", "MULTI_ATTACK", "ATTACK_BUFF", "DEBUFF", "ATTACK_DEFEND")
POWERS = (PowerId.VULNERABLE, PowerId.STRENGTH, PowerId.SLOW, PowerId.TERRITORIAL, PowerId.ARTIFACT)


@dataclass(frozen=True)
class EnemyState:
    slot: int
    monster_id: str
    initial_hp: int
    hp: int
    max_hp: int
    block: int
    vulnerable: int
    strength: int
    slow: int
    territorial: int
    artifact: int
    intent: tuple
    moves: tuple


def roster_identity(names):
    if not (len(names) == 1 and names[0] in EXPANDED_PROFILES or names == ("NIBBIT", "NIBBIT")):
        raise ValueError("Unsupported fixed roster; summons/revival/other formations require a new contract")


def validate_health(roster):
    if not isinstance(roster, (tuple, list)) or not 1 <= len(roster) <= MAX_ROSTER:
        raise ValueError("Explicit fixed enemy roster required")
    roster_identity(tuple(e.get("monster_id") for e in roster))
    for slot, e in enumerate(roster):
        if set(e) != {"slot", "monster_id", "initial_hp", "final_hp", "max_hp"}:
            raise ValueError("Invalid enemy health metadata")
        lo, hi = EXPANDED_PROFILES[e["monster_id"]]["hp"]
        if (any(type(e[k]) is not int for k in ("slot", "initial_hp", "final_hp", "max_hp"))
                or e["slot"] != slot or not lo <= e["max_hp"] <= hi
                or not 0 < e["initial_hp"] <= e["max_hp"] or not 0 <= e["final_hp"] <= e["max_hp"]):
            raise ValueError("Invalid fixed-roster HP")
    return tuple(sum(e[k] for e in roster) for k in ("initial_hp", "final_hp", "max_hp"))


def capture_health(world, initial):
    if len(world.enemies) != len(initial):
        raise ValueError("Enemy roster changed")
    rows = []
    for slot, (enemy, (name, hp, maximum)) in enumerate(zip(world.enemies, initial)):
        if enemy.monster_id != name or enemy.max_hp != maximum or (enemy.escaped and enemy.current_hp > 0):
            raise ValueError("Enemy identity/max HP/escape changed")
        rows.append(dict(slot=slot, monster_id=name, initial_hp=hp,
                         final_hp=max(0, enemy.current_hp), max_hp=maximum))
    validate_health(rows)
    return tuple(rows)


def health_rows(enemies):
    return tuple(dict(slot=e.slot, monster_id=e.monster_id, initial_hp=e.initial_hp,
                      final_hp=max(0, e.hp), max_hp=e.max_hp) for e in enemies)


def expected_moves(enemy, count, size):
    if size == 2:
        cycle = ("BUTT_MOVE", "SLICE_MOVE", "HISS_MOVE")
        return tuple(cycle[(i + enemy.slot + 1) % 3] for i in range(count))
    return moves(enemy.monster_id, count)


def public_move(enemy, size):
    return mawler_move(enemy.intent) if enemy.monster_id == "MAWLER" else expected_moves(enemy, len(enemy.moves) + 1, size)[-1]


def after_round(before, ended):
    # If the player dies partway through enemy order there is no next decision.
    # Do not invent actions for enemies that may not have executed.
    return tuple(e.moves + ((public_move(e, len(before.enemies)),) if e.hp > 0 and not ended else ()) for e in before.enemies)


def capture_enemies(world, history, initial_hp):
    roster_identity(tuple(e.monster_id for e in world.enemies))
    if type(initial_hp) is not tuple or len(initial_hp) != len(world.enemies):
        raise ValueError("Initial HP for every fixed slot required")
    histories = history.roster_moves or ((),) * len(world.enemies)
    if len(histories) != len(world.enemies):
        raise ValueError("Enemy history/roster mismatch")
    result = []
    for slot, (enemy, hp, past) in enumerate(zip(world.enemies, initial_hp, histories)):
        if (enemy.escaped and enemy.current_hp > 0) or any(p not in POWERS for p in enemy.powers):
            raise ValueError("Unsupported enemy escape/power")
        intents = world.enemy_ais[enemy.combat_id].current_move.intents
        compound = enemy.monster_id == "CUBEX_CONSTRUCT" and tuple(i.intent_type.name for i in intents) == ("ATTACK", "BUFF")
        if len(intents) != 1 and not compound:
            raise ValueError("Unsupported multi intent")
        intent = intents[0]
        power = lambda p: enemy.powers[p].amount if p in enemy.powers else 0
        # Nibbit Slice's public 6-damage intent uniquely identifies its +5 block.
        # The native simulator exposes only the attack icon; include the audited
        # compound intent without consulting its private state-machine ID.
        name = "ATTACK_BUFF" if compound else intent.intent_type.name
        if enemy.monster_id == "NIBBIT" and (name, intent.damage, intent.hits) == ("ATTACK", 6, 1):
            name = "ATTACK_DEFEND"
        result.append(EnemyState(slot, enemy.monster_id, hp, enemy.current_hp, enemy.max_hp, enemy.block,
                     *(power(p) for p in POWERS),
                     (name, intent.damage, intent.hits), past))
    return tuple(result)


def validate_enemies(info):
    from .rewards import V4
    if info.reward_version != V4 or type(info.enemies) is not tuple or not info.enemies:
        raise ValueError("G2 requires versioned public roster")
    if info.termination_reason not in (None, "win", "death", "time_limit"):
        raise ValueError("Invalid terminal reason")
    if any(type(e) is not EnemyState for e in info.enemies):
        raise ValueError("Immutable public enemy states required")
    validate_health(health_rows(info.enemies))
    histories = info.history.roster_moves or ((),) * len(info.enemies)
    if tuple(e.moves for e in info.enemies) != histories or info.history.enemy_moves != info.enemies[0].moves:
        raise ValueError("Public enemy histories disagree")
    first = info.enemies[0]
    if (info.monster_id, info.enemy_hp, info.enemy_max_hp, info.enemy_initial_hp, info.enemy_block,
        info.vulnerable, info.enemy_strength, info.enemy_slow, info.enemy_territorial, info.enemy_artifact, info.intent) != (
        first.monster_id, first.hp, first.max_hp, first.initial_hp, first.block, first.vulnerable,
        first.strength, first.slow, first.territorial, first.artifact, first.intent):
        raise ValueError("First-slot projection disagrees with roster")
    for slot, e in enumerate(info.enemies):
        if (e.slot != slot or any(type(n) is not int or n < 0 for n in (e.hp, e.block, e.vulnerable, e.strength, e.slow, e.territorial, e.artifact))
                or type(e.moves) is not tuple or type(e.intent) is not tuple or len(e.intent) != 3
                or e.intent[0] not in INTENTS or any(type(n) is not int or n < 0 for n in e.intent[1:])):
            raise ValueError("Invalid enemy numeric/history/intent fields")
        if (e.slow != int(e.monster_id == "BYGONE_EFFIGY" and e.hp > 0)
                or e.territorial != int(e.monster_id == "BYRDONIS" and e.hp > 0)
                or e.artifact not in (0, 1) or e.artifact and e.monster_id != "CUBEX_CONSTRUCT"):
            raise ValueError("Unsupported enemy power state")
        if e.monster_id == "MAWLER":
            validate_mawler_history(e.moves, mawler_move(e.intent) if info.termination_reason is None else None)
        elif e.moves != expected_moves(e, len(e.moves), len(info.enemies)):
            raise ValueError("Enemy cycle differs from public slot history")
        if info.termination_reason is None and e.hp > 0:
            offset = slot + 1 if len(info.enemies) == 2 else 0
            expected = e.intent if e.monster_id == "MAWLER" else intent_after(e.monster_id, len(e.moves) + offset)
            if e.monster_id == "NIBBIT" and expected == ("ATTACK", 6, 1):
                expected = ("ATTACK_DEFEND", 6, 1)
            if (len(e.moves) != info.turn - 1 or e.intent != expected
                    or e.strength != expected_strength(e.monster_id, e.moves)):
                raise ValueError("Live enemy phase/strength mismatch")
        if len(e.moves) > info.turn or len(e.moves) > info.history.decisions:
            raise ValueError("Enemy history exceeds elapsed decisions")
        if e.hp == 0 and any((e.vulnerable, e.strength, e.slow, e.territorial, e.artifact)):
            raise ValueError("Dead enemy retains unsupported powers")
    alive = any(e.hp > 0 for e in info.enemies)
    if info.termination_reason == "win" and (alive or info.player_hp <= 0):
        raise ValueError("Win requires whole-roster defeat")
    if info.termination_reason == "death" and info.player_hp > 0:
        raise ValueError("Death requires player defeat")
    if info.termination_reason in (None, "time_limit") and (not alive or info.player_hp <= 0):
        raise ValueError("Missing true terminal outcome")
    if info.termination_reason is None:
        if info.history.decisions >= info.limits.max_decisions or info.turn > info.limits.max_turns:
            raise ValueError("Missing timeout")
        expected_shrink = -1 if first.monster_id == "SHRINKER_BEETLE" and info.turn > 1 else 0
        if info.shrink != expected_shrink:
            raise ValueError("Invalid Shrink lifecycle")
    target = info.history.pending_target
    if info.choice and info.pending_card.token.removesuffix("+") == "HEADBUTT":
        if type(target) is not int or not 0 <= target < len(info.enemies):
            raise ValueError("Headbutt continuation lost its public target")
    elif target is not None:
        raise ValueError("Unexpected pending target")


def check_transition(before, world, slots):
    if tuple(world.enemies) != slots:
        raise ValueError("Fixed roster was added, removed, reordered or replaced")
    for old, enemy in zip(before.enemies, world.enemies):
        if (enemy.monster_id, enemy.max_hp) != (old.monster_id, old.max_hp):
            raise ValueError("Fixed-roster identity or maximum HP changed")
        if old.hp == 0 and enemy.current_hp > 0:
            raise ValueError("Revival is outside the fixed-roster contract")


def create_enemies(world, info):
    from sts2_env.monsters.act1_weak import create_shrinker_beetle, create_fuzzy_wurm_crawler, create_nibbit
    from sts2_env.monsters.act1 import create_bygone_effigy, create_byrdonis, create_cubex_construct, create_mawler
    factories = dict(SHRINKER_BEETLE=create_shrinker_beetle, FUZZY_WURM_CRAWLER=create_fuzzy_wurm_crawler,
                     NIBBIT=create_nibbit, BYGONE_EFFIGY=create_bygone_effigy, BYRDONIS=create_byrdonis,
                     CUBEX_CONSTRUCT=create_cubex_construct, MAWLER=create_mawler)
    for e in info.enemies:
        kwargs = dict(is_alone=False, is_front=e.slot == 0) if len(info.enemies) == 2 else {}
        enemy, ai = factories[e.monster_id](Rng(0), **kwargs)
        world.add_enemy(enemy, ai)


def restore_enemies(world, info, rng):
    for enemy, e in zip(world.enemies, info.enemies):
        ai = world.enemy_ais[enemy.combat_id]
        enemy.current_hp, enemy.max_hp, enemy.block = e.hp, e.max_hp, e.block
        enemy.powers.clear()
        enemy._death_processed = e.hp == 0
        enemy.escaped = e.hp == 0  # Native death removes the creature logically, not its list slot.
        if e.monster_id == "MAWLER":
            ai.state_log = list(e.moves)
            ai._current_state_id = mawler_move(e.intent)
            ai._performed_first_move = bool(e.moves)
        else:
            for _ in e.moves:
                ai.on_move_performed()
                ai.roll_move(rng)
        for p, amount in zip(POWERS, (e.vulnerable, e.strength, e.slow, e.territorial, e.artifact)):
            if amount:
                world.apply_power_to(enemy, p, amount, applier=world.player if p == PowerId.VULNERABLE else enemy)
        if e.slow:
            enemy.powers[PowerId.SLOW]._slow_amount = len(info.history.played_this_turn) - int(info.choice is not None)


def enemy_features():
    fields = ("present", "alive", "hp/160", "initial_hp/160", "max_hp/160", "block/100",
              "vulnerable/10", "strength/100", "slow", "territorial", "artifact", "completed_moves/100",
              "intent.damage/20", "intent.hits/5")
    fields += tuple("monster." + name for name in EXPANDED_PROFILES)
    fields += tuple("intent." + name for name in INTENTS)
    return tuple(f"enemy_slot{slot}.{field}" for slot in range(MAX_ROSTER) for field in fields) + ("pending.target0", "pending.target1")


def encode_enemies(info):
    result = []
    for e in info.enemies:
        result += [1, e.hp > 0, e.hp/160, e.initial_hp/160, e.max_hp/160, e.block/100,
                   e.vulnerable/10, e.strength/100, e.slow, e.territorial, e.artifact, len(e.moves)/100,
                   e.intent[1]/20, e.intent[2]/5]
        result += [e.monster_id == name for name in EXPANDED_PROFILES]
        result += [e.intent[0] == name for name in INTENTS]
    result += [0] * ((MAX_ROSTER-len(info.enemies)) * (14 + len(EXPANDED_PROFILES) + len(INTENTS)))
    result += [info.history.pending_target == slot for slot in range(MAX_ROSTER)]
    return result
