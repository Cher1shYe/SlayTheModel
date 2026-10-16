"""Validate native Spire Codex combat replay reports for tensor assembly."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


REPORT_VERSION = "stm-spire-codex-native-combat-replay-report-v1"
SEQUENTIAL_REPORT_VERSION = "stm-spire-codex-native-sequential-replay-report-v1"
PLAN_VERSION = "stm-spire-codex-native-combat-plan-v1"
FORBIDDEN_POLICY_KEYS = frozenset(
    {
        "seed",
        "rng_state",
        "rng_counters",
        "draw_order",
        "opening_draw_order",
        "order_c",
        "order_deck_c",
        "start_time",
        "wall_clock",
        "ms",
        "label",
        "desc",
        "instance_id",
        "native_id",
        "replay_only_hidden_state",
    }
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_hidden_policy_fields(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_POLICY_KEYS:
                raise ValueError(f"native policy decision contains hidden field {path}.{key}")
            _reject_hidden_policy_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_hidden_policy_fields(child, f"{path}[{index}]")


def _selected_action(
    legal: list[dict[str, Any]], selected: dict[str, Any]
) -> tuple[int, dict[str, Any] | None]:
    exact = [index for index, action in enumerate(legal) if action == selected]
    if len(exact) == 1:
        return exact[0], None
    if selected.get("kind") == "resolve_choice":
        templates = [
            index
            for index, action in enumerate(legal)
            if action.get("kind") == "resolve_choice"
            and action.get("is_selection_template") is True
        ]
        if len(templates) == 1:
            concrete = dict(selected)
            concrete["is_selection_template"] = False
            return templates[0], concrete
    raise ValueError("native selected action does not match one legal action or set template")


def _load_plan(
    directory: Path,
    source: Mapping[str, Any],
    expected_sha256: Any,
    report_name: str,
) -> tuple[Path, dict[str, Any]]:
    run_hash = source.get("run_hash")
    combat_index = source.get("combat_index")
    if not isinstance(run_hash, str) or type(combat_index) is not int:
        raise ValueError(f"native replay report source is invalid: {report_name}")
    plan_path = directory / f"{run_hash}-combat-{combat_index}.json"
    if not plan_path.is_file() or expected_sha256 != _sha256(plan_path):
        raise ValueError(f"native replay plan hash mismatch: {report_name}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (
        plan.get("format_version") != PLAN_VERSION
        or plan.get("replay_only_hidden_state") is not True
        or plan.get("source") != dict(source)
    ):
        raise ValueError(f"native replay plan is incomplete: {report_name}")
    return plan_path, plan


def _steps_from_proof(
    plan: Mapping[str, Any],
    source: Mapping[str, Any],
    decisions: Any,
    report_name: str,
) -> list[dict[str, Any]]:
    plan_actions = plan["combat"]["actions"]
    if not isinstance(decisions, list) or len(decisions) != len(plan_actions):
        raise ValueError(f"native replay decision count mismatch: {report_name}")
    run = plan["combat"]["run_snapshot"]
    room = run.get("room") if isinstance(run.get("room"), Mapping) else {}
    combat_index = source["combat_index"]
    steps: list[dict[str, Any]] = []
    for ordinal, (proof, planned) in enumerate(zip(decisions, plan_actions, strict=True)):
        if proof.get("sourceSequence") != planned.get("source_sequence"):
            raise ValueError(f"native replay source sequence mismatch: {report_name}")
        observation = proof.get("nativeObservation")
        legal = proof.get("nativeLegalActions")
        selected = proof.get("nativeSelectedAction")
        if (
            not isinstance(observation, Mapping)
            or not isinstance(legal, list)
            or not legal
            or not all(isinstance(action, dict) for action in legal)
            or not isinstance(selected, dict)
        ):
            raise ValueError(f"native policy decision is incomplete: {report_name}")
        _reject_hidden_policy_fields(observation, "observation")
        _reject_hidden_policy_fields(legal, "legal_actions")
        _reject_hidden_policy_fields(selected, "selected_action")
        selected_index, selected_action = _selected_action(legal, selected)
        steps.append(
            {
                "episode_id": source.get("episode_id"),
                "character": plan["run"]["character"],
                "segment_index": combat_index,
                "step_index": ordinal,
                "source_sequence": planned["source_sequence"],
                "trajectory_group": f"native-combat:{combat_index}",
                "trajectory_index": ordinal,
                "domain": "combat",
                "observation": dict(observation),
                "context": {
                    "run_context": {
                        "act_index": max(int(run.get("act", 1)) - 1, 0),
                        "act_floor": None,
                        "total_floor": run.get("floor"),
                        "ascension_level": run.get("ascension"),
                        "room_type": room.get("room_type") or room.get("kind") or "Monster",
                        "room_model_id": plan["combat"]["encounter"],
                    }
                },
                "legal_actions": legal,
                "selected_action_index": selected_index,
                "selected_action": selected_action,
            }
        )
    return steps


def load_validated_native_replays(root: str | Path) -> tuple[dict[str, Any], ...]:
    """Load reports whose plan hashes and native policy payloads are complete."""

    directory = Path(root).resolve()
    results: list[dict[str, Any]] = []
    for report_path in sorted(directory.glob("*-report.json")):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        version = report.get("formatVersion")
        if (
            report.get("error") is not None
            or report.get("nativeVictory") is not True
            or report.get("replayOnlyStateExcludedFromDecisions") is not True
        ):
            raise ValueError(f"native replay proof is incomplete: {report_path.name}")
        if version == REPORT_VERSION:
            source = report.get("source")
            if not isinstance(source, Mapping):
                raise ValueError(f"native replay report has no source: {report_path.name}")
            plan_path, plan = _load_plan(
                directory, source, report.get("planSha256"), report_path.name
            )
            decisions = report.get("decisions")
            if not isinstance(decisions, list) or report.get("matchedDecisions") != len(decisions):
                raise ValueError(f"native replay decision count mismatch: {report_path.name}")
            steps = _steps_from_proof(plan, source, decisions, report_path.name)
            plan_hash = _sha256(plan_path)
            character = plan["run"]["character"]
            episode_id = source.get("episode_id")
        elif version == SEQUENTIAL_REPORT_VERSION:
            sources = report.get("sources")
            combats = report.get("combats")
            if (
                not isinstance(sources, list)
                or len(sources) != 2
                or not all(isinstance(source, Mapping) for source in sources)
                or not isinstance(combats, list)
                or len(combats) != 2
            ):
                raise ValueError(f"sequential native replay structure is invalid: {report_path.name}")
            plans: list[tuple[Path, dict[str, Any]]] = []
            for source, hash_key in zip(
                sources, ("firstPlanSha256", "nextPlanSha256"), strict=True
            ):
                plans.append(
                    _load_plan(directory, source, report.get(hash_key), report_path.name)
                )
            episode_ids = {source.get("episode_id") for source in sources}
            run_hashes = {source.get("run_hash") for source in sources}
            characters = {plan["run"]["character"] for _, plan in plans}
            if len(episode_ids) != 1 or len(run_hashes) != 1 or len(characters) != 1:
                raise ValueError(f"sequential native replay changes run identity: {report_path.name}")
            steps = []
            segment_counts: list[int] = []
            for source, (_, plan), combat in zip(sources, plans, combats, strict=True):
                decisions = combat.get("decisions") if isinstance(combat, Mapping) else None
                if (
                    not isinstance(combat, Mapping)
                    or combat.get("encounter") != plan["combat"]["encounter"]
                ):
                    raise ValueError(f"sequential native replay encounter mismatch: {report_path.name}")
                segment = _steps_from_proof(plan, source, decisions, report_path.name)
                segment_counts.append(len(segment))
                steps.extend(segment)
            if report.get("matchedDecisions") != len(steps):
                raise ValueError(f"sequential native replay decision count mismatch: {report_path.name}")
            if (
                report.get("firstMatchedDecisions") not in (None, segment_counts[0])
                or report.get("nextMatchedDecisions") not in (None, segment_counts[1])
            ):
                raise ValueError(f"sequential native replay segment count mismatch: {report_path.name}")
            plan_hash = sha256(
                "".join(_sha256(path) for path, _ in plans).encode()
            ).hexdigest()
            character = next(iter(characters))
            episode_id = next(iter(episode_ids))
        else:
            raise ValueError(f"unsupported native replay report: {report_path.name}")
        results.append(
            {
                "episode_id": episode_id,
                "character": character,
                "plan_sha256": plan_hash,
                "report_sha256": _sha256(report_path),
                "steps": steps,
            }
        )
    return tuple(results)


__all__ = [
    "FORBIDDEN_POLICY_KEYS",
    "PLAN_VERSION",
    "REPORT_VERSION",
    "SEQUENTIAL_REPORT_VERSION",
    "load_validated_native_replays",
]
