"""Tensor-level input and target contracts for SpireFormer.

The game adapter remains responsible for converting stable protocol objects into
dense features.  Keeping that conversion outside the neural network lets the
same model serve live play, recorded trajectories, and a future headless runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import torch
from torch import Tensor


class DecisionDomain(IntEnum):
    """Decision families that share the SpireFormer backbone."""

    COMBAT = 0
    OUTSIDE_COMBAT = 1


@dataclass(frozen=True, slots=True)
class SpireFormerBatch:
    """A padded batch of whole-run decision histories.

    Public masks use ``True`` for real data.  This is intentionally the opposite
    of PyTorch's ``key_padding_mask`` convention, because it makes serialized
    training records and assertions easier to read.

    Shapes:
        entity_features: ``[B, T, N, entity_feature_dim]``
        entity_mask: ``[B, T, N]``
        legal_action_features: ``[B, T, A, action_feature_dim]``
        legal_action_mask: ``[B, T, A]``
        previous_action_features: ``[B, T, action_feature_dim]``
        returns_to_go: ``[B, T, 1]``
        timesteps, domain_ids, step_mask: ``[B, T]``

    ``previous_action_features[:, t]`` describes the action selected at
    ``t - 1``; the first step uses the all-zero begin-of-run vector.
    """

    entity_features: Tensor
    entity_mask: Tensor
    legal_action_features: Tensor
    legal_action_mask: Tensor
    previous_action_features: Tensor
    returns_to_go: Tensor
    timesteps: Tensor
    domain_ids: Tensor
    step_mask: Tensor

    @property
    def batch_size(self) -> int:
        return self.entity_features.shape[0]

    @property
    def sequence_length(self) -> int:
        return self.entity_features.shape[1]

    def to(
        self,
        device: torch.device | str,
        *,
        dtype: torch.dtype | None = None,
        non_blocking: bool = False,
    ) -> "SpireFormerBatch":
        """Move a batch without corrupting boolean masks or integer IDs.

        ``dtype`` applies only to floating-point tensors.  This is important
        for BF16 inference: calling ``Tensor.to(dtype=...)`` indiscriminately
        would turn action indices and masks into floating-point values.
        """

        if dtype is not None and not torch.empty((), dtype=dtype).is_floating_point():
            raise TypeError("batch dtype must be a floating-point torch.dtype")

        def move_float(tensor: Tensor) -> Tensor:
            return tensor.to(
                device=device,
                dtype=dtype or tensor.dtype,
                non_blocking=non_blocking,
            )

        def move_discrete(tensor: Tensor) -> Tensor:
            return tensor.to(device=device, non_blocking=non_blocking)

        return SpireFormerBatch(
            entity_features=move_float(self.entity_features),
            entity_mask=move_discrete(self.entity_mask),
            legal_action_features=move_float(self.legal_action_features),
            legal_action_mask=move_discrete(self.legal_action_mask),
            previous_action_features=move_float(self.previous_action_features),
            returns_to_go=move_float(self.returns_to_go),
            timesteps=move_discrete(self.timesteps),
            domain_ids=move_discrete(self.domain_ids),
            step_mask=move_discrete(self.step_mask),
        )

    def validate(self, entity_feature_dim: int, action_feature_dim: int) -> None:
        """Raise a useful error before an invalid batch reaches attention code."""

        if self.entity_features.ndim != 4:
            raise ValueError("entity_features must have shape [B, T, N, F_entity]")
        batch_size, sequence_length, entity_count, actual_entity_dim = (
            self.entity_features.shape
        )
        if actual_entity_dim != entity_feature_dim:
            raise ValueError(
                f"expected entity feature width {entity_feature_dim}, "
                f"got {actual_entity_dim}"
            )
        if entity_count < 1:
            raise ValueError("the padded entity dimension N must be at least one")

        if self.legal_action_features.ndim != 4:
            raise ValueError(
                "legal_action_features must have shape [B, T, A, F_action]"
            )
        action_shape = self.legal_action_features.shape
        if action_shape[:2] != (batch_size, sequence_length):
            raise ValueError("entity and action tensors must share [B, T]")
        if action_shape[2] < 1:
            raise ValueError("the padded action dimension A must be at least one")
        if action_shape[3] != action_feature_dim:
            raise ValueError(
                f"expected action feature width {action_feature_dim}, "
                f"got {action_shape[3]}"
            )

        expected_step_shape = (batch_size, sequence_length)
        expected_entity_mask_shape = (*expected_step_shape, entity_count)
        expected_action_mask_shape = (*expected_step_shape, action_shape[2])
        expected_previous_shape = (*expected_step_shape, action_feature_dim)
        expected_return_shape = (*expected_step_shape, 1)

        shape_checks = (
            ("entity_mask", self.entity_mask.shape, expected_entity_mask_shape),
            (
                "legal_action_mask",
                self.legal_action_mask.shape,
                expected_action_mask_shape,
            ),
            (
                "previous_action_features",
                self.previous_action_features.shape,
                expected_previous_shape,
            ),
            ("returns_to_go", self.returns_to_go.shape, expected_return_shape),
            ("timesteps", self.timesteps.shape, expected_step_shape),
            ("domain_ids", self.domain_ids.shape, expected_step_shape),
            ("step_mask", self.step_mask.shape, expected_step_shape),
        )
        for name, actual, expected in shape_checks:
            if actual != expected:
                raise ValueError(f"{name} must have shape {expected}, got {actual}")

        bool_tensors = (
            ("entity_mask", self.entity_mask),
            ("legal_action_mask", self.legal_action_mask),
            ("step_mask", self.step_mask),
        )
        for name, tensor in bool_tensors:
            if tensor.dtype is not torch.bool:
                raise TypeError(f"{name} must use torch.bool")
        if self.timesteps.dtype not in (torch.int32, torch.int64):
            raise TypeError("timesteps must use an integer dtype")
        if self.domain_ids.dtype not in (torch.int32, torch.int64):
            raise TypeError("domain_ids must use an integer dtype")

        all_tensors = (
            self.entity_features,
            self.entity_mask,
            self.legal_action_features,
            self.legal_action_mask,
            self.previous_action_features,
            self.returns_to_go,
            self.timesteps,
            self.domain_ids,
            self.step_mask,
        )
        reference_device = self.entity_features.device
        if any(tensor.device != reference_device for tensor in all_tensors):
            raise ValueError("all batch tensors must be on the same device")

        active_steps = self.step_mask
        if torch.any(active_steps & ~self.entity_mask.any(dim=-1)):
            raise ValueError("every active step must contain at least one entity")
        if torch.any(active_steps & ~self.legal_action_mask.any(dim=-1)):
            raise ValueError("every active step must contain at least one legal action")
        if torch.any(active_steps & (self.timesteps < 0)):
            raise ValueError("active timesteps must be non-negative")

        active_domains = self.domain_ids[active_steps]
        if active_domains.numel() and torch.any(
            (active_domains < int(DecisionDomain.COMBAT))
            | (active_domains > int(DecisionDomain.OUTSIDE_COMBAT))
        ):
            raise ValueError("domain_ids must be COMBAT(0) or OUTSIDE_COMBAT(1)")

        floating_tensors = (
            ("entity_features", self.entity_features),
            ("legal_action_features", self.legal_action_features),
            ("previous_action_features", self.previous_action_features),
            ("returns_to_go", self.returns_to_go),
        )
        for name, tensor in floating_tensors:
            if not tensor.is_floating_point():
                raise TypeError(f"{name} must use a floating-point dtype")
            if not torch.isfinite(tensor).all():
                raise ValueError(f"{name} contains NaN or infinity")
        reference_dtype = self.entity_features.dtype
        if any(tensor.dtype != reference_dtype for _, tensor in floating_tensors):
            raise TypeError("all floating-point batch tensors must use the same dtype")


@dataclass(frozen=True, slots=True)
class SpireFormerTargets:
    """Supervision aligned to a :class:`SpireFormerBatch`."""

    action_indices: Tensor
    value_targets: Tensor
    teacher_policy: Tensor | None = None
    policy_target_mask: Tensor | None = None
    value_target_mask: Tensor | None = None

    def to(
        self,
        device: torch.device | str,
        *,
        dtype: torch.dtype | None = None,
        non_blocking: bool = False,
    ) -> "SpireFormerTargets":
        """Move supervision while preserving index and mask dtypes."""

        if dtype is not None and not torch.empty((), dtype=dtype).is_floating_point():
            raise TypeError("target dtype must be a floating-point torch.dtype")

        def move_float(tensor: Tensor) -> Tensor:
            return tensor.to(
                device=device,
                dtype=dtype or tensor.dtype,
                non_blocking=non_blocking,
            )

        def move_optional_float(tensor: Tensor | None) -> Tensor | None:
            return None if tensor is None else move_float(tensor)

        def move_optional_discrete(tensor: Tensor | None) -> Tensor | None:
            if tensor is None:
                return None
            return tensor.to(device=device, non_blocking=non_blocking)

        return SpireFormerTargets(
            action_indices=self.action_indices.to(
                device=device, non_blocking=non_blocking
            ),
            value_targets=move_float(self.value_targets),
            teacher_policy=move_optional_float(self.teacher_policy),
            policy_target_mask=move_optional_discrete(self.policy_target_mask),
            value_target_mask=move_optional_discrete(self.value_target_mask),
        )

    def validate(self, batch: SpireFormerBatch) -> None:
        expected_step_shape = (batch.batch_size, batch.sequence_length)
        if self.action_indices.shape != expected_step_shape:
            raise ValueError(
                f"action_indices must have shape {expected_step_shape}, "
                f"got {self.action_indices.shape}"
            )
        if self.action_indices.dtype not in (torch.int32, torch.int64):
            raise TypeError("action_indices must use an integer dtype")
        if self.action_indices.device != batch.entity_features.device:
            raise ValueError("target tensors must be on the same device as the batch")
        if self.value_targets.shape not in (
            expected_step_shape,
            (*expected_step_shape, 1),
        ):
            raise ValueError("value_targets must have shape [B, T] or [B, T, 1]")
        if not self.value_targets.is_floating_point():
            raise TypeError("value_targets must use a floating-point dtype")
        if self.value_targets.device != batch.entity_features.device:
            raise ValueError("target tensors must be on the same device as the batch")

        for name, target_mask in (
            ("policy_target_mask", self.policy_target_mask),
            ("value_target_mask", self.value_target_mask),
        ):
            if target_mask is None:
                continue
            if target_mask.shape != expected_step_shape:
                raise ValueError(f"{name} must have shape {expected_step_shape}")
            if target_mask.dtype is not torch.bool:
                raise TypeError(f"{name} must use torch.bool")
            if target_mask.device != batch.entity_features.device:
                raise ValueError(f"{name} must be on the same device as the batch")
            if torch.any(target_mask & ~batch.step_mask):
                raise ValueError(f"{name} cannot enable a padded step")

        active = batch.step_mask
        policy_active = (
            active
            if self.policy_target_mask is None
            else active & self.policy_target_mask
        )
        value_active = (
            active
            if self.value_target_mask is None
            else active & self.value_target_mask
        )
        if value_active.any():
            flat_value_targets = (
                self.value_targets.squeeze(-1)
                if self.value_targets.ndim == 3
                else self.value_targets
            )
            if not torch.isfinite(flat_value_targets[value_active]).all():
                raise ValueError("an active value target contains NaN or infinity")
        active_indices = self.action_indices[policy_active]
        action_count = batch.legal_action_features.shape[2]
        if active_indices.numel() and torch.any(
            (active_indices < 0) | (active_indices >= action_count)
        ):
            raise ValueError(
                "an active action target is outside the padded action range"
            )
        if active_indices.numel():
            chosen_is_legal = batch.legal_action_mask[policy_active].gather(
                1, active_indices.to(torch.int64).unsqueeze(-1)
            )
            if not chosen_is_legal.all():
                raise ValueError("an active action target points to an illegal action")

        if self.teacher_policy is not None:
            expected_policy_shape = batch.legal_action_mask.shape
            if self.teacher_policy.shape != expected_policy_shape:
                raise ValueError(
                    f"teacher_policy must have shape {expected_policy_shape}, "
                    f"got {self.teacher_policy.shape}"
                )
            if not self.teacher_policy.is_floating_point():
                raise TypeError("teacher_policy must use a floating-point dtype")
            if self.teacher_policy.device != batch.entity_features.device:
                raise ValueError("teacher_policy must be on the batch device")
            if not torch.isfinite(self.teacher_policy).all():
                raise ValueError("teacher_policy contains NaN or infinity")
            if torch.any(self.teacher_policy < 0):
                raise ValueError("teacher_policy cannot contain negative mass")
            if torch.any(
                self.teacher_policy.masked_select(~batch.legal_action_mask) != 0
            ):
                raise ValueError("teacher_policy assigns mass to an illegal action")
            active_rows = self.teacher_policy[policy_active]
            if active_rows.numel() and not torch.allclose(
                active_rows.sum(dim=-1),
                torch.ones_like(active_rows.sum(dim=-1)),
                atol=1e-5,
                rtol=1e-5,
            ):
                raise ValueError("each active teacher_policy row must sum to one")
