"""The first trainable SpireFormer policy/value network."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any, Mapping

import torch
from torch import Tensor, nn

from .batch import DecisionDomain, SpireFormerBatch
from .decision_transformer import DecisionTransformerCore
from .set_transformer import MAB, SetEncoder


@dataclass(frozen=True, slots=True)
class SpireFormerConfig:
    """Serializable architecture settings for a SpireFormer checkpoint."""

    entity_feature_dim: int
    action_feature_dim: int
    model_dim: int = 128
    set_num_heads: int = 4
    set_num_layers: int = 2
    set_num_inducing_points: int | None = 16
    temporal_num_heads: int = 4
    temporal_num_layers: int = 4
    temporal_ff_multiplier: int = 4
    action_num_heads: int = 4
    dropout: float = 0.1
    max_timestep: int = 4096

    def validate(self) -> None:
        integer_fields = (
            "entity_feature_dim",
            "action_feature_dim",
            "model_dim",
            "set_num_heads",
            "set_num_layers",
            "temporal_num_heads",
            "temporal_num_layers",
            "temporal_ff_multiplier",
            "action_num_heads",
            "max_timestep",
        )
        for field_name in integer_fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.set_num_inducing_points is not None and (
            isinstance(self.set_num_inducing_points, bool)
            or not isinstance(self.set_num_inducing_points, int)
            or self.set_num_inducing_points <= 0
        ):
            raise ValueError("set_num_inducing_points must be positive or None")
        if self.model_dim % self.set_num_heads:
            raise ValueError("model_dim must be divisible by set_num_heads")
        if self.model_dim % self.temporal_num_heads:
            raise ValueError("model_dim must be divisible by temporal_num_heads")
        if self.model_dim % self.action_num_heads:
            raise ValueError("model_dim must be divisible by action_num_heads")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SpireFormerConfig":
        config = cls(**dict(values))
        config.validate()
        return config


@dataclass(frozen=True, slots=True)
class SpireFormerOutput:
    """Outputs aligned to the batch's dynamic legal-action dimension."""

    policy_logits: Tensor
    state_value: Tensor
    state_context: Tensor


class SpireFormer(nn.Module):
    """Unifies in-combat and outside-combat choices in one causal policy.

    The model has three deliberately separate responsibilities:

    1. A Set Transformer encodes the unordered entities visible at each step.
    2. A Decision Transformer conditions the current decision on the causal
       whole-run history and requested return-to-go.
    3. A dynamic scorer ranks *the legal actions supplied for that step*.

    The value path runs the same temporal core with return-to-go zeroed.  This
    prevents the common but subtle label leak where a value head merely copies
    the desired return that was given to the policy as a condition.
    """

    def __init__(self, config: SpireFormerConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config

        self.set_encoder = SetEncoder(
            input_dim=config.entity_feature_dim,
            embedding_dim=config.model_dim,
            num_heads=config.set_num_heads,
            num_layers=config.set_num_layers,
            num_inducing_points=config.set_num_inducing_points,
            num_seeds=1,
            dropout=config.dropout,
            layer_norm=True,
        )
        self.action_input = nn.Sequential(
            nn.Linear(config.action_feature_dim, config.model_dim, bias=False),
            nn.LayerNorm(config.model_dim),
            nn.GELU(),
        )
        self.domain_embedding = nn.Embedding(len(DecisionDomain), config.model_dim)
        self.temporal_core = DecisionTransformerCore(
            embedding_dim=config.model_dim,
            n_heads=config.temporal_num_heads,
            n_layers=config.temporal_num_layers,
            dropout=config.dropout,
            max_timestep=config.max_timestep,
            ff_multiplier=config.temporal_ff_multiplier,
        )
        self.action_entity_attention = MAB(
            query_dim=config.model_dim,
            key_dim=config.model_dim,
            model_dim=config.model_dim,
            num_heads=config.action_num_heads,
            dropout=config.dropout,
            layer_norm=True,
        )
        self.policy_query = nn.Linear(config.model_dim, config.model_dim)
        self.policy_key = nn.Linear(config.model_dim, config.model_dim)
        self.policy_interaction = nn.Sequential(
            nn.Linear(config.model_dim * 3, config.model_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.model_dim, 1),
        )
        self.value_head = nn.Sequential(
            nn.LayerNorm(config.model_dim),
            nn.Linear(config.model_dim, config.model_dim),
            nn.GELU(),
            nn.Linear(config.model_dim, 1),
            nn.Tanh(),
        )

    def set_gradient_checkpointing(self, enabled: bool = True) -> None:
        """Enable activation checkpointing in both expensive encoder stacks."""

        self.set_encoder.set_gradient_checkpointing(enabled)
        self.temporal_core.set_gradient_checkpointing(enabled)

    def forward(
        self, batch: SpireFormerBatch, *, validate: bool = True
    ) -> SpireFormerOutput:
        if validate:
            batch.validate(
                self.config.entity_feature_dim,
                self.config.action_feature_dim,
            )

        batch_size, steps, entity_count, _ = batch.entity_features.shape
        action_count = batch.legal_action_features.shape[2]
        flattened_steps = batch_size * steps

        entity_features = batch.entity_features.reshape(
            flattened_steps, entity_count, self.config.entity_feature_dim
        )
        # SetEncoder follows PyTorch's True=padding convention.
        entity_padding_mask = (~batch.entity_mask).reshape(
            flattened_steps, entity_count
        )
        entity_embeddings, pooled = self.set_encoder.forward_with_entities(
            entity_features,
            entity_padding_mask,
        )

        # Padding is allowed to carry sentinel IDs/timesteps in stored shards.
        # Replace them before table lookup; the corresponding outputs are
        # cleared by step_mask below and can never affect a valid token.
        safe_domain_ids = batch.domain_ids.masked_fill(~batch.step_mask, 0)
        safe_timesteps = batch.timesteps.masked_fill(~batch.step_mask, 0)
        domain_embeddings = self.domain_embedding(safe_domain_ids.to(torch.long))
        state_embeddings = pooled[:, 0].reshape(
            batch_size, steps, self.config.model_dim
        )
        state_embeddings = state_embeddings + domain_embeddings
        state_embeddings = state_embeddings.masked_fill(
            ~batch.step_mask.unsqueeze(-1), 0.0
        )

        previous_action_embeddings = (
            self.action_input(batch.previous_action_features) + domain_embeddings
        )
        previous_action_embeddings = previous_action_embeddings.masked_fill(
            ~batch.step_mask.unsqueeze(-1), 0.0
        )

        policy_context = self.temporal_core(
            state_embeddings,
            previous_action_embeddings,
            batch.returns_to_go,
            safe_timesteps,
            batch.step_mask,
        )
        # The value stream must not see the desired/realized RTG target.
        value_context = self.temporal_core(
            state_embeddings,
            previous_action_embeddings,
            torch.zeros_like(batch.returns_to_go),
            safe_timesteps,
            batch.step_mask,
        )

        action_embeddings = self.action_input(batch.legal_action_features)
        action_embeddings = action_embeddings + domain_embeddings.unsqueeze(2)
        flat_actions = action_embeddings.reshape(
            flattened_steps, action_count, self.config.model_dim
        )
        action_padding_mask = (~batch.legal_action_mask).reshape(
            flattened_steps, action_count
        )
        contextual_actions = self.action_entity_attention(
            flat_actions,
            entity_embeddings,
            query_padding_mask=action_padding_mask,
            key_padding_mask=entity_padding_mask,
        ).reshape(batch_size, steps, action_count, self.config.model_dim)

        query = self.policy_query(policy_context).unsqueeze(2)
        keys = self.policy_key(contextual_actions)
        dot_product = (query * keys).sum(dim=-1) / sqrt(self.config.model_dim)
        expanded_context = policy_context.unsqueeze(2).expand_as(contextual_actions)
        interaction = self.policy_interaction(
            torch.cat(
                (
                    expanded_context,
                    contextual_actions,
                    expanded_context * contextual_actions,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        policy_logits = dot_product + interaction
        policy_logits = policy_logits.masked_fill(~batch.legal_action_mask, -torch.inf)
        state_value = self.value_head(value_context).squeeze(-1)
        state_value = state_value.masked_fill(~batch.step_mask, 0.0)

        return SpireFormerOutput(
            policy_logits=policy_logits,
            state_value=state_value,
            state_context=policy_context,
        )

    @staticmethod
    def select_actions(output: SpireFormerOutput, step_mask: Tensor) -> Tensor:
        """Greedily select legal action slots; padded steps return ``-1``."""

        if output.policy_logits.shape[:2] != step_mask.shape:
            raise ValueError("step_mask must match policy_logits [B, T]")
        if step_mask.dtype is not torch.bool:
            raise TypeError("step_mask must use torch.bool")
        selected = output.policy_logits.argmax(dim=-1)
        return selected.masked_fill(~step_mask, -1)


__all__ = [
    "SpireFormer",
    "SpireFormerConfig",
    "SpireFormerOutput",
]
