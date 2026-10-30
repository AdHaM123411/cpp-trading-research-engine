"""Overfitting checks, clean-room from the public Bailey / Lopez de Prado papers:
Probability of Backtest Overfitting (CSCV) and the Deflated / Probabilistic
Sharpe Ratio. No scipy — normal CDF/PPF by hand. numpy + stdlib only.

The six core functions below (_norm_cdf, _norm_ppf, _sharpe_cols, cscv_pbo,
probabilistic_sharpe, deflated_sharpe) are lifted verbatim from the trading-os
validation engine. EULER_GAMMA is the Euler-Mascheroni constant used by the
deflated-Sharpe expected-maximum estimate.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

EULER_GAMMA = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Acklam's inverse normal CDF approximation."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [
        -39.69683028665376,
        220.9460984245205,
        -275.9285104469687,
        138.3577518672690,
        -30.66479806614716,
        2.506628277459239,
    ]
    b = [
        -54.47609879822406,
        161.5858368580409,
        -155.6989798598866,
        66.80131188771972,
        -13.28068155288572,
    ]
    c = [
        -0.007784894002430293,
        -0.3223964580411365,
        -2.400758277161838,
        -2.549732539343734,
        4.374664141464968,
        2.938163982698783,
    ]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def _sharpe_cols(M: np.ndarray) -> np.ndarray:
    mean = M.mean(axis=0)
    sd = M.std(axis=0, ddof=1)
    return np.divide(mean, sd, out=np.zeros_like(mean), where=sd > 0)


def cscv_pbo(M: np.ndarray, S: int = 8) -> float:
    """Probability of Backtest Overfitting via combinatorially-symmetric CV."""
    T, N = M.shape
    if N < 2 or T < 2 * S:
        return 0.5
    rows = T // S
    M = M[: rows * S]
    chunks = [M[k * rows : (k + 1) * rows] for k in range(S)]
    allset = set(range(S))
    lambdas = []
    for comb in combinations(range(S), S // 2):
        IS = np.vstack([chunks[k] for k in comb])
        OOS = np.vstack([chunks[k] for k in allset - set(comb)])
        nstar = int(np.argmax(_sharpe_cols(IS)))
        oos = _sharpe_cols(OOS)
        order = oos.argsort()
        ranks = np.empty(N)
        ranks[order] = np.arange(1, N + 1)
        w = min(max(ranks[nstar] / (N + 1), 1e-6), 1 - 1e-6)
        lambdas.append(math.log(w / (1 - w)))
    return float((np.array(lambdas) <= 0).mean())


def probabilistic_sharpe(returns: np.ndarray, sr_benchmark: float) -> float:
    n = len(returns)
    if n < 8:
        return 0.0
    sd = returns.std(ddof=1)
    if sd == 0:
        return 0.0
    sr = returns.mean() / sd
    m = returns - returns.mean()
    skew = float((m**3).mean() / sd**3)
    kurt = float((m**4).mean() / sd**4)  # non-excess
    denom = math.sqrt(max(1e-12, 1 - skew * sr + ((kurt - 1) / 4) * sr**2))
    return _norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def deflated_sharpe(returns: np.ndarray, trial_sharpes: np.ndarray) -> float:
    n_trials = max(len(trial_sharpes), 1)
    var_sr = float(np.var(trial_sharpes, ddof=1)) if n_trials > 1 else 0.0
    if var_sr <= 0 or n_trials < 2:
        return probabilistic_sharpe(returns, 0.0)
    sr_star = math.sqrt(var_sr) * (
        (1 - EULER_GAMMA) * _norm_ppf(1 - 1 / n_trials)
        + EULER_GAMMA * _norm_ppf(1 - 1 / (n_trials * math.e))
    )
    return probabilistic_sharpe(returns, sr_star)


# --- thin verdict layer (skill-specific, not part of the lifted math) ---------


def verdict(pbo: float | None = None, dsr: float | None = None) -> dict:
    """Turn raw PBO / DSR numbers into a plain-English pass/fail read.

    PBO < 0.50  -> not overfit (the winning config still wins out-of-sample
                   more often than not).
    DSR > 0.95  -> the Sharpe is very likely real after accounting for how many
                   configurations were tried.
    """
    lines = []
    checks = []

    if pbo is not None:
        pbo_pass = pbo < 0.50
        checks.append(pbo_pass)
        lines.append(
            f"PBO {pbo * 100:.0f}% — "
            + (
                "PASS. The best-looking config keeps winning out-of-sample more "
                "often than not, so the backtest is probably not just curve-fit."
                if pbo_pass
                else "FAIL. The best-looking config flips to below-median "
                "out-of-sample most of the time — this looks overfit. Treat the "
                "headline result as noise."
            )
        )

    if dsr is not None:
        dsr_strong = dsr > 0.95
        checks.append(dsr_strong)
        lines.append(
            f"DSR {dsr:.2f} — "
            + (
                "STRONG. After deflating for the number of trials, there is a "
                f"{dsr * 100:.0f}% chance the true Sharpe is above zero."
                if dsr_strong
                else "WEAK. After deflating for the number of trials, the chance "
                f"the true Sharpe is above zero is only {dsr * 100:.0f}%. The edge "
                "may be a product of trying many configurations."
            )
        )

    overall = "pass" if checks and all(checks) else "fail"
    return {"verdict": overall, "lines": lines}
