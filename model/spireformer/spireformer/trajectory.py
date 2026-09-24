"""Variable-length trajectory records and a padding collator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch
from torch import Tensor

from .batch import DecisionDomain, SpireFormerBatch, SpireFormerTargets


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One observed decision and its supervised action.

    Entity and candidate-action order may be arbitrary.  ``selected_action_index``
    is local to this step's candidate list and is converted into the next step's
    previous-action feature by :func:`collate_trajectories`.
    """

    entity_features: Tensor
    legal_action_features: Tensor
    selected_action_index: int
    return_to_go: float
    timestep: int
    domain: DecisionDomain
    value_target: float | None = None
    teacher_policy: Tensor | None = None

    def validate(self, entity_feature_dim: int, action_feature_dim: int) -> None:
        if self.entity_features.ndim != 2:
            raise ValueError("step entity_features must have shape [N, F_entity]")
        if self.entity_features.shape[0] < 1:
            raise ValueError("a trajectory step must contain at least one entity")
        if self.entity_features.shape[1] != entity_feature_dim:
            raise ValueError("step entity feature width does not match the collator")
        if self.legal_action_features.ndim != 2:
            raise ValueError("step legal_action_features must have shape [A, F_action]")
        if self.legal_action_features.shape[0] < 1:
            raise ValueError("a trajectory step must contain at least one legal action")
        if self.legal_action_features.shape[1] != action_feature_dim:
            raise ValueError("step action feature width does not match the collator")
        if not 0 <= self.selected_action_index < self.legal_action_features.shape[0]:
            raise ValueError("selected_action_index is outside the legal action list")
        if self.timestep < 0:
            raise ValueError("timestep must be non-negative")
        if self.domain not in (DecisionDomain.COMBAT, DecisionDomain.OUTSIDE_COMBAT):
            raise ValueError("unsupported decision domain")
        if self.teacher_policy is not None:
            if self.teacher_policy.shape != (self.legal_action_features.shape[0],):
                raise ValueError("teacher_policy must have one entry per legal action")
            if torch.any(self.teacher_policy < 0) or not torch.isclose(
                self.teacher_policy.sum(),
                self.teacher_policy.new_tensor(1.0),
                atol=1e-5,
                rtol=1e-5,
            ):
                raise ValueError("teacher_policy must be non-negative and sum to one")


@dataclass(frozen=True, slots=True)
class Trajectory:
    steps: tuple[TrajectoryStep, ...]

    @classmethod
    def from_sequence(cls, steps: Sequence[TrajectoryStep]) -> "Trajectory":
        return cls(tuple(steps))


def collate_trajectories(
    trajectories: Sequence[Trajectory],
    *,
    entity_feature_dim: int,
    action_feature_dim: int,
) -> tuple[SpireFormerBatch, SpireFormerTargets]:
    """Pad variable histories, entity sets, and legal-action sets into one batch."""

    if not trajectories:
        raise ValueError("at least one trajectory is required")
    if any(not trajectory.steps for trajectory in trajectories):
        raise ValueError("empty trajectories are not valid training examples")

    for trajectory in trajectories:
        for step in trajectory.steps:
            step.validate(entity_feature_dim, action_feature_dim)

    prototype = trajectories[0].steps[0].entity_features
    device = prototype.device
    dtype = prototype.dtype
    for trajectory in trajectories:
        for step in trajectory.steps:
            if (
                step.entity_features.device != device
                or step.legal_action_features.device != device
            ):
                raise ValueError("all trajectory tensors must be on the same device")
            if (
                step.entity_features.dtype != dtype
                or step.legal_action_features.dtype != dtype
            ):
                raise ValueError("all trajectory features must use the same dtype")

    batch_size = len(trajectories)
    max_steps = max(len(trajectory.steps) for trajectory in trajectories)
    max_entities = max(
        step.entity_features.shape[0]
        for trajectory in trajectories
        for step in trajectory.steps
    )
    max_actions = max(
        step.legal_action_features.shape[0]
        for trajectory in trajectories
        for step in trajectory.steps
    )

    entities = torch.zeros(
        batch_size,
        max_steps,
        max_entities,
        entity_feature_dim,
        dtype=dtype,
        device=device,
    )
    entity_mask = torch.zeros(
        batch_size, max_steps, max_entities, dtype=torch.bool, device=device
    )
    actions = torch.zeros(
        batch_size,
        max_steps,
        max_actions,
        action_feature_dim,
        dtype=dtype,
        device=device,
    )
    action_mask = torch.zeros(
        batch_size, max_steps, max_actions, dtype=torch.bool, device=device
    )
    previous_actions = torch.zeros(
        batch_size,
        max_steps,
        action_feature_dim,
        dtype=dtype,
        device=device,
    )
    returns_to_go = torch.zeros(batch_size, max_steps, 1, dtype=dtype, device=device)
    timesteps = torch.zeros(batch_size, max_steps, dtype=torch.long, device=device)
    domains = torch.zeros(batch_size, max_steps, dtype=torch.long, device=device)
    step_mask = torch.zeros(batch_size, max_steps, dtype=torch.bool, device=device)
    selected_actions = torch.zeros(
        batch_size, max_steps, dtype=torch.long, device=device
    )
    value_targets = torch.zeros(batch_size, max_steps, dtype=dtype, device=device)
    policy_target_mask = torch.zeros(
        batch_size, max_steps, dtype=torch.bool, device=device
    )
    value_target_mask = torch.zeros(
        batch_size, max_steps, dtype=torch.bool, device=device
    )

    has_teacher_policy = any(
        step.teacher_policy is not None
        for trajectory in trajectories
        for step in trajectory.steps
    )
    teacher_policy = (
        torch.zeros(batch_size, max_steps, max_actions, dtype=dtype, device=device)
        if has_teacher_policy
        else None
    )

    for batch_index, trajectory in enumerate(trajectories):
        previous_action = torch.zeros(action_feature_dim, dtype=dtype, device=device)
        for step_index, step in enumerate(trajectory.steps):
            entity_count = step.entity_features.shape[0]
            action_count = step.legal_action_features.shape[0]
            entities[batch_index, step_index, :entity_count] = step.entity_features
            entity_mask[batch_index, step_index, :entity_count] = True
            actions[batch_index, step_index, :action_count] = step.legal_action_features
            action_mask[batch_index, step_index, :action_count] = True
            previous_actions[batch_index, step_index] = previous_action
            returns_to_go[batch_index, step_index, 0] = step.return_to_go
            timesteps[batch_index, step_index] = step.timestep
            domains[batch_index, step_index] = int(step.domain)
            step_mask[batch_index, step_index] = True
            selected_actions[batch_index, step_index] = step.selected_action_index
            policy_target_mask[batch_index, step_index] = True
            if step.value_target is not None:
                value_targets[batch_index, step_index] = step.value_target
                value_target_mask[batch_index, step_index] = True
            if teacher_policy is not None:
                if step.teacher_policy is None:
                    teacher_policy[
                        batch_index, step_index, step.selected_action_index
                    ] = 1.0
                else:
                    teacher_policy[batch_index, step_index, :action_count] = (
                        step.teacher_policy.to(device=device, dtype=dtype)
                    )
            previous_action = step.legal_action_features[step.selected_action_index]

    batch = SpireFormerBatch(
        entity_features=entities,
        entity_mask=entity_mask,
        legal_action_features=actions,
        legal_action_mask=action_mask,
        previous_action_features=previous_actions,
        returns_to_go=returns_to_go,
        timesteps=timesteps,
        domain_ids=domains,
        step_mask=step_mask,
    )
    targets = SpireFormerTargets(
        action_indices=selected_actions,
        value_targets=value_targets,
        teacher_policy=teacher_policy,
        policy_target_mask=policy_target_mask,
        value_target_mask=value_target_mask,
    )
    batch.validate(entity_feature_dim, action_feature_dim)
    targets.validate(batch)
    return batch, targets
