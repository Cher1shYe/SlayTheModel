"""Independent scratch PPO. Run from a frozen source tree; STOP pauses at a durable boundary."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from scripts.run_native_az_self_evolution import runtime_hashes
from scripts.check_native_collection import sha
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.model_factory import create_transformer, load_transformer_checkpoint, save_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT
from sts2_env.az.native_generic_backend import NativeBackend, make_recipe
from sts2_env.az.native_platform import lock_run
from sts2_env.az.rewards import V7
from sts2_env.az import cost_reward, ppo


class Backend(NativeBackend):
    def _execute(self, job, log):
        return self._execute_parallel(job, log)

    def raw_validator(self, raw):
        return ppo.trajectory_rows(raw, raw['modelSha256'], self.shaping_coefficient,
                                   self.reward_mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-cycles', type=int, default=0, help='0 means continuous')
    args = parser.parse_args()
    base = args.experiment.resolve()
    config = json.loads((base/'config.json').read_text())
    protocol = json.loads((base/'protocol.json').read_text())
    expected = json.loads((base/'expected.json').read_text())
    held = lock_run(base/'runner.lock')
    if (config['initialization'] != 'random' or config['algorithm'] != 'PPO-Clip'
            or config['checkpoint_every'] % config['rollout_battles']
            or config['rollout_battles'] < 1 or config['epochs'] < 1
            or not 0 < config['clip'] < 1 or not 0 < config['gae_lambda'] <= 1
            or config['gamma'] != 1. or config['checkpoint_every'] < 1):
        raise ValueError('Invalid PPO schedule/objective')
    torch.set_num_threads(config.get('torch_threads', 2))
    torch.use_deterministic_algorithms(True)
    native = Path(config['backend']['repo'])
    if runtime_hashes(native) != expected['runtime']:
        raise ValueError('PPO isolated runtime changed')
    for path, digest in expected['dependencies'].items():
        if sha(path) != digest:
            raise ValueError(f'Game/Ritsu build dependency changed: {path}')
    backend = Backend(config['backend'], protocol, base)
    backend.shaping_coefficient = config.get('shaping_coefficient', 0.)
    backend.reward_mode = config.get('reward_mode', 'v7')
    backend.configure_workers(config['workers'])
    backend.configure_search('learned', 1.)
    backend.search_job.update(policySample=True, collectionPolicy='greedy', cPuct=1.5,
                              noiseAlpha=.3, noiseFraction=.25)
    backend.provenance['ppo_sampling'] = dict(version='categorical-native-v1', rng='seed*397^decision*7919^20261021')
    backend.built = True
    identity = dict(config=config, protocol=protocol, expected=expected,
                    provenance=backend.provenance, runner=sha(__file__), algorithm=sha(ppo.__file__))
    identity = json.loads(json.dumps(identity))
    manifest = base/'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text()) != identity:
        raise ValueError('PPO experiment identity changed')
    atomic_json(manifest, identity)
    signature = content_hash(identity)
    latest = base/'latest.pt'
    if latest.exists():
        if not args.resume:
            raise ValueError('Existing PPO checkpoint requires --resume')
        model, payload = load_transformer_checkpoint(latest, config['tier'], CONTENT, V7)
        state = payload['training_state']
        if state['signature'] != signature:
            raise ValueError('PPO resume signature changed')
        optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=0.)
        optimizer.load_state_dict(state.pop('optimizer'))
        torch.set_rng_state(state.pop('torch_rng'))
    else:
        if args.resume:
            raise ValueError('Cannot resume without a PPO recovery checkpoint')
        torch.manual_seed(config['seed'])
        model = create_transformer(config['tier'], CONTENT, V7)
        optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=0.)
        state = dict(signature=signature, cycle=0, phase='collection', updates=0,
                     collected=0, trained=0, batch_cursor=0, history=[], cycle_metrics=[])
    status = dict(status='running', pid=os.getpid(), workers=config['workers'], algorithm='PPO-Clip',
                  initialization='random', search=False, checkpoint_every_battles=config['checkpoint_every'],
                  tier=config['tier'], parameters=sum(p.numel() for p in model.parameters()),
                  reward_mode=backend.reward_mode, recipe_hp=config.get('recipe_hp'),
                  kl_check_interval=config.get('kl_check_interval', 1),
                  learning_rate=config['learning_rate'], kl_scope=config.get('kl_scope', 'minibatch'))
    guard = threading.RLock()
    done = threading.Event()

    def persist():
        with guard:
            save_transformer_checkpoint(latest, model, f'ppo-update-{state["updates"]}',
                config=config, training_state=dict(state, optimizer=optimizer.state_dict(),
                                                 torch_rng=torch.get_rng_state()))

    def publish():
        with guard:
            extra = 0
            if state['phase'] == 'collection':
                file = base/'cache'/f'{state["cycle"]:06d}'/'progress.json'
                if file.exists():
                    extra = json.loads(file.read_text())['completed']
            view = dict(status, phase=state['phase'], cycle=state['cycle'], updates=state['updates'],
                        battles_completed=state['collected']+extra, battles_trained=state['trained'],
                        current_batch_completed=extra if state['phase']=='collection' else config['rollout_battles'],
                        current_batch_total=config['rollout_battles'], minibatch_cursor=state['batch_cursor'],
                        last_update=state['cycle_metrics'][-1] if state['cycle_metrics'] else None,
                        updated_at=datetime.now(timezone.utc).isoformat(),
                        latest_recovery=str(latest), last_batch=state['history'][-1] if state['history'] else None)
            atomic_json(base/'progress.json', view)

    def permanent_checkpoint():
        if state['phase'] == 'collection' and state['trained'] and state['trained'] % config['checkpoint_every'] == 0:
            destination = base/'checkpoints'/f'battles-{state["trained"]:09d}.pt'
            destination.parent.mkdir(exist_ok=True)
            if destination.exists() and sha(destination) != sha(latest):
                # Audited runtime migrations change only recovery identity. Preserve
                # the original milestone bytes used by evaluations and compare ALL state.
                saved = torch.load(destination, map_location='cpu', weights_only=False)
                recovery = torch.load(latest, map_location='cpu', weights_only=False)
                old_signature = saved['training_state']['signature']
                if old_signature not in config.get('checkpoint_signature_migrations', []):
                    raise ValueError('Permanent PPO checkpoint already differs')
                saved['training_state']['signature'] = recovery['training_state']['signature']
                def identical(a, b):
                    if isinstance(a, torch.Tensor):
                        return isinstance(b, torch.Tensor) and torch.equal(a, b)
                    if isinstance(a, dict):
                        return isinstance(b, dict) and a.keys() == b.keys() and all(identical(a[k], b[k]) for k in a)
                    if isinstance(a, (list, tuple)):
                        return type(a) is type(b) and len(a) == len(b) and all(identical(x, y) for x, y in zip(a, b))
                    return a == b
                if not identical(saved, recovery):
                    raise ValueError('Migrated permanent PPO checkpoint state differs')
            if not destination.exists():
                temporary = destination.with_suffix('.tmp')
                shutil.copyfile(latest, temporary)
                os.replace(temporary, destination)

    def monitor():
        try:
            while not done.wait(5):
                publish()
        except BaseException:
            status['progress_error'] = traceback.format_exc()
            done.set()

    if not latest.exists():
        persist()
        shutil.copyfile(latest, base/'initial.pt')
    permanent_checkpoint()  # Recover a crash between latest.pt and the milestone copy.
    publish()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        while not args.max_cycles or state['cycle'] < args.max_cycles:
            if done.is_set():
                raise RuntimeError(status.get('progress_error', 'Progress monitor exited'))
            if (base/'STOP').exists():
                status['status'] = 'paused'
                break
            cycle = state['cycle']
            cache = base/'cache'/f'{cycle:06d}'
            behavior = base/'behavior'/f'{cycle:06d}.pt'
            if not behavior.exists():
                if state['phase'] != 'collection':
                    raise ValueError('Training cannot recreate a missing behavior checkpoint')
                save_transformer_checkpoint(behavior, model, f'ppo-behavior-{cycle}', config=config)
            behavior_sha = sha(behavior)
            recipes = [make_recipe(config['recipe_seed'] + cycle * config['rollout_battles'] + i,
                         protocol['encounters'][(cycle*config['rollout_battles']+i) % len(protocol['encounters'])],
                         protocol['cards'], 'train', config.get('recipe_hp')) for i in range(config['rollout_battles'])]
            # Cache reuse executes all source, identity, outcome and parity validations.
            raws = backend.fights(behavior, recipes, cache, 'policy')
            training, returns = [], []
            for raw in raws:
                rows = ppo.trajectory_rows(raw, behavior_sha, backend.shaping_coefficient,
                                           backend.reward_mode)
                terminal = ppo.terminal_reward(raw, backend.reward_mode)
                training.extend(ppo.advantages(rows, terminal, config['gamma'], config['gae_lambda']))
                returns.append(cost_reward.total(rows, terminal))
            ppo.normalize_advantages(training)
            dataset = content_hash(dict(behavior=behavior_sha, files={r['recipe']['scenario_id']:
                        sha(cache/f'{r["recipe"]["scenario_id"]}.json') for r in raws}))
            old_model, _ = load_transformer_checkpoint(behavior, config['tier'], CONTENT, V7)
            error = ppo.verify_behavior(old_model, training, config['microbatch'])
            del old_model
            if state['phase'] == 'collection':
                # Ensure latest weights really are the behavior policy before any update.
                ppo.verify_behavior(model, training, config['microbatch'])
                state.update(phase='training', dataset=dataset, collected=state['collected']+len(raws),
                             batch_cursor=0, cycle_metrics=[])
                persist()
            elif state['dataset'] != dataset:
                raise ValueError('PPO rollout changed during training/resume')
            publish()
            plan = list(ppo.batch_plan(len(training), config, cycle))
            for index, (epoch, indices) in enumerate(plan):
                if index < state['batch_cursor']:
                    continue
                if (base/'STOP').exists():
                    status['status'] = 'paused'
                    break
                metrics = ppo.scheduled_update(model, optimizer, [training[i] for i in indices], config,
                    kl_rows=training if config.get('kl_scope') == 'rollout' else None,
                    rollout_updates=sum(m['applied'] for m in state['cycle_metrics']),
                    epoch_end=index + 1 == len(plan) or plan[index + 1][0] != epoch)
                metrics.update(epoch=epoch, minibatch=index, samples=len(indices))
                state['cycle_metrics'].append(metrics)
                state['batch_cursor'] = index+1
                if metrics['applied']:
                    state['updates'] += 1
                if not metrics['applied'] or metrics.get('stop_rollout', False):
                    state['batch_cursor'] = len(plan)
                persist()
                publish()
                if not metrics['applied'] or metrics.get('stop_rollout', False):
                    break
            if status['status'] == 'paused':
                break
            record = dict(cycle=cycle, battles=len(raws), rows=len(training), dataset=dataset,
                          reward_mode=backend.reward_mode,
                          shaping_coefficient=backend.shaping_coefficient,
                          mean_shaping_return=sum(r.get('shaping_reward', 0.) for r in training)/len(raws),
                          mean_training_return=sum(returns)/len(returns),
                          value_targets_outside_unit=sum(abs(r['return']) > 1 for r in training),
                          wins=sum(r['outcome']['won'] for r in raws),
                          mean_v7=sum(r['outcome']['reward'] for r in raws)/len(raws),
                          time_limits=sum(not r['complete'] for r in raws),
                          behavior_sha256=behavior_sha, behavior_max_error=error,
                          updates=sum(m['applied'] for m in state['cycle_metrics']),
                          metrics=state['cycle_metrics'])
            atomic_json(base/'batches'/f'{cycle:06d}.json', record)
            state['history'].append({k:v for k,v in record.items() if k != 'metrics'})
            state.update(phase='collection', cycle=cycle+1, trained=state['collected'],
                         batch_cursor=0, cycle_metrics=[])
            persist()
            permanent_checkpoint()
            publish()
            print(json.dumps(state['history'][-1]), flush=True)
        else:
            status['status'] = 'completed'
    except BaseException:
        status.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        done.set()
        thread.join()
        publish()
        held.close()


if __name__ == '__main__':
    main()
