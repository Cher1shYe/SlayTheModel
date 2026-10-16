"""Public TestSubject enemy reconstruction, ahead of full Boss content admission.

The snapshot contains only public phase events, HP, block and power amounts.
It deliberately contains no world, RNG, creature ID or native AI closure.
Caller restores player/cards/choice continuation separately. Only stable player
decision boundaries with the audited powers are supported.
"""
from dataclasses import dataclass

import sts2_env.powers  # noqa: F401  native factory requires registration
from sts2_env.core.enums import PowerId
from sts2_env.monsters.act3 import create_test_subject
from .boss_phases import BossPhaseState, FORM_HP, KNOCKOUT, DEFEAT, RESPAWN

VERSION = "test-subject-public-enemy-v1"
POWERS = ("ADAPTABLE", "ENRAGE", "INTANGIBLE", "NEMESIS", "PAINFUL_STABS",
          "STRENGTH", "VULNERABLE")


@dataclass(frozen=True)
class BossEnemySnapshot:
    phase: BossPhaseState
    block: int
    powers: tuple[tuple[str, int], ...]
    version: str = VERSION

    def validate(self):
        if (self.version != VERSION or type(self.phase) is not BossPhaseState
                or type(self.block) is not int or self.block < 0
                or type(self.powers) is not tuple):
            raise ValueError("Invalid public Boss snapshot")
        phase, life, _, _ = self.phase.cursor
        names = []
        for item in self.powers:
            if (type(item) is not tuple or len(item) != 2 or item[0] not in POWERS
                    or type(item[1]) is not int or item[1] <= 0):
                raise ValueError("Invalid or unaudited Boss power")
            names.append(item[0])
        if names != sorted(set(names)):
            raise ValueError("Canonical distinct Boss powers required")
        powers = dict(self.powers)
        expected = {
            "ADAPTABLE": int(phase < 2),
            "ENRAGE": 2 * int(phase == 0 and life == "alive"),
            "PAINFUL_STABS": int(phase == 1),
            "NEMESIS": int(phase == 2 and life == "alive"),
            "INTANGIBLE": self.phase.intangible_at_player_boundary,
        }
        if any(powers.get(name, 0) != amount for name, amount in expected.items()):
            raise ValueError("Boss powers contradict public phase history")
        if life != "alive" and (self.block or powers.get("STRENGTH") or powers.get("VULNERABLE")):
            raise ValueError("Dead form retains unaudited block or powers")
        return self

    def to_dict(self):
        self.validate()
        return {"version": self.version, "phase": self.phase.to_dict(),
                "block": self.block, "powers": [list(p) for p in self.powers]}

    @classmethod
    def from_dict(cls, data):
        if (type(data) is not dict or set(data) != {"version", "phase", "block", "powers"}
                or type(data["powers"]) is not list
                or any(type(p) is not list for p in data["powers"])):
            raise ValueError("Invalid public Boss record")
        return cls(BossPhaseState.from_dict(data["phase"]), data["block"],
                   tuple(tuple(p) for p in data["powers"]), data["version"]).validate()


def capture_enemy(enemy, visible_intents, phase):
    """Read public fields only; caller supplies independently recorded events."""
    phase.check_public_enemy(enemy, visible_intents)
    powers = tuple(sorted((p.name, value.amount) for p, value in enemy.powers.items()))
    return BossEnemySnapshot(phase, enemy.block, powers).validate()


def create_enemy(snapshot, rng):
    """Allocate a fresh native closure. Restore after the particle starts combat."""
    if type(snapshot) is not BossEnemySnapshot:
        raise TypeError("Only a public Boss snapshot is accepted")
    snapshot.validate()
    phase, life, _, claws = snapshot.phase.cursor
    if life == "defeated":
        raise ValueError("Terminal snapshots cannot create actionable particles")
    enemy, ai = create_test_subject(rng, completed_respawns=phase, completed_multi_claws=claws)
    ai._az_boss_restore_identity = (enemy, phase, claws)
    return enemy, ai


def restore_enemy(enemy, ai, snapshot):
    """Hydrate the pair returned by create_enemy, after world.start_combat().

    No history effects are replayed: respawns, damage and generated cards must
    not occur while hydrating a snapshot. All mutable powers belong to this
    new creature. Native private fields are written only in the new particle.
    """
    if type(snapshot) is not BossEnemySnapshot:
        raise TypeError("Only a public Boss snapshot is accepted")
    snapshot.validate()
    phase, life, move, claws = snapshot.phase.cursor
    if life == "defeated" or enemy.monster_id != "TEST_SUBJECT":
        raise ValueError("Cannot hydrate a defeated or different enemy")
    if getattr(ai, "_az_boss_restore_identity", None) != (enemy, phase, claws):
        raise ValueError("Fresh particle closure does not match public memory")
    enemy.max_hp, enemy.current_hp, enemy.block = FORM_HP[phase], snapshot.phase.hp, snapshot.block
    enemy.escaped = False
    enemy._death_processed = life == "reviving"
    enemy.powers.clear()
    for name, amount in snapshot.powers:
        enemy.apply_power(PowerId[name], amount)
    if PowerId.ADAPTABLE in enemy.powers:
        enemy.powers[PowerId.ADAPTABLE].is_reviving = life == "reviving"
    if PowerId.NEMESIS in enemy.powers:
        enemy.powers[PowerId.NEMESIS]._should_apply_intangible = bool(snapshot.phase.intangible_at_player_boundary)
    if PowerId.INTANGIBLE in enemy.powers:
        enemy.powers[PowerId.INTANGIBLE].skip_next_tick = True
    ai.state_log = [e for e in snapshot.phase.events if e not in (KNOCKOUT, DEFEAT)]
    ai._current_state_id = move
    ai._performed_first_move = bool(ai.state_log)
    # Every returned intent is pending. In particular a knocked-out second
    # form must perform RESPAWN again even if the first respawn was observed.
    ai.states[RESPAWN]._performed_at_least_once = False
    snapshot.phase.check_public_enemy(enemy, ai.current_move.intents)
    del ai._az_boss_restore_identity
    return enemy, ai
