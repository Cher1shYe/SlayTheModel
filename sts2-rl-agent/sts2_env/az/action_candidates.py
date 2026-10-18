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
    _, mapping = action_candidates(adapter.information)
    if action_key not in mapping:
        raise ValueError(f'Unknown action key: {action_key}')
    return adapter.step(mapping[action_key])


def action_candidates(info):
    from .content import BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT
    from .config import CONTENT_VERSION
    if info.content_version == CONTENT_VERSION: return starter_candidates(info)
    if info.content_version not in (BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT): raise ValueError('Unsupported dynamic action content')
    from sts2_env.gym_env.action_space import action_to_card_and_target
    rows=[]
    for native,legal in enumerate(info.legal_mask):
        if not legal: continue
        if info.choice:
            choice=info.choice
            if choice.mechanism.removesuffix('+') == 'PURITY':
                refs=tuple(f'{o.pile}/{o.index}' for i,o in enumerate(choice.options) if native & (1<<i))
                action=ActionCandidate('choose_set:'+','.join(refs),'choose_set','pending',choice_refs=refs)
            elif native==0:
                action=ActionCandidate('confirm_choice','confirm_choice','pending')
            else:
                o=choice.options[native-1]
                ref=f'{o.pile}/{o.index}'
                action=ActionCandidate('choose:'+ref,'choose','pending',choice_refs=(ref,))
        elif native==0: action=ActionCandidate('end_turn','end_turn')
        else:
            from .actions import decode_card_action
            slot,target=decode_card_action(native, info.content_version)
            if slot is None or slot>=len(info.hand): raise ValueError('Unsupported action category')
            d=card_descriptor(info.hand[slot])
            if d.target == 'random_enemy': refs=tuple(f'enemy/{e.slot}' for e in info.enemies if e.hp>0 and not e.reviving)
            elif target is not None: refs=(f'enemy/{target}',)
            elif d.target=='all_enemies': refs=tuple(f'enemy/{e.slot}' for e in info.enemies if e.hp>0 and not e.reviving)
            elif d.target=='self': refs=('player',)
            else: refs=()
            action=ActionCandidate(f'play:hand/{slot}:'+','.join(refs),'play',f'hand/{slot}',refs)
        rows.append((action,native))
    if len({a.action_key for a,_ in rows})!=len(rows): raise ValueError('Duplicate dynamic action keys')
    return tuple(a for a,_ in rows),{a.action_key:n for a,n in rows}

