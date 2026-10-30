"""Tests for the overfitting checks.

Two headline tests required by spec:
  1. Obviously-overfit synthetic matrix -> PBO should be high (>= 0.5).
  2. Genuinely-good synthetic series   -> DSR should be high (> 0.95).

Plus sanity checks on the hand-rolled normal CDF/PPF and the verdict layer.
"""

import math

import numpy as np

from pbo_deflated_sharpe import (
    cscv_pbo,
    deflated_sharpe,
    probabilistic_sharpe,
    verdict,
    _norm_cdf,
    _norm_ppf,
    _sharpe_cols,
)


def _overfit_matrix(T=1200, N=40, S=8, bump=0.02, noise=0.01, seed=1):
    """Build a textbook-overfit trial matrix: each config gets a big return
    spike in exactly ONE time block and is pure noise everywhere else. Whichever
    config looks best in-sample only looks good because its spike happened to
    land in-sample — out-of-sample it reverts to noise and gets beaten by the
    configs whose spike lands out-of-sample. That anti-persistence is exactly
    what PBO is built to catch, so PBO should come out high regardless of seed."""
    rng = np.random.default_rng(seed)
    M = rng.standard_normal((T, N)) * noise
    rows = T // S
    for j in range(N):
        c = j % S  # this config's "lucky" block
        M[c * rows : (c + 1) * rows, j] += bump
    return M


def test_pbo_high_on_overfit_matrix():
    """Structurally overfit matrix -> the in-sample winner reverts out-of-sample,
    so PBO should be high (> 0.5)."""
    M = _overfit_matrix()
    pbo = cscv_pbo(M)
    assert pbo > 0.5, f"expected high PBO on overfit data, got {pbo:.3f}"
    # And the verdict layer should call it a fail.
    v = verdict(pbo=pbo)
    assert v["verdict"] == "fail"


def test_dsr_high_on_genuine_series():
    """A real positive drift with only a few low-variance trials should survive
    deflation -> DSR > 0.95."""
    rng = np.random.default_rng(2)
    returns = rng.standard_normal(1000) * 0.01 + 0.0011  # genuine upward drift
    trial_sharpes = np.array([0.05, 0.06, 0.04, 0.07, 0.05])
    dsr = deflated_sharpe(returns, trial_sharpes)
    assert dsr > 0.95, f"expected strong DSR, got {dsr:.4f}"
    v = verdict(dsr=dsr)
    assert v["verdict"] == "pass"


def test_dsr_deflates_below_psr_with_many_trials():
    """Deflating over many noisy trials must pull the probability DOWN relative
    to the un-deflated PSR — that is the whole point of the deflation."""
    rng = np.random.default_rng(3)
    returns = rng.standard_normal(1000) * 0.01 + 0.0006  # weak-ish edge
    many_trials = rng.standard_normal(200) * 0.08  # lots of scattered trials
    psr = probabilistic_sharpe(returns, 0.0)
    dsr = deflated_sharpe(returns, many_trials)
    assert dsr <= psr, f"deflation should not increase the probability: {dsr} vs {psr}"


def test_norm_cdf_known_values():
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-12
    assert abs(_norm_cdf(1.96) - 0.975) < 1e-3
    assert abs(_norm_cdf(-1.96) - 0.025) < 1e-3


def test_norm_ppf_inverts_cdf():
    for p in (0.025, 0.1, 0.5, 0.9, 0.975):
        assert abs(_norm_cdf(_norm_ppf(p)) - p) < 1e-4


def test_sharpe_cols_handles_zero_variance():
    M = np.array([[1.0, 0.0], [1.0, 0.5], [1.0, -0.5]])  # col 0 has zero variance
    s = _sharpe_cols(M)
    assert s[0] == 0.0
    assert math.isfinite(s[1])
