"""Lineage-aware Rasch MAP and Laplace predictive means, following aflow S3."""
from dataclasses import dataclass

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.special import expit


@dataclass
class Fit:
    mean: np.ndarray
    cov: np.ndarray
    pred: np.ndarray


def fit(outcomes, parents, calibration=None):
    """outcomes[c,s] is 0/1, or NaN for an unobserved/already assimilated cell.
    The baseline has fixed strength zero. Vector order: seed difficulties,
    followed by non-baseline strengths (append-only when adding children).
    """
    m, q = outcomes.shape
    if len(parents) != m or parents[0] != -1 or not q:
        raise ValueError("invalid lineage or empty seed panel")
    obs_c, obs_s = np.where(np.isfinite(outcomes))
    y = outcomes[obs_c, obs_s]
    d = q + m - 1
    center = np.zeros(d)
    precision = np.zeros((d, d))
    if calibration is None:
        precision[np.arange(q), np.arange(q)] = 1 / 2.25
        first_child = 1
    else:
        mean, cov = calibration
        size = len(mean)
        center[:size] = mean
        precision[:size, :size] = cho_solve(cho_factor(cov), np.eye(size))
        first_child = size - q + 1
    # Add the parent-to-child Gaussian factors. Center each new child at its
    # parent's prior mean, so the prior remains centered after expansion.
    for c in range(first_child, m):
        p = parents[c]
        if not 0 <= p < c:
            raise ValueError("parent must precede child")
        a, b = q + c - 1, q + p - 1
        precision[a, a] += 1 / 2.25
        if p:
            center[a] = center[b]
            precision[b, b] += 1 / 2.25
            precision[a, b] -= 1 / 2.25
            precision[b, a] -= 1 / 2.25

    def objective(x):
        eta = np.r_[0., x[q:]][obs_c] - x[obs_s]
        resid = expit(eta) - y
        dx = x - center
        g = precision @ dx
        loss = .5 * dx @ g + (np.logaddexp(0, eta) - y * eta).sum()
        g[:q] -= np.bincount(obs_s, weights=resid, minlength=q)
        g[q:] += np.bincount(obs_c, weights=resid, minlength=m)[1:]
        return loss, g

    opt = minimize(objective, center, jac=True, method="L-BFGS-B",
                   options=dict(ftol=1e-14, gtol=1e-8, maxiter=1500))
    if np.max(np.abs(opt.jac)) > 1e-4 or not np.isfinite(opt.fun):
        raise RuntimeError(f"Rasch fit failed: {opt.message}")
    eta = np.r_[0., opt.x[q:]][:, None] - opt.x[:q]
    p = expit(eta[obs_c, obs_s])
    w = p * (1 - p)
    h = precision.copy()
    np.add.at(h, (obs_s, obs_s), w)
    nonroot = obs_c > 0
    a, b, v = q + obs_c[nonroot] - 1, obs_s[nonroot], w[nonroot]
    for row, col, val in [(a, a, v), (a, b, -v), (b, a, -v)]:
        np.add.at(h, (row, col), val)
    cov = cho_solve(cho_factor(h), np.eye(d))
    var = np.broadcast_to(cov.diagonal()[:q], (m, q)).copy()
    var[1:] += cov.diagonal()[q:, None] - 2 * cov[q:, :q]
    # Only univariate marginal predictions are needed for these rankings.
    nodes, weights = np.polynomial.hermite.hermgauss(20)
    sd = np.sqrt(2 * np.maximum(var, 0))
    pred = sum(w * expit(eta + t * sd) for t, w in zip(nodes, weights)) / np.sqrt(np.pi)
    return Fit(opt.x, cov, pred)


def screen(pilot):
    rate = pilot.pred.mean(axis=0)
    keep = np.flatnonzero((rate >= .15) & (rate <= .85))
    if not len(keep):
        raise ValueError("no calibration seed in [15%,85%]; use a larger new development panel")
    q = len(rate)
    index = np.r_[keep, np.arange(q, len(pilot.mean))]
    return keep, (pilot.mean[index], pilot.cov[np.ix_(index, index)])


def select(scores, active):
    def ranked(ids):
        return sorted(ids, key=lambda i: (-scores[i], i))
    retained = ranked(active)[:2]
    extra = ranked(set(range(len(scores))) - set(retained))[:2]
    return retained, extra

