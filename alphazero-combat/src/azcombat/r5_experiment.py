"""Evidence-bound R5 engineering experiment; never publishes a champion.

The original collection manifest is retained, including its erroneous budget
evidence claim. Admission is technical eligibility, not retrospective approval
of that claim or an independent integrity review.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path

from .experiments import _generated_scenario_bytes, checked_model, sha256
from .natural_pilot import _read_frozen_manifest, _source_snapshot
from .native_probe import run_probe, audit_probe
from .r4_admission import _capture_evidence
from .r4_training import R4AdmissionDataset, R4WeightedSample, train_r4
from .samples import read_jsonl
from .training import TrainConfig
from .export import export_onnx
from .trajectory_parity import verify_trajectory
from .versions import (FEATURE_ABI, OBSERVATION_SCHEMA_VERSION,
                       REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def ref(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': sha256(path)}


def check_ref(reference):
    path = Path(reference['path']).resolve(strict=True)
    if sha256(path) != reference['sha256']:
        raise ValueError(f'artifact hash changed: {path}')
    return path


def assign_weights(entries):
    counts = Counter((e['partition'], e['policy']) for e in entries)
    terminal = Counter((e['partition'], e['policy']) for e in entries
                       if e['outcome'] in ('win', 'loss'))
    for entry in entries:
        if entry['outcome'] not in ('win', 'loss', 'unresolved') or entry['rowCount'] < 1:
            raise ValueError('invalid outcome or row count')
        key = entry['partition'], entry['policy']
        entry['policyRowWeight'] = .5 / (counts[key] * entry['rowCount'])
        entry['valueRowWeight'] = (0 if entry['outcome'] == 'unresolved' else
                                   .5 / (terminal[key] * entry['rowCount']))


def validate_entries(entries, partitions):
    """Check the entire task matrix and recompute weights rather than trusting them."""
    groups = [partitions[key] for key in ('train', 'validation', 'finalEvaluationSealed')]
    seeds = [seed for group in groups for seed in group]
    if list(map(len, groups)) != [4, 1, 5] or len(seeds) != len(set(seeds)):
        raise ValueError('seed partition overlap or size mismatch')
    expected = {(s, e, p) for s in groups[0] + groups[1]
                for e in ('CULTISTS_NORMAL', 'LIVING_FOG_NORMAL')
                for p in ('pure-mcts', 'tree-candidate')}
    actual = {(e['seed'], e['encounter'], e['policy']) for e in entries}
    if len(entries) != 20 or actual != expected or len({e['taskId'] for e in entries}) != 20:
        raise ValueError('incomplete or duplicated task matrix')
    if len({e['trajectory']['sha256'] for e in entries}) != 20:
        raise ValueError('duplicate trajectory content')
    calculated = deepcopy(entries)
    assign_weights(calculated)
    for entry, recalculated in zip(entries, calculated, strict=True):
        partition = 'train' if entry['seed'] in groups[0] else 'validation'
        if entry['partition'] != partition:
            raise ValueError('seed assigned to wrong partition')
        for head in ('policyRowWeight', 'valueRowWeight'):
            value = entry[head]
            if not math.isfinite(value) or not math.isclose(value, recalculated[head],
                                                          rel_tol=0, abs_tol=1e-14):
                raise ValueError('trajectory weight differs from frozen rule')


def prepare(manifest_path, audit_path, checkpoint, output):
    manifest_path, audit_path = manifest_path.resolve(strict=True), audit_path.resolve(strict=True)
    manifest, audit = _read_frozen_manifest(manifest_path), read(audit_path)
    if (audit['status'] != 'complete' or audit['errors'] or audit['attempts'] != 20
            or audit['completedCombats'] != 20 or audit['manifestSha256'] != sha256(manifest_path)
            or len(audit['pairedOpenings']) != 10
            or any(pair['status'] != 'matched' for pair in audit['pairedOpenings'])):
        raise ValueError('collection has not passed complete paired protocol audit')
    root = manifest_path.parent
    behavior = Path(manifest['treeCandidate']['onnxPath'])
    if checked_model(behavior) != manifest['treeCandidate']['onnxSha256']:
        raise ValueError('behavior model identity changed')
    if read(behavior.with_suffix('.manifest.json'))['checkpointSha256'] != sha256(checkpoint):
        raise ValueError('behavior checkpoint identity changed')
    output.mkdir(parents=True, exist_ok=False)
    entries = []
    for task, audited in zip(manifest['tasks'], audit['tasks'], strict=True):
        if task['taskId'] != audited['taskId'] or len(audited['attempts']) != 1:
            raise ValueError('task/attempt correspondence differs')
        attempt = audited['attempts'][0]
        if attempt['status'] != 'complete' or attempt['acceptanceStatus'] != 'accepted':
            raise ValueError('unaccepted attempt')
        # The protocol audit covered loaded MVID/path/hash, visit counts, reward
        # captures and real outcomes. Bind ALL its evidence before reusing it.
        for relative, identity in attempt['artifacts'].items():
            path = (root / relative).resolve(strict=True)
            if not path.is_relative_to(root) or sha256(path) != identity['sha256']:
                raise ValueError('audited evidence changed or escapes collection')
        directory = root / 'attempts' / task['taskId'] / 'attempt-001'
        trajectory = directory / 'trajectory.jsonl'
        samples = read_jsonl(trajectory, require_current_search_semantics=True)
        raw = [json.loads(line) for line in trajectory.read_text(encoding='utf-8').splitlines()]
        if len(samples) != attempt['decisions'] or any(
                s.seed != task['seed'] or s.outcome != attempt['outcome']
                or s.value_target != attempt['valueTarget'] for s in samples):
            raise ValueError('trajectory labels or counts differ')
        capture = _capture_evidence(raw)
        if capture['sources'] != ['native-damage-command-v1']:
            raise ValueError('R5 requires native damage event evidence')
        for assembly in attempt['assemblies'].values():
            if sha256(Path(assembly['path'])).lower() != assembly['sha256'].lower():
                raise ValueError('audited Native assembly changed')
        parity = None
        if task['policy'] == 'tree-candidate':
            result = verify_trajectory(checkpoint, behavior, trajectory,
                                       directory / 'trajectory.root-parity.jsonl')
            parity_path = output / (task['taskId'] + '.numeric-parity.json')
            write_new(parity_path, result)
            parity = ref(parity_path)
        entries.append({**{key: task[key] for key in
                           ('taskId', 'seed', 'partition', 'encounter', 'policy')},
                        'trajectory': ref(trajectory),
                        'input': ref(root / task['generatedScenario']),
                        'rowCount': len(samples), 'outcome': attempt['outcome'],
                        'valueTarget': attempt['valueTarget'],
                        'choiceRows': attempt['choiceDecisions'],
                        'nestedChoiceRows': attempt['nestedChoiceDecisions'],
                        'captureEvidence': capture, 'numericParity': parity,
                        'modelSha256': task['requestedModelSha256'],
                        'assemblies': attempt['assemblies']})
        print(json.dumps({'event': 'admission-checked', 'taskId': task['taskId']}), flush=True)
    assign_weights(entries)
    validate_entries(entries, manifest['seedPartitions'])
    notes = {
        'format': 'azcombat.r5-evidence-limitations.v1',
        'createdAtUtc': datetime.now(timezone.utc).isoformat(),
        'originalManifest': ref(manifest_path),
        'originalBudgetFile': ref(Path(manifest['budgetEvidence']['path'])),
        'budgetClaim': 'INVALID: manually authored config labelled complete research-wave; not an executed wave',
        'historicalR3Narrative': 'unverified stale boilerplate; not admissible evidence',
        'behaviorTrainingLedgerClaim': 'original v1 string is stale; collection rows audited as reward-ledger.v2',
        'actualBudgetEvidence': ref(audit_path),
        'budgetEvidenceTiming': 'post-collection re-read of 20 actual uncapped 1000ms runs, NOT pre-collection evidence',
        'admissionScope': 'engineering training from strictly read-back natural trajectories only',
        'independentIntegrityReview': 'unavailable',
        'sourceHistory': 'original collection source verified by original protocol audit before pipeline edits',
        'noRewriting': 'original manifest, attempts, JSONL and prior evidence retained unchanged',
        'unseenSeedCaveat': 'unique new namespace; deleted historical artifacts prevent exhaustive historical inventory',
        'nestedCoverage': audit['nestedChoiceRows'],
        'formalPromotionAllowed': False,
    }
    write_new(output / 'evidence-limitations.json', notes)
    index = {'format': 'azcombat.trajectory-admission.v1', 'status': 'admitted-engineering-only',
             'manifest': ref(manifest_path), 'protocolAudit': ref(audit_path),
             'limitations': ref(output / 'evidence-limitations.json'),
             'partitions': manifest['seedPartitions'], 'entries': entries,
             'contracts': {key: manifest['contracts'][key] for key in
                           ('featureAbi', 'observationSchemaVersion', 'searchSemanticsVersion', 'rewardLedgerVersion')},
             'summary': {'tasks': len(entries), 'samples': sum(e['rowCount'] for e in entries),
                         'byOutcomeCombats': dict(Counter(e['outcome'] for e in entries)),
                         'byPolicyRows': {p: sum(e['rowCount'] for e in entries if e['policy'] == p)
                                          for p in ('pure-mcts', 'tree-candidate')},
                         'choiceRows': sum(e['choiceRows'] for e in entries),
                         'nestedChoiceRows': sum(e['nestedChoiceRows'] for e in entries)}}
    write_new(output / 'index.json', index)
    evaluation = []
    for i, seed in enumerate(manifest['seedPartitions']['finalEvaluationSealed']):
        cards = manifest['deckTemplates']['cards']['ABCDE'[i]]
        for encounter in ('CULTISTS_NORMAL', 'LIVING_FOG_NORMAL'):
            scenario = output / f'eval-{i}-{encounter}.json'
            with scenario.open('xb') as handle:
                handle.write(_generated_scenario_bytes(seed, encounter, cards))
            for policy in ('pure-mcts', 'policy-value-tree-v1'):
                evaluation.append({'taskId': f'{i:03d}-{encounter}-{policy}', 'seed': seed,
                                   'encounter': encounter, 'policy': policy, 'scenario': ref(scenario)})
    plan = {'format': 'azcombat.r5-training-evaluation-plan.v1',
            'createdAtUtc': datetime.now(timezone.utc).isoformat(), 'index': ref(output / 'index.json'),
            'limitations': ref(output / 'evidence-limitations.json'),
            'sourceSnapshot': _source_snapshot(Path(__file__).resolve().parents[3]),
            'training': {'epochs': 5, 'learningRate': .001, 'hidden': 16, 'seed': 20260926,
                         'initialization': 'fresh; no checkpoint continuation', 'selection': 'fixed-final-epoch',
                         'optimizer': 'trajectory-weighted-full-batch.v1', 'parameters': 1970,
                         'policy': 'equal behavior mass; equal trajectory mass within behavior; all legal visit labels',
                         'value': 'equal terminal trajectory mass within behavior; unresolved zero value weight',
                         'interpretation': 'realized utility under recorded subsequent behavior, not counterfactual action value'},
            'evaluation': evaluation, 'budgetMilliseconds': 1000, 'maxSimulations': None,
            'maxDecisions': 256, 'timeoutSeconds': 1800, 'numericalTolerance': 1e-5,
            'automaticRetries': 0, 'minimumSimulationRate': None,
            'gameDir': manifest['gameDir'], 'ritsuRoot': manifest['ritsuRoot'],
            'externalBuildInputs': manifest['externalBuildInputs'],
            'deckNovelty': 'reuse A-E templates; unseen evaluation seeds do not mean unseen decks',
            'gate': {'unit': '10 paired combats clustered by 5 seeds',
                     'screen': 'all audited and paired; no unresolved; candidate wins and utility sum nondecreasing per encounter',
                     'promotion': 'NEVER from this engineering run: independent integrity review and natural nested coverage still required'},
            'stopping': 'first protocol/infrastructure error; retain all attempts; no tuning or automatic retry',
            'evaluationUse': 'once-only final fixed candidate comparison; no model selection or tuning',
            'championCreated': False, 'selfPlayAllowed': False}
    write_new(output / 'plan.json', plan)
    write_new(output / 'plan.sha256.json', ref(output / 'plan.json'))
    return index['summary']


def load_index(path):
    index = read(path)
    if index.get('format') != 'azcombat.trajectory-admission.v1' or index.get('status') != 'admitted-engineering-only':
        raise ValueError('unadmitted index')
    for key in ('manifest', 'protocolAudit', 'limitations'):
        check_ref(index[key])
    contracts = dict(featureAbi=FEATURE_ABI, observationSchemaVersion=OBSERVATION_SCHEMA_VERSION,
                     searchSemanticsVersion=SEARCH_SEMANTICS_VERSION, rewardLedgerVersion=REWARD_LEDGER_VERSION)
    if index['contracts'] != contracts:
        raise ValueError('index ABI differs')
    manifest = read(check_ref(index['manifest']))
    if index['partitions'] != manifest['seedPartitions']:
        raise ValueError('index split differs from original collection')
    validate_entries(index['entries'], index['partitions'])
    loaded = {'train': [], 'validation': []}
    for entry in index['entries']:
        check_ref(entry['input'])
        if entry['numericParity'] is not None:
            check_ref(entry['numericParity'])
        samples = read_jsonl(check_ref(entry['trajectory']), require_current_search_semantics=True)
        if len(samples) != entry['rowCount']:
            raise ValueError('sample count differs')
        for sample in samples:
            if sample.seed != entry['seed'] or sample.outcome != entry['outcome'] or sample.value_target != entry['valueTarget']:
                raise ValueError('sample identity/label differs')
            loaded[entry['partition']].append(R4WeightedSample(
                sample, entry['taskId'], entry['partition'], entry['policy'], entry['outcome'],
                entry['policyRowWeight'], entry['valueRowWeight']))
    if sum(map(len, loaded.values())) != index['summary']['samples']:
        raise ValueError('index total differs')
    return R4AdmissionDataset(path, tuple(loaded['train']), tuple(loaded['validation']),
                              tuple(index['partitions']['finalEvaluationSealed']))


def check_plan(path):
    check_ref(read(path.with_name('plan.sha256.json')))
    plan = read(path)
    if plan['sourceSnapshot'] != _source_snapshot(Path(__file__).resolve().parents[3]):
        raise ValueError('experiment source changed after freeze')
    check_ref(plan['index'])
    check_ref(plan['limitations'])
    for identity in plan['externalBuildInputs'].values():
        check_ref(identity)
    return plan


def train(plan_path):
    plan = check_plan(plan_path)
    root = plan_path.parent
    if (root / 'training-started.json').exists():
        raise ValueError('training already attempted; retain original attempt')
    data = load_index(check_ref(plan['index']))
    write_new(root / 'training-started.json', {'plan': ref(plan_path),
              'startedAtUtc': datetime.now(timezone.utc).isoformat()})
    try:
        metadata = train_r4(data, root / 'candidate.pt',
                            TrainConfig(epochs=5, learning_rate=.001, hidden=16, seed=20260926),
                            run_name='R5-ENGINEERING-FIXED-FINAL-001')
        write_new(root / 'training.json', metadata)
        exported = export_onnx(root / 'candidate.pt', root / 'candidate.onnx',
                               [item.sample for item in data.policy_samples])
        write_new(root / 'candidate-lock.json', {'plan': ref(plan_path),
                  'checkpoint': ref(root / 'candidate.pt'), 'onnx': ref(root / 'candidate.onnx'),
                  'manifest': ref(root / 'candidate.manifest.json')})
        return {'status': 'trained', 'parameterCount': metadata['parameterCount'],
                'trainRows': metadata['trainRows'], 'validationRows': metadata['validationRows']}
    except Exception as error:
        write_new(root / 'training-failed.json', {'error': repr(error)})
        raise


def screen_pairs(results):
    pairs = {}
    for task in results:
        key = task['seed'], task['encounter']
        pair = pairs.setdefault(key, {})
        if task['policy'] in pair:
            raise ValueError('duplicate evaluation task')
        pair[task['policy']] = task
    reasons = []
    for key, pair in pairs.items():
        if set(pair) != {'pure-mcts', 'policy-value-tree-v1'}:
            raise ValueError('incomplete evaluation pair')
        if pair['pure-mcts']['opening'] != pair['policy-value-tree-v1']['opening']:
            raise ValueError('paired opening mismatch')
        if any(item['report']['outcome'] == 'unresolved' for item in pair.values()):
            reasons.append(f'unresolved pair: {key}')
    outcomes = {}
    for encounter in sorted({key[1] for key in pairs}):
        scores = {}
        for policy in ('pure-mcts', 'policy-value-tree-v1'):
            reports = [pair[policy]['report'] for key, pair in pairs.items() if key[1] == encounter]
            scores[policy] = {'wins': sum(r['outcome'] == 'win' for r in reports),
                              'losses': sum(r['outcome'] == 'loss' for r in reports),
                              'unresolved': sum(r['outcome'] == 'unresolved' for r in reports),
                              'utilitySum': sum(r['valueTarget'] for r in reports)}
        base, candidate = scores['pure-mcts'], scores['policy-value-tree-v1']
        if candidate['wins'] < base['wins'] or candidate['utilitySum'] < base['utilitySum']:
            reasons.append(f'candidate regresses: {encounter}')
        outcomes[encounter] = scores
    return {'status': 'rejected' if reasons else 'engineering-screen-passed', 'reasons': reasons,
            'pairs': len(pairs), 'byEncounterPolicy': outcomes, 'formalPromotionGranted': False,
            'championCreated': False, 'selfPlayStarted': False}


def evaluate(plan_path):
    plan = check_plan(plan_path)
    root = plan_path.parent
    lock = read(root / 'candidate-lock.json')
    for identity in lock.values():
        check_ref(identity)
    model, checkpoint = check_ref(lock['onnx']), check_ref(lock['checkpoint'])
    results = []
    for task in plan['evaluation']:
        check_plan(plan_path)
        directory = root / 'evaluation' / task['taskId']
        complete = directory / 'complete.json'
        if directory.exists():
            if not complete.exists():
                raise ValueError(f'previous unfinished/failed attempt; no automatic retry: {directory}')
            saved = read(complete)
            for identity in saved['artifacts'].values():
                check_ref(identity)
            if saved['task'] != task:
                raise ValueError('saved task changed')
            results.append(saved)
            continue
        directory.mkdir(parents=True)
        write_new(directory / 'attempt.json', {'task': task, 'plan': ref(plan_path),
                  'startedAtUtc': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'event': 'evaluation-start', 'taskId': task['taskId']}), flush=True)
        trajectory, trace = directory / 'trajectory.jsonl', directory / 'root-parity.jsonl'
        candidate = task['policy'] != 'pure-mcts'
        try:
            report = run_probe(output=trajectory, seed=task['seed'], encounter=task['encounter'],
                               search_mode=task['policy'], model=model if candidate else None,
                               game_dir=Path(plan['gameDir']), ritsu_root=Path(plan['ritsuRoot']),
                               max_decisions=plan['maxDecisions'], budget_ms=plan['budgetMilliseconds'],
                               max_simulations=plan['maxSimulations'], timeout_seconds=plan['timeoutSeconds'],
                               root_parity_output=trace if candidate else None,
                               generated_scenario=check_ref(task['scenario']))
            parity = verify_trajectory(checkpoint, model, trajectory, trace) if candidate else None
            # Re-read emitted samples and current state against the actual callback.
            raw = [json.loads(line) for line in trajectory.read_text(encoding='utf-8').splitlines()]
            capture = _capture_evidence(raw)
            if capture['sources'] != ['native-damage-command-v1']:
                raise ValueError('evaluation lost native damage evidence')
            opening = {key: raw[0][key] for key in ('observation', 'stateKey', 'legalActions')}
            opening['generatedDeck'] = raw[0]['provenance']['generatedDeck']
            result = {'task': task, **task, 'report': report, 'opening': opening,
                      'numericParity': parity, 'captureEvidence': capture,
                      'nestedChoiceRows': sum(m['choiceLayer'] > 1 for m in raw[0]['provenance']['decisionMetrics']),
                      'artifacts': {file.name: ref(file) for file in directory.iterdir() if file.is_file()}}
            if candidate:
                previous = results[-1]
                if (previous['seed'], previous['encounter'], previous['policy']) != (
                        task['seed'], task['encounter'], 'pure-mcts') or previous['opening'] != opening:
                    raise ValueError('paired opening mismatch')
            write_new(complete, result)
            results.append(result)
            print(json.dumps({'event': 'evaluation-complete', 'taskId': task['taskId'],
                              'outcome': report['outcome']}), flush=True)
        except Exception as error:
            write_new(directory / 'failure.json', {'error': repr(error), 'task': task,
                      'finishedAtUtc': datetime.now(timezone.utc).isoformat()})
            raise
    if len(results) != len(plan['evaluation']):
        raise ValueError('evaluation incomplete')
    summary = screen_pairs(results)
    summary.update({'plan': ref(plan_path), 'candidate': ref(model),
                    'decisions': sum(r['report']['samples'] for r in results),
                    'choiceRows': sum(r['report']['choiceRows'] for r in results),
                    'nestedChoiceRows': sum(r['nestedChoiceRows'] for r in results),
                    'independentReview': 'unavailable', 'collectionLimitations': plan['limitations'],
                    'attempts': len(results), 'retries': 0,
                    'completedAtUtc': datetime.now(timezone.utc).isoformat()})
    write_new(root / 'evaluation-summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'evaluate'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        if not all((args.manifest, args.audit, args.checkpoint, args.output)):
            parser.error('prepare requires manifest, audit, checkpoint, output')
        result = prepare(args.manifest, args.audit, args.checkpoint, args.output.resolve())
    else:
        if args.plan is None:
            parser.error('train/evaluate requires plan')
        result = (train if args.command == 'train' else evaluate)(args.plan.resolve(strict=True))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
