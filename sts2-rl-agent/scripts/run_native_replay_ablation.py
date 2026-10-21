"""Independent, fixed-update round2-only versus two-round replay training."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from sts2_env.az.config import atomic_json, content_hash
from sts2_env.az.learner import Learner
from sts2_env.az.model_factory import load_transformer_checkpoint, save_transformer_checkpoint
from sts2_env.az.native_generic import CONTENT, to_episode
from sts2_env.az.native_platform import lock_run
from sts2_env.az.native_transformer import batch_native
from sts2_env.az.network import masked_log_probs
from sts2_env.az.rewards import V7
from sts2_env.az.transformer_network import keyed_targets


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def split_episodes(recipes, seed=20261020):
    """Two whole fights per encounter, deterministic independent of input order."""
    groups = defaultdict(list)
    for recipe in recipes:
        groups[recipe['encounter']].append(recipe['scenario_id'])
    held = set()
    for ids in groups.values():
        if len(ids) < 3:
            raise ValueError('Not enough episodes for whole-fight holdout')
        held.update(sorted(ids, key=lambda s: content_hash([seed, s]))[:2])
    return held


def schedules(counts, sizes, replay, seed=20261020):
    """Shuffle cycles without dropping rows; identical total sample/update budget."""
    rngs = {k: np.random.default_rng(seed + k) for k in counts}
    orders, offsets = {}, {}
    def draw(k, n):
        result = []
        while n:
            if k not in orders or offsets[k] == len(orders[k]):
                orders[k] = rngs[k].permutation(counts[k]).tolist()
                offsets[k] = 0
            take = min(n, len(orders[k]) - offsets[k])
            result.extend((k, i) for i in orders[k][offsets[k]:offsets[k]+take])
            offsets[k] += take
            n -= take
        return result
    for step, size in enumerate(sizes):
        old = (size // 2 + (step % 2 if size % 2 else 0)) if replay else 0
        yield draw(0, old) + draw(1, size-old)


def evaluate(model, rows):
    model.eval()
    episode = defaultdict(lambda: defaultdict(float))
    with torch.inference_mode():
        for start in range(0, len(rows), 16):
            part = rows[start:start+16]
            batch = batch_native([r['observation'] for r in part])
            targets = keyed_targets(batch, [r['policy_target'] for r in part])
            logits, values = model(batch)
            logs = masked_log_probs(logits, batch['legal_mask'])
            for i, row in enumerate(part):
                e = episode[row['scenario_id']]
                error = float(values[i]) - row['z']
                e['rows'] += 1
                e['value_mse_sum'] += error**2
                e['value_mae_sum'] += abs(error)
                if not row['forced_action']:
                    positive = targets[i] > 0
                    e['policy_rows'] += 1
                    e['policy_kl_sum'] += float((targets[i, positive] * (
                        targets[i, positive].log()-logs[i, positive])).sum())
                    e['policy_ce_sum'] += float(-(targets[i, positive]*logs[i, positive]).sum())
                    e['argmax_agreement_sum'] += int(logs[i].argmax() == targets[i].argmax())
    metrics = {}
    for name, denominator in [('value_mse', 'rows'), ('value_mae', 'rows'),
                              ('policy_kl', 'policy_rows'), ('policy_ce', 'policy_rows'),
                              ('argmax_agreement', 'policy_rows')]:
        eligible = [e for e in episode.values() if e[denominator]]
        metrics[name] = sum(e[name+'_sum']/e[denominator] for e in eligible)/len(eligible)
    return dict(episodes=len(episode), metrics=metrics, per_episode=dict(episode))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    base = args.experiment.resolve()
    held_lock = lock_run(base/'runner.lock')
    torch.set_num_threads(1)
    config = json.loads((base/'config.json').read_text())
    frozen = json.loads((base/'inputs.json').read_text())
    for name, digest in frozen.items():
        if sha(base/name) != digest:
            raise ValueError(f'Frozen experiment input changed: {name}')
    identity = content_hash(dict(config=config, inputs=frozen))
    def publish(**extra):
        atomic_json(base/'progress.json', dict(updated_at=datetime.now(timezone.utc).isoformat(),
            identity=identity, **extra))
    try:
        publish(status='running', phase='validate_dataset')
        train, holdout, split = {}, {}, {}
        for k in (0, 1):
            manifests = sorted((base/f'data/round{k+1}').glob('*/manifest.json'))
            recipes = [r for p in manifests for r in json.loads(p.read_text())['recipes']]
            if len(recipes) != 1024 or len({r['scenario_id'] for r in recipes}) != 1024:
                raise ValueError('Expected exactly 1024 unique fights per round')
            ids = split_episodes(recipes)
            split[str(k+1)] = dict(holdout=sorted(ids),
                train=sorted(r['scenario_id'] for r in recipes if r['scenario_id'] not in ids))
            train[k], holdout[k] = [], []
            for p in manifests:
                manifest = json.loads(p.read_text())
                expected = content_hash(dict(provenance=manifest['provenance'],
                    model=manifest['model_sha256'], arm=manifest['arm'], recipes=manifest['recipes']))
                if expected != manifest['identity']:
                    raise ValueError('Cache manifest identity mismatch')
                for recipe in manifest['recipes']:
                    raw = json.loads((p.parent/(recipe['scenario_id']+'.json')).read_text())
                    if (raw['identity'] != expected or raw['recipe'] != recipe
                            or raw['modelSha256'] != manifest['model_sha256']):
                        raise ValueError('Cache trajectory identity mismatch')
                    rows = to_episode(raw)['rows']  # Strict native/schema/trajectory validation.
                    (holdout[k] if recipe['scenario_id'] in ids else train[k]).extend(rows)
        atomic_json(base/'split.json', split)
        source, payload = load_transformer_checkpoint(base/'models/start.pt', 'XS', CONTENT, V7)
        initial = payload['training_state']
        if not {'optimizer', 'torch_rng', 'history'} <= initial.keys():
            raise ValueError('Optimizer/RNG recovery state missing')
        sizes = config['batch_sizes']
        if len(sizes) != 879 or sum(sizes) != 56175:
            raise ValueError('Must preserve original round2 update and sample budgets')
        dataset = dict(training_rows={str(k+1):len(v) for k,v in train.items()},
                       holdout_rows={str(k+1):len(v) for k,v in holdout.items()},
                       updates=len(sizes), samples=sum(sizes), split_sha256=sha(base/'split.json'))
        atomic_json(base/'dataset.json', dataset)
        initial_path = base/'initial-evaluation.json'
        if not initial_path.exists():
            publish(status='running', phase='initial_evaluation')
            atomic_json(initial_path, {str(k+1):evaluate(source, v) for k,v in holdout.items()})
        for arm in ('round2_only', 'replay_round1_round2'):
            directory = base/arm
            directory.mkdir(exist_ok=True)
            latest = directory/'latest.pt'
            model, data = load_transformer_checkpoint(latest if latest.exists() else base/'models/start.pt',
                                                     'XS', CONTENT, V7)
            recovery = data['training_state']
            history = recovery['history'] if latest.exists() else []
            if latest.exists() and recovery['signature'] != dict(identity=identity, arm=arm):
                raise ValueError('Resume identity changed')
            learner = Learner(model, learning_rate=config['learning_rate'], value_weight=.5)
            learner.optimizer.load_state_dict(recovery['optimizer'])
            torch.set_rng_state(recovery['torch_rng'])
            learner.updates = len(history)
            def boundary(step):
                target = directory/f'checkpoint-{step:04d}.pt'
                if not target.exists():
                    shutil.copy2(latest, target)
                result = directory/f'evaluation-{step:04d}.json'
                if not result.exists():
                    publish(status='running', arm=arm, phase='holdout_evaluation', updates=step, total_updates=879)
                    atomic_json(result, {str(k+1):evaluate(learner.model, v) for k,v in holdout.items()})
                    learner.model.train()
            if len(history) in (293, 586, 879):
                boundary(len(history))
            for step, batch in enumerate(schedules({k:len(v) for k,v in train.items()}, sizes,
                                                   arm == 'replay_round1_round2'), 1):
                if step <= len(history):
                    continue
                metrics = learner.update_entities([train[k][i] for k,i in batch], microbatch_size=16)
                history.append(dict(metrics, samples=len(batch), old_samples=sum(k==0 for k,i in batch)))
                save_transformer_checkpoint(latest, learner.model, config=config,
                    training_state=dict(signature=dict(identity=identity, arm=arm),
                        optimizer=learner.optimizer.state_dict(), torch_rng=torch.get_rng_state(),
                        history=history))
                publish(status='running', phase='training', arm=arm, updates=step,
                        total_updates=879, latest_metrics=history[-1])
                if step in (293, 586, 879):
                    boundary(step)
            atomic_json(directory/'training-history.json', history)
        results = {arm:json.loads((base/arm/'evaluation-0879.json').read_text())
                   for arm in ('round2_only', 'replay_round1_round2')}
        paired = {}
        for round_id in ('1', '2'):
            a = results['round2_only'][round_id]['per_episode']
            c = results['replay_round1_round2'][round_id]['per_episode']
            if a.keys() != c.keys():
                raise ValueError('Holdout episode sets differ')
            paired[round_id] = {}
            for metric, denom in [('value_mse','rows'), ('policy_kl','policy_rows')]:
                diffs = np.array([c[k][metric+'_sum']/c[k][denom] -
                                  a[k][metric+'_sum']/a[k][denom] for k in sorted(a) if a[k][denom]])
                rng = np.random.default_rng(20261020)
                means = np.array([rng.choice(diffs, len(diffs), replace=True).mean() for _ in range(5000)])
                paired[round_id][metric] = dict(replay_minus_control=float(diffs.mean()),
                    ci95=np.quantile(means,[.025,.975]).tolist(), lower_is_better=True)
        report = dict(initial=json.loads(initial_path.read_text()), results=results,
                      paired_by_episode=paired, dataset=dataset,
                      caveat='Round1 holdout was seen by the common starting model; it measures retention. '
                      'Round2 holdout is excluded from both new training arms. Offline losses do not establish win-rate gains.')
        atomic_json(base/'report.json', report)
        publish(status='completed', phase='completed', report=str(base/'report.json'))
    except BaseException:
        import traceback
        publish(status='failed', error=traceback.format_exc())
        raise
    finally:
        held_lock.close()


if __name__ == '__main__':
    main()
