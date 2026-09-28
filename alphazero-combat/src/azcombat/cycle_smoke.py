"""Single engineering candidate cycle. Rejection never launches self-play."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from .r4_training import load_r4_admission, train_r4
from .training import TrainConfig
from .export import export_onnx
from .native_probe import run_probe


def write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--index', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = load_r4_admission(args.index)
    seeds = ['AZ-CYCLE-DEV-20260926-01', 'AZ-CYCLE-DEV-20260926-02']
    tasks = [{'seed': seed, 'encounter': encounter, 'policy': policy}
             for seed in seeds for encounter in ('CULTISTS_NORMAL', 'LIVING_FOG_NORMAL')
             for policy in ('pure-mcts', 'policy-value-tree-v1')]
    plan = {'format': 'azcombat.cycle-smoke-plan.v1', 'purpose': 'engineering-development-not-final-evaluation',
            'tasks': tasks, 'training': {'epochs': 5, 'learningRate': .001, 'hidden': 16, 'seed': 20260926,
                'checkpointSelection': 'fixed-final-epoch', 'optimizer': 'one full weighted gradient step per epoch',
                'valueWeights': 'preserve indexed weights: equal terminal trajectory mass within each behavior stratum'},
            'indexSha256': digest(args.index), 'budgetMilliseconds': 1000, 'maxSimulations': 50,
            'maxDecisions': 256, 'timeoutSeconds': 1800, 'minimumSimulationRate': None,
            'protocolErrors': 'stop and retain; no automatic retry', 'deck': 'normal starter; no fixtures or forced actions',
            'gate': 'all pairs audited, no unresolved, candidate wins >= baseline wins; tied wins require nondecreasing total utility',
            'acceptanceScope': 'engineering screen only; separate strict promotion required before champion/self-play',
            'sourceSha256': {str(p): digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
            'python': sys.executable, 'sealedHHSeedsUsed': False}
    write_new(output / 'plan.json', plan)
    write_new(output / 'plan-hash.json', {'sha256': digest(output / 'plan.json')})
    checkpoint = output / 'candidate.pt'
    metadata = train_r4(data, checkpoint, TrainConfig(epochs=5, learning_rate=.001, seed=20260926, hidden=16),
                        run_name='R4-WEIGHTED-FINAL-EPOCH-REPAIR-001')
    write_new(output / 'training.json', metadata)
    model = output / 'candidate.onnx'
    export_onnx(checkpoint, model, [item.sample for item in data.policy_samples])
    results = []
    for index, task in enumerate(tasks):
        target = output / f'{index:03d}.jsonl'
        candidate = task['policy'] != 'pure-mcts'
        print(json.dumps({'event': 'start', **task}), flush=True)
        try:
            report = run_probe(output=target, seed=task['seed'], encounter=task['encounter'],
                search_mode=task['policy'], model=model if candidate else None,
                game_dir=Path(r'D:\Steam\steamapps\common\Slay the Spire 2'),
                ritsu_root=Path(r'D:\Steam\steamapps\workshop\content\2868840\3747602295'),
                max_decisions=256, budget_ms=1000, max_simulations=50, timeout_seconds=1800,
                root_parity_output=output / f'{index:03d}.parity.jsonl' if candidate else None)
            results.append({**task, 'report': report})
            write_new(output / f'{index:03d}.complete.json', results[-1])
            if candidate:
                baseline = [json.loads(line) for line in (output / f'{index-1:03d}.jsonl').read_text(encoding='utf-8').splitlines()]
                actual = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()]
                if baseline[0]['observation'] != actual[0]['observation'] or baseline[0]['legalActions'] != actual[0]['legalActions']:
                    raise ValueError('paired opening observation or legal actions differ')
        except Exception as error:
            write_new(output / 'halted.json', {'status': 'protocol-or-infrastructure-blocked', 'task': task,
                'error': repr(error), 'completed': len(results), 'selfPlayStarted': False})
            raise
        print(json.dumps({'event': 'complete', 'task': index, 'outcome': report['outcome']}), flush=True)
    base = [r['report'] for r in results if r['policy'] == 'pure-mcts']
    cand = [r['report'] for r in results if r['policy'] != 'pure-mcts']
    bw = sum(r['outcome'] == 'win' for r in base)
    cw = sum(r['outcome'] == 'win' for r in cand)
    reasons = []
    if any(r['outcome'] == 'unresolved' for r in base + cand):
        reasons.append('unresolved evaluation pair')
    if cw < bw or (cw == bw and sum(r['valueTarget'] for r in cand) < sum(r['valueTarget'] for r in base)):
        reasons.append('candidate regresses against paired pure MCTS')
    write_new(output / 'screen.json', {'status': 'rejected' if reasons else 'engineering-screen-passed',
        'reasons': reasons, 'baselineWins': bw, 'candidateWins': cw, 'pairs': len(base),
        'championCreated': False, 'selfPlayStarted': False, 'formalPromotionGranted': False,
        'remaining': ['independent promotion coverage, including natural nested choices'] if not reasons else [],
        'planSha256': digest(output / 'plan.json'), 'modelSha256': digest(model)})


if __name__ == '__main__':
    main()
