import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from azcombat import large_experiment as large


class LargeExperimentContinuationTests(unittest.TestCase):
    def test_general_amendment_freezes_57_completions_and_task_58_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('plan.json', large.CONTINUATION_FILE, 'continuation-001.sha256.json'):
                (root / name).write_text('{}', encoding='utf-8')
            collection = root / 'collection'
            collection.mkdir()
            tasks = [{'taskId': f'train-{i:03d}-CULTISTS_NORMAL'} for i in range(58)]
            tasks[41]['taskId'] = large.CONTINUATION_TASK
            for task in tasks:
                directory = collection / task['taskId']
                directory.mkdir()
                selected = directory / 'retry-001' if task['taskId'] == large.CONTINUATION_TASK else directory
                selected.mkdir(exist_ok=True)
                (selected / 'attempt.json').write_text('{}', encoding='utf-8')
                if task != tasks[57]:
                    (selected / 'complete.json').write_text('{}', encoding='utf-8')
                else:
                    (selected / 'failure.json').write_text('{}', encoding='utf-8')
            plan = {'sourceSnapshot': {'original': True}, 'tasks': tasks, 'partitions': {},
                    'behavior': 'pure-mcts', 'budget': {}, 'contracts': {}, 'training': {}}
            first = {'retryTaskId': large.CONTINUATION_TASK,
                     'continuationSourceSnapshot': {'first': True}}

            def completed(_root, _plan, task, directory, *, retry=False):
                return {'taskId': task['taskId'], 'attempt': large.ref(directory / 'attempt.json'),
                        'complete': large.ref(directory / 'complete.json'), 'artifacts': {}, 'retry': retry}

            failed = {'taskId': tasks[57]['taskId'], 'files': {}, 'probeStatus': 'failed',
                      'error': 'TimeoutExpired', 'classification': 'infrastructure-timeout',
                      'retry': False}
            with (patch.object(large, '_load_frozen_plan', return_value=plan),
                  patch.object(large, 'load_continuation', return_value=first),
                  patch.object(large, '_completed_evidence', side_effect=completed),
                  patch.object(large, '_failed_evidence', return_value=failed),
                  patch.object(large, '_source_snapshot', return_value={'second': True})):
                result = large.amend_general_retry(root)
                self.assertEqual(result['completedPriorAttempts'], 57)
                amendment = large.read(root / large.GENERAL_CONTINUATION_FILE)
                self.assertEqual(amendment['failedPriorAttempt'], failed)
                self.assertEqual(amendment['completedPriorAttempts'][41]['retry'], True)
                self.assertEqual(amendment['maximumAttemptsPerTask'], 2)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    large.amend_general_retry(root)

            with (patch.object(large, 'load_continuation', return_value=first),
                  patch.object(large, '_verify_completed_evidence'),
                  patch.object(large, '_failed_evidence', return_value=failed),
                  patch.object(large, '_source_snapshot', return_value={'changed': True})):
                with self.assertRaisesRegex(ValueError, 'current source'):
                    large.load_general_continuation(root, plan)

    def test_general_failure_retries_once_without_overwriting_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            (root / large.GENERAL_CONTINUATION_FILE).write_text('{}', encoding='utf-8')
            scenario = root / 'scenario.json'
            scenario.write_text('{}', encoding='utf-8')
            task = {'taskId': 'train-029-CULTISTS_NORMAL', 'seed': 'test-seed',
                    'encounter': 'CULTISTS_NORMAL', 'scenario': large.ref(scenario)}
            plan = {'tasks': [task], 'gameDir': str(root), 'ritsuRoot': str(root),
                    'budget': {'maxDecisions': 256, 'milliseconds': 1000,
                               'maxSimulations': None, 'timeoutSeconds': 1800}}
            continuation = {'format': 'azcombat.large-teacher-continuation.v2',
                            'failedPriorAttempt': {'taskId': 'earlier'}}
            with (patch.object(large, 'load_plan', return_value=plan),
                  patch.object(large, 'load_general_continuation', return_value=continuation),
                  patch.object(large, 'run_probe', side_effect=(ValueError('illegal policy'),
                                                               RuntimeError('retry failed'))) as probe):
                with self.assertRaisesRegex(RuntimeError, 'retry failed'):
                    large.collect(root, use_continuation=True)
            original = root / 'collection' / task['taskId']
            retry = original / 'retry-001'
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(probe.call_args_list[0].kwargs['output'], original / 'trajectory.jsonl')
            self.assertEqual(probe.call_args_list[1].kwargs['output'], retry / 'trajectory.jsonl')
            self.assertIn('illegal policy', large.read(original / 'failure.json')['error'])
            self.assertIn('retry failed', large.read(retry / 'failure.json')['error'])
            self.assertFalse((root / 'index.json').exists())

            with (patch.object(large, 'load_plan', return_value=plan),
                  patch.object(large, 'load_general_continuation', return_value=continuation),
                  patch.object(large, 'run_probe') as probe):
                with self.assertRaisesRegex(ValueError, 'prior retry is unfinished'):
                    large.collect(root, use_continuation=True)
                probe.assert_not_called()

    def test_general_resume_58_uses_preserved_failure_and_separate_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            (root / large.GENERAL_CONTINUATION_FILE).write_text('{}', encoding='utf-8')
            scenario = root / 'scenario.json'
            scenario.write_text('{}', encoding='utf-8')
            task = {'taskId': 'train-028-LIVING_FOG_NORMAL', 'seed': 'test-seed',
                    'encounter': 'LIVING_FOG_NORMAL', 'scenario': large.ref(scenario)}
            plan = {'tasks': [task], 'gameDir': str(root), 'ritsuRoot': str(root),
                    'budget': {'maxDecisions': 256, 'milliseconds': 1000,
                               'maxSimulations': None, 'timeoutSeconds': 1800}}
            directory = root / 'collection' / task['taskId']
            directory.mkdir(parents=True)
            (directory / 'attempt.json').write_text(json.dumps({
                'task': task, 'plan': large.ref(root / 'plan.json'), 'retry': False}), encoding='utf-8')
            (directory / 'failure.json').write_text(json.dumps({
                'task': task, 'error': 'TimeoutExpired', 'finishedAtUtc': 'frozen'}), encoding='utf-8')
            frozen = large._failed_evidence(root, plan, task, directory)
            continuation = {'format': 'azcombat.large-teacher-continuation.v2',
                            'failedPriorAttempt': frozen}
            with (patch.object(large, 'load_plan', return_value=plan),
                  patch.object(large, 'load_general_continuation', return_value=continuation),
                  patch.object(large, 'run_probe', side_effect=RuntimeError('retry stopped')) as probe):
                with self.assertRaisesRegex(RuntimeError, 'retry stopped'):
                    large.collect(root, use_continuation=True)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(frozen, large._failed_evidence(root, plan, task, directory))
            self.assertTrue((directory / 'retry-001' / 'failure.json').exists())

    def test_general_attempt_counts_are_dynamic(self):
        entries = [{} for _ in range(100)]
        attempts = [{'status': 'complete', 'retry': False} for _ in range(100)]
        attempts.insert(41, {'status': 'infrastructure-interrupted', 'retry': False})
        attempts[42]['retry'] = True
        attempts.insert(58, {'status': 'failed', 'retry': False})
        attempts[59]['retry'] = True
        continuation = {'format': 'azcombat.large-teacher-continuation.v2'}
        self.assertEqual(large._attempt_counts(entries, attempts, continuation), (102, 2, 2))
        attempts[59]['retry'] = False
        with self.assertRaisesRegex(ValueError, 'attempt ledger'):
            large._attempt_counts(entries, attempts, continuation)

    def test_general_ledger_rejects_retry_after_completed_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = {'taskId': 'train-000-CULTISTS_NORMAL'}
            directory = root / 'collection' / task['taskId']
            (directory / 'retry-001').mkdir(parents=True)
            (directory / 'complete.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'completed task has retry'):
                large._attempt_ledger(root, {'tasks': [task]},
                                      {'format': 'azcombat.large-teacher-continuation.v2'})

    def test_timeout_classification_is_explicit_not_a_combat_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            task = {'taskId': 'train-028-LIVING_FOG_NORMAL', 'seed': 'test-seed',
                    'encounter': 'LIVING_FOG_NORMAL', 'scenario': {'path': str(root / 'scenario.json'),
                                                                  'sha256': 'fixed'}}
            directory = root / 'collection' / task['taskId']
            directory.mkdir(parents=True)
            (directory / 'attempt.json').write_text(json.dumps({
                'task': task, 'plan': large.ref(root / 'plan.json'), 'retry': False}), encoding='utf-8')
            (directory / 'failure.json').write_text(json.dumps({
                'task': task, 'error': "TimeoutExpired(['worker'], 2100)",
                'finishedAtUtc': 'frozen'}), encoding='utf-8')
            evidence = large._failed_evidence(root, {}, task, directory)
            self.assertEqual(evidence['classification'], 'infrastructure-timeout')
            self.assertNotIn('outcome', evidence)

    def test_amendment_binds_original_attempts_and_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            collection = root / 'collection'
            collection.mkdir()
            tasks = [{'taskId': f'train-{i:03d}-CULTISTS_NORMAL'} for i in range(41)]
            tasks.append({'taskId': large.CONTINUATION_TASK})
            for task in tasks:
                directory = collection / task['taskId']
                directory.mkdir()
                (directory / 'attempt.json').write_text('{}', encoding='utf-8')
                if task['taskId'] != large.CONTINUATION_TASK:
                    (directory / 'complete.json').write_text('{}', encoding='utf-8')
            plan = {'sourceSnapshot': {'sourceTreeSha256': 'original'}, 'tasks': tasks,
                    'partitions': {}, 'behavior': 'pure-mcts', 'budget': {},
                    'contracts': {}, 'training': {}}
            interrupted = {'taskId': large.CONTINUATION_TASK, 'failure': 'preserved'}
            with (patch.object(large, '_load_frozen_plan', return_value=plan),
                  patch.object(large, '_check_completed', return_value=({'artifacts': {}}, {})),
                  patch.object(large, '_interrupted_evidence', return_value=interrupted),
                  patch.object(large, '_source_snapshot', return_value={'sourceTreeSha256': 'new'})):
                result = large.amend_resume(root)
                self.assertEqual(result['completedOriginalAttempts'], 41)
                amendment = large.load_continuation(root, plan)
                self.assertEqual(amendment['originalSourceSnapshot'], plan['sourceSnapshot'])
                self.assertEqual(amendment['interruptedOriginal'], interrupted)
                self.assertEqual(amendment['retryLimit'], 1)
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    large.amend_resume(root)
            with (patch.object(large, '_interrupted_evidence', return_value=interrupted),
                  patch.object(large, '_source_snapshot', return_value={'sourceTreeSha256': 'changed-again'})):
                with self.assertRaisesRegex(ValueError, 'continuation differs'):
                    large.load_continuation(root, plan)
            (collection / tasks[0]['taskId'] / 'complete.json').write_text('{"changed":true}', encoding='utf-8')
            with (patch.object(large, '_interrupted_evidence', return_value=interrupted),
                  patch.object(large, '_source_snapshot', return_value={'sourceTreeSha256': 'new'})):
                with self.assertRaisesRegex(ValueError, 'hash changed'):
                    large.load_continuation(root, plan)

    def test_only_interrupted_frozen_task_may_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = {'taskId': 'train-021-CULTISTS_NORMAL', 'scenario': {'path': str(root / 'input.json'),
                                                                    'sha256': ''}}
            scenario = root / 'input.json'
            scenario.write_text('{}', encoding='utf-8')
            task['scenario'] = large.ref(scenario)
            directory = root / 'collection' / task['taskId']
            directory.mkdir(parents=True)
            (directory / 'failure.json').write_text('{}', encoding='utf-8')
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            plan = {'tasks': [task]}
            with (patch.object(large, 'load_plan', return_value=plan),
                  patch.object(large, 'load_continuation', return_value={'retryTaskId': large.CONTINUATION_TASK}),
                  patch.object(large, 'run_probe') as probe):
                with self.assertRaisesRegex(ValueError, 'unapproved unfinished task'):
                    large.collect(root, use_continuation=True)
                probe.assert_not_called()
                self.assertFalse((directory / 'retry-001').exists())

    def test_retry_completion_checks_task_and_artifact_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'plan.json').write_text('{}', encoding='utf-8')
            task = {'taskId': large.CONTINUATION_TASK}
            retry = root / 'collection' / task['taskId'] / 'retry-001'
            retry.mkdir(parents=True)
            (retry / 'attempt.json').write_text(json.dumps({
                'task': task, 'plan': large.ref(root / 'plan.json'), 'retry': True}), encoding='utf-8')
            artifact = retry / 'trajectory.jsonl'
            artifact.write_text('original', encoding='utf-8')
            complete = retry / 'complete.json'
            complete.write_text(json.dumps({'task': {'taskId': 'wrong'},
                                            'artifacts': {'trajectory': large.ref(artifact)}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'completion differs'):
                large._check_completed(root, {}, task, retry, retry=True)
            complete.write_text(json.dumps({'task': task,
                                            'artifacts': {'trajectory': large.ref(artifact)}}), encoding='utf-8')
            artifact.write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                large._check_completed(root, {}, task, retry, retry=True)

    def test_attempt_ledger_requires_one_preserved_failure_and_one_retry(self):
        entries = [{} for _ in range(100)]
        attempts = [{'status': 'complete', 'retry': False} for _ in range(100)]
        attempts.insert(41, {'status': 'infrastructure-interrupted'})
        attempts[42]['retry'] = True
        self.assertEqual(large._attempt_counts(entries, attempts, {'retryTaskId': large.CONTINUATION_TASK}),
                         (101, 1, 1))
        with self.assertRaisesRegex(ValueError, 'attempt ledger'):
            large._attempt_counts(entries, attempts[1:], {'retryTaskId': large.CONTINUATION_TASK})
        attempts[42]['retry'] = False
        with self.assertRaisesRegex(ValueError, 'attempt ledger'):
            large._attempt_counts(entries, attempts, {'retryTaskId': large.CONTINUATION_TASK})

    def test_amended_index_binds_failed_attempt_and_retry_positions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            retry = root / 'collection' / large.CONTINUATION_TASK / 'retry-001'
            retry.mkdir(parents=True)
            for name in ('attempt.json', 'complete.json'):
                (retry / name).write_text('{}', encoding='utf-8')
            interrupted = {'taskId': large.CONTINUATION_TASK, 'failure': 'original'}
            entries = [{} for _ in range(100)]
            ledger = [{'taskId': f'task-{i}', 'status': 'complete', 'retry': False}
                      for i in range(100)]
            ledger.insert(41, {'taskId': large.CONTINUATION_TASK,
                               'status': 'infrastructure-interrupted', 'evidence': interrupted})
            ledger[42] = {'taskId': large.CONTINUATION_TASK, 'status': 'complete',
                          'attempt': large.ref(retry / 'attempt.json'),
                          'execution': large.ref(retry / 'complete.json'), 'retry': True}
            index = {'entries': entries, 'attemptLedger': ledger}
            continuation = {'interruptedOriginal': interrupted}
            large._check_amended_index_ledger(root, index, continuation)
            ledger[41] = {'taskId': 'other', 'status': 'infrastructure-interrupted',
                          'evidence': interrupted}
            with self.assertRaisesRegex(ValueError, 'exact interrupted attempt'):
                large._check_amended_index_ledger(root, index, continuation)
            ledger[41]['taskId'] = large.CONTINUATION_TASK
            ledger[42]['retry'] = False
            with self.assertRaisesRegex(ValueError, 'exact retry completion'):
                large._check_amended_index_ledger(root, index, continuation)

    def test_amendment_refuses_preexisting_hash_sidecar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'continuation-001.sha256.json').write_text('{}', encoding='utf-8')
            with patch.object(large, '_load_frozen_plan', return_value={}):
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    large.amend_resume(root)

    def test_collect_only_cli_never_trains(self):
        with (patch.object(sys, 'argv', ['large_experiment', 'collect-only', '--output', 'D:/frozen-r6']),
              patch.object(large, 'collect', return_value={'combats': 100}) as collect,
              patch.object(large, 'train') as train):
            large.main()
            collect.assert_called_once_with(Path('D:/frozen-r6').resolve(), use_continuation=True)
            train.assert_not_called()


if __name__ == '__main__':
    unittest.main()
