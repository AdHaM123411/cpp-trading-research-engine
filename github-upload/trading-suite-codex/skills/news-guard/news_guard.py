#!/usr/bin/env python3
"""news-guard — event-blackout layer for a trading risk engine.

Given an instrument and a time, decide approve/block based on proximity to
high-impact economic events (FOMC, NFP, CPI, central-bank decisions...).
The classic "don't trade into the number" guard, as a callable function.

Data sources, in order:
  1. Live Forex Factory weekly calendar JSON (free, no API key):
     https://nfs.faireconomy.media/ff_calendar_thisweek.json
  2. Bundled offline fallback CSV (events.csv) when the network is unreachable.

Only HIGH-impact events trigger a blackout. The instrument is mapped to the
set of currencies/regions it is exposed to, and only events in that set count.

CLI:
    python3 news_guard.py --instrument EURUSD --at "2026-07-02T13:30Z"
    python3 news_guard.py --instrument SPY --at "2026-07-29T18:05Z" --alert

Programmatic:
    from news_guard import evaluate
    evaluate("EURUSD", "2026-07-02T13:30Z")  # -> dict
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BUNDLED_CSV = Path(__file__).resolve().parent / "events.csv"

# Default blackout window: 30 min before the event, 15 min after.
DEFAULT_BEFORE_MIN = 30
DEFAULT_AFTER_MIN = 15

# Currencies we know how to reason about.
KNOWN_CCYS = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY"}

# Non-FX instruments -> the currencies / regions whose high-impact prints move
# them. Equity indices are driven by US macro; crypto by US macro plus its own
# event stream (see CRYPTO_KEYWORDS).
INSTRUMENT_MAP = {
    # US equity indices / ETFs
    "SPY": {"USD"},
    "SPX": {"USD"},
    "ES": {"USD"},
    "US500": {"USD"},
    "QQQ": {"USD"},
    "NDX": {"USD"},
    "NQ": {"USD"},
    "US100": {"USD"},
    "DIA": {"USD"},
    "DJI": {"USD"},
    "US30": {"USD"},
    "YM": {"USD"},
    "IWM": {"USD"},
    "RUT": {"USD"},
    # Other regional indices
    "DAX": {"EUR"},
    "GER40": {"EUR"},
    "FTSE": {"GBP"},
    "UK100": {"GBP"},
    "NIKKEI": {"JPY"},
    "JP225": {"JPY"},
    # Metals (USD-denominated)
    "XAUUSD": {"USD"},
    "GOLD": {"USD"},
    "XAGUSD": {"USD"},
    "SILVER": {"USD"},
    # Crypto -> US macro sensitivity; crypto-specific events handled separately
    "BTC": {"USD"},
    "BTCUSD": {"USD"},
    "BTCUSDT": {"USD"},
    "XBTUSD": {"USD"},
    "ETH": {"USD"},
    "ETHUSD": {"USD"},
    "ETHUSDT": {"USD"},
    "SOL": {"USD"},
    "SOLUSD": {"USD"},
}

# Instruments that should ALSO blackout on crypto-specific high-impact events
# (e.g. a spot-ETF decision) regardless of the event currency tag.
CRYPTO_INSTRUMENTS = {
    "BTC",
    "BTCUSD",
    "BTCUSDT",
    "XBTUSD",
    "ETH",
    "ETHUSD",
    "ETHUSDT",
    "SOL",
    "SOLUSD",
}
CRYPTO_KEYWORDS = ("crypto", "bitcoin", "btc", "ethereum", "etf", "sec ")


@dataclass(frozen=True)
class Event:
    title: str
    currency: str
    impact: str
    when: datetime  # timezone-aware

    def to_public(self) -> dict:
        return {
            "title": self.title,
            "currency": self.currency,
            "impact": self.impact,
            "time": self.when.astimezone(timezone.utc).isoformat(),
        }


# --------------------------------------------------------------------------
# Time / instrument helpers
# --------------------------------------------------------------------------


def parse_time(value: str) -> datetime:
    """Parse an ISO-8601 time. Accepts a trailing 'Z'. Assumes UTC if naive."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def instrument_currencies(instrument: str) -> set[str]:
    """Map an instrument to the set of currencies whose events move it."""
    sym = instrument.upper().replace("/", "").replace("-", "").replace("_", "")
    if sym in INSTRUMENT_MAP:
        return set(INSTRUMENT_MAP[sym])
    # Straight 6-char FX pair, e.g. EURUSD -> {EUR, USD}
    if len(sym) == 6:
        base, quote = sym[:3], sym[3:]
        ccys = {c for c in (base, quote) if c in KNOWN_CCYS}
        if len(ccys) == 2:
            return ccys
    # Bare currency code
    if sym in KNOWN_CCYS:
        return {sym}
    # Unknown: fall back to US macro (the most broadly systemic driver) and
    # let the caller see the assumption in the reason string.
    return {"USD"}


def is_crypto(instrument: str) -> bool:
    sym = instrument.upper().replace("/", "").replace("-", "").replace("_", "")
    return sym in CRYPTO_INSTRUMENTS


# --------------------------------------------------------------------------
# Calendar loading (live, then bundled fallback)
# --------------------------------------------------------------------------


def _coerce_event(title, country, impact, when_raw) -> Optional[Event]:
    try:
        when = parse_time(str(when_raw))
    except (ValueError, TypeError):
        return None
    return Event(
        title=str(title).strip(),
        currency=str(country).strip().upper(),
        impact=str(impact).strip(),
        when=when,
    )


def load_from_forexfactory(timeout: float = 8.0) -> list[Event]:
    """Fetch the free, keyless Forex Factory weekly JSON. Raises on failure."""
    import requests  # imported lazily so offline use needs no network stack

    resp = requests.get(
        FF_URL, timeout=timeout, headers={"User-Agent": "news-guard/1.0"}
    )
    resp.raise_for_status()
    rows = resp.json()
    out: list[Event] = []
    for r in rows:
        ev = _coerce_event(
            r.get("title"), r.get("country"), r.get("impact"), r.get("date")
        )
        if ev:
            out.append(ev)
    return out


def load_from_csv(path: Path = BUNDLED_CSV) -> list[Event]:
    """Load the bundled offline fallback calendar."""
    out: list[Event] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(row for row in f if not row.lstrip().startswith("#"))
        for r in reader:
            ev = _coerce_event(
                r.get("title"), r.get("currency"), r.get("impact"), r.get("datetime")
            )
            if ev:
                out.append(ev)
    return out


def load_events(offline: bool = False) -> tuple[list[Event], str]:
    """Return (events, source). Falls back to the bundled CSV on any failure."""
    if not offline:
        try:
            events = load_from_forexfactory()
            if events:
                return events, "forexfactory"
        except Exception:
            pass  # fall through to the offline calendar
    return load_from_csv(), "bundled-csv"


# --------------------------------------------------------------------------
# Core decision
# --------------------------------------------------------------------------


def _relevant(event: Event, ccys: set[str], crypto: bool) -> bool:
    if event.impact.lower() != "high":
        return False
    if event.currency in ccys:
        return True
    if crypto:
        text = event.title.lower()
        return any(k in text for k in CRYPTO_KEYWORDS)
    return False


def decide(
    instrument: str,
    at: datetime,
    events: Iterable[Event],
    before_min: int = DEFAULT_BEFORE_MIN,
    after_min: int = DEFAULT_AFTER_MIN,
    source: str = "unknown",
) -> dict:
    """Pure decision function — no I/O. Block if `at` sits inside the blackout
    window of any relevant high-impact event."""
    ccys = instrument_currencies(instrument)
    crypto = is_crypto(instrument)
    relevant = sorted(
        (e for e in events if _relevant(e, ccys, crypto)), key=lambda e: e.when
    )

    before = timedelta(minutes=before_min)
    after = timedelta(minutes=after_min)

    blocking = None
    for ev in relevant:
        if ev.when - before <= at <= ev.when + after:
            blocking = ev
            break

    # Next relevant event at or after `at` (for context / countdown).
    upcoming = next((e for e in relevant if e.when >= at), None)
    next_event = upcoming.to_public() if upcoming else None
    minutes_until = (
        round((upcoming.when - at).total_seconds() / 60.0, 1) if upcoming else None
    )

    if blocking is not None:
        delta_min = round((blocking.when - at).total_seconds() / 60.0, 1)
        if delta_min > 0:
            timing = f"in {delta_min:g} min"
        elif delta_min < 0:
            timing = f"{abs(delta_min):g} min ago"
        else:
            timing = "now"
        reason = (
            f"BLOCK: {blocking.currency} {blocking.title} ({timing}) is inside the "
            f"{before_min}m-before/{after_min}m-after blackout for {instrument.upper()}."
        )
        return {
            "decision": "block",
            "reason": reason,
            "instrument": instrument.upper(),
            "currencies": sorted(ccys),
            "at": at.astimezone(timezone.utc).isoformat(),
            "blocking_event": blocking.to_public(),
            "next_event": next_event,
            "minutes_until": minutes_until,
            "source": source,
        }

    if next_event is None:
        reason = (
            f"APPROVE: no high-impact {'/'.join(sorted(ccys))} events found for "
            f"{instrument.upper()} in the loaded calendar."
        )
    else:
        reason = (
            f"APPROVE: next high-impact event ({next_event['currency']} "
            f"{next_event['title']}) is {minutes_until:g} min away — outside the "
            f"{before_min}m blackout for {instrument.upper()}."
        )
    return {
        "decision": "approve",
        "reason": reason,
        "instrument": instrument.upper(),
        "currencies": sorted(ccys),
        "at": at.astimezone(timezone.utc).isoformat(),
        "blocking_event": None,
        "next_event": next_event,
        "minutes_until": minutes_until,
        "source": source,
    }


def evaluate(
    instrument: str,
    at: str | datetime,
    before_min: int = DEFAULT_BEFORE_MIN,
    after_min: int = DEFAULT_AFTER_MIN,
    offline: bool = False,
) -> dict:
    """Convenience wrapper: load the calendar and decide."""
    at_dt = at if isinstance(at, datetime) else parse_time(at)
    if at_dt.tzinfo is None:
        at_dt = at_dt.replace(tzinfo=timezone.utc)
    events, source = load_events(offline=offline)
    return decide(instrument, at_dt, events, before_min, after_min, source)


# --------------------------------------------------------------------------
# Optional phone alert (opt-in, secrets from env only)
# --------------------------------------------------------------------------


def send_alert(result: dict) -> dict:
    """Send an SMS alert via Twilio on a block. Reads creds from env vars only:
        TWILIO_ACCOUNT_SID, (TWILIO_API_KEY + TWILIO_API_SECRET) or TWILIO_AUTH_TOKEN,
        TWILIO_FROM (sender number), TWILIO_ALERT_TO (recipient number).
    No secrets are stored in this file. Mirrors the auth pattern in
    ~/business-context/zero-one-restructure/twilio-outreach-setup.mjs.
    Returns a small status dict; never raises into the decision path.
    """
    import requests

    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    api_key = os.environ.get("TWILIO_API_KEY")
    api_secret = os.environ.get("TWILIO_API_SECRET")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_num = os.environ.get("TWILIO_FROM")
    to_num = os.environ.get("TWILIO_ALERT_TO")

    auth_user = api_key or sid
    auth_pass = api_secret if api_key else auth_token
    missing = [
        n
        for n, v in (
            ("TWILIO_ACCOUNT_SID", sid),
            ("TWILIO_FROM", from_num),
            ("TWILIO_ALERT_TO", to_num),
            ("TWILIO_API_SECRET/TWILIO_AUTH_TOKEN", auth_pass),
        )
        if not v
    ]
    if missing:
        return {"sent": False, "error": f"missing env: {', '.join(missing)}"}

    body = f"news-guard {result['decision'].upper()} {result['instrument']}: {result['reason']}"
    try:
        resp = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": from_num, "To": to_num, "Body": body[:1500]},
            auth=(auth_user, auth_pass),
            timeout=10,
        )
        resp.raise_for_status()
        return {"sent": True, "sid": resp.json().get("sid")}
    except Exception as exc:  # never let an alert failure break the guard
        return {"sent": False, "error": str(exc)}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="news_guard",
        description="Block trading around high-impact economic events.",
    )
    p.add_argument("--instrument", required=True, help="e.g. EURUSD, SPY, BTC")
    p.add_argument("--at", required=True, help='ISO time, e.g. "2026-07-02T13:30Z"')
    p.add_argument(
        "--before",
        type=int,
        default=DEFAULT_BEFORE_MIN,
        help=f"minutes before event (default {DEFAULT_BEFORE_MIN})",
    )
    p.add_argument(
        "--after",
        type=int,
        default=DEFAULT_AFTER_MIN,
        help=f"minutes after event (default {DEFAULT_AFTER_MIN})",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="skip the live feed, use the bundled CSV only",
    )
    p.add_argument(
        "--alert",
        action="store_true",
        help="on a block, send a Twilio SMS (creds from env vars)",
    )
    p.add_argument("--compact", action="store_true", help="single-line JSON")
    args = p.parse_args(argv)

    try:
        result = evaluate(
            args.instrument, args.at, args.before, args.after, offline=args.offline
        )
    except ValueError as exc:
        print(f"error: bad --at time: {exc}", file=sys.stderr)
        return 2

    if args.alert and result["decision"] == "block":
        result["alert"] = send_alert(result)

    print(json.dumps(result, indent=None if args.compact else 2))
    # Exit non-zero on a block so shell callers can gate on it.
    return 1 if result["decision"] == "block" else 0


if __name__ == "__main__":
    raise SystemExit(main())
