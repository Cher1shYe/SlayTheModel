"""Versioned terminal utility; damage is measured once, never repeatedly paid."""
V1 = "win-loss-v1"
V2 = "win-first-hp-v2"
V3 = "win-timeout-hp-v3"
V4 = "fixed-roster-hp-v4"
# primary-roster-hp-v5: the frozen ENEMY_LIFECYCLE contract. Secondary summons
# and their repeated deaths/revivals never earn progress; scalar HP summaries
# describe primary obligations only.
V5 = "primary-roster-hp-v5"


V6 = "finite-primary-phases-v6"

def validate_reward(version):
    if version not in (V1, V2, V3, V4, V5, V6):
        raise ValueError("Unsupported reward version")
    return version


def terminal_reward(reason, final_hp, initial_hp, enemy_hp, enemy_max_hp, version=V1, *, enemy_initial_hp=None, enemy_roster=None):
    import math
    validate_reward(version)
    if version == V6:
        from .boss import reward_from_rows
        return reward_from_rows(reason, final_hp, initial_hp, enemy_initial_hp, enemy_hp, enemy_max_hp, enemy_roster)
    if version == V5:
        # One shared terminal contract for environment, search, replay and
        # evaluation; the immutable ledger carries every admission fact.
        from .summon import ledger_from_rows, primary_summary
        ledger = ledger_from_rows(enemy_roster)
        if primary_summary(ledger) != (enemy_initial_hp, enemy_hp, enemy_max_hp):
            raise ValueError("Primary ledger and aggregate HP disagree")
        return ledger.terminal_reward(reason, final_hp, initial_hp)
    if version == V4:
        from .multi import validate_health
        totals = validate_health(enemy_roster)
        if totals != (enemy_initial_hp, enemy_hp, enemy_max_hp):
            raise ValueError("Roster and aggregate HP disagree")
        if reason == "win" and (enemy_hp != 0 or final_hp <= 0):
            raise ValueError("Fixed-roster win requires all enemies defeated and player alive")
    if not all(math.isfinite(x) for x in (final_hp, initial_hp, enemy_hp, enemy_max_hp)):
        raise ValueError("Nonfinite HP is not a reward")
    if version in (V3, V4) and (enemy_initial_hp is None or not math.isfinite(enemy_initial_hp) or enemy_initial_hp <= 0):
        raise ValueError("Reward v3 requires positive enemy initial HP")
    if reason is None:
        return 0.0
    if reason not in ("win", "death", "time_limit"):
        raise ValueError("Exceptions are not terminal rewards")
    if version == V1:
        return 1.0 if reason == "win" else -1.0
    if initial_hp <= 0 or enemy_max_hp <= 0:
        raise ValueError("Positive initial HP required")
    if reason == "win":
        retained = min(1.0, max(0.0, final_hp / initial_hp))
        return 0.8 + 0.2 * retained
    damage = 1.0 - min(1.0, max(0.0, enemy_hp / (enemy_initial_hp if version in (V3, V4) else enemy_max_hp)))
    if version in (V3, V4) and reason == "time_limit":
        return -0.2 + 0.4 * damage
    return -1.0 + 0.2 * damage
