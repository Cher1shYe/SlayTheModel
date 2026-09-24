"""Causal trajectory encoder used by SpireFormer.

This module intentionally depends only on PyTorch.  The original Decision
Transformer implementation uses a modified Hugging Face GPT-2; for
SpireFormer the much smaller :class:`torch.nn.TransformerEncoder` surface is
enough and avoids making model inference depend on ``transformers``.
"""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.utils.checkpoint import checkpoint


class DecisionTransformerCore(nn.Module):
    """Encode a trajectory as a causal ``(return, state, action)`` sequence.

    Parameters
    ----------
    embedding_dim:
        Width of state, action, and output embeddings.
    n_heads:
        Number of self-attention heads. ``embedding_dim`` must be divisible by
        this value.
    n_layers:
        Number of causal Transformer blocks.
    dropout:
        Dropout used by attention, feed-forward blocks, and token embeddings.
    max_timestep:
        Number of entries in the learned timestep embedding table. Valid
        timestep values are in ``[0, max_timestep)``.
    ff_multiplier:
        Feed-forward hidden width as a multiple of ``embedding_dim``.

    Notes
    -----
    ``previous_action_embeddings[:, t]`` represents :math:`a_{t-1}`, the
    action which led to :math:`s_t`.  To preserve Decision Transformer's
    ``(R_t, S_t, A_t)`` order without leaking the action being predicted, the
    module moves that value into the preceding action slot:

    ``action_slot[t - 1] = previous_action_embeddings[t]``.

    Consequently ``S_t`` can attend to :math:`a_{t-1}`.  The final action slot
    is an ignored zero placeholder.  ``previous_action_embeddings[:, 0]`` has
    no preceding slot and is intentionally unused.  When a trajectory window
    starts in the middle of an episode, this means the action immediately
    before the window is not represented; callers should include one earlier
    step if retaining that boundary action is important.
    """

    _TOKEN_TYPES = 3
    _RETURN_TOKEN = 0
    _STATE_TOKEN = 1
    _ACTION_TOKEN = 2

    def __init__(
        self,
        embedding_dim: int,
        n_heads: int,
        n_layers: int,
        *,
        dropout: float = 0.1,
        max_timestep: int = 4096,
        ff_multiplier: int = 4,
    ) -> None:
        super().__init__()

        if embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        if n_heads <= 0:
            raise ValueError("n_heads must be positive")
        if embedding_dim % n_heads != 0:
            raise ValueError("embedding_dim must be divisible by n_heads")
        if n_layers <= 0:
            raise ValueError("n_layers must be positive")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if max_timestep <= 0:
            raise ValueError("max_timestep must be positive")
        if ff_multiplier <= 0:
            raise ValueError("ff_multiplier must be positive")

        self.embedding_dim = embedding_dim
        self.max_timestep = max_timestep

        self.return_projection = nn.Linear(1, embedding_dim)
        self.timestep_embedding = nn.Embedding(max_timestep, embedding_dim)
        self.token_type_embedding = nn.Embedding(self._TOKEN_TYPES, embedding_dim)
        self.input_norm = nn.LayerNorm(embedding_dim)
        self.input_dropout = nn.Dropout(dropout)

        layer = nn.TransformerEncoderLayer(
            d_model=embedding_dim,
            nhead=n_heads,
            dim_feedforward=embedding_dim * ff_multiplier,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer,
            num_layers=n_layers,
            norm=nn.LayerNorm(embedding_dim),
            # norm_first layers cannot use PyTorch's nested-tensor fast path;
            # disabling it explicitly avoids a misleading runtime warning.
            enable_nested_tensor=False,
        )
        self.gradient_checkpointing = False

        self._reset_parameters()

    def set_gradient_checkpointing(self, enabled: bool = True) -> None:
        """Enable per-layer activation recomputation for large configurations."""

        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self.gradient_checkpointing = enabled

    def _reset_parameters(self) -> None:
        # A small embedding initialization matches common GPT-style models and
        # keeps the three additive embedding sources at a comparable scale.
        nn.init.normal_(self.timestep_embedding.weight, mean=0.0, std=0.02)
        nn.init.normal_(self.token_type_embedding.weight, mean=0.0, std=0.02)
        nn.init.xavier_uniform_(self.return_projection.weight)
        nn.init.zeros_(self.return_projection.bias)

    def forward(
        self,
        state_embeddings: Tensor,
        previous_action_embeddings: Tensor,
        returns_to_go: Tensor,
        timesteps: Tensor,
        step_mask: Tensor | None = None,
    ) -> Tensor:
        """Return the contextual state representation for every decision step.

        Parameters
        ----------
        state_embeddings:
            Float tensor with shape ``[batch, steps, embedding_dim]``.
        previous_action_embeddings:
            Float tensor with the same shape. Entry ``t`` is the action that
            led to state ``t``; see the class note for the internal shift.
        returns_to_go:
            Float tensor with shape ``[batch, steps, 1]``.
        timesteps:
            Integer tensor with shape ``[batch, steps]``.
        step_mask:
            Optional boolean tensor with shape ``[batch, steps]`` where
            ``True`` denotes a real step and ``False`` denotes padding. Unlike
            PyTorch's key-padding mask, this public mask uses ``True=valid``.

        Returns
        -------
        Tensor
            Contextual state-token representations of shape
            ``[batch, steps, embedding_dim]``. Padded steps are exactly zero.
        """

        batch_size, steps = self._validate_inputs(
            state_embeddings,
            previous_action_embeddings,
            returns_to_go,
            timesteps,
            step_mask,
        )

        if step_mask is None:
            step_mask = torch.ones(
                (batch_size, steps),
                dtype=torch.bool,
                device=state_embeddings.device,
            )

        time_embeddings = self.timestep_embedding(timesteps)
        type_embeddings = self.token_type_embedding.weight

        return_tokens = (
            self.return_projection(returns_to_go)
            + time_embeddings
            + type_embeddings[self._RETURN_TOKEN]
        )
        state_tokens = (
            state_embeddings + time_embeddings + type_embeddings[self._STATE_TOKEN]
        )

        # previous_action_embeddings[t] is a_(t-1), so place it after S_(t-1).
        # This makes it visible to S_t while keeping it causally invisible to
        # S_(t-1). The final slot is only a placeholder and is masked out.
        shifted_actions = torch.zeros_like(previous_action_embeddings)
        shifted_actions[:, :-1] = previous_action_embeddings[:, 1:]
        action_tokens = (
            shifted_actions + time_embeddings + type_embeddings[self._ACTION_TOKEN]
        )

        tokens = torch.stack(
            (return_tokens, state_tokens, action_tokens), dim=2
        ).reshape(batch_size, steps * self._TOKEN_TYPES, self.embedding_dim)
        tokens = self.input_dropout(self.input_norm(tokens))

        # Return and state slots follow step validity. An action transition is
        # valid only when both adjacent states are real. The final action slot
        # has no successor and is always padding.
        action_mask = torch.zeros_like(step_mask)
        action_mask[:, :-1] = step_mask[:, :-1] & step_mask[:, 1:]
        token_valid_mask = torch.stack(
            (step_mask, step_mask, action_mask), dim=2
        ).reshape(batch_size, steps * self._TOKEN_TYPES)

        sequence_length = tokens.shape[1]
        causal_mask = torch.triu(
            torch.ones(
                (sequence_length, sequence_length),
                dtype=torch.bool,
                device=tokens.device,
            ),
            diagonal=1,
        )
        key_padding_mask = ~token_valid_mask

        if self.gradient_checkpointing and self.training and torch.is_grad_enabled():
            encoded = tokens
            for layer in self.transformer.layers:

                def run_layer(value: Tensor, module: nn.Module = layer) -> Tensor:
                    return module(
                        value,
                        src_mask=causal_mask,
                        src_key_padding_mask=key_padding_mask,
                    )

                encoded = checkpoint(run_layer, encoded, use_reentrant=False)
            if self.transformer.norm is not None:
                encoded = self.transformer.norm(encoded)
        else:
            encoded = self.transformer(
                tokens,
                mask=causal_mask,
                src_key_padding_mask=key_padding_mask,
            )
        state_output = encoded[:, self._STATE_TOKEN :: self._TOKEN_TYPES]

        # Queries at padded positions are still evaluated by PyTorch. Clearing
        # them gives downstream policy/value heads an unambiguous contract.
        return state_output.masked_fill(~step_mask.unsqueeze(-1), 0.0)

    def _validate_inputs(
        self,
        state_embeddings: Tensor,
        previous_action_embeddings: Tensor,
        returns_to_go: Tensor,
        timesteps: Tensor,
        step_mask: Tensor | None,
    ) -> tuple[int, int]:
        if state_embeddings.ndim != 3:
            raise ValueError(
                "state_embeddings must have shape [batch, steps, embedding_dim]"
            )
        batch_size, steps, embedding_dim = state_embeddings.shape
        if batch_size == 0 or steps == 0:
            raise ValueError("batch and steps dimensions must be non-empty")
        if embedding_dim != self.embedding_dim:
            raise ValueError(
                "state_embeddings last dimension must equal embedding_dim "
                f"({self.embedding_dim}), got {embedding_dim}"
            )
        if not state_embeddings.is_floating_point():
            raise TypeError("state_embeddings must be a floating-point tensor")

        expected_embedding_shape = (batch_size, steps, self.embedding_dim)
        if previous_action_embeddings.shape != expected_embedding_shape:
            raise ValueError(
                "previous_action_embeddings must have shape "
                f"{expected_embedding_shape}, got "
                f"{tuple(previous_action_embeddings.shape)}"
            )
        if not previous_action_embeddings.is_floating_point():
            raise TypeError(
                "previous_action_embeddings must be a floating-point tensor"
            )

        expected_scalar_shape = (batch_size, steps, 1)
        if returns_to_go.shape != expected_scalar_shape:
            raise ValueError(
                f"returns_to_go must have shape {expected_scalar_shape}, "
                f"got {tuple(returns_to_go.shape)}"
            )
        if not returns_to_go.is_floating_point():
            raise TypeError("returns_to_go must be a floating-point tensor")

        expected_step_shape = (batch_size, steps)
        if timesteps.shape != expected_step_shape:
            raise ValueError(
                f"timesteps must have shape {expected_step_shape}, "
                f"got {tuple(timesteps.shape)}"
            )
        if timesteps.dtype not in {
            torch.int8,
            torch.int16,
            torch.int32,
            torch.int64,
            torch.uint8,
        }:
            raise TypeError("timesteps must be an integer tensor")

        if step_mask is not None:
            if step_mask.shape != expected_step_shape:
                raise ValueError(
                    f"step_mask must have shape {expected_step_shape}, "
                    f"got {tuple(step_mask.shape)}"
                )
            if step_mask.dtype is not torch.bool:
                raise TypeError("step_mask must be a boolean tensor")
            if not torch.all(step_mask.any(dim=1)):
                raise ValueError("every batch item must contain a valid step")

        tensors = (
            previous_action_embeddings,
            returns_to_go,
            timesteps,
            *((step_mask,) if step_mask is not None else ()),
        )
        if any(tensor.device != state_embeddings.device for tensor in tensors):
            raise ValueError("all inputs must be on the same device")

        if torch.any(timesteps < 0) or torch.any(timesteps >= self.max_timestep):
            raise ValueError(f"timesteps must be in [0, {self.max_timestep})")

        return batch_size, steps
