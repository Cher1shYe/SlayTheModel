"""Independent, strict native collection -> full epochs -> paired search evaluation.

Run from a frozen Python snapshot, with --experiment pointing at its parent.
Every optimizer boundary is durable; resume revalidates all cached fights.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import threading
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.learner import Learner
from sts2_env.az.model_factory import load_transformer_checkpoint, save_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, raw_leaf_settings, validate_raw, to_episode
from sts2_env.az.native_generic_backend import NativeBackend, make_recipe
from sts2_env.az.rewards import V7


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def epoch_batches(count, epochs, batch_size, seed):
    if min(count, epochs, batch_size) < 1:
        raise ValueError('Nonempty data and positive epoch/batch counts required')
    for epoch in range(epochs):
        order = np.random.default_rng(seed + epoch).permutation(count)
        for start in range(0, count, batch_size):
            yield epoch, order[start:start + batch_size].tolist()


def train_epochs(model, samples, config, dataset_id, resume=None, persist=None):
    learner = Learner(model, learning_rate=config['learning_rate'], value_weight=config['value_weight'])
    signature = dict(dataset=dataset_id, count=len(samples), epochs=config['epochs'],
                     batch_size=config['batch_size'], seed=config['init_seed'])
    history = []
    if resume is not None:
        if resume['signature'] != signature:
            raise ValueError('Epoch resume dataset/schedule mismatch')
        learner.optimizer.load_state_dict(resume['optimizer'])
        torch.set_rng_state(resume['torch_rng'])
        history = list(resume['history'])
        learner.updates = len(history)
    else:
        torch.manual_seed(config['init_seed'])
    total = config['epochs'] * math.ceil(len(samples) / config['batch_size'])
    if len(history) > total:
        raise ValueError('Resume exceeds epoch schedule')
    for index, (epoch, indices) in enumerate(epoch_batches(len(samples), config['epochs'], config['batch_size'], config['init_seed'])):
        if index < len(history):
            continue
        metrics = learner.update_entities([samples[i] for i in indices], microbatch_size=16)
        history.append(dict(metrics, epoch=epoch + 1, samples=len(indices)))
        if persist:
            persist(learner.model, dict(signature=signature, optimizer=learner.optimizer.state_dict(),
                    torch_rng=torch.get_rng_state(), history=history))
    return learner.model.eval(), history


class SearchBackend(NativeBackend):
    def raw_validator(self, raw):
        if raw_leaf_settings(raw) != (self.search_job['leafMode'], self.search_job['valueMix']):
            raise ValueError('Leaf settings mismatch')
        return validate_raw(raw, allow_training_cutoff=True, allow_search_validation_cutoff=True)


def summary(raws):
    searched = [s for r in raws for s in r['steps'] if not s['forced']]
    return dict(episodes=len(raws), wins=sum(r['outcome']['won'] for r in raws),
        win_rate=sum(r['outcome']['won'] for r in raws)/len(raws),
        mean_utility=float(np.mean([r['outcome']['reward'] for r in raws])),
        truncated=sum(not r['complete'] for r in raws),
        searched_decisions=len(searched),
        mean_simulations=float(np.mean([s['simulations'] for s in searched])) if searched else None,
        mean_backup_depth=float(np.mean([s['leafDiagnostics']['meanBackupDepth'] for s in searched])) if searched else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    base = args.experiment.resolve()
    import msvcrt
    run_lock = (base/'runner.lock').open('a+b')
    if run_lock.tell() == 0:
        run_lock.write(b'0')
        run_lock.flush()
    run_lock.seek(0)
    msvcrt.locking(run_lock.fileno(), msvcrt.LK_NBLCK, 1)
    config = json.loads((base/'config.json').read_text())
    protocol = json.loads((base/'protocol.json').read_text())
    out = base/'run'
    out.mkdir(exist_ok=True)
    torch.set_num_threads(2)
    backend = SearchBackend(config['backend'], protocol, out)
    backend.configure_workers(4)
    backend.configure_search('mixed', .5)
    source = base/'models/initial.pt'
    if sha(source) != config['initial_sha256']:
        raise ValueError('Initial champion checksum mismatch')
    initial, _ = load_transformer_checkpoint(source, 'XS', CONTENT, V7)
    recipes = tuple(make_recipe(config['training_seed_base'] + i,
        protocol['encounters'][i % len(protocol['encounters'])], protocol['cards'], 'train')
        for i in range(config['training']['episodes_per_iteration']))
    if len({r['scenario_id'] for r in recipes}) != len(recipes):
        raise ValueError('Duplicate training recipes')
    if {r['seed'] for r in recipes} & {r['seed'] for r in backend.validation}:
        raise ValueError('Training/validation seed overlap')
    identity = content_hash(dict(config=config, provenance=backend.provenance, runner=sha(__file__), recipes=recipes))
    state_path = out/'state.json'
    if state_path.exists():
        if not args.resume:
            raise ValueError('Existing run requires --resume')
        state = json.loads(state_path.read_text())
        if state['identity'] != identity:
            raise ValueError('Experiment identity changed; audited migration required')
    else:
        if args.resume:
            raise ValueError('Resume state missing')
        state = dict(identity=identity, phase='collection', update_checkpoint=None, history=[],
                     initial_sha256=sha(source), champion_checkpoint=str(source))
        atomic_json(state_path, state)
        atomic_json(base/'training-recipes.json', recipes)
    progress = dict(status='running', pid=os.getpid(), experiment=str(base), budget_ms=500,
                    workers=4, training_fights=len(recipes), epochs=3, batch_size=64)
    lock = threading.Lock()
    def publish(**values):
        with lock:
            progress.update(values, updated_at=datetime.now(timezone.utc).isoformat())
            atomic_json(base/'progress.json', progress)
    # File-only heartbeat, not an external monitoring service.
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(5):
            details = {}
            for name in ('collection', 'baseline', 'candidate'):
                p = out/name/'progress.json'
                if p.exists():
                    details[name] = json.loads(p.read_text())
            publish(fights=details)
    publish(phase=state['phase'])
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        # Build once in this experiment only. Resume verifies the isolated runtime.
        build_marker = base/'runtime.json'
        runtime = backend.repo/'artifacts/native-host'
        def runtime_hashes():
            return {str(p.relative_to(runtime)): sha(p) for p in sorted(runtime.rglob('*'))
                    if p.is_file() and p.suffix.lower() in ('.dll', '.exe')}
        if build_marker.exists():
            if json.loads(build_marker.read_text()) != runtime_hashes():
                raise ValueError('Isolated runtime changed')
            backend.built = True
        else:
            publish(phase='building_isolated_runtime')
            build = base/'build'
            build.mkdir(exist_ok=True)
            backend._prepare_parallel(build)
            atomic_json(build_marker, runtime_hashes())
        publish(phase='collection')
        raws = backend.fights(source, recipes, out/'collection', 'puct')
        collection_summary = summary(raws)
        atomic_json(out/'collection-summary.json', collection_summary)
        samples = []
        for raw in raws:
            samples.extend(to_episode(raw)['rows'])
        del raws
        dataset_id = content_hash([(s['episode_id'], s['step_index']) for s in samples])
        manifest = dict(samples=len(samples), dataset_id=dataset_id,
                        updates=3*math.ceil(len(samples)/64), epochs=3, drop_last=False)
        atomic_json(out/'dataset.json', manifest)
        publish(phase='baseline_validation', dataset=manifest)
        baseline = backend.fights(source, backend.validation, out/'baseline', 'puct')
        before = summary(baseline)
        baseline_rows = [dict(scenario_id=r['recipe']['scenario_id'], reward=r['outcome']['reward']) for r in baseline]
        del baseline
        atomic_json(out/'baseline-summary.json', before)
        model, payload = (load_transformer_checkpoint(out/state['update_checkpoint'], 'XS', CONTENT, V7)
                          if state['update_checkpoint'] else (initial, {}))
        publish(phase='training')
        def persist(model, training_state):
            count = len(training_state['history'])
            name = f'checkpoints/update-{count:05d}.pt'
            save_transformer_checkpoint(out/name, model, f'epoch-update-{count}', config=config, training_state=training_state)
            state.update(phase='training', update_checkpoint=name, updates=count)
            atomic_json(state_path, state)
            publish(phase='training', updates=count, total_updates=manifest['updates'],
                    latest_metrics=training_state['history'][-1])
        model, losses = train_epochs(model, samples, config['training'], dataset_id,
                                    payload.get('training_state'), persist)
        del samples
        candidate = out/'candidate.pt'
        if candidate.exists():
            old, _ = load_transformer_checkpoint(candidate, 'XS', CONTENT, V7)
            if any(not torch.equal(t, old.state_dict()[k]) for k,t in model.state_dict().items()):
                raise ValueError('Saved candidate differs from resumed learner')
        else:
            save_transformer_checkpoint(candidate, model, '1024-fights-3-epochs', config=config)
        publish(phase='candidate_validation')
        after_raw = backend.fights(candidate, backend.validation, out/'candidate', 'puct')
        from sts2_env.az.all_runner import paired_gain
        comparison = paired_gain(baseline_rows, [dict(scenario_id=r['recipe']['scenario_id'], reward=r['outcome']['reward']) for r in after_raw])
        report = dict(baseline=before, candidate=summary(after_raw), paired=comparison,
                      dataset=manifest, losses=losses, collection=collection_summary,
                      initial_sha256=sha(source), candidate_sha256=sha(candidate))
        atomic_json(out/'report.json', report)
        state.update(phase='completed', history=[report], candidate_checkpoint=str(candidate))
        atomic_json(state_path, state)
        publish(status='completed', phase='completed', report=str(out/'report.json'))
    except BaseException:
        publish(status='failed', error=traceback.format_exc())
        raise
    finally:
        stopped.set()
        thread.join()


if __name__ == '__main__':
    main()
