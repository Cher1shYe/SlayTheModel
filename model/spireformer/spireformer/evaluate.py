"""Offline, held-out evaluation for a SpireFormer tensor dataset.

This module evaluates the *recorded human action*, not game strength.  A
Decision Transformer can receive the recorded return-to-go as an input; that
number can contain future rewards.  Evaluation therefore replaces it with zero
by default.  ``conditioning='recorded'`` is an explicit diagnostic mode whose
policy scores must not be interpreted as an online result.

Tensor manifests do not contain source episode IDs.  We reject an identical
training dataset or reused shard, but the caller must also establish that the
source episodes of the train and hold-out datasets are disjoint.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from math import sqrt
from pathlib import Path
from typing import Any, Mapping

import torch
from torch import Tensor, nn

from .batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets
from .checkpoint import load_checkpoint
from .data import TensorDatasetManifest, TensorShardDataset, create_trajectory_dataloader
from .manifest import SpireFormerManifest
from .model import SpireFormer, SpireFormerOutput
from .precision import PrecisionMode, autocast_context, ensure_precision_supported


@dataclass(slots=True)
class _PolicyTotals:
    count: int = 0
    correct: int = 0
    first_legal_correct: int = 0
    nll_sum: float = 0.0
    uniform_expected_correct_sum: float = 0.0
    uniform_nll_sum: float = 0.0

    def add(
        self,
        mask: Tensor,
        *,
        predicted: Tensor,
        selected: Tensor,
        first_legal: Tensor,
        nll: Tensor,
        action_counts: Tensor,
    ) -> None:
        count = int(mask.sum().item())
        if not count:
            return
        self.count += count
        self.correct += int(((predicted == selected) & mask).sum().item())
        self.first_legal_correct += int(
            ((first_legal == selected) & mask).sum().item()
        )
        self.nll_sum += float(nll[mask].sum().item())
        counts = action_counts[mask].to(torch.float64)
        self.uniform_expected_correct_sum += float(counts.reciprocal().sum().item())
        self.uniform_nll_sum += float(counts.log().sum().item())

    def result(self) -> dict[str, int | float | None]:
        return {
            "count": self.count,
            "top1_accuracy": self.correct / self.count if self.count else None,
            "nll": self.nll_sum / self.count if self.count else None,
            "uniform_expected_top1": (
                self.uniform_expected_correct_sum / self.count if self.count else None
            ),
            "uniform_nll": self.uniform_nll_sum / self.count if self.count else None,
            "first_legal_accuracy": (
                self.first_legal_correct / self.count if self.count else None
            ),
        }


@dataclass(slots=True)
class _SetTotals:
    count: int = 0
    exact: int = 0
    count_correct: int = 0
    joint_action_and_set_correct: int = 0

    def result(self) -> dict[str, int | float | None]:
        return {
            "count": self.count,
            "exact_set_accuracy": self.exact / self.count if self.count else None,
            "count_accuracy": (
                self.count_correct / self.count if self.count else None
            ),
            "joint_action_and_set_accuracy": (
                self.joint_action_and_set_correct / self.count
                if self.count
                else None
            ),
        }


@dataclass(slots=True)
class _ValueTotals:
    count: int = 0
    absolute_error_sum: float = 0.0
    squared_error_sum: float = 0.0

    def result(self) -> dict[str, int | float | None]:
        return {
            "count": self.count,
            "mae": self.absolute_error_sum / self.count if self.count else None,
            "rmse": (
                sqrt(self.squared_error_sum / self.count) if self.count else None
            ),
        }


def _device(value: str | torch.device) -> torch.device:
    if value == "auto":
        value = (
            "cuda"
            if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available() else "cpu"
        )
    resolved = torch.device(value)
    if resolved.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    if resolved.type == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS was requested but is not available")
    if resolved.type not in {"cpu", "cuda", "mps"}:
        raise ValueError(f"unsupported evaluation device {resolved.type!r}")
    return resolved


def _check_compatibility(
    model_manifest: SpireFormerManifest, dataset: TensorDatasetManifest
) -> None:
    fields = ("tensorizer_version", "vocabulary_hash", "reward_version")
    for name in fields:
        if getattr(model_manifest, name) != getattr(dataset, name):
            raise ValueError(f"evaluation dataset {name} differs from checkpoint")
    if model_manifest.no_save_load_information != dataset.no_save_load_information:
        raise ValueError("evaluation dataset information regime differs from checkpoint")
    if model_manifest.config.entity_feature_dim != dataset.entity_feature_dim:
        raise ValueError("evaluation dataset entity feature width differs from checkpoint")
    if model_manifest.config.action_feature_dim != dataset.action_feature_dim:
        raise ValueError("evaluation dataset action feature width differs from checkpoint")


def _training_overlap_status(
    extra: Mapping[str, Any],
    held_out: TensorDatasetManifest,
    *,
    allow_training_dataset: bool,
) -> str:
    resume_contract = extra.get("resume_contract")
    if not isinstance(resume_contract, Mapping):
        return "training_manifest_unavailable"
    raw_train = resume_contract.get("dataset_manifest")
    if not isinstance(raw_train, Mapping):
        return "training_manifest_unavailable"
    training = TensorDatasetManifest.from_dict(raw_train)
    same_id = training.dataset_id == held_out.dataset_id
    hashes = {shard.sha256 for shard in training.shards}
    shared_shard = any(shard.sha256 in hashes for shard in held_out.shards)
    if same_id or shared_shard:
        if not allow_training_dataset:
            raise ValueError(
                "evaluation dataset is the training dataset or reuses a training shard"
            )
        return "training_overlap_allowed"
    return "dataset_id_and_shards_disjoint"


def _checkpoint_training_manifest(extra: Mapping[str, Any]) -> TensorDatasetManifest:
    resume_contract = extra.get("resume_contract")
    raw_training = (
        resume_contract.get("dataset_manifest")
        if isinstance(resume_contract, Mapping)
        else None
    )
    if not isinstance(raw_training, Mapping):
        raise ValueError(
            "checkpoint has no training dataset manifest for assembly split verification"
        )
    return TensorDatasetManifest.from_dict(raw_training)


def _load_assembly_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("assembly report is unreadable or malformed") from error
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("assembly report schema is invalid")
    return report


def _report_split_identities(
    report: Mapping[str, Any], split: str, manifest: TensorDatasetManifest
) -> tuple[set[str], set[str]]:
    for name in ("tensorizer_version", "vocabulary_hash", "reward_version"):
        if report.get(name) != getattr(manifest, name):
            raise ValueError(f"assembly report {name} differs from tensor manifest")
    for name in ("entity_feature_dim", "action_feature_dim"):
        if report.get(name) != getattr(manifest, name):
            raise ValueError(f"assembly report {name} differs from tensor manifest")
    splits = report.get("splits")
    if not isinstance(splits, dict) or split not in splits:
        raise ValueError(f"assembly report lacks {split} split")
    entry = splits[split]
    if not isinstance(entry, dict) or not isinstance(entry.get("episodes"), list):
        raise ValueError(f"assembly report {split} episodes are malformed")
    episodes = entry["episodes"]
    if (
        entry.get("episode_count") != len(episodes)
        or entry.get("bc_steps") != manifest.step_count
        or entry.get("trajectories") != manifest.trajectory_count
    ):
        raise ValueError(f"assembly report {split} counts differ from tensor manifest")
    ids: set[str] = set()
    sources: set[str] = set()
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ValueError(f"assembly report {split} episode is malformed")
        episode_id = episode.get("episode_id")
        source_hash = episode.get("source_sha256")
        if (
            not isinstance(episode_id, str)
            or not episode_id
            or not isinstance(source_hash, str)
            or len(source_hash) != 64
        ):
            raise ValueError(f"assembly report {split} episode identity is invalid")
        try:
            int(source_hash, 16)
        except ValueError as error:
            raise ValueError(
                f"assembly report {split} source hash is not hexadecimal"
            ) from error
        if episode_id in ids or source_hash in sources:
            raise ValueError(f"assembly report {split} repeats an episode")
        ids.add(episode_id)
        sources.add(source_hash)
    return ids, sources


def _verify_assembled_episode_split(
    dataset: TensorShardDataset,
    extra: Mapping[str, Any],
    *,
    training_assembly_root: str | Path | None,
) -> bool:
    """Verify episode IDs from one assembly or an independently assembled holdout.

    A standalone tensor dataset has no episode identifiers.  The assembler
    publishes those identifiers in ``assembly-report.json``.  A present but
    inconsistent report is an error, rather than an unverified success.
    """

    path = dataset.root.resolve()
    split = path.name
    holdout_report_path = path.parent / "assembly-report.json"
    if training_assembly_root is None:
        if split not in {"val", "test"} or not holdout_report_path.is_file():
            return False
        train_root = path.parent
    else:
        if split != "holdout":
            raise ValueError("training_assembly_root requires a holdout dataset")
        if not holdout_report_path.is_file():
            raise ValueError("holdout assembly report is missing")
        train_root = Path(training_assembly_root).resolve()

    checkpoint_train = _checkpoint_training_manifest(extra)
    root_train = TensorDatasetManifest.load(train_root / "train")
    if checkpoint_train.to_dict() != root_train.to_dict():
        raise ValueError(
            "checkpoint training dataset manifest does not match assembly root/train"
        )
    train_report = _load_assembly_report(train_root / "assembly-report.json")
    holdout_report = (
        train_report
        if training_assembly_root is None
        else _load_assembly_report(holdout_report_path)
    )
    train_ids, train_sources = _report_split_identities(
        train_report, "train", root_train
    )
    holdout_ids, holdout_sources = _report_split_identities(
        holdout_report, split, dataset.manifest
    )
    if train_ids & holdout_ids or train_sources & holdout_sources:
        raise ValueError("assembly report train and held-out episodes overlap")
    return True


def evaluate_model(
    model: nn.Module,
    dataset: TensorShardDataset,
    *,
    device: str | torch.device = "cpu",
    precision: PrecisionMode | str = PrecisionMode.FP32,
    batch_size: int = 1,
    conditioning: str = "zero",
) -> dict[str, Any]:
    """Score hard action labels from one dataset without changing model weights.

    ``conditioning='zero'`` is the default because recorded return-to-go can
    reveal rewards obtained after the decision.  ``recorded`` is allowed only
    for an explicitly labeled diagnostic.  A top-1 hit on an action with one
    legal candidate is trivial; ``nontrivial`` excludes those decisions.
    """

    if not isinstance(dataset, TensorShardDataset):
        raise TypeError("dataset must be a TensorShardDataset")
    if conditioning not in {"zero", "recorded"}:
        raise ValueError("conditioning must be 'zero' or 'recorded'")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    resolved_device = _device(device)
    mode = PrecisionMode.parse(precision)
    ensure_precision_supported(mode, resolved_device)
    model = model.to(resolved_device)
    model.eval()
    loader = create_trajectory_dataloader(dataset, batch_size=batch_size)

    policy = {
        "overall": _PolicyTotals(),
        "nontrivial": _PolicyTotals(),
        "combat": _PolicyTotals(),
        "combat_nontrivial": _PolicyTotals(),
        "outside_combat": _PolicyTotals(),
        "outside_combat_nontrivial": _PolicyTotals(),
    }
    sets = _SetTotals()
    values = _ValueTotals()

    with torch.inference_mode():
        for batch, targets in loader:
            # Tensor shards may store bounded features in FP16 to save disk.
            # Match the trainer: keep master inputs in FP32 and let autocast
            # choose BF16 operations when requested.  Leaving cached FP16 here
            # makes Set Transformer's FP32 inducing queries incompatible with
            # FP16 keys and values during ordinary CPU/FP32 evaluation.
            batch = batch.to(resolved_device, dtype=torch.float32)
            targets = targets.to(resolved_device, dtype=torch.float32)
            targets.validate(batch)
            if conditioning == "zero":
                batch = replace(batch, returns_to_go=torch.zeros_like(batch.returns_to_go))
            with autocast_context(mode, resolved_device):
                output: SpireFormerOutput = model(batch)

            legal = batch.legal_action_mask
            logits = output.policy_logits.float().masked_fill(~legal, -torch.inf)
            # A padded step has no legal action.  Replace only that row so
            # log_softmax never produces NaN from an all-masked padding row.
            safe_logits = torch.where(
                batch.step_mask.unsqueeze(-1), logits, torch.zeros_like(logits)
            )
            selected = targets.action_indices.long()
            active = batch.step_mask
            if targets.policy_target_mask is not None:
                active = active & targets.policy_target_mask
            log_probs = torch.log_softmax(safe_logits, dim=-1)
            nll = -log_probs.gather(-1, selected.unsqueeze(-1)).squeeze(-1)
            if not torch.isfinite(nll[active]).all():
                raise ValueError("evaluation model produced non-finite policy loss")
            predicted = logits.argmax(dim=-1)
            first_legal = legal.to(torch.int64).argmax(dim=-1)
            action_counts = legal.sum(dim=-1)
            nontrivial = active & (action_counts > 1)
            masks = {
                "overall": active,
                "nontrivial": nontrivial,
                "combat": active & (batch.domain_ids == int(DecisionDomain.COMBAT)),
                "combat_nontrivial": nontrivial
                & (batch.domain_ids == int(DecisionDomain.COMBAT)),
                "outside_combat": active
                & (batch.domain_ids == int(DecisionDomain.OUTSIDE_COMBAT)),
                "outside_combat_nontrivial": nontrivial
                & (batch.domain_ids == int(DecisionDomain.OUTSIDE_COMBAT)),
            }
            for name, mask in masks.items():
                policy[name].add(
                    mask,
                    predicted=predicted,
                    selected=selected,
                    first_legal=first_legal,
                    nll=nll,
                    action_counts=action_counts,
                )

            if targets.set_target_mask is not None:
                set_mask = targets.set_target_mask & active
                count = int(set_mask.sum().item())
                if count:
                    if batch.set_candidate_mask is None or targets.set_selected_mask is None:
                        raise ValueError("set target is missing candidate or selected mask")
                    predicted_sets = SpireFormer.select_sets(output, batch)
                    gold_sets = targets.set_selected_mask
                    exact = (
                        (predicted_sets == gold_sets) | ~batch.set_candidate_mask
                    ).all(dim=-1)
                    predicted_counts = predicted_sets.sum(dim=-1)
                    gold_counts = gold_sets.sum(dim=-1)
                    sets.count += count
                    sets.exact += int((exact & set_mask).sum().item())
                    sets.count_correct += int(
                        ((predicted_counts == gold_counts) & set_mask).sum().item()
                    )
                    sets.joint_action_and_set_correct += int(
                        (exact & (predicted == selected) & set_mask).sum().item()
                    )

            value_mask = batch.step_mask
            if targets.value_target_mask is not None:
                value_mask = value_mask & targets.value_target_mask
            value_count = int(value_mask.sum().item())
            if value_count:
                expected = targets.value_targets
                if expected.ndim == 3:
                    expected = expected.squeeze(-1)
                error = output.state_value.float() - expected.float()
                if not torch.isfinite(error[value_mask]).all():
                    raise ValueError("evaluation model produced non-finite value estimates")
                values.count += value_count
                values.absolute_error_sum += float(error[value_mask].abs().sum().item())
                values.squared_error_sum += float(error[value_mask].square().sum().item())

    return {
        "kind": "offline_evaluation",
        "trajectory_count": dataset.manifest.trajectory_count,
        "conditioning": conditioning,
        "recorded_future_return_input": conditioning == "recorded",
        "policy": {
            "overall": policy["overall"].result(),
            "nontrivial": policy["nontrivial"].result(),
            "by_domain": {
                "combat": {
                    "overall": policy["combat"].result(),
                    "nontrivial": policy["combat_nontrivial"].result(),
                },
                "outside_combat": {
                    "overall": policy["outside_combat"].result(),
                    "nontrivial": policy["outside_combat_nontrivial"].result(),
                },
            },
        },
        "set_selection": sets.result(),
        "value": values.result(),
    }


def evaluate_checkpoint(
    checkpoint_path: str | Path,
    dataset_path: str | Path,
    *,
    device: str | torch.device = "auto",
    precision: PrecisionMode | str = PrecisionMode.FP32,
    batch_size: int = 1,
    verify_hashes: bool = True,
    conditioning: str = "zero",
    allow_training_dataset: bool = False,
    training_assembly_root: str | Path | None = None,
) -> dict[str, Any]:
    """Load trusted model weights and evaluate an independently prepared shard set.

    The overlap check can detect equal dataset IDs and identical shard hashes.
    With ``training_assembly_root``, a separate ``holdout`` assembly can be
    checked against the training assembly's episode report.  Without either
    assembly report, tensor manifests alone cannot establish episode identity.
    """

    raw = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if not isinstance(raw, Mapping) or not isinstance(raw.get("manifest"), Mapping):
        raise ValueError("checkpoint manifest is missing or malformed")
    model_manifest = SpireFormerManifest.from_dict(raw["manifest"])
    del raw
    dataset = TensorShardDataset(dataset_path, verify_hashes=verify_hashes)
    _check_compatibility(model_manifest, dataset.manifest)
    model = SpireFormer(model_manifest.config)
    state = load_checkpoint(
        checkpoint_path,
        model=model,
        expected_manifest=model_manifest,
        map_location="cpu",
        restore_rng=False,
    )
    overlap_status = _training_overlap_status(
        state.extra, dataset.manifest, allow_training_dataset=allow_training_dataset
    )
    episode_split_verified = _verify_assembled_episode_split(
        dataset,
        state.extra,
        training_assembly_root=training_assembly_root,
    )
    result = evaluate_model(
        model,
        dataset,
        device=device,
        precision=precision,
        batch_size=batch_size,
        conditioning=conditioning,
    )
    result.update(
        {
            "checkpoint_step": state.step,
            "dataset_id": dataset.manifest.dataset_id,
            "overlap_check": overlap_status,
            "episode_split_verified": episode_split_verified,
        }
    )
    return result


__all__ = ["evaluate_checkpoint", "evaluate_model"]
