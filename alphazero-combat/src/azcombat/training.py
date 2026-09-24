"""Strict MCTS JSONL warm-start training; no native replay state enters the model."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import random
from typing import Iterable, Sequence

import torch
from torch import Tensor, nn

from .samples import TrainingSample, read_jsonl
from .schema import ActionNode

ENTITY_DIM = 12
GLOBAL_DIM = 4
ACTION_DIM = 19
ACTION_KINDS = ("PlayCard", "UsePotion", "EndTurn", "Target", "Option", "CardSubset", "CardOrder", "NestedChoice")
FEATURE_ABI = "azcombat.features.v4"


def _hash(value: object) -> float:
    if value is None:
        return 0.0
    return int.from_bytes(hashlib.sha256(str(value).encode("utf-8")).digest()[:4], "big") / 0xffffffff


def _num(value: object) -> float:
    return float(value) if type(value) in (int, float) else 0.0


def encode_observation(sample: TrainingSample) -> tuple[Tensor, Tensor]:
    """Encode allowlisted player, card, relic, potion, orb, creature and power sets."""
    obs = sample.observation
    entities: list[list[float]] = []
    for player in obs["players"]:
        entities.append([1, _hash(player["characterId"]), _num(player["energy"]), _num(player["stars"]),
                         _num(player["turnNumber"]), _hash(player["phase"])] + [0] * 6)
        for pile in player["piles"]:
            if pile["pileType"].lower() == "draw" and pile["cards"]:
                raise ValueError("hidden draw pile contents cannot enter the policy encoder")
            for card in pile["cards"]:
                entities.append([2, _hash(card["modelId"]), _num(card["combatCardIndex"]),
                                 _num(card["energyCost"]), _hash(pile["pileType"]), _hash(card["afflictionId"]),
                                 _num(card["afflictionCount"]), len(card["keywords"])] + [0] * 4)
        for relic in player["relics"]:
            entities.append([3, _hash(relic["modelId"])] + [0] * 10)
        for potion in player["potions"]:
            entities.append([4, _hash(potion["modelId"]), _num(potion["slotIndex"])] + [0] * 9)
        for orb in player["orbs"]:
            entities.append([5, _hash(orb["modelId"]), _num(orb["passive"]), _num(orb["evoke"])] + [0] * 8)
    for creature in obs["creatures"]:
        entities.append([6, _hash(creature["monsterId"]), _num(creature["currentHp"]),
                         _num(creature["maxHp"]), _num(creature["block"]),
                         float(creature["playerId"] is not None)] + [0] * 6)
        if creature["currentIntent"] is not None:
            entities.append([8, _hash(creature["currentIntent"])] + [0] * 10)
        for power in creature["powers"]:
            entities.append([7, _hash(power["modelId"]), _num(power["amount"])] + [0] * 9)
    choice = obs["choice"]
    if choice is not None:
        entities.append([9, _hash(choice["triggerCardId"]), _hash(choice["effect"]),
                         _hash(choice["sourcePile"]), choice["minCount"], choice["maxCount"],
                         float(choice["ordered"]), len(choice["candidates"]),
                         len(choice["completedSelections"])] + [0] * 3)
        for index, candidate in enumerate(choice["candidates"]):
            entities.append([10, _hash(candidate["modelId"]), candidate["combatCardIndex"],
                             candidate["upgradeLevel"], index] + [0] * 7)
        for index, completed in enumerate(choice["completedSelections"]):
            card_ids = completed["combatCardIndices"]
            entities.append([11, _hash(completed["effect"]), len(card_ids),
                             _hash(json.dumps(card_ids, separators=(",", ":"))) if card_ids else 0.0,
                             index] + [0] * 7)
    if not entities:
        entities = [[0] * ENTITY_DIM]
    globals_ = [_num(obs["roundNumber"]), _hash(obs["currentSide"]),
                len(obs["players"]), len(obs["creatures"])]
    return torch.tensor(entities, dtype=torch.float32), torch.tensor(globals_, dtype=torch.float32)


def encode_actions(sample: TrainingSample) -> tuple[list[str], Tensor]:
    """Flatten legal tree in preorder; preserve candidate identity and path depth."""
    ids: list[str] = []
    features: list[list[float]] = []

    def visit(nodes: Sequence[ActionNode], depth: int) -> None:
        for node in nodes:
            ids.append(node.action_id)
            payload = node.payload or {}
            selected = payload.get("SelectedCards") or []
            # Replay identity and predicted damage/HP are diagnostics, never network inputs.
            selected_ids = [card["CardId"] for card in selected]
            features.append([float(node.kind == kind) for kind in ACTION_KINDS] + [
                _hash(payload.get("CardId")), _num(payload.get("CardOccurrence")),
                _num(payload.get("TargetCombatId")), 0.0, 0.0, len(selected_ids),
                sum(_hash(card_id) for card_id in selected_ids) / max(1, len(selected_ids)),
                _hash(json.dumps(selected_ids, separators=(",", ":"), ensure_ascii=True)) if selected_ids else 0.0,
                0.0, 0.0, float(depth),
            ])
            visit(node.children, depth + 1)

    visit(sample.legal_actions, 0)
    return ids, torch.tensor(features, dtype=torch.float32)


def split_by_seed(samples: Sequence[TrainingSample], fraction: float = 0.2) -> tuple[list[TrainingSample], list[TrainingSample]]:
    if not 0 < fraction < 1:
        raise ValueError("validation fraction must be between 0 and 1")
    seeds = sorted({s.seed for s in samples}, key=lambda seed: hashlib.sha256(seed.encode()).digest())
    if len(seeds) < 2:
        raise ValueError("at least two independent seeds are required for train/validation")
    validation_seeds = set(seeds[:max(1, min(len(seeds) - 1, round(len(seeds) * fraction)))])
    return ([s for s in samples if s.seed not in validation_seeds],
            [s for s in samples if s.seed in validation_seeds])


class CombatDataset:
    def __init__(self, paths: Iterable[Path]):
        self.paths = tuple(Path(p) for p in paths)
        if not self.paths:
            raise ValueError("at least one JSONL path is required")
        self.samples = [sample for path in self.paths for sample in read_jsonl(path)]
        if not self.samples:
            raise ValueError("no strictly valid training samples")

    def __len__(self) -> int:
        return len(self.samples)


class DeepSetsPolicyValue(nn.Module):
    def __init__(self, hidden: int = 128):
        super().__init__()
        self.hidden = hidden
        self.phi = nn.Sequential(nn.Linear(ENTITY_DIM, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
        self.trunk = nn.Sequential(nn.Linear(hidden + GLOBAL_DIM, hidden), nn.ReLU(), nn.Linear(hidden, hidden), nn.ReLU())
        self.candidate = nn.Sequential(nn.Linear(hidden + ACTION_DIM, hidden), nn.ReLU(), nn.Linear(hidden, 1))
        self.value = nn.Sequential(nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 1), nn.Tanh())

    def forward(self, entities: Tensor, global_features: Tensor, actions: Tensor) -> tuple[Tensor, Tensor]:
        state = self.trunk(torch.cat((self.phi(entities).sum(dim=0), global_features)))
        logits = self.candidate(torch.cat((state.expand(actions.shape[0], -1), actions), dim=-1)).squeeze(-1)
        return logits, self.value(state).squeeze(-1)


@dataclass(frozen=True)
class TrainConfig:
    epochs: int = 5
    learning_rate: float = 0.001
    validation_fraction: float = 0.2
    seed: int = 0
    hidden: int = 128


def _loss(model: DeepSetsPolicyValue, sample: TrainingSample) -> tuple[Tensor, Tensor, Tensor]:
    entities, global_features = encode_observation(sample)
    action_ids, actions = encode_actions(sample)
    logits, value = model(entities, global_features, actions)
    visits = torch.tensor([sample.visit_policy.get(action_id, 0) for action_id in action_ids], dtype=torch.float32)
    policy = visits / visits.sum()
    policy_loss = -(policy * torch.log_softmax(logits, dim=0)).sum()
    value_loss = (value - sample.value_target).square()
    return policy_loss + value_loss, policy_loss, value_loss


def train(dataset: CombatDataset, checkpoint: Path, config: TrainConfig = TrainConfig(),
          init_checkpoint: Path | None = None, bootstrap_audit: dict | None = None) -> dict:
    if config.epochs < 1 or config.learning_rate <= 0 or config.hidden < 1:
        raise ValueError("invalid training hyperparameters")
    if checkpoint.exists():
        raise FileExistsError("checkpoint already exists")
    train_samples, validation = split_by_seed(dataset.samples, config.validation_fraction)
    random.seed(config.seed)
    torch.manual_seed(config.seed)
    parent_metadata = None
    if init_checkpoint is not None:
        model, parent = load_checkpoint(init_checkpoint)
        if parent["config"]["hidden"] != config.hidden:
            raise ValueError("continuation must retain the parent network width")
        parent_metadata = parent["metadata"]
        old = set(parent_metadata["trainSeeds"]) | set(parent_metadata["validationSeeds"])
        if old & {sample.seed for sample in dataset.samples}:
            raise ValueError("self-play seed overlaps parent training/validation lineage")
    else:
        model = DeepSetsPolicyValue(config.hidden)
    if bootstrap_audit is not None:
        actual_inputs = {(str(path.resolve()), hashlib.sha256(path.read_bytes()).hexdigest().lower())
                         for path in dataset.paths}
        audited_inputs = {(item["path"], item["sha256"].lower())
                          for item in bootstrap_audit.get("inputFiles", [])}
        if init_checkpoint is None or bootstrap_audit.get("format") != "azcombat.bootstrap-audit.v1" \
                or bootstrap_audit.get("valid") is not True \
                or bootstrap_audit.get("sourceCheckpointSha256", "").lower() != hashlib.sha256(init_checkpoint.read_bytes()).hexdigest().lower() \
                or {sample.seed for sample in dataset.samples} != set(bootstrap_audit.get("seeds", [])) \
                or len(actual_inputs) != len(dataset.paths) or actual_inputs != audited_inputs:
            raise ValueError("bootstrap audit/source model/seed lineage differs")
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    history = []
    for epoch in range(config.epochs):
        model.train()
        ordered = list(train_samples)
        random.shuffle(ordered)
        train_losses = []
        for sample in ordered:
            optimizer.zero_grad()
            loss, _, _ = _loss(model, sample)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())
        model.eval()
        with torch.no_grad():
            valid_loss = sum(_loss(model, sample)[0].item() for sample in validation) / len(validation)
        history.append({"epoch": epoch + 1, "trainLoss": sum(train_losses) / len(ordered), "validationLoss": valid_loss})
    metadata = {"trainSeeds": sorted({s.seed for s in train_samples} | set(parent_metadata["trainSeeds"] if parent_metadata else [])),
                "validationSeeds": sorted({s.seed for s in validation} | set(parent_metadata["validationSeeds"] if parent_metadata else [])),
                "history": history, "generation": (parent_metadata.get("generation", 0) + 1) if parent_metadata else 0,
                "inputSha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in dataset.paths},
                "samples": len(dataset)}
    if init_checkpoint is not None:
        metadata["parentCheckpointSha256"] = hashlib.sha256(init_checkpoint.read_bytes()).hexdigest()
        metadata["cumulativeSamples"] = parent_metadata.get("cumulativeSamples", parent_metadata["samples"]) + len(dataset)
    if bootstrap_audit is not None:
        metadata["bootstrapWaveManifestSha256"] = bootstrap_audit["waveManifestSha256"]
        metadata["bootstrapOnnxSha256"] = bootstrap_audit["candidateSha256"]
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"format": "azcombat.checkpoint.v3", "featureAbi": FEATURE_ABI, "model": model.state_dict(),
                "config": asdict(config), "metadata": metadata}, checkpoint)
    return metadata


def load_checkpoint(path: Path) -> tuple[DeepSetsPolicyValue, dict]:
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if payload.get("format") != "azcombat.checkpoint.v3" or payload.get("featureAbi") != FEATURE_ABI:
        raise ValueError("unsupported checkpoint format")
    model = DeepSetsPolicyValue(payload["config"]["hidden"])
    model.load_state_dict(payload["model"])
    model.eval()
    return model, payload
