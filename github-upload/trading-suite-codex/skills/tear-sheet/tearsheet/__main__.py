"""CLI: python -m tearsheet --input trades.csv --out report.html

Reads a trade log / equity curve CSV, auto-detects its shape, and writes a
self-contained QuantStats HTML tear-sheet plus a PNG snapshot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .tearsheet import TearSheetError, build_report, load_returns


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tearsheet",
        description="Turn a trade log or equity curve into a QuantStats tear-sheet.",
    )
    p.add_argument("--input", "-i", required=True, help="Path to the CSV.")
    p.add_argument(
        "--out",
        "-o",
        default="report.html",
        help="Output HTML path (default: report.html).",
    )
    p.add_argument(
        "--png",
        default=None,
        help="Output PNG path for the key-panel snapshot "
        "(default: alongside the HTML).",
    )
    p.add_argument(
        "--type",
        dest="kind",
        choices=["returns", "equity", "pnl"],
        default=None,
        help="Force the input interpretation (default: auto-detect).",
    )
    p.add_argument("--date-col", default=None, help="Name of the date column.")
    p.add_argument("--value-col", default=None, help="Name of the value column.")
    p.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Starting capital for PnL inputs (default: 10000).",
    )
    p.add_argument(
        "--benchmark",
        "-b",
        default=None,
        help="Benchmark CSV path or ticker (e.g. SPY) for relative metrics.",
    )
    p.add_argument("--title", default="Strategy Tear-Sheet", help="Report title.")
    args = p.parse_args(argv)

    try:
        loaded = load_returns(
            args.input,
            kind=args.kind,
            date_col=args.date_col,
            value_col=args.value_col,
            capital=args.capital,
        )
        print(f"[tearsheet] {loaded.note}", file=sys.stderr)

        out_html = Path(args.out)
        png = Path(args.png) if args.png else out_html.with_suffix(".png")

        metrics = build_report(
            loaded.returns,
            out_html,
            title=args.title,
            benchmark=args.benchmark,
            png=png,
        )
    except TearSheetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("\nTear-sheet written:")
    print(f"  HTML : {metrics['html']}")
    if "png" in metrics:
        print(f"  PNG  : {metrics['png']}")
    print("\nHeadline metrics")
    print(
        f"  Period       : {metrics['start']} -> {metrics['end']} "
        f"({metrics['periods']} periods)"
    )
    print(f"  Total return : {_fmt_pct(metrics['total_return'])}")
    print(f"  CAGR         : {_fmt_pct(metrics['cagr'])}")
    print(f"  Sharpe       : {metrics['sharpe']:.2f}")
    print(f"  Sortino      : {metrics['sortino']:.2f}")
    print(f"  Max drawdown : {_fmt_pct(metrics['max_drawdown'])}")
    print(f"  Volatility   : {_fmt_pct(metrics['volatility'])}")
    print(f"  Win rate     : {_fmt_pct(metrics['win_rate'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
