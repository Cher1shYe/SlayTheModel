"""Encounter robustness under varied decks; feeds the P3 generator admission."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits, RULES_VERSION, SCHEMA_VERSION, atomic_json
from sts2_env.az.content import ALL_CONTENT
from sts2_env.az.monster_registry import ENCOUNTERS
from sts2_env.az.rewards import V7
from sts2_env.az.scenarios import CombatScenario, DeckEntry

DECKS = (
    (('STRIKE_IRONCLAD', False, 5), ('DEFEND_IRONCLAD', False, 4), ('BASH', False, 1)),
    (('POMMEL_STRIKE', False, 3), ('SHRUG_IT_OFF', False, 3), ('INFLAME', True, 2),
     ('ANGER', False, 2), ('IRON_WAVE', False, 2)),
)


def recipe(encounter, index):
    deck = tuple(DeckEntry(card, upgraded, count) for card, upgraded, count in DECKS[index])
    return CombatScenario(SCHEMA_VERSION, f'robust-{index}-{encounter}', 'all-content-arbitrary-v1',
                          'train', 'Ironclad', 0, encounter, deck, 80, 80, (), (),
                          900000 + index, RULES_VERSION, ALL_CONTENT)


def probe(encounter, index, steps=6, seed=5):
    env = ObservableCombatAdapter(recipe(encounter, index), reward_version=V7,
                                  limits=EpisodeLimits(max_turns=6, max_decisions=40))
    rng = np.random.default_rng(seed + index)
    for step in range(steps):
        if env.outcome().done:
            return None
        legal = np.flatnonzero(env.information.legal_mask)
        env.step(int(rng.choice(legal)))
    return None


def main():
    parity = json.loads((ROOT / 'docs/all_encounter_parity.json').read_text(encoding='utf-8'))
    passed = sorted(name for name, entry in parity['results'].items()
                    if entry['status'] == 'pass')
    results, robust = {}, []
    for encounter in passed:
        outcomes = []
        for index in range(len(DECKS)):
            try:
                probe(encounter, index)
                outcomes.append({'deck': index, 'status': 'pass'})
            except Exception as exc:  # noqa: BLE001
                outcomes.append({'deck': index, 'status': 'fail',
                                 'error': f'{type(exc).__name__}: {exc}'})
        results[encounter] = outcomes
        if all(outcome['status'] == 'pass' for outcome in outcomes):
            robust.append(encounter)
        status = 'pass' if encounter in robust else 'fail'
        detail = next((o['error'] for o in outcomes if o['status'] == 'fail'), 'all decks')
        print(f'{status:5s} {encounter:46s} {detail[:90]}')
    report = {'version': 'all-encounter-robustness-v1', 'content': ALL_CONTENT,
              'decks': len(DECKS), 'steps': 6, 'parity_passed': len(passed),
              'robust': robust, 'robust_count': len(robust),
              'unstable': sorted(set(passed) - set(robust)), 'results': results,
              'note': 'Random-legal-action probes with two fixed synthetic decks; no training.'}
    atomic_json(ROOT / 'docs/all_encounter_robustness.json', report)
    print(json.dumps({'parity_passed': len(passed), 'robust': len(robust),
                      'unstable': report['unstable']}, ensure_ascii=False))


if __name__ == '__main__':
    main()

