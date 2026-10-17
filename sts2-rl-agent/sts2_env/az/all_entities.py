"""Entity projection for the all-encounter roster.

Card entities are shared with the V4 projection; only enemies come from the
generic public roster.  Each enemy exposes the visible intents (attack values as
damage effects, other intent icons as intent ops), the public powers, and the
public move-graph position/edges.  No monster id and no private state id is a
learned feature.
"""
from __future__ import annotations

from .entity_encoder import Entity, numeric
from .mechanic_registry import Operation as O

INTENT_OPS = {
    'DEFEND': 'intent_defend', 'BUFF': 'intent_buff', 'DEBUFF': 'intent_debuff',
    'DEBUFF_STRONG': 'intent_debuff', 'STATUS_CARD': 'intent_status', 'SUMMON': 'intent_summon',
    'HEAL': 'intent_heal', 'SLEEP': 'intent_sleep', 'STUN': 'intent_stun', 'STUNNED': 'intent_stun',
    'ATTACK_BUFF': 'intent_buff', 'ATTACK_DEFEND': 'intent_defend', 'ATTACK_DEBUFF': 'intent_debuff',
}
POWER_OPS = {
    'STRENGTH': 'strength', 'VULNERABLE': 'vulnerable', 'ARTIFACT': 'artifact',
    'SLOW': 'damage_per_play', 'TERRITORIAL': 'strength_per_turn', 'ILLUSION': 'revive',
    'MINION': 'secondary', 'INTANGIBLE': 'damage_cap', 'NEMESIS': 'alternate_intangible',
    'ADAPTABLE': 'prevent_combat_end', 'ENRAGE': 'strength_per_skill',
    'PAINFUL_STABS': 'wound_per_unblocked_hit', 'PLATING': 'plating',
}


def enemy_entities(info):
    """One entity per public roster slot."""
    from .monster_registry import info_for

    result = []
    for slot in info.enemies:
        script = info_for(slot.monster_id)
        moves = script.moves
        stage = moves.index(slot.move) if slot.move in moves else -1
        last = moves.index(slot.moves[-1]) if slot.moves and slot.moves[-1] in moves else -1
        effects = []
        for intent_type, damage, hits in slot.intents:
            if intent_type in ('ATTACK', 'MULTI_ATTACK'):
                effects.append(O('damage', 'player', 'on_play', int(damage), hits=max(1, int(hits))))
            else:
                effects.append(O(INTENT_OPS.get(intent_type, 'intent_other'), 'player', 'on_play', 0))
        for name, amount in slot.powers:
            effects.append(O(POWER_OPS.get(name, 'public_power'), 'self', 'on_play', int(amount)))
        if stage >= 0:
            effects.append(O('stage', 'self', 'on_play', stage))
            successors = dict(script.successors).get(slot.move, ())
            for target in successors:
                if target in moves:
                    effects.append(O('next_stage', 'self', 'on_play', moves.index(target)))
        for effect in effects:
            effect.validate()
        result.append(Entity(f'enemy/{slot.slot}', 'enemy', 'none', None, numeric(
            hp=slot.hp, max_hp=slot.max_hp, initial_hp=slot.initial_hp, block=slot.block,
            vulnerable=slot.vulnerable, strength=slot.strength, slow=slot.slow,
            territorial=slot.territorial, artifact=slot.artifact, illusion=slot.illusion,
            minion=slot.minion, primary=int(slot.primary), spawned=int(slot.spawned),
            reviving=int(slot.reviving), intent_damage=slot.intents[0][1],
            intent_hits=slot.intents[0][2], enemy_rounds=len(slot.moves),
            cycle_step=max(0, stage), last_stage=last,
            pending_target=int(info.history.pending_target == slot.slot)), tuple(effects)))
    return result

