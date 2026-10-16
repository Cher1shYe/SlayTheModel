"""Rebuild whole-run-act-v1 rewards from version-neutral journal facts.

The collector records public decision states, per-action state deltas, native
combat lifecycle markers, and the terminal outcome.  Reward formulas belong
here: changing their weights must not require another game recording.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Mapping

from .act_rewards import BattleEnd, BattleStart, EpisodeRewardAccumulator
from .raw_journal import EpisodeAudit, JournalEvent, StepAudit


@dataclass(frozen=True)
class _Combat:
    combat_id: str
    start: JournalEvent
    end: JournalEvent
    steps: tuple[StepAudit, ...]
    player_alive: bool


def _fail(audit: EpisodeAudit, message: str) -> ValueError:
    return ValueError(f"episode {audit.episode_id}: {message}")


def _context_player(audit: EpisodeAudit, step: StepAudit) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    context = step.decision.payload.get("context")
    run = context.get("run_context") if isinstance(context, dict) else None
    players = run.get("players") if isinstance(run, dict) else None
    if not isinstance(players, list) or len(players) != 1 or not isinstance(players[0], dict):
        raise _fail(audit, f"step {step.global_step} lacks a single public run-context player")
    return run, players[0]


def _integer(audit: EpisodeAudit, value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _fail(audit, f"invalid {name}")
    return value


def _player_state(audit: EpisodeAudit, step: StepAudit) -> dict[str, int]:
    run, player = _context_player(audit, step)
    hp = _integer(audit, player.get("current_hp"), "current HP")
    maximum = _integer(audit, player.get("max_hp"), "maximum HP")
    act_index = _integer(audit, run.get("act_index"), "act index")
    if hp < 0 or maximum <= 0 or hp > maximum or act_index not in (0, 1, 2):
        raise _fail(audit, f"step {step.global_step} has out-of-range public run state")
    deck = player.get("deck")
    relics = player.get("relics")
    if not isinstance(deck, list) or not isinstance(relics, list):
        raise _fail(audit, f"step {step.global_step} lacks deck or relic observations")
    upgraded = 0
    for card in deck:
        if not isinstance(card, dict):
            raise _fail(audit, f"step {step.global_step} has malformed deck cards")
        level = _integer(audit, card.get("upgrade_level"), "card upgrade level")
        if level < 0:
            raise _fail(audit, "negative card upgrade level")
        upgraded += level > 0
    return {
        "hp": hp, "max_hp": maximum, "act": act_index + 1,
        "upgraded_cards": upgraded, "relics": len(relics),
    }


def _combat_lifecycle(audit: EpisodeAudit) -> tuple[_Combat, ...]:
    active: tuple[str, JournalEvent] | None = None
    combats: list[_Combat] = []
    covered: set[int] = set()
    for event in audit.events:
        if event.event_type != "diagnostic":
            continue
        code = event.payload.get("code")
        if code not in ("combat_started", "combat_ended"):
            continue
        data = event.payload.get("data")
        combat_id = data.get("combat_id") if isinstance(data, dict) else None
        if not isinstance(combat_id, str) or not combat_id:
            raise _fail(audit, f"{code} lacks a combat ID")
        if code == "combat_started":
            if active is not None:
                raise _fail(audit, "nested combat lifecycle markers")
            active = (combat_id, event)
            continue
        if active is None or active[0] != combat_id:
            raise _fail(audit, "combat end does not match its start")
        start = active[1]
        steps = tuple(
            step for step in audit.steps
            if step.domain == "combat"
            and start.event_sequence < step.decision.event_sequence < event.event_sequence
        )
        if not steps:
            raise _fail(audit, f"combat {combat_id} has no public decision state")
        if any(step.global_step in covered for step in steps):
            raise _fail(audit, "one combat decision belongs to two lifecycle intervals")
        covered.update(step.global_step for step in steps)
        data = event.payload.get("data")
        player_alive = data.get("player_alive") if isinstance(data, dict) else None
        if not isinstance(player_alive, bool):
            raise _fail(audit, f"combat {combat_id} lacks native outcome evidence")
        combats.append(_Combat(combat_id, start, event, steps, player_alive))
        active = None
    if active is not None:
        # Older collectors can publish the fatal run history before emitting
        # CombatEnded. A native defeat is itself the stronger closing fact.
        if audit.finished is None or audit.finished.payload.get("outcome") != "defeat":
            raise _fail(audit, "unclosed native combat lifecycle")
        combat_id, start = active
        steps = tuple(
            step for step in audit.steps
            if step.domain == "combat"
            and start.event_sequence < step.decision.event_sequence
            < audit.finished.event_sequence
        )
        if not steps:
            raise _fail(audit, f"fatal combat {combat_id} has no public decision state")
        covered.update(step.global_step for step in steps)
        combats.append(_Combat(combat_id, start, audit.finished, steps, False))
    all_combat = {step.global_step for step in audit.steps if step.domain == "combat"}
    if covered != all_combat:
        raise _fail(audit, "native combat lifecycle does not cover every combat decision")
    return tuple(combats)


def _hp_delta(audit: EpisodeAudit, combat: _Combat) -> int:
    total = 0
    rewarded = 0
    for step in combat.steps:
        if step.reward is None:
            continue
        components = step.reward.payload.get("components")
        value = components.get("hp_delta") if isinstance(components, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise _fail(audit, f"combat {combat.combat_id} has invalid HP transition evidence")
        if not float(value).is_integer():
            raise _fail(audit, f"combat {combat.combat_id} has fractional HP transition")
        total += int(value)
        rewarded += 1
    if not rewarded:
        raise _fail(audit, f"combat {combat.combat_id} has no HP transition evidence")
    return total


def _next_public_state(audit: EpisodeAudit, combat: _Combat) -> dict[str, int] | None:
    for step in audit.steps:
        if step.decision.event_sequence <= combat.end.event_sequence:
            continue
        if step.domain == "combat":
            return None
        return _player_state(audit, step)
    return None


def derived_act_episode_returns(audit: EpisodeAudit) -> tuple[dict[int, float], dict[str, Any]]:
    """Compute rewards without reward-specific fields in the source journal.

    Combat HP uses the first public combat decision as the pre-action anchor,
    then sums the generic whole-run-v2 HP transitions through combat end.  A
    following public state is used to cross-check HP and obtain post max HP.
    This deliberately excludes HP changes that happened before the first
    player decision; the evidence mode is written into the assembly report.
    """

    if audit.finished is None or audit.finished.payload.get("outcome") not in ("win", "defeat"):
        raise _fail(audit, "missing supported terminal outcome")
    combats = _combat_lifecycle(audit)
    accumulator = EpisodeRewardAccumulator()
    entries: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()

    def record(sequence: int, kind: str, components: dict[str, float], **extra: Any) -> None:
        amount = math.fsum(components.values())
        totals.update(components)
        entries.append({"event_sequence": sequence, "kind": kind,
                        "components": components, "reward": amount, **extra})

    cross_checked = 0
    for combat in combats:
        first = _player_state(audit, combat.steps[0])
        run, _ = _context_player(audit, combat.steps[0])
        room_type = run.get("room_type")
        if not isinstance(room_type, str):
            raise _fail(audit, f"combat {combat.combat_id} lacks room type")
        is_boss = room_type.lower() == "boss"
        start = BattleStart(
            combat.combat_id, first["act"], is_boss, first["hp"], first["max_hp"],
            first["upgraded_cards"], first["relics"],
        )
        start_components = accumulator.begin_battle(start)
        record(combat.start.event_sequence, "combat_start", start_components,
               combat_id=combat.combat_id, act=start.act, is_boss=is_boss)

        alive = combat.player_alive
        post_hp = first["hp"] + _hp_delta(audit, combat)
        following = _next_public_state(audit, combat)
        post_max = first["max_hp"]
        if following is not None:
            if following["hp"] != post_hp:
                raise _fail(audit, f"combat {combat.combat_id} HP transitions disagree with next public state")
            post_max = following["max_hp"]
            cross_checked += 1
        if post_hp < 0 or post_hp > post_max or alive != (post_hp > 0):
            raise _fail(audit, f"combat {combat.combat_id} has inconsistent terminal HP")
        won = alive
        end = BattleEnd(
            combat.combat_id, first["act"], post_hp, post_max, won,
            act_completed=won and is_boss,
        )
        end_components = accumulator.end_battle(end)
        record(combat.end.event_sequence, "combat_end", end_components,
               combat_id=combat.combat_id, act=end.act, is_boss=is_boss)

    terminal_components = accumulator.finish(audit.finished.payload["outcome"])
    record(audit.finished.event_sequence, "terminal", terminal_components)

    remaining = 0.0
    pending = len(entries) - 1
    returns: dict[int, float] = {}
    for step in reversed(audit.steps):
        sequence = step.decision.event_sequence
        while pending >= 0 and entries[pending]["event_sequence"] > sequence:
            remaining = math.fsum((remaining, entries[pending]["reward"]))
            pending -= 1
        returns[step.global_step] = remaining
    if not returns:
        raise _fail(audit, "no decisions to condition")
    return returns, {
        "outcome": audit.finished.payload["outcome"],
        "evidence_mode": "derived_from_public_journal_v1",
        "precombat_hp_anchor": "first_public_combat_decision",
        "postcombat_hp": "sum_of_whole_run_v2_hp_transitions",
        "rtg_min": min(returns.values()), "rtg_max": max(returns.values()),
        "total_reward": math.fsum(entry["reward"] for entry in entries),
        "reward_component_totals": dict(sorted(totals.items())),
        "reward_events": entries,
        "combat_boundaries": {"starts": len(combats), "ends": len(combats)},
        "postcombat_public_state_cross_checks": cross_checked,
    }


__all__ = ["derived_act_episode_returns"]
