"""CLI for the overfitting checks.

Two inputs the skill accepts:

  Input A — a matrix of per-period returns, one COLUMN per strategy/parameter
            trial, one ROW per period. Feeds CSCV -> PBO%.

  Input B — the chosen strategy's own return series + the array of all trial
            Sharpes. Feeds the Deflated Sharpe Ratio.

Examples
--------
# PBO from a trial matrix (CSV: rows = periods, columns = trials, optional header)
python -m pbo_deflated_sharpe.run --matrix trials.csv

# DSR: chosen strategy returns + every trial's Sharpe
python -m pbo_deflated_sharpe.run --returns chosen.csv --sharpes sharpes.csv

# Both at once. If --sharpes is omitted, the per-column Sharpes of the matrix
# are used as the trial set, and the best column is treated as the chosen one.
python -m pbo_deflated_sharpe.run --matrix trials.csv

# A built-in demo (no files needed): one overfit case, one genuine case.
python -m pbo_deflated_sharpe.run --demo
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from .engine import (
    cscv_pbo,
    deflated_sharpe,
    probabilistic_sharpe,
    _sharpe_cols,
    verdict,
)


def _load(path: str) -> np.ndarray:
    """Load a CSV/whitespace numeric file, skipping a header row if present."""
    try:
        return np.loadtxt(path, delimiter=",")
    except ValueError:
        return np.loadtxt(path, delimiter=",", skiprows=1)


def _as_matrix(arr: np.ndarray) -> np.ndarray:
    return arr.reshape(-1, 1) if arr.ndim == 1 else arr


def _print_report(pbo=None, dsr=None, psr=None, n_trials=None):
    print("=" * 64)
    print("  Backtest overfitting report")
    print("=" * 64)
    if pbo is not None:
        print(f"  PBO (prob. of backtest overfitting) : {pbo * 100:5.1f}%")
    if psr is not None:
        print(f"  PSR (prob. Sharpe > 0, no deflation): {psr:6.3f}")
    if dsr is not None:
        extra = f"  (deflated over {n_trials} trials)" if n_trials else ""
        print(f"  DSR (deflated Sharpe, prob. real)   : {dsr:6.3f}{extra}")
    print("-" * 64)
    v = verdict(pbo=pbo, dsr=dsr)
    for line in v["lines"]:
        print(f"  {line}")
    print("-" * 64)
    print(f"  VERDICT: {v['verdict'].upper()}")
    print("=" * 64)
    return v


def _demo():
    rng = np.random.default_rng(7)
    T, N, S = 1200, 40, 8

    # Overfit case: each config gets one big return spike in a single time block
    # and is pure noise elsewhere. The in-sample winner only won because its
    # spike landed in-sample; out-of-sample it reverts -> high PBO, weak DSR.
    M = rng.standard_normal((T, N)) * 0.01
    rows = T // S
    for j in range(N):
        M[(j % S) * rows : (j % S + 1) * rows, j] += 0.02
    pbo_bad = cscv_pbo(M)
    sharpes_bad = _sharpe_cols(M)
    # For DSR, judge a config with no real edge (pure noise) against the wide
    # spread of trial Sharpes the search threw off -> deflation kills it.
    chosen_bad = rng.standard_normal(T) * 0.01
    dsr_bad = deflated_sharpe(chosen_bad, sharpes_bad)

    print("\n### DEMO 1 — 40 overfit trials (each spikes in one block) -> OVERFIT\n")
    _print_report(pbo=pbo_bad, dsr=dsr_bad, n_trials=N)

    # Genuine case: a real positive drift, only a handful of trials.
    n = 1000
    good = rng.standard_normal(n) * 0.01 + 0.0009  # ~0.09 daily Sharpe drift
    trials = np.array([0.05, 0.06, 0.04, 0.07, 0.05])  # few, low-variance trials
    psr_good = probabilistic_sharpe(good, 0.0)
    dsr_good = deflated_sharpe(good, trials)
    print("\n### DEMO 2 — genuine drift, 5 trials (should look STRONG)\n")
    _print_report(dsr=dsr_good, psr=psr_good, n_trials=len(trials))


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="pbo-deflated-sharpe",
        description="PBO / Deflated Sharpe / Probabilistic Sharpe overfitting checks.",
    )
    p.add_argument("--matrix", help="CSV of per-period returns, one column per trial.")
    p.add_argument("--returns", help="CSV of the chosen strategy's return series.")
    p.add_argument("--sharpes", help="CSV of every trial's Sharpe ratio.")
    p.add_argument(
        "--S", type=int, default=8, help="CSCV partitions (even, default 8)."
    )
    p.add_argument("--demo", action="store_true", help="Run the built-in demo.")
    args = p.parse_args(argv)

    if args.demo:
        _demo()
        return 0

    if not (args.matrix or args.returns):
        p.error("give --matrix, or --returns (+ optional --sharpes), or --demo")

    pbo = dsr = psr = None
    n_trials = None
    M = None

    if args.matrix:
        M = _as_matrix(_load(args.matrix))
        pbo = cscv_pbo(M, S=args.S)

    # Build the DSR inputs.
    chosen = None
    trial_sharpes = None
    if args.returns:
        chosen = _load(args.returns).ravel()
    if args.sharpes:
        trial_sharpes = _load(args.sharpes).ravel()

    if chosen is None and M is not None:
        # No explicit chosen series: take the best in-sample column of the matrix.
        col_sharpes = _sharpe_cols(M)
        chosen = M[:, int(np.argmax(col_sharpes))]
        if trial_sharpes is None:
            trial_sharpes = col_sharpes
    if trial_sharpes is None and M is not None:
        trial_sharpes = _sharpe_cols(M)

    if chosen is not None:
        psr = probabilistic_sharpe(chosen, 0.0)
        if trial_sharpes is not None and len(trial_sharpes) > 1:
            dsr = deflated_sharpe(chosen, trial_sharpes)
            n_trials = len(trial_sharpes)
        else:
            dsr = psr  # no trial set -> deflation is a no-op

    _print_report(pbo=pbo, dsr=dsr, psr=psr, n_trials=n_trials)
    return 0


if __name__ == "__main__":
    sys.exit(main())
