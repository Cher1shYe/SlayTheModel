"""End-to-end behavioural tests for the first SpireFormer network."""

from __future__ import annotations

from dataclasses import replace

import torch

from spireformer import (
    DecisionDomain,
    SpireFormer,
    SpireFormerBatch,
    SpireFormerConfig,
    SpireFormerTargets,
    compute_spireformer_loss,
)


def _config() -> SpireFormerConfig:
    return SpireFormerConfig(
        entity_feature_dim=6,
        action_feature_dim=7,
        model_dim=16,
        set_num_heads=4,
        set_num_layers=2,
        set_num_inducing_points=3,
        temporal_num_heads=4,
        temporal_num_layers=2,
        temporal_ff_multiplier=2,
        action_num_heads=4,
        dropout=0.0,
        max_timestep=128,
    )


def _mixed_batch() -> SpireFormerBatch:
    """Return one batch containing combat, outside-combat, and padded steps."""

    generator = torch.Generator().manual_seed(20260924)
    batch_size, steps, entities, actions = 2, 3, 4, 5
    return SpireFormerBatch(
        entity_features=torch.randn(
            batch_size, steps, entities, 6, generator=generator
        ),
        entity_mask=torch.tensor(
            [
                [
                    [True, True, True, False],
                    [True, False, False, False],
                    [True, True, False, False],
                ],
                [
                    [True, True, True, True],
                    [True, True, True, False],
                    [False, False, False, False],
                ],
            ]
        ),
        legal_action_features=torch.randn(
            batch_size, steps, actions, 7, generator=generator
        ),
        legal_action_mask=torch.tensor(
            [
                [
                    [True, True, False, False, False],
                    [True, True, True, True, False],
                    [True, False, True, False, False],
                ],
                [
                    [True, True, True, False, False],
                    [False, True, False, True, True],
                    [False, False, False, False, False],
                ],
            ]
        ),
        previous_action_features=torch.randn(batch_size, steps, 7, generator=generator),
        returns_to_go=torch.randn(batch_size, steps, 1, generator=generator),
        timesteps=torch.tensor([[0, 1, 2], [19, 20, 0]]),
        domain_ids=torch.tensor(
            [
                [
                    int(DecisionDomain.COMBAT),
                    int(DecisionDomain.OUTSIDE_COMBAT),
                    int(DecisionDomain.COMBAT),
                ],
                [
                    int(DecisionDomain.OUTSIDE_COMBAT),
                    int(DecisionDomain.COMBAT),
                    int(DecisionDomain.COMBAT),
                ],
            ]
        ),
        step_mask=torch.tensor([[True, True, True], [True, True, False]]),
    )


def _targets(batch: SpireFormerBatch) -> SpireFormerTargets:
    # Every index on an active policy row points to a True action-mask entry.
    return SpireFormerTargets(
        action_indices=torch.tensor([[1, 3, 2], [2, 4, 0]]),
        value_targets=torch.tensor([[0.75, -0.25, 0.5], [0.1, -0.8, 0.0]]),
        policy_target_mask=batch.step_mask.clone(),
        value_target_mask=batch.step_mask.clone(),
    )


def _model() -> SpireFormer:
    torch.manual_seed(1729)
    return SpireFormer(_config())


def test_complete_mixed_domain_forward_loss_and_backward() -> None:
    """One graph must train across combat and outside-combat decisions."""

    batch = _mixed_batch()
    targets = _targets(batch)
    model = _model().train()

    output = model(batch)

    assert output.policy_logits.shape == (2, 3, 5)
    assert output.state_value.shape == (2, 3)
    assert output.state_context.shape == (2, 3, 16)
    assert torch.isfinite(output.policy_logits[batch.legal_action_mask]).all()
    assert torch.isneginf(output.policy_logits[~batch.legal_action_mask]).all()
    assert torch.isfinite(output.state_value).all()
    assert torch.count_nonzero(output.state_value[~batch.step_mask]) == 0
    assert torch.count_nonzero(output.state_context[~batch.step_mask]) == 0

    selected = model.select_actions(output, batch.step_mask)
    assert selected[~batch.step_mask].eq(-1).all()
    selected_is_legal = batch.legal_action_mask[batch.step_mask].gather(
        1, selected[batch.step_mask].unsqueeze(-1)
    )
    assert selected_is_legal.all()

    loss = compute_spireformer_loss(output, batch, targets)
    assert torch.isfinite(loss.total)
    assert torch.isfinite(loss.policy)
    assert torch.isfinite(loss.value)
    assert torch.isfinite(loss.entropy)
    loss.total.backward()

    for name, parameter in model.named_parameters():
        assert parameter.grad is not None
        assert torch.isfinite(parameter.grad).all(), name


def test_entity_order_is_invariant_for_the_whole_model() -> None:
    batch = _mixed_batch()
    permutation = torch.tensor([2, 0, 3, 1])
    permuted = replace(
        batch,
        entity_features=batch.entity_features[:, :, permutation],
        entity_mask=batch.entity_mask[:, :, permutation],
    )
    model = _model().eval()

    with torch.inference_mode():
        baseline = model(batch)
        changed = model(permuted)

    torch.testing.assert_close(
        changed.policy_logits, baseline.policy_logits, rtol=1e-5, atol=1e-6
    )
    torch.testing.assert_close(
        changed.state_value, baseline.state_value, rtol=1e-5, atol=1e-6
    )
    torch.testing.assert_close(
        changed.state_context, baseline.state_context, rtol=1e-5, atol=1e-6
    )


def test_action_order_is_equivariant_for_the_whole_model() -> None:
    batch = _mixed_batch()
    permutation = torch.tensor([3, 0, 4, 1, 2])
    permuted = replace(
        batch,
        legal_action_features=batch.legal_action_features[:, :, permutation],
        legal_action_mask=batch.legal_action_mask[:, :, permutation],
    )
    model = _model().eval()

    with torch.inference_mode():
        baseline = model(batch)
        changed = model(permuted)

    torch.testing.assert_close(
        changed.policy_logits,
        baseline.policy_logits[:, :, permutation],
        rtol=1e-5,
        atol=1e-6,
    )
    # Candidate actions are scored after the causal state/value stream.
    torch.testing.assert_close(changed.state_value, baseline.state_value)
    torch.testing.assert_close(changed.state_context, baseline.state_context)


def test_masked_contents_and_padded_steps_cannot_affect_real_outputs() -> None:
    batch = _mixed_batch()
    changed_entities = batch.entity_features.clone()
    changed_actions = batch.legal_action_features.clone()
    changed_previous_actions = batch.previous_action_features.clone()
    changed_returns = batch.returns_to_go.clone()
    changed_entities[~batch.entity_mask] = 10_000.0
    changed_actions[~batch.legal_action_mask] = -10_000.0
    changed_previous_actions[~batch.step_mask] = 20_000.0
    changed_returns[~batch.step_mask] = -20_000.0
    changed_batch = replace(
        batch,
        entity_features=changed_entities,
        legal_action_features=changed_actions,
        previous_action_features=changed_previous_actions,
        returns_to_go=changed_returns,
    )
    model = _model().eval()

    with torch.inference_mode():
        baseline = model(batch)
        changed = model(changed_batch)

    torch.testing.assert_close(
        changed.policy_logits[batch.legal_action_mask],
        baseline.policy_logits[batch.legal_action_mask],
        rtol=1e-5,
        atol=1e-6,
    )
    torch.testing.assert_close(changed.state_value, baseline.state_value)
    torch.testing.assert_close(changed.state_context, baseline.state_context)
    assert torch.isneginf(changed.policy_logits[~batch.legal_action_mask]).all()
    assert torch.count_nonzero(changed.state_value[~batch.step_mask]) == 0
    assert torch.count_nonzero(changed.state_context[~batch.step_mask]) == 0


def test_padding_may_use_negative_domain_and_timestep_sentinels() -> None:
    batch = _mixed_batch()
    sentinel_domains = batch.domain_ids.clone()
    sentinel_timesteps = batch.timesteps.clone()
    sentinel_domains[~batch.step_mask] = -1
    sentinel_timesteps[~batch.step_mask] = -1
    sentinel_batch = replace(
        batch,
        domain_ids=sentinel_domains,
        timesteps=sentinel_timesteps,
    )
    model = _model().eval()

    # Validation deliberately constrains active entries only; forward must
    # sanitize padding before embedding-table lookup.
    sentinel_batch.validate(6, 7)
    with torch.inference_mode():
        baseline = model(batch)
        changed = model(sentinel_batch)

    torch.testing.assert_close(changed.policy_logits, baseline.policy_logits)
    torch.testing.assert_close(changed.state_value, baseline.state_value)
    torch.testing.assert_close(changed.state_context, baseline.state_context)


def test_value_stream_does_not_read_return_to_go_in_eval_mode() -> None:
    batch = _mixed_batch()
    changed_returns = batch.returns_to_go.clone()
    changed_returns[batch.step_mask] = changed_returns[batch.step_mask] * -37.0 + 100.0
    changed_batch = replace(batch, returns_to_go=changed_returns)
    model = _model().eval()

    with torch.inference_mode():
        baseline = model(batch)
        changed = model(changed_batch)

    # The policy is return-conditioned; the separately evaluated value stream
    # deliberately receives zero RTG to avoid copying its own supervision.
    torch.testing.assert_close(
        changed.state_value, baseline.state_value, rtol=0.0, atol=0.0
    )
