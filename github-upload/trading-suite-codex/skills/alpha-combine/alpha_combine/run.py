"""CLI entry point for the alpha-combine engine.

Usage:
    # combine a CSV of per-period signal returns (index=date, cols=signals)
    uv run python -m alpha_combine.run --csv signals.csv [--ic 0.05]

    # demo: build the classic BTC signal families and combine them
    uv run python -m alpha_combine.run --ticker BTC-USD --years 10 --ic 0.05

    # prediction-market mode (Part 5)
    uv run python -m alpha_combine.run --csv probs.csv --prediction-market
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

from .engine import combine


def _fetch_close(ticker: str, years: int) -> pd.Series:
    import yfinance as yf

    end = pd.Timestamp.utcnow().normalize()
    start = end - pd.DateOffset(years=years)
    for attempt in (1, 2):
        try:
            df = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! yfinance error on attempt {attempt}: {exc}")
            df = pd.DataFrame()
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df["Close"].dropna()
        if attempt == 1:
            print("  ! yfinance returned empty data — retrying in 30s.")
            time.sleep(30)
    raise RuntimeError(f"yfinance returned empty data for {ticker} after retry.")


def _classic_signal_returns(close: pd.Series) -> pd.DataFrame:
    """The classic signal families the orchestrator feeds the engine.

    Each column is the per-period P&L of acting on that signal: signal sign
    at t, realised on the next-day return. These are the *basis* the engine
    measures the LSTM / Markov signals' independent edge against.
    """
    ret = close.pct_change()
    fwd = ret.shift(-1)  # next-day return acted on by today's signal

    mom = np.sign(close.pct_change(20))  # 20d momentum
    rev = -np.sign(close.pct_change(5))  # 5d mean reversion
    vol20 = ret.rolling(20).std()
    vol60 = ret.rolling(60).std()
    volsig = np.sign(vol60 - vol20)  # vol-compression -> risk-on

    out = pd.DataFrame(
        {
            "momentum_20d": mom * fwd,
            "mean_reversion_5d": rev * fwd,
            "volatility_regime": volsig * fwd,
        }
    ).dropna()
    return out


def main() -> int:
    p = argparse.ArgumentParser(prog="alpha-combine")
    p.add_argument("--csv", help="CSV of per-period signal returns (index=date)")
    p.add_argument("--ticker", default="BTC-USD")
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--d", type=int, default=20, help="Step-8 expected-return lookback")
    p.add_argument("--ic", type=float, default=None, help="Avg information coefficient")
    p.add_argument("--prediction-market", action="store_true")
    p.add_argument("--b", type=float, default=1.0, help="Kelly bet odds (1=even)")
    args = p.parse_args()

    if args.csv:
        print(f"\nalpha-combine — csv={args.csv}")
        returns = pd.read_csv(args.csv, index_col=0, parse_dates=True)
    else:
        print(
            f"\nalpha-combine — demo on classic {args.ticker} signal families "
            f"(years={args.years})"
        )
        print(f"  fetching {args.ticker} from Yahoo Finance...")
        close = _fetch_close(args.ticker, args.years)
        print(
            f"  fetched {len(close)} rows | "
            f"{close.index.min().date()} -> {close.index.max().date()}"
        )
        returns = _classic_signal_returns(close)

    print(f"  {returns.shape[0]} periods x {returns.shape[1]} signals")

    res = combine(
        returns,
        d=args.d,
        ic=args.ic,
        prediction_market=args.prediction_market,
        b=args.b,
    )

    print("\n11-step combined weights (sum |w| = 1):")
    w = res["weights"].sort_values(key=np.abs, ascending=False)
    for name, val in w.items():
        bar = "#" * int(round(abs(val) * 40))
        print(f"  {name:>22s}  {val:+.4f}  {bar}")

    print(
        f"\n  Effective independent signals : {res['effective_N']:.2f}"
        f"  (raw count {res['n_signals']})"
    )
    if res["ir_estimate"] is not None:
        print(f"  Implied IR (IC x sqrt(eff N)) : {res['ir_estimate']:.4f}")
    cv = res["cv_edge"]
    cv_s = f"{cv:.3f}" if np.isfinite(cv) else "inf (too few periods)"
    print(f"  CV of edge (Monte-Carlo)      : {cv_s}")
    print(f"  Kelly fraction (raw)          : {res['kelly_raw']:.4f}")
    print(f"  Kelly fraction (CV-adjusted)  : {res['kelly_fraction']:.4f}")
    if args.prediction_market:
        print("  [prediction-market mode: combined output read as probability]")

    print("\n----------------------------------------------------------------")
    print(" Framework: Roan (@RohOnChain), Quant Maths article. Built as a")
    print(" Claude Code skill by Lewis Jackson. Backtests are historical.")
    print("----------------------------------------------------------------\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
