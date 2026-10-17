"""All-encounter content version: same card contract, generic public roster.

The card half of the contract is identical to V4 (``ironclad-colorless-foundation-v4``),
so the audited card codecs are reused.  Only the enemy half changes: instead of
the ten hand-audited profiles, every act1-act4 encounter uses ``roster``, whose
slots are reconstructed from the visible intent and public move history.

Nothing here reads a hidden state-machine field as data: ``roster.capture_slots``
derives the current move publicly and only asserts it equals the native state id.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

from .config import EpisodeLimits
from .content import ALL_CONTENT, ALL_INFORMATION, EXPANSION_CONTENT
from .information import InformationState, PublicHistory, observe
from .rewards import V7, terminal_reward

CARD_VIEW = 'ironclad-colorless-information-v5'


def card_view(info):
    """View the same state through the audited V4 card contract."""
    return replace(info, content_version=EXPANSION_CONTENT, information_version=CARD_VIEW)


def _codes():
    from .content_expansion import CODEC
    from .g1 import codec_for
    return CODEC, codec_for(EXPANSION_CONTENT)


def observe_all(world, history, limits=None, initial_hp=80, reward_version=V7,
                content_version=ALL_CONTENT, known_deck=(), enemy_initial_hp=None,
                encounter=''):
    """Project the public state of any act encounter plus the shared card state."""
    from sts2_env.core.enums import CombatSide

    from .execution import capture as capture_execution, inventory as event_inventory, states
    from .g1 import observe_choice
    from .roster import capture_slots

    if type(history) is not PublicHistory:
        raise TypeError('Explicit public history is required')
    limits = limits or EpisodeLimits()
    if (world.relics or any(p is not None for p in world.potions) or world.is_multiplayer
            or world.ascension_level != 0 or not world.enemies
            or (world.play_pile and not world.is_over and world.pending_choice is None)):
        raise ValueError('Unsupported observable scope')
    if not world.is_over and world.current_side != CombatSide.PLAYER:
        raise ValueError('Not a public player decision')
    CODEC, _ = _codes()

    def cards(pile):
        from .deck_observation import validate_card
        from .lifecycle import validate_state
        from .decks import card_token
        out = []
        for card in pile:
            validate_card(card, EXPANSION_CONTENT)
            validate_state(CODEC.capture(card), history)
            out.append(card_token(card))
        return tuple(out)

    hand = cards(world.hand)
    hand_states = tuple(CODEC.capture(c) for c in world.hand)
    pending_card, choice = observe_choice(world, EXPANSION_CONTENT)
    discard = cards(world.discard_pile)
    exhaust = tuple(sorted(cards(world.exhaust_pile)))
    execution = capture_execution(world, CODEC)
    remaining = event_inventory(known_deck, history.public_events, CODEC)
    pending_tokens = (pending_card.token,) if pending_card else ()
    if execution:
        pending_tokens = tuple(c.token for c in states(execution, CODEC)[1])
    remaining.subtract(pending_tokens + hand + discard + exhaust + history.removed_powers)
    if any(n < 0 for n in remaining.values()):
        raise ValueError('Visible cards exceed known deck')
    draw = tuple(sorted(remaining.elements()))
    enemies = capture_slots(world, history, enemy_initial_hp)
    enemy_initial_hp = enemies[0].initial_hp
    player = world.player
    reason = ('win' if world.player_won else 'death') if world.is_over else None
    if reason is None and (history.decisions >= limits.max_decisions or world.turn_count > limits.max_turns):
        reason = 'time_limit'
    from .actions import action_size, public_mask
    mask = (tuple(bool(v) for v in public_mask(world, EXPANSION_CONTENT)) if reason is None
            else (False,) * action_size(EXPANSION_CONTENT))
    from .card_memory import capture as capture_card_memory
    from .player_abilities import POWER_IDS
    from .power_memory import capture as capture_power_memory
    from .foundation import capture as capture_basic
    from sts2_env.core.enums import PowerId
    first = enemies[0]
    return InformationState(
        player.current_hp, player.max_hp, player.block, world.energy, world.max_energy,
        world.turn_count, hand, draw, discard, exhaust, 0,
        first.hp, first.max_hp, first.block, dict(first.powers).get('VULNERABLE', 0),
        first.intents[0] if first.intents else ('ATTACK', 0, 1), history, mask, limits, reason,
        enemies=enemies, boss=None, execution=execution,
        power_memory=capture_power_memory(world), card_memory=capture_card_memory(world, history, known_deck, CODEC, execution),
        basic_statuses=capture_basic(world), retain_hand=player.powers[PowerId.RETAIN_HAND].amount
        if PowerId.RETAIN_HAND in player.powers else 0,
        known_top=history.known_top, known_bottom=history.known_bottom, hand_states=hand_states,
        pending_card=pending_card, choice=choice, initial_hp=initial_hp, reward_version=reward_version,
        content_version=content_version, information_version=ALL_INFORMATION,
        monster_id=first.monster_id, enemy_strength=dict(first.powers).get('STRENGTH', 0),
        known_deck=known_deck, enemy_initial_hp=enemy_initial_hp,
        enemy_slow=dict(first.powers).get('SLOW', 0), enemy_territorial=dict(first.powers).get('TERRITORIAL', 0),
        enemy_artifact=dict(first.powers).get('ARTIFACT', 0),
        player_vulnerable=player.powers[PowerId.VULNERABLE].amount if PowerId.VULNERABLE in player.powers else 0,
        player_abilities=tuple((p.name, obj.amount) for p, obj in player.powers.items() if p in POWER_IDS.values()),
        player_strength=player.powers[PowerId.STRENGTH].amount if PowerId.STRENGTH in player.powers else 0,
        encounter=encounter,
    ).validate()


def validate_all(info):
    """Focused public validator for the all-encounter contract."""
    from .card_memory import validate as validate_card_memory
    from .execution import validate as validate_execution
    from .foundation import validate as validate_basic
    from .player_abilities import validate as validate_abilities
    from .power_memory import read as read_power_memory
    from .roster import validate_slots

    view = card_view(info)
    if (info.content_version != ALL_CONTENT or info.information_version != ALL_INFORMATION
            or info.reward_version != V7 or type(info.encounter) is not str or not info.encounter):
        raise ValueError('Unsupported all-content version/encounter')
    if type(info.enemies) is not tuple:
        raise ValueError('Explicit public roster required')
    validate_slots(info.enemies)
    first = info.enemies[0]
    if (info.monster_id != first.monster_id or info.enemy_hp != first.hp
            or info.enemy_max_hp != first.max_hp or info.enemy_block != first.block
            or info.enemy_initial_hp != first.initial_hp or info.intent != first.intents[0]
            or info.enemy_strength != dict(first.powers).get('STRENGTH', 0)
            or info.vulnerable != dict(first.powers).get('VULNERABLE', 0)):
        raise ValueError('First-slot projection disagrees with the roster: '
                         f'{info.monster_id}/{first.monster_id} '
                         f'{info.enemy_hp}/{first.hp} {info.enemy_max_hp}/{first.max_hp} '
                         f'block {info.enemy_block}/{first.block} '
                         f'initial {info.enemy_initial_hp}/{first.initial_hp} '
                         f'intent {info.intent}/{first.intents[0]} '
                         f'str {info.enemy_strength}/{dict(first.powers).get("STRENGTH", 0)}')
    if info.boss is not None:
        raise ValueError('All-content roster must not carry boss phases')
    if type(info.enemies) is not tuple or len({slot.slot for slot in info.enemies}) != len(info.enemies):
        raise ValueError('Duplicate roster slots')
    validate_abilities(view)
    validate_basic(view)
    read_power_memory(view)
    validate_card_memory(view, _codes()[0])
    validate_execution(view, _codes()[0])
    if info.termination_reason is None:
        if info.player_hp <= 0 or not any(slot.hp > 0 for slot in info.enemies):
            raise ValueError('Missing terminal outcome')
        if info.history.decisions >= info.limits.max_decisions or info.turn > info.limits.max_turns:
            raise ValueError('Missing timeout')
    else:
        alive = any(slot.hp > 0 for slot in info.enemies)
        if info.termination_reason == 'win' and (alive or info.player_hp <= 0):
            raise ValueError('Win requires the whole roster to be defeated')
        if info.termination_reason == 'death' and info.player_hp > 0:
            raise ValueError('Death requires player defeat')
    if type(info.legal_mask) is not tuple or len(info.legal_mask) != len(info.legal_mask) or not info.legal_mask:
        raise ValueError('Invalid public legal mask')
    if info.terminal_value() is None and not any(info.legal_mask):
        raise ValueError('Nonterminal state needs a legal action')
    return info


def roster_rows(enemies):
    """Reward ledger rows: primaries are everything without a Minion power."""
    from .enemy_lifecycle import EnemyLife, EnemyLedger

    entries = []
    for slot in enemies:
        powers = dict(slot.powers)
        primary = 'MINION' not in powers
        phase = 'alive' if slot.hp > 0 else ('reviving' if 'ILLUSION' in powers else 'defeated')
        entries.append(EnemyLife(slot.slot, slot.monster_id, primary, slot.initial_hp,
                                 slot.max_hp, slot.hp, phase, False))
    ledger = EnemyLedger(tuple(entries))
    ledger.validate()
    from .summon import ledger_rows, primary_summary
    return ledger, ledger_rows(ledger), primary_summary(ledger)


def terminal_value_all(info):
    if info.termination_reason is None:
        return None
    ledger, rows, (initial, final, maximum) = roster_rows(info.enemies)
    return terminal_reward(info.termination_reason, info.player_hp, info.initial_hp, final, maximum,
                           info.reward_version, enemy_initial_hp=initial, enemy_roster=rows,
                           player_max_hp=info.player_max_hp)


def check_transition(before, world, slots):
    """Roster identity is append-only: no reorder/removal/replacement."""
    current = tuple(world.enemies)
    if len(current) < len(slots) or current[:len(slots)] != slots:
        raise ValueError('Roster was removed, reordered or replaced')


def finish_history(before, world, history, action):
    """Merge the visible engine journal and append exactly the performed moves.

    Card-side bookkeeping is identical to V4, so it runs against a card-contract
    view.  Enemy moves are appended from the observed ``enemy_action`` events and
    the move that was public before the round; no private AI cursor is read.
    """
    from dataclasses import replace as _replace
    from .execution import finish_history as finish_execution
    from .extended_choices import finish_history as finish_choices
    from .simple_cards import finish_history as finish_simple

    view = _replace(before, content_version=EXPANSION_CONTENT, information_version=CARD_VIEW)
    events = tuple(world.visible_card_events)
    if events[:len(before.history.public_events)] != before.history.public_events:
        raise ValueError('Public event journal prefix changed')
    history = finish_simple(view, world, history)
    history = finish_choices(view, world, history, action)
    history = finish_execution(view, world, history)
    moves = [list(slot.moves) for slot in before.enemies]
    for event in events[len(before.history.public_events):]:
        if event[0] == 'enemy_action':
            slot = event[1]
            if not 0 <= slot < len(before.enemies):
                raise ValueError('Unobserved enemy acted')
            moves[slot].append(before.enemies[slot].move)
    roster = tuple(tuple(m) for m in moves)
    return _replace(history, enemy_moves=roster[0], roster_moves=roster)


def create_enemies(world, info, rng):
    from .roster import create_slots
    return create_slots(world, info.enemies, rng, encounter=info.encounter or None)


def restore_enemies(world, info, rng):
    from .roster import restore_slots
    return restore_slots(world, info.enemies, rng)
