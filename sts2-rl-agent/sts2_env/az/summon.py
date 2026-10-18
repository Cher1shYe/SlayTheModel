"""G2.2b public contract for the audited Fogmog / EyeWithTeeth summon encounter.

Only three kinds of fact may enter an AI history or an observation:

* the *current public intent* (the icon and damage the player is shown),
* *visible powers* (including the Minion/Illusion flags that make the Eye a
  secondary enemy), and
* *observed past events* (performed moves replayed from the public intent the
  player already saw, plus generated cards that appeared in public piles).

Never read: ``MonsterAI._current_state_id``, ``MonsterAI.state_log``,
``_performed_first_move``, future RNG draws, hidden pile order, or a private
power attribute beyond the public ``is_reviving`` knockout flag.  Fogmog's
``SWIPE_MOVE`` and ``SWIPE_RANDOM_MOVE`` are publicly identical (``ATTACK`` 8 +
``BUFF``); the applicable state is derived from the already observed history and
the audited state machine, never from the private branch id or a future roll.

Lifecycle: stable append-only slots.  Fogmog is the only primary; the summoned
EyeWithTeeth is a secondary minion that is knocked down (never removed) and
revives in its own slot, so native target indices never shift or get reused.
``primary`` is exactly the native rule (no power with
``owner_is_secondary_enemy``), i.e. a function of visible powers only.
"""
from dataclasses import dataclass

from .card_generation import CardGeneration, DISTRACT_DAZED_COUNT
from .content import (
    SUMMON_CONTENT,
    SUMMON_PROFILES,
    expected_strength,
    intent_after,
    mawler_move,
    moves as cycle_moves,
    validate_mawler_history,
)
from .enemy_lifecycle import EnemyLedger, EnemyLife
from .rewards import V5
from sts2_env.core.enums import PowerId

SUMMON_INFORMATION = "summon-information-v1"
SUMMON_ACTION_VERSION = "combat-summon1024-v4"
SUMMON_ACTION_SIZE = 1024
# <=20 initial cards + <=400 one-copy Anger + 3 Dazed per performed Eye turn at
# the existing 400-decision/100-turn limits.  The old 420 ceiling cannot hold it.
SUMMON_CARD_CAPACITY = 720
MAX_SLOTS = 2  # Fogmog plus at most one summoned Eye occupy the native slots

FOGMOG = "FOGMOG"
EYE = "EYE_WITH_TEETH"
EYE_HP = 6
# IllusionPower.after_death installs these; the follow-up is derived from the
# public log, never from the private AI object.
EYE_DISTRACT_MOVE = "DISTRACT_MOVE"
EYE_REVIVE_MOVE = "REVIVE_MOVE"
EYE_MOVES = (EYE_DISTRACT_MOVE, EYE_REVIVE_MOVE)
# Fogmog's ILLUSION_MOVE is its initial state and its first performed move, so
# the summoned slot exists from player turn 2 on and acts from enemy round 2.
EYE_SPAWN_ROUND = 1

from sts2_env.monsters.act1 import (  # noqa: E402  (native constants: one source of truth)
    FOGMOG_BASE_HEADBUTT_DAMAGE,
    FOGMOG_BASE_SWIPE_DAMAGE,
    FOGMOG_HEADBUTT_MOVE,
    FOGMOG_ILLUSION_MOVE,
    FOGMOG_SWIPE_MOVE,
    FOGMOG_SWIPE_RANDOM_MOVE,
    create_eye_with_teeth,
    create_fogmog,
)

FOGMOG_MOVES = (FOGMOG_ILLUSION_MOVE, FOGMOG_SWIPE_MOVE, FOGMOG_SWIPE_RANDOM_MOVE, FOGMOG_HEADBUTT_MOVE)
FOGMOG_SWIPE_MOVES = (FOGMOG_SWIPE_MOVE, FOGMOG_SWIPE_RANDOM_MOVE)
# Public intent shown for each audited move (ascension 0, the only admitted one).
FOGMOG_INTENTS = {
    FOGMOG_ILLUSION_MOVE: ("SUMMON", 0, 1),
    FOGMOG_SWIPE_MOVE: ("ATTACK_BUFF", FOGMOG_BASE_SWIPE_DAMAGE, 1),
    FOGMOG_SWIPE_RANDOM_MOVE: ("ATTACK_BUFF", FOGMOG_BASE_SWIPE_DAMAGE, 1),
    FOGMOG_HEADBUTT_MOVE: ("ATTACK", FOGMOG_BASE_HEADBUTT_DAMAGE, 1),
}
EYE_INTENTS = {EYE_DISTRACT_MOVE: ("STATUS_CARD", 0, 1), EYE_REVIVE_MOVE: ("HEAL", 0, 1)}

DAZED = "DAZED"
DAZED_SOURCE = "EYE_WITH_TEETH.DISTRACT_MOVE"
DAZED_MECHANISM = "distract-dazed-v1"

SUMMON_POWERS = (PowerId.VULNERABLE, PowerId.STRENGTH, PowerId.SLOW, PowerId.TERRITORIAL,
                 PowerId.ARTIFACT, PowerId.ILLUSION, PowerId.MINION)
INTENTS = ("ATTACK", "ATTACK_BUFF", "BUFF", "DEBUFF", "DEBUFF_STRONG", "SLEEP", "MULTI_ATTACK",
           "ATTACK_DEFEND", "SUMMON", "STATUS_CARD", "HEAL")
# Admitted secondary summons.  The Eye is never an encounter of its own, so it
# stays out of SUMMON_PROFILES, which defines the nine sampled encounters.
SUMMON_MINIONS = {EYE: dict(hp=(EYE_HP, EYE_HP))}
MONSTER_IDS = (*(name for name, profile in SUMMON_PROFILES.items() if "members" not in profile), *SUMMON_MINIONS)
FOGMOG_ENCOUNTER = SUMMON_PROFILES[FOGMOG]["encounter"]


@dataclass(frozen=True)
class SlotState:
    """One stable native roster slot; append-only, never compacted or reused."""
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
    illusion: int
    minion: int
    primary: bool
    spawned: bool
    reviving: bool
    intent: tuple
    moves: tuple


def fogmog_candidates(previous):
    """Public next-move candidates given the last performed public move."""
    if previous is None:
        return (FOGMOG_ILLUSION_MOVE,)
    if previous in (FOGMOG_ILLUSION_MOVE, FOGMOG_HEADBUTT_MOVE):
        return (FOGMOG_SWIPE_MOVE,)
    if previous == FOGMOG_SWIPE_MOVE:
        # The BRANCH state becomes public only through the intent it produces.
        return (FOGMOG_SWIPE_RANDOM_MOVE, FOGMOG_HEADBUTT_MOVE)
    if previous == FOGMOG_SWIPE_RANDOM_MOVE:
        return (FOGMOG_HEADBUTT_MOVE,)
    raise ValueError("Unknown public Fogmog move")


def fogmog_move(previous, intent):
    """Identify the current/performed move from the public intent alone."""
    matches = [m for m in fogmog_candidates(previous) if FOGMOG_INTENTS[m] == intent]
    if len(matches) != 1:
        raise ValueError("Fogmog public intent does not identify exactly one audited move")
    return matches[0]


def fogmog_history(history):
    previous = None
    for move in history:
        if move not in fogmog_candidates(previous):
            raise ValueError("Public Fogmog history contradicts the audited state machine")
        previous = move
    return fogmog_candidates(previous)


def fogmog_strength(history):
    # Every swipe deals its damage and then gains one Strength; headbutt and the
    # summon move never do.
    return sum(move in FOGMOG_SWIPE_MOVES for move in history)


def eye_next_move(history, reviving=False):
    """Eye resumes its public DISTRACT intent after each knockout/revival.

    Native StateLog includes the selected move, unlike Python's performed log.
    A new knockout always interrupts DISTRACT, never the last performed REVIVE.
    """
    if any(move not in EYE_MOVES for move in history):
        raise ValueError("Unknown public Eye move")
    return EYE_REVIVE_MOVE if reviving else EYE_DISTRACT_MOVE


def eye_intent(history, reviving):
    return EYE_INTENTS[eye_next_move(history, reviving)]


def eye_distract_count(slots):
    return sum(move == EYE_DISTRACT_MOVE for e in slots for move in e.moves)


def roster_identity(names):
    if len(names) == 1 and names[0] in SUMMON_PROFILES and "members" not in SUMMON_PROFILES[names[0]]:
        return
    if names == ("NIBBIT", "NIBBIT") or names == (FOGMOG, EYE):
        return
    raise ValueError("Unsupported summon roster; only the audited Fogmog illusion may add a slot")


def primary_names(names):
    if names == (FOGMOG, EYE):
        return (FOGMOG,)
    if names == ("NIBBIT", "NIBBIT"):
        return names
    return names


def hp_range(monster_id):
    if monster_id in SUMMON_PROFILES:
        return SUMMON_PROFILES[monster_id]["hp"]
    if monster_id in SUMMON_MINIONS:
        return SUMMON_MINIONS[monster_id]["hp"]
    raise ValueError("Unsupported summoned monster")


def public_intent(enemy, intents):
    """Project the visible intent; never read the private state id."""
    names = tuple(i.intent_type.name for i in intents)
    if len(intents) == 1:
        intent = intents[0]
        name, damage, hits = intent.intent_type.name, intent.damage, intent.hits
    elif enemy.monster_id in (FOGMOG, "CUBEX_CONSTRUCT") and names == ("ATTACK", "BUFF"):
        # Fogmog's swipe and Cubex's repeater show a compound attack+buff icon.
        intent = intents[0]
        name, damage, hits = "ATTACK_BUFF", intent.damage, intent.hits
    else:
        raise ValueError("Unsupported multi intent")
    # Nibbit Slice's public 6-damage intent uniquely identifies its +5 block.
    if enemy.monster_id == "NIBBIT" and (name, damage, hits) == ("ATTACK", 6, 1):
        name = "ATTACK_DEFEND"
    return (name, damage, hits)


def public_move(e, size):
    """The move this slot performs or will perform, from public state only."""
    if e.monster_id == FOGMOG:
        return fogmog_move(e.moves[-1] if e.moves else None, e.intent)
    if e.monster_id == EYE:
        return eye_next_move(e.moves, e.reviving)
    from .multi import public_move as multi_public_move
    return multi_public_move(e, size)


def acts_this_round(e):
    """A slot acts in the enemy round unless it is permanently gone."""
    return e.hp > 0 or e.reviving


def padded_histories(history, count):
    """Per-slot public move history; a slot that never acted has none yet."""
    moves = history.roster_moves
    if type(moves) is not tuple or len(moves) > count:
        raise ValueError("Public roster history exceeds the observed roster")
    return moves + ((),) * (count - len(moves))


def expected_move_count(info, e):
    """Performed moves expected at this decision for one slot."""
    start = EYE_SPAWN_ROUND if e.spawned else 0
    return info.turn - 1 - start


def after_round(before, ended):
    """Append exactly the moves the enemy round actually performed.

A terminal partial round records nothing: enemies that never reached their turn
must not be credited with an unperformed action.
"""
    if not before.enemies:
        return ()
    return tuple(e.moves + ((public_move(e, len(before.enemies)),) if acts_this_round(e) and not ended else ())
                 for e in before.enemies)


def generation_after(before, ended, decision):
    """Exactly three Dazed per actually performed Eye DISTRACT_MOVE."""
    if ended:
        return ()
    events = []
    for e in before.enemies:
        if e.monster_id == EYE and e.hp > 0 and public_move(e, len(before.enemies)) == EYE_DISTRACT_MOVE:
            events.append(CardGeneration(decision, DAZED_SOURCE, DAZED, "discard", DAZED_MECHANISM,
                                         DISTRACT_DAZED_COUNT))
    return tuple(events)


def roster_rows(slots):
    return tuple(dict(slot=e.slot, monster_id=e.monster_id, initial_hp=e.initial_hp,
                      final_hp=e.hp, max_hp=e.max_hp) for e in slots)


def validate_health(slots):
    rows = roster_rows(slots)
    roster_identity(tuple(e["monster_id"] for e in rows))
    primaries = primary_names(tuple(e["monster_id"] for e in rows))
    for slot, e in enumerate(rows):
        lo, hi = hp_range(e["monster_id"])
        if (any(type(e[k]) is not int for k in ("slot", "initial_hp", "final_hp", "max_hp"))
                or e["slot"] != slot or not lo <= e["max_hp"] <= hi
                or not 0 < e["initial_hp"] <= e["max_hp"] or not 0 <= e["final_hp"] <= e["max_hp"]):
            raise ValueError("Invalid summon roster HP")
        if slot < len(primaries):
            if e["monster_id"] != primaries[slot]:
                raise ValueError("Primary slot identity differs from the admitted encounter")
        elif e["monster_id"] not in SUMMON_MINIONS:
            raise ValueError("Unsupported summoned minion identity")
    if len(rows) == len(primaries) + len(SUMMON_MINIONS) and tuple(e["monster_id"] for e in rows) != (FOGMOG, EYE):
        raise ValueError("Only the audited Fogmog illusion may add a second slot")
    return rows


def capture_slots(world, history, initial_hp):
    """Project the public roster; a summoned slot is observed, never inferred."""
    if type(initial_hp) is not tuple or not initial_hp:
        raise ValueError("Initial HP for every initial slot required")
    if not len(initial_hp) <= len(world.enemies) <= MAX_SLOTS:
        raise ValueError("Unsupported summon roster size")
    histories = padded_histories(history, len(world.enemies))
    result = []
    for slot, (enemy, past) in enumerate(zip(world.enemies, histories)):
        spawned = slot >= len(initial_hp)
        if enemy.monster_id not in MONSTER_IDS or (enemy.escaped and enemy.current_hp > 0):
            raise ValueError("Unsupported summoned monster/escape")
        if any(p not in SUMMON_POWERS for p in enemy.powers):
            raise ValueError("Unsupported summon power")
        amount = lambda p: enemy.powers[p].amount if p in enemy.powers else 0
        illusion, minion = amount(PowerId.ILLUSION), amount(PowerId.MINION)
        hp = max(0, enemy.current_hp)
        primary = minion == 0
        if spawned and (enemy.max_hp != EYE_HP or illusion != 1 or minion != 1 or primary):
            raise ValueError("Unaudited secondary slot")
        result.append(SlotState(slot, enemy.monster_id, enemy.max_hp if spawned else initial_hp[slot],
                                hp, enemy.max_hp, enemy.block, amount(PowerId.VULNERABLE),
                                amount(PowerId.STRENGTH), amount(PowerId.SLOW), amount(PowerId.TERRITORIAL),
                                amount(PowerId.ARTIFACT), illusion, minion, primary, spawned,
                                hp == 0 and illusion > 0,
                                public_intent(enemy, world.enemy_ais[enemy.combat_id].current_move.intents),
                                past))
    return tuple(result)


def expected_roster_intents(info, e):
    if e.monster_id == FOGMOG:
        return tuple(FOGMOG_INTENTS[m] for m in fogmog_history(e.moves))
    if e.monster_id == EYE:
        return (eye_intent(e.moves, e.reviving),)
    if e.monster_id == "MAWLER":
        validate_mawler_history(e.moves, mawler_move(e.intent))
        return (e.intent,)
    offset = e.slot + 1 if len(info.enemies) == 2 else 0
    expected = intent_after(e.monster_id, len(e.moves) + offset)
    if e.monster_id == "NIBBIT" and expected == ("ATTACK", 6, 1):
        expected = ("ATTACK_DEFEND", 6, 1)
    return (expected,)


def expected_roster_strength(e):
    if e.monster_id == EYE:
        return 0
    if e.monster_id == FOGMOG:
        return fogmog_strength(e.moves)
    return expected_strength(e.monster_id, e.moves)


def validate_slots(info):
    """Full public validation for one summon-content information state."""
    if info.reward_version != V5 or type(info.enemies) is not tuple or not info.enemies:
        raise ValueError("Summon content requires versioned public slots and reward v5")
    if info.termination_reason not in (None, "win", "death", "time_limit"):
        raise ValueError("Invalid terminal reason")
    if any(type(e) is not SlotState for e in info.enemies):
        raise ValueError("Immutable public summon slots required")
    if not 1 <= len(info.enemies) <= MAX_SLOTS:
        raise ValueError("Summon roster exceeds the admitted native slots")
    validate_health(info.enemies)
    names = tuple(e.monster_id for e in info.enemies)
    primaries = primary_names(names)
    histories = padded_histories(info.history, len(info.enemies))
    if tuple(e.moves for e in info.enemies) != histories or info.history.enemy_moves != info.enemies[0].moves:
        raise ValueError("Public enemy histories disagree")
    first = info.enemies[0]
    if (info.monster_id, info.enemy_hp, info.enemy_max_hp, info.enemy_initial_hp, info.enemy_block,
        info.vulnerable, info.enemy_strength, info.enemy_slow, info.enemy_territorial,
        info.enemy_artifact, info.intent) != (
        first.monster_id, first.hp, first.max_hp, first.initial_hp, first.block, first.vulnerable,
        first.strength, first.slow, first.territorial, first.artifact, first.intent):
        raise ValueError("First-slot projection disagrees with the roster")
    for slot, e in enumerate(info.enemies):
        if (e.slot != slot or any(type(n) is not int or n < 0 for n in
                                  (e.hp, e.block, e.vulnerable, e.strength, e.slow, e.territorial,
                                   e.artifact, e.illusion, e.minion))
                or (e.spawned and (slot < len(primaries) or e.initial_hp != EYE_HP))
                or (not e.spawned and slot >= len(primaries))
                or type(e.primary) is not bool or type(e.spawned) is not bool
                or type(e.reviving) is not bool or not 0 <= e.hp <= e.max_hp
                or e.primary != (e.minion == 0) or e.illusion != int(e.monster_id == EYE)
                or e.minion != int(e.monster_id == EYE)
                or e.reviving != (e.hp == 0 and e.illusion > 0)
                or type(e.moves) is not tuple or type(e.intent) is not tuple or len(e.intent) != 3
                or e.intent[0] not in INTENTS or any(type(n) is not int or n < 0 for n in e.intent[1:])):
            raise ValueError("Invalid summon slot fields")
        if e.slow != int(e.monster_id == "BYGONE_EFFIGY" and e.hp > 0):
            raise ValueError("Unsupported Slow state")
        if e.territorial != int(e.monster_id == "BYRDONIS" and e.hp > 0):
            raise ValueError("Unsupported Territorial state")
        if e.artifact not in (0, 1) or (e.artifact and e.monster_id != "CUBEX_CONSTRUCT"):
            raise ValueError("Unsupported Artifact state")
        if e.monster_id == FOGMOG:
            fogmog_history(e.moves)
        elif e.monster_id == EYE:
            eye_next_move(e.moves, e.reviving)
        elif e.monster_id == "MAWLER":
            validate_mawler_history(e.moves, mawler_move(e.intent) if info.termination_reason is None else None)
        elif names == ("NIBBIT", "NIBBIT"):
            from .multi import expected_moves
            if e.moves != expected_moves(e, len(e.moves), 2):
                raise ValueError("Nibbit pair cycle differs from public slot history")
        elif e.moves != cycle_moves(e.monster_id, len(e.moves)):
            raise ValueError("Enemy cycle differs from public slot history")
        if len(e.moves) > info.turn or len(e.moves) > info.history.decisions:
            raise ValueError("Enemy history exceeds elapsed decisions")
        if e.hp == 0 and any((e.vulnerable, e.strength, e.slow, e.territorial, e.artifact)):
            raise ValueError("Knocked-down enemy retains unsupported powers")
        if info.termination_reason is not None:
            continue
        if not acts_this_round(e):
            # A permanently gone slot stopped acting in the round it died, so
            # only the elapsed-decision bound applies to its public history.
            continue
        if len(e.moves) != expected_move_count(info, e):
            raise ValueError("Public move count disagrees with the elapsed enemy rounds")
        if e.reviving:
            if e.monster_id != EYE or e.intent != eye_intent(e.moves, True):
                raise ValueError("Reviving slot intent is not the audited revive move")
        elif e.hp > 0:
            if e.intent not in expected_roster_intents(info, e):
                raise ValueError("Live enemy intent mismatch")
            if e.strength != expected_roster_strength(e):
                raise ValueError("Public strength disagrees with performed moves")
    _validate_dazed(info)
    _validate_terminal(info)
    return info


def _validate_dazed(info):
    events = tuple(e for e in info.history.generated
                   if type(e) is CardGeneration and e.mechanism == DAZED_MECHANISM)
    if len(events) != eye_distract_count(info.enemies):
        raise ValueError("Dazed ledger disagrees with the public Eye move history")
    target = info.history.pending_target
    if info.choice and info.pending_card and info.pending_card.token.removesuffix("+") in ("HEADBUTT","SEEKER_STRIKE"):
        if type(target) is not int or not 0 <= target < len(info.enemies):
            raise ValueError("Headbutt continuation lost its public target")
    elif target is not None:
        raise ValueError("Unexpected pending target")


def _validate_terminal(info):
    alive_primary = any(e.primary and e.hp > 0 for e in info.enemies)
    if info.termination_reason == "win" and (alive_primary or info.player_hp <= 0):
        raise ValueError("Win requires every primary enemy permanently defeated")
    if info.termination_reason == "death" and info.player_hp > 0:
        raise ValueError("Death requires player defeat")
    if info.termination_reason in (None, "time_limit") and (not alive_primary or info.player_hp <= 0):
        raise ValueError("Missing true terminal outcome")
    if info.termination_reason is not None and any(e.reviving and e.primary for e in info.enemies):
        raise ValueError("A reviving primary needs a separate budget contract")
    if info.termination_reason is None:
        if info.history.decisions >= info.limits.max_decisions or info.turn > info.limits.max_turns:
            raise ValueError("Missing timeout")
        expected_shrink = -1 if info.enemies[0].monster_id == "SHRINKER_BEETLE" and info.turn > 1 else 0
        if info.shrink != expected_shrink:
            raise ValueError("Invalid Shrink lifecycle")


def check_transition(before, world, slots):
    """Append-only roster: no reorder, removal, replacement or index reuse."""
    current = tuple(world.enemies)
    if len(current) < len(slots) or len(current) > MAX_SLOTS or current[:len(slots)] != slots:
        raise ValueError("Summon roster was removed, reordered or replaced")
    for old, enemy in zip(before.enemies, world.enemies):
        if (enemy.monster_id, enemy.max_hp) != (old.monster_id, old.max_hp):
            raise ValueError("Summon slot identity or maximum HP changed")
        if old.hp == 0 < enemy.current_hp and (not old.spawned or old.monster_id != EYE):
            raise ValueError("Revival is outside the audited illusion contract")
    for slot, enemy in enumerate(current[len(before.enemies):], start=len(before.enemies)):
        if (slot, enemy.monster_id) != (1, EYE) or len(before.enemies) != 1:
            raise ValueError("Only the audited Fogmog illusion may add a slot")
    return True


def ledger_from_slots(slots):
    entries = []
    for e in slots:
        phase = "removed" if getattr(e, "escaped", False) else ("alive" if e.hp > 0 else ("reviving" if e.reviving and (getattr(e, "_amount", lambda _: 0)("REATTACH") == 0 or any(s.hp > 0 for s in slots)) else "defeated"))
        entries.append(EnemyLife(e.slot, e.monster_id, e.primary, e.initial_hp, e.max_hp, 0 if phase == "removed" else e.hp, phase, e.spawned))
    from .roster import EnemySlot
    from .enemy_lifecycle import ALL_CONTRACT_VERSION, CONTRACT_VERSION
    version = ALL_CONTRACT_VERSION if all(type(e) is EnemySlot for e in slots) else CONTRACT_VERSION
    ledger = EnemyLedger(tuple(entries), version)
    ledger.validate()
    return ledger


def capture_ledger(world, initial_hp):
    """Public lifecycle ledger straight from the finished world."""
    entries = []
    for slot, enemy in enumerate(world.enemies):
        amount = lambda p: enemy.powers[p].amount if p in enemy.powers else 0
        spawned = slot >= len(initial_hp)
        illusion, minion = amount(PowerId.ILLUSION), amount(PowerId.MINION)
        hp = max(0, enemy.current_hp)
        phase = "alive" if hp > 0 else ("reviving" if illusion > 0 else "defeated")
        entries.append(EnemyLife(slot, enemy.monster_id, minion == 0,
                                 enemy.max_hp if spawned else initial_hp[slot],
                                 enemy.max_hp, hp, phase, spawned))
    ledger = EnemyLedger(tuple(entries))
    ledger.validate()
    return ledger


def primary_summary(ledger):
    primary = tuple(e for e in ledger.entries if e.primary and not e.spawned)
    return (sum(e.initial_hp for e in primary), sum(e.hp for e in primary), sum(e.max_hp for e in primary))


def ledger_rows(ledger):
    from .enemy_lifecycle import ALL_CONTRACT_VERSION
    rows = ledger.to_dict()["entries"]
    if ledger.version == ALL_CONTRACT_VERSION:
        rows = [dict(row, lifecycle_version=ledger.version) for row in rows]
    return tuple(rows)


def ledger_from_rows(rows):
    if type(rows) not in (tuple, list) or not rows or any(type(row) is not dict for row in rows):
        raise ValueError("Immutable public lifecycle ledger required")
    try:
        from .enemy_lifecycle import CONTRACT_VERSION, ALL_CONTRACT_VERSION
        versions = {row.get("lifecycle_version", CONTRACT_VERSION) for row in rows}
        if len(versions) != 1:
            raise ValueError("Mixed lifecycle versions")
        version = versions.pop()
        ledger = EnemyLedger(tuple(EnemyLife(**{k: v for k, v in row.items() if k != "lifecycle_version"}) for row in rows), version)
        ledger.validate()
    except (TypeError, AttributeError) as exc:
        raise ValueError("Invalid lifecycle ledger record") from exc
    return ledger


def encounter_roster(encounter_id):
    for name, profile in SUMMON_PROFILES.items():
        if profile["encounter"] == encounter_id:
            return tuple(profile.get("members", (name,))), ((EYE,) if name == FOGMOG else ())
    raise ValueError("Unsupported summon encounter identity")


def validate_ledger_rows(rows, content_version, encounter_id):
    """Validate an admitted ledger against encounter identities and lifecycles."""
    if content_version != SUMMON_CONTENT:
        raise ValueError("Summon ledger requires the summon content")
    ledger = ledger_from_rows(rows)
    members, minions = encounter_roster(encounter_id)
    primary = tuple(e for e in ledger.entries if e.primary)
    secondary = tuple(e for e in ledger.entries if not e.primary)
    if tuple(e.monster_id for e in primary) != members or len(primary) != len(members):
        raise ValueError("Ledger primaries differ from the admitted encounter")
    if any(e.spawned or e.phase not in ("alive", "defeated") for e in primary):
        raise ValueError("Primary ledger entries cannot be summons or removals")
    if len(secondary) > len(minions) or any(e.monster_id not in minions for e in secondary):
        raise ValueError("Ledger carries an unadmitted summoned minion")
    if any(e.initial_hp != EYE_HP or e.max_hp != EYE_HP or e.hp > EYE_HP or not e.spawned
           or e.phase not in ("alive", "reviving") for e in secondary):
        raise ValueError("Summoned minion lifecycle is not the audited illusion")
    for entry in ledger.entries:
        lo, hi = hp_range(entry.monster_id)
        if not lo <= entry.max_hp <= hi:
            raise ValueError("Ledger HP range differs from the admitted encounter")
    return ledger


def create_enemies(world, info, rng):
    """Rebuild exactly the observed roster in a particle (no future summon yet)."""
    from sts2_env.monsters.act1 import create_bygone_effigy, create_byrdonis, create_cubex_construct, create_mawler
    from sts2_env.monsters.act1_weak import create_fuzzy_wurm_crawler, create_nibbit, create_shrinker_beetle
    factories = {"SHRINKER_BEETLE": create_shrinker_beetle, "FUZZY_WURM_CRAWLER": create_fuzzy_wurm_crawler,
                 "NIBBIT": create_nibbit, "BYGONE_EFFIGY": create_bygone_effigy, "BYRDONIS": create_byrdonis,
                 "CUBEX_CONSTRUCT": create_cubex_construct, "MAWLER": create_mawler,
                 FOGMOG: create_fogmog, EYE: create_eye_with_teeth}
    for e in info.enemies:
        # The illusion closure must alias the particle stream; Fogmog and the Eye
        # are therefore built on it.  The eight fixed encounters keep the
        # historical factory-only construction, whose audited cycles draw nothing.
        kwargs = (dict(is_alone=False, is_front=e.slot == 0)
                  if e.monster_id == "NIBBIT" and len(info.enemies) == 2 else {})
        if e.monster_id in (FOGMOG, EYE):
            enemy, ai = factories[e.monster_id](rng, **kwargs)
        else:
            from sts2_env.core.rng import Rng
            enemy, ai = factories[e.monster_id](Rng(0), **kwargs)
        world.add_enemy(enemy, ai)
    return world


def restore_enemies(world, info, rng):
    """Restore every slot from public state; a reviving Eye keeps its own slot."""
    from .multi import POWERS as MULTI_POWERS
    from .multi import restore_enemies as multi_restore
    if not any(e.monster_id in (FOGMOG, EYE) for e in info.enemies):
        return multi_restore(world, info, rng)
    for enemy, e in zip(world.enemies, info.enemies):
        ai = world.enemy_ais[enemy.combat_id]
        enemy.current_hp, enemy.max_hp, enemy.block = e.hp, e.max_hp, e.block
        enemy.powers.clear()
        enemy._death_processed = e.hp == 0
        # IllusionPower prevents removal, so a knocked-down Eye stays in the
        # roster, is simply not hittable, and revives in place later.
        enemy.escaped = e.hp == 0 and not e.reviving
        if e.monster_id == FOGMOG:
            ai.state_log = list(e.moves)
            ai._current_state_id = fogmog_move(e.moves[-1] if e.moves else None, e.intent)
            ai._performed_first_move = bool(e.moves)
        elif e.monster_id == EYE:
            _restore_eye(ai, enemy, e)
        elif e.monster_id == "MAWLER":
            ai.state_log = list(e.moves)
            ai._current_state_id = mawler_move(e.intent)
            ai._performed_first_move = bool(e.moves)
        else:
            for _ in e.moves:
                ai.on_move_performed()
                ai.roll_move(rng)
        for p, amount in zip(MULTI_POWERS, (e.vulnerable, e.strength, e.slow, e.territorial, e.artifact)):
            if amount:
                world.apply_power_to(enemy, p, amount, applier=world.player if p == PowerId.VULNERABLE else enemy)
        if e.illusion:
            world.apply_power_to(enemy, PowerId.ILLUSION, e.illusion, applier=enemy)
        if e.minion and not enemy.has_power(PowerId.MINION):
            world.apply_power_to(enemy, PowerId.MINION, e.minion, applier=enemy)
        if e.illusion and PowerId.ILLUSION in enemy.powers:
            # Applied last: the native hittability hook must see the knockout.
            enemy.powers[PowerId.ILLUSION].is_reviving = e.reviving
        if e.slow:
            enemy.powers[PowerId.SLOW]._slow_amount = len(info.history.played_this_turn) - int(info.choice is not None)
    return world


def _restore_eye(ai, enemy, e):
    """Rebuild the public Eye machine, including the audited revive follow-up."""
    from sts2_env.core.enums import IntentType
    from sts2_env.monsters.intents import Intent
    from sts2_env.monsters.state_machine import MoveState
    ai.state_log = list(e.moves)
    ai._performed_first_move = bool(e.moves)
    current = eye_next_move(e.moves, e.reviving)

    def _revive_move(_combat):
        # Mirrors IllusionPower.revive for the public heal; the particle never
        # invents a different follow-up than the audited state machine.
        illusion = enemy.powers.get(PowerId.ILLUSION)
        if illusion is not None:
            illusion.is_reviving = False
        enemy.current_hp = enemy.max_hp
        enemy.escaped = False
        enemy._death_processed = False

    if current == EYE_REVIVE_MOVE:
        follow_up = EYE_DISTRACT_MOVE
        ai.states[EYE_REVIVE_MOVE] = MoveState(EYE_REVIVE_MOVE, _revive_move, [Intent(IntentType.HEAL)],
                                               follow_up_id=follow_up, must_perform_once=True)
    ai._current_state_id = current
    return ai


def enemy_features():
    fields = ("present", "alive", "reviving", "primary", "spawned", "hp/160", "initial_hp/160", "max_hp/160",
              "block/100", "vulnerable/10", "strength/100", "slow", "territorial", "artifact", "illusion",
              "minion", "completed_moves/100", "intent.damage/20", "intent.hits/5")
    fields += tuple("monster." + name for name in MONSTER_IDS)
    fields += tuple("intent." + name for name in INTENTS)
    return (tuple(f"summon_slot{slot}.{field}" for slot in range(MAX_SLOTS) for field in fields)
            + ("pending.target0", "pending.target1"))


def slot_width():
    return 19 + len(MONSTER_IDS) + len(INTENTS)


def encode_slots(info):
    result = []
    for e in info.enemies:
        result += [1, e.hp > 0, e.reviving, e.primary, e.spawned, e.hp / 160, e.initial_hp / 160, e.max_hp / 160,
                   e.block / 100, e.vulnerable / 10, e.strength / 100, e.slow, e.territorial, e.artifact,
                   e.illusion, e.minion, len(e.moves) / 100, e.intent[1] / 20, e.intent[2] / 5]
        result += [e.monster_id == name for name in MONSTER_IDS]
        result += [e.intent[0] == name for name in INTENTS]
    result += [0] * ((MAX_SLOTS - len(info.enemies)) * slot_width())
    result += [info.history.pending_target == slot for slot in range(MAX_SLOTS)]
    return result


def restore_card(token, history):
    """Card factory for particle piles; DAZED is generated-only and unupgraded."""
    if token == DAZED:
        from sts2_env.cards.status import make_dazed
        return make_dazed()
    from .lifecycle import restore_token
    return restore_token(token, history)


def admitted_generated(event, content_version):
    """True for the audited enemy-generated Dazed event."""
    return (content_version == SUMMON_CONTENT and type(event) is CardGeneration
            and event.source_token == DAZED_SOURCE and event.result_token == DAZED
            and event.destination == "discard" and event.mechanism == DAZED_MECHANISM
            and event.count == DISTRACT_DAZED_COUNT)


def terminal_ledger(info):
    ledger = ledger_from_slots(info.enemies)
    return ledger, ledger_rows(ledger), primary_summary(ledger)
