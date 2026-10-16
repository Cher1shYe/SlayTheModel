"""Read and audit append-only collector JSONL before tensorization.

The episode journal is the source of truth.  In particular, a successful
``action_submitted`` is not a policy label until its matching native execution
result has succeeded; episode completeness is a separate value-target gate.

This reader intentionally does not infer observations or labels from adjacent
events.  It preserves every decision, including cancelled and unfinished ones,
so callers can report exclusions and split trajectories at real event sequence
boundaries.  Raw metadata (Steam identity, seed, timestamps) stays in the audit
events and must never be passed to the model as features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import UUID


_ZERO_HASH = "0" * 64
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_HASH_SUFFIX = re.compile(rb',"event_sha256":"([0-9a-f]{64})"}\Z')
_SUCCESS = frozenset({"applied", "observed_transition"})
_EXECUTION_STATUSES = _SUCCESS | frozenset(
    {"cancelled", "rejected", "failed", "timed_out", "stale"}
)
_EVENT_TYPES = frozenset(
    {
        "episode_started",
        "decision",
        "action_submitted",
        "execution_result",
        "reward",
        "save_load",
        "coverage_gap",
        "diagnostic",
        "manual_combat_input",
        "manual_combat_input_outcome",
        "episode_finished",
    }
)
_HEADER_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "event_id",
        "episode_id",
        "event_sequence",
        "global_step",
        "timeline_generation",
        "recorded_at_utc",
        "source",
        "previous_event_sha256",
        "payload",
        "event_sha256",
    }
)


class JournalValidationError(ValueError):
    """A JSONL episode cannot be trusted for training."""


def _fail(path: Path, line: int, message: str) -> JournalValidationError:
    return JournalValidationError(f"{path}:{line}: {message}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value}")


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return UUID(value).int != 0
    except (ValueError, AttributeError):
        return False


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _utc(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _object(value: Any, name: str, path: Path, line: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path, line, f"{name} must be an object")
    return value


def _event_ref(value: Any, name: str, path: Path, line: int) -> str:
    if not _uuid(value):
        raise _fail(path, line, f"{name} must be a nonempty UUID")
    return value


def _validate_selected_set(
    template: Mapping[str, Any],
    selected: Mapping[str, Any],
    observation: Mapping[str, Any],
    domain: str,
    path: Path,
    line: int,
) -> None:
    """Check concrete set labels without expanding candidate combinations."""

    if selected.get("is_selection_template"):
        raise _fail(path, line, "concrete selected_action is still a template")
    if domain == "combat":
        if template.get("kind") != "resolve_choice" or selected.get("selected_model_ids") is not None:
            raise _fail(path, line, "invalid concrete combat selection kind/fields")
        for key in (
            "kind",
            "actor_player_id",
            "choice_id",
            "combat_card_index",
            "potion_index",
            "target_creature_id",
            "option_index",
        ):
            if selected.get(key) != template.get(key):
                raise _fail(path, line, f"selected combat set differs in {key}")
        choice = observation.get("active_choice")
        ids = selected.get("selected_combat_card_ids")
        if not isinstance(choice, dict) or not isinstance(ids, list):
            raise _fail(path, line, "combat set lacks active choice or selected card IDs")
        if choice.get("choice_id") != template.get("choice_id") or choice.get("max_selections", 0) <= 1:
            raise _fail(path, line, "combat set does not match the active choice")
        cards = choice.get("cards")
        if not isinstance(cards, list):
            raise _fail(path, line, "combat choice cards must be an array")
        offered = {
            card.get("combat_card_index")
            for card in cards
            if isinstance(card, dict) and card.get("combat_card_index") is not None
        }
        if (
            not all(_integer(card_id) and card_id >= 0 for card_id in ids)
            or ids != sorted(set(ids))
            or any(card_id not in offered for card_id in ids)
            or not _integer(choice.get("min_selections"))
            or not _integer(choice.get("max_selections"))
            or not choice["min_selections"] <= len(ids) <= choice["max_selections"]
        ):
            raise _fail(path, line, "selected combat cards violate frozen candidates/bounds")
    else:
        if template.get("kind") not in ("choose_card_set", "remove_card_set") or selected.get("bundle_cards") is not None:
            raise _fail(path, line, "invalid concrete outside selection kind/fields")
        for key in (
            "action_id",
            "kind",
            "ordinal",
            "target_id",
            "map_coordinate",
            "cost",
            "target_deck_index",
        ):
            if selected.get(key) != template.get(key):
                raise _fail(path, line, f"selected outside set differs in {key}")
        candidates = observation.get("card_selection_options")
        choice = observation.get("choice_context")
        chosen = selected.get("selected_cards")
        if (
            not isinstance(candidates, list)
            or not isinstance(choice, dict)
            or not isinstance(chosen, list)
            or not _integer(choice.get("min_selections"))
            or not _integer(choice.get("max_selections"))
            or not choice["min_selections"] <= len(chosen) <= choice["max_selections"]
        ):
            raise _fail(path, line, "outside set lacks candidates or valid selection bounds")
        indexes: list[int] = []
        for card in chosen:
            if not isinstance(card, dict):
                raise _fail(path, line, "selected outside card is not an object")
            index = card.get("option_index")
            if not _integer(index) or index < 0 or index >= len(candidates):
                raise _fail(path, line, "outside card option_index is not offered")
            if card != candidates[index]:
                raise _fail(path, line, "outside card differs from frozen candidate")
            indexes.append(index)
        if indexes != sorted(set(indexes)):
            raise _fail(path, line, "outside selected option indexes must be unique/sorted")


@dataclass(frozen=True)
class JournalEvent:
    """A verified event, including its original structured audit payload."""

    event_type: str
    event_id: str
    episode_id: str
    event_sequence: int
    global_step: int | None
    timeline_generation: int
    payload: Mapping[str, Any]
    event_sha256: str
    record: Mapping[str, Any]


@dataclass(frozen=True)
class StepAudit:
    """One original decision and the exact evidence for its training masks."""

    decision: JournalEvent
    submission: JournalEvent | None
    result: JournalEvent | None
    reward: JournalEvent | None
    submissions: tuple[JournalEvent, ...]
    results: tuple[JournalEvent, ...]
    bc_eligible: bool
    value_eligible: bool
    transition_eligible: bool
    bc_reasons: tuple[str, ...]
    value_reasons: tuple[str, ...]
    transition_reasons: tuple[str, ...]

    @property
    def decision_id(self) -> str:
        return self.decision.event_id

    @property
    def global_step(self) -> int:
        assert self.decision.global_step is not None
        return self.decision.global_step

    @property
    def domain(self) -> str:
        return str(self.decision.payload["domain"])

    @property
    def information_regime(self) -> str:
        return str(self.decision.payload["information_regime"])

    @property
    def actor(self) -> str | None:
        if self.submission is None:
            return None
        return str(self.submission.payload["policy"]["actor"])

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.bc_reasons, *self.value_reasons)))


@dataclass(frozen=True)
class EpisodeAudit:
    """Verified journal and all of its decisions, including masked decisions."""

    path: Path
    episode_id: str
    events: tuple[JournalEvent, ...]
    steps: tuple[StepAudit, ...]
    started: JournalEvent
    finished: JournalEvent | None
    value_target_valid: bool

    @property
    def reward_version(self) -> str:
        return str(self.started.payload["reward_version"])


@dataclass
class _StepBuilder:
    decision: JournalEvent
    submissions: list[JournalEvent] = field(default_factory=list)
    results: list[JournalEvent] = field(default_factory=list)
    reward: JournalEvent | None = None
    blocked_reasons: list[str] = field(default_factory=list)

    def block(self, reason: str) -> None:
        if reason not in self.blocked_reasons:
            self.blocked_reasons.append(reason)


def _unexplained_outside_potion_decrease(builder: _StepBuilder) -> bool:
    """Find potion loss with no explicit outside action that accounts for it.

    WholeRunV2 measures the inventory change at the next stable boundary. An
    unrecorded use or discard between two outside decisions can therefore be
    charged to an unrelated selected action. The journal remains structurally
    valid, but neither that BC label nor the complete-run return is reliable.
    """

    if builder.decision.payload["domain"] != "outside_combat" or builder.reward is None:
        return False
    delta = builder.reward.payload["components"].get("potion_count_delta", 0)
    if delta >= 0:
        return False
    successful_attempts = {
        result.payload["attempt_id"]
        for result in builder.results
        if result.payload["status"] in _SUCCESS
    }
    for submission in builder.submissions:
        if submission.payload["attempt_id"] not in successful_attempts:
            continue
        index = submission.payload["selected_action_index"]
        action = builder.decision.payload["legal_actions"][index]
        # These kinds are reserved for a future explicit outside potion input.
        # No currently emitted outside action has either kind.
        return action.get("kind") not in ("use_potion", "discard_potion")
    return False


def _load_events(path: Path) -> tuple[JournalEvent, ...]:
    events: list[JournalEvent] = []
    prior_hash = _ZERO_HASH
    episode_id: str | None = None
    source: str | None = None
    generation = 0
    event_ids: set[str] = set()
    finished = False

    with path.open("rb") as stream:
        for line_number, line_bytes in enumerate(stream, 1):
            if not line_bytes.endswith(b"\n"):
                raise _fail(path, line_number, "event line is not newline terminated")
            raw = line_bytes[:-1]
            if raw.endswith(b"\r"):
                raise _fail(path, line_number, "CRLF is not the collector journal format")
            suffix = _HASH_SUFFIX.search(raw)
            if suffix is None:
                raise _fail(path, line_number, "event hash must be the final JSON field")
            expected_hash = hashlib.sha256(raw[: suffix.start()] + b"}").hexdigest()
            if suffix.group(1).decode("ascii") != expected_hash:
                raise _fail(path, line_number, "event SHA-256 does not match content")
            try:
                record = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_no_duplicate_keys,
                    parse_constant=_reject_constant,
                )
            except (UnicodeError, ValueError) as exc:
                raise _fail(path, line_number, f"invalid JSON: {exc}") from exc
            if not isinstance(record, dict) or set(record) != _HEADER_FIELDS:
                raise _fail(path, line_number, "event envelope fields do not match schema v1")
            if record["schema_version"] != 1 or not _integer(record["schema_version"]):
                raise _fail(path, line_number, "unsupported event schema_version")
            event_type = record["event_type"]
            if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
                raise _fail(path, line_number, f"unsupported event_type {event_type!r}")
            if finished:
                raise _fail(path, line_number, "event follows episode_finished")
            if not _integer(record["event_sequence"]) or record["event_sequence"] != len(events):
                raise _fail(path, line_number, "event_sequence is not contiguous from zero")
            if not _uuid(record["event_id"]) or record["event_id"] in event_ids:
                raise _fail(path, line_number, "invalid or duplicate event_id")
            event_ids.add(record["event_id"])
            if not _uuid(record["episode_id"]):
                raise _fail(path, line_number, "invalid episode_id")
            if episode_id is None:
                episode_id = record["episode_id"]
            elif record["episode_id"] != episode_id:
                raise _fail(path, line_number, "episode_id changed within file")
            if not isinstance(record["source"], str) or record["source"] not in ("live", "headless"):
                raise _fail(path, line_number, "invalid source")
            if source is None:
                source = record["source"]
            elif record["source"] != source:
                raise _fail(path, line_number, "source changed within file")
            if not _utc(record["recorded_at_utc"]):
                raise _fail(path, line_number, "recorded_at_utc must be UTC")
            if not _sha(record["previous_event_sha256"]) or record["previous_event_sha256"] != prior_hash:
                raise _fail(path, line_number, "previous_event_sha256 chain is broken")
            if record["event_sha256"] != expected_hash:
                raise _fail(path, line_number, "event_sha256 field is inconsistent")
            if not _integer(record["timeline_generation"]) or record["timeline_generation"] < 0:
                raise _fail(path, line_number, "invalid timeline_generation")
            expected_generation = generation + (event_type == "save_load")
            if record["timeline_generation"] != expected_generation:
                raise _fail(path, line_number, "timeline_generation changed without save_load")
            generation = expected_generation
            step = record["global_step"]
            if step is not None and (not _integer(step) or step < 0):
                raise _fail(path, line_number, "invalid global_step")
            if event_type == "episode_started":
                if events or step is not None or generation != 0:
                    raise _fail(path, line_number, "episode_started must be first")
            elif not events:
                raise _fail(path, line_number, "first event must be episode_started")
            if event_type in (
                "episode_finished",
                "diagnostic",
                "manual_combat_input",
                "manual_combat_input_outcome",
            ) and step is not None:
                raise _fail(path, line_number, f"{event_type} must not carry global_step")
            payload = _object(record["payload"], "payload", path, line_number)
            if event_type == "save_load":
                if payload.get("from_timeline_generation") != generation - 1 or payload.get(
                    "to_timeline_generation"
                ) != generation:
                    raise _fail(path, line_number, "save_load generation payload mismatch")
                if payload.get("kind") not in ("resume", "rewind", "unknown"):
                    raise _fail(path, line_number, "invalid save_load kind")
            event = JournalEvent(
                event_type=event_type,
                event_id=record["event_id"],
                episode_id=record["episode_id"],
                event_sequence=record["event_sequence"],
                global_step=step,
                timeline_generation=generation,
                payload=payload,
                event_sha256=expected_hash,
                record=record,
            )
            events.append(event)
            prior_hash = expected_hash
            finished = event_type == "episode_finished"
    if not events:
        raise JournalValidationError(f"{path}: empty journal")
    return tuple(events)


def _block_referenced_steps(
    builders: Mapping[str, _StepBuilder],
    pending: set[str],
    event: JournalEvent,
    reason: str,
    path: Path,
) -> None:
    payload = event.payload
    refs: set[str] = set()
    for field_name in (
        "related_decision_id",
        "invalidated_decision_id",
        "target_decision_id",
    ):
        value = payload.get(field_name)
        if value is not None:
            refs.add(_event_ref(value, field_name, path, event.event_sequence + 1))
    invalidated = payload.get("invalidated_decisions")
    if invalidated is not None:
        if not isinstance(invalidated, list):
            raise _fail(path, event.event_sequence + 1, "invalidated_decisions must be an array")
        for item in invalidated:
            if not isinstance(item, dict) or not _uuid(item.get("decision_id")):
                raise _fail(path, event.event_sequence + 1, "invalid invalidated_decisions entry")
            refs.add(item["decision_id"])
    if payload.get("invalidates_pending_decision") or payload.get("creates_data_gap"):
        if payload.get("target_decision_id") is None:
            refs.update(pending)
    for decision_id in refs:
        if decision_id not in builders:
            raise _fail(path, event.event_sequence + 1, f"{reason} references an unknown decision")
        builders[decision_id].block(reason)
    related_attempt = payload.get("related_attempt_id")
    related_decision = payload.get("related_decision_id")
    if related_attempt is not None:
        if related_decision is None or not any(
            submission.payload.get("attempt_id") == related_attempt
            for submission in builders[related_decision].submissions
        ):
            raise _fail(path, event.event_sequence + 1, f"{reason} refers to an unknown attempt")


def _finish_step(
    builder: _StepBuilder,
    *,
    episode_value_ok: bool,
    reward_version: str,
) -> StepAudit:
    successful: list[tuple[JournalEvent, JournalEvent]] = []
    results_by_attempt = {result.payload["attempt_id"]: result for result in builder.results}
    for submission in builder.submissions:
        result = results_by_attempt.get(submission.payload["attempt_id"])
        if result is not None and result.payload["status"] in _SUCCESS:
            successful.append((submission, result))
    if len(successful) > 1:
        raise JournalValidationError(
            f"decision {builder.decision.event_id} has multiple successful attempts"
        )
    submission, result = successful[0] if successful else (None, None)
    bc_reasons = list(builder.blocked_reasons)
    if builder.decision.payload["information_regime"] != "no_sl":
        bc_reasons.append("information_regime_not_no_sl")
    if submission is None or result is None:
        bc_reasons.append("no_successful_execution")
        if not builder.submissions:
            bc_reasons.append("action_not_submitted")
        elif not builder.results:
            bc_reasons.append("execution_result_missing")
        else:
            bc_reasons.append(
                "execution_status_" + str(builder.results[-1].payload["status"])
            )
    transition_reasons = list(bc_reasons)
    if result is not None:
        detail = result.payload.get("detail")
        if isinstance(detail, str) and "transition_contaminated_by_queued_manual_input" in detail:
            transition_reasons.append("queued_manual_input_contaminated_transition")
        if result.payload.get("next_state_fingerprint") is None:
            transition_reasons.append("next_state_fingerprint_missing")
    value_reasons = list(bc_reasons)
    if not episode_value_ok:
        value_reasons.append("episode_value_target_invalid")
    if reward_version != "whole-run-v2":
        value_reasons.append("reward_version_not_whole_run_v2")
    if builder.reward is None:
        value_reasons.append("reward_missing")
    if result is not None and isinstance(result.payload.get("detail"), str) and (
        "transition_contaminated_by_queued_manual_input" in result.payload["detail"]
    ):
        value_reasons.append("queued_manual_input_contaminated_transition")
    return StepAudit(
        decision=builder.decision,
        submission=submission,
        result=result,
        reward=builder.reward,
        submissions=tuple(builder.submissions),
        results=tuple(builder.results),
        bc_eligible=not bc_reasons,
        value_eligible=not value_reasons,
        transition_eligible=not transition_reasons,
        bc_reasons=tuple(dict.fromkeys(bc_reasons)),
        value_reasons=tuple(dict.fromkeys(value_reasons)),
        transition_reasons=tuple(dict.fromkeys(transition_reasons)),
    )


def load_episode(path: str | Path) -> EpisodeAudit:
    """Verify one published or legacy-named JSONL and audit every decision.

    Raises :class:`JournalValidationError` for torn lines, corrupt hashes,
    inconsistent identities or ambiguous action/result/reward links.  The file
    name is never used as a source of episode identity or metadata.
    """

    path = Path(path)
    events = _load_events(path)
    started = events[0]
    start_payload = started.payload
    reward_version = start_payload.get("reward_version")
    if not isinstance(reward_version, str) or not reward_version:
        raise JournalValidationError(f"{path}: episode_started has no reward_version")
    builders: dict[str, _StepBuilder] = {}
    decision_order: list[str] = []
    attempts: dict[str, tuple[str, JournalEvent]] = {}
    pending: set[str] = set()
    manual_inputs: dict[str, JournalEvent] = {}
    manual_outcomes: dict[str, JournalEvent] = {}
    finished: JournalEvent | None = None
    gap_count = 0
    rewind_count = 0
    unknown_load_count = 0

    for event in events[1:]:
        kind = event.event_type
        payload = event.payload
        line = event.event_sequence + 1
        if kind == "decision":
            decision_id = _event_ref(payload.get("decision_id"), "decision_id", path, line)
            if decision_id != event.event_id or event.global_step != len(decision_order):
                raise _fail(path, line, "decision ID or global_step is not contiguous")
            if payload.get("domain") not in ("combat", "outside_combat"):
                raise _fail(path, line, "invalid decision domain")
            if payload.get("information_regime") not in ("no_sl", "sl", "unknown"):
                raise _fail(path, line, "invalid information_regime")
            if not _sha(payload.get("state_fingerprint")):
                raise _fail(path, line, "invalid decision state_fingerprint")
            if not isinstance(payload.get("observation"), dict):
                raise _fail(path, line, "decision observation must be an object")
            actions = payload.get("legal_actions")
            keys = payload.get("action_keys")
            if (
                not isinstance(actions, list)
                or not actions
                or not all(isinstance(action, dict) for action in actions)
                or not isinstance(keys, list)
                or len(actions) != len(keys)
                or not all(isinstance(key, str) and key for key in keys)
                or len(set(keys)) != len(keys)
            ):
                raise _fail(path, line, "invalid decision legal_actions/action_keys")
            if payload["domain"] == "outside_combat" and any(
                action.get("action_id") != key
                for action, key in zip(actions, keys, strict=True)
            ):
                raise _fail(path, line, "outside action_id does not match action key")
            if payload["domain"] == "combat":
                for action, key in zip(actions, keys, strict=True):
                    # CombatActionDescriptor keys are SHA-256 of its compact
                    # snake-case JSON. All official descriptor fields are
                    # ASCII; Unicode identifiers use escaped JSON codepoints.
                    encoded = json.dumps(
                        action, separators=(",", ":"), ensure_ascii=True
                    ).encode("utf-8")
                    if key != "combat:" + hashlib.sha256(encoded).hexdigest():
                        raise _fail(path, line, "combat action digest does not match legal action")
            builders[decision_id] = _StepBuilder(event)
            decision_order.append(decision_id)
            pending.add(decision_id)
        elif kind == "action_submitted":
            decision_id = _event_ref(payload.get("decision_id"), "decision_id", path, line)
            attempt_id = _event_ref(payload.get("attempt_id"), "attempt_id", path, line)
            builder = builders.get(decision_id)
            if builder is None or decision_id not in pending or attempt_id in attempts:
                raise _fail(path, line, "action references missing/closed decision or duplicate attempt")
            if event.global_step != builder.decision.global_step or event.timeline_generation != builder.decision.timeline_generation:
                raise _fail(path, line, "action step/generation does not match decision")
            if builder.submissions and builder.submissions[-1].payload["attempt_id"] not in {
                result.payload["attempt_id"]
                for result in builder.results
                if result.payload["status"] == "rejected"
            }:
                raise _fail(path, line, "multiple attempts require a prior rejected result")
            index = payload.get("selected_action_index")
            keys = builder.decision.payload["action_keys"]
            if not _integer(index) or index < 0 or index >= len(keys):
                raise _fail(path, line, "selected_action_index is outside legal actions")
            if payload.get("selected_action_key") != keys[index]:
                raise _fail(path, line, "selected_action_key does not match legal action")
            template = builder.decision.payload["legal_actions"][index]
            selection = payload.get("selected_action")
            if bool(template.get("is_selection_template")) != (selection is not None):
                raise _fail(path, line, "concrete selected_action/template mismatch")
            if selection is not None and not isinstance(selection, dict):
                raise _fail(path, line, "selected_action must be an object")
            if selection is not None:
                _validate_selected_set(
                    template,
                    selection,
                    builder.decision.payload["observation"],
                    builder.decision.payload["domain"],
                    path,
                    line,
                )
            policy = _object(payload.get("policy"), "policy", path, line)
            if policy.get("actor") not in ("human", "policy", "script"):
                raise _fail(path, line, "invalid policy actor")
            logits = policy.get("logits")
            if logits is not None and (
                not isinstance(logits, list)
                or len(logits) != len(keys)
                or any(
                    not _finite_number(value)
                    for value in logits
                )
            ):
                raise _fail(path, line, "invalid policy logits")
            visits = policy.get("mcts_visit_counts")
            if visits is not None and (
                not isinstance(visits, list)
                or len(visits) != len(keys)
                or any(not _integer(value) or value < 0 for value in visits)
            ):
                raise _fail(path, line, "invalid MCTS visit counts")
            builder.submissions.append(event)
            attempts[attempt_id] = (decision_id, event)
        elif kind == "execution_result":
            decision_id = _event_ref(payload.get("decision_id"), "decision_id", path, line)
            attempt_id = _event_ref(payload.get("attempt_id"), "attempt_id", path, line)
            builder = builders.get(decision_id)
            attempt = attempts.get(attempt_id)
            if builder is None or attempt is None or attempt[0] != decision_id:
                raise _fail(path, line, "execution_result has no matching action_submitted")
            if attempt_id in {prior.payload["attempt_id"] for prior in builder.results}:
                raise _fail(path, line, "duplicate execution_result for attempt")
            submission = attempt[1]
            if event.global_step != builder.decision.global_step or event.timeline_generation != submission.timeline_generation:
                raise _fail(path, line, "execution_result step/generation mismatch")
            if (
                payload.get("selected_action_index") != submission.payload["selected_action_index"]
                or payload.get("selected_action_key") != submission.payload["selected_action_key"]
                or not isinstance(payload.get("expected_state_fingerprint"), str)
                or payload["expected_state_fingerprint"].lower()
                != builder.decision.payload["state_fingerprint"].lower()
            ):
                raise _fail(path, line, "execution_result selection/fingerprint mismatch")
            if payload.get("status") not in _EXECUTION_STATUSES:
                raise _fail(path, line, "invalid execution_result status")
            next_fingerprint = payload.get("next_state_fingerprint")
            if next_fingerprint is not None and not _sha(next_fingerprint):
                raise _fail(path, line, "invalid next_state_fingerprint")
            builder.results.append(event)
            if payload["status"] != "rejected":
                if payload["status"] not in _SUCCESS:
                    pending.discard(decision_id)
        elif kind == "reward":
            decision_id = _event_ref(payload.get("decision_id"), "decision_id", path, line)
            builder = builders.get(decision_id)
            if builder is None or decision_id not in pending or builder.reward is not None:
                raise _fail(path, line, "reward has no open decision or is duplicated")
            if event.global_step != builder.decision.global_step or event.timeline_generation != builder.decision.timeline_generation:
                raise _fail(path, line, "reward step/generation mismatch")
            if payload.get("reward_version") != reward_version:
                raise _fail(path, line, "reward_version differs from episode")
            components = payload.get("components")
            if not isinstance(components, dict) or not components or any(
                not isinstance(key, str)
                or not key
                or not _finite_number(value)
                for key, value in components.items()
            ):
                raise _fail(path, line, "reward components must be finite numeric values")
            if not any(result.payload["status"] in _SUCCESS for result in builder.results):
                raise _fail(path, line, "reward has no successful execution_result")
            builder.reward = event
            pending.discard(decision_id)
        elif kind == "coverage_gap":
            gap_count += 1
            _block_referenced_steps(builders, pending, event, "coverage_gap", path)
            if payload.get("invalidates_pending_decision"):
                if payload.get("target_decision_id") is None:
                    pending.clear()
                else:
                    pending.discard(payload["target_decision_id"])
        elif kind == "save_load":
            if payload.get("kind") == "rewind":
                rewind_count += 1
            elif payload.get("kind") == "unknown":
                unknown_load_count += 1
            _block_referenced_steps(
                builders, pending, event, "save_load_interrupted_decision", path
            )
            pending.clear()
        elif kind == "manual_combat_input":
            intent_id = _event_ref(payload.get("intent_id"), "intent_id", path, line)
            native_action_id = payload.get("native_action_id")
            if not _integer(native_action_id) or native_action_id < 0 or intent_id in manual_inputs:
                raise _fail(path, line, "invalid/duplicate manual combat input")
            manual_inputs[intent_id] = event
            related = payload.get("related_decision_id")
            if related is not None and related not in builders:
                raise _fail(path, line, "manual input references unknown decision")
        elif kind == "manual_combat_input_outcome":
            intent_id = _event_ref(payload.get("intent_id"), "intent_id", path, line)
            original = manual_inputs.get(intent_id)
            if original is None or intent_id in manual_outcomes:
                raise _fail(path, line, "manual outcome lacks matching input")
            if payload.get("native_action_id") != original.payload["native_action_id"]:
                raise _fail(path, line, "manual outcome native_action_id mismatch")
            if payload.get("status") not in _EXECUTION_STATUSES:
                raise _fail(path, line, "invalid manual outcome status")
            manual_outcomes[intent_id] = event
        elif kind == "episode_finished":
            finished = event
            if event.global_step is not None:
                raise _fail(path, line, "episode_finished must not carry global_step")
            if payload.get("completeness") not in ("complete", "incomplete") or not isinstance(
                payload.get("value_target_valid"), bool
            ):
                raise _fail(path, line, "invalid episode_finished completeness/value flag")
            if payload.get("coverage_gap_count") != gap_count or payload.get("rewind_count") != rewind_count or payload.get("unknown_save_load_count") != unknown_load_count:
                raise _fail(path, line, "episode_finished audit counts disagree with journal")
            if payload.get("manual_combat_input_count") != len(manual_inputs) or payload.get("unresolved_manual_combat_input_count") != len(manual_inputs) - len(manual_outcomes):
                raise _fail(path, line, "episode_finished manual input counts disagree")
            if payload["value_target_valid"] and (
                payload["completeness"] != "complete"
                or pending
                or gap_count
                or rewind_count
                or unknown_load_count
            ):
                raise _fail(path, line, "episode falsely claims a valid value target")

    # A manual side event alone is never a BC label.  If it names a structured
    # step but its native outcome is missing or unsuccessful, mask that step.
    for intent_id, manual in manual_inputs.items():
        related = manual.payload.get("related_decision_id")
        if related is None:
            continue
        builder = builders[related]
        linked_attempt = manual.payload.get("related_attempt_id")
        if linked_attempt is not None and linked_attempt not in {
            item.payload["attempt_id"] for item in builder.submissions
        }:
            raise JournalValidationError(
                f"manual input {intent_id} references a missing structured attempt"
            )
        outcome = manual_outcomes.get(intent_id)
        if outcome is None:
            builder.block("manual_input_outcome_missing")
        elif outcome.payload["status"] not in _SUCCESS:
            builder.block("manual_input_not_applied")

    unexplained_outside_potion_decreases = 0
    for builder in builders.values():
        if _unexplained_outside_potion_decrease(builder):
            builder.block("unexplained_outside_potion_decrease")
            unexplained_outside_potion_decreases += 1

    # The collector's value flag is necessary but not sufficient for no-SL
    # training: each decision must itself be no_sl and reward v2 must be used.
    episode_value_ok = bool(
        finished is not None
        and finished.payload["value_target_valid"]
        and finished.payload["completeness"] == "complete"
        and reward_version == "whole-run-v2"
        and not gap_count
        and not rewind_count
        and not unknown_load_count
        and not unexplained_outside_potion_decreases
        and finished.payload.get("unresolved_manual_combat_input_count", 0) == 0
        and finished.payload.get("unstructured_unsafe_manual_combat_input_count", 0) == 0
        and not any(
            isinstance(result.payload.get("detail"), str)
            and "transition_contaminated_by_queued_manual_input" in result.payload["detail"]
            for builder in builders.values()
            for result in builder.results
        )
        and all(
            builder.decision.payload["information_regime"] == "no_sl"
            for builder in builders.values()
        )
    )
    steps = tuple(
        _finish_step(
            builders[decision_id],
            episode_value_ok=episode_value_ok,
            reward_version=reward_version,
        )
        for decision_id in decision_order
    )
    return EpisodeAudit(
        path=path,
        episode_id=started.episode_id,
        events=events,
        steps=steps,
        started=started,
        finished=finished,
        value_target_valid=episode_value_ok,
    )
