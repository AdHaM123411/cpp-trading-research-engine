"""Turn a trade log or equity curve into a QuantStats performance tear-sheet.

The hard part of wrapping QuantStats is not the report — it is getting a
clean daily *returns* series out of whatever shape the user hands you. People
keep their track record in three common ways:

    1. daily (or per-period) percentage returns      e.g. 0.012, -0.004
    2. an equity / balance curve (account value)       e.g. 10000, 10120, ...
    3. a trade-by-trade PnL log (dollars per trade)    e.g. +320, -110, ...

`load_returns()` detects which one you gave it and converts everything to a
datetime-indexed daily returns Series, which is the only thing QuantStats
actually consumes. `build_report()` then renders the self-contained HTML and a
PNG snapshot of the key panel.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Column-name hints for auto-detection (matched case-insensitively, substring).
_EQUITY_HINTS = ("equity", "balance", "nav", "account", "value", "capital", "close")
_PNL_HINTS = ("pnl", "p&l", "p_l", "profit", "pl", "dollar", "net")
_RETURN_HINTS = ("return", "ret", "pct", "%", "change", "r_")
_DATE_HINTS = ("date", "time", "timestamp", "day", "dt", "datetime")


class TearSheetError(ValueError):
    """Raised for input we cannot turn into a returns series."""


@dataclass
class LoadResult:
    """A returns series plus a note on how it was derived (for the CLI to print)."""

    returns: pd.Series
    kind: str  # "returns" | "equity" | "pnl"
    note: str


def _pick_date_column(df: pd.DataFrame) -> str | None:
    """Find the column that looks like a date, preferring named hints."""
    for col in df.columns:
        if any(h in str(col).lower() for h in _DATE_HINTS):
            return col
    # Fall back: first column that parses as datetime for most rows.
    for col in df.columns:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
        except (ValueError, TypeError):
            continue
        if parsed.notna().mean() > 0.8:
            return col
    return None


def _pick_value_column(df: pd.DataFrame, date_col: str | None) -> str:
    """Pick the numeric value column (the one we'll interpret as the series)."""
    candidates = [c for c in df.columns if c != date_col]
    numeric = [c for c in candidates if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        # Try coercing each candidate; keep the most-numeric one.
        best, best_score = None, 0.0
        for c in candidates:
            score = pd.to_numeric(df[c], errors="coerce").notna().mean()
            if score > best_score:
                best, best_score = c, score
        if best is None or best_score < 0.5:
            raise TearSheetError(
                "No numeric value column found. Pass --value-col explicitly."
            )
        return best
    # Prefer a column whose name hints at equity/return/pnl, else the last one.
    for hints in (_EQUITY_HINTS, _RETURN_HINTS, _PNL_HINTS):
        for c in numeric:
            if any(h in str(c).lower() for h in hints):
                return c
    return numeric[-1]


def _classify(series: pd.Series, value_col: str) -> str:
    """Decide whether a numeric series is returns, equity levels, or trade PnL."""
    name = str(value_col).lower()
    if any(h in name for h in _EQUITY_HINTS):
        return "equity"
    if any(h in name for h in _RETURN_HINTS):
        return "returns"
    if any(h in name for h in _PNL_HINTS):
        return "pnl"

    vals = series.dropna().astype(float)
    if vals.empty:
        raise TearSheetError("Value column is empty after dropping NaNs.")

    # Heuristics when the column name gives nothing away:
    all_positive = (vals > 0).all()
    median_abs = vals.abs().median()
    has_negatives = (vals < 0).any()

    # Equity curves are all-positive and large (account values), and tend to
    # drift in one direction rather than oscillate around zero.
    if all_positive and median_abs > 5:
        return "equity"
    # Dollar PnL: sizable magnitudes with both signs.
    if has_negatives and median_abs >= 1.5:
        return "pnl"
    # Everything small and centred near zero -> already returns.
    return "returns"


def _to_daily_returns(series: pd.Series, kind: str, capital: float) -> pd.Series:
    """Convert a typed series into a daily returns Series."""
    series = series.sort_index()

    if kind == "returns":
        rets = series.astype(float)
        # Accept either fractional (0.01) or percent (1.0 meaning 1%) inputs.
        # If the typical move is > 1.5 in absolute terms it is almost certainly
        # quoted in percent, so rescale.
        if rets.abs().median() > 1.5:
            rets = rets / 100.0
    elif kind == "equity":
        rets = series.astype(float).pct_change()
    elif kind == "pnl":
        # Build an equity curve from a starting capital, then take returns.
        # return_t = pnl_t / equity_{t-1}, which is the honest per-period return.
        equity = capital + series.astype(float).cumsum()
        prev = equity.shift(1).fillna(capital)
        rets = series.astype(float) / prev
    else:  # pragma: no cover - guarded upstream
        raise TearSheetError(f"Unknown series kind: {kind}")

    # Multiple trades on the same calendar day -> compound them into one daily
    # return so QuantStats sees a clean daily frequency.
    if rets.index.has_duplicates:
        rets = (1.0 + rets).groupby(level=0).prod() - 1.0

    rets = rets.replace([np.inf, -np.inf], np.nan).dropna()
    rets.name = "returns"
    return rets


def load_returns(
    path: str | Path,
    *,
    kind: str | None = None,
    date_col: str | None = None,
    value_col: str | None = None,
    capital: float = 10_000.0,
) -> LoadResult:
    """Read a CSV and return a daily returns Series with detection metadata.

    Parameters mirror the CLI flags. `kind` forces the interpretation
    ("returns" | "equity" | "pnl"); leave it None to auto-detect.
    """
    path = Path(path)
    if not path.exists():
        raise TearSheetError(f"Input file not found: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise TearSheetError("Input CSV has no rows.")

    date_col = date_col or _pick_date_column(df)
    if date_col is None:
        raise TearSheetError(
            "Could not find a date column. Pass --date-col with the column name."
        )

    value_col = value_col or _pick_value_column(df, date_col)
    if value_col not in df.columns:
        raise TearSheetError(f"value column '{value_col}' not in CSV.")

    idx = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    vals = pd.to_numeric(df[value_col], errors="coerce")
    series = pd.Series(vals.values, index=idx).dropna()
    series = series[series.index.notna()]
    if series.empty:
        raise TearSheetError(
            "No usable (date, value) rows after parsing. Check column choices."
        )

    kind = kind or _classify(series, value_col)
    if kind not in ("returns", "equity", "pnl"):
        raise TearSheetError(f"--type must be returns|equity|pnl, got {kind!r}")

    rets = _to_daily_returns(series, kind, capital)
    if len(rets) < 2:
        raise TearSheetError(
            "Need at least two periods of returns to build a tear-sheet."
        )

    note = (
        f"detected={kind}; date_col='{date_col}'; value_col='{value_col}'; "
        f"periods={len(rets)}; range={rets.index.min().date()}..{rets.index.max().date()}"
    )
    return LoadResult(returns=rets, kind=kind, note=note)


def _load_benchmark(benchmark: str | None, index: pd.DatetimeIndex):
    """Resolve a benchmark argument to a returns Series, or None.

    Accepts either a CSV path (same detection as the main input) or a ticker
    symbol that QuantStats downloads via yfinance.
    """
    if not benchmark:
        return None
    p = Path(benchmark)
    if p.exists():
        return load_returns(p).returns
    # Treat as a ticker. QuantStats handles the download + alignment.
    import quantstats as qs  # local import: only needed when a ticker is given

    try:
        bench = qs.utils.download_returns(benchmark)
        return bench
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        raise TearSheetError(
            f"Could not load benchmark '{benchmark}' as a CSV path or ticker: {exc}"
        ) from exc


def _require_quantstats():
    try:
        import quantstats as qs  # noqa: F401
    except ImportError as exc:
        raise TearSheetError(
            "QuantStats is not installed. Install it with:\n"
            "    pip install quantstats\n"
            "(or, inside this skill: `uv sync`)."
        ) from exc
    return qs


def build_report(
    returns: pd.Series,
    out_html: str | Path,
    *,
    title: str = "Strategy Tear-Sheet",
    benchmark: str | None = None,
    png: str | Path | None = None,
) -> dict:
    """Render a QuantStats HTML tear-sheet and a PNG snapshot of the key panel.

    Returns a dict of headline metrics (also computed even if plotting fails).
    """
    qs = _require_quantstats()
    qs.extend_pandas()

    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)

    bench = _load_benchmark(benchmark, returns.index)

    # Headline metrics, computed directly so we can report them regardless of
    # what the HTML renderer does.
    metrics = {
        "start": str(returns.index.min().date()),
        "end": str(returns.index.max().date()),
        "periods": int(len(returns)),
        "cagr": float(qs.stats.cagr(returns)),
        "sharpe": float(qs.stats.sharpe(returns)),
        "sortino": float(qs.stats.sortino(returns)),
        "max_drawdown": float(qs.stats.max_drawdown(returns)),
        "volatility": float(qs.stats.volatility(returns)),
        "win_rate": float(qs.stats.win_rate(returns)),
        "total_return": float(qs.stats.comp(returns)),
    }

    with warnings.catch_warnings():
        # QuantStats leans on a few deprecated pandas/matplotlib calls; they are
        # noisy but harmless and would otherwise drown the CLI output.
        warnings.simplefilter("ignore")
        qs.reports.html(
            returns,
            benchmark=bench,
            output=str(out_html),
            title=title,
            download_filename=str(out_html),
        )

        if png is not None:
            png = Path(png)
            png.parent.mkdir(parents=True, exist_ok=True)
            qs.plots.snapshot(
                returns,
                title=title,
                savefig=str(png),
                show=False,
            )

    metrics["html"] = str(out_html)
    if png is not None:
        metrics["png"] = str(png)
    return metrics
