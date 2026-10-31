"""Weak on-policy card/skip prior for ArmG REINFORCE.

Apply only to the Ironclad reward-card subset with a normal skip action and at
least one Ironclad card with observed cohort Elo. Colorless and other legal actions remain available
to the actual policy and its REINFORCE loss. This is a soft regularizer, not a
hard action mask or a quantitative guarantee of closeness to the website.
"""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .armg import _ACTIONS, _CARD_OFF
from .armg_prior import LocalPrior
from .common import CARD_COUNT, RACT, SCREEN

SKIP_ELO = (1400.0, 1500.0, 1600.0)
OBS_SCREEN_OFFSET = 38


class CardSkipPrior:
    def __init__(self, data_dir, skip_elos=SKIP_ELO, skip_elo_fn=None):
        self.site = LocalPrior(data_dir)
        self.skip_elos = tuple(map(float, skip_elos))
        self.skip_elo_fn = skip_elo_fn
        if len(self.skip_elos) != 3 or not all(math.isfinite(x) for x in self.skip_elos):
            raise ValueError('three finite skip Elo values are required')
        cards = json.loads((Path(__file__).resolve().parents[1] / 'simulator/content/cards.json').read_text(encoding='utf-8'))
        self.pools = {c['id']: str(c.get('pool', '')).lower() for c in cards}

    @staticmethod
    def score(row):
        """Use offered-but-never-picked cards with very strong shrinkage.

        Zero picks is observed evidence, not a missing card. The one pseudo
        observation keeps that evidence weak without importing other cohorts.
        """
        if row is None or row.get('elo') is None:
            return 0.0, False
        elo = float(row['elo'])
        offered = int(row.get('offered') or 0)
        picked = int(row.get('picked') or 0)
        if not math.isfinite(elo) or offered <= 0 or picked < 0 or picked > offered:
            return 0.0, False
        effective = min(offered, max(2, 2*picked))
        confidence = effective / (effective + 50.0)
        return float(np.clip((elo - 1500.0) * math.log(10) / 800 * confidence, -1.5, 1.5)), True

    def target(self, record):
        obs, features, choice = record[:3]
        if (len(obs) <= OBS_SCREEN_OFFSET + int(SCREEN.CARD_REWARD) or
                float(obs[OBS_SCREEN_OFFSET + int(SCREEN.CARD_REWARD)]) < 0.5):
            return None
        act = int(round(float(obs[4]) * 3.0))
        if act not in (1, 2, 3):
            raise ValueError('invalid public act in card-reward observation')
        kinds = [int(np.argmax(row[:_ACTIONS])) for row in features]
        skips = [i for i, k in enumerate(kinds) if k == int(RACT.SKIP_CARD)]
        takes = [i for i, k in enumerate(kinds) if k == int(RACT.TAKE_CARD)]
        if len(skips) != 1 or not takes:
            return None
        skip_elo = self.skip_elos[act - 1] if self.skip_elo_fn is None else float(self.skip_elo_fn(obs))
        if not math.isfinite(skip_elo):
            raise ValueError('skip Elo must be finite')
        indices, scores = [skips[0]], [(skip_elo - 1500) * math.log(10) / 800]
        colorless_excluded = other_pool_excluded = unknown = zero_pick = 0
        for i in takes:
            encoded = features[i, _CARD_OFF:_CARD_OFF + CARD_COUNT]
            if not encoded.any():
                unknown += 1
                continue
            card_id = int(np.argmax(encoded))
            pool = self.pools.get(self.site.card_ids.get(card_id))
            if pool == 'colorless':
                colorless_excluded += 1
                continue
            if pool is not None and pool != 'ironclad':
                other_pool_excluded += 1
                continue
            row = self.site.card_row(card_id)
            score, known = self.score(row)
            if not known:
                unknown += 1
                continue
            indices.append(i)
            scores.append(score)
            zero_pick += int(int(row.get('picked') or 0) == 0)
        if len(indices) < 2:
            return {'act': act, 'eligible': False, 'card_count': len(takes),
                    'covered_cards': 0, 'colorless_excluded': colorless_excluded,
                    'other_pool_excluded': other_pool_excluded, 'unknown_cards': unknown, 'zero_pick_cards': 0,
                    'chose_skip': int(choice == skips[0])}
        raw = np.asarray(scores, dtype=np.float64)
        q = np.exp(raw - raw.max()); q /= q.sum()
        return {'act': act, 'eligible': True, 'indices': indices, 'target': q.astype(np.float32),
                'card_count': len(takes), 'covered_cards': len(indices)-1,
                'colorless_excluded': colorless_excluded, 'other_pool_excluded': other_pool_excluded,
                'unknown_cards': unknown, 'zero_pick_cards': zero_pick,
                'chose_skip': int(choice == skips[0])}


def backward_prior(model, weighted, prior, strength=0.05, chunk_size=16):
    """Accumulate lambda times mean KL(q_site || p_policy) on observed states."""
    if not math.isfinite(strength) or strength < 0 or chunk_size < 1:
        raise ValueError('invalid prior strength or batch size')
    eligible = []
    stats = Counter()
    for records, _advantage in weighted:
        for record in records:
            target = prior.target(record)
            if target is None:
                continue
            act = target['act']
            stats['reward_decisions'] += 1
            stats[f'act{act}_reward_decisions'] += 1
            stats[f'act{act}_chosen_skip'] += target['chose_skip']
            for key in ('card_count', 'covered_cards', 'colorless_excluded', 'other_pool_excluded',
                        'unknown_cards', 'zero_pick_cards'):
                stats[key] += target[key]
            if target['eligible']:
                stats['eligible_decisions'] += 1
                stats[f'act{act}_eligible'] += 1
                eligible.append((record, target))
    n = len(eligible)
    if not n:
        return {'strength': strength, 'ce': None, 'kl': None, **dict(stats)}
    total_ce = total_kl = 0.0
    for start in range(0, n, chunk_size):
        chunk = eligible[start:start+chunk_size]
        max_actions = max(len(record[1]) for record, _ in chunk)
        obs = np.stack([record[0] for record, _ in chunk])
        from .armg import ARMG_ACTION_DIM
        candidates = np.zeros((len(chunk), max_actions, ARMG_ACTION_DIM), dtype=np.float32)
        for i, (record, _) in enumerate(chunk):
            candidates[i, :len(record[1])] = record[1]
        logits = model(torch.from_numpy(obs), torch.from_numpy(candidates))
        ce, kl = [], []
        for i, (_record, target) in enumerate(chunk):
            logp = F.log_softmax(logits[i, target['indices']], dim=0)
            q = torch.from_numpy(target['target'])
            cross_entropy = -(q * logp).sum()
            ce.append(cross_entropy)
            kl.append(cross_entropy + (q * torch.log(q)).sum())
        chunk_ce, chunk_kl = torch.stack(ce).sum(), torch.stack(kl).sum()
        if not torch.isfinite(chunk_kl):
            raise RuntimeError('non-finite website prior loss')
        total_ce += float(chunk_ce.detach()); total_kl += float(chunk_kl.detach())
        if strength:
            (strength * chunk_kl / n).backward()
    return {'strength': strength, 'ce': total_ce/n, 'kl': total_kl/n, **dict(stats)}
