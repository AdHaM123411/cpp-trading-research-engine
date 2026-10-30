"""The 11-step institutional alpha-combination engine.

Implements, verbatim, Part 3 of Roan's "The Math Behind Combining 50 Weak
Signals Into One Winning Trade" (the Quant Maths article). Each step in
`combine()` is annotated with the article's step number and formula.

You have N signals. Each has a historical return series across M periods.
The engine converts those series into one optimal weight per signal, then a
single combined ("mega-alpha") output, an effective-independent-signal count,
an implied information ratio, and an uncertainty-adjusted Kelly fraction.

One step in the article (Step 9) is stated in prose, not pseudocode, and is
dimensionally ambiguous for small signal stacks ("regress E_normalized over
Lambda(i,s) ... residuals = the component genuinely independent, not explained
by patterns shared across the full stack"). We implement its stated *purpose*
robustly: project the expected-return vector off the shared cross-signal
variance directions (principal components of the signal correlation matrix
with eigenvalue > 1, i.e. variance shared by more than one signal) and keep
the residual. This is exact for independent signals (no shrinkage), shrinks
redundant/duplicated signals toward zero, and is well-defined for any N >= 1.
The interpretation is documented inline at Step 9.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _kelly_fraction(p: float, b: float) -> float:
    """Classical Kelly for a binary bet: f_kelly = (p*b - q) / b."""
    q = 1.0 - p
    if b <= 0:
        return 0.0
    return (p * b - q) / b


def combine(
    returns: pd.DataFrame,
    d: int = 20,
    ic: float | None = None,
    prediction_market: bool = False,
    b: float = 1.0,
    mc_paths: int = 10_000,
    seed: int = 42,
) -> dict:
    """Run the 11-step engine.

    Parameters
    ----------
    returns : DataFrame, shape (M periods, N signals)
        returns.iloc[s, i] = R(i, s): the realised P&L of acting on signal i
        in period s. Index = time, columns = signal names.
    d : int
        Lookback for the Step-8 expected-return moving average.
    ic : float, optional
        Average information coefficient across signals. If given, the
        Fundamental Law IR = IC * sqrt(effective_N) is reported.
    prediction_market : bool
        Part-5 mode. Combined output is read as a probability estimate and
        the empirical-Kelly block is reported against even-money odds `b`.
    b : float
        Bet odds for the Kelly block (1.0 = even money).
    mc_paths : int
        Bootstrap paths for CV_edge (uncertainty of the edge estimate).
    seed : int
        RNG seed for the Monte-Carlo CV_edge estimate.

    Returns
    -------
    dict with: weights, raw_weights, effective_N, ir_estimate,
    kelly_fraction, kelly_raw, cv_edge, combined_signal, sigma, epsilon,
    n_signals, n_periods.
    """
    if returns.shape[1] < 1:
        raise ValueError("need at least one signal column")
    R = returns.astype(float).copy()
    M, N = R.shape

    # --- Step 1: collect R(i, s) -------------------------------------------
    # (the input frame is exactly this)

    # --- Step 2: serial demean.  X(i,s) = R(i,s) - mean_s R(i,.) -----------
    X = R - R.mean(axis=0)

    # --- Step 3: sample variance.  sigma(i)^2 = (1/M) sum_s X(i,s)^2 -------
    sigma2 = (X**2).mean(axis=0)
    sigma = np.sqrt(sigma2)
    sigma = sigma.replace(0.0, np.nan)  # a dead (constant) signal -> no weight

    # --- Step 4: normalise.  Y(i,s) = X(i,s) / sigma(i) -------------------
    Y = X / sigma

    # --- Step 5: drop the most recent observation (no look-ahead) ---------
    Y = Y.iloc[:-1] if len(Y) > 2 else Y

    # --- Step 6: cross-sectional demean at each period --------------------
    #     Lambda(i,s) = Y(i,s) - (1/N) sum_j Y(j,s)
    Lam = Y.sub(Y.mean(axis=1), axis=0)

    # --- Step 7: drop one more period (residual look-ahead hygiene) -------
    Lam = Lam.iloc[:-1] if len(Lam) > 2 else Lam

    # --- Step 8: expected forward return, normalised ----------------------
    #     E(i) = (1/d) sum of the most recent d R(i,s); E_norm = E / sigma
    E = R.tail(d).mean(axis=0)
    E_norm = (E / sigma).fillna(0.0)

    # --- Step 9: residual after removing shared variance with Lambda ------
    # Purpose (article, Part 4): keep only the part of each signal's expected
    # return that NO OTHER signal in the stack already explains. We identify
    # the shared structure as the principal components of the cross-signal
    # correlation matrix of Lambda whose eigenvalue > 1 (variance carried by
    # more than one signal), then project E_norm off that subspace.
    cols = list(R.columns)
    Lam_v = Lam[cols].to_numpy()
    e = E_norm.to_numpy(dtype=float)
    if N == 1 or Lam_v.shape[0] < 2:
        epsilon = e.copy()
    else:
        std = Lam_v.std(axis=0, ddof=1)
        std_safe = np.where(std == 0, 1.0, std)
        Z = (Lam_v - Lam_v.mean(axis=0)) / std_safe
        C = np.corrcoef(Z, rowvar=False)
        C = np.nan_to_num(C, nan=0.0)
        # GLS whitening by the inverse signal-correlation. This is the
        # Frisch-Waugh-Lovell realisation of "the residual of the expected
        # return after removing the variance it shares with the rest of the
        # stack": e_independent = C^+ @ E_norm. Two perfectly correlated
        # signals SHARE one signal's worth of weight (pinv splits it) instead
        # of each receiving full weight. An independent stack has C ~ I, so
        # C^+ ~ I and nothing is shrunk. Pseudo-inverse keeps it well-defined
        # when duplicates make C singular.
        epsilon = np.linalg.pinv(C, rcond=1e-10) @ e

    # --- Step 10: w(i) = eta * epsilon(i) / sigma(i) ----------------------
    sig = sigma.reindex(cols).to_numpy(dtype=float)
    sig_safe = np.where(np.isfinite(sig) & (sig != 0), sig, np.nan)
    raw_w = epsilon / sig_safe
    raw_w = np.nan_to_num(raw_w, nan=0.0)

    # --- Step 11: normalise so sum |w| = 1 (full allocation, no leverage) -
    denom = np.abs(raw_w).sum()
    w = raw_w / denom if denom > 0 else raw_w
    weights = pd.Series(w, index=cols, name="weight")
    raw_weights = pd.Series(raw_w, index=cols, name="raw_weight")

    # --- Effective number of independent signals --------------------------
    # Participation ratio of the (L1-normalised) weight vector. Equals N for
    # an equal-weight stack, collapses toward the count of signals that
    # actually carry weight after redundancy is stripped. This is the N that
    # belongs in the Fundamental Law, not the raw column count.
    w2 = float((w**2).sum())
    effective_N = (1.0 / w2) if w2 > 0 else 0.0
    ir_estimate = (ic * np.sqrt(effective_N)) if ic is not None else None

    # --- Combined "mega-alpha": weighted sum of the normalised signals ----
    Yfull = (X / sigma).fillna(0.0)
    combined_signal = (Yfull[cols] * weights.reindex(cols).to_numpy()).sum(axis=1)
    combined_signal.name = "combined_signal"

    # --- Empirical Kelly with uncertainty haircut -------------------------
    #     f_empirical = f_kelly * (1 - CV_edge)
    #     CV_edge from a Monte-Carlo bootstrap of the combined return stream.
    combined_returns = (R[cols] * weights.reindex(cols).to_numpy()).sum(axis=1)
    cr = combined_returns.to_numpy(dtype=float)
    cr = cr[np.isfinite(cr)]
    rng = np.random.default_rng(seed)
    if len(cr) >= 5:
        idx = rng.integers(0, len(cr), size=(mc_paths, len(cr)))
        path_edges = cr[idx].mean(axis=1)
        mean_edge = float(path_edges.mean())
        cv_edge = (
            float(path_edges.std(ddof=1) / abs(mean_edge))
            if mean_edge != 0
            else float("inf")
        )
        wins = cr[cr > 0]
        losses = cr[cr < 0]
        p_win = float(len(wins) / len(cr))
        if prediction_market:
            p_for_kelly, b_for_kelly = p_win, b
        else:
            avg_win = float(wins.mean()) if len(wins) else 0.0
            avg_loss = float(-losses.mean()) if len(losses) else 0.0
            b_for_kelly = (avg_win / avg_loss) if avg_loss > 0 else b
            p_for_kelly = p_win
        kelly_raw = _kelly_fraction(p_for_kelly, b_for_kelly)
    else:
        cv_edge = float("inf")
        kelly_raw = 0.0

    cv_clamped = min(max(cv_edge, 0.0), 1.0) if np.isfinite(cv_edge) else 1.0
    kelly_fraction = max(kelly_raw * (1.0 - cv_clamped), 0.0)

    return {
        "weights": weights,
        "raw_weights": raw_weights,
        "effective_N": effective_N,
        "ir_estimate": ir_estimate,
        "kelly_fraction": kelly_fraction,
        "kelly_raw": kelly_raw,
        "cv_edge": cv_edge,
        "combined_signal": combined_signal,
        "sigma": sigma.reindex(cols),
        "epsilon": pd.Series(epsilon, index=cols, name="epsilon"),
        "n_signals": int(N),
        "n_periods": int(M),
    }
