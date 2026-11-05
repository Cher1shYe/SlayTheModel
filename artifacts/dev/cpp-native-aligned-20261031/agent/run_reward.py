"""Per-run terminal reward and permanent-deck Elo for the Ironclad trainer.

    R = sum_i [(L_i * i) / 20 + (i / 10) * E_i]
        + sum_{k=1..B} k / 2
        + 0.05 * U + 0.02 * D
        + mean_Elo / 600

``i`` is the 1-based act, ``L_i`` the highest act-local floor actually reached
acts never entered contribute 0, ``E_i`` the elites defeated in that act, ``B``
the bosses defeated in order, ``U`` successful campfire upgrades and ``D``
successful shop removals. Only a normal game over (win or death) is scored;
errors and truncations never receive this reward.

Elo uses the frozen Spire Codex snapshot named by ``DEFAULT_ELO_SNAPSHOT``. Its
identity (file hashes, row counts, matching rule, missing counts) is recorded so
a number can be traced back to data. Missing Elo is *not* zero: the spec assigns
1150 to Strike/Defend/Bash and to cards without a usable rating, and the count
of such cards is reported separately.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .common import sim

DEFAULT_ELO_SNAPSHOT = Path(r"D:/sts2_datacollection/sts2/runs/"
                            r"armg_spire_wr50_prior_20261030/data")

# Native card-pool names whose cards never score Elo. Their ids also never
# enter the denominator.
_EXCLUDED_POOLS = frozenset({"CURSE", "STATUS", "TOKEN", "EVENT"})
# Card names (lower-case) excluded by explicit rule.
_EXCLUDED_NAMES = frozenset({"corruption", "break", "grapple"})
_FLAT_ELO_NAMES = frozenset({"strike", "defend", "bash"})
_FLAT_ELO = 1150.0
UPGRADED_SUFFIX = "+"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _snapshot_key(name: str) -> str:
    """Card title -> the snapshot's snake-case row id.

    Apostrophes are dropped (``Pact's End`` -> ``PACTS_END``), other
    punctuation becomes a separator (``Fight Me!`` -> ``FIGHT_ME``), and runs
    of separators collapse to one underscore.
    """
    cleaned = "".join(" " if not (ch.isalnum() or ch == "'") else ch
                      for ch in name.upper()).replace("'", "")
    return "_".join(cleaned.split())


class DeckElo:
    """Permanent-deck mean Elo from a frozen snapshot, per card copy."""

    def __init__(self, data_dir=DEFAULT_ELO_SNAPSHOT):
        self.data_dir = Path(data_dir or DEFAULT_ELO_SNAPSHOT)
        self.manifest = json.loads((self.data_dir / "manifest.json").read_text(encoding="utf-8"))
        cards = json.loads((self.data_dir / "cards.json").read_text(encoding="utf-8"))
        grouped = {}
        for row in cards["rows"]:
            if row.get("upgraded"):
                continue
            grouped.setdefault(row["id"], row)
        self.rows = grouped
        self.snapshot_sha256 = _sha256(self.data_dir / "cards.json")
        self.manifest_sha256 = _sha256(self.data_dir / "manifest.json")
        self.manifest_declared_sha256 = self.manifest.get("snapshots", {}).get("cards", {}).get("sha256")
        if self.manifest_declared_sha256 and self.manifest_declared_sha256 != self.snapshot_sha256:
            raise ValueError("frozen Elo cards.json does not match its manifest hash")
        self.row_count = len(cards["rows"])
        self.matched_names = 0
        self.unmatched_names = 0
        self.name_to_row = {}
        for card_id in range(1, sim.CARD_COUNT):
            upper = _snapshot_key(sim.card_name(card_id))
            row = self.rows.get(upper)
            if row is None and upper.endswith("_CARD"):
                row = self.rows.get(upper[:-5])
            if row is None:
                self.unmatched_names += 1
                continue
            self.matched_names += 1
            self.name_to_row[card_id] = row

    def countable(self, card_id: int) -> bool:
        if not sim.card_native_available(int(card_id)):
            return False
        if sim.card_multiplayer_only(int(card_id)):
            return False
        if sim.card_pool_name(int(card_id)) in _EXCLUDED_POOLS:
            return False
        return sim.card_name(int(card_id)).lower() not in _EXCLUDED_NAMES

    def card_elo(self, card_id: int) -> tuple[float, bool]:
        """(elo, used_fallback). Upgraded cards use the base card's rating."""
        name = sim.card_name(int(card_id)).lower()
        if name in _FLAT_ELO_NAMES:
            return _FLAT_ELO, False
        row = self.name_to_row.get(int(card_id))
        if row is None:
            return _FLAT_ELO, True
        elo = row.get("elo")
        if elo is None or not math.isfinite(float(elo)):
            return _FLAT_ELO, True
        return float(elo), False

    def __call__(self, deck) -> dict:
        total = 0.0
        counted = missing = excluded = 0
        for card in deck:
            card_id = int(card[0])
            if not self.countable(card_id):
                excluded += 1
                continue
            elo, fallback = self.card_elo(card_id)
            total += elo
            counted += 1
            missing += int(fallback)
        # An empty countable deck contributes 0, not a divide-by-zero.
        mean = total / counted if counted else 0.0
        return {"deck_mean_elo": mean, "deck_elo_counted": counted,
                "deck_elo_excluded": excluded, "deck_elo_missing": missing,
                "deck_elo_bonus": mean / 600.0}

    def identity(self) -> dict:
        return {"path": str(self.data_dir), "source": self.manifest.get("snapshots", {}),
                "cards_sha256": self.snapshot_sha256,
                "manifest_sha256": self.manifest_sha256,
                "rows": self.row_count, "matched_card_ids": self.matched_names,
                "unmatched_card_ids": self.unmatched_names,
                "flat_elo_cards": sorted(_FLAT_ELO_NAMES), "flat_elo": _FLAT_ELO,
                "excluded_pools": sorted(_EXCLUDED_POOLS),
                "excluded_names": sorted(_EXCLUDED_NAMES),
                "matching_rule": "title -> upper snake (punctuation dropped, "
                                 "spaces collapsed to _), strip trailing _CARD; "
                                 "rows with upgraded=true ignored"}


class RunRewardTracker:
    """Accumulates the terminal-reward components while a run is played."""

    def __init__(self):
        self.act_floor = {}     # act -> highest act-local floor reached
        self.elites = {}        # act -> elites defeated
        self.bosses = 0
        self.upgrades = 0
        self.removals = 0
        self.events = []        # audit trail of scored actions

    def observe(self, rc) -> None:
        """Record position for the act the run is currently in."""
        if rc.screen != sim.RunScreen.RUN_OVER:
            act = int(rc.act) + 1
            floor = int(rc.act_floor)
            if floor > self.act_floor.get(act, 0):
                self.act_floor[act] = floor

    def boss_defeated(self):
        self.bosses += 1
        return {"kind": "boss", "index": self.bosses}

    def elite_defeated(self, act: int):
        act = max(1, int(act))
        self.elites[act] = self.elites.get(act, 0) + 1
        return {"kind": "elite", "act": act}

    def upgraded(self):
        self.upgrades += 1
        return {"kind": "campfire_upgrade"}

    def removed(self):
        self.removals += 1
        return {"kind": "shop_removal"}

    def cumulative(self) -> float:
        """Reward earned so far; the Elo term is terminal-only and added last."""
        c = self.components()
        return (c["floor_reward"] + c["elite_bonus"] + c["boss_bonus"]
                + c["upgrade_bonus"] + c["removal_bonus"])

    def components(self) -> dict:
        floor_term = sum(self.act_floor.get(i, 0) * i / 20.0 for i in range(1, 5))
        elite_term = sum((i / 10.0) * self.elites.get(i, 0) for i in range(1, 5))
        boss_term = sum(k / 2.0 for k in range(1, self.bosses + 1))
        return {"floor_reward": floor_term, "elite_bonus": elite_term,
                "boss_bonus": boss_term, "upgrade_bonus": 0.05 * self.upgrades,
                "removal_bonus": 0.02 * self.removals,
                "campfire_upgrades": self.upgrades, "shop_removals": self.removals,
                "bosses": self.bosses, "elites_by_act": dict(self.elites),
                "max_floor_by_act": dict(self.act_floor)}


def terminal_reward(components: dict, deck_elo_bonus: float = 0.0) -> float:
    """Sum the components; the permanent-deck Elo term is the last one."""
    if not 0 <= components["bosses"] <= 4:
        raise ValueError("a run cannot defeat more than four bosses")
    if not math.isfinite(deck_elo_bonus):
        raise ValueError("non-finite deck Elo bonus")
    value = (components["floor_reward"] + components["elite_bonus"]
             + components["boss_bonus"] + components["upgrade_bonus"]
             + components["removal_bonus"] + deck_elo_bonus)
    if not math.isfinite(value):
        raise ValueError("non-finite terminal reward")
    return value
