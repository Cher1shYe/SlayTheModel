"""Fine-tune an ArmG checkpoint on already-collected prior episodes only.

This entry point never collects games or runs reinforcement learning.  It
preserves the original checkpoint and writes a new checkpoint and provenance.
Set STS2_PRIOR_PYD to the simulator extension that produced the episodes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil

from deployment import evaluate_battle_root_prior as isolated
import numpy as np
import torch

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, _ACTIONS, _CARD_OFF, ArmGScorer
from agent.armg_prior import LocalPrior
from agent.armg_prior_train import _split_records
from agent.armg_train import _save, _warm_start
from agent.common import CARD_COUNT, RACT
from torch.nn import functional as F


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def _check_shard(path):
    with np.load(path, allow_pickle=False) as data:
        s, a, q, offsets, screens = (data[k] for k in ('states', 'features', 'targets', 'offsets', 'screens'))
        n = len(s)
        if (s.shape != (n, ARMG_OBS_DIM) or a.ndim != 2 or a.shape[1] != ARMG_ACTION_DIM
                or q.shape != (len(a),) or offsets.shape != (n + 1,) or screens.shape != (n,)
                or n == 0 or offsets[0] != 0 or offsets[-1] != len(a)
                or np.any(np.diff(offsets) < 2)):
            raise ValueError(f'invalid prior episode dimensions: {path}')
        if not np.isfinite(s).all() or not np.isfinite(a).all() or not np.isfinite(q).all() or (q < 0).any():
            raise ValueError(f'invalid prior episode values: {path}')
        for left, right in zip(offsets[:-1], offsets[1:]):
            if not np.isclose(q[left:right].sum(), 1.0, atol=1e-5):
                raise ValueError(f'prior probabilities do not sum to one: {path}')
        return n


def website_targets(state, features, screen, prior):
    """Return (groups, distribution, source) for verified website evidence.

    Skip, uncovered cards, and extra actions have no website-ranking target.
    Scores here come from the site snapshot, not stored composite heuristic q.
    """
    if str(screen) == 'CARD_REWARD':
        scores, indexes = [], []
        for i, row in enumerate(features):
            kinds = row[:_ACTIONS]
            cards = row[_CARD_OFF:_CARD_OFF+CARD_COUNT]
            if not kinds.any() or int(np.argmax(kinds)) != int(RACT.TAKE_CARD) or not cards.any():
                continue
            score, covered = prior.rating(prior.card_row(int(np.argmax(cards))))
            if covered:
                indexes.append(i)
                scores.append(score)
        if len(indexes) >= 2:
            scores = np.asarray(scores, dtype=np.float64)
            scores = np.exp(scores-scores.max())
            return [[i] for i in indexes], scores/scores.sum(), 'cards'
    if str(screen) == 'REST':
        kinds = [int(np.argmax(row[:_ACTIONS])) for row in features]
        names = {int(RACT.REST_HEAL): 'HEAL', int(RACT.REST_UPGRADE): 'SMITH',
                 int(RACT.REST_DIG): 'DIG', int(RACT.REST_LIFT): 'LIFT',
                 int(RACT.REST_CLONE): 'CLONE'}
        # Other types such as potion use change the interpretation of the
        # conditional choice and therefore require KL-only treatment.
        if all(k in names for k in kinds):
            field = 'pct_low_hp' if float(state[0]) < .5 else 'pct_high_hp'
            groups, weights = [], []
            for kind in sorted(set(kinds)):
                row = prior.rests.get(names[kind])
                if row is None or row.get(field) is None or int(row.get('count') or 0) < 10:
                    continue
                groups.append([i for i,k in enumerate(kinds) if k == kind])
                weights.append(float(row[field]) + .5)
            if len(groups) >= 2 and all(math.isfinite(w) and w > 0 for w in weights):
                weights = np.asarray(weights,dtype=np.float64)
                return groups, weights/weights.sum(), 'rest'
    return [], np.zeros(0,dtype=np.float64), None


def _website_epoch(model, episodes, weights, rng, prior, optimizer=None, reference=None, kl_weight=1.0):
    training = optimizer is not None
    model.train(training)
    prior_sum = kl_sum = 0.0
    site_count = count = 0
    sources = Counter()
    order = rng.permutation(len(episodes)) if training else np.arange(len(episodes))
    for j in order:
        with np.load(episodes[int(j)]['shard'], allow_pickle=False) as f:
            states, features, offsets, screens = f['states'], f['features'], f['offsets'], f['screens']
            strata = f['strata'] if 'strata' in f else screens
            indexes = rng.permutation(len(states)) if training else np.arange(len(states))
            for start in range(0, len(indexes), 16):
                ids = indexes[start:start+16]
                n = len(ids)
                max_a = max(int(offsets[i+1]-offsets[i]) for i in ids)
                actions = np.zeros((n,max_a,ARMG_ACTION_DIM), dtype=np.float32)
                mask = np.zeros((n,max_a), dtype=np.bool_)
                weights_arr = np.asarray([weights.get(str(strata[i]), 1.0) for i in ids], dtype=np.float32)
                for k, i in enumerate(ids):
                    lo,hi=int(offsets[i]),int(offsets[i+1])
                    actions[k,:hi-lo] = features[lo:hi]
                    mask[k,:hi-lo] = True
                if training:
                    optimizer.zero_grad()
                with torch.set_grad_enabled(training):
                    inputs = torch.from_numpy(states[ids]); candidates = torch.from_numpy(actions)
                    logits = model(inputs,candidates).masked_fill(~torch.from_numpy(mask),-1e9)
                    w = torch.from_numpy(weights_arr)
                    terms, term_weights = [], []
                    for k,i in enumerate(ids):
                        lo,hi=int(offsets[i]),int(offsets[i+1])
                        groups,target,source=website_targets(states[i],features[lo:hi],screens[i],prior)
                        if source is None:
                            continue
                        # Aggregate candidate probabilities within each class,
                        # so choosing which card to upgrade is not supervised.
                        class_logits=torch.stack([torch.logsumexp(logits[k, group],dim=0) for group in groups])
                        terms.append(-(torch.from_numpy(target.astype(np.float32))*F.log_softmax(class_logits,dim=0)).sum())
                        term_weights.append(w[k])
                        sources[source] += 1
                    if terms:
                        site_loss=torch.stack(terms)
                        site_weights=torch.stack(term_weights)
                        weighted_site=(site_loss*site_weights).sum()
                        site_weight=site_weights.sum()
                    else:
                        site_loss=logits.sum()*0
                        weighted_site=site_loss
                        site_weight=torch.tensor(0.0)
                    logp = F.log_softmax(logits,dim=1)
                    with torch.no_grad():
                        ref_logits=reference(inputs,candidates).masked_fill(~torch.from_numpy(mask),-1e9)
                        ref_logp=F.log_softmax(ref_logits,dim=1)
                        ref_p=ref_logp.exp()
                    kl = (ref_p*(ref_logp-logp)).sum(dim=1)
                    kl_avg=(kl*w).sum()/w.sum()
                    loss = kl_weight*kl_avg + weighted_site/site_weight.clamp_min(1)
                    if not torch.isfinite(loss):
                        raise RuntimeError('non-finite fine-tuning loss')
                    if training:
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                        optimizer.step()
                prior_sum += float(site_loss.detach().sum())
                site_count += len(terms)
                kl_sum += float(kl.detach().sum())
                count += n
    if not count or not site_count:
        raise RuntimeError('no eligible website-ranked card decisions in split')
    return {'site_cross_entropy': prior_sum/site_count, 'kl_to_original': kl_sum/count,
            'decisions': count, 'website_decisions': site_count, 'website_sources': dict(sources)}


def load_records(directories, simulator_hash):
    """Check settings and materialize a deterministic, auditable manifest."""
    records, sources, seeds, data_hash = [], [], set(), None
    for d in directories:
        d = Path(d).resolve(strict=True)
        config = json.loads((d/'config.json').read_text(encoding='utf-8'))
        progress = json.loads((d/'progress.json').read_text(encoding='utf-8'))
        if progress.get('state') != 'completed' or progress.get('stage') != 'completed':
            raise ValueError(f'incomplete source collection: {d}')
        expected = {'simulator_sha256': simulator_hash, 'information': 'oracle',
                    'ascension': 0, 'simulations_per_decision': 2000,
                    'boss_simulations_per_decision': 10000, 'path_cache': 'none',
                    'combat': 'pure mcts'}
        for key, value in expected.items():
            if config.get(key) != value:
                raise ValueError(f'{key} mismatch in {d}')
        digest = config.get('data_manifest_sha256')
        if not digest or (data_hash and digest != data_hash):
            raise ValueError('prior snapshot mismatch')
        data_hash = digest
        snap = d/'data_snapshot'
        manifest_path = snap/'manifest.json'
        if _sha(manifest_path) != digest:
            raise ValueError(f'prior manifest mismatch in {d}')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for name in ('cards', 'relics', 'potions', 'community'):
            if _sha(snap/(name+'.json')) != manifest['snapshots'][name]['sha256']:
                raise ValueError(f'{name} snapshot mismatch in {d}')
        row_count = 0
        for line in (d/'episodes.jsonl').read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row.get('status') != 'terminated' or not row.get('shard'):
                raise ValueError(f'incomplete episode in {d}')
            seed = int(row['seed'])
            if seed in seeds:
                raise ValueError(f'duplicate game seed {seed}')
            seeds.add(seed)
            shard = Path(row['shard']).resolve(strict=True)
            if shard.parent != (d/'dataset').resolve():
                raise ValueError(f'episode shard outside source dataset: {shard}')
            n = _check_shard(shard)
            if n != row.get('records'):
                raise ValueError(f'episode record count mismatch: {shard}')
            records.append({**row, 'shard': str(shard), 'shard_sha256': _sha(shard), 'source_dir': str(d)})
            row_count += 1
        if row_count != config.get('games') or row_count != progress.get('games_completed'):
            raise ValueError(f'episode count mismatch in {d}')
        sources.append({'directory': str(d), 'config_sha256': _sha(d/'config.json'),
                        'episode_index_sha256': _sha(d/'episodes.jsonl'), 'config': config,
                        'episodes': row_count})
    if not records:
        raise ValueError('no source episodes')
    return records, sources, data_hash


def run(*, checkpoint, sources, out_dir, epochs=3, lr=1e-5, kl_weight=1.0, seed=20261030):
    if not isolated._extension:
        raise ValueError('STS2_PRIOR_PYD must name the source simulator extension')
    if epochs < 1 or lr <= 0 or kl_weight < 0 or not math.isfinite(kl_weight):
        raise ValueError('invalid fine-tuning settings')
    checkpoint = Path(checkpoint).resolve(strict=True)
    extension = Path(isolated._extension).resolve(strict=True)
    records, source_meta, data_hash = load_records(sources, _sha(extension))
    prior = LocalPrior(Path(source_meta[0]['directory'])/'data_snapshot')
    train, val = _split_records(records)
    if not train or not val:
        raise ValueError('need disjoint training and validation episodes')
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.manual_seed(seed); random.seed(seed); np.random.seed(seed)
    model, reference = ArmGScorer(), ArmGScorer().eval()
    initialization = _warm_start(str(checkpoint), model)
    _warm_start(str(checkpoint), reference)
    for p in reference.parameters():
        p.requires_grad_(False)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    counts = Counter()
    for row in train:
        counts.update(row.get('stratum_counts', row.get('screens', {})))
    if not counts:
        raise ValueError('no training strata')
    typical = sum(counts.values()) / len(counts)
    weights = {k: float(np.clip(typical / v, .25, 3.0)) for k, v in counts.items()}
    config = {'checkpoint': str(checkpoint), 'checkpoint_sha256': _sha(checkpoint),
              'simulator_path': str(extension), 'simulator_sha256': _sha(extension),
              'data_manifest_sha256': data_hash, 'sources': source_meta,
              'training_episodes': len(train), 'validation_episodes': len(val),
              'split': 'whole episode: (seed - 30100000) mod 5 == 0 is validation',
              'stratum_counts': dict(counts), 'stratum_weights': weights,
              'epochs': epochs, 'lr': lr, 'kl_weight': kl_weight, 'seed': seed,
              'information': 'no games or RL; existing oracle-collected states',
              'website_scope': 'conditional Elo ranking among two or more covered reward cards; '
                               'rest action category conditional shares by low/high HP',
              'other_states': 'KL to original policy only; stored composite heuristic targets are not learned',
              'created_utc': datetime.now(timezone.utc).isoformat()}
    _atomic_json(out/'config.json', config)
    _atomic_json(out/'dataset_manifest.json', {'episodes': [{'seed': r['seed'], 'path': r['shard'],
        'sha256': r['shard_sha256'], 'records': r['records'], 'source_dir': r['source_dir'],
        'split': 'validation' if r in val else 'train'} for r in records]})
    progress = {'state': 'running', 'stage': 'pretraining', 'epoch': 0, 'epochs': epochs}
    _atomic_json(out/'progress.json', progress)
    try:
        val_before = _website_epoch(model, val, {}, np.random.default_rng(seed), prior, reference=reference)
        progress.update(validation_loss_before=val_before['site_cross_entropy'],
                        validation_decisions=val_before['decisions'],
                        validation_website_sources=val_before['website_sources'])
        best, best_epoch = float('inf'), None
        rng = np.random.default_rng(seed ^ 0x2142)
        with (out/'metrics.jsonl').open('x', encoding='utf-8', buffering=1) as log:
            for epoch in range(1, epochs+1):
                train_metrics = _website_epoch(model, train, weights, rng, prior, opt, reference, kl_weight)
                validation = _website_epoch(model, val, {}, rng, prior, reference=reference)
                if validation['site_cross_entropy'] < best:
                    best, best_epoch = validation['site_cross_entropy'], epoch
                    _save(out/'finetuned.pt', model, opt,
                          {'stage': 'finetune_complete', 'epoch': epoch, 'validation_loss': best,
                           'validation_loss_before': val_before['site_cross_entropy'], 'initialization': initialization}, config)
                row = {'epoch': epoch, 'train': train_metrics, 'validation': validation, 'best_epoch': best_epoch}
                log.write(json.dumps(row, allow_nan=False)+'\n'); log.flush()
                progress.update(row)
                _atomic_json(out/'progress.json', progress)
        progress.update(state='completed', stage='completed', best_epoch=best_epoch,
                        best_validation_loss=best, checkpoint=str((out/'finetuned.pt').resolve()))
        _atomic_json(out/'progress.json', progress)
    except BaseException as exc:
        progress.update(state='failed', error=f'{type(exc).__name__}: {exc}')
        _atomic_json(out/'progress.json', progress)
        raise
    return progress


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--sources', nargs='+', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--epochs', type=int, default=3)
    p.add_argument('--lr', type=float, default=1e-5)
    p.add_argument('--kl-weight', type=float, default=1.0)
    p.add_argument('--seed', type=int, default=20261030)
    print(json.dumps(run(**vars(p.parse_args(argv))),ensure_ascii=False))


if __name__ == '__main__':
    main()
