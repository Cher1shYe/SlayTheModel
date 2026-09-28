"""Admission-aware R4 training data loader and weighted loss.

This module deliberately keeps the existing 1,970-parameter model and feature
ABI.  It adds only the data contract that the frozen R4 admission index
describes: trajectory-balanced policy weights and a value head that excludes
unresolved outcomes without changing their policy labels.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Sequence
import random
import math

import torch
from torch import Tensor

from .samples import TrainingSample, read_jsonl
from .training import DeepSetsPolicyValue, TrainConfig, encode_actions, encode_observation
from .versions import CHECKPOINT_FORMAT, FEATURE_ABI, OBSERVATION_SCHEMA_VERSION, REWARD_LEDGER_VERSION, SEARCH_SEMANTICS_VERSION


@dataclass(frozen=True)
class R4WeightedSample:
    sample: TrainingSample
    task_id: str
    partition: str
    policy: str
    outcome: str
    policy_weight: float
    value_weight: float


@dataclass(frozen=True)
class R4AdmissionDataset:
    index_path: Path
    train: tuple[R4WeightedSample, ...]
    validation: tuple[R4WeightedSample, ...]
    sealed_evaluation_seeds: tuple[str, ...]

    @property
    def policy_samples(self) -> tuple[R4WeightedSample, ...]:
        return self.train + self.validation

    @property
    def value_samples(self) -> tuple[R4WeightedSample, ...]:
        return tuple(item for item in self.policy_samples if item.value_weight > 0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().lower()


def _load_index(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") != "azcombat.r4-training-admission.v1" or raw.get("status") != "admitted":
        raise ValueError("R4 admission index is not an admitted v1 index")
    summary = raw.get("summary")
    if not isinstance(summary, dict) or summary.get("tasks") != 20 or summary.get("samples") != 1204:
        raise ValueError("R4 admission summary does not match the frozen 20-task batch")
    entries = raw.get("entries")
    if not isinstance(entries, list) or len(entries) != summary["tasks"]:
        raise ValueError("R4 admission entries are incomplete")
    return raw


def _validate_contract(entry: dict, sample: TrainingSample) -> None:
    if sample.seed != entry["seed"] or sample.outcome != entry["outcome"]:
        raise ValueError(f"trajectory metadata differs for {entry['taskId']}")
    if entry.get("rowCount") < 1 or entry.get("policyRowWeight", 0) <= 0:
        raise ValueError(f"invalid policy weight for {entry['taskId']}")
    if entry.get("policy") not in {"pure-mcts", "tree-candidate"}:
        raise ValueError(f"unsupported behavior policy for {entry['taskId']}")
    if entry.get("rewardLedgerVersions") != [REWARD_LEDGER_VERSION]:
        raise ValueError(f"reward ledger contract differs for {entry['taskId']}")
    for key, expected in (("observationSchemaVersion", OBSERVATION_SCHEMA_VERSION),
                          ("searchSemanticsVersion", SEARCH_SEMANTICS_VERSION)):
        # These fields are carried in the index entry in current R4 indexes.
        if key in entry and entry[key] != expected:
            raise ValueError(f"{key} differs for {entry['taskId']}")
    if entry.get("fallbacks", 0) != 0:
        raise ValueError(f"fallback was recorded for {entry['taskId']}")
    if entry.get("acceptanceStatus") not in {"accepted", "accepted-after-reaudit"}:
        raise ValueError(f"unaccepted trajectory {entry['taskId']}")


def load_r4_admission(index_path: Path) -> R4AdmissionDataset:
    """Load and revalidate the frozen index without rewriting any JSONL."""
    index_path = Path(index_path).resolve()
    raw = _load_index(index_path)
    entries = raw["entries"]
    task_ids = [entry.get("taskId") for entry in entries]
    if any(not isinstance(task_id, str) for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
        raise ValueError("R4 task IDs are not unique")
    trajectory_hashes = [entry.get("trajectorySha256", "").lower() for entry in entries]
    if any(len(value) != 64 for value in trajectory_hashes) or len(set(trajectory_hashes)) != len(trajectory_hashes):
        raise ValueError("R4 trajectory hashes are not unique")

    loaded: list[R4WeightedSample] = []
    for entry in entries:
        trajectory = Path(entry["trajectoryPath"]).resolve()
        if not trajectory.is_file() or _sha256(trajectory) != entry["trajectorySha256"].lower():
            raise ValueError(f"trajectory provenance changed for {entry['taskId']}")
        samples = read_jsonl(trajectory, require_current_search_semantics=True)
        if len(samples) != entry["rowCount"]:
            raise ValueError(f"row count changed for {entry['taskId']}")
        policy_weight = float(entry["policyRowWeight"])
        value_weight = float(entry["valueRowWeight"])
        for sample in samples:
            _validate_contract(entry, sample)
            loaded.append(R4WeightedSample(sample, entry["taskId"], entry["partition"],
                                            entry["policy"], entry["outcome"], policy_weight, value_weight))

    train = tuple(item for item in loaded if item.partition == "train")
    validation = tuple(item for item in loaded if item.partition == "validation")
    if not train or not validation:
        raise ValueError("R4 admission must contain both train and validation rows")
    observed_train = {item.sample.seed for item in train}
    observed_validation = {item.sample.seed for item in validation}
    if observed_train & observed_validation:
        raise ValueError("R4 seed leaked across train and validation")
    sealed = tuple(raw.get("plan", {}).get("seedUse", {}).get("sealedEvaluation", ()))
    if any(item.sample.seed in set(sealed) for item in loaded):
        raise ValueError("sealed evaluation seed entered R4 data")
    return R4AdmissionDataset(index_path, train, validation, sealed)


def weighted_loss(model: DeepSetsPolicyValue, item: R4WeightedSample) -> tuple[Tensor, Tensor, Tensor]:
    """Return policy/value losses with frozen per-row admission weights."""
    entities, globals_ = encode_observation(item.sample)
    action_ids, actions = encode_actions(item.sample)
    logits, value = model(entities, globals_, actions)
    visits = torch.tensor([item.sample.visit_policy.get(action_id, 0) for action_id in action_ids], dtype=torch.float32)
    policy = visits / visits.sum()
    policy_loss = -(policy * torch.log_softmax(logits, dim=0)).sum()
    value_loss = (value - item.sample.value_target).square()
    return item.policy_weight * policy_loss + item.value_weight * value_loss, policy_loss, value_loss


def verify_r4_weights(dataset: R4AdmissionDataset) -> dict[str, float]:
    """Check the frozen mass rules before a training process is started."""
    policy_mass = sum(item.policy_weight for item in dataset.train if item.policy == "pure-mcts")
    policy_mass += sum(item.policy_weight for item in dataset.train if item.policy == "tree-candidate")
    value_mass = sum(item.value_weight for item in dataset.train)
    unresolved_value_mass = sum(item.value_weight for item in dataset.train if item.outcome == "unresolved")
    return {"trainPolicyMass": policy_mass, "trainValueMass": value_mass,
            "trainUnresolvedValueMass": unresolved_value_mass}


def _weighted_metrics(model: DeepSetsPolicyValue, rows: Sequence[R4WeightedSample], label: str) -> dict[str, float]:
    totals = {"loss": 0.0, "policyLoss": 0.0, "valueLoss": 0.0, "policyMass": 0.0, "valueMass": 0.0}
    with torch.no_grad():
        for item in rows:
            total, policy_loss, value_loss = weighted_loss(model, item)
            totals["loss"] += total.item()
            totals["policyLoss"] += item.policy_weight * policy_loss.item()
            totals["valueLoss"] += item.value_weight * value_loss.item()
            totals["policyMass"] += item.policy_weight
            totals["valueMass"] += item.value_weight
    if totals["policyMass"] <= 0:
        raise ValueError("R4 evaluation has no policy mass")
    return {f"{label}Loss": totals["loss"], f"{label}PolicyLoss": totals["policyLoss"],
            f"{label}ValueLoss": totals["valueLoss"], f"{label}PolicyMass": totals["policyMass"],
            f"{label}ValueMass": totals["valueMass"]}


def weighted_epoch(model: DeepSetsPolicyValue, rows: Sequence[R4WeightedSample], optimizer) -> None:
    """One optimizer step on the sum of trajectory-weighted gradients.

    Stepping Adam separately per row cancels much of a scalar weight through
    moment normalization. Accumulate first so row duplication cannot reweight
    a trajectory merely by adding optimizer steps.
    """
    optimizer.zero_grad(set_to_none=True)
    for item in rows:
        if not all(math.isfinite(w) and w >= 0 for w in (item.policy_weight, item.value_weight)):
            raise ValueError('invalid head weight')
        loss, _, _ = weighted_loss(model, item)
        if not torch.isfinite(loss):
            raise ValueError('nonfinite weighted loss')
        loss.backward()
    if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
        raise ValueError('nonfinite weighted gradient')
    optimizer.step()


def train_r4(dataset: R4AdmissionDataset, checkpoint: Path, config: TrainConfig = TrainConfig(),
             run_name: str = "R4-SMOKE-WEIGHTED-MIX-001") -> dict:
    """Run the pre-registered engineering fit and write one provenance-bound checkpoint."""
    if checkpoint.exists():
        raise FileExistsError("checkpoint already exists")
    if config.hidden != 16 or config.epochs != 5 or config.learning_rate != 0.001 or config.seed != 20260926:
        raise ValueError("R4 smoke run requires the frozen configuration")
    masses = verify_r4_weights(dataset)
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    model = DeepSetsPolicyValue(config.hidden)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    history: list[dict[str, float | int]] = []
    for epoch in range(config.epochs):
        model.train()
        ordered = list(dataset.train)
        random.shuffle(ordered)
        weighted_epoch(model, ordered, optimizer)
        model.eval()
        metrics = {"epoch": epoch + 1, **_weighted_metrics(model, dataset.train, "train"),
                   **_weighted_metrics(model, dataset.validation, "validation")}
        history.append(metrics)
    metadata = {"runName": run_name, "status": "engineering-fit", "config": {
        "epochs": config.epochs, "learningRate": config.learning_rate, "hidden": config.hidden,
        "seed": config.seed}, "parameterCount": sum(p.numel() for p in model.parameters()),
        "featureAbi": FEATURE_ABI, "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
        "trainRows": len(dataset.train), "validationRows": len(dataset.validation),
        "trainSeeds": sorted({item.sample.seed for item in dataset.train}),
        "validationSeeds": sorted({item.sample.seed for item in dataset.validation}),
        "sealedEvaluationSeeds": list(dataset.sealed_evaluation_seeds), "admissionIndex": str(dataset.index_path),
        "admissionIndexSha256": _sha256(dataset.index_path), "weights": masses,
        "history": history, "selectedEpoch": config.epochs, "selectionMetric": "fixed-final-epoch",
        "optimizerContract": "trajectory-weighted-full-batch.v1",
        "unresolvedHandling": "policy-kept-value-weight-zero", "promotable": False}
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"format": CHECKPOINT_FORMAT, "featureAbi": FEATURE_ABI,
                "observationSchemaVersion": OBSERVATION_SCHEMA_VERSION,
                "model": model.state_dict(), "config": {"hidden": config.hidden},
                "metadata": metadata}, checkpoint)
    return metadata
