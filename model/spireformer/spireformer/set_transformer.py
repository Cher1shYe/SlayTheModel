"""Masked Set Transformer building blocks used by SpireFormer.

The original Set Transformer architecture is built from attention operations
that are permutation equivariant (SAB and ISAB) or permutation invariant
(PMA).  This implementation keeps those semantics while using modern,
batch-first PyTorch tensors and explicit padding masks.

Mask convention
---------------
All padding masks have shape ``[batch, items]`` and use ``True`` for padding.
This is deliberately the same convention as ``torch.nn.MultiheadAttention``.
Padded query positions are reset to zero before a module returns, so they
cannot leak learned projection biases into later layers.
"""

from __future__ import annotations

from typing import Final

import torch
from torch import Tensor, nn
from torch.utils.checkpoint import checkpoint


_SEQUENCE_RANK: Final[int] = 3


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer; got {value!r}")
    return value


def _dropout_probability(value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"dropout must be a number in [0, 1); got {value!r}")
    value = float(value)
    if not 0.0 <= value < 1.0:
        raise ValueError(f"dropout must be in [0, 1); got {value!r}")
    return value


def _validate_sequence(
    tensor: Tensor,
    *,
    name: str,
    feature_dim: int,
    require_non_empty: bool = True,
) -> tuple[int, int]:
    if not isinstance(tensor, Tensor):
        raise TypeError(f"{name} must be a torch.Tensor")
    if tensor.ndim != _SEQUENCE_RANK:
        raise ValueError(
            f"{name} must have shape [batch, items, {feature_dim}]; "
            f"got {tuple(tensor.shape)}"
        )
    batch_size, item_count, actual_dim = tensor.shape
    if actual_dim != feature_dim:
        raise ValueError(
            f"{name} feature dimension must be {feature_dim}; got {actual_dim}"
        )
    if require_non_empty and item_count == 0:
        raise ValueError(
            f"{name} must contain at least one tensor slot; represent an empty "
            "set with one padded slot"
        )
    if not tensor.is_floating_point():
        raise TypeError(f"{name} must use a floating-point dtype; got {tensor.dtype}")
    return batch_size, item_count


def _validate_padding_mask(
    mask: Tensor | None,
    *,
    name: str,
    batch_size: int,
    item_count: int,
    device: torch.device,
) -> Tensor | None:
    if mask is None:
        return None
    if not isinstance(mask, Tensor):
        raise TypeError(f"{name} must be a torch.Tensor or None")
    if mask.dtype != torch.bool:
        raise TypeError(f"{name} must have dtype torch.bool; got {mask.dtype}")
    if mask.ndim != 2 or tuple(mask.shape) != (batch_size, item_count):
        raise ValueError(
            f"{name} must have shape [{batch_size}, {item_count}]; "
            f"got {tuple(mask.shape)}"
        )
    if mask.device != device:
        raise ValueError(f"{name} must be on {device}; got {mask.device}")
    return mask


def _zero_padded_queries(value: Tensor, mask: Tensor | None) -> Tensor:
    if mask is None:
        return value
    return value.masked_fill(mask.unsqueeze(-1), 0.0)


def _autocast_enabled(device: torch.device) -> bool:
    """Handle both current and older supported PyTorch autocast APIs."""

    try:
        return torch.is_autocast_enabled(device.type)
    except TypeError:  # pragma: no cover - compatibility with older PyTorch
        if device.type == "cpu":
            return torch.is_autocast_cpu_enabled()
        return torch.is_autocast_enabled()


class MAB(nn.Module):
    """Multihead Attention Block.

    Args:
        query_dim: Feature width of the query sequence.
        key_dim: Feature width of both the key and value sequences.
        model_dim: Internal and output feature width.
        num_heads: Number of attention heads. ``model_dim`` must be divisible
            by this value.
        feed_forward_dim: Hidden width of the row-wise feed-forward network.
            Defaults to four times ``model_dim``.
        dropout: Dropout probability used by attention and residual branches.
        layer_norm: Whether to apply layer normalization after each residual.

    Inputs use shape ``[B, Q, query_dim]`` and ``[B, K, key_dim]``.  Key/value
    order does not affect the result, while query order is preserved.
    """

    def __init__(
        self,
        query_dim: int,
        key_dim: int,
        model_dim: int,
        num_heads: int,
        *,
        feed_forward_dim: int | None = None,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ) -> None:
        super().__init__()
        self.query_dim = _positive_int("query_dim", query_dim)
        self.key_dim = _positive_int("key_dim", key_dim)
        self.model_dim = _positive_int("model_dim", model_dim)
        self.num_heads = _positive_int("num_heads", num_heads)
        if self.model_dim % self.num_heads != 0:
            raise ValueError(
                "model_dim must be divisible by num_heads; "
                f"got model_dim={self.model_dim}, num_heads={self.num_heads}"
            )
        if not isinstance(layer_norm, bool):
            raise TypeError(f"layer_norm must be bool; got {layer_norm!r}")
        if feed_forward_dim is None:
            feed_forward_dim = self.model_dim * 4
        self.feed_forward_dim = _positive_int("feed_forward_dim", feed_forward_dim)
        dropout = _dropout_probability(dropout)

        self.query_projection = nn.Linear(self.query_dim, self.model_dim)
        self.key_projection = nn.Linear(self.key_dim, self.model_dim)
        self.value_projection = nn.Linear(self.key_dim, self.model_dim)
        self.attention = nn.MultiheadAttention(
            embed_dim=self.model_dim,
            num_heads=self.num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.attention_dropout = nn.Dropout(dropout)
        self.feed_forward = nn.Sequential(
            nn.Linear(self.model_dim, self.feed_forward_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(self.feed_forward_dim, self.model_dim),
        )
        self.feed_forward_dropout = nn.Dropout(dropout)
        self.attention_norm = (
            nn.LayerNorm(self.model_dim) if layer_norm else nn.Identity()
        )
        self.feed_forward_norm = (
            nn.LayerNorm(self.model_dim) if layer_norm else nn.Identity()
        )

    def forward(
        self,
        query: Tensor,
        key: Tensor,
        value: Tensor | None = None,
        *,
        query_padding_mask: Tensor | None = None,
        key_padding_mask: Tensor | None = None,
    ) -> Tensor:
        """Apply cross-attention and return ``[B, Q, model_dim]``.

        ``value`` defaults to ``key``.  A completely padded key set is valid
        as long as it is represented by at least one padded slot.  In that
        case the attention update is zero and only the query residual passes
        through the block; this avoids the NaNs produced by an all-masked
        softmax.
        """

        if value is None:
            value = key
        query_batch, query_count = _validate_sequence(
            query, name="query", feature_dim=self.query_dim
        )
        key_batch, key_count = _validate_sequence(
            key, name="key", feature_dim=self.key_dim
        )
        value_batch, value_count = _validate_sequence(
            value, name="value", feature_dim=self.key_dim
        )
        if query_batch != key_batch or key_batch != value_batch:
            raise ValueError(
                "query, key, and value batch sizes must match; got "
                f"{query_batch}, {key_batch}, and {value_batch}"
            )
        if key_count != value_count:
            raise ValueError(
                "key and value item counts must match; got "
                f"{key_count} and {value_count}"
            )
        if query.device != key.device or key.device != value.device:
            raise ValueError(
                "query, key, and value must be on the same device; got "
                f"{query.device}, {key.device}, and {value.device}"
            )
        if (
            query.dtype != key.dtype or key.dtype != value.dtype
        ) and not _autocast_enabled(query.device):
            raise TypeError(
                "query, key, and value must have the same dtype; got "
                f"{query.dtype}, {key.dtype}, and {value.dtype}"
            )

        query_padding_mask = _validate_padding_mask(
            query_padding_mask,
            name="query_padding_mask",
            batch_size=query_batch,
            item_count=query_count,
            device=query.device,
        )
        key_padding_mask = _validate_padding_mask(
            key_padding_mask,
            name="key_padding_mask",
            batch_size=key_batch,
            item_count=key_count,
            device=key.device,
        )

        projected_query = self.query_projection(query)
        projected_key = self.key_projection(key)
        projected_value = self.value_projection(value)

        # MultiheadAttention produces NaNs if every key in a row is masked.
        # Temporarily expose one slot, then discard that row's attention
        # update.  This gives empty sets deterministic, finite behaviour.
        fully_masked_keys: Tensor | None = None
        safe_key_padding_mask = key_padding_mask
        if key_padding_mask is not None:
            fully_masked_keys = key_padding_mask.all(dim=1)
            safe_key_padding_mask = key_padding_mask.clone()
            safe_key_padding_mask[:, 0] &= ~fully_masked_keys

        attention_update, _ = self.attention(
            projected_query,
            projected_key,
            projected_value,
            key_padding_mask=safe_key_padding_mask,
            need_weights=False,
        )
        if fully_masked_keys is not None:
            attention_update = attention_update.masked_fill(
                fully_masked_keys[:, None, None], 0.0
            )

        hidden = self.attention_norm(
            projected_query + self.attention_dropout(attention_update)
        )
        hidden = self.feed_forward_norm(
            hidden + self.feed_forward_dropout(self.feed_forward(hidden))
        )
        return _zero_padded_queries(hidden, query_padding_mask)


class SAB(nn.Module):
    """Self-Attention Block with permutation-equivariant output."""

    def __init__(
        self,
        input_dim: int,
        model_dim: int,
        num_heads: int,
        *,
        feed_forward_dim: int | None = None,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ) -> None:
        super().__init__()
        self.input_dim = _positive_int("input_dim", input_dim)
        self.model_dim = _positive_int("model_dim", model_dim)
        self.mab = MAB(
            self.input_dim,
            self.input_dim,
            self.model_dim,
            num_heads,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
            layer_norm=layer_norm,
        )

    def forward(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        return self.mab(
            x,
            x,
            query_padding_mask=padding_mask,
            key_padding_mask=padding_mask,
        )


class ISAB(nn.Module):
    """Induced Self-Attention Block.

    ISAB reduces self-attention cost from quadratic in set size to
    ``O(items * num_inducing_points)`` while remaining permutation
    equivariant.
    """

    def __init__(
        self,
        input_dim: int,
        model_dim: int,
        num_heads: int,
        num_inducing_points: int,
        *,
        feed_forward_dim: int | None = None,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ) -> None:
        super().__init__()
        self.input_dim = _positive_int("input_dim", input_dim)
        self.model_dim = _positive_int("model_dim", model_dim)
        self.num_inducing_points = _positive_int(
            "num_inducing_points", num_inducing_points
        )
        self.inducing_points = nn.Parameter(
            torch.empty(1, self.num_inducing_points, self.model_dim)
        )
        nn.init.xavier_uniform_(self.inducing_points)

        self.inducing_attention = MAB(
            self.model_dim,
            self.input_dim,
            self.model_dim,
            num_heads,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
            layer_norm=layer_norm,
        )
        self.output_attention = MAB(
            self.input_dim,
            self.model_dim,
            self.model_dim,
            num_heads,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
            layer_norm=layer_norm,
        )

    def forward(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        batch_size, _ = _validate_sequence(x, name="x", feature_dim=self.input_dim)
        padding_mask = _validate_padding_mask(
            padding_mask,
            name="padding_mask",
            batch_size=batch_size,
            item_count=x.shape[1],
            device=x.device,
        )
        inducing_points = self.inducing_points.expand(batch_size, -1, -1)
        induced = self.inducing_attention(
            inducing_points,
            x,
            key_padding_mask=padding_mask,
        )
        return self.output_attention(
            x,
            induced,
            query_padding_mask=padding_mask,
        )


class PMA(nn.Module):
    """Pooling by Multihead Attention with permutation-invariant output."""

    def __init__(
        self,
        input_dim: int,
        model_dim: int,
        num_heads: int,
        num_seeds: int = 1,
        *,
        feed_forward_dim: int | None = None,
        dropout: float = 0.0,
        layer_norm: bool = True,
    ) -> None:
        super().__init__()
        self.input_dim = _positive_int("input_dim", input_dim)
        self.model_dim = _positive_int("model_dim", model_dim)
        self.num_seeds = _positive_int("num_seeds", num_seeds)
        self.seed_vectors = nn.Parameter(torch.empty(1, self.num_seeds, self.model_dim))
        nn.init.xavier_uniform_(self.seed_vectors)
        self.mab = MAB(
            self.model_dim,
            self.input_dim,
            self.model_dim,
            num_heads,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
            layer_norm=layer_norm,
        )

    def forward(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        batch_size, item_count = _validate_sequence(
            x, name="x", feature_dim=self.input_dim
        )
        padding_mask = _validate_padding_mask(
            padding_mask,
            name="padding_mask",
            batch_size=batch_size,
            item_count=item_count,
            device=x.device,
        )
        seed_vectors = self.seed_vectors.expand(batch_size, -1, -1)
        return self.mab(
            seed_vectors,
            x,
            key_padding_mask=padding_mask,
        )


class SetEncoder(nn.Module):
    """Stacked set encoder plus attention pooling.

    By default the encoder uses ISAB layers.  Pass
    ``num_inducing_points=None`` to use full SAB layers instead.

    ``encode_entities`` returns permutation-equivariant entity features with
    shape ``[B, N, embedding_dim]``.  ``forward`` pools those features into a
    permutation-invariant summary with shape
    ``[B, num_seeds, embedding_dim]``.
    SpireFormer uses both views: entity features contextualize candidate
    actions, while the pooled summary becomes the temporal state token.
    """

    def __init__(
        self,
        input_dim: int,
        embedding_dim: int,
        num_heads: int,
        num_layers: int = 2,
        num_inducing_points: int | None = 16,
        num_seeds: int = 1,
        dropout: float = 0.0,
        layer_norm: bool = True,
        *,
        feed_forward_dim: int | None = None,
    ) -> None:
        super().__init__()
        self.input_dim = _positive_int("input_dim", input_dim)
        self.embedding_dim = _positive_int("embedding_dim", embedding_dim)
        # Lower-level attention literature usually calls this width
        # ``model_dim``.  Expose both names while keeping the public encoder
        # constructor aligned with the SpireFormer configuration.
        self.model_dim = self.embedding_dim
        self.num_heads = _positive_int("num_heads", num_heads)
        self.num_layers = _positive_int("num_layers", num_layers)
        self.num_seeds = _positive_int("num_seeds", num_seeds)
        if num_inducing_points is not None:
            num_inducing_points = _positive_int(
                "num_inducing_points", num_inducing_points
            )
        self.num_inducing_points = num_inducing_points

        layers: list[nn.Module] = []
        layer_input_dim = self.input_dim
        for _ in range(self.num_layers):
            layer: nn.Module
            if self.num_inducing_points is None:
                layer = SAB(
                    layer_input_dim,
                    self.model_dim,
                    self.num_heads,
                    feed_forward_dim=feed_forward_dim,
                    dropout=dropout,
                    layer_norm=layer_norm,
                )
            else:
                layer = ISAB(
                    layer_input_dim,
                    self.model_dim,
                    self.num_heads,
                    self.num_inducing_points,
                    feed_forward_dim=feed_forward_dim,
                    dropout=dropout,
                    layer_norm=layer_norm,
                )
            layers.append(layer)
            layer_input_dim = self.model_dim
        self.layers = nn.ModuleList(layers)
        self.pooling = PMA(
            self.model_dim,
            self.model_dim,
            self.num_heads,
            self.num_seeds,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
            layer_norm=layer_norm,
        )
        self.gradient_checkpointing = False

    def set_gradient_checkpointing(self, enabled: bool = True) -> None:
        """Trade recomputation for activation memory during training."""

        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self.gradient_checkpointing = enabled

    def encode_entities(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        """Return contextual entity features of shape ``[B, N, D]``."""

        return self._encode_entities(x, padding_mask)

    def _encode_entities(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        _validate_sequence(x, name="x", feature_dim=self.input_dim)
        hidden = x
        for layer in self.layers:
            if (
                self.gradient_checkpointing
                and self.training
                and torch.is_grad_enabled()
            ):
                if padding_mask is None:
                    hidden = checkpoint(layer, hidden, use_reentrant=False)
                else:
                    hidden = checkpoint(
                        layer,
                        hidden,
                        padding_mask,
                        use_reentrant=False,
                    )
            else:
                hidden = layer(hidden, padding_mask)
        return hidden

    def pool_entities(
        self, entities: Tensor, padding_mask: Tensor | None = None
    ) -> Tensor:
        """Pool pre-encoded entities into ``[B, num_seeds, D]``."""

        return self.pooling(entities, padding_mask)

    def forward(self, x: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        _, pooled = self.forward_with_entities(x, padding_mask)
        return pooled

    def forward_with_entities(
        self, x: Tensor, padding_mask: Tensor | None = None
    ) -> tuple[Tensor, Tensor]:
        """Encode once and return ``(entities, pooled_summary)``.

        This is the efficient entry point for SpireFormer, which needs both
        views of the same set.  It avoids evaluating the ISAB/SAB stack twice.
        """

        entities = self._encode_entities(x, padding_mask)
        pooled = self.pool_entities(entities, padding_mask)
        return entities, pooled


__all__ = ["ISAB", "MAB", "PMA", "SAB", "SetEncoder"]
