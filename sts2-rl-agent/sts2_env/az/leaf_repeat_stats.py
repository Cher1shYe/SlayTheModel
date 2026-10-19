"""Optional exact-input repeat statistics. Never caches or substitutes model outputs."""
import json


class LeafRepeatStats:
    def __init__(self, model_sha256, capacity=4096):
        self.model_sha256 = model_sha256
        self.capacity = capacity
        self.rows = []
        self.seen = set()
        self.current = None

    def begin_decision(self, decision):
        self.seen.clear()
        self.current = dict(decision=decision, calls=0, repeats=0, untracked=0)
        self.rows.append(self.current)

    def observe(self, packed):
        if self.current is None:
            return
        # Preserve sequence and dictionary order too: no lossy state hash or HP key.
        key = json.dumps(packed, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
        self.current['calls'] += 1
        if key in self.seen:
            self.current['repeats'] += 1
        elif len(self.seen) < self.capacity:
            self.seen.add(key)
        else:
            self.current['untracked'] += 1

    def report(self):
        totals = {k: sum(row[k] for row in self.rows) for k in ('calls', 'repeats', 'untracked')}
        return dict(model_sha256=self.model_sha256, scope='exact packed input within each decision',
                    capacity=self.capacity, decisions=self.rows, **totals,
                    repeat_rate=totals['repeats'] / max(1, totals['calls']))
