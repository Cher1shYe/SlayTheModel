"""Terminal permanent-deck reward from the frozen website Elo snapshot."""
import math
import json
from pathlib import Path

from .armg_prior import LocalPrior
from .common import sim


class DeckEloReward:
    def __init__(self, data_dir):
        self.site = LocalPrior(data_dir)
        content = json.loads((Path(__file__).resolve().parents[1] /
                              'simulator/content/cards.json').read_text(encoding='utf-8'))
        self.excluded_titles = {c['title'].lower() for c in content
                                if c.get('multiplayer_only') or
                                c.get('pool') in ('curse', 'status', 'token', 'event')}
        self.excluded_titles.update(('corruption', 'sloth_status', 'break', 'grapple'))

    def __call__(self, deck):
        values = []
        missing = 0
        excluded = 0
        for card in deck:
            card_id = int(card[0])
            # Simulator titles also cover starter IDs with ambiguous content titles.
            title = sim.card_name(card_id).lower()
            if title in self.excluded_titles:
                excluded += 1
                continue
            if title in ('strike', 'defend', 'bash'):
                elo = 1150.0
            else:
                row = self.site.card_row(card_id)
                elo = row.get('elo') if row else None
                if elo is None or not math.isfinite(float(elo)):
                    elo = 1150.0
                    missing += 1
            values.append(float(elo))
        mean = sum(values) / len(values) if values else 0.0
        return dict(deck_mean_elo=mean, deck_elo_bonus=mean / 5000.0,
                    final_deck_size=len(values) + excluded, deck_elo_counted_cards=len(values),
                    deck_elo_excluded_cards=excluded, deck_elo_missing_cards=missing)
