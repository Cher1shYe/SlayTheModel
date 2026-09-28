"""Frozen million-parameter teacher-data experiment, separate from promotion.

collect -> strict all-task admission -> trajectory-weighted CPU training -> ONNX.
Never uses held-out evaluation seeds, a champion, or model-generated teacher data.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import time

import torch

from .experiments import _generated_scenario_bytes, sha256
from .natural_pilot import _source_snapshot, _external_dependencies
from .native_probe import run_probe, audit_probe
from .r4_admission import _capture_evidence
from .r4_training import R4WeightedSample, weighted_epoch, _weighted_metrics
from .r5_experiment import read, ref, check_ref, write_new
from .samples import read_jsonl
from .training import DeepSetsPolicyValue
from .export import export_onnx
from .versions import (CHECKPOINT_FORMAT, FEATURE_ABI, OBSERVATION_SCHEMA_VERSION,
                       SEARCH_SEMANTICS_VERSION, REWARD_LEDGER_VERSION)

CONTINUATION_TASK = 'train-020-LIVING_FOG_NORMAL'
CONTINUATION_FILE = 'continuation-001.json'
GENERAL_CONTINUATION_FILE = 'continuation-002.json'
GENERAL_CONTINUATION_POSITION = 57


def now():
    return datetime.now(timezone.utc).isoformat()


def task_matrix(partitions):
    seeds = [s for values in partitions.values() for s in values]
    if len(seeds) != len(set(seeds)) or set(partitions) != {'train', 'validation', 'evaluation'}:
        raise ValueError('seed partition overlap or missing partition')
    tasks = []
    for partition in ('train', 'validation'):
        for i, seed in enumerate(partitions[partition]):
            for encounter in ('CULTISTS_NORMAL', 'LIVING_FOG_NORMAL'):
                tasks.append({'taskId': f'{partition}-{i:03d}-{encounter}', 'partition': partition,
                              'seed': seed, 'encounter': encounter, 'deckTemplate': 'ABCDE'[i % 5]})
    return tasks


def weighted_rows(entries, partitions):
    if any(e['partition'] not in ('train', 'validation') for e in entries):
        raise ValueError('invalid training partition')
    expected = {(t['seed'], t['encounter']) for t in task_matrix(partitions)}
    if len(entries) != len(expected) or {(e['seed'], e['encounter']) for e in entries} != expected:
        raise ValueError('incomplete or duplicate collection matrix')
    if len({e['trajectory']['sha256'] for e in entries}) != len(entries):
        raise ValueError('duplicate trajectory bytes')
    counts = Counter(e['partition'] for e in entries)
    terminal = Counter(e['partition'] for e in entries if e['outcome'] in ('win', 'loss'))
    result = {'train': [], 'validation': []}
    for entry in entries:
        partition = entry['partition']
        if entry['seed'] not in partitions[partition] or entry['outcome'] not in ('win', 'loss', 'unresolved'):
            raise ValueError('seed/outcome differs from partition')
        samples = read_jsonl(check_ref(entry['trajectory']), require_current_search_semantics=True)
        if len(samples) != entry['rowCount'] or not samples:
            raise ValueError('row count differs')
        pw = 1 / (counts[partition] * len(samples))
        vw = 0 if entry['outcome'] == 'unresolved' else 1 / (terminal[partition] * len(samples))
        for sample in samples:
            if sample.seed != entry['seed'] or sample.outcome != entry['outcome'] or sample.value_target != entry['valueTarget']:
                raise ValueError('sample outcome/seed/value differs')
            result[partition].append(R4WeightedSample(sample, entry['taskId'], partition,
                                                      'pure-mcts', sample.outcome, pw, vw))
    for partition, rows in result.items():
        if not rows or not terminal[partition] or not math.isclose(sum(r.policy_weight for r in rows), 1, abs_tol=1e-9):
            raise ValueError('missing trajectory/head mass')
        if not math.isclose(sum(r.value_weight for r in rows), 1, abs_tol=1e-9):
            raise ValueError('invalid terminal value mass')
    return result


def freeze(output, game, ritsu, prior_audit):
    repo = Path(__file__).resolve().parents[3]
    if read(prior_audit)['status'] != 'rejected':
        raise ValueError('R5 final rejected evaluation evidence required')
    partitions = {
        'train': [f'AZ-R6-1M-20260927-T{i:02d}' for i in range(40)],
        'validation': [f'AZ-R6-1M-20260927-V{i:02d}' for i in range(10)],
        'evaluation': [f'AZ-R6-1M-20260927-H{i:02d}' for i in range(10)]}
    deck_path = repo / 'alphazero-combat/configs/teacher-tree-r3-decks.json'
    decks = read(deck_path)['templates']
    tasks = task_matrix(partitions)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'inputs').mkdir()
    for task in tasks:
        path = output / 'inputs' / (task['taskId'] + '.json')
        with path.open('xb') as handle:
            handle.write(_generated_scenario_bytes(task['seed'], task['encounter'],
                                                   decks[task['deckTemplate']]['characterCards']))
        task['scenario'] = ref(path)
    model = DeepSetsPolicyValue(448)
    parameters = sum(p.numel() for p in model.parameters())
    if parameters != 1022786:
        raise ValueError('million-parameter architecture identity differs')
    plan = {'format': 'azcombat.large-teacher-plan.v1', 'createdAtUtc': now(),
            'purpose': 'engineering collection and training only; no superiority or promotion claim',
            'partitions': partitions, 'tasks': tasks, 'deckTemplates': ref(deck_path),
            'deckNovelty': 'historical A-E templates reused; new seeds are not new decks',
            'seedHistory': 'new namespace; deleted historic artifacts preclude exhaustive inventory',
            'gameDir': str(game.resolve()), 'ritsuRoot': str(ritsu.resolve()),
            'externalBuildInputs': _external_dependencies(game, ritsu),
            'sourceSnapshot': _source_snapshot(repo), 'priorR5Evaluation': ref(prior_audit),
            'behavior': 'pure-mcts', 'oldDataIncluded': False,
            'budget': {'kind': 'declared-configuration-not-completed-wave', 'milliseconds': 1000,
                       'maxSimulations': None, 'maxDecisions': 256, 'timeoutSeconds': 1800},
            'contracts': dict(featureAbi=FEATURE_ABI, observationSchemaVersion=OBSERVATION_SCHEMA_VERSION,
                              searchSemanticsVersion=SEARCH_SEMANTICS_VERSION, rewardLedgerVersion=REWARD_LEDGER_VERSION),
            'training': {'parameters': parameters, 'hidden': 448, 'epochs': 50,
                         'learningRate': .001, 'seed': 20260927, 'cpuThreads': 1,
                         'optimizer': 'Adam; one trajectory-weighted full-batch gradient step per epoch',
                         'initialization': 'fresh', 'selection': 'fixed-final-epoch',
                         'policyWeights': 'equal trajectory mass, including unresolved; legal visit distributions only',
                         'valueWeights': 'equal terminal trajectory mass; unresolved zero (retained in index)',
                         'valueMeaning': 'realized utility under pure-MCTS future behavior, not counterfactual action value',
                         'minimumTrainRows': 1000, 'minimumValidationRows': 100,
                         'validationUse': 'report-only; no epoch selection',
                         'loss': 'unchanged policy cross-entropy plus utility MSE'},
            'numericalTolerance': 1e-5, 'collectAttemptsPerTask': 1,
            'stop': 'first protocol or infrastructure failure; preserve all files; no automatic retries',
            'evaluationSeedsRun': False, 'championAllowed': False, 'selfPlayAllowed': False,
            'maximumStages': len(tasks), 'estimatedStageDiskGiB': len(tasks),
            'expectedCoverageLimitations': ['two encounters only', 'LIVING_FOG starts with one monster',
                                           'natural deaths/nested choices not guaranteed',
                                           'million-parameter model may overfit this small dataset'],
            'independentIntegrityReview': 'unavailable'}
    write_new(output / 'plan.json', plan)
    write_new(output / 'plan.sha256.json', ref(output / 'plan.json'))
    return {'tasks': len(tasks), 'parameters': parameters, 'plan': str(output / 'plan.json')}


def _root_ref(root, identity):
    path = check_ref(identity)
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'evidence escapes experiment root: {path}')
    return path


def _check_probe_configuration(probe, task, plan):
    expected = {'seed': task['seed'], 'encounter': task['encounter'],
                'generatedScenarioPath': str(check_ref(task['scenario'])),
                'generatedScenarioSha256': task['scenario']['sha256'],
                'requestedSearchMode': 'pure-mcts', 'modelSha256': None,
                'fixtureCards': None, 'forceCard': None, 'initialHp': None,
                'maxDecisions': plan['budget']['maxDecisions'],
                'budgetMilliseconds': plan['budget']['milliseconds'],
                'maxSimulations': plan['budget']['maxSimulations'],
                'timeoutSeconds': plan['budget']['timeoutSeconds'],
                'regressionOnly': False}
    if any(probe.get(key) != value for key, value in expected.items()):
        raise ValueError(f'probe configuration differs from frozen task: {task["taskId"]}')


def _check_completed(root, plan, task, directory, *, retry=False):
    attempt = read(directory / 'attempt.json')
    if (attempt['task'] != task or attempt['plan'] != ref(root / 'plan.json')
            or bool(attempt.get('retry', False)) != retry):
        raise ValueError(f'attempt differs from frozen task: {task["taskId"]}')
    result = read(directory / 'complete.json')
    if result['task'] != task:
        raise ValueError(f'completion differs from frozen task: {task["taskId"]}')
    for identity in result['artifacts'].values():
        _root_ref(root, identity)
    probe = read(directory / 'trajectory.probe.json')
    _check_probe_configuration(probe, task, plan)
    if probe.get('status') != 'complete':
        raise ValueError(f'completed task has noncomplete probe: {task["taskId"]}')
    checked = audit_probe(directory / 'trajectory.jsonl', expected=probe)
    if checked != {key: result['audit'][key] for key in checked}:
        raise ValueError(f'strict audit differs from completion: {task["taskId"]}')
    raw = [json.loads(line) for line in (directory / 'trajectory.jsonl').read_text(encoding='utf-8').splitlines()]
    if _capture_evidence(raw) != result['captureEvidence']:
        raise ValueError(f'damage capture differs from completion: {task["taskId"]}')
    return result, checked


def _interrupted_evidence(root, plan, task):
    directory = root / 'collection' / task['taskId']
    if (directory / 'complete.json').exists() or (directory / 'trajectory.jsonl').exists():
        raise ValueError('interrupted task unexpectedly has completed trajectory')
    attempt_path = directory / 'attempt.json'
    attempt = read(attempt_path)
    if attempt['task'] != task or attempt['plan'] != ref(root / 'plan.json') or attempt.get('retry', False):
        raise ValueError('interrupted attempt differs from frozen task')
    probe_path = directory / 'trajectory.probe.json'
    probe = read(probe_path)
    _check_probe_configuration(probe, task, plan)
    if probe.get('status') != 'started':
        raise ValueError('interrupted probe is not in started state')
    failure_path = directory / 'failure.json'
    failure = read(failure_path)
    if (failure.get('taskId') != task['taskId']
            or failure.get('classification') != 'infrastructure-interrupted-parent-process'
            or failure.get('preservedProbeStatus') != 'started'):
        raise ValueError('interrupted attempt classification differs')
    stage = directory / 'trajectory.stage'
    stage_files = {'stdout': stage / 'stdout.txt', 'stderr': stage / 'stderr.txt',
                   'releaseInfo': stage / 'release_info.json'}
    stage_files.update({name: stage / 'data_NativeWorker_windows_x86_64' / name
                        for name in ('NativeWorker.dll', 'SlayTheModel.Search.dll', 'CombatSolver.dll')})
    if 'SLAY_WORKER_READY' not in stage_files['stdout'].read_text(encoding='utf-8'):
        raise ValueError('interrupted stage lacks worker-ready evidence')
    return {'taskId': task['taskId'], 'attempt': ref(attempt_path), 'probe': ref(probe_path),
            'failure': ref(failure_path), 'stageFiles': {name: ref(path) for name, path in stage_files.items()},
            'classificationProvenance': 'post-hoc infrastructure classification; failure.json is not a NativeWorker event',
            'failureRecordedAtUtc': datetime.fromtimestamp(failure_path.stat().st_mtime, timezone.utc).isoformat()}


def _load_frozen_plan(root):
    path = _root_ref(root, read(root / 'plan.sha256.json'))
    if path != (root / 'plan.json').resolve():
        raise ValueError('plan identity points outside frozen plan')
    plan = read(path)
    if plan['format'] != 'azcombat.large-teacher-plan.v1' or len(plan['tasks']) != 100:
        raise ValueError('plan format or task count differs')
    check_ref(plan['deckTemplates'])
    check_ref(plan['priorR5Evaluation'])
    for identity in plan['externalBuildInputs'].values():
        check_ref(identity)
    expected = task_matrix(plan['partitions'])
    if [{key: task[key] for key in entry} for task, entry in zip(plan['tasks'], expected, strict=True)] != expected:
        raise ValueError('frozen seed/deck/encounter matrix differs')
    for task in plan['tasks']:
        _root_ref(root, task['scenario'])
    return plan


def load_continuation(root, plan, *, require_current_source=True):
    path = _root_ref(root, read(root / 'continuation-001.sha256.json'))
    if path != (root / CONTINUATION_FILE).resolve():
        raise ValueError('continuation identity differs')
    continuation = read(path)
    if (continuation['format'] != 'azcombat.large-teacher-continuation.v1'
            or continuation['originalPlan'] != ref(root / 'plan.json')
            or continuation['originalSourceSnapshot'] != plan['sourceSnapshot']
            or (require_current_source and continuation['continuationSourceSnapshot'] !=
                _source_snapshot(Path(__file__).resolve().parents[3]))
            or continuation['retryTaskId'] != CONTINUATION_TASK
            or continuation['retryDirectory'] != 'retry-001'
            or continuation['retryLimit'] != 1
            or continuation['automaticRetriesForOtherTasks'] != 0
            or continuation['noTrainingInCollectionCommand'] is not True
            or continuation['frozenConfiguration'] != {key: plan[key] for key in
                                                          ('partitions', 'behavior', 'budget', 'contracts', 'training')}
            or len(continuation['completedOriginalAttempts']) != 41):
        raise ValueError('continuation differs from frozen evidence or current source')
    if plan['tasks'][41]['taskId'] != CONTINUATION_TASK:
        raise ValueError('interrupted task position differs from frozen matrix')
    for task, evidence in zip(plan['tasks'][:41], continuation['completedOriginalAttempts'], strict=True):
        directory = root / 'collection' / task['taskId']
        if (evidence['taskId'] != task['taskId']
                or _root_ref(root, evidence['attempt']) != (directory / 'attempt.json').resolve()
                or _root_ref(root, evidence['complete']) != (directory / 'complete.json').resolve()):
            raise ValueError('original completed attempt evidence differs')
        for identity in evidence['artifacts'].values():
            _root_ref(root, identity)
    if continuation['interruptedOriginal'] != _interrupted_evidence(root, plan, plan['tasks'][41]):
        raise ValueError('interrupted original evidence differs')
    return continuation


def _completed_evidence(root, plan, task, directory, *, retry=False):
    result, _ = _check_completed(root, plan, task, directory, retry=retry)
    return {'taskId': task['taskId'], 'attempt': ref(directory / 'attempt.json'),
            'complete': ref(directory / 'complete.json'), 'artifacts': result['artifacts'],
            'retry': retry}


def _failed_evidence(root, plan, task, directory, *, retry=False):
    if (directory / 'complete.json').exists():
        raise ValueError(f'failed attempt has completion: {task["taskId"]}')
    attempt = read(directory / 'attempt.json')
    if (attempt['task'] != task or attempt['plan'] != ref(root / 'plan.json')
            or bool(attempt.get('retry', False)) != retry):
        raise ValueError(f'failed attempt differs from frozen task: {task["taskId"]}')
    failure = read(directory / 'failure.json')
    if failure.get('task') != task or not failure.get('error'):
        raise ValueError(f'failure marker differs from frozen task: {task["taskId"]}')
    probe_path = directory / 'trajectory.probe.json'
    probe_status = None
    if probe_path.exists():
        probe = read(probe_path)
        _check_probe_configuration(probe, task, plan)
        probe_status = probe.get('status')
        if probe_status not in ('started', 'failed', 'complete'):
            raise ValueError(f'unknown failed probe status: {task["taskId"]}')
    files = {str(path.relative_to(directory)): ref(path)
             for path in directory.iterdir() if path.is_file()}
    stage = directory / 'trajectory.stage'
    if stage.exists():
        for relative in ('stdout.txt', 'stderr.txt', 'release_info.json', 'stage_provenance.json',
                         'NativeWorker.exe', 'data_NativeWorker_windows_x86_64/NativeWorker.dll',
                         'data_NativeWorker_windows_x86_64/SlayTheModel.Search.dll',
                         'data_NativeWorker_windows_x86_64/CombatSolver.dll'):
            path = stage / relative
            if path.exists():
                files[str(path.relative_to(directory))] = ref(path)
    classification = ('infrastructure-timeout' if failure['error'].startswith('TimeoutExpired(')
                      else 'failure-unclassified')
    return {'taskId': task['taskId'], 'files': files, 'probeStatus': probe_status,
            'error': failure['error'], 'classification': classification, 'retry': retry}


def _check_evidence(root, evidence, expected):
    if evidence != expected:
        raise ValueError('frozen attempt evidence differs')
    for identity in evidence['files'].values() if 'files' in evidence else evidence['artifacts'].values():
        _root_ref(root, identity)
    for name in ('attempt', 'complete'):
        if name in evidence:
            _root_ref(root, evidence[name])


def _verify_completed_evidence(root, plan, task, directory, evidence, *, retry=False):
    if (evidence.get('taskId') != task['taskId'] or evidence.get('retry') != retry
            or _root_ref(root, evidence['attempt']) != (directory / 'attempt.json').resolve()
            or _root_ref(root, evidence['complete']) != (directory / 'complete.json').resolve()):
        raise ValueError('frozen completed attempt identity differs')
    attempt = read(directory / 'attempt.json')
    result = read(directory / 'complete.json')
    if (attempt.get('task') != task or attempt.get('plan') != ref(root / 'plan.json')
            or bool(attempt.get('retry', False)) != retry or result.get('task') != task
            or result.get('artifacts') != evidence.get('artifacts')):
        raise ValueError('frozen completed attempt contents differ')
    for identity in evidence['artifacts'].values():
        _root_ref(root, identity)


def load_general_continuation(root, plan):
    path = _root_ref(root, read(root / 'continuation-002.sha256.json'))
    if path != (root / GENERAL_CONTINUATION_FILE).resolve():
        raise ValueError('general continuation identity differs')
    continuation = read(path)
    first = load_continuation(root, plan, require_current_source=False)
    expected_config = {key: plan[key] for key in ('partitions', 'behavior', 'budget', 'contracts', 'training')}
    if (continuation.get('format') != 'azcombat.large-teacher-continuation.v2'
            or continuation.get('originalPlan') != ref(root / 'plan.json')
            or continuation.get('firstContinuation') != ref(root / CONTINUATION_FILE)
            or continuation.get('firstContinuationHash') != ref(root / 'continuation-001.sha256.json')
            or continuation.get('originalSourceSnapshot') != plan['sourceSnapshot']
            or continuation.get('firstContinuationSourceSnapshot') != first['continuationSourceSnapshot']
            or continuation.get('continuationSourceSnapshot') != _source_snapshot(Path(__file__).resolve().parents[3])
            or continuation.get('frozenConfiguration') != expected_config
            or continuation.get('retryDirectory') != 'retry-001'
            or continuation.get('maximumAttemptsPerTask') != 2
            or continuation.get('allowFailedAttemptRetry') is not True
            or continuation.get('noTrainingInCollectionCommand') is not True
            or len(continuation.get('completedPriorAttempts', [])) != GENERAL_CONTINUATION_POSITION
            or plan['tasks'][GENERAL_CONTINUATION_POSITION]['taskId'] !=
            continuation.get('failedPriorAttempt', {}).get('taskId')):
        raise ValueError('general continuation differs from frozen evidence or current source')
    for position, evidence in enumerate(continuation['completedPriorAttempts']):
        task = plan['tasks'][position]
        directory = root / 'collection' / task['taskId']
        if task['taskId'] == CONTINUATION_TASK:
            directory /= 'retry-001'
        _verify_completed_evidence(root, plan, task, directory, evidence,
                                   retry=task['taskId'] == CONTINUATION_TASK)
    task = plan['tasks'][GENERAL_CONTINUATION_POSITION]
    expected = _failed_evidence(root, plan, task, root / 'collection' / task['taskId'])
    _check_evidence(root, continuation['failedPriorAttempt'], expected)
    return continuation


def load_plan(root, *, use_continuation=False):
    plan = _load_frozen_plan(root)
    if use_continuation:
        if (root / GENERAL_CONTINUATION_FILE).exists() or (root / 'continuation-002.sha256.json').exists():
            load_general_continuation(root, plan)
        else:
            load_continuation(root, plan)
    elif plan['sourceSnapshot'] != _source_snapshot(Path(__file__).resolve().parents[3]):
        raise ValueError('source changed after preregistration')
    return plan


def amend_general_retry(root):
    plan = _load_frozen_plan(root)
    if (root / GENERAL_CONTINUATION_FILE).exists() or (root / 'continuation-002.sha256.json').exists() or (root / 'index.json').exists():
        raise ValueError('general continuation or admission already exists')
    first = load_continuation(root, plan, require_current_source=False)
    if first['retryTaskId'] != plan['tasks'][41]['taskId']:
        raise ValueError('first continuation retry task differs')
    collection = root / 'collection'
    if {entry.name for entry in collection.iterdir()} != {task['taskId'] for task in plan['tasks'][:58]}:
        raise ValueError('collection does not contain exactly the first 58 task directories')
    completed = []
    for task in plan['tasks'][:GENERAL_CONTINUATION_POSITION]:
        directory = collection / task['taskId']
        if task['taskId'] == CONTINUATION_TASK:
            directory /= 'retry-001'
        elif (directory / 'retry-001').exists():
            raise ValueError('unexpected retry before general continuation')
        completed.append(_completed_evidence(root, plan, task, directory,
                                             retry=task['taskId'] == CONTINUATION_TASK))
    failed_task = plan['tasks'][GENERAL_CONTINUATION_POSITION]
    failed_directory = collection / failed_task['taskId']
    if (failed_directory / 'retry-001').exists():
        raise ValueError('second failed task already retried before continuation was frozen')
    failed = _failed_evidence(root, plan, failed_task, failed_directory)
    continuation = {'format': 'azcombat.large-teacher-continuation.v2',
                    'createdAtUtc': now(),
                    'reason': 'user-authorized same-R6 bounded retry of all failed tasks',
                    'originalPlan': ref(root / 'plan.json'),
                    'firstContinuation': ref(root / CONTINUATION_FILE),
                    'firstContinuationHash': ref(root / 'continuation-001.sha256.json'),
                    'originalSourceSnapshot': plan['sourceSnapshot'],
                    'firstContinuationSourceSnapshot': first['continuationSourceSnapshot'],
                    'continuationSourceSnapshot': _source_snapshot(Path(__file__).resolve().parents[3]),
                    'completedPriorAttempts': completed, 'failedPriorAttempt': failed,
                    'frozenConfiguration': {key: plan[key] for key in
                                            ('partitions', 'behavior', 'budget', 'contracts', 'training')},
                    'retryDirectory': 'retry-001', 'maximumAttemptsPerTask': 2,
                    'allowFailedAttemptRetry': True, 'noTrainingInCollectionCommand': True}
    write_new(root / GENERAL_CONTINUATION_FILE, continuation)
    write_new(root / 'continuation-002.sha256.json', ref(root / GENERAL_CONTINUATION_FILE))
    return {'continuation': str(root / GENERAL_CONTINUATION_FILE),
            'completedPriorAttempts': len(completed), 'failedTask': failed_task['taskId']}


def amend_resume(root):
    plan = _load_frozen_plan(root)
    if (root / CONTINUATION_FILE).exists() or (root / 'continuation-001.sha256.json').exists() or (root / 'index.json').exists():
        raise ValueError('continuation or admission already exists')
    collection = root / 'collection'
    expected_directories = {task['taskId'] for task in plan['tasks'][:42]}
    if {entry.name for entry in collection.iterdir()} != expected_directories:
        raise ValueError('collection does not contain exactly the first 42 task directories')
    completed = []
    for task in plan['tasks'][:41]:
        directory = collection / task['taskId']
        result, _ = _check_completed(root, plan, task, directory)
        completed.append({'taskId': task['taskId'], 'attempt': ref(directory / 'attempt.json'),
                          'complete': ref(directory / 'complete.json'), 'artifacts': result['artifacts']})
    interrupted = _interrupted_evidence(root, plan, plan['tasks'][41])
    if (collection / CONTINUATION_TASK / 'retry-001').exists():
        raise ValueError('retry already started before continuation was frozen')
    continuation = {'format': 'azcombat.large-teacher-continuation.v1', 'createdAtUtc': now(),
                    'reason': 'user-authorized same-directory continuation after infrastructure interruption',
                    'originalPlan': ref(root / 'plan.json'),
                    'originalSourceSnapshot': plan['sourceSnapshot'],
                    'continuationSourceSnapshot': _source_snapshot(Path(__file__).resolve().parents[3]),
                    'completedOriginalAttempts': completed, 'interruptedOriginal': interrupted,
                    'retryTaskId': CONTINUATION_TASK, 'retryDirectory': 'retry-001',
                    'retryLimit': 1, 'automaticRetriesForOtherTasks': 0,
                    'frozenConfiguration': {key: plan[key] for key in
                                            ('partitions', 'behavior', 'budget', 'contracts', 'training')},
                    'noTrainingInCollectionCommand': True}
    write_new(root / CONTINUATION_FILE, continuation)
    write_new(root / 'continuation-001.sha256.json', ref(root / CONTINUATION_FILE))
    return {'continuation': str(root / CONTINUATION_FILE), 'completedOriginalAttempts': len(completed),
            'interruptedTask': CONTINUATION_TASK}


def _attempt_counts(entries, attempts, continuation):
    retries = sum(attempt.get('retry', False) for attempt in attempts)
    failures = sum(attempt['status'] != 'complete' for attempt in attempts)
    if len(entries) != 100:
        raise ValueError('attempt ledger does not contain the frozen combat matrix')
    if continuation and continuation.get('format') == 'azcombat.large-teacher-continuation.v2':
        expected_retries = failures
        if (len(attempts) != 100 + failures or retries != expected_retries
                or failures < 2 or any(attempt['status'] not in
                                       ('complete', 'failed', 'infrastructure-interrupted',
                                        'infrastructure-timeout')
                                       for attempt in attempts)):
            raise ValueError('attempt ledger does not match general continuation')
    elif (len(attempts) != (101 if continuation else 100)
          or retries != int(continuation is not None)
          or failures != int(continuation is not None)):
        raise ValueError('attempt ledger does not match frozen continuation')
    return len(attempts), retries, failures


def _attempt_ledger(root, plan, continuation):
    ledger = []
    for task in plan['tasks']:
        directory = root / 'collection' / task['taskId']
        retry_directory = directory / 'retry-001'
        if (directory / 'complete.json').exists():
            if retry_directory.exists() or (directory / 'failure.json').exists():
                raise ValueError(f'completed task has retry or failure marker: {task["taskId"]}')
            _check_completed(root, plan, task, directory)
            selected = directory
            retry = False
        else:
            if continuation is None:
                raise ValueError(f'unapproved failed original attempt: {task["taskId"]}')
            if task['taskId'] == CONTINUATION_TASK:
                if continuation.get('format') == 'azcombat.large-teacher-continuation.v2':
                    first = load_continuation(root, plan, require_current_source=False)
                else:
                    first = continuation
                evidence = first['interruptedOriginal']
                if evidence != _interrupted_evidence(root, plan, task):
                    raise ValueError('first continuation interrupted evidence differs')
                ledger.append({'taskId': task['taskId'], 'status': 'infrastructure-interrupted',
                               'evidence': evidence})
            else:
                if continuation.get('format') != 'azcombat.large-teacher-continuation.v2':
                    raise ValueError(f'failure outside first continuation: {task["taskId"]}')
                evidence = _failed_evidence(root, plan, task, directory)
                if task['taskId'] == continuation['failedPriorAttempt']['taskId']:
                    _check_evidence(root, continuation['failedPriorAttempt'], evidence)
                status = (evidence['classification'] if evidence['classification'] ==
                          'infrastructure-timeout' else 'failed')
                ledger.append({'taskId': task['taskId'], 'status': status, 'evidence': evidence})
            if not retry_directory.exists():
                raise ValueError(f'failed task lacks retry: {task["taskId"]}')
            _check_completed(root, plan, task, retry_directory, retry=True)
            selected = retry_directory
            retry = True
        ledger.append({'taskId': task['taskId'], 'status': 'complete',
                       'attempt': ref(selected / 'attempt.json'),
                       'execution': ref(selected / 'complete.json'), 'retry': retry})
    if {entry.name for entry in (root / 'collection').iterdir()} != {task['taskId'] for task in plan['tasks']}:
        raise ValueError('collection contains unexpected task directories')
    return ledger


def _check_amended_index_ledger(root, index, continuation):
    ledger = index['attemptLedger']
    if continuation.get('format') == 'azcombat.large-teacher-continuation.v2':
        plan = _load_frozen_plan(root)
        if ledger != _attempt_ledger(root, plan, continuation):
            raise ValueError('general admission attempt ledger differs from preserved attempts')
        if tuple(index['summary'][key] for key in ('attempts', 'retries', 'failedAttempts')) != \
                _attempt_counts(index['entries'], ledger, continuation):
            raise ValueError('general admission attempt totals differ')
        infrastructure_failures = sum(a['status'] in ('infrastructure-interrupted',
                                                      'infrastructure-timeout') for a in ledger)
        if index['summary']['failedInfrastructureAttempts'] != infrastructure_failures:
            raise ValueError('general admission infrastructure failure count differs')
        return
    if (len(ledger) != 101
            or ledger[41] != {'taskId': CONTINUATION_TASK, 'status': 'infrastructure-interrupted',
                              'evidence': continuation['interruptedOriginal']}):
        raise ValueError('amended admission lacks exact interrupted attempt')
    retry_directory = root / 'collection' / CONTINUATION_TASK / 'retry-001'
    if ledger[42] != {'taskId': CONTINUATION_TASK, 'status': 'complete',
                      'attempt': ref(retry_directory / 'attempt.json'),
                      'execution': ref(retry_directory / 'complete.json'), 'retry': True}:
        raise ValueError('amended admission lacks exact retry completion')
    if _attempt_counts(index['entries'], ledger, continuation) != (101, 1, 1):
        raise ValueError('amended admission attempt counts differ')


def collect(root, *, use_continuation=False):
    plan = load_plan(root, use_continuation=use_continuation)
    continuation = None
    if use_continuation:
        continuation = (load_general_continuation(root, plan)
                        if (root / GENERAL_CONTINUATION_FILE).exists()
                        else load_continuation(root, plan))
    if (root / 'index.json').exists():
        raise ValueError('admission already exists; do not rerun collection')
    if not use_continuation and ((root / CONTINUATION_FILE).exists()
                                 or (root / GENERAL_CONTINUATION_FILE).exists()):
        raise ValueError('amended collection requires explicit collect-only command')
    results = []
    for task in plan['tasks']:
        scenario = check_ref(task['scenario'])
        directory = root / 'collection' / task['taskId']
        complete = directory / 'complete.json'
        run_directory = directory
        if directory.exists() and not complete.exists():
            if (continuation is None or not (directory / 'failure.json').exists()):
                raise ValueError(f'unapproved unfinished task: {task["taskId"]}')
            if task['taskId'] == CONTINUATION_TASK:
                first = (load_continuation(root, plan, require_current_source=False)
                         if continuation.get('format') == 'azcombat.large-teacher-continuation.v2'
                         else continuation)
                if first['interruptedOriginal'] != _interrupted_evidence(root, plan, task):
                    raise ValueError('interrupted original changed before retry')
            elif continuation.get('format') == 'azcombat.large-teacher-continuation.v2':
                failed = _failed_evidence(root, plan, task, directory)
                if task['taskId'] == continuation['failedPriorAttempt']['taskId']:
                    _check_evidence(root, continuation['failedPriorAttempt'], failed)
            else:
                raise ValueError(f'unapproved unfinished task: {task["taskId"]}')
            run_directory = directory / 'retry-001'
            if run_directory.exists():
                if not (run_directory / 'complete.json').exists():
                    raise ValueError(f'prior retry is unfinished: {task["taskId"]}')
                result, _ = _check_completed(root, plan, task, run_directory, retry=True)
                results.append(result)
                continue
            run_directory.mkdir()
        if run_directory.exists() and (run_directory / 'complete.json').exists():
            if (directory / 'retry-001').exists():
                raise ValueError(f'unapproved retry after completed task: {task["taskId"]}')
            result, _ = _check_completed(root, plan, task, run_directory)
            results.append(result)
            continue
        load_plan(root, use_continuation=use_continuation)
        if run_directory == directory:
            directory.mkdir(parents=True, exist_ok=True)
        while True:
            write_new(run_directory / 'attempt.json', {'task': task, 'startedAtUtc': now(),
                                                       'plan': ref(root / 'plan.json'),
                                                       'retry': run_directory != directory})
            print(json.dumps({'event': 'collect-start', 'task': task['taskId'],
                              'completed': len(results), 'retry': run_directory != directory}), flush=True)
            path = run_directory / 'trajectory.jsonl'
            try:
                audit = run_probe(output=path, seed=task['seed'], encounter=task['encounter'],
                                  search_mode='pure-mcts', game_dir=Path(plan['gameDir']),
                                  ritsu_root=Path(plan['ritsuRoot']), generated_scenario=scenario,
                                  max_decisions=plan['budget']['maxDecisions'], budget_ms=plan['budget']['milliseconds'],
                                  max_simulations=plan['budget']['maxSimulations'], timeout_seconds=plan['budget']['timeoutSeconds'])
                raw = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
                capture = _capture_evidence(raw)
                if capture['sources'] != ['native-damage-command-v1']:
                    raise ValueError('native damage evidence missing')
                result = {'task': task, 'audit': audit, 'captureEvidence': capture,
                          'finishedAtUtc': now(), 'nestedChoiceRows': sum(
                              m['choiceLayer'] > 1 for m in raw[0]['provenance']['decisionMetrics']),
                          'artifacts': {str(p.relative_to(root)): ref(p)
                                        for p in run_directory.iterdir() if p.is_file()}}
                write_new(run_directory / 'complete.json', result)
                results.append(result)
                print(json.dumps({'event': 'collect-complete', 'task': task['taskId'],
                                  'completed': len(results), 'outcome': audit['outcome'],
                                  'rows': audit['samples']}), flush=True)
                break
            except Exception as error:
                write_new(run_directory / 'failure.json', {'task': task, 'error': repr(error),
                                                          'finishedAtUtc': now()})
                if (continuation is None or
                        continuation.get('format') != 'azcombat.large-teacher-continuation.v2' or
                        run_directory != directory):
                    raise
                _failed_evidence(root, plan, task, directory)
                load_plan(root, use_continuation=use_continuation)
                run_directory = directory / 'retry-001'
                if run_directory.exists():
                    raise ValueError(f'retry already exists after failure: {task["taskId"]}') from error
                run_directory.mkdir()
    entries = []
    for task, result in zip(plan['tasks'], results, strict=True):
        directory = root / 'collection' / task['taskId']
        if not (directory / 'complete.json').exists():
            directory = directory / 'retry-001'
        checked_result, checked = _check_completed(root, plan, task, directory,
                                                   retry=directory.name == 'retry-001')
        if checked_result != result:
            raise ValueError('final completion differs from collected result')
        entries.append({**task, 'trajectory': ref(directory / 'trajectory.jsonl'),
                        'execution': ref(directory / 'complete.json'), 'rowCount': checked['samples'],
                        'outcome': checked['outcome'], 'valueTarget': checked['valueTarget'],
                        'choiceRows': len(checked['choiceRows']), 'nestedChoiceRows': result['nestedChoiceRows'],
                        'rewardLedger': checked['rewardLedger'], 'assemblies': checked['assemblies'],
                        'captureEvidence': result['captureEvidence']})
    rows = weighted_rows(entries, plan['partitions'])
    attempts = _attempt_ledger(root, plan, continuation)
    if any(attempt['status'] == 'failed' for attempt in attempts):
        raise ValueError('unclassified failure attempt requires diagnosis before admission')
    attempts_count, retries, failures = _attempt_counts(entries, attempts, continuation)
    summary = {'combats': len(entries), 'attempts': attempts_count, 'retries': retries,
               'failedAttempts': failures,
               'failedInfrastructureAttempts': sum(a['status'] in
                                                   ('infrastructure-interrupted', 'infrastructure-timeout')
                                                   for a in attempts),
               'byOutcome': dict(Counter(e['outcome'] for e in entries)),
               'rows': sum(e['rowCount'] for e in entries),
               'trainRows': len(rows['train']), 'validationRows': len(rows['validation']),
               'choiceRows': sum(e['choiceRows'] for e in entries),
               'nestedChoiceRows': sum(e['nestedChoiceRows'] for e in entries)}
    write_new(root / 'index.json', {'format': 'azcombat.large-teacher-admission.v1',
              'status': 'admitted-engineering-only', 'plan': ref(root / 'plan.json'),
              'continuation': ref(root / (GENERAL_CONTINUATION_FILE
                                          if continuation and continuation.get('format') ==
                                          'azcombat.large-teacher-continuation.v2'
                                          else CONTINUATION_FILE)) if continuation else None,
              'attemptLedger': attempts, 'entries': entries, 'summary': summary,
              'createdAtUtc': now()})
    print(json.dumps({'event': 'admitted', **summary}), flush=True)
    return summary


def train(root):
    index = read(root / 'index.json')
    plan = load_plan(root, use_continuation=index.get('continuation') is not None)
    if index['format'] != 'azcombat.large-teacher-admission.v1' or index['status'] != 'admitted-engineering-only':
        raise ValueError('index not admitted')
    if check_ref(index['plan']) != (root / 'plan.json').resolve():
        raise ValueError('admission refers to a different plan')
    if index.get('continuation') is not None:
        general = (root / GENERAL_CONTINUATION_FILE).exists()
        expected_continuation = GENERAL_CONTINUATION_FILE if general else CONTINUATION_FILE
        if _root_ref(root, index['continuation']) != (root / expected_continuation).resolve():
            raise ValueError('admission continuation differs')
        continuation = (load_general_continuation(root, plan) if general
                        else load_continuation(root, plan))
        if not general and (index['summary']['attempts'] != 101 or index['summary']['retries'] != 1
                            or index['summary']['failedInfrastructureAttempts'] != 1):
            raise ValueError('amended admission attempt ledger differs')
        _check_amended_index_ledger(root, index, continuation)
    else:
        if index['summary']['attempts'] != 100 or index['summary']['retries'] != 0:
            raise ValueError('original admission attempt ledger differs')
    for entry in index['entries']:
        execution = read(check_ref(entry['execution']))
        for identity in execution['artifacts'].values():
            check_ref(identity)
    data = weighted_rows(index['entries'], plan['partitions'])
    config = plan['training']
    if len(data['train']) < config['minimumTrainRows'] or len(data['validation']) < config['minimumValidationRows']:
        raise ValueError('predeclared minimum sample coverage not reached; do not collect more automatically')
    if (root / 'training-started.json').exists():
        raise ValueError('training already attempted; no automatic restart')
    write_new(root / 'training-started.json', {'startedAtUtc': now(), 'plan': ref(root / 'plan.json'),
                                            'index': ref(root / 'index.json')})
    started = time.monotonic()
    try:
        torch.set_num_threads(config['cpuThreads'])
        random.seed(config['seed'])
        torch.manual_seed(config['seed'])
        model = DeepSetsPolicyValue(config['hidden'])
        if sum(p.numel() for p in model.parameters()) != config['parameters']:
            raise ValueError('parameter count differs')
        optimizer = torch.optim.Adam(model.parameters(), lr=config['learningRate'])
        history = []
        for epoch in range(config['epochs']):
            ordered = list(data['train'])
            random.shuffle(ordered)
            model.train()
            weighted_epoch(model, ordered, optimizer)
            model.eval()
            metric = {'epoch': epoch + 1, 'elapsedSeconds': time.monotonic() - started,
                      **_weighted_metrics(model, data['train'], 'train'),
                      **_weighted_metrics(model, data['validation'], 'validation')}
            write_new(root / f'epoch-{epoch+1:03d}.json', metric)
            history.append(metric)
            print(json.dumps({'event': 'training-epoch', **metric}), flush=True)
        metadata = {'runName': root.name, 'config': config, 'parameterCount': config['parameters'],
                    'featureAbi': FEATURE_ABI, 'observationSchemaVersion': OBSERVATION_SCHEMA_VERSION,
                    'trainSeeds': plan['partitions']['train'], 'validationSeeds': plan['partitions']['validation'],
                    'sealedEvaluationSeeds': plan['partitions']['evaluation'], 'admission': ref(root / 'index.json'),
                    'trainRows': len(data['train']), 'validationRows': len(data['validation']),
                    'history': history, 'selectedEpoch': config['epochs'], 'selectionMetric': 'fixed-final-epoch',
                    'promotable': False, 'trainingSeconds': time.monotonic() - started}
        torch.save({'format': CHECKPOINT_FORMAT, 'featureAbi': FEATURE_ABI,
                    'observationSchemaVersion': OBSERVATION_SCHEMA_VERSION,
                    'config': {'hidden': config['hidden']}, 'model': model.state_dict(), 'metadata': metadata},
                   root / 'candidate.pt')
        write_new(root / 'training.json', metadata)
        export_onnx(root / 'candidate.pt', root / 'candidate.onnx',
                    [r.sample for r in data['train'] + data['validation']], tolerance=plan['numericalTolerance'])
        summary = {'status': 'trained-and-onnx-verified', 'finishedAtUtc': now(),
                   'parameters': config['parameters'], 'data': index['summary'],
                   'checkpoint': ref(root / 'candidate.pt'), 'onnx': ref(root / 'candidate.onnx'),
                   'export': ref(root / 'candidate.manifest.json'), 'formalPromotionGranted': False,
                   'championCreated': False, 'selfPlayStarted': False,
                   'remaining': ['actual large-model Native tree inference verification',
                                 'new preregistered paired evaluation', 'independent review', 'natural nested coverage']}
        write_new(root / 'summary.json', summary)
        return summary
    except Exception as error:
        write_new(root / 'training-failed.json', {'error': repr(error), 'finishedAtUtc': now()})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'amend-resume', 'amend-general-retry',
                                           'collect-only', 'collect-train', 'train'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--ritsu-root', type=Path)
    parser.add_argument('--prior-audit', type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if args.command == 'freeze':
        if not all((args.game_dir, args.ritsu_root, args.prior_audit)):
            parser.error('freeze requires game-dir, ritsu-root, prior-audit')
        result = freeze(root, args.game_dir, args.ritsu_root, args.prior_audit)
    elif args.command == 'amend-resume':
        result = amend_resume(root)
    elif args.command == 'amend-general-retry':
        result = amend_general_retry(root)
    elif args.command == 'collect-only':
        result = collect(root, use_continuation=True)
    else:
        if args.command == 'collect-train':
            collect(root)
        result = train(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
