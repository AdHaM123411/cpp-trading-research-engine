"""Tests for the tear-sheet skill.

These cover the part that actually matters: turning the three common input
shapes (returns / equity / trade PnL) into a clean daily returns series, plus
an end-to-end render that proves a real HTML + PNG file lands on disk.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tearsheet.tearsheet import (
    TearSheetError,
    build_report,
    load_returns,
)

SAMPLE = Path(__file__).parent / "sample_trades.csv"
T = 400
_IDX = pd.date_range("2022-01-01", periods=T, freq="B")


def _write(tmp_path, name, df):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def test_detects_pnl_from_sample():
    res = load_returns(SAMPLE)
    assert res.kind == "pnl"
    assert len(res.returns) > 2
    assert res.returns.index.is_monotonic_increasing


def test_detects_equity_curve(tmp_path):
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, T)
    equity = 10_000 * np.cumprod(1 + rets)
    df = pd.DataFrame({"date": _IDX, "equity": equity})
    res = load_returns(_write(tmp_path, "eq.csv", df))
    assert res.kind == "equity"
    # Equity -> pct_change drops the first row.
    assert len(res.returns) == T - 1
    np.testing.assert_allclose(res.returns.values, rets[1:], rtol=1e-6)


def test_detects_fractional_returns(tmp_path):
    rng = np.random.default_rng(1)
    rets = rng.normal(0.0, 0.01, T)
    df = pd.DataFrame({"date": _IDX, "return": rets})
    res = load_returns(_write(tmp_path, "r.csv", df))
    assert res.kind == "returns"
    np.testing.assert_allclose(res.returns.values, rets, rtol=1e-6)


def test_percent_returns_are_rescaled(tmp_path):
    # Returns quoted in percent (e.g. 1.5 meaning 1.5%) get divided by 100.
    rets_pct = np.full(T, 2.0)
    rets_pct[::2] = -1.5
    df = pd.DataFrame({"date": _IDX, "ret_pct": rets_pct})
    res = load_returns(_write(tmp_path, "pct.csv", df))
    assert res.returns.abs().median() < 0.5


def test_pnl_conversion_uses_capital(tmp_path):
    # First trade: +500 on 10k capital -> exactly 5% return.
    df = pd.DataFrame({"date": ["2022-01-03", "2022-01-04"], "pnl": [500.0, -200.0]})
    res = load_returns(_write(tmp_path, "p.csv", df), capital=10_000)
    assert res.returns.iloc[0] == pytest.approx(0.05, rel=1e-9)


def test_same_day_trades_are_compounded(tmp_path):
    df = pd.DataFrame(
        {
            "date": ["2022-01-03", "2022-01-03", "2022-01-04"],
            "return": [0.01, 0.02, -0.005],
        }
    )
    res = load_returns(_write(tmp_path, "dup.csv", df))
    # Two same-day returns compound: (1.01 * 1.02) - 1.
    assert len(res.returns) == 2
    assert res.returns.iloc[0] == pytest.approx(0.01 * 1.02 + 0.02, rel=1e-9)


def test_missing_file_raises():
    with pytest.raises(TearSheetError):
        load_returns("/nope/does-not-exist.csv")


def test_too_few_rows_raises(tmp_path):
    df = pd.DataFrame({"date": ["2022-01-03"], "return": [0.01]})
    with pytest.raises(TearSheetError):
        load_returns(_write(tmp_path, "one.csv", df))


@pytest.mark.skipif(
    pytest.importorskip("quantstats", reason="quantstats not installed") is None,
    reason="quantstats not installed",
)
def test_end_to_end_renders_html_and_png(tmp_path):
    res = load_returns(SAMPLE)
    out_html = tmp_path / "report.html"
    out_png = tmp_path / "snap.png"
    metrics = build_report(res.returns, out_html, title="Sample", png=out_png)
    assert out_html.exists() and out_html.stat().st_size > 0
    assert out_png.exists() and out_png.stat().st_size > 0
    assert np.isfinite(metrics["sharpe"])
    assert -1.0 <= metrics["max_drawdown"] <= 0.0
    assert 0.0 <= metrics["win_rate"] <= 1.0
