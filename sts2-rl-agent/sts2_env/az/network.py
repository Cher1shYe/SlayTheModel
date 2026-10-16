"""Small CPU policy/value network, legal-only loss, strict debug checkpoints."""
import os
from pathlib import Path
import tempfile

import numpy as np
import torch
from torch import nn

from .config import ACTION_VERSION, CONTENT_VERSION, REWARD_VERSION, RULES_VERSION, atomic_replace, content_hash
from .encoder import CARDS, CARD_FEATURES, ENCODER_VERSION, MODE, SCHEMA, SCHEMA_HASH, schema_for


def batch_observations(observations, device="cpu"):
    if not observations:
        raise ValueError("Empty observation batch")
    if len({(obs.information_mode, obs.reward_version, obs.content_version) for obs in observations}) != 1:
        raise ValueError("Cannot mix debug and observable observations")
    return {key: torch.as_tensor(np.stack([getattr(obs, key) for obs in observations]),
                                 device=device, dtype=(torch.long if key == "card_ids" else
                                                       torch.bool if key == "legal_mask" else torch.float32))
            for key in SCHEMA["shapes"]}


def masked_log_probs(logits, mask):
    if logits.shape != mask.shape or mask.dtype != torch.bool or not mask.any(dim=-1).all():
        raise ValueError("Policy requires a nonempty boolean legal mask per state")
    if not torch.isfinite(logits).all():
        raise ValueError("Nonfinite policy logits")
    return torch.log_softmax(logits.masked_fill(~mask, -torch.inf), dim=-1)


class PolicyValueNetwork(nn.Module):
    def __init__(self, information_mode=MODE, reward_version=REWARD_VERSION, content_version=CONTENT_VERSION):
        super().__init__()
        self.information_mode = information_mode
        self.reward_version = reward_version
        self.content_version = content_version
        self.schema = schema_for(information_mode, reward_version, content_version)
        self.embedding = nn.Embedding(len(self.schema["card_vocabulary"]), 32, padding_idx=0)
        width = 10 * (32 + len(self.schema["card_features"])) + len(self.schema["numeric_features"]) + self.schema["action_size"]
        self.trunk = nn.Sequential(nn.Linear(width, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU())
        self.policy = nn.Linear(256, self.schema["action_size"])
        self.value = nn.Linear(256, 1)

    def forward(self, batch):
        embedded = self.embedding(batch["card_ids"])
        hand = torch.cat([embedded, batch["card_features"]], dim=-1).flatten(1)
        shared = self.trunk(torch.cat([hand, batch["numeric"], batch["legal_mask"].float()], dim=-1))
        return self.policy(shared), torch.tanh(self.value(shared)).squeeze(-1)

    @torch.no_grad()
    def predict(self, observation):
        if (observation.information_mode != self.information_mode or observation.reward_version != self.reward_version
                or observation.content_version != self.content_version):
            raise ValueError("Model/observation information mode mismatch")
        batch = batch_observations([observation], next(self.parameters()).device)
        logits, values = self(batch)
        probabilities = masked_log_probs(logits, batch["legal_mask"]).exp()
        if not torch.isfinite(values).all():
            raise ValueError("Nonfinite value prediction")
        return probabilities[0].cpu().numpy(), float(values[0])


def policy_value_loss(model, batch, policy_targets, value_targets):
    logits, values = model(batch)
    mask = batch["legal_mask"]
    if (policy_targets.shape != logits.shape or value_targets.shape != values.shape
            or not torch.isfinite(policy_targets).all() or not torch.isfinite(value_targets).all()
            or (policy_targets < 0).any() or (policy_targets[~mask] != 0).any()
            or (value_targets.abs() > 1).any()
            or not torch.allclose(policy_targets.sum(-1), torch.ones_like(values), atol=1e-5)):
        raise ValueError("Invalid policy/value labels")
    logs = masked_log_probs(logits, mask)
    # Index legal entries before multiplication: never compute 0 * -inf.
    policy_loss = -(policy_targets[mask] * logs[mask]).sum() / len(values)
    value_loss = torch.mean((value_targets - values) ** 2)
    loss = policy_loss + value_loss
    if not torch.isfinite(loss):
        raise ValueError("Nonfinite loss")
    with torch.no_grad():
        entropy = -(logs[mask].exp() * logs[mask]).sum() / len(values)
        positive = mask & (policy_targets > 0)
        kl = (policy_targets[positive] * (policy_targets[positive].log() - logs[positive])).sum() / len(values)
    return loss, {"policy_loss": float(policy_loss.detach()), "value_loss": float(value_loss.detach()),
                  "policy_entropy": float(entropy), "value_mae": float((values - value_targets).abs().mean().detach()),
                  "kl_target_policy": float(kl)}


def code_digest():
    root = Path(__file__).resolve().parents[1]
    # Includes uncommitted simulator edits; a git HEAD alone would miss them.
    return content_hash({str(path.relative_to(root)).replace("\\", "/"): content_hash(path.read_text(encoding="utf-8"))
                         for path in sorted(root.rglob("*.py"))})


def save_checkpoint(path, model, model_version, config, statistics, iteration=0, training_state=None):
    if not model_version or any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError("Invalid model weights/version")
    schema = schema_for(model.information_mode, model.reward_version, model.content_version)
    payload = {"format_version": 1, "model_state": model.state_dict(), "model_version": model_version,
               "schema_hash": content_hash(schema), "encoder_version": schema["encoder_version"], "information_mode": model.information_mode,
               "action_schema_version": schema["action_schema_version"], "reward_version": model.reward_version,
               "rules_version": RULES_VERSION, "content_manifest_version": model.content_version,
               "code_digest": code_digest(), "config": config, "iteration": iteration,
               "statistics": statistics, "torch_version": str(torch.__version__),
               "resume_scope": "weights_only_no_coordinator"}
    if training_state is not None:
        payload.update(training_state=training_state, resume_scope="training_update_boundary")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            torch.save(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_checkpoint(path, expected_mode, expected_reward=REWARD_VERSION, expected_content=CONTENT_VERSION):
    payload = torch.load(path, map_location="cpu", weights_only=True)
    schema = schema_for(expected_mode, expected_reward, expected_content)
    expected = {"format_version": 1, "schema_hash": content_hash(schema), "information_mode": expected_mode,
                "encoder_version": schema["encoder_version"], "action_schema_version": schema["action_schema_version"],
                "reward_version": expected_reward, "rules_version": RULES_VERSION,
                "content_manifest_version": expected_content}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("Checkpoint mode/schema/version mismatch")
    model = PolicyValueNetwork(expected_mode, expected_reward, expected_content)
    model.load_state_dict(payload["model_state"], strict=True)
    if any(not torch.isfinite(t).all() for t in model.state_dict().values()):
        raise ValueError("Nonfinite checkpoint weights")
    model.eval()
    return model, payload


def save_debug_checkpoint(path, model, model_version, config, statistics, iteration=0):
    if model.information_mode != MODE:
        raise ValueError("Debug checkpoint requires debug model")
    return save_checkpoint(path, model, model_version, config, statistics, iteration)


def load_debug_checkpoint(path, expected_mode=MODE):
    if expected_mode != MODE:
        raise ValueError("Debug loader cannot load observable checkpoints")
    return load_checkpoint(path, MODE)
