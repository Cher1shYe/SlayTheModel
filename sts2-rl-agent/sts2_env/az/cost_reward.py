"""Linear battle-cost reward: outcome + linear HP loss + weak turn cost.

The per-step process reward is the decrease of

    C_t = 0.29 * lost_hp_t / entry_hp + 0.002 * min(turns_t, 40) / 40

so that the episode return telescopes to

    R = R_end - C_end

with R_end = +0.8 win, -0.7 death, -0.4 time_limit. Full HP loss always costs
0.29, whichever entry HP the recipe uses, so the ordering

    worst win 0.51 > best time_limit -0.40 > best death -0.70

holds inside the critic's [-1, 1] output range. There is no exponential term
and no V7 potential shaping on this path.
"""
import math

VERSION = 'linear-battle-cost-v1'
HP_CAP = 9999
HP_COST = .29
TURN_COST = .002
TURN_CAP = 40
WIN, DEATH, TIME_LIMIT = .8, -.7, -.4


def cost(hp, entry_hp, turns):
    """C_t from the observed HP and the number of turns already ended."""
    if type(hp) is not int or type(entry_hp) is not int or type(turns) is not int:
        raise ValueError('Cost facts must be ints')
    if not 1 <= entry_hp <= HP_CAP or not 0 <= hp <= HP_CAP or not 0 <= turns:
        raise ValueError('Cost facts out of range')
    lost = min(max(entry_hp - hp, 0), entry_hp)
    return HP_COST * lost / entry_hp + TURN_COST * min(turns, TURN_CAP) / TURN_CAP


def terminal(raw):
    """R_end from the validated native outcome."""
    end = raw['outcome']
    if type(raw['complete']) is not bool or type(end['won']) is not bool:
        raise ValueError('Terminal outcome flags must be bool')
    if not raw['complete']:
        return TIME_LIMIT
    return WIN if end['won'] else DEATH


def total(rows, end_reward):
    value = end_reward + sum(r.get('shaping_reward', 0.) for r in rows)
    if not math.isfinite(value):
        raise ValueError('Nonfinite battle return')
    return value
