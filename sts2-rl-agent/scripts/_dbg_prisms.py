"""Temporary infested prism energy debug (not a test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from tests.test_az_all_mcts import aligned_particle, env_for
from sts2_env.az.content_expansion import CODEC

env = env_for('setup_infested_prisms_elite')
rng = np.random.default_rng(21)
for step in range(5):
    info = env.information
    particle = aligned_particle(env, rng)
    legal = np.flatnonzero(info.legal_mask)
    action = int(rng.choice(legal))
    print('step', step, 'action', action, 'energy', info.energy)
    print('  hand tokens', info.hand)
    print('  hand costs', [s.cost for s in info.hand_states])
    print('  particle costs', [CODEC.capture(c).cost for c in particle.world.hand])
    print('  enemy powers', [(s.monster_id, s.powers) for s in info.enemies])
    predicted = particle.step(action)
    env.step(action)
    print('  predicted energy', predicted.energy, 'real energy', env.information.energy)
    if predicted != env.information:
        break
