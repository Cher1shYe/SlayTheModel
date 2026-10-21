"""Keyed particle PUCT. Every node rebuilds its own public candidate table."""
from dataclasses import dataclass
from collections import OrderedDict
from math import sqrt
from time import perf_counter
import numpy as np

from .information import InformationState, BeliefSampler
from .entity_encoder import encode_entities
from .action_candidates import action_candidates
from .observable_puct import ActionEdge, OutcomeNode
from sts2_env.cards import base as card_base

VERSION = 'dynamic-key-puct-v1'
from .search_config import DYNAMIC_RISK, DYNAMIC_VERSIONS, leaf_settings


@dataclass
class DynamicSearchResult:
    action: str
    root_visits: dict
    policy_target: dict
    root_priors: dict
    simulations: int
    elapsed: float
    forced_action: bool
    model_version: str
    root: OutcomeNode
    mean_depth: float = 0.
    max_depth_reached: int = 0


def search_dynamic(info, sample, evaluate, candidates, *, model_version, search_seed=0,
                   budget=64, c_puct=1.5, max_depth=128, training=False,
                   epsilon=.25, alpha=.3, temperature=0, search_version=VERSION, cutoff_reward=None,
                   leaf_mode='heuristic', value_mix=.5):
    leaf_settings(leaf_mode, value_mix)
    if search_version != DYNAMIC_RISK and leaf_mode != 'heuristic':
        raise ValueError('Leaf evaluation modes require dynamic risk search')
    if (search_version not in DYNAMIC_VERSIONS or not model_version or type(budget) is not int or budget < 1
            or type(max_depth) is not int or max_depth < 1 or temperature not in (0, 1)
            or (not training and temperature != 0) or not np.isfinite([c_puct, epsilon, alpha]).all()
            or c_puct < 0 or not 0 <= epsilon <= 1 or alpha <= 0):
        raise ValueError('Invalid dynamic search configuration')
    if info.terminal_value() is not None:
        raise ValueError('Terminal state has no dynamic policy')
    risk_search = search_version == DYNAMIC_RISK
    if risk_search != (cutoff_reward is not None):
        raise ValueError('Risk search requires its explicit cutoff/terminal evaluator')
    started = perf_counter()
    rng = np.random.default_rng(search_seed)

    def leaf_value(public, learned):
        # Terminal outcomes are handled separately and never blended/predicted.
        if not risk_search or leaf_mode == 'learned':
            return learned
        heuristic = cutoff_reward(info, public)
        if not np.isfinite(heuristic) or not -1 <= heuristic <= 1:
            raise ValueError('Invalid heuristic utility')
        return heuristic if leaf_mode == 'heuristic' else (1-value_mix)*heuristic + value_mix*learned

    def keys(public):
        items = tuple(candidates(public))
        if not items or len(items) != len(set(items)):
            raise ValueError('Empty/duplicate dynamic candidate keys')
        return tuple(sorted(items))  # canonical tie/noise order, independent of enumeration

    def predict(public, actions):
        p, v = evaluate(public)
        if (set(p) != set(actions) or not np.isfinite(list(p.values())).all()
                or any(x < 0 for x in p.values()) or not np.isclose(sum(p.values()), 1, atol=1e-5)
                or not np.isfinite(v) or not -1 <= v <= 1):
            raise ValueError('Invalid keyed prediction')
        total = sum(p.values())
        return {k: p[k] / total for k in actions}, float(v)

    def expand(public, node, noisy=False):
        p, v = predict(public, node.legal_mask)
        if noisy:
            noise = rng.dirichlet(np.full(len(p), alpha))
            p = {k: (1-epsilon)*p[k] + epsilon*n for k, n in zip(node.legal_mask, noise)}
        node.initial_value = v
        node.edges = {k: ActionEdge(p[k]) for k in node.legal_mask}
        return v

    saved_id = card_base._next_instance_id
    try:
        root = OutcomeNode(keys(info))
        if len(root.legal_mask) == 1:
            key = root.legal_mask[0]
            return DynamicSearchResult(key, {key: 0}, {key: 1.}, {key: 1.}, 0,
                                       perf_counter()-started, True, model_version, root)
        expand(info, root, training)
        depths = []
        for _ in range(budget):
            particle = sample(info, rng)
            if particle.info.key() != info.key():
                raise ValueError('Particle changed public root')
            node, path = root, []
            for depth in range(1, max_depth+1):
                if keys(particle.info) != node.legal_mask:
                    raise ValueError('Same node has inconsistent candidates')
                total = sum(e.visits for e in node.edges.values())
                action = max(node.legal_mask, key=lambda k: node.edges[k].q +
                    c_puct*node.edges[k].prior*sqrt(1+total)/(1+node.edges[k].visits))
                edge = node.edges[action]
                successor = particle.step(action)
                path.append(edge)
                value = successor.terminal_value()
                if risk_search and value is not None:
                    value = cutoff_reward(info, successor)
                if value is not None:
                    if not np.isfinite(value) or not -1 <= value <= 1:
                        raise ValueError('Invalid terminal utility')
                    break
                identity = (model_version, successor.key())
                new = identity not in edge.outcomes
                if new:
                    edge.outcomes[identity] = OutcomeNode(keys(successor))
                node = edge.outcomes[identity]
                node.arrivals += 1
                if keys(successor) != node.legal_mask:
                    raise ValueError('Same successor has inconsistent candidates')
                if new:
                    value = expand(successor, node)
                    value = leaf_value(successor, value)
                    break
                if depth == max_depth:
                    _, value = predict(successor, node.legal_mask)
                    value = leaf_value(successor, value)
            if not np.isfinite(value) or not -1 <= value <= 1:
                raise ValueError('Invalid backed-up utility')
            depths.append(len(path))
            for edge in path:
                edge.visits += 1
                edge.total_value += value
        visits = {k: root.edges[k].visits for k in root.legal_mask}
        target = {k: v / budget for k, v in visits.items()}
        action = (root.legal_mask[int(rng.choice(len(target), p=list(target.values())))] if temperature
                  else max(root.legal_mask, key=lambda k: (visits[k], root.edges[k].q, root.edges[k].prior) if risk_search else (visits[k], root.edges[k].prior)))
        return DynamicSearchResult(action, visits, target, {k: e.prior for k, e in root.edges.items()},
                                   budget, perf_counter()-started, False, model_version, root,
                                   float(np.mean(depths)), max(depths))
    finally:
        card_base._next_instance_id = saved_id


class KeyedParticle:
    def __init__(self, particle):
        self.particle = particle

    @property
    def info(self):
        return self.particle.info

    def step(self, key):
        _, mapping = action_candidates(self.info)
        if key not in mapping:
            raise ValueError('Action missing from current particle node')
        return self.particle.step(mapping[key])


class _SearchEvaluationCache:
    """Bounded, search-local memoization of immutable public inputs only.

    Include the derived mask: InformationState.key deliberately omits it so
    mismatched masks must still reach the encoder's contract validation.
    Never retain a world, hidden state, RNG or data from a previous model call.
    """
    def __init__(self, model, capacity=256):
        self.model, self.capacity = model, capacity
        self.identities = OrderedDict()
        self.entries = OrderedDict()

    def entry(self, public):
        identity = id(public)
        cached = self.identities.get(identity)
        if cached is None:
            key = (public.key(), public.legal_mask)
            # Retaining the object prevents Python from recycling its id.
            self.identities[identity] = (public, key)
            if len(self.identities) > self.capacity:
                self.identities.popitem(last=False)
        else:
            key = cached[1]
            self.identities.move_to_end(identity)
        if key not in self.entries:
            self.entries[key] = [encode_entities(public), None]
            if len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
        else:
            self.entries.move_to_end(key)
        return self.entries[key]

    def encode(self, public):
        return self.entry(public)[0]

    def predict(self, public):
        entry = self.entry(public)
        if entry[1] is None:
            entry[1] = self.model.predict(entry[0])
        return entry[1]


def plan_dynamic(info, model, *, cache_evaluations=True, **kwargs):
    if type(info) is not InformationState:
        raise TypeError('Dynamic planner accepts public InformationState only')
    from .transformer_network import TransformerPolicyValueNetwork
    if not isinstance(model, TransformerPolicyValueNetwork):
        raise ValueError('Dynamic planner requires a Transformer model')
    if (model.content_version,model.reward_version) != (info.content_version,info.reward_version):
        raise ValueError('Dynamic planner content/reward mismatch')
    from .rewards import V7
    requested = kwargs.get('search_version', VERSION)
    if (requested == DYNAMIC_RISK) != (info.reward_version == V7):
        raise ValueError('Search/reward versions must match')
    if requested == DYNAMIC_RISK:
        from .risk_reward import search_utility
        kwargs['cutoff_reward'] = search_utility
    # The uncached path remains available for exact differential regression tests.
    cache = _SearchEvaluationCache(model) if cache_evaluations else None
    encode = cache.encode if cache else encode_entities
    evaluate = cache.predict if cache else lambda public: model.predict(encode(public))
    encode(info)
    sampler = BeliefSampler()
    return search_dynamic(info, lambda public, rng: KeyedParticle(sampler.sample(public, rng)),
        evaluate,
        lambda public: (a.action_key for a in encode(public).actions if a.legal), **kwargs)
