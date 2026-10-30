---
name: news-guard
description: Event-blackout layer for a trading risk engine. Given an instrument (EURUSD, SPY, BTC...) and a time, it decides approve/block based on proximity to high-impact economic events — the classic "don't trade into NFP / FOMC / CPI" guard. Fetches the free, keyless Forex Factory weekly calendar JSON and falls back to a bundled CSV of recurring events when offline. Maps the instrument to the currencies/regions it is exposed to, blacks out only HIGH-impact events inside a configurable window (default 30 min before, 15 min after), and returns {decision, reason, next_event, minutes_until}. Optional opt-in Twilio SMS on a block, with credentials read from env vars only.
---

# news-guard

Install location: `~/.claude/skills/news-guard/`.

An event-blackout guard for an AI trading system's risk engine. It answers one
question: *is now a safe time to trade this instrument, or is a high-impact
economic print about to hit?* It is the "don't trade into the number" rule made
into a callable function.

## Invocation

```bash
cd ~/.claude/skills/news-guard

# decide whether to trade EURUSD at a given time
python3 news_guard.py --instrument EURUSD --at "2026-07-02T13:30Z"

# force the offline bundled calendar (no network)
python3 news_guard.py --instrument SPY --at "2026-07-29T18:05Z" --offline

# widen the window, single-line JSON
python3 news_guard.py --instrument BTC --at "2026-07-14T12:30Z" --before 45 --after 30 --compact

# send a Twilio SMS if (and only if) the decision is block
python3 news_guard.py --instrument EURUSD --at "2026-07-02T13:30Z" --alert
```

Programmatic use from your risk engine:

```python
from news_guard import evaluate
res = evaluate("EURUSD", "2026-07-02T13:30Z")
if res["decision"] == "block":
    skip_trade(res["reason"])
```

The CLI also exits non-zero (`1`) on a block, so a shell caller can gate on it:
`python3 news_guard.py ... && place_trade`.

## What it does

1. **Loads the calendar.** Tries the live Forex Factory weekly JSON first
   (`https://nfs.faireconomy.media/ff_calendar_thisweek.json` — free, no API
   key). On any network/parse failure it falls back to the bundled
   `events.csv`, so it always returns a decision.
2. **Maps the instrument to currencies/regions** (see table below). Only events
   tagged to those currencies count.
3. **Filters to HIGH impact only.** Medium/Low events never trigger a blackout.
4. **Checks the blackout window.** If the query time sits inside
   `[event − before, event + after]` of any relevant high-impact event, it
   blocks; otherwise it approves.
5. **Optionally alerts.** With `--alert`, a block fires a Twilio SMS. Credentials
   come from env vars only — nothing is stored in the skill.

## Instrument → region mapping

| Instrument type | Example | Relevant events |
|---|---|---|
| FX pair (6-char) | `EURUSD` | both legs → EUR + USD high-impact |
| FX pair | `GBPJPY` | GBP + JPY |
| US index / ETF | `SPY`, `ES`, `QQQ`, `US30` | USD high-impact |
| Regional index | `DAX`, `FTSE`, `JP225` | EUR / GBP / JPY |
| Metals | `XAUUSD`, `GOLD` | USD high-impact |
| Crypto | `BTC`, `ETHUSD`, `SOL` | USD macro **plus** crypto-specific events (title contains crypto/bitcoin/ETF/SEC...) |
| Bare currency | `USD` | that currency |
| Unknown | anything else | defaults to USD (the broadest systemic driver) and says so in the reason |

Slashes, dashes and case are normalised (`eur/usd` == `EURUSD`).

## Blackout logic

- Window defaults: **30 min before → 15 min after** the event. Override with
  `--before` / `--after` (or the `before_min` / `after_min` args).
- A trade is **blocked** if its time falls inside the window of *any* relevant
  high-impact event.
- `next_event` / `minutes_until` always report the next relevant high-impact
  event at or after the query time, even on an approve, so the caller can see
  how much clear runway it has.

## Reading the output

```json
{
  "decision": "block",            // "block" | "approve"
  "reason": "BLOCK: USD US Non-Farm Payrolls (now) is inside the 30m-before/15m-after blackout for EURUSD.",
  "instrument": "EURUSD",
  "currencies": ["EUR", "USD"],  // what the instrument was mapped to
  "at": "2026-07-02T13:30:00+00:00",
  "blocking_event": { "title": "...", "currency": "USD", "impact": "High", "time": "..." },
  "next_event":     { "title": "...", "currency": "USD", "impact": "High", "time": "..." },
  "minutes_until": 0.0,           // minutes to next_event (signed: negative = just passed)
  "source": "forexfactory"       // or "bundled-csv" when offline
}
```

`source` tells you whether the decision used live data or the offline fallback —
useful to log so you know when the guard was running blind.

## Worked example

`EURUSD` at `2026-07-02T13:30Z`, using the bundled calendar (which pins US
Non-Farm Payrolls at that instant):

```
$ python3 news_guard.py --instrument EURUSD --at "2026-07-02T13:30Z" --offline
{
  "decision": "block",
  "reason": "BLOCK: USD US Non-Farm Payrolls (now) is inside the 30m-before/15m-after blackout for EURUSD.",
  ...
  "minutes_until": 0.0,
  "source": "bundled-csv"
}
# exit code 1
```

EURUSD maps to {EUR, USD}; NFP is a USD high-impact print landing exactly at the
query time, so the trade is blocked. The same instrument at `20:00Z` the same day
approves — the next high-impact USD event is days away.

## Optional Twilio alert

`--alert` sends one SMS on a block. It reads credentials from the environment
only (no secrets in any file), following the same auth pattern as Lewis's Twilio
setup at `~/business-context/zero-one-restructure/twilio-outreach-setup.mjs`:

```
TWILIO_ACCOUNT_SID=AC...            # required
TWILIO_API_KEY=SK... + TWILIO_API_SECRET=...   # preferred (scoped, revocable)
#   ...or TWILIO_AUTH_TOKEN=...     # fallback
TWILIO_FROM=+1...                   # sender number
TWILIO_ALERT_TO=+44...              # where the alert goes
```

If creds are missing the guard still returns its decision; the result just
carries `{"alert": {"sent": false, "error": "missing env: ..."}}`. An alert
failure never breaks the trading decision.

## Tests

```bash
cd ~/.claude/skills/news-guard
python3 -m pytest tests/ -q
```

The suite is fully offline (it uses the bundled CSV) and deterministic: it
asserts a known event window blocks, a quiet window approves, the
instrument→currency mapping, crypto handling, and custom windows. 9 tests.

## Dependencies

Python 3.11+ (uses `datetime.fromisoformat` with `Z` and `set[str]` syntax),
`requests` for the live feed only. Everything else is stdlib (`csv`, `json`,
`argparse`, `datetime`). No credentials in files; the only env vars read are the
optional `TWILIO_*` alert creds. Offline operation needs no network and no
`requests` import.
