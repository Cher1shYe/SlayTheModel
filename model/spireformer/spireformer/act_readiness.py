"""Read-only readiness checks for journals intended for act-reward training.

This reports integrity, provenance, boundary evidence, and source eligibility
separately. It never repairs a journal, relaxes unknown information modes, or
creates training tensors.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .act_reward_journal import BOUNDARY_CODE, act_episode_returns
from .act_rewards import ACT_RTG_SCHEME
from .assemble import (
    POLICY_TEACHER_INFORMATION,
    _file_sha256,
    _policy_exclusion_reason,
    _semantic_reasons,
    _source_paths,
    _validate_act_reward_source,
    _validate_complete_run,
)
from .raw_journal import EpisodeAudit, load_episode


def _gate(function: Any, audit: EpisodeAudit) -> dict[str, Any]:
    try:
        result = function(audit)
    except (ValueError, TypeError, KeyError) as exc:
        return {"passed": False, "error": str(exc)}
    details = result[1] if isinstance(result, tuple) and len(result) == 2 else None
    return {"passed": True, "error": None, "details": details}


def _episode_report(path: Path, allowed_policy_ids: tuple[str, ...]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source": str(path), "source_sha256": None, "journal_valid": False,
        "training_ready": False, "error": None,
    }
    try:
        report["source_sha256"] = _file_sha256(path)
        audit = load_episode(path)
        # A writer modifying a published source while it is being audited must
        # not receive a report bound to a different version of that source.
        if report["source_sha256"] != _file_sha256(path):
            raise ValueError("source changed while being audited")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report["error"] = str(exc)
        return report

    report.update({
        "journal_valid": True,
        "episode_id": audit.episode_id,
        "event_count": len(audit.events),
        "decision_count": len(audit.steps),
        "decisions_by_domain": dict(sorted(Counter(step.domain for step in audit.steps).items())),
        "information_regimes": dict(sorted(Counter(step.information_regime for step in audit.steps).items())),
        "outcome": audit.finished.payload.get("outcome") if audit.finished is not None else None,
    })
    actors: Counter[str] = Counter()
    policy_ids: Counter[str] = Counter()
    teacher_information: Counter[str] = Counter()
    boundary_phases: Counter[str] = Counter()
    lifecycle: Counter[str] = Counter()
    gaps: list[dict[str, Any]] = []
    decision_steps = {step.decision_id: step.global_step for step in audit.steps}
    for event in audit.events:
        if event.event_type == "action_submitted":
            policy = event.payload["policy"]
            actors[str(policy.get("actor") or "missing")] += 1
            policy_ids[str(policy.get("policy_id") or "missing")] += 1
            teacher_information[str(policy.get("teacher_information") or "missing")] += 1
        elif event.event_type == "coverage_gap":
            related_id = event.payload.get("related_decision_id")
            gaps.append({
                "event_sequence": event.event_sequence,
                "global_step": event.global_step,
                "related_global_step": decision_steps.get(related_id),
                "reason": event.payload.get("reason"),
            })
        elif event.event_type == "diagnostic":
            code = event.payload.get("code")
            if code in ("combat_started", "combat_ended"):
                lifecycle[code] += 1
            if code == BOUNDARY_CODE:
                data = event.payload.get("data")
                phase = data.get("phase") if isinstance(data, dict) else None
                boundary_phases[str(phase or "missing")] += 1

    human_bc_steps = 0
    native_mcts_candidate_steps = 0
    training_eligible_steps = 0
    exclusions: Counter[str] = Counter()
    for step in audit.steps:
        reasons = tuple(dict.fromkeys((*step.bc_reasons, *_semantic_reasons(step))))
        if not reasons:
            human_bc_steps += int(step.actor == "human")
            native_mcts_candidate_steps += int(
                step.actor == "policy"
                and _policy_exclusion_reason(step, ("native-mcts",)) is None
            )
        source_reason = _policy_exclusion_reason(step, allowed_policy_ids)
        if source_reason:
            reasons = (*reasons, source_reason)
        if not reasons:
            training_eligible_steps += 1
        exclusions.update(reasons)

    complete_run = _gate(_validate_complete_run, audit)
    act_source = _gate(_validate_act_reward_source, audit)
    reward_evidence = _gate(act_episode_returns, audit)
    report.update({
        "submission_actors": dict(sorted(actors.items())),
        "submission_policy_ids": dict(sorted(policy_ids.items())),
        "submission_teacher_information": dict(sorted(teacher_information.items())),
        "coverage_gap_count": len(gaps), "coverage_gaps": gaps,
        "native_combat_lifecycle": {
            "starts": lifecycle["combat_started"], "ends": lifecycle["combat_ended"],
        },
        "act_reward_boundaries": {
            "starts": boundary_phases["combat_start"],
            "ends": boundary_phases["combat_end"],
            "other": sum(count for phase, count in boundary_phases.items()
                         if phase not in ("combat_start", "combat_end")),
        },
        "human_bc_steps": human_bc_steps,
        "native_mcts_candidate_steps": native_mcts_candidate_steps,
        "training_eligible_steps": training_eligible_steps,
        "step_exclusion_reasons": dict(sorted(exclusions.items())),
        "complete_run_gate": complete_run,
        "act_source_gate": act_source,
        "act_reward_evidence_gate": reward_evidence,
        "training_ready": bool(act_source["passed"] and reward_evidence["passed"]
                               and training_eligible_steps),
    })
    return report


def audit_act_reward_data(
    inputs: Sequence[str | Path], *, allowed_policy_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Audit published files without writing sources or training artifacts.

    Directory inputs include only their immediate ``*.jsonl`` files, matching
    assembly. Compact views, partials, and quarantined subdirectories are not
    recursively mistaken for source episodes. One damaged file is reported
    without preventing checks of the remaining files.
    """

    allowed = tuple(sorted(set(allowed_policy_ids)))
    if any(policy not in POLICY_TEACHER_INFORMATION for policy in allowed):
        raise ValueError("allowed_policy_ids supports only native-mcts and first-legal")
    reports = []
    for path in _source_paths([Path(item).resolve() for item in inputs]):
        try:
            reports.append(_episode_report(path, allowed))
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # A valid envelope can still contain a malformed observation.
            # Isolate that source as well as byte/hash failures.
            reports.append({
                "source": str(path), "source_sha256": _file_sha256(path),
                "journal_valid": False, "training_ready": False,
                "error": f"semantic audit failed: {exc}",
            })
    ready = [report for report in reports if report["training_ready"]]
    return {
        "schema_version": 1,
        "reward_scheme": ACT_RTG_SCHEME,
        "allow_policy": list(allowed),
        "read_only": True,
        "tensor_output_created": False,
        "source_count": len(reports),
        "valid_journal_count": sum(report["journal_valid"] for report in reports),
        "training_ready_episode_count": len(ready),
        "training_ready_step_count": sum(report["training_eligible_steps"] for report in ready),
        "episodes": reports,
    }


def format_readiness_summary(report: dict[str, Any]) -> str:
    """Render a compact result without copying player identity or seed fields."""

    lines = [
        f"Act reward readiness: {report['training_ready_episode_count']}/{report['source_count']} "
        f"episodes ready, {report['training_ready_step_count']} eligible training steps.",
        "Allowed policy sources: " + (", ".join(report["allow_policy"]) or "none (human only)"),
    ]
    for episode in report["episodes"]:
        if not episode["journal_valid"]:
            lines.append(f"INVALID {Path(episode['source']).name}: {episode['error']}")
            continue
        identity = episode["episode_id"].replace("-", "")[:12]
        boundaries = episode["act_reward_boundaries"]
        status = "READY" if episode["training_ready"] else "NOT READY"
        lines.append(
            f"{status} {identity}: decisions={episode['decision_count']}, "
            f"gaps={episode['coverage_gap_count']}, "
            f"reward boundaries={boundaries['starts']}/{boundaries['ends']}, "
            f"human BC={episode['human_bc_steps']}, "
            f"native-mcts candidates={episode['native_mcts_candidate_steps']}"
        )
        for name in ("act_source_gate", "act_reward_evidence_gate"):
            if not episode[name]["passed"]:
                lines.append(f"  {name}: {episode[name]['error']}")
        if not episode["training_eligible_steps"]:
            lines.append("  No successful, source-allowed no-SL decisions passed the semantic audit.")
    return "\n".join(lines)
