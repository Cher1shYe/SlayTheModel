"""Native combat-monster inventory for the AZ public-state layer.

This module only reads *static* game data: which encounters exist in the native
rom, which creature factories build each monster, and the public shape of each
monster's move graph (visible intents and legal transition edges).  It never
runs a mission or reads a world.

Two publicness criteria are reported per monster:

* ``deterministic_script`` 鈥?every transition out of a MoveState is a single
  explicit follow-up, so the move history is enough to know the state.
* ``intent_unique`` 鈥?every move in the graph has a distinct visible-intent
  signature, so the current move can be read from the displayed intent.

A monster is admitted by the generic roster layer only when both hold; other
monsters stay explicitly unsupported instead of guessing hidden AI state.
"""
from __future__ import annotations

from dataclasses import dataclass

from sts2_env.core.rng import Rng
from sts2_env.monsters.state_machine import (ConditionalBranchState, MonsterAI,
                                             MoveState, RandomBranchState)


def _intent_signature(state):
    return tuple((i.intent_type.name, i.damage, i.hits) for i in state.intents)


@dataclass(frozen=True)
class MonsterInfo:
    monster_id: str
    creator: str
    moves: tuple[str, ...]
    intent_signatures: tuple[tuple[str, tuple], ...]
    initial_moves: tuple[str, ...]
    successors: tuple[tuple[str, tuple[str, ...]], ...]
    ambiguous_pairs: tuple[tuple[str, str, str], ...]
    multi_intent_moves: tuple[str, ...]
    branch_states: tuple[str, ...]

    @property
    def admitted(self):
        return bool(self.moves) and not self.ambiguous_pairs and bool(self.initial_moves)


def _resolve_branches(ai, state_id, seen=None):
    """All MoveState ids reachable from state_id through branch states."""
    seen = seen or set()
    if state_id in seen:
        return ()
    seen.add(state_id)
    state = ai.states.get(state_id)
    if state is None:
        return ()
    if isinstance(state, MoveState):
        return (state_id,)
    targets = ()
    if isinstance(state, RandomBranchState):
        targets = tuple(b.state_id for b in state.branches)
    elif isinstance(state, ConditionalBranchState):
        targets = tuple(target for _, target in state.branches)
    result = ()
    for target in targets:
        result += _resolve_branches(ai, target, seen)
    return tuple(dict.fromkeys(result))


def _graph(ai):
    """Public move graph: initial moves, successors and intent ambiguity.

    Only each state's own successors matter: the player sees the current intent
    and (from the previous move) which states are eligible.  Two eligible
    successors that display the same intent make the current move unknowable
    and the monster is refused instead of guessed.
    """
    states = ai.states
    moves = {sid: s for sid, s in states.items() if isinstance(s, MoveState)}
    branch_states = tuple(sid for sid, s in states.items()
                          if isinstance(s, (RandomBranchState, ConditionalBranchState)))
    initial = _resolve_branches(ai, ai._current_state_id if ai._current_state_id in states
                                else next(iter(states)))
    successors = {}
    ambiguous = []
    for state_id, state in moves.items():
        follow = state.follow_up_id
        targets = _resolve_branches(ai, follow) if follow in states else ()
        successors[state_id] = tuple(targets)
        signatures = {}
        for target in targets:
            signatures.setdefault(_intent_signature(moves[target]), []).append(target)
        for ids in signatures.values():
            if len(ids) > 1:
                ambiguous.append((state_id, ids[0], ids[1]))
    # Initial ambiguity: two reachable first moves showing the same intent.
    first = {}
    for move_id in initial:
        first.setdefault(_intent_signature(moves[move_id]), []).append(move_id)
    for ids in first.values():
        if len(ids) > 1:
            ambiguous.append(('initial', ids[0], ids[1]))
    return moves, branch_states, tuple(initial), successors, tuple(ambiguous)


def describe_monster(monster_id, creator, samples=64, **kwargs):
    """Describe one monster's public move graph, including initial ambiguity.

    The first move is chosen by the native AI at construction; whether the
    player can tell which move it is from the visible intent is audited by
    sampling constructions, never by reading a future transition.
    """
    enemy, ai = creator(Rng(0), **kwargs)
    moves, branches, initial, successors, ambiguous = _graph(ai)
    ordered = tuple(moves)
    by_intent = {}
    observed_initial = []
    for seed in range(samples):
        _, sample_ai = creator(Rng(seed), **kwargs)
        move_id = sample_ai._current_state_id
        if move_id not in moves:
            continue
        observed_initial.append(move_id)
        by_intent.setdefault(_intent_signature(moves[move_id]), set()).add(move_id)
    initial_ambiguous = tuple((sig[0][0], sorted(ids)[0], sorted(ids)[1])
                              for sig, ids in by_intent.items() if len(ids) > 1)
    return MonsterInfo(
        monster_id=monster_id,
        creator=getattr(creator, '__name__', repr(creator)),
        moves=ordered,
        intent_signatures=tuple((m, _intent_signature(moves[m])) for m in ordered),
        initial_moves=tuple(dict.fromkeys(observed_initial)) or initial,
        successors=tuple((m, successors[m]) for m in ordered),
        ambiguous_pairs=tuple(ambiguous) + tuple(initial_ambiguous),
        multi_intent_moves=tuple(m for m in ordered if len(moves[m].intents) != 1),
        branch_states=branches,
    )


# Factory table.  Some creators need construction keywords that the native
# encounters always pass (e.g. Nibbit's alone/front flags); they are recorded
# here as the audit-visible default.
def _creators():
    from sts2_env.monsters import act1, act1_weak, act2, act3, act4, shared

    table = {}
    # ``shared`` supplies a few creatures that real act encounters compose in
    # (e.g. the Queen's TorchHeadAmalgam); event-only shared monsters simply
    # never appear in the act encounter table.
    for module in (act1_weak, act1, act2, act3, act4, shared):
        for name in dir(module):
            if not name.startswith('create_'):
                continue
            creator = getattr(module, name)
            if callable(creator):
                table[name] = creator
    return table


CREATORS = _creators()


def _creator_variants():
    """Every construction variant of every monster, with boolean keyword combos.

    Encounters pass flags such as Nibbit's ``is_alone``/``is_front``; the public
    state only keeps the resulting creature and its move graph.  The variant is
    therefore re-derived by matching the observed move ids against the graphs
    each construction produces.
    """
    import inspect
    import itertools

    variants = {}
    for creator_name, creator in CREATORS.items():
        params = inspect.signature(creator).parameters
        if any(p.kind is inspect.Parameter.POSITIONAL_ONLY for p in params.values()):
            continue
        flags = []
        for name, spec in params.items():
            if name in ('rng', 'ascension_level'):
                continue
            if spec.default in (True, False):
                flags.append((name, (False, True)))
            elif type(spec.default) is int and 0 <= spec.default <= 3:
                # Positional-family arguments such as Exoskeleton's ``slot``.
                flags.append((name, (0, 1, 2, 3)))
        combos = 1
        for _, values in flags:
            combos *= len(values)
        if combos > 64:
            continue
        for values in itertools.product(*(values for _, values in flags)):
            kwargs = dict(zip((name for name, _ in flags), values))
            try:
                enemy, ai = creator(Rng(0), **kwargs)
            except Exception:  # noqa: BLE001 - variant simply does not build
                continue
            moves = tuple(sid for sid, state in ai.states.items() if isinstance(state, MoveState))
            if not moves:
                continue
            key = enemy.monster_id
            entry = (creator_name, kwargs, moves, ai._current_state_id)
            variants.setdefault(key, {})
            if (moves, ai._current_state_id) not in variants[key]:
                variants[key][(moves, ai._current_state_id)] = entry
    return {name: tuple(entries.values()) for name, entries in variants.items()}


CREATOR_VARIANTS = _creator_variants()

INFO = {}


def variants_for(monster_id):
    return CREATOR_VARIANTS.get(monster_id, ())


def info_for(monster_id):
    """Cached public move graph for one monster id (union of its variants)."""
    if monster_id not in INFO:
        variants = variants_for(monster_id)
        if not variants:
            raise ValueError(f'Unknown monster: {monster_id}')
        import dataclasses
        info = describe_monster(monster_id, CREATORS[variants[0][0]], **variants[0][1])
        initials = tuple(dict.fromkeys(
            tuple(entry[3] for entry in variants)
            + tuple(ENCOUNTER_INITIAL_MOVES.get(monster_id, ()))
            + info.initial_moves))
        signatures = dict(info.intent_signatures)
        groups = {}
        for move in initials:
            groups.setdefault(signatures.get(move), []).append(move)
        extra = tuple((sig[0][0] if sig else 'unknown', ids[0], ids[1])
                      for sig, ids in groups.items() if len(ids) > 1)
        INFO[monster_id] = dataclasses.replace(info, initial_moves=initials,
                                               ambiguous_pairs=info.ambiguous_pairs + extra)
    return INFO[monster_id]


def move_from_intents(monster_id, previous_move, intents):
    """Which move a visible intent refers to, from the public move history.

    ``previous_move`` is None for the initial state.  The caller has already
    checked that the intent is unambiguous; a missing match raises.
    """
    if tuple(intents) == (('STUNNED', 0, 1),):
        return 'STUNNED'
    if tuple(intents) == (('HEAL', 0, 1),):
        # Illusion minions install a public revive move (heal icon) at runtime.
        return 'REVIVE_MOVE'
    info = info_for(monster_id)
    signatures = dict(info.intent_signatures)
    if previous_move is None:
        candidates = info.initial_moves
    elif previous_move in ('STUNNED', 'REVIVE_MOVE'):
        # After a stun the script resumes; the visible intent must identify one
        # legal move on its own.
        candidates = tuple(signatures)
    else:
        successors = dict(info.successors)
        if previous_move not in successors:
            raise ValueError(f'Unknown {monster_id} move: {previous_move}')
        candidates = successors[previous_move]
    matches = [move for move in candidates if signatures[move] == tuple(intents)]
    if len(matches) != 1:
        # State-dependent transitions (HP gates, phase changes) are not always in
        # the static graph, but a unique signature over the whole move set still
        # identifies the observed move from public intents alone.
        global_matches = [move for move in signatures if signatures[move] == tuple(intents)]
        if len(global_matches) == 1:
            matches = global_matches
    if len(matches) > 1 and len({signatures[move] for move in matches}) == 1:
        # Several script states are publicly indistinguishable (same visible
        # intents). Record one canonical move deterministically; the private
        # variant carries no observable information.
        matches = [sorted(matches)[0]]
    if len(matches) != 1:
        raise ValueError(f'Intent does not identify one {monster_id} move: {matches}')
    return matches[0]


def _encounters():
    from sts2_env.encounters import act1, act2, act3, act4

    table = {}
    for module in (act1, act2, act3, act4):
        for name in dir(module):
            if name.startswith('setup_') and callable(getattr(module, name)):
                table[name] = getattr(module, name)
    return table


ENCOUNTERS = _encounters()


def _sample_initial_moves(samples=4):
    """Initial moves actually produced by the native encounter tables.

    Per-slot consumer arguments (Exoskeleton positions, Nibbit rows) are passed
    by the encounters themselves, so this is the public source of truth for
    which first moves can appear.
    """
    from sts2_env.core.combat import CombatState

    observed = {}
    for name, setup in ENCOUNTERS.items():
        for seed in range(samples):
            world = CombatState(80, 80, [], seed, relics=[], potions=[], character_id='Ironclad')
            try:
                setup(world, Rng(seed))
                world.start_combat()
            except Exception:  # noqa: BLE001 - not every seed must set up
                continue
            for enemy in world.enemies:
                ai = world.enemy_ais[enemy.combat_id]
                observed.setdefault(enemy.monster_id, set()).add(ai._current_state_id)
    return {name: tuple(sorted(moves)) for name, moves in observed.items()}


ENCOUNTER_INITIAL_MOVES = _sample_initial_moves()
ACT_OF = {}


def _encounter_acts():
    from sts2_env.encounters import act1, act2, act3, act4

    for act, module in (('act1', act1), ('act2', act2), ('act3', act3), ('act4', act4)):
        for name in dir(module):
            if name.startswith('setup_') and callable(getattr(module, name)):
                ACT_OF[name] = act


_encounter_acts()


def sample_roster(setup, seeds=(0, 1, 2, 3, 4, 5)):
    """Real native rosters produced by one encounter setup across fixed seeds."""
    from sts2_env.core.combat import CombatState

    rosters = set()
    for seed in seeds:
        world = CombatState(80, 80, [], seed, relics=[], potions=[], character_id="Ironclad")
        try:
            setup(world, Rng(seed))
            world.start_combat()
        except Exception as exc:  # noqa: BLE001 - report, never guess
            return ('setup_error', type(exc).__name__, str(exc)), ()
        rosters.add(tuple(enemy.monster_id for enemy in world.enemies))
    return None, tuple(sorted(rosters))


def audit():
    """Static monster/encounter inventory; no mission and no model is run."""
    monsters = {}
    for creator_name, creator in CREATORS.items():
        try:
            enemy, _ = creator(Rng(0))
            monster_id = enemy.monster_id
        except TypeError:
            continue
        except Exception:  # noqa: BLE001 - cannot build with defaults
            continue
        monsters.setdefault(monster_id, creator_name)
    described = {}
    for monster_id, creator_name in monsters.items():
        try:
            described[monster_id] = info_for(monster_id)
        except Exception:  # noqa: BLE001 - no public construction variant
            try:
                described[monster_id] = describe_monster(monster_id, CREATORS[creator_name])
            except Exception:  # noqa: BLE001
                continue
    encounters = {}
    for name, setup in ENCOUNTERS.items():
        error, rosters = sample_roster(setup)
        monsters_seen = sorted({m for roster in rosters for m in roster})
        encounters[name] = dict(act=ACT_OF.get(name), error=error, rosters=rosters,
                                monsters=monsters_seen,
                                admitted=bool(rosters) and all(
                                    described.get(m) is not None and described[m].admitted
                                    for m in monsters_seen))
    return dict(monsters=described, encounters=encounters,
                admitted_encounters=sorted(n for n, e in encounters.items() if e['admitted']),
                total_encounters=len(encounters),
                admitted_monsters=sorted(m for m, d in described.items() if d.admitted),
                total_monsters=len(described))






