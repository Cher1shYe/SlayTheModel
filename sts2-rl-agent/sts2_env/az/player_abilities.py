"""V2 public player abilities: observed amounts and reproducible play history.

Only stateless single-player hooks are admitted. Deferred draws/damage callbacks
are deliberately excluded until their continuation state has a public contract.
"""
from collections import Counter
from .content import EXPANSION_CONTENT
from .mechanic_registry import Operation as O
from sts2_env.core.enums import PowerId

POWER_IDS = {n: PowerId[n] for n in ('BARRICADE', 'RAGE', 'FEEL_NO_PAIN', 'DEMON_FORM', 'FASTEN', 'PLATING')}
CARD_POWER = {'BARRICADE_CARD': ('BARRICADE', None), 'RAGE_CARD': ('RAGE', 'power'),
    'FEEL_NO_PAIN_CARD': ('FEEL_NO_PAIN', 'power'), 'DEMON_FORM_CARD': ('DEMON_FORM', 'strength'),
    'FASTEN': ('FASTEN', 'extra_block'), 'ETERNAL_ARMOR': ('PLATING', 'plating')}


def rules(name, amount):
    if name == 'BARRICADE': return (O('keep_block', 'self', 'turn_start', 1),)
    if name == 'RAGE': return (O('block_per_attack', 'self', 'after_attack_play', amount), O('remove', 'self', 'player_turn_end', 1))
    if name == 'FEEL_NO_PAIN': return (O('block_per_exhaust', 'self', 'on_exhaust', amount),)
    if name == 'DEMON_FORM': return (O('strength_per_turn', 'self', 'turn_start', amount),)
    if name == 'FASTEN': return (O('defend_block_bonus', 'self', 'powered_card_block', amount),)
    if name == 'PLATING': return (O('plating', 'self', 'player_turn_end', amount), O('decrement', 'self', 'enemy_turn_end', 1))
    raise ValueError('Unsupported public player ability')


def card_effects(name, variables):
    power, key = CARD_POWER[name]
    return rules(power, variables[key] if key else 1)


def active_effects(abilities):
    return tuple(o for name, amount in abilities for o in rules(name, amount))


def value(token):
    from .deck_observation import prototype
    name = token.removesuffix('+')
    power, key = CARD_POWER[name]
    return power, prototype(token).effect_vars[key] if key else 1


def demon_strength(info):
    return sum(value(token)[1] * (info.turn - turn) for token, turn in info.history.ability_plays
               if token.removesuffix('+') == 'DEMON_FORM_CARD')


def validate(info):
    abilities, events = info.player_abilities, info.history.ability_plays
    if type(abilities) is not tuple or type(events) is not tuple:
        raise ValueError('Public abilities must be immutable')
    if info.content_version != EXPANSION_CONTENT:
        if abilities or events: raise ValueError('Player abilities outside versioned contract')
        return
    seen = set()
    for row in abilities:
        if (type(row) is not tuple or len(row) != 2 or row[0] not in POWER_IDS or row[0] in seen
                or type(row[1]) is not int or not 0 < row[1] <= 10000):
            raise ValueError('Invalid public ability amount/identity')
        seen.add(row[0])
    expected, last = {}, 1
    for row in events:
        if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                or row[0].removesuffix('+') not in CARD_POWER or type(row[1]) is not int
                or not last <= row[1] <= info.turn):
            raise ValueError('Invalid public ability play ledger')
        token, turn = row
        if turn > last:
            expected.pop('RAGE', None)
            expected['PLATING'] = max(0, expected.get('PLATING', 0) - (turn-last))
        name, amount = value(token)
        expected[name] = 1 if name == 'BARRICADE' else expected.get(name, 0) + amount
        last = turn
    if info.turn > last:
        expected.pop('RAGE', None)
        expected['PLATING'] = max(0, expected.get('PLATING', 0) - (info.turn-last))
    expected = {k:v for k,v in expected.items() if v}
    if info.termination_reason != 'death':
        current = Counter(t for t, turn in events if turn == info.turn)
        played = Counter(t for t in info.history.played_this_turn if t.removesuffix('+') in CARD_POWER)
        if current != played: raise ValueError('Ability plays disagree with current turn history')
    if len(events) > info.history.decisions:
        raise ValueError('Ability plays exceed decisions')
    removed = Counter(t for t, _ in events if t.removesuffix('+') != 'RAGE_CARD')
    actual = Counter(t for t in info.history.removed_powers if t.removesuffix('+') != 'INFLAME')
    if removed != actual: raise ValueError('Ability ledger and removed power cards disagree')
    # Death may clear powers and abort a round before its tick/start hooks.
    if info.termination_reason != 'death' and dict(abilities) != expected:
        raise ValueError(f'Public abilities disagree with plays: {dict(abilities)} != {expected}')


def block_before_enemy(info):
    """Deterministic pre-enemy hooks, including ethereal exhaust before Burn."""
    from .deck_observation import prototype
    p = dict(info.player_abilities)
    return max(0, info.player_block + p.get('PLATING', 0)
        + p.get('FEEL_NO_PAIN', 0) * sum(prototype(t).is_ethereal for t in info.hand)
        - 2 * info.hand.count('BURN'))

