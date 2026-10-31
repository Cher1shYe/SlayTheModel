"""Read-only behavior audit of one frozen PPO checkpoint; no optimizer updates."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import re
import shutil

from deployment import train_armg_a10_ppo as trainer
from agent.common import RACT, SCREEN, sim
import torch


class ObservedRun:
    def __init__(self, run):
        self.run = run
        self.counts = Counter()
        self.cards = Counter()
        self.shops = set()
        self.removable_shops = set()
        self.rests = set()
        self.upgradable_rests = set()
        content = json.loads((Path(__file__).resolve().parents[1] / 'simulator/content/cards.json').read_text())
        by_title = {}
        by_id = {card['id']: card for card in content}
        for card in content:
            by_title.setdefault(card['title'], []).append(card)
        self.card_data = {}
        for i in range(sim.CARD_COUNT):
            matches = by_title.get(sim.card_name(i), [])
            self.card_data[i] = matches[0] if len(matches) == 1 else by_id.get(sim.card_name(i), {})

    def __getattr__(self, name):
        return getattr(self.run, name)

    def step(self, kind, index):
        rc = self.run
        screen, grid, act = rc.screen, int(rc.card_grid_kind), int(rc.act) + 1
        key = (act, int(rc.floor), int(rc.current_row), int(rc.current_col))
        legal = {int(a[0]) for a in rc.legal_actions()}
        if screen == SCREEN.SHOP:
            self.shops.add(key)
            if int(RACT.REMOVE_CARD) in legal:
                self.removable_shops.add(key)
        if screen == SCREEN.REST:
            self.rests.add(key)
            if int(RACT.REST_UPGRADE) in legal:
                self.upgradable_rests.add(key)
        card = None
        if screen == SCREEN.CARD_REWARD and not grid and kind == int(RACT.TAKE_CARD):
            card = int(rc.offered[index][0])
        accepted = rc.step(kind, index)
        if not accepted:
            return accepted
        if screen == SCREEN.CARD_REWARD and not grid:
            if kind in (int(RACT.TAKE_CARD), int(RACT.SKIP_CARD)):
                self.counts['card_reward_choices'] += 1
                self.counts[f'act{act}_card_reward_choices'] += 1
            if kind == int(RACT.SKIP_CARD):
                self.counts['card_reward_skips'] += 1
                self.counts[f'act{act}_card_reward_skips'] += 1
            elif card is not None:
                self.counts['card_reward_takes'] += 1
                data = self.card_data[card]
                self.cards[data.get('id', f'UNKNOWN_{card}')] += 1
                card_type = data.get('type', 'UNKNOWN')
                self.counts[f'card_type_{card_type}'] += 1
                self.counts[f'act{act}_card_type_{card_type}'] += 1
                if re.search(r'\bBlock\b', data.get('description', ''), re.I) or (data.get('base_block') or 0) > 0:
                    self.counts['block_related_cards'] += 1
                    if card_type != 'ATTACK':
                        self.counts['nonattack_block_related_cards'] += 1
        if screen == SCREEN.REST and kind == int(RACT.REST_UPGRADE):
            self.counts['campfire_upgrades'] += 1
            self.counts[f'act{act}_campfire_upgrades'] += 1
        if screen == SCREEN.REST and kind == int(RACT.REST_HEAL):
            self.counts['campfire_heals'] += 1
        if screen == SCREEN.SHOP and kind == int(RACT.REMOVE_CARD):
            self.counts['shop_removes'] += 1
            self.counts[f'act{act}_shop_removes'] += 1
        return accepted

    def summary(self):
        return dict(self.counts, shop_visits=len(self.shops),
                    shops_with_removal_available=len(self.removable_shops),
                    campfire_visits=len(self.rests),
                    campfires_with_upgrade_available=len(self.upgradable_rests))


def play(task):
    observed = []
    original = trainer.base.new_run
    def new_run(*args):
        rc = ObservedRun(original(*args))
        observed.append(rc)
        return rc
    trainer.base.new_run = new_run
    try:
        ep = trainer._play(task)
        ep.pop('records', None)
        ep.pop('ppo_records', None)
        ep['behavior'] = observed[0].summary()
        ep['selected_cards'] = dict(observed[0].cards)
        return ep
    finally:
        trainer.base.new_run = original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--games', type=int, default=32)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.checkpoint, out/'frozen.pt')
    checkpoint = torch.load(out/'frozen.pt', map_location='cpu', weights_only=False)
    config = checkpoint['settings']
    torch.save(checkpoint['state_dict'], out/'weights.pt')
    (out/'active').mkdir()
    manifest = {'checkpoint_games': checkpoint['progress']['games'], 'sampling': 'stochastic (training policy)',
                'games': args.games, 'checkpoint_sha256': hashlib.sha256((out/'frozen.pt').read_bytes()).hexdigest(),
                'training_settings': config, 'seed_base': 42050000}
    (out/'config.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    tasks = [(42050000+i, 500000+i, 700000+i*7919, 0, str(out/'weights.pt'), False,
              config['simulations'], config['combat_budget_per_floor'], config['combat_budget_elite_bonus'],
              config['combat_budget_boss_bonus'], config['max_steps'], str(out/'active'), 'oracle', 10, config['reward_mode'], config['website_snapshot_dir'])
             for i in range(args.games)]
    counts, cards = Counter(), Counter()
    episodes = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context('spawn')) as pool:
        futures = [pool.submit(play, task) for task in tasks]
        with (out/'episodes.jsonl').open('w', encoding='utf-8') as log:
            for future in as_completed(futures):
                ep = future.result()
                episodes.append(ep)
                counts.update(ep['behavior']); cards.update(ep['selected_cards'])
                log.write(json.dumps(ep) + '\n'); log.flush()
                summary = {'completed': len(episodes), 'target': args.games,
                           'checkpoint_games': manifest['checkpoint_games'],
                           'counts': dict(counts), 'cards': dict(cards.most_common()),
                           'mean_floor': sum(x['floor'] for x in episodes)/len(episodes)}
                (out/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
                print(json.dumps({'completed': len(episodes), 'target': args.games}), flush=True)


if __name__ == '__main__':
    main()
