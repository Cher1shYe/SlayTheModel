"""Assemble one BC-only corpus from verified collector and Spire Codex data."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import torch

from .assemble import (
    BC_ONLY_SCHEME,
    REWARD_VERSION,
    _episode_trajectories,
    _file_sha256,
    _select_splits,
    _source_paths,
    _training_decisions,
)
from .batch import DecisionDomain
from .data import TensorShardWriter
from .raw_features import RawFeatureEncoder, RawFeatureSpec
from .raw_journal import EpisodeAudit, load_episode
from .spire_codex_native import load_validated_native_replays
from .spire_codex_tensor import (
    EpisodeFeatures,
    _load_episodes,
    _windows,
    split_episodes,
)


TENSORIZER_VERSION = "mixed-collector-spire-codex-bc-v1"
SPLIT_VERSION = "spire-codex-v1+explicit-human-v1"


def _load_codex(
    reconstructed_root: Path, native_replay_root: Path | None
) -> tuple[tuple[EpisodeFeatures, ...], dict[str, int]]:
    summary = json.loads(
        (reconstructed_root / "summary.json").read_text(encoding="utf-8")
    )
    if summary.get("format_version") != "stm-spire-codex-reconstructed-v1":
        raise ValueError("unsupported Spire Codex reconstruction format")
    if summary.get("bc_observation_missing_fields") != {}:
        raise ValueError("Spire Codex BC observations contain missing public fields")
    policy = summary.get("policy")
    if not isinstance(policy, Mapping) or policy.get(
        "resumed_segments_are_excluded_until_continuity_is_verified"
    ) is not True:
        raise ValueError("Spire Codex resumed segments are not safely excluded")

    outside = _load_episodes(reconstructed_root)
    outside_steps = sum(len(episode.steps) for episode in outside)
    if outside_steps != summary.get("bc_eligible_steps"):
        raise ValueError("Spire Codex reconstruction BC count differs from its files")
    episodes = {episode.episode_id: episode for episode in outside}
    native_steps = 0
    native_sources = 0
    if native_replay_root is not None:
        for native in load_validated_native_replays(native_replay_root):
            episode_id = native["episode_id"]
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError("native replay has no episode identity")
            steps = tuple(native["steps"])
            native_steps += len(steps)
            native_sources += 1
            existing = episodes.get(episode_id)
            combined_hash = sha256(
                (
                    (existing.source_sha256 if existing is not None else "")
                    + native["plan_sha256"]
                    + native["report_sha256"]
                ).encode()
            ).hexdigest()
            episodes[episode_id] = EpisodeFeatures(
                episode_id=episode_id,
                character=native["character"],
                source_sha256=combined_hash,
                steps=(existing.steps if existing is not None else ()) + steps,
            )
    return tuple(sorted(episodes.values(), key=lambda item: item.episode_id)), {
        "outside_steps": outside_steps,
        "native_steps": native_steps,
        "native_sources": native_sources,
    }


def _load_human_splits(
    inputs: Sequence[str | Path],
    train_episodes: Sequence[str],
    val_episodes: Sequence[str],
    test_episodes: Sequence[str],
) -> dict[str, tuple[EpisodeAudit, ...]]:
    if not train_episodes or not val_episodes or not test_episodes:
        raise ValueError("mixed assembly requires explicit human train/val/test episodes")
    requested = tuple(
        prefix.replace("-", "").lower()
        for prefix in (*train_episodes, *val_episodes, *test_episodes)
    )
    paths = []
    for path in _source_paths(inputs):
        with path.open("rb") as stream:
            try:
                episode_id = json.loads(stream.readline()).get("episode_id", "")
            except (UnicodeError, ValueError, AttributeError):
                episode_id = ""
        normalized = episode_id.replace("-", "").lower() if isinstance(episode_id, str) else ""
        if any(normalized.startswith(prefix) for prefix in requested):
            paths.append(path)
    audits = tuple(load_episode(path) for path in paths)
    return _select_splits(
        audits, train_episodes, val_episodes, test_episodes
    )


def _count_domains(trajectories: Iterable[Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for trajectory in trajectories:
        for step in trajectory.steps:
            counts[
                "combat"
                if step.domain == DecisionDomain.COMBAT
                else "outside_combat"
            ] += 1
    return counts


def assemble_mixed_bc_dataset(
    reconstructed_root: str | Path,
    human_inputs: Sequence[str | Path],
    output: str | Path,
    *,
    human_train_episodes: Sequence[str],
    human_val_episodes: Sequence[str],
    human_test_episodes: Sequence[str],
    native_replay_root: str | Path | None = None,
    max_window_steps: int = 64,
    trajectories_per_shard: int = 128,
    max_vocabulary_size: int = 512,
) -> Mapping[str, Any]:
    """Tensorize both sources with a vocabulary fit on their training splits."""

    if max_window_steps < 1 or trajectories_per_shard < 1 or max_vocabulary_size < 1:
        raise ValueError("window, shard, and vocabulary sizes must be positive")
    reconstructed = Path(reconstructed_root).resolve()
    native_root = None if native_replay_root is None else Path(native_replay_root).resolve()
    destination = Path(output).resolve()
    if destination.exists():
        raise FileExistsError(f"output already exists: {destination}")

    codex_episodes, codex_counts = _load_codex(reconstructed, native_root)
    codex_splits = split_episodes(codex_episodes)
    human_splits = _load_human_splits(
        human_inputs,
        human_train_episodes,
        human_val_episodes,
        human_test_episodes,
    )
    specification = RawFeatureSpec.fit(
        (
            decision
            for source in (
                (
                    step
                    for episode in codex_splits["train"]
                    for step in episode.steps
                ),
                _training_decisions(human_splits["train"]),
            )
            for decision in source
        ),
        max_vocabulary_size=max_vocabulary_size,
    )
    encoder = RawFeatureEncoder(specification)

    identities: set[str] = set()
    source_hashes: set[str] = set()
    material: list[tuple[str, str, str, str]] = []
    for split in ("train", "val", "test"):
        for episode in codex_splits[split]:
            material.append((split, "spire_codex", episode.episode_id, episode.source_sha256))
        for audit in human_splits[split]:
            material.append((split, "human_collector", audit.episode_id, _file_sha256(audit.path)))
    for _, _, episode_id, source_hash in material:
        if episode_id in identities or source_hash in source_hashes:
            raise ValueError("an episode identity or source hash appears in more than one split")
        identities.add(episode_id)
        source_hashes.add(source_hash)
    dataset_id = sha256(
        json.dumps(
            {
                "tensorizer": TENSORIZER_VERSION,
                "feature_hash": specification.sha256(),
                "sources": sorted(material),
                "max_window_steps": max_window_steps,
                "feature_dtype": "float16",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:32]

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        (temporary / "feature-spec.json").write_text(
            json.dumps(specification.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report: dict[str, Any] = {
            "schema_version": 1,
            "tensorizer_version": TENSORIZER_VERSION,
            "reward_version": REWARD_VERSION,
            "reward_scheme": BC_ONLY_SCHEME,
            "conditioning": "constant_zero_bc_only",
            "dataset_id": dataset_id,
            "vocabulary_hash": specification.sha256(),
            "entity_feature_dim": specification.entity_feature_dim,
            "action_feature_dim": specification.action_feature_dim,
            "feature_dtype": "float16",
            "feature_spec_source": "fit_combined_train_only",
            "split_version": SPLIT_VERSION,
            "max_window_steps": max_window_steps,
            "trajectories_per_shard": trajectories_per_shard,
            "source_spire_codex_outside_bc_steps": codex_counts["outside_steps"],
            "source_spire_codex_native_combat_bc_steps": codex_counts["native_steps"],
            "native_combat_replay_count": codex_counts["native_sources"],
            "splits": {},
        }
        for split in ("train", "val", "test"):
            episode_reports: list[dict[str, Any]] = []
            trajectory_count = 0
            domain_counts: Counter[str] = Counter()
            source_counts: Counter[str] = Counter()
            with TensorShardWriter(
                temporary / split,
                entity_feature_dim=specification.entity_feature_dim,
                action_feature_dim=specification.action_feature_dim,
                tensorizer_version=TENSORIZER_VERSION,
                vocabulary_hash=specification.sha256(),
                reward_version=REWARD_VERSION,
                dataset_id=f"{dataset_id}-{split}",
                trajectories_per_shard=trajectories_per_shard,
                dtype=torch.float16,
            ) as writer:
                for episode in codex_splits[split]:
                    trajectories = _windows(
                        episode, encoder, max_window_steps=max_window_steps
                    )
                    for trajectory in trajectories:
                        writer.add(trajectory)
                    counts = _count_domains(trajectories)
                    domain_counts.update(counts)
                    trajectory_count += len(trajectories)
                    source_counts["spire_codex"] += sum(counts.values())
                    set_labels = sum(
                        step.get("selected_action") is not None for step in episode.steps
                    )
                    episode_reports.append({
                        "episode_id": episode.episode_id,
                        "source_sha256": episode.source_sha256,
                        "source_type": "spire_codex",
                        "raw_steps": len(episode.steps),
                        "bc_steps": len(episode.steps),
                        "excluded_steps": 0,
                        "exclusion_reasons": {},
                        "set_labels": set_labels,
                        "trajectories": len(trajectories),
                        "raw_value_target_valid": False,
                    })
                for audit in human_splits[split]:
                    trajectories, episode_report = _episode_trajectories(
                        audit, encoder, max_window_steps, BC_ONLY_SCHEME
                    )
                    for trajectory in trajectories:
                        writer.add(trajectory)
                    counts = _count_domains(trajectories)
                    domain_counts.update(counts)
                    trajectory_count += len(trajectories)
                    source_counts["human_collector"] += sum(counts.values())
                    episode_reports.append({
                        **episode_report,
                        "source_type": "human_collector",
                    })
            step_count = sum(item["bc_steps"] for item in episode_reports)
            report["splits"][split] = {
                "episodes": episode_reports,
                "episode_ids": [item["episode_id"] for item in episode_reports],
                "episode_count": len(episode_reports),
                "bc_steps": step_count,
                "step_count": step_count,
                "set_labels": sum(item["set_labels"] for item in episode_reports),
                "trajectories": trajectory_count,
                "trajectory_count": trajectory_count,
                "by_domain": dict(sorted(domain_counts.items())),
                "by_source": dict(sorted(source_counts.items())),
            }
        report["source_episode_count"] = sum(
            split["episode_count"] for split in report["splits"].values()
        )
        report["source_bc_steps"] = sum(
            split["bc_steps"] for split in report["splits"].values()
        )
        report["source_human_bc_steps"] = sum(
            split["by_source"].get("human_collector", 0)
            for split in report["splits"].values()
        )
        (temporary / "assembly-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return report
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = ["TENSORIZER_VERSION", "assemble_mixed_bc_dataset"]
