"""M1 deterministic, full-state-debug PUCT. Not an information-set planner.

Nodes below an action have one deterministic successor. Do not reuse this tree
for observable search: M2 needs explicit public outcome branches and particles.
"""
from dataclasses import dataclass, field
from math import sqrt
from time import perf_counter
from typing import Protocol

import numpy as np

from .config import EpisodeLimits
from .encoder import MODE, encode_debug
from sts2_env.cards import base as card_base
from sts2_env.search.clone import clone_state
from sts2_env.search.mcts import apply_action


class DebugDomain(Protocol):
    def clone(self): ...
    def terminal_value(self): ...
    def legal_mask(self): ...
    def step(self, action): ...


@dataclass
class DebugCombatDomain:
    world: object
    decisions: int = 0
    limits: EpisodeLimits = field(default_factory=EpisodeLimits)

    def clone(self):
        return DebugCombatDomain(clone_state(self.world), self.decisions, self.limits)

    def terminal_value(self):
        if self.world.is_over:
            return 1.0 if self.world.player_won else -1.0
        if self.decisions >= self.limits.max_decisions or self.world.turn_count > self.limits.max_turns:
            return -1.0
        return None

    def legal_mask(self):
        return encode_debug(self.world, self.decisions).legal_mask

    def step(self, action):
        if self.terminal_value() is not None:
            raise ValueError("Cannot step terminal debug domain")
        mask = self.legal_mask()
        if not 0 <= action < len(mask) or not mask[action]:
            raise ValueError("Illegal debug search action")
        apply_action(self.world, action)
        self.decisions += 1


@dataclass
class Edge:
    prior: float
    visits: int = 0
    total_value: float = 0.0
    child: object = None

    @property
    def q(self):
        return self.total_value / self.visits if self.visits else 0.0


@dataclass
class Node:
    edges: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    action: int | None
    root_visits: np.ndarray
    policy_target: np.ndarray
    root_priors: np.ndarray
    simulations: int
    elapsed: float
    forced_action: bool
    model_version: str
    root: Node
    information_mode: str = MODE


def search_debug(domain, evaluate, *, model_version, search_seed=0, budget=64,
                 c_puct=1.5, max_depth=128, training=False, epsilon=0.25, alpha=0.3,
                 temperature=0.0):
    """evaluate(domain) -> legal priors[115], player-perspective value.

Each completed simulation backs up one leaf/terminal value. Root initialization
does not count. The label is always normalized raw visits, independent of tau.
The global engine allocator and original world are preserved even on exceptions.
"""
    if (type(budget) is not int or budget < 1 or type(max_depth) is not int or max_depth < 1
            or not np.isfinite([c_puct, epsilon, alpha, temperature]).all()
            or c_puct < 0 or not 0 <= epsilon <= 1 or alpha <= 0 or temperature not in (0, 1)
            or (not training and temperature != 0) or not model_version):
        raise ValueError("Invalid PUCT configuration")
    started = perf_counter()
    rng = np.random.default_rng(search_seed)
    saved_id = card_base._next_instance_id
    visits = np.zeros(115, dtype=np.int64)
    priors = np.zeros(115, dtype=np.float64)
    root = Node()

    def mask_for(state):
        mask = np.asarray(state.legal_mask())
        if mask.shape != (115,) or not np.isin(mask, [0, 1]).all() or not mask.any():
            raise ValueError("Invalid nonterminal mask")
        return mask.astype(bool)

    def checked_prediction(state, mask):
        p, v = evaluate(state)
        p = np.asarray(p, dtype=np.float64)
        if (p.shape != (115,) or not np.isfinite(p).all() or (p < 0).any()
                or p[~mask].any() or not np.isclose(p.sum(), 1, atol=1e-5)
                or not np.isfinite(v) or not -1 <= v <= 1):
            raise ValueError("Invalid network prediction")
        return p / p.sum(), float(v)

    def expand(state, node, noise=False):
        mask = mask_for(state)
        p, value = checked_prediction(state, mask)
        legal = np.flatnonzero(mask)
        if noise:
            p[legal] = (1 - epsilon) * p[legal] + epsilon * rng.dirichlet(np.full(len(legal), alpha))
        node.edges = {int(a): Edge(float(p[a])) for a in legal}
        return value

    try:
        if domain.terminal_value() is not None:
            return SearchResult(None, visits, priors.copy(), priors, 0, perf_counter() - started,
                                False, model_version, root)
        # Even root evaluation receives a clone, never the environment world.
        root_state = domain.clone()
        legal = np.flatnonzero(mask_for(root_state))
        if len(legal) == 1:
            action = int(legal[0])
            priors[action] = 1
            return SearchResult(action, visits, priors.copy(), priors, 0, perf_counter() - started,
                                True, model_version, root)
        expand(root_state, root, noise=training)
        for action, edge in root.edges.items():
            priors[action] = edge.prior
        for _ in range(budget):
            card_base._next_instance_id = saved_id
            state = domain.clone()
            node, path = root, []
            for depth in range(1, max_depth + 1):
                if set(np.flatnonzero(mask_for(state))) != set(node.edges):
                    raise ValueError("Deterministic node legal actions changed")
                total = sum(edge.visits for edge in node.edges.values())
                action, edge = max(node.edges.items(), key=lambda pair:
                    pair[1].q + c_puct * pair[1].prior * sqrt(1 + total) / (1 + pair[1].visits))
                state.step(action)
                path.append(edge)
                value = state.terminal_value()
                if value is not None:
                    if not np.isfinite(value) or not -1 <= value <= 1:
                        raise ValueError("Invalid terminal utility")
                    break
                if edge.child is None:
                    edge.child = Node()
                    value = expand(state, edge.child)
                    break
                node = edge.child
                if depth == max_depth:
                    _, value = checked_prediction(state, mask_for(state))
                    break
            for edge in path:
                edge.visits += 1
                edge.total_value += value  # single player: never alternate signs
        for action, edge in root.edges.items():
            visits[action] = edge.visits
        target = visits / visits.sum()
        action = int(rng.choice(115, p=target)) if temperature == 1 else int(np.argmax(visits))
        return SearchResult(action, visits, target, priors, budget, perf_counter() - started,
                            False, model_version, root)
    finally:
        card_base._next_instance_id = saved_id


def plan_debug(world, model, *, decisions=0, limits=None, **kwargs):
    domain = DebugCombatDomain(world, decisions, limits or EpisodeLimits())
    return search_debug(domain, lambda state: model.predict(encode_debug(state.world, state.decisions)), **kwargs)
