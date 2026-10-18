"""Staged G2.2 reward contract, not yet an admitted AZ content/schema.

Initial primary enemies own the fixed reward budget. Secondary summons have
zero budget; neither spawning nor repeatedly killing them earns progress.
Only current, publicly settled lifecycle state is used, never cumulative damage
or a future summon/revival count. Native observers must supply those states.
"""
from dataclasses import dataclass, replace
import math

CONTRACT_VERSION = "primary-roster-hp-v5"
ALL_CONTRACT_VERSION = "initial-primary-budget-v6"
PHASES = ("alive", "reviving", "defeated", "removed")


@dataclass(frozen=True)
class EnemyLife:
    # Stable ledger slot is allocated on birth; it is not a global creature ID.
    slot: int
    monster_id: str
    primary: bool
    initial_hp: int
    max_hp: int
    hp: int
    phase: str = "alive"
    spawned: bool = False

    def validate(self, version=CONTRACT_VERSION):
        if (type(self.slot) is not int or self.slot < 0
                or type(self.monster_id) is not str or not self.monster_id
                or type(self.primary) is not bool or type(self.spawned) is not bool
                or any(type(n) is not int for n in (self.initial_hp, self.max_hp, self.hp))
                or not 0 < self.initial_hp <= self.max_hp or not 0 <= self.hp <= self.max_hp
                or self.phase not in PHASES):
            raise ValueError("Invalid public enemy lifecycle")
        if (self.phase == "alive") != (self.hp > 0):
            raise ValueError("Lifecycle/HP mismatch")
        if version == CONTRACT_VERSION and self.primary and (self.spawned or self.phase == "removed"):
            raise ValueError("Primary summons/removal need a separate budget contract")


@dataclass(frozen=True)
class EnemyLedger:
    entries: tuple[EnemyLife, ...]
    version: str = CONTRACT_VERSION

    def validate(self):
        if self.version not in (CONTRACT_VERSION, ALL_CONTRACT_VERSION) or type(self.entries) is not tuple or not self.entries:
            raise ValueError("Versioned immutable ledger required")
        seen_spawn = False
        for slot, entry in enumerate(self.entries):
            if type(entry) is not EnemyLife or entry.slot != slot:
                raise ValueError("Stable birth slots required; never compact or reuse slots")
            entry.validate(self.version)
            if seen_spawn and not entry.spawned:
                raise ValueError("Initial roster must precede summons")
            seen_spawn |= entry.spawned
        if not any(e.primary and not e.spawned for e in self.entries):
            raise ValueError("At least one initial primary enemy required")

    def spawn_secondary(self, monster_id, hp):
        self.validate()
        result = replace(self, entries=self.entries + (
            EnemyLife(len(self.entries), monster_id, False, hp, hp, hp, spawned=True),
        ))
        result.validate()
        return result

    def update(self, slot, hp, phase):
        self.validate()
        if type(slot) is not int or not 0 <= slot < len(self.entries):
            raise ValueError("Unknown lifecycle slot")
        old = self.entries[slot]
        # Defeated means permanently defeated. A temporary death is reviving.
        allowed = {
            "alive": ("alive", "reviving", "defeated", "removed"),
            "reviving": ("reviving", "alive", "defeated", "removed"),
            "defeated": ("defeated", "removed"),
            "removed": ("removed",),
        }
        if phase not in allowed[old.phase]:
            raise ValueError("Invalid lifecycle transition")
        updated = replace(old, hp=hp, phase=phase)
        result = replace(self, entries=self.entries[:slot] + (updated,) + self.entries[slot + 1:])
        result.validate()
        return result

    @property
    def damage_progress(self):
        self.validate()
        primary = tuple(e for e in self.entries if e.primary and not e.spawned)
        denominator = sum(e.initial_hp for e in primary)
        # A temporarily dead primary retains its full initial obligation until
        # it revives or the native terminal rule settles permanent defeat.
        remaining = sum(e.initial_hp if e.phase in ("reviving", "removed") else e.hp for e in primary)
        return max(0.0, min(1.0, 1.0 - remaining / denominator))

    def terminal_reward(self, reason, final_hp, initial_hp, *, blocks_combat_end=False):
        self.validate()
        if (type(blocks_combat_end) is not bool
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in (final_hp, initial_hp))
                or final_hp < 0 or initial_hp <= 0):
            raise ValueError("Invalid player HP/terminal state")
        if reason not in (None, "win", "death", "time_limit"):
            raise ValueError("Exceptions are not terminal rewards")
        defeated = all(e.phase == "defeated" for e in self.entries if e.primary)
        if self.version == ALL_CONTRACT_VERSION:
            relevant = tuple(e for e in self.entries if e.primary and (reason != "win" or not e.spawned))
            defeated = all(e.phase in ("defeated", "removed") for e in relevant)
        won = defeated and not blocks_combat_end and final_hp > 0
        if reason == "win" and not won or reason == "death" and final_hp != 0:
            raise ValueError("Terminal reason disagrees with lifecycle")
        if reason in (None, "time_limit") and (won or final_hp == 0):
            raise ValueError("True terminal outcome takes precedence over budget")
        if reason is None:
            return 0.0
        if reason == "win":
            return 0.8 + 0.2 * min(1.0, final_hp / initial_hp)
        d = self.damage_progress
        return -0.2 + 0.4 * d if reason == "time_limit" else -1.0 + 0.2 * d

    def to_dict(self):
        from dataclasses import asdict
        self.validate()
        return {"version": self.version, "entries": [asdict(e) for e in self.entries]}

    @classmethod
    def from_dict(cls, data):
        if type(data) is not dict or set(data) != {"version", "entries"} or type(data["entries"]) is not list:
            raise ValueError("Invalid lifecycle record")
        try:
            result = cls(tuple(EnemyLife(**e) for e in data["entries"]), data["version"])
            result.validate()
        except (TypeError, AttributeError) as exc:
            raise ValueError("Invalid lifecycle record") from exc
        return result
