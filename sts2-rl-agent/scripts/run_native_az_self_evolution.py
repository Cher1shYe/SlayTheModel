"""Strict, resumable full-epoch AlphaZero self-evolution with a bounded startup check."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import threading
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from scripts.run_native_epoch_experiment import sha, summary, train_epochs
from sts2_env.az.all_runner import paired_gain
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.model_factory import load_transformer_checkpoint, save_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, raw_leaf_settings, validate_raw, to_episode
from sts2_env.az.native_generic_backend import NativeBackend, make_recipe
from sts2_env.az.rewards import V7
from sts2_env.az.native_platform import lock_run

SEARCH = 'all-node-policy-pure-value-v1'


class AlphaZeroBackend(NativeBackend):
    def raw_validator(self, raw):
        if raw_leaf_settings(raw) != ('learned', 1.) or raw.get('searchMode') != SEARCH:
            raise ValueError('Requires all-node policy and pure learned value')
        return validate_raw(raw, allow_training_cutoff=True, allow_search_validation_cutoff=True)


def recipes_for(config, protocol, iteration):
    count = config['training']['episodes_per_iteration']
    return tuple(make_recipe(config['training_seed_base'] + iteration * 10000 + i,
        protocol['encounters'][i % len(protocol['encounters'])], protocol['cards'], 'train')
        for i in range(count))


def runtime_hashes(repo):
    root = repo / 'artifacts/native-host'
    result = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
              if p.is_file() and (p.suffix.lower() in ('.dll', '.exe', '.so', '.json', '.x86_64')
                                  or '.so.' in p.name)}
    if not result:
        raise ValueError('An isolated prebuilt runtime is required')
    return result


def rows(raws):
    return [dict(scenario_id=r['recipe']['scenario_id'], reward=r['outcome']['reward']) for r in raws]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--verify-and-stop', action='store_true',
                        help='Collect one 16-fight shard, verify one separate update, then stop.')
    args = parser.parse_args()
    base = args.experiment.resolve()
    run_lock = lock_run(base/'runner.lock')
    config = json.loads((base/'config.json').read_text(encoding='utf-8'))
    protocol = json.loads((base/'protocol.json').read_text(encoding='utf-8'))
    from scripts.build_native_runtime import sha_file
    build_inputs = json.loads((base/'build-inputs.json').read_text(encoding='utf-8'))
    if not build_inputs or any(sha_file(path) != digest for path, digest in build_inputs.items()):
        raise ValueError('Game/RitsuLib build input changed')
    training = config['training']
    if (config['search']['prior_mode'] != SEARCH or config['search']['leaf_mode'] != 'learned'
            or config['search']['value_mix'] != 1. or config['workers'] != 8
            or training['episodes_per_iteration'] != 1024 or training['epochs'] != 3
            or not 1 <= training['iterations'] <= 1000):
        raise ValueError('Invalid frozen self-evolution configuration')
    out = base/'run'
    out.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    backend = AlphaZeroBackend(config['backend'], protocol, out)
    backend.configure_workers(config['workers'])
    backend.configure_search('learned', 1.)
    expected_runtime = json.loads((base/'runtime.json').read_text(encoding='utf-8'))
    if expected_runtime != runtime_hashes(backend.repo):
        raise ValueError('Isolated runtime identity changed')
    backend.built = True  # Never compile in this runner.
    source = base/'models/initial.pt'
    if sha(source) != config['initial_sha256']:
        raise ValueError('Initial candidate checksum mismatch')
    identity = content_hash(dict(config=config, protocol=protocol, provenance=backend.provenance,
                                 runtime=expected_runtime, build_inputs=build_inputs, runner=sha(__file__),
                                 epoch_runner=sha(Path(__file__).with_name('run_native_epoch_experiment.py'))))
    state_path = out/'state.json'
    if state_path.exists():
        if not args.resume:
            raise ValueError('Existing run requires --resume')
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state['identity'] != identity:
            raise ValueError('Run identity changed; audited migration required')
        for name, digest in state['checkpoint_hashes'].items():
            if sha(base/name) != digest:
                raise ValueError('Saved checkpoint identity changed')
    else:
        if args.resume:
            raise ValueError('Resume state missing')
        state = dict(identity=identity, history=[], pending=None, phase='collection',
                     learner='models/initial.pt', champion='models/initial.pt', champion_rows=None,
                     checkpoint_hashes={'models/initial.pt': sha(source)})
        atomic_json(state_path, state)
    progress = dict(status='running', pid=os.getpid(), workers=8, budget_ms=backend.budget,
                    search=SEARCH, planned_fights_per_iteration=1024, epochs=3)
    lock, stop = threading.Lock(), threading.Event()
    active = [None]

    def publish(**values):
        with lock:
            progress.update(values, updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(base/'progress.json', progress)

    def heartbeat():
        while not stop.wait(5):
            p = active[0]
            if p is not None and (p/'progress.json').exists():
                publish(active_shard=json.loads((p/'progress.json').read_text()))
            else:
                publish()

    def fights(checkpoint, recipes, directory):
        active[0] = directory
        result = backend.fights(base/checkpoint, recipes, directory, 'puct')
        publish(active_shard=json.loads((directory/'progress.json').read_text()))
        return result

    def remember(name):
        state['checkpoint_hashes'][name] = sha(base/name)

    publish(phase=state['phase'])
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        for iteration in range(len(state['history']), training['iterations']):
            directory = out/f'iteration-{iteration:03d}'
            directory.mkdir(exist_ok=True)
            recipes = recipes_for(config, protocol, iteration)
            if {r['seed'] for r in recipes} & {r['seed'] for r in backend.validation}:
                raise ValueError('Training and validation overlap')
            atomic_json(directory/'recipes.json', recipes)
            samples, collected = [], []
            publish(phase='collection', iteration=iteration, completed_fights=0)
            for start in range(0, len(recipes), 16):
                raw = fights(state['learner'], recipes[start:start+16],
                             directory/'collection'/f'shard-{start//16:03d}')
                collected.extend(raw)
                for fight in raw:
                    samples.extend(to_episode(fight)['rows'])
                publish(completed_fights=len(collected), total_fights=1024)
                if args.verify_and_stop:
                    if state['pending'] is not None or state['history']:
                        raise ValueError('Startup check is only valid before formal training')
                    publish(phase='verify_optimizer')
                    model, _ = load_transformer_checkpoint(base/state['learner'], 'XS', CONTENT, V7)
                    # Exercise the same learner and persistence path, using a separate diagnostic checkpoint.
                    probe_config = dict(training, epochs=1)
                    probe_samples = samples[:training['batch_size']]
                    probe_id = content_hash([(s['episode_id'], s['step_index']) for s in probe_samples])
                    probe_path = directory/'startup-check.pt'
                    def save_probe(model, payload):
                        save_transformer_checkpoint(probe_path, model, training_state=payload)
                    updated, losses = train_epochs(model, probe_samples, probe_config, probe_id, persist=save_probe)
                    restored, payload = load_transformer_checkpoint(probe_path, 'XS', CONTENT, V7)
                    if (len(losses) != 1 or not any(not torch.equal(t, model.state_dict()[k])
                            for k, t in updated.state_dict().items())
                            or any(not torch.equal(t, restored.state_dict()[k])
                                   for k, t in updated.state_dict().items())):
                        raise ValueError('Optimizer/checkpoint verification failed')
                    evidence = dict(status='passed', collected_fights=len(collected), samples=len(samples),
                        diagnostic_updates=len(losses), metrics=losses, checkpoint_sha256=sha(probe_path),
                        search=SEARCH, workers=8, collection=summary(collected),
                        formal_updates=0, initial_sha256=sha(source))
                    atomic_json(base/'startup-check.json', evidence)
                    state['phase'] = 'collection'
                    atomic_json(state_path, state)
                    publish(status='stopped', phase='verified_and_stopped', evidence=evidence)
                    return
            dataset_id = content_hash([(s['episode_id'], s['step_index']) for s in samples])
            atomic_json(directory/'dataset.json', dict(dataset_id=dataset_id, samples=len(samples),
                epochs=training['epochs'], updates=training['epochs']*math.ceil(len(samples)/training['batch_size'])))
            if state['champion_rows'] is None:
                publish(phase='baseline_validation')
                baseline = fights(state['champion'], backend.validation, out/'baseline')
                state['champion_rows'] = rows(baseline)
                atomic_json(out/'baseline-summary.json', summary(baseline))
                atomic_json(state_path, state)
            if state['pending'] is None:
                state['pending'] = dict(iteration=iteration, update_checkpoint=None)
                atomic_json(state_path, state)
            pending = state['pending']
            checkpoint = pending['update_checkpoint'] or state['learner']
            model, payload = load_transformer_checkpoint(base/checkpoint, 'XS', CONTENT, V7)
            resume = payload.get('training_state')
            if resume is not None and not pending['update_checkpoint']:
                # Carry Adam moments and RNG across rounds, with a new full-epoch schedule.
                resume = dict(resume, history=[], signature=dict(dataset=dataset_id, count=len(samples),
                    epochs=training['epochs'], batch_size=training['batch_size'], seed=training['init_seed']))
            def persist(model, training_state):
                count = len(training_state['history'])
                name = f'run/iteration-{iteration:03d}/checkpoints/update-{count:05d}.pt'
                save_transformer_checkpoint(base/name, model, config=config, training_state=training_state)
                remember(name)
                pending['update_checkpoint'] = name
                state['phase'] = 'training'
                atomic_json(state_path, state)
                publish(phase='training', updates=count, latest_metrics=training_state['history'][-1])
            model, losses = train_epochs(model, samples, training, dataset_id, resume, persist)
            candidate = pending['update_checkpoint']
            publish(phase='candidate_validation')
            evaluated = fights(candidate, backend.validation, directory/'validation')
            candidate_rows = rows(evaluated)
            comparison = paired_gain(state['champion_rows'], candidate_rows)
            promoted = comparison['ci95'][0] > 0
            record = dict(iteration=iteration, candidate=candidate, promoted=promoted, paired=comparison,
                          validation=summary(evaluated), collection=summary(collected), updates=len(losses))
            if promoted:
                state.update(champion=candidate, champion_rows=candidate_rows)
            state.update(learner=candidate, pending=None, phase='collection')
            state['history'].append(record)
            atomic_json(directory/'report.json', record)
            atomic_json(state_path, state)
        state['phase'] = 'completed'
        atomic_json(state_path, state)
        publish(status='completed', phase='completed', history=state['history'])
    except BaseException:
        publish(status='failed', error=traceback.format_exc())
        raise
    finally:
        stop.set()
        thread.join()


if __name__ == '__main__':
    main()
