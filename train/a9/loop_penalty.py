"""Penalize repeated PUBLIC decision states only after several visits."""
from collections import deque
import hashlib


def fingerprint(obs):
    digest = hashlib.blake2b(digest_size=16)
    for key in ('token_cat', 'token_num', 'action_cat', 'action_ref', 'action_num'):
        array = obs[key]
        digest.update(str((key, array.shape, array.dtype)).encode())
        digest.update(array.tobytes())
    return digest.digest()


def visit(env, obs, state, penalty, max_repeats=16, history_size=64):
    scope = (state['act'], state['floor'], state['fight'], state['combat'])
    key = fingerprint(obs)
    if env.get('loop_scope') != scope:
        env['loop_scope'] = scope
        env['loop_history'] = deque([key], maxlen=history_size)
        env['loop_room_hits'] = 0
        return 0., False
    history = env['loop_history']
    repeats = history.count(key)
    history.append(key)
    if repeats < 3:
        return 0., False
    cost = penalty * min(repeats - 2, 4)
    env['loop_room_hits'] += 1
    env['loop_hits'] = env.get('loop_hits', 0) + 1
    env['loop_cost'] = env.get('loop_cost', 0.) + cost
    return -cost, env['loop_room_hits'] >= max_repeats
