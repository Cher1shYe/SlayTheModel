"""Temporary all-encounter diff helper (not a test)."""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from tests.test_az_all_mcts import aligned_particle, env_for

encounter = sys.argv[1]
env = env_for(encounter)
rng = np.random.default_rng(21)
for step in range(10):
    if env.outcome().done:
        print('done at', step)
        break
    try:
        particle = aligned_particle(env, rng)
        legal = np.flatnonzero(env.information.legal_mask)
        action = int(rng.choice(legal))
        predicted = particle.step(action)
        env.step(action)
    except Exception as exc:  # noqa: BLE001
        print('ERROR step', step, type(exc).__name__, str(exc)[:160])
        break
    if predicted != env.information:
        print('MISMATCH step', step, 'action', action)
        for field in dataclasses.fields(predicted):
            a, b = getattr(predicted, field.name), getattr(env.information, field.name)
            if a != b:
                print(' DIFF', field.name)
                print('   particle', str(a)[:600])
                print('   real    ', str(b)[:600])
        break
else:
    print('all steps equal')
