"""V2 public player abilities: observed amounts and reproducible play history.

Only stateless single-player hooks are admitted. Deferred draws/damage callbacks
are deliberately excluded until their continuation state has a public contract.
"""
from collections import Counter
from .content import EXPANSION_CONTENT
from .mechanic_registry import Operation as O
from sts2_env.core.enums import PowerId

POWER_IDS = {n: PowerId[n] for n in ('BARRICADE', 'RAGE', 'FEEL_NO_PAIN', 'DEMON_FORM', 'FASTEN', 'PLATING','NO_DRAW',
                                     'TANK', 'CORRUPTION', 'BEACON_OF_HOPE',
                                     'NOSTALGIA', 'THE_GAMBIT', 'BLOCK_NEXT_TURN',
                                     'AUTOMATION', 'PANACHE', 'ROLLING_BOULDER', 'THE_BOMB')}
CARD_POWER = {'BARRICADE_CARD': ('BARRICADE', None), 'RAGE_CARD': ('RAGE', 'power'),
    'FEEL_NO_PAIN_CARD': ('FEEL_NO_PAIN', 'power'), 'DEMON_FORM_CARD': ('DEMON_FORM', 'strength'),
    'FASTEN': ('FASTEN', 'extra_block'), 'ETERNAL_ARMOR': ('PLATING', 'plating'), 'STONE_ARMOR': ('PLATING','plating'), 'BATTLE_TRANCE': ('NO_DRAW',None),
    'TANK_CARD': ('TANK', None), 'CORRUPTION_CARD': ('CORRUPTION', None), 'BEACON_OF_HOPE': ('BEACON_OF_HOPE', None),
    'NOSTALGIA_CARD': ('NOSTALGIA', None), 'THE_GAMBIT': ('THE_GAMBIT', None), 'PROLONG': ('BLOCK_NEXT_TURN', None),
    'AUTOMATION': ('AUTOMATION', 'energy'), 'PANACHE_CARD': ('PANACHE', 'panache_damage'),
    'ROLLING_BOULDER': ('ROLLING_BOULDER', 'rolling_boulder'), 'THE_BOMB_CARD': ('THE_BOMB', 'turns')}
# The accumulated amount of these powers is the block observed when the card was
# played or a displayed countdown/counter; it is public and displayed, but not
# re-derivable from the condensed play ledger alone, so it is validated as an
# observed amount plus an explicit public lifecycle.
RAW_POWERS = frozenset({'BLOCK_NEXT_TURN', 'AUTOMATION', 'PANACHE', 'ROLLING_BOULDER', 'THE_BOMB'})
# Powers whose public amount saturates at one; others accumulate every play.
# TANK/CORRUPTION are declared single in the native C# but this simulator keeps
# increasing their amount, so the public ledger follows the executed engine.
SINGLE_POWERS = frozenset({'BARRICADE', 'NO_DRAW'})


def rules(name, amount):
    if name == 'BARRICADE': return (O('keep_block', 'self', 'turn_start', 1),)
    if name == 'RAGE': return (O('block_per_attack', 'self', 'after_attack_play', amount), O('remove', 'self', 'player_turn_end', 1))
    if name == 'FEEL_NO_PAIN': return (O('block_per_exhaust', 'self', 'on_exhaust', amount),)
    if name == 'DEMON_FORM': return (O('strength_per_turn', 'self', 'turn_start', amount),)
    if name == 'FASTEN': return (O('defend_block_bonus', 'self', 'powered_card_block', amount),)
    if name == 'NO_DRAW': return (O('no_draw','self','outside_hand_draw',1), O('remove','self','player_turn_end',1))
    if name == 'PLATING': return (O('plating', 'self', 'player_turn_end', amount), O('decrement', 'self', 'enemy_turn_end', 1))
    if name == 'TANK': return (O('damage_multiplier', 'self', 'incoming_powered_attack', 2),)
    if name == 'CORRUPTION': return (O('skill_cost_zero', 'hand', 'playability', 1), O('skill_exhaust', 'hand', 'after_play', 1))
    if name == 'BEACON_OF_HOPE': return (O('ally_guard', 'ally', 'after_block', amount),)
    if name == 'NOSTALGIA': return (O('to_draw_top', 'hand', 'after_play', amount),)
    if name == 'THE_GAMBIT': return (O('lethal_on_unblocked', 'self', 'incoming_powered_attack', 1),)
    if name == 'BLOCK_NEXT_TURN': return (O('defer_block', 'self', 'turn_start', amount),)
    if name == 'AUTOMATION': return (O('energy_per_draws', 'self', 'on_draw', amount, coefficient=10),)
    if name == 'PANACHE': return (O('damage_per_plays', 'all_enemies', 'after_play', amount, coefficient=5),)
    if name == 'ROLLING_BOULDER': return (O('damage', 'all_enemies', 'turn_start', amount), O('damage', 'all_enemies', 'turn_start', 5, condition='always'))
    if name == 'THE_BOMB': return (O('damage', 'all_enemies', 'player_turn_end', 40),)
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
            expected.pop('RAGE', None); expected.pop('NO_DRAW', None)
            expected['PLATING'] = max(0, expected.get('PLATING', 0) - (turn-last))
        name, amount = value(token)
        if name not in RAW_POWERS:
            expected[name] = 1 if name in SINGLE_POWERS else expected.get(name, 0) + amount
        last = turn
    if info.turn > last:
        expected.pop('RAGE', None); expected.pop('NO_DRAW', None)
        expected['PLATING'] = max(0, expected.get('PLATING', 0) - (info.turn-last))
    expected = {k:v for k,v in expected.items() if v}
    if info.termination_reason != 'death':
        current = Counter(t for t, turn in events if turn == info.turn)
        played = Counter(e[1] for e in info.history.public_events if e[0]=='finish' and e[2]==info.turn and e[1].removesuffix('+') in CARD_POWER)
        if current != played: raise ValueError('Ability plays disagree with current turn history')
    if len(events) > info.history.decisions and not info.history.public_events:
        raise ValueError('Ability plays exceed decisions')
    from .deck_observation import prototype
    removed = Counter(t for t, _ in events if prototype(t).is_power)
    from .foundation import FACTORIES as BASIC_FACTORIES
    actual = Counter(t for t in info.history.removed_powers if t.removesuffix('+') != 'INFLAME' and t.removesuffix('+') not in BASIC_FACTORIES)
    if removed != actual: raise ValueError('Ability ledger and removed power cards disagree')
    # Observed-only powers: the amount is displayed public state that cannot be
    # rebuilt from the condensed ledger, so only its presence/lifecycle is checked.
    observed = dict(abilities)
    last_play = {}
    for token, turn in events:
        last_play[token.removesuffix('+')] = turn
    if observed.get('BLOCK_NEXT_TURN'):
        if last_play.get('PROLONG') != info.turn:
            raise ValueError('Next-turn block power without a current-turn Prolong play')
    if info.termination_reason is None:
        for power, card in (('AUTOMATION', 'AUTOMATION'), ('PANACHE', 'PANACHE_CARD'),
                            ('ROLLING_BOULDER', 'ROLLING_BOULDER')):
            if (power in observed) != (card in last_play):
                raise ValueError(f'{power} presence disagrees with its play ledger')
        if 'THE_BOMB' in observed:
            played = last_play.get('THE_BOMB_CARD')
            if played is None or not 0 <= info.turn - played <= 2:
                raise ValueError('The Bomb countdown disagrees with its play ledger')
        elif 'THE_BOMB_CARD' in last_play and info.turn - last_play['THE_BOMB_CARD'] <= 2:
            raise ValueError('The Bomb must still be counting down')
    derived = {k: v for k, v in observed.items() if k not in RAW_POWERS}
    # Death may clear powers and abort a round before its tick/start hooks.
    if info.termination_reason != 'death' and derived != expected:
        raise ValueError(f'Public abilities disagree with plays: {derived} != {expected}')


def block_before_enemy(info):
    """Deterministic pre-enemy hooks, including ethereal exhaust before Burn."""
    from .deck_observation import prototype
    p = dict(info.player_abilities)
    return max(0, info.player_block + p.get('PLATING', 0)
        + p.get('FEEL_NO_PAIN', 0) * sum(prototype(t).is_ethereal for t in info.hand)
        - 2 * info.hand.count('BURN'))

