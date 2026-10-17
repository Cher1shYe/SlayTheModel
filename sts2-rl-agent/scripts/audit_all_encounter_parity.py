"""All-encounter MCTS parity sweep. Never trains and never writes weights."""
import dataclasses
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits, SCHEMA_VERSION, RULES_VERSION, atomic_json
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.content_expansion import CODEC
from sts2_env.az.information import BeliefSampler
from sts2_env.az.monster_registry import ENCOUNTERS
from sts2_env.az.rewards import V7
from sts2_env.az.scenarios import CombatScenario, DeckEntry
from sts2_env.search.clone import clone_state

DECK = ['STRIKE_IRONCLAD'] * 3 + ['DEFEND_IRONCLAD'] * 3 + ['BASH', 'GOLD_AXE', 'BOLAS', 'FEED']


def recipe(encounter, seed):
    from collections import Counter
    entries = tuple(DeckEntry(name, False, count) for name, count in Counter(DECK).items())
    return CombatScenario(SCHEMA_VERSION, f'sweep-{encounter}-{seed}', 'ironclad-colorless-audit',
                          'train', 'Ironclad', 0, encounter, entries, 80, 80, (), (), seed,
                          RULES_VERSION, ALL_CONTENT)


def aligned_particle(env, rng):
    particle = BeliefSampler().sample(env.information, rng)
    if particle.info != env.information:
        return particle, 'sample'
    for attr in ('draw_pile', 'discard_pile'):
        pool = list(getattr(particle.world, attr))
        ordered = []
        for card in getattr(env.world, attr):
            twin = next(x for x in pool if CODEC.capture(x) == CODEC.capture(card))
            pool.remove(twin)
            ordered.append(twin)
        setattr(particle.world, attr, ordered)
    particle.world.rng = clone_state(env.world.rng)
    return particle, None


def check(encounter, seed=21, steps=8):
    if encounter == 'setup_test_subject_boss':
        return {'status': 'delegated', 'detail': 'three-form boss uses the dedicated boss_phases contract'}
    try:
        env = ObservableCombatAdapter(recipe(encounter, seed), reward_version=V7,
                                      limits=EpisodeLimits(max_turns=6, max_decisions=40))
    except Exception as exc:  # noqa: BLE001
        return {'status': 'build_error', 'detail': f'{type(exc).__name__}: {exc}'}
    rng = np.random.default_rng(seed)
    try:
        for step in range(steps):
            if env.outcome().done:
                return {'status': 'pass', 'detail': f'done after {step} steps'}
            particle, failure = aligned_particle(env, rng)
            if failure:
                return {'status': 'fail', 'detail': f'step {step}: particle != root', 'step': step}
            legal = np.flatnonzero(env.information.legal_mask)
            action = int(rng.choice(legal))
            predicted = particle.step(action)
            env.step(action)
            if predicted != env.information:
                fields = [f.name for f in dataclasses.fields(predicted)
                          if getattr(predicted, f.name) != getattr(env.information, f.name)]
                return {'status': 'fail', 'detail': f'step {step}: {fields}', 'step': step,
                        'action': action}
    except Exception as exc:  # noqa: BLE001 - record, never mask
        return {'status': 'error', 'detail': f'{type(exc).__name__}: {exc}'}
    return {'status': 'pass', 'detail': f'{steps} steps'}


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    names = sorted(ENCOUNTERS)
    if limit:
        names = names[:limit]
    results = {}
    for name in names:
        outcome = check(name)
        results[name] = outcome
        print(f"{outcome['status']:6s} {name:46s} {outcome['detail']}")
    passed = sum(r['status'] == 'pass' for r in results.values())
    delegated = sum(r['status'] == 'delegated' for r in results.values())
    summary = {'version': 'all-encounter-parity-v1', 'content': ALL_CONTENT,
               'encounters': len(results), 'passed': passed, 'delegated': delegated,
               'failed': len(results) - passed - delegated, 'results': results}
    atomic_json(ROOT / 'docs/all_encounter_parity.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
