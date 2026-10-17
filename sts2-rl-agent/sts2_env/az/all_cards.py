"""Batch 5: remaining Ironclad/Colorless cards admitted for single-player combat.

Scope is still one Ironclad player, no relics/potions, ascension 0. Three card
classes are handled explicitly:

* **single-player mechanics** – the native effect has a real single-player
  consequence (damage, block, max HP, status, return-to-hand, powers), and the
  public contract records exactly that consequence;
* **multiplayer-only** – the native effect needs another player (ANY_ALLY /
  ALL_ALLIES targeting).  With one player there is no legal ally target, so the
  card can never be played and has no state transition.  The descriptor still
  states the intended ally effect and its `ally_required` condition; nothing is
  silently dropped.
* **out-of-combat reward** – gold/potion gains change run state, not combat
  state; only the in-combat damage is described.

Deferred tokens are excluded from FACTORIES and stay refused by the admission
path: ALCHEMIZE (potions outside combat scope), ENTROPY / JACK_OF_ALL_TRADES /
SPLASH (cross-character generation pools), HIDDEN_GEM (hidden draw-pile card
identity mutation).  Deferral is recorded in docs/IRONCLAD_COLORLESS_COVERAGE.md.
"""
from sts2_env.cards import colorless, ironclad

from .mechanic_registry import MechanicDescriptor, Operation as O

FACTORIES = {
    'CORRUPTION_CARD': ironclad.make_corruption,
    'FEED': ironclad.make_feed,
    'TANK_CARD': ironclad.make_tank,
    'KNOCKDOWN': colorless.make_knockdown,
    'TAG_TEAM': colorless.make_tag_team,
    'GANG_UP': colorless.make_gang_up,
    'HAND_OF_GREED': colorless.make_hand_of_greed,
    'GOLD_AXE': colorless.make_gold_axe,
    'BOLAS': colorless.make_bolas,
    'THRUMMING_HATCHET': colorless.make_thrumming_hatchet,
    'BEACON_OF_HOPE': colorless.make_beacon_of_hope,
    'NOSTALGIA_CARD': colorless.make_nostalgia_card,
    'THE_GAMBIT': colorless.make_the_gambit,
    'PROLONG': colorless.make_prolong,
    'AUTOMATION': colorless.make_automation,
    'PANACHE_CARD': colorless.make_panache_card,
    'ROLLING_BOULDER': colorless.make_rolling_boulder,
    'THE_BOMB_CARD': colorless.make_the_bomb_card,
    'DEMONIC_SHIELD': ironclad.make_demonic_shield,
    'BELIEVE_IN_YOU': colorless.make_believe_in_you,
    'COORDINATE_CARD': colorless.make_coordinate_card,
    'INTERCEPT_CARD': colorless.make_intercept_card,
    'LIFT': colorless.make_lift,
    'MIMIC': colorless.make_mimic,
    'HUDDLE_UP': colorless.make_huddle_up,
    'RALLY': colorless.make_rally,
}

# Powers are executed through the audited player-ability registry; the card
# descriptor is supplied by player_abilities.card_effects, not here.
POWER_CARDS = ('CORRUPTION_CARD', 'TANK_CARD', 'BEACON_OF_HOPE',
               'NOSTALGIA_CARD', 'THE_GAMBIT', 'PROLONG',
               'AUTOMATION', 'PANACHE_CARD', 'ROLLING_BOULDER', 'THE_BOMB_CARD')

# Native ANY_ALLY effects; unplayable while the owner has no living ally.
ALLY_REQUIRED = ('DEMONIC_SHIELD', 'BELIEVE_IN_YOU', 'COORDINATE_CARD',
                 'INTERCEPT_CARD', 'LIFT', 'MIMIC')
# Native ALL_ALLIES effects; playable, but every target is a teammate.
ALLY_ONLY = ('HUDDLE_UP', 'RALLY')

# Tokens whose only out-of-combat effect is gold/potion inventory.
OUT_OF_COMBAT = ('HAND_OF_GREED',)

# Cards that return to hand before the next hand draw.  The native marker
# (combat_vars['_return_before_hand_draw_round']) is fully derived from the
# public play history: one instance per play made this turn carries it, and
# copies of the same face are interchangeable, so the particle can restore the
# multiset of returning faces without a hidden card index.
RETURNING = frozenset({'BOLAS', 'THRUMMING_HATCHET'})


def descriptor(card):
    name, v = card.card_id.name, card.effect_vars
    target = {'SELF': 'self', 'ANY_ENEMY': 'enemy', 'ALL_ENEMIES': 'all_enemies',
              'ANY_ALLY': 'ally', 'ALL_ALLIES': 'allies'}[card.target_type.name]
    damage = O('damage', 'enemy', 'on_play', card.base_damage or 0)
    if name in POWER_CARDS:
        from .player_abilities import card_effects
        effects = list(card_effects(name, v))
    elif name == 'FEED':
        effects = [damage, O('gain_max_hp', 'self', 'on_death', v['max_hp'], condition='target_alive')]
    elif name == 'KNOCKDOWN':
        effects = [damage, O('knockdown', 'enemy', 'on_play', v['knockdown']),
                   O('duration', 'enemy', 'enemy_turn_end', 1)]
    elif name == 'TAG_TEAM':
        # Native amount is the fixed one-stack debuff; only another player's
        # attack can trigger it, so single-player it stays visible and inert.
        effects = [damage, O('tag_team', 'enemy', 'on_play', 1),
                   O('duration', 'enemy', 'enemy_turn_end', 1)]
    elif name == 'GANG_UP':
        effects = [O('damage', 'enemy', 'on_play', v['calc_base']),
                   O('damage', 'enemy', 'on_play', v['extra_damage'], coefficient=1, condition='ally_present')]
    elif name == 'HAND_OF_GREED':
        effects = [damage, O('gold', 'self', 'on_death', v['gold'], condition='target_alive')]
    elif name == 'GOLD_AXE':
        effects = [O('damage_per_play', 'enemy', 'on_play', v['calc_base'], coefficient=v['extra_damage'])]
    elif name in ('BOLAS', 'THRUMMING_HATCHET'):
        effects = [damage, O('return_to_hand', 'self', 'before_hand_draw', 1)]
    elif name == 'DEMONIC_SHIELD':
        effects = [O('hp_loss', 'self', 'on_play', v['hp_loss']),
                   O('block', 'ally', 'on_play', v['calc_extra'], coefficient=v['calc_extra'],
                     condition='ally_required')]
    elif name == 'BELIEVE_IN_YOU':
        effects = [O('energy', 'ally', 'on_play', v['energy'], condition='ally_required')]
    elif name == 'COORDINATE_CARD':
        effects = [O('strength', 'ally', 'on_play', v['strength'], condition='ally_required')]
    elif name == 'INTERCEPT_CARD':
        effects = [O('block', 'self', 'on_play', card.base_block or 0),
                   O('ally_guard', 'ally', 'incoming_powered_attack', 1, condition='ally_required')]
    elif name == 'LIFT':
        effects = [O('block', 'ally', 'on_play', card.base_block or 0, condition='ally_required')]
    elif name == 'MIMIC':
        effects = [O('replay_attack', 'ally', 'after_play_damage', 1, condition='ally_required')]
    elif name == 'HUDDLE_UP':
        effects = [O('draw', 'ally', 'on_play', v['cards'], condition='ally_present')]
    elif name == 'RALLY':
        effects = [O('block', 'ally', 'on_play', v['block'], condition='ally_present')]
    else:
        raise ValueError(f'Unimplemented batch-5 descriptor: {name}')
    for keyword in sorted(card.keywords):
        timing = {'exhaust': 'after_play', 'retain': 'turn_end_hand', 'innate': 'opening_hand',
                  'ethereal': 'turn_end_hand', 'unplayable': 'generated_card'}[keyword]
        effects.append(O(keyword, 'self', timing, 1))
    return MechanicDescriptor(card.card_type.value, card.cost, target,
                              tuple(e.validate() for e in effects))
