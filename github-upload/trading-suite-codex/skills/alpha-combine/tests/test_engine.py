"""Verification suite for the 11-step engine.

Plan verification step 1: feed signals with a known independence structure
and assert the engine (a) never double-counts a redundant signal, (b) reports
an effective-independent count well below the raw column count when the stack
is redundant, and (c) lets genuine independent edge out-weigh copies.

These assert deterministic *invariants* of the institutional procedure, not
magic-number performance bands. Note the article explicitly permits signed
weights (Step 11 normalises sum|w|=1), so magnitude comparisons use abs().
"""

import numpy as np
import pandas as pd
import pytest

from alpha_combine.engine import combine

T = 1200
_IDX = pd.date_range("2019-01-01", periods=T, freq="D")


def _exact_dup_strong_edge():
    """3 independent clean edges + 2 EXACT duplicates of the first two."""
    rng = np.random.default_rng(0)
    b1 = rng.normal(0, 0.01, T)
    b2 = rng.normal(0, 0.01, T)
    b3 = rng.normal(0, 0.01, T)
    return pd.DataFrame(
        {
            "s1": b1 + 0.004,
            "s2": b2 + 0.002,
            "s3": b3 + 0.001,
            "dup_s1": b1 + 0.004,
            "dup_s2": b2 + 0.002,
        },
        index=_IDX,
    )


def _near_dup_noisy():
    """3 independent + 2 noisy near-copies (the realistic redundancy case)."""
    rng = np.random.default_rng(0)
    s1 = rng.normal(0, 0.01, T)
    s2 = rng.normal(0, 0.01, T)
    s3 = rng.normal(0, 0.01, T)
    return pd.DataFrame(
        {
            "s1": s1,
            "s2": s2,
            "s3": s3,
            "dup_s1": s1 + rng.normal(0, 5e-4, T),
            "dup_s2": s2 + rng.normal(0, 5e-4, T),
        },
        index=_IDX,
    )


def test_weights_l1_normalised():
    for df in (_exact_dup_strong_edge(), _near_dup_noisy()):
        res = combine(df)
        assert abs(res["weights"].abs().sum() - 1.0) < 1e-9


def test_exact_duplicate_is_not_double_counted():
    """The core anti-double-count guarantee: an exact duplicate receives
    *identical* weight to its original (pinv splits the shared weight), so a
    signal entered twice does not get twice the influence."""
    res = combine(_exact_dup_strong_edge(), d=T)
    w = res["weights"]
    assert w["s1"] == pytest.approx(w["dup_s1"], rel=1e-6)
    assert w["s2"] == pytest.approx(w["dup_s2"], rel=1e-6)


def test_redundant_stack_has_low_effective_n():
    """5 columns but only 3 independent -> effective_N must sit well below
    the raw count, and never below the deduplicated stack's count."""
    full = _exact_dup_strong_edge()
    dedup = full[["s1", "s2", "s3"]]
    r_full = combine(full, d=T)
    r_dedup = combine(dedup, d=T)
    assert r_full["n_signals"] == 5
    assert r_full["effective_N"] < 4.2, r_full["effective_N"]
    assert r_full["effective_N"] >= r_dedup["effective_N"] - 1e-9
    assert r_full["effective_N"] < r_full["n_signals"]


def test_independent_edge_outweighs_redundant_copies():
    """With genuine edge present, the aggregate weight on the independent
    signals (including the unique-edge s3 that nothing else replicates)
    exceeds the aggregate weight on the pure copies."""
    res = combine(_exact_dup_strong_edge(), d=T)
    w = res["weights"].abs()
    independent = w["s1"] + w["s2"] + w["s3"]
    redundant = w["dup_s1"] + w["dup_s2"]
    assert independent > redundant, (independent, redundant)


def test_ir_estimate_uses_effective_n():
    res = combine(_near_dup_noisy(), ic=0.05)
    assert res["ir_estimate"] == pytest.approx(
        0.05 * np.sqrt(res["effective_N"]), rel=1e-9
    )


def test_single_signal_degrades_gracefully():
    idx = pd.date_range("2022-01-01", periods=300, freq="D")
    df = pd.DataFrame(
        {"only": np.random.default_rng(2).normal(0, 0.01, 300)}, index=idx
    )
    res = combine(df)
    assert res["n_signals"] == 1
    assert abs(res["weights"].abs().sum() - 1.0) < 1e-9


def test_prediction_market_mode_runs():
    res = combine(_exact_dup_strong_edge(), prediction_market=True, b=1.0)
    assert 0.0 <= res["kelly_fraction"] <= 1.0
    assert np.isfinite(res["cv_edge"]) or res["cv_edge"] == float("inf")
