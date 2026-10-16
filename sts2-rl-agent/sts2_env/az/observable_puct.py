"""Particle PUCT with shared information-history nodes and sampled outcome edges.

The planner's public boundary accepts InformationState only. Each simulation
draws a fresh root particle and keeps it for the whole path. Action selection
uses shared P/N/W; chance successors are produced by the engine, never by PUCT.
"""
from dataclasses import dataclass, field
from math import sqrt
from time import perf_counter

import numpy as np

from .information import BeliefSampler, InformationState
from .encoder import encode_information
from .puct import SearchResult
from .search_config import LEGACY, PRIOR, PARENT, COMBINED, validate_search
from sts2_env.cards import base as card_base


@dataclass
class OutcomeNode:
    legal_mask: tuple
    edges: dict = field(default_factory=dict)
    arrivals: int = 0
    initial_value: float = 0.0


@dataclass
class ActionEdge:
    prior: float
    visits: int = 0
    total_value: float = 0.0
    outcomes: dict = field(default_factory=dict)

    @property
    def q(self):
        return self.total_value / self.visits if self.visits else 0.0


def search_belief(info, sample, evaluate, *, model_version, search_seed=0, budget=64,
                  c_puct=1.5, max_depth=128, training=False, epsilon=0.25,
                  alpha=0.3, temperature=0, search_version=LEGACY):
    """Generic probability-tree core; combat callers use plan_observable.

sample(info, rng) returns a particle with .info and .step(action)->public_info.
Public objects expose .legal_mask, .key() and .terminal_value(). The generic
interface makes enumerated chance-tree expectation tests independent of combat.
"""
    validate_search(search_version)
    if (type(budget) is not int or budget < 1 or type(max_depth) is not int or max_depth < 1
            or not np.isfinite([c_puct, epsilon, alpha, temperature]).all() or c_puct < 0
            or not 0 <= epsilon <= 1 or alpha <= 0 or temperature not in (0, 1)
            or (not training and temperature != 0) or not model_version):
        raise ValueError("Invalid information-search configuration")
    started = perf_counter()
    rng = np.random.default_rng(search_seed)
    root = OutcomeNode(tuple(info.legal_mask))
    size = len(info.legal_mask)
    visits = np.zeros(size, dtype=np.int64)
    priors = np.zeros(size, dtype=np.float64)
    saved_id = card_base._next_instance_id

    def mask_for(current):
        mask = np.asarray(current.legal_mask)
        if mask.shape != (size,) or not np.isin(mask, [0, 1]).all() or not mask.any():
            raise ValueError("Invalid nonterminal information mask")
        return mask.astype(bool)

    def predict(current):
        mask = mask_for(current)
        p, value = evaluate(current)
        p = np.asarray(p, dtype=np.float64)
        if (p.shape != (size,) or not np.isfinite(p).all() or (p < 0).any() or p[~mask].any()
                or not np.isclose(p.sum(), 1, atol=1e-5) or not np.isfinite(value) or not -1 <= value <= 1):
            raise ValueError("Invalid observable network prediction")
        return p / p.sum(), float(value)

    def expand(current, node, noisy=False):
        p, value = predict(current)
        node.initial_value = value
        legal = np.flatnonzero(mask_for(current))
        if noisy:
            p[legal] = (1 - epsilon) * p[legal] + epsilon * rng.dirichlet(np.full(len(legal), alpha))
        node.edges = {int(a): ActionEdge(float(p[a])) for a in legal}
        return value

    def result(action, target, count, forced=False):
        return SearchResult(action, visits, target, priors, count, perf_counter() - started,
                            forced, model_version, root, "observable")

    try:
        if info.terminal_value() is not None:
            return result(None, priors.copy(), 0)
        legal = np.flatnonzero(mask_for(info))
        if len(legal) == 1:
            priors[legal[0]] = 1
            return result(int(legal[0]), priors.copy(), 0, True)
        expand(info, root, training)
        for action, edge in root.edges.items():
            priors[action] = edge.prior
        for _ in range(budget):
            particle = sample(info, rng)
            if particle.info.key() != info.key():
                raise ValueError("Root particle changed public information")
            node, path = root, []
            for depth in range(1, max_depth + 1):
                if tuple(particle.info.legal_mask) != node.legal_mask:
                    raise ValueError("Same information node has inconsistent legal actions")
                total = sum(edge.visits for edge in node.edges.values())
                action, edge = max(node.edges.items(), key=lambda pair:
                    (node.initial_value if not pair[1].visits and search_version in (PARENT, COMBINED)
                     else pair[1].q) + c_puct * pair[1].prior * sqrt(1 + total) / (1 + pair[1].visits))
                successor = particle.step(action)
                path.append(edge)
                key = (model_version, successor.key())
                new = key not in edge.outcomes
                if new:
                    edge.outcomes[key] = OutcomeNode(tuple(successor.legal_mask))
                node = edge.outcomes[key]
                node.arrivals += 1
                if tuple(successor.legal_mask) != node.legal_mask:
                    raise ValueError("Same outcome has inconsistent legal actions")
                value = successor.terminal_value()
                if value is not None:
                    if not np.isfinite(value) or not -1 <= value <= 1:
                        raise ValueError("Invalid terminal utility")
                    break
                if new:
                    value = expand(successor, node)
                    break
                if depth == max_depth:
                    _, value = predict(successor)
                    break
            for edge in path:
                edge.visits += 1
                edge.total_value += value
        for action, edge in root.edges.items():
            visits[action] = edge.visits
        target = visits / visits.sum()
        action = int(rng.choice(size, p=target)) if temperature == 1 else int(np.argmax(visits))
        if temperature == 0 and search_version in (PRIOR, COMBINED):
            tied = np.flatnonzero(visits == visits.max())
            action = int(max(tied, key=lambda a: (priors[a], -int(a))))
        return result(action, target, budget)
    finally:
        card_base._next_instance_id = saved_id


def plan_observable(info, model, **kwargs):
    if type(info) is not InformationState:
        raise TypeError("Observable planner accepts InformationState, never a world or recipe")
    if model.information_mode != "observable":
        raise ValueError("Observable planning requires an observable model")
    if getattr(model, "reward_version", "win-loss-v1") != info.reward_version:
        raise ValueError("Planner/model reward mismatch")
    if getattr(model, "content_version", "shrinker-starter-v1") != info.content_version:
        raise ValueError("Planner/model content mismatch")
    info.validate()
    return search_belief(info, BeliefSampler().sample,
                         lambda public: model.predict(encode_information(public)), **kwargs)
