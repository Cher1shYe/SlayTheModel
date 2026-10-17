"""Audited single-enemy starter encounter profiles; no hidden AI state."""
from .config import CONTENT_VERSION

M6_CONTENT = "three-weak-starter-v1"
M6_INFORMATION = "three-weak-information-v1"
DECK_CONTENT = "three-weak-decks-v1"
HARD_CONTENT = "five-encounters-decks-v2"
EXPANDED_CONTENT = "seven-encounters-decks-v3"
G1_CONTENT = "g1-choices-v1"
GEN_CONTENT = "g1-generated-v1"
UP_CONTENT = "g1-upgrades-v1"
TOP_CONTENT = "g1-topdeck-v1"
LIFE_CONTENT = "g1-lifecycle-v1"
SEL_CONTENT = "g1-selection-v1"
SET_CONTENT = "g1-selection-v2"
MORPH_CONTENT = "g1-morph-v1"
MULTI_CONTENT = "g2-multi-v1"
BOSS_CONTENT = "g2-boss-v1"
EXPANSION_CONTENT = "ironclad-colorless-simple-v3"
SUMMON_CONTENT = "g2-summon-v1"  # inherits g2-multi-v1 and adds the audited Fogmog/Eye encounter
PROFILES = {
    "SHRINKER_BEETLE": dict(encounter="setup_shrinker_beetle_weak", hp=(38, 40),
                           cycle=("SHRINKER_MOVE", "CHOMP_MOVE", "STOMP_MOVE"), strength=0),
    "FUZZY_WURM_CRAWLER": dict(encounter="setup_fuzzy_wurm_crawler_weak", hp=(55, 57),
                              cycle=("FIRST_ACID_GOOP", "INHALE", "ACID_GOOP"), strength=7),
    "NIBBIT": dict(encounter="setup_nibbits_weak", hp=(42, 46),
                   cycle=("BUTT_MOVE", "SLICE_MOVE", "HISS_MOVE"), strength=2),
}
EXTRA_MOVES = ("FIRST_ACID_GOOP", "INHALE", "ACID_GOOP", "BUTT_MOVE", "SLICE_MOVE", "HISS_MOVE")
HARD_PROFILES = {**PROFILES,
    "BYGONE_EFFIGY": dict(encounter="setup_bygone_effigy_elite", hp=(127, 127),
                          cycle=("INITIAL_SLEEP_MOVE", "WAKE_MOVE", "SLASHES_MOVE"), strength=10),
    "BYRDONIS": dict(encounter="setup_byrdonis_elite", hp=(91, 94),
                     cycle=("SWOOP_MOVE", "PECK_MOVE"), strength=1),
}
HARD_MOVES = ("INITIAL_SLEEP_MOVE", "WAKE_MOVE", "SLASHES_MOVE", "SWOOP_MOVE", "PECK_MOVE")
EXPANDED_PROFILES = {**HARD_PROFILES,
    "CUBEX_CONSTRUCT": dict(encounter="setup_cubex_construct_normal", hp=(65, 65),
                            cycle=("CHARGE_UP_MOVE", "REPEATER_MOVE", "REPEATER_MOVE_2", "EXPEL_BLAST"), strength=2),
    "MAWLER": dict(encounter="setup_mawler_normal", hp=(72, 72),
                   cycle="public intent + random nonrepeat attacks; roar once", strength=0),
}
EXPANDED_MOVES = ("CHARGE_UP_MOVE", "REPEATER_MOVE", "REPEATER_MOVE_2", "EXPEL_BLAST",
                  "CLAW_MOVE", "RIP_AND_TEAR_MOVE", "ROAR_MOVE")
MAWLER_INTENTS = {"CLAW_MOVE": ("MULTI_ATTACK", 4, 2), "RIP_AND_TEAR_MOVE": ("ATTACK", 14, 1),
                  "ROAR_MOVE": ("DEBUFF", 0, 1)}


def mawler_move(intent):
    for move, value in MAWLER_INTENTS.items():
        if intent == value:
            return move
    raise ValueError("Unknown Mawler public intent")


def validate_mawler_history(history, current=None):
    sequence = history + ((current,) if current else ())
    if (sequence and sequence[0] != "CLAW_MOVE") or any(m not in MAWLER_INTENTS for m in sequence):
        raise ValueError("Invalid Mawler initial move/history")
    if sequence.count("ROAR_MOVE") > 1 or any(a == b for a, b in zip(sequence, sequence[1:])):
        raise ValueError("Invalid Mawler repeat history")


MULTI_PROFILES = {**EXPANDED_PROFILES, "NIBBIT_PAIR": dict(encounter="setup_nibbits_normal", hp=(84, 92), members=("NIBBIT", "NIBBIT"))}

# Fogmog is the only primary; the summoned EyeWithTeeth is a secondary minion
# that never blocks the native victory condition. Encounter list: the eight
# g2-multi encounters plus setup_fogmog_normal (9 encounters x 6 families x 3 HP
# tiers = 162 frozen strata).
SUMMON_PROFILES = {**MULTI_PROFILES, "FOGMOG": dict(encounter="setup_fogmog_normal", hp=(74, 74),
                                                   cycle="public intent + weighted random branch; one EyeWithTeeth summon",
                                                   strength=0)}


BOSS_PROFILES = {**SUMMON_PROFILES, "TEST_SUBJECT": dict(encounter="setup_test_subject_boss", hp=(100, 100), cycle="public finite phases", strength=0)}

def profiles(version):
    if version in (BOSS_CONTENT, EXPANSION_CONTENT):
        return BOSS_PROFILES
    if version == SUMMON_CONTENT:
        return SUMMON_PROFILES
    if version == MULTI_CONTENT:
        return MULTI_PROFILES
    if version in (EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT):
        return EXPANDED_PROFILES
    return HARD_PROFILES if version == HARD_CONTENT else PROFILES


def validate_content(version):
    if version not in (CONTENT_VERSION, M6_CONTENT, DECK_CONTENT, HARD_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT):
        raise ValueError("Unsupported content version")
    return version


def moves(monster, count):
    if monster == "CUBEX_CONSTRUCT":
        return tuple("CHARGE_UP_MOVE" if i == 0 else ("REPEATER_MOVE", "REPEATER_MOVE_2", "EXPEL_BLAST")[(i - 1) % 3] for i in range(count))
    if monster == "BYGONE_EFFIGY":
        return tuple("INITIAL_SLEEP_MOVE" if i == 0 else "WAKE_MOVE" if i == 1 else "SLASHES_MOVE" for i in range(count))
    if monster == "BYRDONIS":
        return tuple(("SWOOP_MOVE", "PECK_MOVE")[i % 2] for i in range(count))
    if monster == "SHRINKER_BEETLE":
        return tuple("SHRINKER_MOVE" if i == 0 else "CHOMP_MOVE" if i % 2 else "STOMP_MOVE" for i in range(count))
    cycle = PROFILES[monster]["cycle"]
    return tuple(cycle[i % 3] for i in range(count))


def intent_after(monster, completed):
    move = moves(monster, completed + 1)[-1]
    if monster == "CUBEX_CONSTRUCT":
        return {"CHARGE_UP_MOVE": ("BUFF", 0, 1), "REPEATER_MOVE": ("ATTACK_BUFF", 7, 1),
                "REPEATER_MOVE_2": ("ATTACK_BUFF", 7, 1), "EXPEL_BLAST": ("MULTI_ATTACK", 5, 2)}[move]
    if monster == "BYGONE_EFFIGY":
        return {"INITIAL_SLEEP_MOVE": ("SLEEP", 0, 1), "WAKE_MOVE": ("BUFF", 0, 1),
                "SLASHES_MOVE": ("ATTACK", 15, 1)}[move]
    if monster == "BYRDONIS":
        return ("ATTACK", 16, 1) if move == "SWOOP_MOVE" else ("MULTI_ATTACK", 3, 3)
    if move == "SHRINKER_MOVE":
        return ("DEBUFF_STRONG", 0, 1)
    if move in ("INHALE", "HISS_MOVE"):
        return ("BUFF", 0, 1)
    return ("ATTACK", {"CHOMP_MOVE": 7, "STOMP_MOVE": 13, "FIRST_ACID_GOOP": 4,
                       "ACID_GOOP": 4, "BUTT_MOVE": 12, "SLICE_MOVE": 6}[move], 1)


def expected_strength(monster, history):
    if monster == "MAWLER":
        return 0
    if monster == "CUBEX_CONSTRUCT":
        return 2 * sum(m != "EXPEL_BLAST" for m in history)
    if monster == "BYGONE_EFFIGY":
        return 10 * history.count("WAKE_MOVE")
    if monster == "BYRDONIS":
        return len(history)
    return PROFILES[monster]["strength"] * sum(m in ("INHALE", "HISS_MOVE") for m in history)
