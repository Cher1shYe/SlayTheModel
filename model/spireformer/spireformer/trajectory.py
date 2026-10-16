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
    set_candidate_features: Tensor | None = None
    set_selected_mask: Tensor | None = None
    set_min_select: int | None = None
    set_max_select: int | None = None
    # The template action alone does not identify the chosen subset.  A
    # tensorizer must encode the concrete executed action for the next step.
    executed_action_features: Tensor | None = None

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
        if (
            self.executed_action_features is not None
            and self.executed_action_features.shape != (action_feature_dim,)
        ):
            raise ValueError("executed_action_features must have shape [F_action]")
        set_fields = (
            self.set_candidate_features,
            self.set_min_select,
            self.set_max_select,
        )
        if all(field is None for field in set_fields):
            if self.set_selected_mask is not None:
                raise ValueError("set target requires set-choice candidates and bounds")
            return
        if any(field is None for field in set_fields):
            raise ValueError("set-choice trajectory fields must be supplied together")
        candidates = self.set_candidate_features
        selected = self.set_selected_mask
        assert candidates is not None
        assert self.set_min_select is not None and self.set_max_select is not None
        if candidates.ndim != 2 or candidates.shape[1] != entity_feature_dim:
            raise ValueError("set_candidate_features must have shape [C, F_entity]")
        if not 0 <= self.set_min_select <= self.set_max_select <= candidates.shape[0]:
            raise ValueError("set choice bounds exceed candidate count")
        if selected is not None:
            if (
                selected.shape != (candidates.shape[0],)
                or selected.dtype is not torch.bool
            ):
                raise ValueError("set_selected_mask must be a boolean tensor [C]")
            if self.executed_action_features is None:
                raise ValueError(
                    "labeled set choice requires concrete executed_action_features"
                )
            selected_count = int(selected.sum().item())
            if not self.set_min_select <= selected_count <= self.set_max_select:
                raise ValueError("selected set cardinality violates choice bounds")


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
                or (
                    step.set_candidate_features is not None
                    and step.set_candidate_features.device != device
                )
                or (
                    step.set_selected_mask is not None
                    and step.set_selected_mask.device != device
                )
                or (
                    step.executed_action_features is not None
                    and step.executed_action_features.device != device
                )
            ):
                raise ValueError("all trajectory tensors must be on the same device")
            if (
                step.entity_features.dtype != dtype
                or step.legal_action_features.dtype != dtype
                or (
                    step.set_candidate_features is not None
                    and step.set_candidate_features.dtype != dtype
                )
                or (
                    step.executed_action_features is not None
                    and step.executed_action_features.dtype != dtype
                )
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
    has_set_choices = any(
        step.set_candidate_features is not None
        for trajectory in trajectories
        for step in trajectory.steps
    )
    max_set_candidates = max(
        (
            step.set_candidate_features.shape[0]
            for trajectory in trajectories
            for step in trajectory.steps
            if step.set_candidate_features is not None
        ),
        default=0,
    )
    # Zero-candidate, zero-select decisions still need a padded tensor slot.
    max_set_candidates = max(1, max_set_candidates)

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
    set_candidates = (
        torch.zeros(
            batch_size,
            max_steps,
            max_set_candidates,
            entity_feature_dim,
            dtype=dtype,
            device=device,
        )
        if has_set_choices
        else None
    )
    set_candidate_mask = (
        torch.zeros(
            batch_size, max_steps, max_set_candidates, dtype=torch.bool, device=device
        )
        if has_set_choices
        else None
    )
    set_selected_mask = (
        torch.zeros(
            batch_size, max_steps, max_set_candidates, dtype=torch.bool, device=device
        )
        if has_set_choices
        else None
    )
    set_min_select = (
        torch.zeros(batch_size, max_steps, dtype=torch.long, device=device)
        if has_set_choices
        else None
    )
    set_max_select = (
        torch.zeros(batch_size, max_steps, dtype=torch.long, device=device)
        if has_set_choices
        else None
    )
    set_step_mask = (
        torch.zeros(batch_size, max_steps, dtype=torch.bool, device=device)
        if has_set_choices
        else None
    )
    set_target_mask = (
        torch.zeros(batch_size, max_steps, dtype=torch.bool, device=device)
        if has_set_choices
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
            if step.set_candidate_features is not None:
                assert set_candidates is not None and set_candidate_mask is not None
                assert set_selected_mask is not None and set_min_select is not None
                assert set_max_select is not None and set_step_mask is not None
                assert (
                    step.set_min_select is not None and step.set_max_select is not None
                )
                candidate_count = step.set_candidate_features.shape[0]
                set_candidates[batch_index, step_index, :candidate_count] = (
                    step.set_candidate_features
                )
                set_candidate_mask[batch_index, step_index, :candidate_count] = True
                if step.set_selected_mask is not None:
                    set_selected_mask[batch_index, step_index, :candidate_count] = (
                        step.set_selected_mask
                    )
                    assert set_target_mask is not None
                    set_target_mask[batch_index, step_index] = True
                set_min_select[batch_index, step_index] = step.set_min_select
                set_max_select[batch_index, step_index] = step.set_max_select
                set_step_mask[batch_index, step_index] = True
            previous_action = (
                step.executed_action_features
                if step.executed_action_features is not None
                else step.legal_action_features[step.selected_action_index]
            )

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
        set_candidate_features=set_candidates,
        set_candidate_mask=set_candidate_mask,
        set_min_select=set_min_select,
        set_max_select=set_max_select,
        set_step_mask=set_step_mask,
    )
    targets = SpireFormerTargets(
        action_indices=selected_actions,
        value_targets=value_targets,
        teacher_policy=teacher_policy,
        policy_target_mask=policy_target_mask,
        value_target_mask=value_target_mask,
        set_selected_mask=set_selected_mask,
        set_target_mask=set_target_mask,
    )
    batch.validate(entity_feature_dim, action_feature_dim)
    targets.validate(batch)
    return batch, targets
