"""Convert verified collector journals into versioned tensor shard datasets.

BC-only retains a constant zero return input. Optional whole-run schemes use
verified outcomes, HP changes, or explicit native battle boundaries to derive
decision returns, without passing future facts to the state feature encoder.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import torch

from .batch import DecisionDomain
from .data import TensorShardWriter
from .raw_features import RawFeatureEncoder, RawFeatureSpec
from .raw_journal import EpisodeAudit, StepAudit, load_episode
from .rewards import WIN_RTG_SCHEME, win_returns_to_go, win_reward_parameters
from .act_rewards import ACT_RTG_SCHEME, act_reward_parameters
from .act_reward_journal import act_episode_returns
from .trajectory import Trajectory, TrajectoryStep


TENSORIZER_VERSION = "collector-raw-bc-v3"
REWARD_VERSION = "bc-only-v1"
BC_ONLY_SCHEME = "bc-only"
HP_SAFE_RTG_SCHEME = "whole-run-hp-safe-v1"
HP_SAFE_RTG_REWARD_VERSION = HP_SAFE_RTG_SCHEME
HP_SAFE_FRACTION = 0.5
HP_SHAPING_WEIGHT = 0.2
REWARD_SCHEMES = (BC_ONLY_SCHEME, HP_SAFE_RTG_SCHEME, WIN_RTG_SCHEME, ACT_RTG_SCHEME)
POLICY_TEACHER_INFORMATION = {
    "native-mcts": "native_checkpoint_privileged",
    "first-legal": "public_observation",
}
_CUT_EVENTS = frozenset({"coverage_gap", "save_load"})
_EPISODE_PREFIX = re.compile(r"[0-9a-f]{8,32}\Z")


@dataclass(frozen=True)
class AssemblyResult:
    output: Path
    report: Mapping[str, Any]


def _source_paths(inputs: Sequence[str | Path]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            # Published journals only.  Partial and quarantined files are not
            # training inputs even when they are present beneath this folder.
            paths.update(item for item in path.glob("*.jsonl") if item.is_file())
        elif path.is_file() and path.suffix == ".jsonl":
            paths.add(path)
        else:
            raise ValueError(f"input must be a published .jsonl file or directory: {path}")
    if not paths:
        raise ValueError("no published JSONL files were found")
    return tuple(sorted(paths))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _peek_episode_id(path: Path) -> str:
    """Use the header only to locate requested files, never to validate them."""

    with path.open("rb") as stream:
        first_line = stream.readline()
    try:
        value = json.loads(first_line).get("episode_id")
    except (UnicodeError, ValueError, AttributeError):
        return ""
    return value.replace("-", "").lower() if isinstance(value, str) else ""


def _select_splits(
    audits: Sequence[EpisodeAudit],
    train_episodes: Sequence[str],
    val_episodes: Sequence[str],
    test_episodes: Sequence[str],
    holdout_episodes: Sequence[str] = (),
) -> dict[str, tuple[EpisodeAudit, ...]]:
    by_id: dict[str, EpisodeAudit] = {}
    for audit in audits:
        normalized = audit.episode_id.replace("-", "").lower()
        if normalized in by_id:
            raise ValueError(f"duplicate episode ID in inputs: {normalized}")
        by_id[normalized] = audit

    if holdout_episodes and (train_episodes or val_episodes or test_episodes):
        raise ValueError("holdout episodes cannot be combined with training splits")
    if not train_episodes and not val_episodes and not test_episodes and not holdout_episodes:
        if len(audits) != 1:
            raise ValueError(
                "multiple raw episodes require explicit --train-episode selectors; "
                "historical journals include known semantic defects"
            )
        return {"train": tuple(audits)}
    if not train_episodes and not holdout_episodes:
        raise ValueError("explicit splits require at least one --train-episode")

    assigned: set[str] = set()
    result: dict[str, tuple[EpisodeAudit, ...]] = {}
    split_selectors = (
        (("holdout", holdout_episodes),)
        if holdout_episodes else
        (("train", train_episodes), ("val", val_episodes), ("test", test_episodes))
    )
    for split, prefixes in split_selectors:
        chosen: list[EpisodeAudit] = []
        for raw_prefix in prefixes:
            prefix = raw_prefix.replace("-", "").lower()
            if _EPISODE_PREFIX.fullmatch(prefix) is None:
                raise ValueError(f"episode selector must be 8-32 hex characters: {raw_prefix!r}")
            matches = [key for key in by_id if key.startswith(prefix)]
            if len(matches) != 1:
                raise ValueError(
                    f"episode selector {raw_prefix!r} matched {len(matches)} episodes; expected exactly one"
                )
            episode_id = matches[0]
            if episode_id in assigned:
                raise ValueError(f"episode {episode_id} appears in more than one split")
            assigned.add(episode_id)
            chosen.append(by_id[episode_id])
        if chosen:
            result[split] = tuple(sorted(chosen, key=lambda audit: audit.episode_id))
    return result


def _policy_exclusion_reason(
    step: StepAudit, allowed_policy_ids: Sequence[str] = (),
) -> str | None:
    """Keep teacher provenance distinct from the student's public observation.

    Opt-in never repairs unknown information regimes or makes an omniscient
    teacher human. This metadata is audit-only and is not an encoder input.
    """
    if step.actor == "human":
        return None
    if step.actor != "policy" or not allowed_policy_ids:
        return "actor_not_human"
    policy = step.submission.payload.get("policy", {}) if step.submission else {}
    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or policy_id not in allowed_policy_ids:
        return "policy_not_allowed"
    expected = POLICY_TEACHER_INFORMATION.get(policy_id)
    if expected is None or policy.get("teacher_information") != expected:
        return "policy_teacher_information_unverified"
    return None


def _training_decisions(
    audits: Iterable[EpisodeAudit], allowed_policy_ids: Sequence[str] = (),
) -> Iterable[Mapping[str, Any]]:
    for audit in audits:
        for step in audit.steps:
            if (step.bc_eligible and _policy_exclusion_reason(step, allowed_policy_ids) is None
                    and not _semantic_reasons(step)):
                yield step.decision.payload


def _semantic_reasons(step: StepAudit) -> tuple[str, ...]:
    """Reject known historical legal-set/observation mismatches.

    These checks compare *native identifiers only within the same decision*.
    The identifiers are neither fitted into the vocabulary nor emitted as
    numeric features.  Earlier collector builds compressed sparse potion slots
    and once offered an already queued card a second time; both produced a
    structurally valid journal with an invalid action meaning.  The run
    context's public potion slots provide an independent same-step reference
    that also catches an incorrect observed slot pointing to another potion.
    """

    if step.domain != "combat":
        return ()
    payload = step.decision.payload
    observation = payload["observation"]
    players = observation.get("players")
    if not isinstance(players, list):
        return ("combat_players_missing",)
    by_id = {
        player.get("player_id"): player
        for player in players
        if isinstance(player, dict)
    }
    context = payload.get("context")
    run_context = context.get("run_context") if isinstance(context, dict) else None
    run_players = run_context.get("players") if isinstance(run_context, dict) else None
    run_by_id = {
        player.get("player_id"): player
        for player in run_players
        if isinstance(player, dict)
    } if isinstance(run_players, list) else {}
    pending = observation.get("pending_manual_actions") or []
    queued_cards = {
        (action.get("actor_player_id"), action.get("combat_card_index"))
        for action in pending
        if isinstance(action, dict) and action.get("kind") == "play_card"
    }
    reasons: set[str] = set()
    for player_id, player in by_id.items():
        observed_potions = player.get("potions") or []
        reference_player = run_by_id.get(player_id)
        if reference_player is None:
            if observed_potions:
                reasons.add("potion_run_context_missing")
            continue
        reference_potions = reference_player.get("potions") or []
        observed_slots = [
            (item.get("slot_index"), item.get("model_id"))
            for item in observed_potions
            if isinstance(item, dict)
        ]
        reference_slots = [
            (item.get("slot_index"), item.get("model_id"))
            for item in reference_potions
            if isinstance(item, dict)
        ]
        if (
            len(observed_slots) != len(observed_potions)
            or len(reference_slots) != len(reference_potions)
            or any(
                type(slot) is not int or not isinstance(model, str)
                for slot, model in (*observed_slots, *reference_slots)
            )
        ):
            reasons.add("potion_slots_disagree_with_run_context")
        elif (
            len(set(observed_slots)) != len(observed_slots)
            or len(set(reference_slots)) != len(reference_slots)
            or set(observed_slots) != set(reference_slots)
        ):
            reasons.add("potion_slots_disagree_with_run_context")
    for action in payload["legal_actions"]:
        kind = action.get("kind")
        if kind not in ("play_card", "use_potion"):
            continue
        player = by_id.get(action.get("actor_player_id"))
        if not isinstance(player, dict):
            reasons.add("action_player_missing")
            continue
        if kind == "use_potion":
            potions = player.get("potions") or []
            if not any(
                isinstance(potion, dict)
                and potion.get("slot_index") == action.get("potion_index")
                for potion in potions
            ):
                reasons.add("potion_slot_not_in_observation")
        else:
            piles = player.get("piles") or []
            in_hand = any(
                isinstance(pile, dict)
                and pile.get("pile_type") == "Hand"
                and any(
                    isinstance(card, dict)
                    and card.get("combat_card_index") == action.get("combat_card_index")
                    for card in pile.get("cards", [])
                )
                for pile in piles
            )
            if not in_hand:
                reasons.add("play_card_not_in_hand")
            if (action.get("actor_player_id"), action.get("combat_card_index")) in queued_cards:
                reasons.add("queued_card_offered_again")
    return tuple(sorted(reasons))


def _decision_hp(step: StepAudit) -> tuple[int, int, int]:
    """Read one player's HP at the decision boundary from two public views."""

    payload = step.decision.payload
    context = payload.get("context")
    run_context = context.get("run_context") if isinstance(context, dict) else None
    players = run_context.get("players") if isinstance(run_context, dict) else None
    if not isinstance(players, list) or len(players) != 1 or not isinstance(players[0], dict):
        raise ValueError(f"step {step.global_step} requires exactly one run-context player")
    player = players[0]
    player_id = player.get("player_id")
    current_hp = player.get("current_hp")
    max_hp = player.get("max_hp")
    if (
        type(player_id) is not int
        or type(current_hp) is not int
        or type(max_hp) is not int
        or max_hp <= 0
        or current_hp < 0
        or current_hp > max_hp
    ):
        raise ValueError(f"step {step.global_step} has invalid run-context HP")

    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise ValueError(f"step {step.global_step} has no observation")
    observed = (
        observation.get("creatures")
        if step.domain == "combat"
        else observation.get("players")
    )
    if not isinstance(observed, list):
        raise ValueError(f"step {step.global_step} has no observed player HP")
    matches = [
        item for item in observed
        if isinstance(item, dict) and item.get("player_id") == player_id
    ]
    if len(matches) != 1 or (
        matches[0].get("current_hp"), matches[0].get("max_hp")
    ) != (current_hp, max_hp):
        raise ValueError(f"step {step.global_step} observation/run-context HP disagree")
    return player_id, current_hp, max_hp


def _optional_hp_pair(
    source: Mapping[str, Any], prefix: str, episode_id: str, *, text_values: bool = False
) -> tuple[int, int] | None:
    current_key = f"{prefix}_current_hp"
    maximum_key = f"{prefix}_max_hp"
    if current_key not in source and maximum_key not in source:
        return None
    current = source.get(current_key)
    maximum = source.get(maximum_key)
    if text_values:
        if isinstance(current, str) and re.fullmatch(r"[0-9]+", current):
            current = int(current)
        if isinstance(maximum, str) and re.fullmatch(r"[0-9]+", maximum):
            maximum = int(maximum)
    if (
        type(current) is not int
        or type(maximum) is not int
        or maximum <= 0
        or current < 0
        or current > maximum
    ):
        raise ValueError(f"episode {episode_id} has invalid {prefix} HP metadata")
    return current, maximum


def _validate_complete_run(audit: EpisodeAudit) -> None:
    """Require trustworthy terminal outcome and continuous no-SL decisions."""

    if not audit.value_target_valid or audit.reward_version != "whole-run-v2":
        raise ValueError(f"episode {audit.episode_id} lacks a complete no-SL whole-run-v2 return")
    if audit.finished is None or audit.finished.payload.get("outcome") not in ("win", "defeat"):
        raise ValueError(f"episode {audit.episode_id} has no supported terminal outcome")
    if audit.finished.payload.get("termination_reason") != "native_run_history":
        raise ValueError(f"episode {audit.episode_id} lacks a native run-history terminal result")
    if not audit.steps or audit.steps[0].global_step != 0:
        raise ValueError(f"episode {audit.episode_id} has no initial decision")
    metadata = audit.started.payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"episode {audit.episode_id} has malformed start metadata")
    observed_from_start = (metadata or {}).get("observed_from_run_start")
    if observed_from_start is False or observed_from_start == "False":
        raise ValueError(f"episode {audit.episode_id} began after the run start")
    if not (observed_from_start is True or observed_from_start == "True"):
        raise ValueError(f"episode {audit.episode_id} has invalid run-start evidence")
    if any(event.event_type in _CUT_EVENTS for event in audit.events):
        raise ValueError(f"episode {audit.episode_id} has a gap or save/load event")
    for expected_index, step in enumerate(audit.steps):
        if step.global_step != expected_index:
            raise ValueError(f"episode {audit.episode_id} has noncontiguous decisions")
        if step.information_regime != "no_sl":
            raise ValueError(f"episode {audit.episode_id} step {step.global_step} is not no-SL")
        if _semantic_reasons(step) or "unexplained_outside_potion_decrease" in step.bc_reasons:
            raise ValueError(f"episode {audit.episode_id} step {step.global_step} fails semantic audit")


def _validate_act_reward_source(audit: EpisodeAudit) -> None:
    """Require a continuous public timeline, while allowing segmented labels.

    Coverage gaps invalidate the affected action labels and cut transformer
    history in ``_episode_trajectories``. They do not invalidate rewards that
    can be independently reconstructed from generic state transitions and the
    native terminal result.
    """
    if audit.reward_version != "whole-run-v2":
        raise ValueError(f"episode {audit.episode_id} lacks whole-run-v2 state transitions")
    if audit.finished is None or audit.finished.payload.get("outcome") not in ("win", "defeat"):
        raise ValueError(f"episode {audit.episode_id} has no supported terminal outcome")
    if audit.finished.payload.get("termination_reason") != "native_run_history":
        raise ValueError(f"episode {audit.episode_id} lacks a native run-history terminal result")
    if not audit.steps or audit.steps[0].global_step != 0:
        raise ValueError(f"episode {audit.episode_id} has no initial decision")
    metadata = audit.started.payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError(f"episode {audit.episode_id} has malformed start metadata")
    observed = (metadata or {}).get("observed_from_run_start")
    if observed is not True and observed != "True":
        raise ValueError(f"episode {audit.episode_id} lacks native run-start evidence")
    if any(event.event_type == "save_load" for event in audit.events):
        raise ValueError(f"episode {audit.episode_id} contains a save/load timeline change")
    for expected, step in enumerate(audit.steps):
        if step.global_step != expected:
            raise ValueError(f"episode {audit.episode_id} has noncontiguous recorded decisions")
        if step.information_regime != "no_sl":
            raise ValueError(f"episode {audit.episode_id} step {step.global_step} is not no-SL")


def _episode_win_returns(audit: EpisodeAudit) -> tuple[dict[int, float], dict[str, Any]]:
    """Historical terminal-only scheme; raw HP rewards are not reused."""
    _validate_complete_run(audit)
    outcome = audit.finished.payload["outcome"]
    values = win_returns_to_go(outcome, len(audit.steps))
    return dict(enumerate(values)), {
        "outcome": outcome,
        "rtg_min": min(values),
        "rtg_max": max(values),
        "terminal_reward": values[0],
    }


def _episode_returns(audit: EpisodeAudit) -> tuple[dict[int, float], dict[str, Any]]:
    """Compute decision-time RTG from terminal HP and the visible current HP.

    A prior action's reward event can be written after the next decision even
    though its HP effect is already present in that decision's observation.
    Summing rewards by event sequence would count that known healing twice.
    The HP shaping term telescopes, so its exact remaining sum is the terminal
    capped HP score minus the capped HP visible at this decision.
    """

    unobserved_potion_steps = [
        step.global_step
        for step in audit.steps
        if "unexplained_outside_potion_decrease" in step.bc_reasons
    ]
    if unobserved_potion_steps:
        raise ValueError(
            f"episode {audit.episode_id} has "
            "unexplained_outside_potion_decrease at steps "
            f"{unobserved_potion_steps}"
        )
    if not audit.value_target_valid or audit.reward_version != "whole-run-v2":
        raise ValueError(
            f"episode {audit.episode_id} lacks a complete no-SL whole-run-v2 return"
        )
    if audit.finished is None or audit.finished.payload.get("outcome") not in ("win", "defeat"):
        raise ValueError(f"episode {audit.episode_id} has no supported terminal outcome")
    if not audit.steps or audit.steps[0].global_step != 0:
        raise ValueError(f"episode {audit.episode_id} has no initial decision")

    first_player_id, initial_hp, initial_max_hp = _decision_hp(audit.steps[0])
    metadata = audit.started.payload.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError(f"episode {audit.episode_id} has malformed start metadata")
    observed_from_start = metadata.get("observed_from_run_start")
    if observed_from_start is False or observed_from_start == "False":
        raise ValueError(f"episode {audit.episode_id} began after the run start")
    if not (
        observed_from_start is None
        or observed_from_start is True
        or observed_from_start == "True"
    ):
        raise ValueError(f"episode {audit.episode_id} has invalid run-start evidence")
    episode_start = _optional_hp_pair(
        metadata, "episode_start", audit.episode_id, text_values=True
    )
    run_start = _optional_hp_pair(
        metadata, "run_start", audit.episode_id, text_values=True
    )
    if (episode_start is None) != (run_start is None):
        raise ValueError(f"episode {audit.episode_id} has incomplete initial HP metadata")
    if run_start is not None and not (
        observed_from_start is True or observed_from_start == "True"
    ):
        raise ValueError(f"episode {audit.episode_id} has no proof of run-start HP")
    if episode_start is not None and episode_start != (initial_hp, initial_max_hp):
        raise ValueError(f"episode {audit.episode_id} initial decision/episode HP disagree")
    if run_start is not None:
        if run_start != (initial_hp, initial_max_hp):
            raise ValueError(f"episode {audit.episode_id} initial decision/run HP disagree")
        initial_max_hp = run_start[1]
    if initial_hp <= 0 or any(
        event.event_type in ("reward", "save_load")
        and event.event_sequence < audit.steps[0].decision.event_sequence
        for event in audit.events
    ):
        raise ValueError(f"episode {audit.episode_id} has no reliable initial HP")
    decision_hp: dict[int, int] = {}
    for step in audit.steps:
        if step.information_regime != "no_sl":
            raise ValueError(
                f"episode {audit.episode_id} step {step.global_step} is not no-SL"
            )
        if _semantic_reasons(step):
            raise ValueError(
                f"episode {audit.episode_id} step {step.global_step} fails semantic audit"
            )
        player_id, current_hp, _ = _decision_hp(step)
        if player_id != first_player_id:
            raise ValueError(f"episode {audit.episode_id} changes player identity")
        decision_hp[step.global_step] = current_hp

    final_hp = initial_hp
    reward_events = 0
    for event in audit.events:
        if event.event_type != "reward":
            continue
        components = event.payload.get("components")
        delta = components.get("hp_delta") if isinstance(components, dict) else None
        if type(delta) is not int:
            raise ValueError(f"episode {audit.episode_id} has an invalid HP delta")
        final_hp += delta
        reward_events += 1
        if final_hp < 0:
            raise ValueError(f"episode {audit.episode_id} reconstructs negative HP")
    if not reward_events:
        raise ValueError(f"episode {audit.episode_id} has no HP reward evidence")

    summary = audit.finished.payload.get("summary")
    if isinstance(summary, dict):
        terminal_status = summary.get("terminal_hp_status")
        has_terminal_fields = any(
            key in summary
            for key in ("terminal_current_hp", "terminal_max_hp", "terminal_hp_status")
        )
        if has_terminal_fields:
            if terminal_status == "available":
                terminal_hp = _optional_hp_pair(summary, "terminal", audit.episode_id)
                if terminal_hp is None or terminal_hp[0] != final_hp:
                    raise ValueError(
                        f"episode {audit.episode_id} reward/terminal HP disagree"
                    )
            elif terminal_status == "unavailable":
                terminal_current = summary.get("terminal_current_hp")
                terminal_maximum = summary.get("terminal_max_hp")
                if terminal_current is not None and (
                    type(terminal_current) is not int
                    or terminal_current < 0
                    or terminal_current != final_hp
                ):
                    raise ValueError(
                        f"episode {audit.episode_id} has inconsistent terminal HP status"
                    )
                if terminal_maximum is not None and (
                    type(terminal_maximum) is not int or terminal_maximum <= 0
                ):
                    raise ValueError(
                        f"episode {audit.episode_id} has inconsistent terminal HP status"
                    )
                if terminal_current is not None and terminal_maximum is not None:
                    raise ValueError(
                        f"episode {audit.episode_id} marks available terminal HP unavailable"
                    )
            else:
                raise ValueError(
                    f"episode {audit.episode_id} has invalid terminal HP status"
                )

    safe_hp = HP_SAFE_FRACTION * initial_max_hp
    def capped_hp(hp: int) -> float:
        return min(max(hp / safe_hp, 0.0), 1.0)

    terminal = 1.0 if audit.finished.payload["outcome"] == "win" else 0.0
    final_score = capped_hp(final_hp)
    returns = {
        step: terminal + HP_SHAPING_WEIGHT * (final_score - capped_hp(hp))
        for step, hp in decision_hp.items()
    }
    return returns, {
        "initial_max_hp": initial_max_hp,
        "initial_hp_source": (
            "run_start_metadata" if run_start else "inferred_first_decision"
        ),
        "final_hp": final_hp,
        "terminal_hp_cross_checked": (
            isinstance(summary, dict)
            and summary.get("terminal_hp_status") == "available"
        ),
        "outcome": audit.finished.payload["outcome"],
        "reward_events": reward_events,
        "rtg_min": min(returns.values()),
        "rtg_max": max(returns.values()),
    }


def _encode_step(
    step: StepAudit, encoder: RawFeatureEncoder, *, return_to_go: float = 0.0
) -> TrajectoryStep:
    assert step.submission is not None
    payload = step.decision.payload
    domain = step.domain
    observation = payload["observation"]
    legal_actions = payload["legal_actions"]
    context = payload.get("context")
    run_context = context.get("run_context") if isinstance(context, dict) else None
    selected_index = step.submission.payload["selected_action_index"]
    selected_action = step.submission.payload.get("selected_action")

    entities = encoder.encode_observation(domain, observation, run_context)
    actions = encoder.encode_actions(domain, observation, legal_actions)
    candidates = encoder.encode_set_candidates(domain, observation)
    selected_mask = None
    if selected_action is not None:
        if candidates is None:
            raise ValueError("selection template has no frozen candidate set")
        selected_mask = encoder.encode_selected_set(
            domain, observation, selected_action, candidates
        )
        executed_action = encoder.encode_executed_action(
            domain, observation, selected_action
        )
    else:
        executed_action = actions[selected_index].clone()

    return TrajectoryStep(
        entity_features=entities,
        legal_action_features=actions,
        selected_action_index=selected_index,
        return_to_go=return_to_go,
        timestep=step.global_step,
        domain=(
            DecisionDomain.COMBAT
            if domain == "combat"
            else DecisionDomain.OUTSIDE_COMBAT
        ),
        value_target=None,
        set_candidate_features=None if candidates is None else candidates.features,
        set_selected_mask=selected_mask,
        set_min_select=None if candidates is None else candidates.min_select,
        set_max_select=None if candidates is None else candidates.max_select,
        executed_action_features=executed_action,
    )


def _episode_trajectories(
    audit: EpisodeAudit,
    encoder: RawFeatureEncoder,
    max_window_steps: int,
    reward_scheme: str = BC_ONLY_SCHEME,
    allowed_policy_ids: Sequence[str] = (),
) -> tuple[list[Trajectory], dict[str, Any]]:
    if reward_scheme not in REWARD_SCHEMES:
        raise ValueError(f"unsupported reward scheme: {reward_scheme}")
    if reward_scheme == HP_SAFE_RTG_SCHEME:
        returns, return_report = _episode_returns(audit)
    elif reward_scheme == WIN_RTG_SCHEME:
        returns, return_report = _episode_win_returns(audit)
    elif reward_scheme == ACT_RTG_SCHEME:
        _validate_act_reward_source(audit)
        returns, return_report = act_episode_returns(audit)
    else:
        returns, return_report = {}, {}
    trajectories: list[Trajectory] = []
    segment: list[TrajectoryStep] = []
    exclusions: Counter[str] = Counter()
    cuts = sorted(
        event.event_sequence
        for event in audit.events
        if event.event_type in _CUT_EVENTS
    )
    cut_index = 0
    previous_step: StepAudit | None = None
    included = 0
    set_labels = 0
    included_sources: Counter[str] = Counter()
    teacher_information: Counter[str] = Counter()

    def flush() -> None:
        if segment:
            trajectories.append(Trajectory(tuple(segment)))
            segment.clear()

    for step in audit.steps:
        while cut_index < len(cuts) and cuts[cut_index] <= step.decision.event_sequence:
            cut_index += 1
        if previous_step is not None:
            cut_between = (
                cut_index > 0
                and previous_step.decision.event_sequence
                < cuts[cut_index - 1]
                < step.decision.event_sequence
            )
            if step.global_step != previous_step.global_step + 1 or cut_between:
                flush()

        semantic_reasons = _semantic_reasons(step)
        policy_reason = _policy_exclusion_reason(step, allowed_policy_ids)
        if not step.bc_eligible or policy_reason or semantic_reasons:
            flush()
            for reason in step.bc_reasons:
                exclusions[reason] += 1
            if step.bc_eligible and policy_reason:
                exclusions[policy_reason] += 1
            for reason in semantic_reasons:
                exclusions[reason] += 1
            previous_step = None
            continue

        try:
            encoded = _encode_step(
                step, encoder, return_to_go=returns.get(step.global_step, 0.0)
            )
            encoded.validate(encoder.spec.entity_feature_dim, encoder.spec.action_feature_dim)
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise ValueError(
                f"episode {audit.episode_id} step {step.global_step} cannot be tensorized: {exc}"
            ) from exc
        segment.append(encoded)
        included += 1
        policy = step.submission.payload["policy"]
        included_sources["human" if step.actor == "human" else policy["policy_id"]] += 1
        if step.actor == "policy":
            teacher_information[policy["teacher_information"]] += 1
        set_labels += encoded.set_selected_mask is not None
        if len(segment) >= max_window_steps:
            flush()
        previous_step = step
    flush()
    return trajectories, {
        "episode_id": audit.episode_id,
        "source_sha256": _file_sha256(audit.path),
        "raw_steps": len(audit.steps),
        "bc_steps": included,
        "excluded_steps": len(audit.steps) - included,
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "set_labels": set_labels,
        "trajectories": len(trajectories),
        "included_sources": dict(sorted(included_sources.items())),
        "teacher_information": dict(sorted(teacher_information.items())),
        "raw_value_target_valid": audit.value_target_valid,
        **return_report,
    }


def assemble_raw_dataset(
    inputs: Sequence[str | Path],
    output: str | Path,
    *,
    train_episodes: Sequence[str] = (),
    val_episodes: Sequence[str] = (),
    test_episodes: Sequence[str] = (),
    holdout_episodes: Sequence[str] = (),
    feature_spec_path: str | Path | None = None,
    max_window_steps: int = 64,
    trajectories_per_shard: int = 8,
    max_vocabulary_size: int = 512,
    reward_scheme: str = BC_ONLY_SCHEME,
    allowed_policy_ids: Sequence[str] = (),
) -> AssemblyResult:
    """Audit raw episodes, split by episode, and publish a reproducible cache.

    No split is published until every selected episode and encoded step is
    valid.  The feature vocabulary is fit only on included training decisions.
    """

    if not isinstance(max_window_steps, int) or isinstance(max_window_steps, bool) or max_window_steps < 1:
        raise ValueError("max_window_steps must be a positive integer")
    if reward_scheme not in REWARD_SCHEMES:
        raise ValueError(f"unsupported reward scheme: {reward_scheme}")
    if isinstance(allowed_policy_ids, str) or any(
        policy_id not in POLICY_TEACHER_INFORMATION for policy_id in allowed_policy_ids
    ):
        raise ValueError("allowed policies must be native-mcts or first-legal")
    allowed_policy_ids = tuple(sorted(set(allowed_policy_ids)))
    reward_version = (
        REWARD_VERSION if reward_scheme == BC_ONLY_SCHEME else reward_scheme
    )
    if not isinstance(trajectories_per_shard, int) or isinstance(trajectories_per_shard, bool) or trajectories_per_shard < 1:
        raise ValueError("trajectories_per_shard must be a positive integer")
    if bool(holdout_episodes) != (feature_spec_path is not None):
        raise ValueError("--holdout-episode and --feature-spec must be supplied together")
    source_paths = _source_paths(inputs)
    requested = tuple(
        prefix.replace("-", "").lower()
        for prefix in (*train_episodes, *val_episodes, *test_episodes, *holdout_episodes)
    )
    if requested:
        # A large raw directory can contain many historical 30+ MB runs.  A
        # header peek selects candidates; load_episode still verifies every
        # byte and every event of each selected journal before use.
        source_paths = tuple(
            path
            for path in source_paths
            if any(_peek_episode_id(path).startswith(prefix) for prefix in requested)
        )
    audits = tuple(load_episode(path) for path in source_paths)
    splits = _select_splits(
        audits, train_episodes, val_episodes, test_episodes, holdout_episodes
    )
    if feature_spec_path is None:
        specification = RawFeatureSpec.fit(
            _training_decisions(splits["train"], allowed_policy_ids),
            max_vocabulary_size=max_vocabulary_size,
        )
    else:
        raw_spec = json.loads(Path(feature_spec_path).read_text(encoding="utf-8"))
        if not isinstance(raw_spec, dict):
            raise ValueError("feature specification must be a JSON object")
        specification = RawFeatureSpec.from_dict(raw_spec)
    encoder = RawFeatureEncoder(specification)

    destination = Path(output)
    if destination.exists():
        raise FileExistsError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        spec_path = temporary / "feature-spec.json"
        spec_path.write_text(
            json.dumps(specification.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report: dict[str, Any] = {
            "schema_version": 1,
            "tensorizer_version": TENSORIZER_VERSION,
            "reward_version": reward_version,
            "reward_scheme": reward_scheme,
            "allowed_policy_ids": list(allowed_policy_ids),
            "policy_teacher_information": {
                policy_id: POLICY_TEACHER_INFORMATION[policy_id] for policy_id in allowed_policy_ids
            },
            "reward_parameters": (
                {
                    "terminal_win": 1.0,
                    "terminal_defeat": 0.0,
                    "safe_hp_fraction_of_initial_max": HP_SAFE_FRACTION,
                    "hp_shaping_weight": HP_SHAPING_WEIGHT,
                    "discount": 1.0,
                    "raw_reward_version": "whole-run-v2",
                }
                if reward_scheme == HP_SAFE_RTG_SCHEME
                else win_reward_parameters() if reward_scheme == WIN_RTG_SCHEME
                else act_reward_parameters() if reward_scheme == ACT_RTG_SCHEME else None
            ),
            "conditioning": (
                "realized_whole_run_return_to_go"
                if reward_scheme != BC_ONLY_SCHEME
                else "constant_zero_bc_only"
            ),
            "vocabulary_hash": specification.sha256(),
            "entity_feature_dim": specification.entity_feature_dim,
            "action_feature_dim": specification.action_feature_dim,
            "max_window_steps": max_window_steps,
            "trajectories_per_shard": trajectories_per_shard,
            "feature_spec_source": "external" if feature_spec_path is not None else "fit_train_only",
            "splits": {},
        }
        for split, split_audits in splits.items():
            episode_reports: list[dict[str, Any]] = []
            trajectory_count = 0
            with TensorShardWriter(
                temporary / split,
                entity_feature_dim=specification.entity_feature_dim,
                action_feature_dim=specification.action_feature_dim,
                tensorizer_version=TENSORIZER_VERSION,
                vocabulary_hash=specification.sha256(),
                reward_version=reward_version,
                trajectories_per_shard=trajectories_per_shard,
                dtype=torch.float32,
            ) as writer:
                for audit in split_audits:
                    part, episode_report = _episode_trajectories(
                        audit, encoder, max_window_steps, reward_scheme, allowed_policy_ids
                    )
                    for trajectory in part:
                        writer.add(trajectory)
                    trajectory_count += len(part)
                    episode_reports.append(episode_report)
                if not trajectory_count:
                    raise ValueError(
                        f"split {split} contains no eligible no-SL decisions from allowed sources"
                    )
            report["splits"][split] = {
                "episodes": episode_reports,
                "episode_count": len(episode_reports),
                "bc_steps": sum(item["bc_steps"] for item in episode_reports),
                "set_labels": sum(item["set_labels"] for item in episode_reports),
                "trajectories": trajectory_count,
            }
        (temporary / "assembly-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            raise FileExistsError(f"output appeared during assembly: {destination}")
        os.replace(temporary, destination)
        return AssemblyResult(destination, report)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = [
    "AssemblyResult", "BC_ONLY_SCHEME", "HP_SAFE_RTG_SCHEME", "WIN_RTG_SCHEME", "ACT_RTG_SCHEME",
    "HP_SAFE_RTG_REWARD_VERSION", "REWARD_SCHEMES", "REWARD_VERSION",
    "TENSORIZER_VERSION", "assemble_raw_dataset",
]
