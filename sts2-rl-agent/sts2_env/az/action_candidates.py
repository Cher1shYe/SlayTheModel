"""Legacy execution mapping lives here, never in the dynamic neural network."""
from .entity_encoder import ActionCandidate
from .mechanic_registry import card_descriptor
from sts2_env.core.constants import MAX_HAND_SIZE, MAX_ENEMIES


def starter_candidates(info):
    rows = [(ActionCandidate('end_turn', 'end_turn'), 0)]
    for slot, name in enumerate(info.hand):
        d = card_descriptor(name)
        if info.energy < d.cost:
            continue
        target = 'enemy' if d.target == 'enemy' else 'player'
        legacy = 1 + MAX_HAND_SIZE + slot * MAX_ENEMIES if target == 'enemy' else slot + 1
        rows.append((ActionCandidate(f'play:hand/{slot}:{target}', 'play', f'hand/{slot}', (target,)), legacy))
    if {i for i, legal in enumerate(info.legal_mask) if legal} != {i for _, i in rows}:
        raise ValueError('Dynamic/native legal action mismatch')
    return tuple(a for a, _ in rows), {a.action_key: i for a, i in rows}


def execute_candidate(adapter, action_key):
    from .entity_encoder import encode_entities
    encode_entities(adapter.information)
    _, mapping = starter_candidates(adapter.information)
    if action_key not in mapping:
        raise ValueError(f'Unknown action key: {action_key}')
    return adapter.step(mapping[action_key])
