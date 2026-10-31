"""Soft local decision priors from a frozen Spire Codex cohort snapshot.

Statistics are weak, observational preferences, not action values. Missing or
unmatched data always has nonzero neutral probability.  The special card reward
gate keeps card ranks and skip on separate scales.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .common import CARD_COUNT, RACT, SCREEN, sim
from .heuristics import run_policy
from .armg_need import need_overlay


def _softmax(x):
    x = np.asarray(x, dtype=np.float64)
    x = x - x.max()
    y = np.exp(x)
    return y / y.sum()


class LocalPrior:
    def __init__(self, data_dir):
        p = Path(data_dir)
        data = {key: json.loads((p / (key + ".json")).read_text(encoding="utf-8"))
                for key in ("cards", "relics", "potions", "community")}
        expected = {"solo", "wr50", "standard"}
        for key in ("cards", "relics", "potions"):
            if (data[key].get("character", "").upper() != "IRONCLAD"
                or not expected.issubset(set(data[key].get("bracket", "").split(":")))):
                raise ValueError(f"{key} snapshot is not the requested cohort")
        self.cards = {r["id"]: r for r in data["cards"]["rows"] if not r.get("upgraded")}
        self.relics = {r["id"]: r for r in data["relics"]["rows"] if not r.get("upgraded")}
        self.rests = {r["id"]: r for r in data["community"].get("rest_sites", [])}
        self.ancients = data["community"].get("ancient_offers", {})
        self.removed = {r["id"]: r for r in data["community"].get("most_removed", [])}
        self.skip_base = float(data["community"]["reward_skip_rate"]) / 100.0
        if not 0 < self.skip_base < 1:
            raise ValueError("invalid cohort skip rate")
        content = json.loads((Path(__file__).resolve().parents[1] /
                              "simulator/content/cards.json").read_text(encoding="utf-8"))
        titles = {}
        for card in content:
            titles.setdefault(card["title"], []).append(card["id"])
        self.card_ids = {}
        for n in range(CARD_COUNT):
            ids = titles.get(sim.card_name(n), [])
            if len(ids) == 1:
                self.card_ids[n] = ids[0]
        self.relic_ids = {int(v): k for k, v in sim.RelicId.__members__.items()}

    def card_row(self, card_id):
        name = self.card_ids.get(int(card_id))
        if not name:
            return None
        if name in self.cards:
            return self.cards[name]
        return self.cards.get(name[:-5]) if name.endswith("_CARD") else None

    @staticmethod
    def rating(row):
        if row is None or row.get("elo") is None:
            return 0.0, False
        n = max(0, int(row.get("offered") or 0))
        picks = max(0, int(row.get("picked") or 0))
        if not n or not picks:
            return 0.0, False
        # Small samples shrink to a neutral score; T=2 softens BT Elo.
        confidence = min(n, picks * 2) / (min(n, picks * 2) + 50.0)
        return float(np.clip((float(row["elo"]) - 1500.0) * math.log(10) / 800 * confidence, -1.5, 1.5)), True

    def action_sources(self, rc, actions, decision_source):
        """Provenance for each legal candidate (not a claim of reliable value)."""
        result = []
        for kind, idx in actions:
            kind, idx = int(kind), int(idx)
            source = "rule" if decision_source != "neutral" else "neutral"
            if decision_source.startswith("card_"):
                if kind == int(RACT.TAKE_CARD):
                    _, covered = self.rating(self.card_row(int(rc.offered[idx][0])))
                    source = "card_website_rule" if covered else "card_rule_neutral"
                elif kind == int(RACT.SKIP_CARD):
                    source = "skip_website_rule"
                elif kind == int(RACT.SACRIFICE_CARD_REWARD):
                    source = "sacrifice_rule"
                else:
                    source = "neutral"
            elif decision_source == "rest_website":
                source = "rest_website"
            elif decision_source == "ancient_website_rule" and kind == int(RACT.EVENT_CHOICE):
                if 0 <= idx < len(rc.event_relics):
                    name = self.relic_ids.get(int(rc.event_relics[idx]), "")
                    row = self.ancients.get(name)
                    if row and int(row.get("offered") or 0) >= 10:
                        source = "ancient_website_rule"
            elif decision_source == "remove_website_rule" and kind == int(RACT.REMOVE_CARD):
                name = self.card_ids.get(int(rc.deck[idx][0]), "")
                if name in self.removed or name.removesuffix("_CARD") in self.removed:
                    source = "remove_website_rule"
            result.append(source)
        return result

    def distribution(self, rc, actions):
        """Return legal-action probabilities and provenance of this decision."""
        n = len(actions)
        if not n:
            raise ValueError("empty legal actions")
        actions = [(int(k), int(i)) for k, i in actions]
        if n == 1:
            return np.ones(1, dtype=np.float64), "forced"
        take = [i for i, (k, _) in enumerate(actions) if k == int(RACT.TAKE_CARD)]
        skip = [i for i, (k, _) in enumerate(actions) if k == int(RACT.SKIP_CARD)]
        sacrifice = [i for i, (k, _) in enumerate(actions) if k == int(RACT.SACRIFICE_CARD_REWARD)]
        if rc.screen == SCREEN.CARD_REWARD and take and (skip or sacrifice):
            scores, covered = [], 0
            bonuses, _, active = need_overlay(rc, actions)
            for i in take:
                _, idx = actions[i]
                score, has_data = self.rating(self.card_row(int(rc.offered[idx][0])))
                covered += int(has_data)
                scores.append(score + (0.25 * float(bonuses[i]) if active else 0))
            choices = _softmax(scores)
            # The population's skip rate is a weak intercept, not the current
            # screen's empirical probability. Context terms are hypotheses.
            delta = 0.18 * np.clip((len(rc.deck) - 15) / 10, -1, 1)
            delta -= 0.25 * float(np.clip(max(scores), -1, 1))
            logit = math.log(self.skip_base / (1 - self.skip_base)) + delta
            p_skip = float(np.clip(1 / (1 + math.exp(-logit)), 0.05, 0.80))
            q = np.zeros(n, dtype=np.float64)
            q[take] = (1 - p_skip) * choices
            if sacrifice and skip:
                q[skip] = p_skip * .25 / len(skip)
                q[sacrifice] = p_skip * .75 / len(sacrifice)
            else:
                omissions = skip or sacrifice
                q[omissions] = p_skip / len(omissions)
            # Out-of-combat potion actions may coexist with the card screen.
            # Keep them legal and exploratory, rather than silently zeroing.
            other = [i for i in range(n) if i not in take + skip + sacrifice]
            if other:
                q *= .98
                q[other] = .02 / len(other)
            return q / q.sum(), ("card_website" if covered else "card_rule")

        rest_kind = {int(RACT.REST_HEAL): "HEAL", int(RACT.REST_UPGRADE): "SMITH",
                     int(RACT.REST_DIG): "DIG", int(RACT.REST_LIFT): "LIFT",
                     int(RACT.REST_CLONE): "CLONE"}
        if rc.screen == SCREEN.REST and all(k in rest_kind for k, _ in actions):
            counts = {k: sum(a[0] == k for a in actions) for k in rest_kind}
            field = "pct_low_hp" if rc.hp * 2 < rc.max_hp else "pct_high_hp"
            weights = []
            for k, _ in actions:
                row = self.rests.get(rest_kind[k], {})
                weights.append((float(row.get(field) or 0.5) + 0.5) / counts[k])
            return np.asarray(weights) / sum(weights), "rest_website"

        scores = np.zeros(n, dtype=np.float64)
        source = "rule"
        try:
            preferred = tuple(map(int, run_policy(rc)))
            if preferred in actions:
                scores[actions.index(preferred)] += 0.8
        except (RuntimeError, ValueError, IndexError, AttributeError):
            source = "neutral"
        for i, (kind, idx) in enumerate(actions):
            rid = None
            if kind == int(RACT.EVENT_CHOICE) and 0 <= idx < len(rc.event_relics):
                rid = int(rc.event_relics[idx])
            elif kind == int(RACT.TAKE_RELIC_REWARD) and 0 <= idx < len(rc.reward_relics):
                rid = int(rc.reward_relics[idx][0])
            elif kind == int(RACT.BUY_RELIC) and 0 <= idx < len(rc.shop_relics):
                # Shop availability and value are not the free-relic choice;
                # the general rule prior handles these without mixing statistics.
                continue
            if rid is not None:
                name = self.relic_ids.get(rid, "")
                row = self.ancients.get(name)
                if row and int(row.get("offered") or 0) >= 10:
                    p = float(row.get("take_rate") or 0) / 100
                    conf = int(row["offered"]) / (int(row["offered"]) + 50)
                    scores[i] += np.clip((p - .33) * 2 * conf, -.6, .6)
                    source = "ancient_website_rule"
            if kind == int(RACT.REMOVE_CARD) and 0 <= idx < len(rc.deck):
                card_name = self.card_ids.get(int(rc.deck[idx][0]), "")
                row = self.removed.get(card_name) or self.removed.get(card_name.removesuffix("_CARD"))
                if row:
                    scores[i] += min(.5, math.log1p(int(row["count"])) / 20)
                    source = "remove_website_rule"
        return _softmax(scores), source
