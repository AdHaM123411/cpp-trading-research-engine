"""Verification suite for the safety gate.

The four required invariants, each asserting a hard guarantee of the gate (not a
performance band):
  a) a live order with no ALLOW_TRADING routes to paper,
  b) an order breaching a risk limit is blocked,
  c) a live order without the correct typed confirmation is rejected,
  d) a fully-valid confirmed live order passes the gate to a stub adapter.

No live order is ever transmitted: the "live" adapter is a local simulating stub
and tests control ALLOW_TRADING via monkeypatch, never the real shell.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from execution_safety import (  # noqa: E402
    Order,
    RiskProfile,
    StubLiveAdapter,
    guard_order,
)


def _profile() -> RiskProfile:
    return RiskProfile(
        account_equity=100_000.0,
        max_risk_per_trade_pct=1.0,  # max $1,000 at risk
        max_daily_loss_pct=3.0,
        current_open_risk_pct=0.0,
        max_position_notional=50_000.0,
        min_stop_atr_mult=1.0,
        symbol_allowlist=["SPY", "EUR/USD", "BTC-PERP"],
    )


def _good_order() -> Order:
    # 100 SPY @ 100, stop 5 away => $500 risk = 0.5% of equity. Notional 10k.
    # Stop 5 away, ATR 4 => 1.25x ATR. Passes every limit.
    return Order(
        symbol="SPY",
        side="sell",
        qty=100,
        order_type="market",
        price=100.0,
        stop=105.0,
        atr=4.0,
    )


@pytest.fixture
def audit(tmp_path) -> Path:
    return tmp_path / "audit.jsonl"


# (a) ----------------------------------------------------------------------- #
def test_live_without_allow_trading_routes_to_paper(monkeypatch, audit):
    monkeypatch.delenv("ALLOW_TRADING", raising=False)
    res = guard_order(
        _good_order(),
        _profile(),
        live=True,
        confirmation="CONFIRM SELL 100 SPY @ market",
        audit_path=audit,
    )
    assert res["routed"] == "paper", res
    assert "ALLOW_TRADING" in res["reason"]
    assert audit.exists()


# (b) ----------------------------------------------------------------------- #
def test_risk_limit_breach_is_blocked(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    # Stop 60 away on 100 qty => $6,000 risk = 6% of equity, over the 1% cap.
    bad = Order(
        symbol="SPY",
        side="sell",
        qty=100,
        order_type="market",
        price=100.0,
        stop=160.0,
        atr=4.0,
    )
    res = guard_order(
        bad,
        _profile(),
        live=True,
        confirmation=bad.confirmation_token(),
        audit_path=audit,
    )
    assert res["routed"] == "blocked", res
    assert any("per-trade cap" in b for b in res["breaches"]), res["breaches"]


def test_missing_stop_is_blocked(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    bad = Order(symbol="SPY", side="buy", qty=10, price=100.0, stop=None, atr=4.0)
    res = guard_order(bad, _profile(), live=False, audit_path=audit)
    assert res["routed"] == "blocked"
    assert any("stop" in b.lower() for b in res["breaches"])


def test_symbol_not_on_allowlist_is_blocked(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    bad = Order(symbol="GME", side="buy", qty=10, price=100.0, stop=96.0, atr=4.0)
    res = guard_order(bad, _profile(), live=False, audit_path=audit)
    assert res["routed"] == "blocked"
    assert any("allowlist" in b.lower() for b in res["breaches"])


# (c) ----------------------------------------------------------------------- #
def test_live_with_wrong_confirmation_is_rejected(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    res = guard_order(
        _good_order(),
        _profile(),
        live=True,
        confirmation="yes do it",
        audit_path=audit,
    )
    assert res["routed"] == "blocked", res
    assert res["expected_confirmation"] == "CONFIRM SELL 100 SPY @ market"


def test_live_with_no_confirmation_is_rejected(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    res = guard_order(
        _good_order(), _profile(), live=True, confirmation=None, audit_path=audit
    )
    assert res["routed"] == "blocked"


# (d) ----------------------------------------------------------------------- #
def test_valid_confirmed_live_order_passes_to_stub_adapter(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    res = guard_order(
        _good_order(),
        _profile(),
        live=True,
        confirmation="CONFIRM SELL 100 SPY @ market",
        live_adapter=StubLiveAdapter(),
        audit_path=audit,
    )
    assert res["routed"] == "live", res
    assert res["fill"]["broker"] == "stub-live"
    assert res["fill"]["ok"] is True


# extra invariants ---------------------------------------------------------- #
def test_default_is_paper(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    res = guard_order(
        _good_order(), _profile(), audit_path=audit
    )  # live defaults False
    assert res["routed"] == "paper"


def test_every_decision_is_audited(monkeypatch, audit):
    monkeypatch.setenv("ALLOW_TRADING", "1")
    guard_order(_good_order(), _profile(), live=False, audit_path=audit)
    guard_order(
        _good_order(),
        _profile(),
        live=True,
        confirmation="CONFIRM SELL 100 SPY @ market",
        audit_path=audit,
    )
    lines = [l for l in audit.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
