"""Audited starter semantics. Content IDs are lookup keys, never model features.

Sources: cards/ironclad_basic.py, monsters/act1_weak.py, powers/common.py
and powers/monster.py. Extending this registry requires an engine parity test.
"""
from dataclasses import dataclass, asdict

from .config import content_hash

OPS = ('none', 'damage', 'block', 'vulnerable', 'shrink', 'damage_multiplier', 'decrement', 'remove')
OPS += ('draw', 'energy', 'hp_loss', 'strength', 'exhaust', 'retain', 'ethereal', 'unplayable',
        'damage_from_block', 'damage_per_exhaust', 'choose_exhaust', 'random_exhaust', 'choose_upgrade',
        'upgrade_hand', 'choose_topdeck', 'generate_copy', 'generate', 'cost', 'transform_attacks',
        'damage_per_energy', 'cost_per_attack', 'retain_hand', 'damage_unpowered', 'stage', 'next_stage',
        'random_branch', 'summon', 'revive', 'secondary', 'artifact', 'strength_per_skill', 'strength_per_turn',
        'damage_per_play', 'clear_turn', 'damage_cap', 'finite_forms', 'wound_per_unblocked_hit', 'alternate_intangible')
OPS += ('hits_per_claw', 'untargetable', 'clear_debuffs', 'prevent_combat_end')
OPS += ('clear_form_powers', 'advance_phase', 'draw_to_hand_limit')
OPS += ('damage_per_vulnerable', 'damage_conditional_hits', 'strength_from_target_vulnerable', 'multiply_vulnerable')
OPS += ('keep_block', 'block_per_attack', 'block_per_exhaust', 'defend_block_bonus', 'plating', 'defend_tag')
OPS += ('damage_per_finished_attack','energy_per_hand_attack','damage_per_strike_card','draw_until_nonattack',
        'exhaust_hand','damage_per_exhausted_hand','exhaust_nonattacks_with_block','draw_per_exhausted_hand',
        'require_exhaust_count','no_draw','innate','block_from_damage_result','damage_per_draw_card',
        'splash_damage_result','damage_per_debuff_type','strike_tag')
TARGETS = ('none', 'self', 'enemy', 'player')
TARGETS += ('all_enemies', 'hand', 'discard', 'draw_bottom', 'generated', 'applier')
TARGETS += ('random_enemy','other_enemies')
TIMINGS = ('none', 'on_play', 'first_enemy_turn', 'odd_enemy_turn', 'even_enemy_turn',
           'outgoing_powered_attack', 'incoming_powered_attack', 'enemy_turn_end', 'applier_death')
TIMINGS += ('after_play', 'turn_end_hand', 'before_attack_play', 'generated_card', 'generated_on_play',
            'generated_after_play', 'on_skill_play', 'on_card_play', 'on_unblocked_hit', 'on_death', 'turn_start')
TIMINGS += ('player_turn_end', 'after_attack_play', 'on_exhaust', 'powered_card_block')
TIMINGS += ('after_play_damage','after_exhaust','playability','outside_hand_draw','opening_hand')
CONDITIONS = ('always', 'hand_empty', 'phase0', 'phase1', 'phase2', 'alive', 'if_hand_nonempty', 'unupgraded', 'reviving')
CONDITIONS += ('target_vulnerable', 'target_alive','exhausted_this_turn','combat_active','no_attacks_in_hand')


@dataclass(frozen=True)
class Operation:
    kind: str
    target: str
    timing: str
    amount: float
    hits: int = 1
    condition: str = 'always'
    coefficient: float = 0.

    def validate(self):
        if self.kind not in OPS or self.target not in TARGETS or self.timing not in TIMINGS or self.condition not in CONDITIONS:
            raise ValueError(f'Unsupported mechanic path: {self}')
        if (not isinstance(self.amount, (int, float)) or not float('-inf') < self.amount < float('inf')
                or type(self.hits) is not int or self.hits < 1 or not float('-inf') < self.coefficient < float('inf')):
            raise ValueError('Invalid mechanic parameters')
        return self


@dataclass(frozen=True)
class MechanicDescriptor:
    card_type: int  # 0 non-card, 1 attack, 2 skill
    cost: int
    target: str
    effects: tuple[Operation, ...]


POWER_RULES = {
    'shrink': (Operation('damage_multiplier', 'self', 'outgoing_powered_attack', .7),
               Operation('remove', 'self', 'applier_death', 1)),
    'vulnerable': (Operation('damage_multiplier', 'self', 'incoming_powered_attack', 1.5),
                   Operation('decrement', 'self', 'enemy_turn_end', 1)),
}


CARDS = {
    'STRIKE_IRONCLAD': MechanicDescriptor(1, 1, 'enemy', (Operation('damage', 'enemy', 'on_play', 6),)),
    'DEFEND_IRONCLAD': MechanicDescriptor(2, 1, 'self', (Operation('block', 'self', 'on_play', 5),)),
    'BASH': MechanicDescriptor(1, 2, 'enemy', (Operation('damage', 'enemy', 'on_play', 8), Operation('vulnerable', 'enemy', 'on_play', 2))),
}
SHRINKER = (
    Operation('shrink', 'player', 'first_enemy_turn', -1),
    Operation('damage', 'player', 'odd_enemy_turn', 7),
    Operation('damage', 'player', 'even_enemy_turn', 13),
)
REGISTRY_VERSION = 'ironclad-colorless-mechanics-v3'
REGISTRY_HASH = content_hash({'version': REGISTRY_VERSION, 'cards': {k: asdict(v) for k, v in CARDS.items()},
                              'shrinker': [asdict(v) for v in SHRINKER],
                              'powers': {k: [asdict(v) for v in ops] for k, ops in POWER_RULES.items()},
                              'ops': OPS, 'targets': TARGETS, 'timings': TIMINGS, 'conditions': CONDITIONS})


def card_descriptor(name):
    from .expanded_mechanics import describe_card
    return describe_card(name)
