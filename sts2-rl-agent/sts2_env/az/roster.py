"""Generic public roster for all act combat encounters.

The observer only keeps facts a player can see: creature identity, health,
block, visible powers, the displayed intent list, the completed move history
and the derived current move.  The current move is *derived* from the intent
and history through the audited public script; the native private state id is
read once, only to verify that the derivation agrees, and is never stored.

Particles rebuild each creature with the construction variant that contains the
observed moves, then restore the public bookkeeping.  A creature whose move is
not publicly determined is refused instead of guessed.
"""
from __future__ import annotations

from dataclasses import dataclass

from sts2_env.core.enums import IntentType, PowerId
from sts2_env.core.rng import Rng

from .monster_registry import (CREATORS, ENCOUNTERS, info_for, move_from_intents,
                               variants_for)

MAX_SLOTS = 5
INTENT_NAMES = tuple(name for name in IntentType.__members__)
MAX_POWERS = 64


@dataclass(frozen=True)
class EnemySlot:
    slot: int
    monster_id: str
    initial_hp: int
    hp: int
    max_hp: int
    block: int
    powers: tuple
    intents: tuple
    move: str
    moves: tuple
    escaped: bool
    spawned: bool = False

    # Read-only compatibility surface for shared public helpers that were written
    # against the older single-intent slot shape.  Values still come only from
    # the public power list / intent list.
    def _amount(self, name):
        return dict(self.powers).get(name, 0)

    @property
    def strength(self):
        return self._amount('STRENGTH')

    @property
    def vulnerable(self):
        return self._amount('VULNERABLE')

    @property
    def slow(self):
        return self._amount('SLOW')

    @property
    def territorial(self):
        return self._amount('TERRITORIAL')

    @property
    def artifact(self):
        return self._amount('ARTIFACT')

    @property
    def illusion(self):
        return self._amount('ILLUSION')

    @property
    def minion(self):
        return self._amount('MINION')

    @property
    def primary(self):
        return self.minion == 0

    @property
    def reviving(self):
        return self.hp == 0 and self.illusion > 0

    @property
    def intent(self):
        return self.intents[0] if self.intents else ('ATTACK', 0, 1)


def intent_signal(ai):
    return tuple((i.intent_type.name, int(i.damage), int(i.hits)) for i in ai.current_move.intents)


def _legal_transition(monster_id, previous, current):
    if previous is None:
        return current in info_for(monster_id).initial_moves
    successors = dict(info_for(monster_id).successors)
    return previous in successors and current in successors[previous]


def capture_slots(world, history, initial_hp):
    """Project the real roster; verifies that every move is publicly derivable."""
    if not 1 <= len(world.enemies) <= MAX_SLOTS:
        raise ValueError('Roster size outside the admitted engine capacity')
    if initial_hp is None:
        # First observation: the visible starting HP is the current HP.
        initial_hp = tuple(max(0, enemy.current_hp) for enemy in world.enemies)
    if type(initial_hp) is not tuple or len(initial_hp) > len(world.enemies):
        raise ValueError('Initial HP for every slot required')
    initial_count = len(initial_hp)
    if initial_count < len(world.enemies):
        # A summoned slot appeared after the initial roster: its obligation
        # starts at its visible spawn HP and the roster stays append-only.
        initial_hp = initial_hp + tuple(max(0, enemy.current_hp)
                                        for enemy in world.enemies[initial_count:])
    histories = history.roster_moves
    if len(histories) > len(world.enemies):
        raise ValueError('Public roster history exceeds the roster size')
    histories = histories + ((),) * (len(world.enemies) - len(histories))
    if len(histories) != len(world.enemies):
        raise ValueError('Public roster history does not match the roster size')
    slots = []
    for slot, (enemy, hp, past) in enumerate(zip(world.enemies, initial_hp, histories)):
        ai = world.enemy_ais[enemy.combat_id]
        intents = intent_signal(ai)
        previous = past[-1] if past else None
        move = move_from_intents(enemy.monster_id, previous, intents)
        if move != ai._current_state_id:
            raise ValueError(f'Private move disagrees with the public script: {enemy.monster_id}')
        for before, after in zip(past, past[1:]):
            if not _legal_transition(enemy.monster_id, before, after):
                raise ValueError(f'Illegal public transition: {enemy.monster_id}')
        powers = tuple(sorted((p.name, int(obj.amount)) for p, obj in enemy.powers.items()))
        slots.append(EnemySlot(slot, enemy.monster_id, int(hp), max(0, int(enemy.current_hp)),
                               int(enemy.max_hp), int(enemy.block), powers, intents, move,
                               tuple(past), bool(enemy.escaped), slot >= initial_count))
    return tuple(slots)


def validate_slots(slots):
    if not isinstance(slots, tuple) or not 1 <= len(slots) <= MAX_SLOTS:
        raise ValueError('Explicit public roster required')
    first_spawn = next((slot.slot for slot in slots if slot.spawned), len(slots))
    if any(not slot.spawned for slot in slots[first_spawn:]):
        raise ValueError('Summoned slots must be an append-only suffix')
    for index, slot in enumerate(slots):
        if type(slot) is not EnemySlot or slot.slot != index:
            raise ValueError('Public roster slots must be ordered and immutable')
        info = info_for(slot.monster_id)
        if info.ambiguous_pairs:
            raise ValueError(f'Monster move is not publicly determined: {slot.monster_id}')
        if (any(type(n) is not int for n in (slot.initial_hp, slot.hp, slot.max_hp, slot.block))
                or not 0 < slot.initial_hp <= slot.max_hp <= 100000
                or not 0 <= slot.hp <= slot.max_hp or slot.block < 0):
            raise ValueError('Invalid public roster health')
        if type(slot.escaped) is not bool:
            raise ValueError('Invalid public escape flag')
        if (type(slot.powers) is not tuple or len(slot.powers) > MAX_POWERS
                or any(type(p) is not tuple or len(p) != 2 or type(p[0]) is not str
                       or p[0] not in PowerId.__members__ or type(p[1]) is not int
                       or not -100000 <= p[1] <= 100000 for p in slot.powers)
                or len(dict(slot.powers)) != len(slot.powers)):
            raise ValueError('Invalid public power list')
        if (type(slot.intents) is not tuple or not 1 <= len(slot.intents) <= 8
                or any(type(i) is not tuple or len(i) != 3 or i[0] not in INTENT_NAMES
                       or type(i[1]) is not int or type(i[2]) is not int
                       or not 0 <= i[1] <= 10000 or not 0 <= i[2] <= 100 for i in slot.intents)):
            raise ValueError('Invalid public intent list')
        if type(slot.moves) is not tuple or len(slot.moves) > 200:
            raise ValueError('Invalid public move history')
        signatures = dict(info.intent_signatures)
        if signatures.get(slot.move) != slot.intents:
            raise ValueError('Intent does not match the public move')
        for before, after in zip(slot.moves, slot.moves[1:]):
            if not _legal_transition(slot.monster_id, before, after):
                raise ValueError('Public move history violates the script')
        previous = slot.moves[-1] if slot.moves else None
        if slot.moves:
            if not _legal_transition(slot.monster_id, previous, slot.move):
                raise ValueError('Current move is not reachable from the public history')
        elif slot.move not in info.initial_moves:
            raise ValueError('Current move cannot be the initial move')
        if slot.hp == 0 and slot.monster_id == 'TEST_SUBJECT':
            raise ValueError('Boss phase forms require the dedicated contract')
    return slots


def _variant_for(monster_id, required_moves):
    required = set(required_moves)
    for creator_name, kwargs, moves, _ in variants_for(monster_id):
        if required <= set(moves):
            return CREATORS[creator_name], kwargs
    raise ValueError(f'No public construction variant explains {monster_id} moves: {sorted(required)}')


def create_slots(world, slots, rng, encounter=None):
    """Create every observed creature; identity and HP are restored afterwards.

    With a public encounter id the native encounter setup is used as the
    construction oracle (it supplies per-slot consumer arguments such as
    Exoskeleton's position).  The setup is sampled until it reproduces the
    observed leading roster; any remaining slot (a later summon) is built from
    the per-monster variants instead.
    """
    from sts2_env.core.combat import CombatState

    validate_slots(slots)
    observed = tuple(slot.monster_id for slot in slots)
    built = {}
    if encounter is not None:
        for _ in range(64):
            seed = int(rng.next_int(0, 2**31 - 1))
            scratch = CombatState(80, 80, [], seed, relics=[], potions=[], character_id='Ironclad')
            try:
                ENCOUNTERS[encounter](scratch, Rng(seed))
                scratch.start_combat()
            except Exception:  # noqa: BLE001 - resample another public setup draw
                continue
            names = tuple(enemy.monster_id for enemy in scratch.enemies)
            if names and names == observed[:len(names)]:
                for slot, enemy in enumerate(scratch.enemies):
                    built[slot] = (enemy, scratch.enemy_ais[enemy.combat_id])
                break
    for slot in slots:
        if slot.slot in built:
            enemy, ai = built[slot.slot]
        else:
            creator, kwargs = _variant_for(slot.monster_id, (*slot.moves, slot.move))
            enemy, ai = creator(Rng(int(rng.next_int(0, 2**31 - 1))), **kwargs)
        if enemy.monster_id != slot.monster_id:
            raise ValueError('Construction variant produced another monster')
        world.add_enemy(enemy, ai)
    return world


def restore_slots(world, slots, rng):
    """Restore public bookkeeping, including the current move and its history."""
    from sts2_env.core.creature import get_power_class

    validate_slots(slots)
    if len(world.enemies) != len(slots):
        raise ValueError('Particle roster size mismatch')
    for enemy, slot in zip(world.enemies, slots):
        ai = world.enemy_ais[enemy.combat_id]
        if enemy.monster_id != slot.monster_id:
            raise ValueError('Particle roster identity mismatch')
        enemy.current_hp, enemy.max_hp, enemy.block = slot.hp, slot.max_hp, slot.block
        enemy.powers.clear()
        enemy.escaped = slot.escaped
        enemy._death_processed = slot.hp == 0
        ai.state_log = list(slot.moves)
        ai._current_state_id = slot.move
        ai._performed_first_move = bool(slot.moves)
        state = ai.states.get(slot.move)
        if state is not None and getattr(state, 'must_perform_once', False):
            state._performed_at_least_once = slot.move in slot.moves
        for name, amount in slot.powers:
            power = get_power_class(PowerId[name])(amount)
            power.applier = world.player if name in ('VULNERABLE', 'KNOCKDOWN', 'GRAPPLE') else enemy
            if name == 'KNOCKDOWN':
                power._instances = [(amount, world.player)]
            if name == 'SLOW':
                power._slow_amount = len(world._played_cards_this_turn)
            # Enemy-side statuses were applied during the player turn, so their
            # first enemy-turn tick is due; only player-side debuffs skip it.
            power.skip_next_tick = False
            enemy.powers[PowerId[name]] = power
    return world


def after_round(before, ended):
    """Append exactly the moves the enemy round performed, per public slot.

    A dead or escaped slot takes no turn, so it must not gain a public move.
    """
    return tuple(slot.moves + ((slot.move,) if slot.hp > 0 and not ended and not slot.escaped else ())
                 for slot in before)
