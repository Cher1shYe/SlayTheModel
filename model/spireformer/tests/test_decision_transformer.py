"""Tests for SpireFormer's dependency-free Decision Transformer core."""

from __future__ import annotations

import pytest
import torch

from spireformer.decision_transformer import DecisionTransformerCore


def _model() -> DecisionTransformerCore:
    torch.manual_seed(17)
    model = DecisionTransformerCore(
        embedding_dim=16,
        n_heads=4,
        n_layers=2,
        dropout=0.0,
        max_timestep=128,
        ff_multiplier=2,
    )
    return model.eval()


def _inputs(batch: int = 2, steps: int = 6):
    torch.manual_seed(23)
    states = torch.randn(batch, steps, 16)
    previous_actions = torch.randn(batch, steps, 16)
    returns_to_go = torch.randn(batch, steps, 1)
    timesteps = torch.arange(steps).expand(batch, -1).clone()
    return states, previous_actions, returns_to_go, timesteps


def test_returns_one_contextual_representation_per_step() -> None:
    model = _model()
    inputs = _inputs(batch=3, steps=5)

    with torch.no_grad():
        output = model(*inputs)

    assert output.shape == (3, 5, 16)
    assert torch.isfinite(output).all()


def test_state_representation_is_causal() -> None:
    """Changing future R/S/A tokens must not alter earlier state outputs."""

    model = _model()
    states, actions, returns, timesteps = _inputs(batch=1, steps=6)

    with torch.no_grad():
        baseline = model(states, actions, returns, timesteps)

    changed_states = states.clone()
    changed_actions = actions.clone()
    changed_returns = returns.clone()
    changed_timesteps = timesteps.clone()
    changed_states[:, 4:] += 100.0
    changed_actions[:, 4:] -= 100.0
    changed_returns[:, 4:] *= -20.0
    changed_timesteps[:, 4:] += 40

    with torch.no_grad():
        changed = model(
            changed_states,
            changed_actions,
            changed_returns,
            changed_timesteps,
        )

    # Outputs through S_3 cannot attend to any token from step 4 onward.
    torch.testing.assert_close(baseline[:, :4], changed[:, :4], rtol=0, atol=1e-6)


def test_previous_action_is_shifted_without_current_action_leakage() -> None:
    """a_(t-1) affects S_t, but the action after S_t cannot affect S_t."""

    model = _model()
    states, actions, returns, timesteps = _inputs(batch=1, steps=5)

    with torch.no_grad():
        baseline = model(states, actions, returns, timesteps)

    changed_actions = actions.clone()
    # previous_actions[3] is a_2. Internally it occupies A_2: after S_2 and
    # before S_3. It therefore must not affect S_2 but should affect S_3.
    changed_actions[:, 3, 0] += 50.0
    with torch.no_grad():
        changed = model(states, changed_actions, returns, timesteps)

    torch.testing.assert_close(baseline[:, :3], changed[:, :3], rtol=0, atol=1e-6)
    assert not torch.allclose(baseline[:, 3], changed[:, 3])

    # There is no preceding A slot for the action before a truncated window's
    # first state. The documented v0.1 boundary behavior deliberately drops it.
    first_action_changed = actions.clone()
    first_action_changed[:, 0, 0] -= 50.0
    with torch.no_grad():
        first_action_output = model(
            states,
            first_action_changed,
            returns,
            timesteps,
        )
    torch.testing.assert_close(baseline, first_action_output, rtol=0, atol=1e-6)


def test_padding_is_ignored_and_padded_outputs_are_zero() -> None:
    model = _model()
    states, actions, returns, timesteps = _inputs(batch=2, steps=6)
    step_mask = torch.tensor(
        [
            [True, True, True, True, False, False],
            [True, True, False, False, False, False],
        ]
    )

    with torch.no_grad():
        baseline = model(states, actions, returns, timesteps, step_mask)

    changed_states = states.clone()
    changed_actions = actions.clone()
    changed_returns = returns.clone()
    changed_states[~step_mask] += 1_000.0
    changed_actions[~step_mask] -= 1_000.0
    changed_returns[~step_mask] *= -1_000.0

    with torch.no_grad():
        changed = model(
            changed_states,
            changed_actions,
            changed_returns,
            timesteps,
            step_mask,
        )

    torch.testing.assert_close(baseline, changed, rtol=0, atol=1e-6)
    assert torch.count_nonzero(baseline[~step_mask]) == 0


@pytest.mark.parametrize(
    ("argument", "replacement", "message"),
    [
        ("state", torch.randn(2, 6, 15), "state_embeddings last dimension"),
        ("action", torch.randn(2, 5, 16), "previous_action_embeddings"),
        ("return", torch.randn(2, 6), "returns_to_go"),
        ("time", torch.zeros(2, 6, 1, dtype=torch.long), "timesteps"),
        ("mask", torch.ones(2, 6, dtype=torch.long), "step_mask"),
    ],
)
def test_rejects_invalid_shapes_and_mask_dtype(
    argument: str,
    replacement: torch.Tensor,
    message: str,
) -> None:
    model = _model()
    states, actions, returns, timesteps = _inputs()
    values = {
        "state": states,
        "action": actions,
        "return": returns,
        "time": timesteps,
        "mask": torch.ones(2, 6, dtype=torch.bool),
    }
    values[argument] = replacement

    with pytest.raises((TypeError, ValueError), match=message):
        model(
            values["state"],
            values["action"],
            values["return"],
            values["time"],
            values["mask"],
        )


def test_rejects_out_of_range_timesteps_and_empty_sequences() -> None:
    model = _model()
    states, actions, returns, timesteps = _inputs(batch=1, steps=3)
    timesteps[:, -1] = 128

    with pytest.raises(ValueError, match="timesteps must be in"):
        model(states, actions, returns, timesteps)

    with pytest.raises(ValueError, match="batch and steps"):
        model(
            torch.empty(1, 0, 16),
            torch.empty(1, 0, 16),
            torch.empty(1, 0, 1),
            torch.empty(1, 0, dtype=torch.long),
        )
