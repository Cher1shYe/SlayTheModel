"""TestSubject public phase foundation, integrated by g2-boss-v1.

Ascension 0, one player, one initial primary, stable slot 0. The three fixed
forms are game rules, not sampled future HP or private AI state. A separate
versioned reward contract counts each finite form once; it must never relabel V5
Replay. No observation here reads a state id, closure, RNG or hidden card pile.
"""
from dataclasses import dataclass, replace
import math

from sts2_env.core.enums import PowerId
from sts2_env.monsters import act3 as native

VERSION = "test-subject-phase-foundation-v1"
REWARD_VERSION = "finite-primary-phases-v6"
FORM_HP = (native.TEST_SUBJECT_BASE_FIRST_FORM_HP,
           native.TEST_SUBJECT_BASE_SECOND_FORM_HP,
           native.TEST_SUBJECT_BASE_THIRD_FORM_HP)
BITE = native.TEST_SUBJECT_BITE_MOVE
SKULL = native.TEST_SUBJECT_SKULL_BASH_MOVE
POUNCE = native.TEST_SUBJECT_POUNCE_MOVE
CLAW = native.TEST_SUBJECT_MULTI_CLAW_MOVE
LACERATE = native.TEST_SUBJECT_PHASE3_LACERATE_MOVE
BIG = native.TEST_SUBJECT_BIG_POUNCE_MOVE
GROWL = native.TEST_SUBJECT_BURNING_GROWL_MOVE
RESPAWN = native.TEST_SUBJECT_RESPAWN_MOVE
KNOCKOUT, DEFEAT = "public-knockout", "public-final-defeat"
FOLLOW = {BITE: SKULL, SKULL: BITE, CLAW: POUNCE, POUNCE: CLAW,
          LACERATE: BIG, BIG: GROWL, GROWL: LACERATE}


def public_cursor(events):
    """Reduce completed visible moves/deaths; never use a native AI log."""
    if type(events) is not tuple:
        raise ValueError("Immutable public events required")
    phase, life, move, claws = 0, "alive", BITE, 0
    for event in events:
        if type(event) is not str or life == "defeated":
            raise ValueError("Invalid event after permanent defeat")
        if event == KNOCKOUT:
            if life != "alive" or phase == 2:
                raise ValueError("Only the first two forms can revive")
            life, move = "reviving", RESPAWN
        elif event == DEFEAT:
            if life != "alive" or phase != 2:
                raise ValueError("Only the last form can be permanently defeated")
            life, move = "defeated", None
        elif event == move:
            if event == RESPAWN:
                phase += 1
                life, move = "alive", CLAW if phase == 1 else LACERATE
            else:
                claws += int(event == CLAW)
                move = FOLLOW[event]
        else:
            raise ValueError("Public move contradicts the phase history")
    return phase, life, move, claws


@dataclass(frozen=True)
class BossPhaseState:
    hp: int = FORM_HP[0]
    events: tuple[str, ...] = ()
    version: str = VERSION

    def validate(self):
        phase, life, _, _ = public_cursor(self.events)
        if (self.version != VERSION or type(self.hp) is not int
                or not 0 <= self.hp <= FORM_HP[phase]
                or (self.hp > 0) != (life == "alive")):
            raise ValueError("Phase, HP or version mismatch")
        return self

    @property
    def cursor(self):
        self.validate()
        return public_cursor(self.events)

    @property
    def intent(self):
        _, life, move, claws = self.cursor
        if life == "defeated":
            return ()
        # These are native base intent values; Strength/Weak modifiers remain
        # separate public powers and are not silently folded into this history.
        return {
            BITE: (("ATTACK", native.TEST_SUBJECT_BASE_BITE_DAMAGE, 1),),
            SKULL: (("ATTACK", native.TEST_SUBJECT_BASE_SKULL_BASH_DAMAGE, 1), ("DEBUFF", 0, 1)),
            POUNCE: (("ATTACK", native.TEST_SUBJECT_BASE_POUNCE_DAMAGE, 1),),
            CLAW: (("MULTI_ATTACK", native.TEST_SUBJECT_BASE_MULTI_CLAW_DAMAGE,
                    native.TEST_SUBJECT_BASE_MULTI_CLAW_COUNT + claws),),
            LACERATE: (("MULTI_ATTACK", native.TEST_SUBJECT_BASE_MULTI_CLAW_DAMAGE,
                        native.TEST_SUBJECT_PHASE3_LACERATE_REPEAT),),
            BIG: (("ATTACK", native.TEST_SUBJECT_BIG_POUNCE_DAMAGE, 1),),
            GROWL: (("STATUS_CARD", 0, native.TEST_SUBJECT_BASE_BURNING_GROWL_BURNS), ("BUFF", 0, 1)),
            RESPAWN: (("HEAL", 0, 1), ("BUFF", 0, 1)),
        }[move]

    def with_hp(self, hp):
        """Damage/healing within a form. Zero HP needs an explicit death event."""
        self.validate()
        return replace(self, hp=hp).validate()

    def knock_out(self):
        phase, life, _, _ = self.cursor
        if life != "alive":
            raise ValueError("Cannot kill an untargetable or defeated form twice")
        event = DEFEAT if phase == 2 else KNOCKOUT
        return replace(self, hp=0, events=self.events + (event,)).validate()

    def after_move(self, visible_intent):
        """Call only after the observed move actually completed, not on preview."""
        phase, life, move, _ = self.cursor
        if life == "defeated" or visible_intent != self.intent:
            raise ValueError("Completed move differs from the public intent")
        hp = FORM_HP[phase + 1] if move == RESPAWN else self.hp
        return replace(self, hp=hp, events=self.events + (move,)).validate()

    def check_public_enemy(self, enemy, intents, *, ascension=0, players=1):
        """Validate phase facts only, not all powers or a full planner snapshot.

        Caller must retain slot identity. This method does not admit content,
        reconstruct AI, validate card state or grant permission to train.
        """
        phase, life, _, _ = self.cursor
        if (type(ascension) is not int or ascension != 0
                or type(players) is not int or players != 1
                or enemy.monster_id != native.TEST_SUBJECT_MONSTER_ID
                or enemy.current_hp != self.hp or enemy.max_hp != FORM_HP[phase]):
            raise ValueError("Unaudited Boss or phase health")
        markers = tuple(enemy.get_power_amount(p) for p in
                        (PowerId.ADAPTABLE, PowerId.PAINFUL_STABS, PowerId.NEMESIS))
        # PainfulStabs explicitly persists across owner death in native C#;
        # it is removed by the second respawn, not by the second knockout.
        expected = (1, int(phase == 1), 0) if phase < 2 else (0, 0, int(life == "alive"))
        if markers != expected:
            raise ValueError("Visible phase powers disagree with history")
        shown = tuple((i.intent_type.name, i.damage, i.hits) for i in intents)
        if life != "defeated" and shown != self.intent:
            raise ValueError("Visible intent disagrees with history")
        return self

    @property
    def damage_progress(self):
        phase, _, _, _ = self.cursor
        # Future fixed forms remain obligations from the start. Moving from a
        # knocked-out form to the next full form therefore adds zero progress.
        remaining = self.hp + sum(FORM_HP[phase + 1:])
        return 1 - remaining / sum(FORM_HP)

    @property
    def intangible_at_player_boundary(self):
        """Audited Nemesis parity after a fully completed enemy turn.

        The second respawn installs Nemesis before that turn's end hook, so
        its first toggle already happens on the revival turn. Not valid for
        arbitrary mid-hook snapshots or player cards that alter these powers.
        """
        phase, life, _, _ = self.cursor
        if phase != 2 or life == "defeated":
            return 0
        completed = sum(e in (LACERATE, BIG, GROWL) for e in self.events)
        return int(completed % 2 == 0)

    def terminal_reward(self, reason, final_hp, initial_hp):
        _, life, _, _ = self.cursor
        if (reason not in (None, "win", "death", "time_limit")
                or any(type(x) not in (int, float) or not math.isfinite(x)
                       for x in (final_hp, initial_hp))
                or final_hp < 0 or initial_hp <= 0):
            raise ValueError("Invalid terminal record")
        won = life == "defeated" and final_hp > 0
        if (reason == "win" and not won or reason == "death" and final_hp != 0
                or reason in (None, "time_limit") and (won or final_hp == 0)):
            raise ValueError("Real terminal outcome takes precedence")
        if reason is None:
            return 0.0
        if reason == "win":
            return .8 + .2 * min(1, final_hp / initial_hp)
        return (-.2 + .4 * self.damage_progress if reason == "time_limit"
                else -1 + .2 * self.damage_progress)

    def to_dict(self):
        self.validate()
        return {"version": self.version, "hp": self.hp, "events": list(self.events)}

    @classmethod
    def from_dict(cls, data):
        if (type(data) is not dict or set(data) != {"version", "hp", "events"}
                or type(data["events"]) is not list):
            raise ValueError("Invalid phase record")
        return cls(data["hp"], tuple(data["events"]), data["version"]).validate()
