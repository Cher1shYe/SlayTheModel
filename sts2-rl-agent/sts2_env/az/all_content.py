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
    mask = (tuple(bool(v) for v in public_mask(world, ALL_CONTENT)) if reason is None
            else (False,) * action_size(EXPANSION_CONTENT))
    from .card_memory import capture as capture_card_memory
    from .foundation import PLAYER
    from .power_memory import capture as capture_power_memory
    from .foundation import capture as capture_basic
    from sts2_env.core.enums import PowerId
    # Player powers exposed by their own fields are excluded here to avoid
    # duplication: shrink/vulnerable/strength/retain and basic statuses.
    handled = (PowerId.SHRINK, PowerId.VULNERABLE, PowerId.STRENGTH, PowerId.RETAIN_HAND,
               *(PowerId[name] for name in PLAYER))
    first = enemies[0]
    shrink = player.powers[PowerId.SHRINK].amount if PowerId.SHRINK in player.powers else 0
    return InformationState(
        player.current_hp, player.max_hp, player.block, world.energy, world.max_energy,
        world.turn_count, hand, draw, discard, exhaust, shrink,
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
        player_abilities=tuple((p.name, obj.amount) for p, obj in player.powers.items()
                               if p not in handled),
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
    _validate_player_powers(info)
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
        alive = any(slot.hp > 0 and not slot.escaped and not slot.spawned and slot.primary for slot in info.enemies)
        if info.termination_reason == 'win' and (alive or info.player_hp <= 0):
            raise ValueError('Win requires the whole roster to be defeated')
        if info.termination_reason == 'death' and info.player_hp > 0:
            raise ValueError('Death requires player defeat')
    if type(info.legal_mask) is not tuple or len(info.legal_mask) != len(info.legal_mask) or not info.legal_mask:
        raise ValueError('Invalid public legal mask')
    if info.terminal_value() is None and not any(info.legal_mask):
        raise ValueError('Nonterminal state needs a legal action')
    return info


def _validate_player_powers(info):
    """Every visible player power must be exposed and ordered consistently."""
    from sts2_env.core.enums import PowerId

    from .foundation import PLAYER
    from .power_memory import read as read_power_memory

    abilities = info.player_abilities
    if (type(abilities) is not tuple
            or any(type(row) is not tuple or len(row) != 2 or row[0] not in PowerId.__members__
                   or type(row[1]) is not int or not -100000 <= row[1] <= 100000 for row in abilities)
            or len({name for name, _ in abilities}) != len(abilities)):
        raise ValueError('Invalid public player powers')
    memory = read_power_memory(info)
    # Zero Strength/Dexterity are hidden from the public power order, so they
    # must not be required back from it.
    basic = {name for slot, name, amount in info.basic_statuses
             if slot == -1 and not (name in ('STRENGTH', 'DEXTERITY') and amount == 0)}
    exposed = basic | {name for name, _ in abilities}
    if info.shrink:
        exposed.add('SHRINK')
    if info.player_vulnerable:
        exposed.add('VULNERABLE')
    if info.player_strength:
        exposed.add('STRENGTH')
    if info.retain_hand:
        exposed.add('RETAIN_HAND')
    if set(memory['order']) != exposed:
        raise ValueError('Public power order disagrees with the exposed powers')


def roster_rows(enemies):
    """Reward ledger rows: primaries are everything without a Minion power."""
    from .summon import ledger_from_slots, ledger_rows, primary_summary
    ledger = ledger_from_slots(enemies)
    return ledger, ledger_rows(ledger), primary_summary(ledger)


def terminal_value_all(info):
    if info.termination_reason is None:
        return None
    from .risk_reward import public_risk

    ledger, rows, (initial, final, maximum) = roster_rows(info.enemies)
    return terminal_reward(info.termination_reason, info.player_hp, info.initial_hp, final, maximum,
                           info.reward_version, enemy_initial_hp=initial, enemy_roster=rows,
                           player_max_hp=info.player_max_hp, incoming_risk=public_risk(info))


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
    history = finish_choices(before, world, history, action)
    history = finish_execution(view, world, history)
    from .monster_registry import move_from_intents
    moves = [list(slot.moves) for slot in before.enemies]
    moves.extend([] for _ in range(len(world.enemies) - len(moves)))
    recorded = None
    for event in events[len(before.history.public_events):]:
        if event[0] == 'enemy_intent_action':
            _, slot, monster_id, intents, _ = event
            if not 0 <= slot < len(moves) or world.enemies[slot].monster_id != monster_id:
                raise ValueError('Invalid performed enemy intent')
            previous = moves[slot][-1] if moves[slot] else None
            moves[slot].append(move_from_intents(monster_id, previous, intents))
            recorded = slot
        elif event[0] == 'enemy_action':
            slot = event[1]
            if recorded != slot:
                if not 0 <= slot < len(before.enemies):
                    raise ValueError('New enemy action requires its visible intent event')
                moves[slot].append(before.enemies[slot].move)
            recorded = None
    roster = tuple(tuple(m) for m in moves)
    return _replace(history, enemy_moves=roster[0], roster_moves=roster)


def roster_ledger(world, initial_hp):
    """Reward ledger straight from the finished world (no move validation)."""
    from .enemy_lifecycle import EnemyLife, EnemyLedger, ALL_CONTRACT_VERSION

    entries = []
    for slot, enemy in enumerate(world.enemies):
        powers = {p.name: obj.amount for p, obj in enemy.powers.items()}
        hp = max(0, enemy.current_hp)
        phase = 'removed' if enemy.escaped else ('alive' if hp > 0 else ('reviving' if (powers.get('ILLUSION', 0) > 0 or (powers.get('REATTACH', 0) > 0 and any(e.current_hp > 0 for e in world.enemies))) else 'defeated'))
        hp = 0 if enemy.escaped else hp
        entries.append(EnemyLife(slot, enemy.monster_id, 'MINION' not in powers,
                                 initial_hp[slot] if slot < len(initial_hp) else enemy.max_hp,
                                 enemy.max_hp, hp, phase, slot >= len(initial_hp)))
    ledger = EnemyLedger(tuple(entries), ALL_CONTRACT_VERSION)
    ledger.validate()
    return ledger


def create_enemies(world, info, rng):
    from .roster import create_slots
    return create_slots(world, info.enemies, rng, encounter=info.encounter or None)


def restore_enemies(world, info, rng):
    from .roster import restore_slots
    return restore_slots(world, info.enemies, rng)


def sample_particle(info, search_rng):
    """Build one causal hypothetical world from public state only."""
    from sts2_env.cards import base as card_base
    from sts2_env.core.combat import CombatState
    from sts2_env.core.enums import PowerId
    from sts2_env.core.rng import Rng

    from .card_memory import restore as restore_card_memory
    from .decks import make_token
    from .execution import restore as restore_execution
    from .foundation import restore as restore_foundation
    from .g1 import codec_for, restore_continuation
    from .information import InformationState, SearchParticle
    from .lifecycle import restore_token
    from .power_memory import restore as restore_power_memory

    if type(info) is not InformationState:
        raise TypeError('BeliefSampler accepts only InformationState, never WorldState/recipe')
    if info.content_version != ALL_CONTENT:
        raise ValueError('All-content sampler requires its version')
    info.validate()
    if info.terminal_value() is not None:
        raise ValueError('Cannot sample a terminal information state')
    saved_id = card_base._next_instance_id
    try:
        card_base._next_instance_id = 0
        rng = Rng(int(search_rng.integers(0, 2 ** 31)))
        world = CombatState(info.player_hp, info.player_max_hp, [], 0, relics=[], potions=[],
                            character_id='Ironclad')
        world._az_all_content = True
        create_enemies(world, info, rng)
        world.start_combat()
        world.rng = rng
        world.player.block = info.player_block
        world.energy = info.energy
        world.turn_count = world.round_number = info.turn
        state = world.current_player_state
        for attr, names in (('hand', info.hand), ('draw_pile', info.draw_composition),
                            ('discard_pile', info.discard), ('exhaust_pile', info.exhaust)):
            cards = [restore_token(name, info.history) for name in names]
            for card in cards:
                card.owner = world.player
            setattr(world, attr, cards)
        prefix, suffix = [], []
        for token in info.known_top:
            card = next(c for c in world.draw_pile if card_token_matches(c, token))
            world.draw_pile.remove(card)
            prefix.append(card)
        for token in info.known_bottom:
            card = next(c for c in world.draw_pile if card_token_matches(c, token))
            world.draw_pile.remove(card)
            suffix.append(card)
        rng.shuffle(world.draw_pile)
        world.draw_pile = prefix + world.draw_pile + suffix
        CODEC, _ = _codes()
        restore_card_memory(world, info, CODEC)
        from .all_cards import RETURNING
        for token in set(info.history.played_this_turn):
            remaining = info.history.played_this_turn.count(token)
            if token.removesuffix('+') not in RETURNING or not remaining:
                continue
            for card in reversed(list(world.discard_pile)):
                if remaining <= 0:
                    break
                if _token(card) == token:
                    card.combat_vars['_return_before_hand_draw_round'] = info.turn + 1
                    remaining -= 1
            for card in list(world.hand):
                if remaining <= 0:
                    break
                if _token(card) == token:
                    card.combat_vars['_return_before_hand_draw_round'] = info.turn + 1
                    remaining -= 1
        world._played_cards_combat = [_play_token(e[1]) for e in info.history.public_events
                                      if e[0] == 'start']
        for card in world._played_cards_combat:
            card.owner = world.player
        all_cards = world.hand + world.draw_pile + world.discard_pile + world.exhaust_pile
        state.starting_deck = list(all_cards)
        state.player_state.deck = list(all_cards)
        world._energy_spent_this_turn[world.player] = sum(p.energy for p in info.history.payments)
        if info.retain_hand:
            world.apply_power_to(world.player, PowerId.RETAIN_HAND, info.retain_hand, applier=world.player)
        if info.shrink:
            world.apply_power_to(world.player, PowerId.SHRINK, info.shrink, applier=world.enemies[0])
        if info.player_vulnerable:
            world.apply_power_to(world.player, PowerId.VULNERABLE, info.player_vulnerable, applier=world.enemies[0])
            world.player.powers[PowerId.VULNERABLE].skip_next_tick = False
        if info.player_strength:
            world.apply_power_to(world.player, PowerId.STRENGTH, info.player_strength, applier=world.player)
        if info.history.exhausted_this_turn:
            # This is an event history, not a selection from the current pile.
            # Dampen removal can upgrade a card after it was exhausted. As with
            # played-card history above, reconstruct detached event snapshots.
            # The engine's reader only tests whether an event belongs to owner.
            for token in info.history.exhausted_this_turn:
                card = _play_token(token)
                card.owner = world.player
                world._exhaust_events_this_turn.append(card)
        if info.player_abilities:
            from sts2_env.core.enums import PowerId as _PowerId
            for name, amount in info.player_abilities:
                if name == 'DAMPEN':
                    # The card faces already contain Dampen's historical effect.
                    # Applying it again would downgrade later Aggression upgrades.
                    from sts2_env.core.creature import get_power_class
                    world.player.powers[_PowerId[name]] = get_power_class(_PowerId[name])(amount)
                else:
                    world.apply_power_to(world.player, _PowerId[name], amount, applier=world.player)
                # A visible player power is observed at a player decision, so the
                # enemy turn that applied it has already ended and its first
                # duration tick has been consumed.
                world.player.powers[_PowerId[name]].skip_next_tick = False
        available = list(world.discard_pile)
        for name in (info.history.played_this_turn[:-1] if info.choice else info.history.played_this_turn):
            card = _play_token(name)
            card.owner = world.player
            world._played_cards_this_turn.append(card)
        CODEC_CARDS = codec_for(EXPANSION_CONTENT)
        world.hand = [CODEC_CARDS.restore(c) for c in info.hand_states]
        for card in world.hand:
            card.owner = world.player
        restore_continuation(world, card_view(info))
        all_cards = world.hand + world.draw_pile + world.discard_pile + world.exhaust_pile + world.play_pile
        state.starting_deck = list(all_cards)
        state.player_state.deck = list(all_cards)
        restore_enemies(world, info, rng)
        restore_foundation(world, info)
        restore_execution(world, info, CODEC)
        restore_power_memory(world, info)
        projected = observe_all(world, info.history, info.limits, info.initial_hp,
                                info.reward_version, ALL_CONTENT, info.known_deck,
                                tuple(slot.initial_hp for slot in info.enemies if not slot.spawned),
                                info.encounter)
        if projected != info:
            fields = [name for name in projected.__dataclass_fields__
                      if getattr(projected, name) != getattr(info, name)]
            detail = ''
            if 'enemies' in fields:
                detail = '; ' + ', '.join(
                    f'slot {a.slot}: hp {a.hp}/{b.hp} init {a.initial_hp}/{b.initial_hp} '
                    f'max {a.max_hp}/{b.max_hp} block {a.block}/{b.block} '
                    f'spawned={a.spawned}/{b.spawned} powers={a.powers}/{b.powers} '
                    f'power_state={a.power_state == b.power_state} '
                    f'intents={a.intents == b.intents} moves={a.moves == b.moves} '
                    f'move={a.move}/{b.move} escaped={a.escaped}/{b.escaped}'
                    for a, b in zip(projected.enemies, info.enemies) if a != b)
            if 'basic_statuses' in fields:
                detail += (f'; basic {projected.basic_statuses}/{info.basic_statuses}')
            if 'player_abilities' in fields:
                detail += f'; abilities {projected.player_abilities}/{info.player_abilities}'
            raise ValueError('Particle does not reproduce the root public state/legal actions: '
                             f'{fields}{detail}')
        return SearchParticle(world, projected, card_base._next_instance_id)
    finally:
        card_base._next_instance_id = saved_id


def _token(card):
    from .decks import card_token
    return card_token(card)


def _play_token(token):
    """Card factory for played-card memory, including inherited status tokens."""
    if token in ('DAZED', 'BURN', 'WOUND', 'SLIMED', 'TOXIC', 'INFECTION', 'BECKON', 'FRANTIC_ESCAPE'):
        from sts2_env.cards import status
        return getattr(status, 'make_' + token.lower())()
    from .decks import make_token
    return make_token(token)


def card_token_matches(card, token):
    return _token(card) == token

