"""Audited starter semantics. Content IDs are lookup keys, never model features.

Sources: cards/ironclad_basic.py, monsters/act1_weak.py, powers/common.py
and powers/monster.py. Extending this registry requires an engine parity test.
"""
from dataclasses import dataclass, asdict

from .config import content_hash

OPS = ('none', 'damage', 'block', 'vulnerable', 'shrink', 'damage_multiplier', 'decrement', 'remove')
TARGETS = ('none', 'self', 'enemy', 'player')
TIMINGS = ('none', 'on_play', 'first_enemy_turn', 'odd_enemy_turn', 'even_enemy_turn',
           'outgoing_powered_attack', 'incoming_powered_attack', 'enemy_turn_end', 'applier_death')


@dataclass(frozen=True)
class Operation:
    kind: str
    target: str
    timing: str
    amount: float
    hits: int = 1

    def validate(self):
        if self.kind not in OPS or self.target not in TARGETS or self.timing not in TIMINGS:
            raise ValueError(f'Unsupported mechanic path: {self}')
        if not isinstance(self.amount, (int, float)) or not float('-inf') < self.amount < float('inf') or self.hits < 1:
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
REGISTRY_VERSION = 'starter-mechanics-v1'
REGISTRY_HASH = content_hash({'version': REGISTRY_VERSION, 'cards': {k: asdict(v) for k, v in CARDS.items()},
                              'shrinker': [asdict(v) for v in SHRINKER],
                              'powers': {k: [asdict(v) for v in ops] for k, ops in POWER_RULES.items()},
                              'ops': OPS, 'targets': TARGETS, 'timings': TIMINGS})


def card_descriptor(name):
    try:
        return CARDS[name]
    except KeyError as exc:
        raise ValueError(f'Unsupported mechanic path: cards/{name}') from exc
