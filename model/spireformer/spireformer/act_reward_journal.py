"""Derive event-timed act rewards without modifying the source journal.

New journals can provide exact native boundary diagnostics. Older whole-run-v2
journals use the documented public-state/HP-transition reconstruction path;
reports preserve which evidence mode and precombat anchor were used.
"""

from __future__ import annotations

from collections import Counter
import math
from typing import Any

from .act_rewards import BattleEnd, BattleStart, EpisodeRewardAccumulator
from .act_reward_derived import derived_act_episode_returns
from .raw_journal import EpisodeAudit


BOUNDARY_CODE = "act_reward_boundary"


def act_episode_returns(audit: EpisodeAudit) -> tuple[dict[int, float], dict[str, Any]]:
    boundary_events = [
        event for event in audit.events
        if event.event_type == "diagnostic"
        and event.payload.get("code") == BOUNDARY_CODE
    ]
    unavailable = [
        event for event in audit.events
        if event.event_type == "diagnostic"
        and isinstance(event.payload.get("code"), str)
        and event.payload["code"].startswith("act_reward_")
        and event.payload["code"] != BOUNDARY_CODE
    ]
    if not boundary_events:
        # Reward-specific capture is optional.  The original journal remains
        # the fact source; formulas and weights are applied offline.
        if unavailable:
            raise ValueError(
                f"episode {audit.episode_id}: reward-specific capture reported an unusable boundary"
            )
        return derived_act_episode_returns(audit)
    accumulator = EpisodeRewardAccumulator()
    active: BattleStart | None = None
    lifecycle_starts = 0
    lifecycle_ids: set[str] = set()
    starts = 0
    ends = 0
    entries: list[dict[str, Any]] = []
    components_total: Counter[str] = Counter()
    decision_sequences: list[tuple[int, int]] = []
    finished = False

    def fail(message: str) -> ValueError:
        return ValueError(f"episode {audit.episode_id}: {message}")

    def record(sequence: int, kind: str, components: dict[str, float], **extra: Any) -> None:
        amount = math.fsum(components.values())
        components_total.update(components)
        entries.append({"event_sequence": sequence, "kind": kind,
                        "components": components, "reward": amount, **extra})

    for event in audit.events:
        if finished:
            raise fail("events after terminal outcome")
        payload = event.payload
        if event.event_type == "decision":
            if payload.get("domain") == "combat" and active is None:
                raise fail("combat decision lacks explicit precombat reward boundary")
            assert event.global_step is not None
            decision_sequences.append((event.global_step, event.event_sequence))
        elif event.event_type == "diagnostic":
            code = payload.get("code")
            if code == "combat_started":
                lifecycle_starts += 1
                if active is None:
                    raise fail("native combat start lacks reward boundary evidence")
                lifecycle_data = payload.get("data")
                combat_id = lifecycle_data.get("combat_id") if isinstance(lifecycle_data, dict) else None
                if combat_id != active.combat_id or combat_id in lifecycle_ids:
                    raise fail("native combat lifecycle ID differs or is duplicated")
                lifecycle_ids.add(combat_id)
            if code != BOUNDARY_CODE:
                # A failed capture must not silently look like a fight without
                # rewards, including zero-input/automatic combats.
                if isinstance(code, str) and code.startswith("act_reward_"):
                    raise fail(f"unusable reward boundary diagnostic: {code}")
                continue
            data = payload.get("data")
            if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
                raise fail("unsupported or missing reward boundary schema")
            phase = data.get("phase")
            try:
                if phase == "combat_start":
                    if data.get("won") is not None or data.get("act_completed") is not False:
                        raise fail("invalid precombat outcome evidence")
                    start = BattleStart(
                        combat_id=data["combat_id"], act=data["act"],
                        is_boss=data["is_boss"], hp=data["hp"], max_hp=data["max_hp"],
                        upgraded_cards=data["upgraded_cards"], relics=data["relics"],
                    )
                    components = accumulator.begin_battle(start)
                    active = start
                    starts += 1
                    record(event.event_sequence, phase, components,
                           combat_id=start.combat_id, act=start.act, is_boss=start.is_boss)
                elif phase == "combat_end":
                    if active is None or data.get("is_boss") is not active.is_boss:
                        raise fail("combat end lacks matching boss classification")
                    end = BattleEnd(
                        combat_id=data["combat_id"], act=data["act"], hp=data["hp"],
                        max_hp=data["max_hp"], won=data["won"],
                        act_completed=data["act_completed"],
                    )
                    components = accumulator.end_battle(end)
                    record(event.event_sequence, phase, components,
                           combat_id=end.combat_id, act=end.act, is_boss=active.is_boss)
                    ends += 1
                    active = None
                else:
                    raise fail(f"unknown reward boundary phase: {phase!r}")
            except (KeyError, TypeError, ValueError) as exc:
                raise fail(f"invalid reward boundary at event {event.event_sequence}: {exc}") from exc
        elif event.event_type == "episode_finished":
            components = accumulator.finish(payload.get("outcome"))
            record(event.event_sequence, "terminal", components)
            finished = True

    if not finished:
        raise fail("missing terminal outcome")
    if active is not None or starts != ends:
        raise fail("unclosed reward combat boundary")
    if lifecycle_starts != starts:
        raise fail("reward boundaries do not cover native combat lifecycle")

    # Reward at boss entry belongs to the preceding navigation/event action.
    # It has already been received by the first boss decision, so exclude it
    # there. Use native event sequence, never late per-action reward writes.
    returns: dict[int, float] = {}
    pending = len(entries) - 1
    remaining = 0.0
    for global_step, sequence in reversed(decision_sequences):
        while pending >= 0 and entries[pending]["event_sequence"] > sequence:
            remaining = math.fsum((remaining, entries[pending]["reward"]))
            pending -= 1
        returns[global_step] = remaining
    if not returns:
        raise fail("no decisions to condition")
    return returns, {
        "outcome": audit.finished.payload["outcome"],
        "rtg_min": min(returns.values()), "rtg_max": max(returns.values()),
        "total_reward": math.fsum(entry["reward"] for entry in entries),
        "reward_component_totals": dict(sorted(components_total.items())),
        "reward_events": entries,
        "combat_boundaries": {"starts": starts, "ends": ends},
    }
