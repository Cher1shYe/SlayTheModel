"""Bridge safe Spire Codex reconstructions into SpireFormer tensor shards.

The pure ``feature_decision`` adapter is intentionally independent of PyTorch
so its protocol projection can be audited on machines without the training
runtime.  ``assemble_spire_codex_dataset`` imports the existing SpireFormer
encoder and shard writer only when tensor publication is requested.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping, Sequence


TENSORIZER_VERSION = "spire-codex-bc-v2"
REWARD_VERSION = "bc-only-v1"
SPLIT_VERSION = "spire-codex-episode-split-v1"


def _coordinate(value: object) -> dict[str, int] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(",")
    if len(parts) != 2:
        return None
    try:
        column, row = (int(part) for part in parts)
    except ValueError:
        return None
    if row < 0 or column < 0:
        return None
    return {"row": row, "column": column}


def _card(card: Mapping[str, Any], deck_index: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "model_id": card.get("model_id"),
        "upgrade_level": card.get("upgrade", 0),
        "affliction_id": None,
        "affliction_count": len(card.get("afflictions", []))
        if isinstance(card.get("afflictions"), list) else 0,
        "enchantment_id": card.get("enchantment"),
        "enchantment_amount": card.get("enchantment_amount"),
        "display": None,
    }
    if deck_index is not None:
        result["deck_index"] = deck_index
    return result


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _surface(choice: Mapping[str, Any], source_kind: object) -> str:
    source = choice.get("source")
    decision_type = choice.get("decision_type")
    if source_kind == "shop_purchase" or source == "shop":
        return "Merchant"
    if source == "map" or decision_type == "map_node":
        return "Map"
    if source == "event" or decision_type == "event":
        return "Event"
    if source == "rest_site" or decision_type == "rest":
        return "RestSite"
    if source == "treasure" or decision_type == "treasure":
        return "Treasure"
    if source == "deck_select" or str(decision_type).startswith("deck_select"):
        return "CardGridChoice"
    if decision_type == "card_reward":
        return "CardReward"
    if decision_type == "relic_reward":
        return "RelicChoice"
    return "Rewards"


def _observation(step: Mapping[str, Any]) -> dict[str, Any]:
    source = step.get("observation")
    run = source.get("run") if isinstance(source, Mapping) else None
    if not isinstance(run, Mapping):
        raise ValueError("Spire Codex step has no reconstructed run observation")
    choice = step.get("choice")
    choice = choice if isinstance(choice, Mapping) else {}
    set_candidates = step.get("set_candidates")
    set_candidates = set_candidates if isinstance(set_candidates, list) else []
    bounds = step.get("selection_bounds")
    bounds = bounds if isinstance(bounds, Mapping) else {}
    room = run.get("room")
    room = room if isinstance(room, Mapping) else {}
    potions = [
        {"slot_index": potion.get("slot"), "model_id": potion.get("model_id")}
        for potion in run.get("potions", [])
        if isinstance(potion, Mapping)
    ]
    max_potion_count = max(
        3,
        1 + max(
            (potion["slot_index"] for potion in potions
             if type(potion.get("slot_index")) is int),
            default=-1,
        ),
    )
    map_state = run.get("map")
    map_state = map_state if isinstance(map_state, Mapping) else {}
    map_points = []
    for node in map_state.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        coordinate = _coordinate(node.get("coordinate"))
        if coordinate is None:
            continue
        map_points.append(
            {
                "coordinate": coordinate,
                "point_type": node.get("kind"),
                "visited": node.get("coordinate") == room.get("coord"),
                "children": [
                    child
                    for raw_child in node.get("children", [])
                    if (child := _coordinate(raw_child)) is not None
                ],
            }
        )
    candidates = []
    for option_index, candidate in enumerate(set_candidates):
        if not isinstance(candidate, Mapping):
            continue
        model_id = candidate.get("option_id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("set-selection candidate has no stable model ID")
        candidates.append(
            {
                "option_index": option_index,
                "model_id": model_id,
                "deck_index": None,
                "upgrade_level": candidate.get("upgrade", 0),
                "display": None,
            }
        )
    result: dict[str, Any] = {
        "schema_version": 5,
        "surface": _surface(choice, step.get("source_kind")),
        "choice_context": {
            "phase": "Selection" if candidates else "Default",
            "min_selections": bounds.get("minimum") if candidates else None,
            "max_selections": bounds.get("maximum") if candidates else None,
            "selected_count": 0,
            "cancelable": bounds.get("can_decline") is True,
            "requires_confirmation": bool(candidates),
        },
        "act_index": max(int(run.get("act", 1)) - 1, 0),
        "act_floor": None,
        "total_floor": run.get("floor"),
        "ascension_level": run.get("ascension"),
        "room_type": room.get("room_type") or room.get("kind") or "Unknown",
        "room_model_id": room.get("id"),
        "current_map_coordinate": _coordinate(room.get("coord")),
        "players": [
            {
                "player_id": 0,
                "character_id": run.get("character"),
                "current_hp": run.get("current_hp"),
                "max_hp": run.get("max_hp"),
                "gold": run.get("gold"),
                "max_potion_count": max_potion_count,
                "deck": [
                    _card(card, index)
                    for index, card in enumerate(run.get("deck", []))
                    if isinstance(card, Mapping)
                ],
                "relics": [
                    {
                        "model_id": relic.get("model_id"),
                        "display": (
                            {"visible_counter": relic.get("counter")}
                            if type(relic.get("counter")) is int else None
                        ),
                    }
                    for relic in run.get("relics", [])
                    if isinstance(relic, Mapping)
                ],
                "potions": potions,
            }
        ],
        "map_points": map_points,
        "card_selection_options": candidates or None,
    }
    return result


def _direct_action(option: Mapping[str, Any], choice: Mapping[str, Any]) -> dict[str, Any]:
    option_kind = option.get("kind")
    decision_type = choice.get("decision_type")
    if option_kind == "map_node":
        kind = "travel"
    elif option_kind == "event_option":
        kind = "choose_event_option"
    elif option_kind == "rest_option":
        kind = "choose_rest_site_option"
    elif option_kind == "card":
        kind = "choose_card"
    elif option_kind == "relic":
        kind = "choose_relic"
    elif option_kind == "decline":
        kind = "skip"
    elif option_kind == "reroll":
        kind = "choose_reward_alternative"
    elif option_kind in ("buy_card", "buy_relic", "buy_potion"):
        kind = option_kind
    elif option_kind == "buy_removal_service":
        kind = "open_card_removal"
    elif option_kind == "leave_shop":
        kind = "leave_merchant"
    elif decision_type == "treasure":
        kind = "take_treasure_relic"
    else:
        kind = "choose_minigame_option"
    option_id = option.get("option_id") or option.get("model_id") or option_kind
    result: dict[str, Any] = {
        "kind": kind,
        "target_id": option_id,
        "cost": option.get("cost"),
        "target_deck_index": None,
        "map_coordinate": _coordinate(option.get("option_id"))
        if option_kind == "map_node" else None,
        "is_selection_template": False,
    }
    return result


def feature_decision(step: Mapping[str, Any]) -> dict[str, Any]:
    """Project one eligible reconstructed step into the existing feature schema."""

    if step.get("record_type") != "step" or step.get("domain") != "outside_combat":
        raise ValueError("Spire Codex feature bridge accepts outside-combat steps only")
    if step.get("bc_eligible") is not True:
        raise ValueError("Spire Codex feature bridge accepts BC-eligible steps only")
    observation = _observation(step)
    choice = step.get("choice")
    choice = choice if isinstance(choice, Mapping) else {}
    action = step.get("action")
    if not isinstance(action, Mapping):
        raise ValueError("BC-eligible step has no selected action")

    candidates = observation.get("card_selection_options")
    if isinstance(candidates, list) and candidates:
        select_kind = choice.get("select_kind")
        template_kind = "remove_card_set" if select_kind == "remove" else "choose_card_set"
        legal_actions = [
            {
                "kind": template_kind,
                "target_id": f"selection:{select_kind or 'card'}",
                "cost": None,
                "target_deck_index": None,
                "map_coordinate": None,
                "is_selection_template": True,
            }
        ]
        if observation["choice_context"]["cancelable"]:
            legal_actions.append(
                {
                    "kind": "cancel_choice",
                    "target_id": "selection:cancel",
                    "cost": None,
                    "target_deck_index": None,
                    "map_coordinate": None,
                    "is_selection_template": False,
                }
            )
        if action.get("kind") == "select_set":
            selected_indexes = action.get("candidate_indices")
            if not isinstance(selected_indexes, list) or any(
                type(index) is not int or not 0 <= index < len(candidates)
                for index in selected_indexes
            ):
                raise ValueError("set-selection action has invalid candidate indexes")
            selected_action: dict[str, Any] | None = {
                **legal_actions[0],
                "is_selection_template": False,
                "selected_cards": [candidates[index] for index in selected_indexes],
            }
            selected_action_index = 0
        elif action.get("kind") == "decline" and len(legal_actions) == 2:
            selected_action = None
            selected_action_index = 1
        else:
            raise ValueError("set-selection step has an unsupported selected action")
    else:
        raw_actions = step.get("legal_actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ValueError("direct-choice step has no legal action list")
        legal_actions = [
            _direct_action(option, choice)
            for option in raw_actions
            if isinstance(option, Mapping)
        ]
        selected_action_index = action.get("action_index")
        if type(selected_action_index) is not int or not 0 <= selected_action_index < len(legal_actions):
            raise ValueError("selected action index is outside the legal action list")
        selected_action = None

    return {
        "episode_id": step.get("episode_id"),
        "segment_index": step.get("segment_index"),
        "step_index": step.get("step_index"),
        "source_sequence": step.get("source_sequence"),
        "domain": "outside_combat",
        "trajectory_group": f"segment:{step.get('segment_index')}",
        "trajectory_index": step.get("step_index"),
        "context": {},
        "observation": observation,
        "legal_actions": legal_actions,
        "selected_action_index": selected_action_index,
        "selected_action": selected_action,
    }


@dataclass(frozen=True, slots=True)
class EpisodeFeatures:
    episode_id: str
    character: str
    source_sha256: str
    steps: tuple[dict[str, Any], ...]


def _load_episodes(root: Path) -> tuple[EpisodeFeatures, ...]:
    manifest = [
        json.loads(line)
        for line in (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    episodes: list[EpisodeFeatures] = []
    seen: set[str] = set()
    for row in manifest:
        episode_id = row.get("episode_id")
        expected_sha256 = row.get("output_sha256")
        if (
            not isinstance(episode_id, str)
            or not episode_id
            or episode_id in seen
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError("reconstruction manifest has an invalid episode identity")
        seen.add(episode_id)
        path = root / row["file"]
        if _sha256_file(path) != expected_sha256:
            raise ValueError(f"reconstructed episode hash mismatch: {episode_id}")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            records = [json.loads(line) for line in stream if line.strip()]
        if any(
            record.get("episode_id") != episode_id
            for record in records
            if isinstance(record, Mapping)
        ):
            raise ValueError(f"reconstructed episode ID mismatch: {episode_id}")
        steps = tuple(
            feature_decision(record)
            for record in records
            if record.get("record_type") == "step" and record.get("bc_eligible") is True
        )
        if steps:
            episodes.append(
                EpisodeFeatures(
                    episode_id=episode_id,
                    character=row["character"],
                    source_sha256=expected_sha256,
                    steps=steps,
                )
            )
    return tuple(episodes)


def split_episodes(episodes: Sequence[EpisodeFeatures]) -> dict[str, tuple[EpisodeFeatures, ...]]:
    """Create a deterministic, character-stratified episode split."""

    by_character: dict[str, list[EpisodeFeatures]] = defaultdict(list)
    for episode in episodes:
        by_character[episode.character].append(episode)
    splits: dict[str, list[EpisodeFeatures]] = {"train": [], "val": [], "test": []}
    for character, group in sorted(by_character.items()):
        ordered = sorted(
            group,
            key=lambda episode: sha256(
                f"{SPLIT_VERSION}:{episode.episode_id}".encode()
            ).hexdigest(),
        )
        # Keep enough full episodes for meaningful held-out metrics while
        # preserving every character in every split.  Rounded 10% holdouts
        # yield an approximately 80/10/10 split for the curated archive.
        holdout = max(1, int(len(ordered) * 0.1 + 0.5)) if len(ordered) >= 3 else 0
        if holdout * 2 >= len(ordered):
            holdout = 1
        test = ordered[:holdout]
        val = ordered[holdout : holdout * 2]
        train = ordered[holdout * 2 :]
        if not train:
            raise ValueError(f"character {character} has no training episode after split")
        splits["train"].extend(train)
        splits["val"].extend(val)
        splits["test"].extend(test)
    return {
        name: tuple(sorted(items, key=lambda episode: episode.episode_id))
        for name, items in splits.items()
        if items
    }


def _windows(episode: EpisodeFeatures, encoder: Any, *, max_window_steps: int) -> list[Any]:
    from .batch import DecisionDomain
    from .trajectory import Trajectory, TrajectoryStep

    trajectories: list[Any] = []
    current: list[Any] = []
    previous: Mapping[str, Any] | None = None

    def flush() -> None:
        if current:
            trajectories.append(Trajectory(tuple(current)))
            current.clear()

    for source in episode.steps:
        if previous is not None and (
            source["trajectory_group"] != previous["trajectory_group"]
            or source["trajectory_index"] != previous["trajectory_index"] + 1
        ):
            flush()
        domain = source["domain"]
        observation = source["observation"]
        legal_actions = source["legal_actions"]
        run_context = source.get("context", {}).get("run_context", {})
        entities = encoder.encode_observation(domain, observation, run_context)
        actions = encoder.encode_actions(domain, observation, legal_actions)
        candidates = encoder.encode_set_candidates(domain, observation)
        selected_action = source.get("selected_action")
        selected_mask = None
        if selected_action is not None:
            if candidates is None:
                raise ValueError("concrete set action has no encoded candidates")
            selected_mask = encoder.encode_selected_set(
                domain, observation, selected_action, candidates
            )
            executed = encoder.encode_executed_action(
                domain, observation, selected_action
            )
        else:
            executed = actions[source["selected_action_index"]].clone()
        encoded = TrajectoryStep(
            entity_features=entities,
            legal_action_features=actions,
            selected_action_index=source["selected_action_index"],
            return_to_go=0.0,
            timestep=source["trajectory_index"],
            domain=DecisionDomain.COMBAT if domain == "combat" else DecisionDomain.OUTSIDE_COMBAT,
            value_target=None,
            set_candidate_features=None if candidates is None else candidates.features,
            set_selected_mask=selected_mask,
            set_min_select=None if candidates is None else candidates.min_select,
            set_max_select=None if candidates is None else candidates.max_select,
            executed_action_features=executed,
        )
        encoded.validate(encoder.spec.entity_feature_dim, encoder.spec.action_feature_dim)
        current.append(encoded)
        if len(current) >= max_window_steps:
            flush()
        previous = source
    flush()
    return trajectories


def assemble_spire_codex_dataset(
    reconstructed_root: str | Path,
    output: str | Path,
    *,
    max_window_steps: int = 64,
    trajectories_per_shard: int = 128,
    max_vocabulary_size: int = 512,
    native_replay_root: str | Path | None = None,
) -> Mapping[str, Any]:
    """Publish BC-only tensor shards with a deterministic episode split."""

    if max_window_steps < 1 or trajectories_per_shard < 1 or max_vocabulary_size < 1:
        raise ValueError("window, shard, and vocabulary sizes must be positive")
    try:
        import torch
        from .data import TensorShardWriter
        from .raw_features import RawFeatureEncoder, RawFeatureSpec
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyTorch is required to publish SpireFormer tensor shards") from exc

    root = Path(reconstructed_root).resolve()
    destination = Path(output).resolve()
    if destination.exists():
        raise FileExistsError(f"output already exists: {destination}")
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    if summary.get("format_version") != "stm-spire-codex-reconstructed-v1":
        raise ValueError("unsupported Spire Codex reconstruction format")
    if summary.get("bc_observation_missing_fields") != {}:
        raise ValueError("BC observations still contain missing public fields")
    policy = summary.get("policy")
    if (
        not isinstance(policy, Mapping)
        or policy.get("resumed_segments_are_excluded_until_continuity_is_verified")
        is not True
    ):
        raise ValueError("reconstruction does not prove resumed segments are excluded")
    outside_episodes = _load_episodes(root)
    outside_step_count = sum(len(episode.steps) for episode in outside_episodes)
    if outside_step_count != summary.get("bc_eligible_steps"):
        raise ValueError("reconstruction BC count differs from its episode files")
    episodes_by_id = {episode.episode_id: episode for episode in outside_episodes}
    native_step_count = 0
    native_source_count = 0
    if native_replay_root is not None:
        from .spire_codex_native import load_validated_native_replays

        for native in load_validated_native_replays(native_replay_root):
            episode_id = native["episode_id"]
            if not isinstance(episode_id, str) or not episode_id:
                raise ValueError("native replay has no episode identity")
            native_steps = tuple(native["steps"])
            native_step_count += len(native_steps)
            native_source_count += 1
            existing = episodes_by_id.get(episode_id)
            combined_hash = sha256(
                ((existing.source_sha256 if existing is not None else "")
                 + native["plan_sha256"] + native["report_sha256"]).encode()
            ).hexdigest()
            episodes_by_id[episode_id] = EpisodeFeatures(
                episode_id=episode_id,
                character=native["character"],
                source_sha256=combined_hash,
                steps=(existing.steps if existing is not None else ()) + native_steps,
            )
    episodes = tuple(sorted(episodes_by_id.values(), key=lambda episode: episode.episode_id))
    splits = split_episodes(episodes)
    specification = RawFeatureSpec.fit(
        (
            step
            for episode in splits["train"]
            for step in episode.steps
        ),
        max_vocabulary_size=max_vocabulary_size,
    )
    encoder = RawFeatureEncoder(specification)
    dataset_material = {
        "tensorizer": TENSORIZER_VERSION,
        "feature_hash": specification.sha256(),
        "sources": sorted((episode.episode_id, episode.source_sha256) for episode in episodes),
        "max_window_steps": max_window_steps,
        "feature_dtype": "float16",
    }
    dataset_id = sha256(
        json.dumps(dataset_material, sort_keys=True, separators=(",", ":")).encode()
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
            "conditioning": "constant_zero_bc_only",
            "dataset_id": dataset_id,
            "vocabulary_hash": specification.sha256(),
            "entity_feature_dim": specification.entity_feature_dim,
            "action_feature_dim": specification.action_feature_dim,
            "feature_dtype": "float16",
            "source_episode_count": len(episodes),
            "source_bc_steps": sum(len(episode.steps) for episode in episodes),
            "source_outside_bc_steps": outside_step_count,
            "source_native_combat_bc_steps": native_step_count,
            "native_combat_replay_count": native_source_count,
            "split_version": SPLIT_VERSION,
            "max_window_steps": max_window_steps,
            "trajectories_per_shard": trajectories_per_shard,
            "feature_spec_source": "fit_train_only",
            "splits": {},
        }
        for split_name, split_episodes_value in splits.items():
            trajectory_count = 0
            step_count = 0
            set_labels = 0
            episode_reports: list[dict[str, Any]] = []
            with TensorShardWriter(
                temporary / split_name,
                entity_feature_dim=specification.entity_feature_dim,
                action_feature_dim=specification.action_feature_dim,
                tensorizer_version=TENSORIZER_VERSION,
                vocabulary_hash=specification.sha256(),
                reward_version=REWARD_VERSION,
                dataset_id=f"{dataset_id}-{split_name}",
                trajectories_per_shard=trajectories_per_shard,
                # Raw features are bounded one-hot flags and scaled asinh
                # values.  FP16 storage is lossless for the flags and is
                # promoted back to FP32 by the trainer, while avoiding a
                # multi-gigabyte cache for repeated public map sets.
                dtype=torch.float16,
            ) as writer:
                for episode in split_episodes_value:
                    trajectories = _windows(
                        episode, encoder, max_window_steps=max_window_steps
                    )
                    episode_set_labels = sum(
                        step.get("selected_action") is not None for step in episode.steps
                    )
                    for trajectory in trajectories:
                        writer.add(trajectory)
                        trajectory_count += 1
                        step_count += len(trajectory.steps)
                    set_labels += episode_set_labels
                    episode_reports.append(
                        {
                            "episode_id": episode.episode_id,
                            "source_sha256": episode.source_sha256,
                            "raw_steps": len(episode.steps),
                            "bc_steps": len(episode.steps),
                            "excluded_steps": 0,
                            "exclusion_reasons": {},
                            "set_labels": episode_set_labels,
                            "trajectories": len(trajectories),
                            "raw_value_target_valid": False,
                        }
                    )
            report["splits"][split_name] = {
                "episodes": episode_reports,
                "episode_ids": [episode.episode_id for episode in split_episodes_value],
                "episode_count": len(split_episodes_value),
                "bc_steps": step_count,
                "step_count": step_count,
                "set_labels": set_labels,
                "trajectories": trajectory_count,
                "trajectory_count": trajectory_count,
                "by_character": dict(sorted(
                    (character, sum(episode.character == character for episode in split_episodes_value))
                    for character in sorted({episode.character for episode in split_episodes_value})
                )),
            }
        if sum(value["step_count"] for value in report["splits"].values()) != report["source_bc_steps"]:
            raise ValueError("tensor split step count does not match safe BC source count")
        (temporary / "assembly-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
        return report
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = [
    "EpisodeFeatures",
    "REWARD_VERSION",
    "SPLIT_VERSION",
    "TENSORIZER_VERSION",
    "assemble_spire_codex_dataset",
    "feature_decision",
    "split_episodes",
]
