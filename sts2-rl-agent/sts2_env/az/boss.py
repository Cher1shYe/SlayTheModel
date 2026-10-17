"""Versioned Boss integration. Only public decision facts enter this module."""
from dataclasses import replace
from collections import Counter

from .content import BOSS_CONTENT, EXPANSION_CONTENT, SUMMON_CONTENT
from .rewards import V5, V6, V7
from .boss_phases import BossPhaseState, FORM_HP, KNOCKOUT, DEFEAT, RESPAWN, CLAW, POUNCE, GROWL
from .boss_reconstruction import BossEnemySnapshot, capture_enemy, create_enemy, restore_enemy
from .card_generation import CardGeneration
from sts2_env.core.enums import PowerId

MONSTER = "TEST_SUBJECT"


def canonical_phase(hp, maximum):
    if maximum not in FORM_HP or type(hp) is not int:
        raise ValueError("Unknown Boss form HP")
    stage = FORM_HP.index(maximum)
    events = (KNOCKOUT, RESPAWN) * stage
    if hp == 0:
        events += (DEFEAT if stage == 2 else KNOCKOUT,)
    return BossPhaseState(hp, events).validate()


def phase_rows(phase):
    stage, _, _, _ = phase.cursor
    return ({"boss_phase": canonical_phase(phase.hp, FORM_HP[stage]).to_dict()},)


def rows_summary(rows):
    if len(rows) == 1 and "boss_phase" in rows[0]:
        if set(rows[0]) != {"boss_phase"}:
            raise ValueError("Unexpected Boss reward metadata")
        phase = BossPhaseState.from_dict(rows[0]["boss_phase"])
        stage, _, _, _ = phase.cursor
        return 600, phase.hp + sum(FORM_HP[stage + 1:]), 600
    from .summon import ledger_from_rows, primary_summary
    return primary_summary(ledger_from_rows(rows))


def reward_from_rows(reason, hp, initial_hp, initial, remaining, maximum, rows):
    if not isinstance(rows, (tuple, list)) or not rows or rows_summary(rows) != (initial, remaining, maximum):
        raise ValueError("V6 reward ledger disagrees with aggregates")
    if "boss_phase" in rows[0]:
        return BossPhaseState.from_dict(rows[0]["boss_phase"]).terminal_reward(reason, hp, initial_hp)
    from .summon import ledger_from_rows
    return ledger_from_rows(rows).terminal_reward(reason, hp, initial_hp)


def capture_reward(world, initial_hp):
    if world.enemies[0].monster_id == MONSTER:
        enemy = world.enemies[0]
        return phase_rows(canonical_phase(max(0, enemy.current_hp), enemy.max_hp))
    from .summon import capture_ledger, ledger_rows
    return ledger_rows(capture_ledger(world, initial_hp))


def admitted_generation(event, content):
    return (content in (BOSS_CONTENT, EXPANSION_CONTENT) and type(event) is CardGeneration
            and event.destination == "discard" and type(event.count) is int and event.count > 0
            and ((event.source_token == "TEST_SUBJECT.PAINFUL_STABS" and event.result_token == "WOUND"
                  and event.mechanism == "boss-wound-v1" and event.count <= 52)
                 or (event.source_token == "TEST_SUBJECT.BURNING_GROWL" and event.result_token == "BURN"
                     and event.mechanism == "boss-burn-v1" and event.count == 3)))


def generation_after(before, ended, decision):
    if before.monster_id != MONSTER:
        from .summon import generation_after as old
        return old(before, ended, decision)
    if ended:
        return ()
    stage, life, move, _ = before.boss.phase.cursor
    if life != "alive":
        return ()
    if move == GROWL:
        return (CardGeneration(decision, "TEST_SUBJECT.BURNING_GROWL", "BURN", "discard", "boss-burn-v1", 3),)
    if stage != 1 or move not in (CLAW, POUNCE):
        return ()
    # Only these player powers are admitted. Burn consumes block before the
    # enemy attacks. Vulnerable ticks at enemy turn end, after all hits.
    from .player_abilities import block_before_enemy
    block = block_before_enemy(before)
    damage = int((before.intent[1] + before.enemy_strength) * (1.5 if before.player_vulnerable else 1))
    if before.content_version == EXPANSION_CONTENT:
        from .foundation import amount
        import math
        damage=max(0,math.floor((before.intent[1]+before.enemy_strength)
            *(1.5 if before.player_vulnerable else 1)
            *(.75 if amount(before,0,'WEAK') else 1)
            *(.5 if amount(before,-1,'COLOSSUS') and before.vulnerable else 1)))
    count = 0
    for _ in range(before.intent[2]):
        count += int(damage > block)
        block = max(0, block - damage)
    return ((CardGeneration(decision, "TEST_SUBJECT.PAINFUL_STABS", "WOUND", "discard", "boss-wound-v1", count),)
            if count else ())


def after_round(before, ended):
    if before.monster_id != MONSTER:
        from .summon import after_round as old
        return old(before, ended)
    return (before.history.enemy_moves + (() if ended else (before.boss.phase.cursor[2],)),)


def finish_history(before, world, history, action):
    """Actual public HP confirms knockout; do not inspect hidden AI memory."""
    from .content import EXPANSION_CONTENT
    if before.content_version == EXPANSION_CONTENT:
        from .simple_cards import finish_history as finish_simple
        history = finish_simple(before, world, history)
        from .extended_choices import finish_history as finish_choices
        history = finish_choices(before,world,history,action)
        from .execution import finish_history as finish_execution
        history = finish_execution(before,world,history)
        from .public_rounds import finish
        return finish(before,world,history)
    if before.monster_id != MONSTER:
        return history
    events = before.history.boss_events
    phase = before.boss.phase
    if action == 0 and before.choice is None and not world.is_over:
        events += (phase.cursor[2],)
    enemy = world.enemies[0]
    if phase.hp > 0 and enemy.current_hp == 0:
        events += (DEFEAT if phase.cursor[0] == 2 else KNOCKOUT,)
    return replace(history, boss_events=events)


def capture(world, history, initial_hp):
    if world.enemies[0].monster_id != MONSTER:
        from .summon import capture_slots
        return capture_slots(world, history, initial_hp), None
    enemy = world.enemies[0]
    phase = BossPhaseState(max(0, enemy.current_hp), history.boss_events).validate()
    snapshot = (BossEnemySnapshot(phase, enemy.block, tuple(sorted((p.name, value.amount) for p, value in enemy.powers.items()))).validate()
                if world.is_over else capture_enemy(enemy, world.enemy_ais[enemy.combat_id].current_move.intents, phase))
    from .summon import SlotState
    intent = phase.intent[0] if phase.intent else ("ATTACK", 0, 1)
    p = dict(snapshot.powers)
    slot = SlotState(0, MONSTER, 100, phase.hp, enemy.max_hp, enemy.block,
                     p.get("VULNERABLE", 0), p.get("STRENGTH", 0), 0, 0, 0, 0, 0,
                     True, False, phase.cursor[1] == "reviving", intent, history.enemy_moves)
    return (slot,), snapshot


def validate(info):
    if info.reward_version not in (V6, V7) or info.limits.max_turns > 100 or info.limits.max_decisions > 400:
        raise ValueError("Boss content requires V6 and proven capacity budgets")
    if info.monster_id != MONSTER:
        if info.boss is not None or info.history.boss_events:
            raise ValueError("Boss phase in another encounter")
        from .summon import validate_slots
        validate_slots(replace(info, content_version=SUMMON_CONTENT, reward_version=V5))
        return
    if type(info.boss) is not BossEnemySnapshot or len(info.enemies) != 1:
        raise ValueError("Missing public Boss snapshot")
    info.boss.validate()
    phase = info.boss.phase
    stage, life, move, _ = phase.cursor
    slot = info.enemies[0]
    if (phase.events != info.history.boss_events or phase.hp != info.enemy_hp
            or info.enemy_max_hp != FORM_HP[stage] or info.enemy_initial_hp != 100
            or slot.hp != info.enemy_hp or slot.max_hp != info.enemy_max_hp
            or slot.monster_id != MONSTER or slot.slot != 0 or not slot.primary or slot.spawned
            or slot.moves != info.history.enemy_moves or (info.history.roster_moves or ((),)) != (slot.moves,)):
        raise ValueError("Boss phase and public projections disagree")
    if info.termination_reason is None:
        if info.turn != len(info.history.enemy_moves) + 1 or info.player_hp <= 0 or life == "defeated":
            raise ValueError("Boss public turn or terminal mismatch")
        if info.intent != phase.intent[0]:
            raise ValueError("Boss intent mismatch")
    powers = dict(info.boss.powers)
    from .summon import SlotState
    expected_slot = SlotState(0, MONSTER, 100, phase.hp, FORM_HP[stage], info.boss.block,
                             powers.get("VULNERABLE", 0), powers.get("STRENGTH", 0), 0, 0, 0, 0, 0,
                             True, False, life == "reviving",
                             phase.intent[0] if phase.intent else ("ATTACK", 0, 1), info.history.enemy_moves)
    if slot != expected_slot:
        raise ValueError("Boss slot disagrees with phase snapshot")
    burns = [event for event in info.history.generated if event.mechanism == "boss-burn-v1"]
    if len(burns) != phase.events.count(GROWL):
        raise ValueError("Boss Burn generation disagrees with completed public moves")
    if (info.enemy_strength != powers.get("STRENGTH", 0) or info.vulnerable != powers.get("VULNERABLE", 0)
            or info.enemy_block != info.boss.block):
        raise ValueError("Boss public power projections disagree")
    if info.termination_reason is not None:
        phase.terminal_reward(info.termination_reason, info.player_hp, info.initial_hp)


def check_transition(before, world, slots):
    if before.monster_id == MONSTER:
        if tuple(world.enemies) != slots:
            raise ValueError("Boss native slot identity changed")
    else:
        from .summon import check_transition as old
        old(before, world, slots)


def create_enemies(world, info, rng):
    if info.monster_id != MONSTER:
        from .summon import create_enemies as old
        return old(world, info, rng)
    enemy, ai = create_enemy(info.boss, rng)
    world.add_enemy(enemy, ai)
    return world


def restore_enemies(world, info, rng):
    if info.monster_id != MONSTER:
        from .summon import restore_enemies as old
        return old(world, info, rng)
    enemy = world.enemies[0]
    restore_enemy(enemy, world.enemy_ais[enemy.combat_id], info.boss)
    return world


def numeric_names():
    from .summon import enemy_features
    return (tuple(f"boss.{pile}.{token}/2145" for pile in ("draw", "discard", "exhaust", "deck", "removed", "played")
                  for token in ("DAZED", "BURN", "WOUND"))
            + enemy_features()
            + ("boss.present", "boss.phase/3", "boss.reviving", "boss.claws/50",
               "boss.adaptable", "boss.enrage/2", "boss.painful_stabs", "boss.nemesis", "boss.intangible"))


def encode(info):
    from .summon import encode_slots
    values = [Counter(pile)[token] / 2145 for pile in (info.draw_composition, info.discard, info.exhaust,
              info.known_deck, info.history.removed_powers, info.history.played_this_turn) for token in ("DAZED", "BURN", "WOUND")]
    values += encode_slots(info)
    if info.boss is None:
        return values + [0] * 9
    phase, life, _, claws = info.boss.phase.cursor
    powers = dict(info.boss.powers)
    return values + [1, (phase + 1) / 3, life == "reviving", claws / 50,
                     powers.get("ADAPTABLE", 0), powers.get("ENRAGE", 0) / 2,
                     powers.get("PAINFUL_STABS", 0), powers.get("NEMESIS", 0), powers.get("INTANGIBLE", 0)]
