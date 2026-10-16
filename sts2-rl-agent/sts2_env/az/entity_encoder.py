"""Public-only starter slice of the extensible entity/action schema."""
from collections import Counter
from dataclasses import dataclass, asdict
import math
from pathlib import Path

from .config import CONTENT_VERSION, REWARD_VERSION, RULES_VERSION, content_hash, atomic_json
from .information import InformationState
from .mechanic_registry import card_descriptor, SHRINKER, Operation, REGISTRY_HASH, POWER_RULES

NUMERIC_FIELDS = ('hp', 'max_hp', 'block', 'energy', 'max_energy', 'turn', 'decisions',
                  'max_decisions', 'max_turns', 'initial_hp', 'shrink', 'vulnerable',
                  'intent_damage', 'intent_hits', 'cycle_step', 'count', 'hand_slot',
                  'base_cost', 'current_cost', 'card_type', 'played_this_turn', 'enemy_rounds')
KINDS = ('state', 'player', 'enemy', 'card')
ZONES = ('none', 'hand', 'draw', 'discard', 'exhaust')
# Ten cards, never generated, plus STATE/player/enemy. At most ten plays + end turn.
SCHEMA = {'version': 'public-entities-starter-v1', 'action_version': 'dynamic-actions-v1',
          'numeric': NUMERIC_FIELDS, 'kinds': KINDS, 'zones': ZONES,
          'max_entities': 13, 'max_actions': 11, 'max_effects': 8,
          'rules': RULES_VERSION, 'content': CONTENT_VERSION, 'reward': REWARD_VERSION,
          'mechanics': REGISTRY_HASH, 'mode': 'network-only', 'search': 'not-integrated-v1',
          'split': 'contract-fixtures-only-v1'}
SCHEMA_HASH = content_hash(SCHEMA)


def numeric(**kwargs):
    if set(kwargs) - set(NUMERIC_FIELDS):
        raise ValueError('Unknown numeric feature')
    # Fixed invertible scaling; no clipping or per-batch normalization.
    return tuple(float(kwargs.get(k, 0)) / 100 for k in NUMERIC_FIELDS)


@dataclass(frozen=True)
class Entity:
    ref: str
    kind: str
    zone: str
    owner: str | None
    numbers: tuple[float, ...]
    effects: tuple[Operation, ...] = ()


@dataclass(frozen=True)
class ActionCandidate:
    action_key: str
    action_type: str
    source_ref: str | None = None
    target_refs: tuple[str, ...] = ()
    choice_refs: tuple[str, ...] = ()
    public_parameters: tuple[float, ...] = ()
    legal: bool = True


@dataclass(frozen=True)
class EntityObservation:
    entities: tuple[Entity, ...]
    actions: tuple[ActionCandidate, ...]
    schema_hash: str = SCHEMA_HASH

    def validate(self):
        if self.schema_hash != SCHEMA_HASH:
            raise ValueError('Entity schema mismatch')
        if not 1 <= len(self.entities) <= SCHEMA['max_entities'] or not 1 <= len(self.actions) <= SCHEMA['max_actions']:
            raise ValueError('Public length overflow or empty state/actions; truncation forbidden')
        refs = {e.ref for e in self.entities}
        if len(refs) != len(self.entities) or sum(e.kind == 'state' for e in self.entities) != 1:
            raise ValueError('Duplicate entity reference or missing/duplicate STATE')
        for e in self.entities:
            if (not e.ref or e.kind not in KINDS or e.zone not in ZONES or (e.owner is not None and e.owner not in refs)
                    or len(e.numbers) != len(NUMERIC_FIELDS) or not all(math.isfinite(x) for x in e.numbers)
                    or len(e.effects) > SCHEMA['max_effects']):
                raise ValueError(f'Invalid entity: {e.ref}')
            for op in e.effects:
                op.validate()
        if len({a.action_key for a in self.actions}) != len(self.actions) or not any(a.legal for a in self.actions):
            raise ValueError('Duplicate action key or no legal action')
        for a in self.actions:
            if (not a.action_key or a.action_type not in ('end_turn', 'play') or type(a.legal) is not bool
                    or a.choice_refs or a.public_parameters
                    or len(a.target_refs) > 1
                    or any(r not in refs for r in ((a.source_ref,) if a.source_ref else ()) + a.target_refs)):
                raise ValueError(f'Unsupported action or dangling reference: {a.action_key}')
            by_ref = {e.ref: e for e in self.entities}
            if a.action_type == 'end_turn' and (a.source_ref is not None or a.target_refs):
                raise ValueError('End turn cannot refer to source/target entities')
            if a.action_type == 'play' and (a.source_ref is None or len(a.target_refs) != 1
                    or by_ref[a.source_ref].kind != 'card' or by_ref[a.source_ref].zone != 'hand'
                    or by_ref[a.target_refs[0]].kind not in ('player', 'enemy')):
                raise ValueError('Play requires a hand card and a creature target')
        return self


def encode_entities(info, diagnostic_dir='output/az_transformer_errors'):
    if type(info) is not InformationState:
        raise TypeError('Only InformationState is accepted')
    try:
        return _encode_entities(info)
    except ValueError as exc:
        # Store only the supplied public projection; never inspect the environment.
        if diagnostic_dir is not None:
            document = {'schema_hash': SCHEMA_HASH, 'reason': str(exc), 'public_information': asdict(info)}
            atomic_json(Path(diagnostic_dir) / (content_hash(document) + '.json'), document)
        raise


def _encode_entities(info):
    if info.content_version != CONTENT_VERSION or info.reward_version != REWARD_VERSION:
        raise ValueError(f'Unsupported content/reward: {info.content_version}/{info.reward_version}')
    info.validate()
    if info.terminal_value() is not None:
        raise ValueError('Terminal states have no decision policy')
    if info.known_top or info.known_bottom or info.known_deck or info.player_strength or info.exhaust:
        raise ValueError('Unsupported starter state extension')
    entities = [Entity('state', 'state', 'none', None, numeric(
        turn=info.turn, decisions=info.history.decisions, max_decisions=info.limits.max_decisions,
        max_turns=info.limits.max_turns, initial_hp=info.initial_hp,
        played_this_turn=len(info.history.played_this_turn), enemy_rounds=len(info.history.enemy_moves))),
        Entity('player', 'player', 'none', None, numeric(hp=info.player_hp, max_hp=info.player_max_hp,
            block=info.player_block, energy=info.energy, max_energy=info.max_energy, shrink=info.shrink),
            POWER_RULES['shrink'] if info.shrink else ()),
        Entity('enemy', 'enemy', 'none', None, numeric(hp=info.enemy_hp, max_hp=info.enemy_max_hp,
            block=info.enemy_block, vulnerable=info.vulnerable, intent_damage=info.intent[1],
            intent_hits=info.intent[2], cycle_step=0 if info.turn == 1 else 1 if info.turn % 2 == 0 else 2),
            SHRINKER + (POWER_RULES['vulnerable'] if info.vulnerable else ()))]
    for zone, pile in (('hand', info.hand), ('draw', info.draw_composition), ('discard', info.discard)):
        entries = [(i, name, 1) for i, name in enumerate(pile)] if zone == 'hand' else [(i, name, count) for i, (name, count) in enumerate(sorted(Counter(pile).items()))]
        for i, name, count in entries:
            d = card_descriptor(name)
            entities.append(Entity(f'{zone}/{i}', 'card', zone, 'player', numeric(
                count=count, hand_slot=i + 1 if zone == 'hand' else 0, base_cost=d.cost,
                current_cost=d.cost, card_type=d.card_type), d.effects))
    from .action_candidates import starter_candidates
    actions, _ = starter_candidates(info)
    return EntityObservation(tuple(entities), actions).validate()
