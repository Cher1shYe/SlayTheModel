"""G1 public card-state codec. Representation support is not content admission.

The caller supplies an audited token/factory registry and explicitly enables
mutable fields. No world, owner, global instance ID or executable callback is
stored. Restore allocates through the caller's particle-local ID allocator.
"""
from dataclasses import dataclass, fields
from typing import Callable, Mapping

from sts2_env.cards import base

CARD_STATE_VERSION = "az-public-card-state-v1"


@dataclass(frozen=True)
class CardStatePolicy:
    temporary_cost: bool = False
    combat_cost: bool = False
    retain: bool = False
    effect_changes: bool = False
    max_x_energy_spent: int = 3
    generated_metadata: bool = False
    return_to_hand: bool = False
    state_version: str = CARD_STATE_VERSION


@dataclass(frozen=True)
class PublicCardState:
    token: str
    cost: int
    original_cost: int
    base_damage: int | None
    base_block: int | None
    effect_vars: tuple[tuple[str, int], ...]
    turn_cost: int | None = None
    single_turn_retain: bool = False
    version: str = CARD_STATE_VERSION
    turn_star_cost: int | None = None
    is_clone: bool = False


class CardStateCodec:
    def __init__(self, factories: Mapping[str, Callable], policy=CardStatePolicy()):
        if not factories or type(policy) is not CardStatePolicy:
            raise ValueError("Explicit factories and card policy required")
        self.factories = dict(factories)
        self.policy = policy

    def _make(self, token):
        if type(token) is not str or token not in self.factories:
            raise ValueError("Unaudited card token")
        card = self.factories[token]()
        if card.card_id.name + ("+" if card.upgraded else "") != token:
            raise ValueError("Factory/token mismatch")
        return card

    def _reference(self, token):
        saved = base._next_instance_id
        try:
            return self._make(token)
        finally:
            base._next_instance_id = saved

    def capture(self, card):
        token = card.card_id.name + ("+" if card.upgraded else "")
        reference = self._reference(token)
        dynamic = {"instance_id", "cost", "combat_vars", "single_turn_retain"}
        if self.policy.effect_changes:
            dynamic |= {"base_damage", "base_block", "effect_vars"}
        for field in fields(reference):
            if field.name not in dynamic and getattr(card, field.name) != getattr(reference, field.name):
                raise ValueError(f"Unaudited card mutation: {field.name}")
        # Owner is engine bookkeeping, never a network feature. Reject arbitrary
        # extra state rather than dropping it while claiming lossless restoration.
        if set(vars(card)) - {f.name for f in fields(reference)} - {"owner", "energy_spent"}:
            raise ValueError("Unaudited attached card state")
        if hasattr(card, "energy_spent") and (type(card.energy_spent) is not int or not 0 <= card.energy_spent <= (self.policy.max_x_energy_spent if card.has_energy_cost_x else 3)):
            raise ValueError("Unaudited energy spending")
        allowed={"_turn_cost_override", "_stars_spent_for_play"}
        if self.policy.generated_metadata:allowed|={"_turn_star_cost_override","_is_clone"}
        if self.policy.return_to_hand:allowed|={"_return_before_hand_draw_round"}
        if set(card.combat_vars) - allowed:
            raise ValueError("Unaudited combat variable")
        if card.combat_vars.get("_stars_spent_for_play", 0) != 0:
            raise ValueError("Star spending requires another mechanism contract")
        turn_cost = card.combat_vars.get("_turn_cost_override")
        if "_turn_cost_override" in card.combat_vars and type(turn_cost) is not int:
            raise ValueError("Invalid temporary cost")
        state = PublicCardState(token, card.cost, card.original_cost, card.base_damage,
                                card.base_block, tuple(sorted(card.effect_vars.items())),
                                turn_cost, card.single_turn_retain,self.policy.state_version,
                                card.combat_vars.get('_turn_star_cost_override'),bool(card.combat_vars.get('_is_clone',0)))
        if card.combat_vars.get('_is_clone',0) not in (0,1):raise ValueError('Invalid clone flag')
        self.validate(state)
        return state

    def validate(self, state):
        if type(state) is not PublicCardState or state.version != self.policy.state_version:
            raise ValueError("Unsupported card state version/type")
        if type(state.is_clone)is not bool or (state.is_clone and not self.policy.generated_metadata):raise ValueError('Clone state not admitted')
        if state.turn_star_cost is not None and (not self.policy.generated_metadata or type(state.turn_star_cost)is not int or state.turn_star_cost!=0):raise ValueError('Star cost state not admitted')
        reference = self._reference(state.token)
        if (type(state.cost) is not int or type(state.original_cost) is not int
                or state.original_cost != reference.original_cost
                or state.cost < -1 or type(state.single_turn_retain) is not bool):
            raise ValueError("Invalid public cost/retain")
        if any(x is not None and type(x) is not int for x in (state.base_damage, state.base_block)):
            raise ValueError("Invalid public card values")
        if (type(state.effect_vars) is not tuple or any(type(p) is not tuple or len(p) != 2
                or type(p[0]) is not str or type(p[1]) is not int for p in state.effect_vars)
                or tuple(sorted(state.effect_vars)) != state.effect_vars
                or len(dict(state.effect_vars)) != len(state.effect_vars)):
            raise ValueError("Noncanonical effect variables")
        if not self.policy.effect_changes and (state.base_damage != reference.base_damage
                or state.base_block != reference.base_block or dict(state.effect_vars) != reference.effect_vars):
            raise ValueError("Effect mutations not admitted")
        if state.turn_cost is not None:
            if (not self.policy.temporary_cost or type(state.turn_cost) is not int
                    or state.turn_cost < 0 or state.cost != state.turn_cost):
                raise ValueError("Temporary cost not admitted or inconsistent")
        elif state.cost != reference.cost and not self.policy.combat_cost:
            raise ValueError("Combat cost not admitted")
        if state.single_turn_retain and not self.policy.retain:
            raise ValueError("Temporary retain not admitted")
        return state

    def restore(self, state):
        self.validate(state)
        card = self._make(state.token)
        card.cost, card.original_cost = state.cost, state.original_cost
        card.base_damage, card.base_block = state.base_damage, state.base_block
        card.effect_vars = dict(state.effect_vars)
        card.single_turn_retain = state.single_turn_retain
        if state.turn_cost is not None:
            card.set_temporary_cost_for_turn(state.turn_cost)
        if state.turn_star_cost is not None:card.set_temporary_star_cost_for_turn(state.turn_star_cost)
        if state.is_clone:card.combat_vars['_is_clone']=1
        return card
