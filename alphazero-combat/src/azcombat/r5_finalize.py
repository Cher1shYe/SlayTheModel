"""Finalize already-completed R5 without rerunning or rewriting frozen tasks."""
import argparse
import json
from pathlib import Path

from .native_probe import audit_probe
from .r5_experiment import read, ref, check_ref, write_new, screen_pairs


def finalize(root):
    plan = read(check_ref(read(root / 'plan.sha256.json')))
    for item in read(root / 'candidate-lock.json').values():
        check_ref(item)
    results, records = [], []
    for task in plan['evaluation']:
        directory = root / 'evaluation' / task['taskId']
        result = read(directory / 'complete.json')
        if result['task'] != task:
            raise ValueError('completed task differs from frozen evaluation')
        for artifact in result['artifacts'].values():
            check_ref(artifact)
        # Final audit is independent of the broken summary aggregation, and
        # invokes the same strict Native protocol/ledger re-reader.
        probe = read(directory / 'trajectory.probe.json')
        audited = audit_probe(directory / 'trajectory.jsonl', expected=probe)
        if any(audited[key] != result['report'][key] for key in audited):
            raise ValueError('final reread differs from executed probe')
        results.append(result)
        records.append(ref(directory / 'complete.json'))
    summary = screen_pairs(results)
    summary.update({'plan': ref(root / 'plan.json'), 'tasks': records,
                    'decisions': sum(r['report']['samples'] for r in results),
                    'choiceRows': sum(len(r['report']['choiceRows']) for r in results),
                    'nestedChoiceRows': sum(r['nestedChoiceRows'] for r in results),
                    'attempts': len(results), 'retries': 0,
                    'fallbacks': sum(r['report']['fallbacks'] for r in results),
                    'maxPythonOnnxError': max(r['numericParity']['maxPythonOnnxError']
                                              for r in results if r['numericParity']),
                    'maxNativeOnnxError': max(r['numericParity']['maxNativeOnnxError']
                                              for r in results if r['numericParity']),
                    'summaryRepair': 'original aggregation tried sum(list); finalizer counts len(choiceRows); no task/model changes',
                    'independentIntegrityReview': 'unavailable',
                    'limitations': plan['limitations']})
    write_new(root / 'evaluation-final-audit.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    result = finalize(args.root.resolve(strict=True))
    print(json.dumps({k: v for k, v in result.items() if k != 'tasks'}, indent=2))
