"""Shared-seed selection used between live S3 posterior updates."""
import numpy as np


def select_batch(predictions, used, order, size=5):
    """Use the current comparison's probabilities, over the full seed universe."""
    saturated = (predictions < .15).all(axis=0) | (predictions > .85).all(axis=0)
    disagreement = 1 - predictions.prod(axis=0) - (1 - predictions).prod(axis=0)
    eligible = [i for i in order if not used[i] and not saturated[i]]
    return sorted(eligible, key=lambda i: -disagreement[i])[:size]


def use_results(observations, selected, seed_indices, scores):
    """A cached game enters the likelihood once, irrespective of memberships."""
    for ci, cid in enumerate(selected):
        for si, index in enumerate(seed_indices):
            previous = observations[cid, index]
            value = scores[ci, si]
            if np.isfinite(previous) and previous != value:
                raise ValueError("conflicting outcome for the same candidate and seed")
            observations[cid, index] = value

def reveal_block(observations, parents, selected, index, outcomes, posterior, on_update):
    """Assimilate each fresh answer in candidate order before selecting another seed."""
    from rasch import fit

    for cid, outcome in zip(selected, outcomes, strict=True):
        previous = observations[cid, index]
        if np.isfinite(previous):
            if previous != outcome:
                raise ValueError("conflicting outcome for the same candidate and seed")
            continue
        if outcome not in (0, 1):
            raise ValueError("game outcome must be zero or one")
        observations[cid, index] = outcome
        posterior = fit(observations, parents)
        on_update(cid, index, posterior)
    return posterior
