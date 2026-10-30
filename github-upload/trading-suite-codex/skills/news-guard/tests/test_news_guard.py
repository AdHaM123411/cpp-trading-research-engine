"""Deterministic tests for news-guard.

All tests use the bundled CSV via `offline=True` (or the pure `decide()`
function), so they NEVER touch the network and produce identical results on
every machine. They assert the two invariants that matter:

  * a known high-impact event window BLOCKS a relevant instrument, and
  * a quiet window APPROVES it,

plus the instrument -> currency mapping and crypto-specific handling.
"""

import os
import sys
from datetime import timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_guard import (  # noqa: E402
    decide,
    evaluate,
    instrument_currencies,
    is_crypto,
    load_from_csv,
    parse_time,
)

# The bundled CSV pins US Non-Farm Payrolls (USD, High) at 2026-07-02T13:30Z.
EVENTS = load_from_csv()


def test_instrument_currency_mapping():
    assert instrument_currencies("EURUSD") == {"EUR", "USD"}
    assert instrument_currencies("eur/usd") == {"EUR", "USD"}
    assert instrument_currencies("SPY") == {"USD"}
    assert instrument_currencies("BTC") == {"USD"}
    assert instrument_currencies("DAX") == {"EUR"}
    assert is_crypto("BTC") and not is_crypto("SPY")


def test_known_event_window_blocks():
    """EURUSD evaluated AT the NFP print -> block (USD is relevant)."""
    res = decide("EURUSD", parse_time("2026-07-02T13:30Z"), EVENTS)
    assert res["decision"] == "block"
    assert res["blocking_event"]["currency"] == "USD"
    assert "Non-Farm Payrolls" in res["blocking_event"]["title"]
    assert res["minutes_until"] == 0.0


def test_inside_window_before_blocks():
    """20 minutes before the print is inside the 30m-before window."""
    res = decide("SPY", parse_time("2026-07-02T13:10Z"), EVENTS)
    assert res["decision"] == "block"
    assert res["minutes_until"] == 20.0


def test_quiet_window_approves():
    """Hours after the print, nothing relevant is near -> approve."""
    res = decide("EURUSD", parse_time("2026-07-02T20:00Z"), EVENTS)
    assert res["decision"] == "approve"
    assert res["blocking_event"] is None


def test_just_outside_window_approves():
    """16 minutes after a 15m-after window has closed -> approve."""
    res = decide("SPY", parse_time("2026-07-02T13:46Z"), EVENTS)
    assert res["decision"] == "approve"


def test_unrelated_currency_not_blocked():
    """A GBP/JPY pair is not exposed to the USD NFP print at 13:30."""
    res = decide("GBPJPY", parse_time("2026-07-02T13:30Z"), EVENTS)
    assert res["decision"] == "approve"


def test_custom_window_widens_blackout():
    """A 120m-before window catches the print from two hours out."""
    res = decide(
        "EURUSD",
        parse_time("2026-07-02T11:45Z"),
        EVENTS,
        before_min=120,
        after_min=15,
    )
    assert res["decision"] == "block"


def test_evaluate_offline_is_deterministic():
    """The public wrapper, forced offline, matches the pure decision."""
    res = evaluate("EURUSD", "2026-07-02T13:30Z", offline=True)
    assert res["decision"] == "block"
    assert res["source"] == "bundled-csv"


def test_output_times_are_utc_iso():
    res = decide("EURUSD", parse_time("2026-07-02T13:30Z"), EVENTS)
    assert res["at"].endswith("+00:00")
    assert res["blocking_event"]["time"].endswith("+00:00")
    # blocking event time round-trips back to the same instant
    assert parse_time(res["blocking_event"]["time"]).tzinfo == timezone.utc
