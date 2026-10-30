---
name: execution-safety
description: The safety gate between an AI agent and a real broker. The human-confirmation + hard-risk-limit middleware that means no order reaches a broker without (a) passing hard risk limits and (b) an explicit typed human confirmation. Forks the proven tastytrade-style ALLOW_TRADING=1 env gate + per-order confirm pattern: live trading is OFF by default, everything routes to paper until two locks open at once. Broker-agnostic — wraps alpaca-py / ib_async / ccxt behind adapter stubs, so the gate runs and is testable with no broker keys and no network. Every order runs a four-step pipeline (mode check, hard risk limits, typed confirmation, audit log) and returns {routed: paper|live|blocked, reason, audit_id}. The agent proposes; this gate decides.
---

# execution-safety

Install location: `~/.claude/skills/execution-safety/`.

The highest-leverage missing piece of an AI trading system. An agent that can
research, backtest and size a trade still should not be able to *send* one on its
own. This skill is the seam where a human stays in the loop: the agent proposes
an order, the gate decides whether it ever reaches a broker. The gap is the
point — proposal and execution are deliberately separated.

It forks a pattern that already works in production brokers (tastytrade's
`ALLOW_TRADING=1` env gate plus a per-order `confirm:true`) and mirrors the
`submitOrder(plan, {live, confirm})` contract already in trading-os
(`os/src/core/engine.ts`). Same shape, hardened: an env flag *and* a per-call
`live` flag *and* an exact typed confirmation, with hard risk limits in front of
all of it.

## Invocation

```bash
cd ~/.claude/skills/execution-safety

# Print the exact confirmation token a human must echo for a live order
python3 execution_safety.py --symbol SPY --side sell --qty 50 --type market --show-token
# -> CONFIRM SELL 50 SPY @ market

# Run an order through the gate (defaults to paper)
python3 execution_safety.py --symbol SPY --side sell --qty 50 --type market \
    --price 548 --stop 540 --atr 4 --profile risk_profile.example.json

# Attempt the live path (needs ALLOW_TRADING=1 in the shell + exact token)
ALLOW_TRADING=1 python3 execution_safety.py --symbol SPY --side sell --qty 50 \
    --type market --price 548 --stop 540 --atr 4 \
    --profile risk_profile.example.json --live \
    --confirm "CONFIRM SELL 50 SPY @ market"
```

From Python (the way an agent calls it):

```python
from execution_safety import guard_order, RiskProfile, Order

profile = RiskProfile.from_json("risk_profile.example.json")
order = Order(symbol="SPY", side="sell", qty=50, order_type="market",
              price=548.0, stop=540.0, atr=4.0)

result = guard_order(order, profile, live=True,
                     confirmation="CONFIRM SELL 50 SPY @ market")
# {"routed": "live"|"paper"|"blocked", "reason": ..., "audit_id": ...}
```

## The guard pipeline

Every order runs the same four steps, in order. First failure wins.

1. **Mode check.** Live requires `ALLOW_TRADING=1` in the environment **AND**
   `live=True` on the call. Both locks open or the order routes to **paper**.
   Default is paper. The agent cannot set the env flag mid-run — a human sets it
   in the shell.
2. **Hard risk limits.** The order is **blocked** if it breaches any limit in the
   `RiskProfile`: risk-per-trade over cap, projected open risk over the daily
   stop, no stop attached, stop closer than `min_stop_atr_mult`× ATR, notional
   over the max position, or symbol not on the allowlist. These run on paper
   orders too — a bad order is bad whether or not the capital is real.
3. **Typed human confirmation.** A live order must carry the exact confirmation
   token (e.g. `CONFIRM SELL 50 SPY @ market`). Any mismatch is **blocked**.
   Never auto-confirmed; the token is derived from the order so it can't be a
   stale copy-paste from a different order.
4. **Audit log.** Every decision — approved, paper, or blocked, with the reason —
   is appended as one JSON line to `audit_log.jsonl` (override with
   `EXECUTION_SAFETY_AUDIT`). Returns `{routed, reason, audit_id}`.

## RiskProfile schema

A plain dataclass, loadable from JSON (`risk_profile.example.json` included).
Fail-closed: an empty `symbol_allowlist` blocks everything.

| Field | Meaning |
|-------|---------|
| `account_equity` | Account equity, used to turn cash risk into a percentage. |
| `max_risk_per_trade_pct` | Reject if this order risks more than this % of equity. |
| `max_daily_loss_pct` | Reject if projected open risk would exceed the day's stop. |
| `current_open_risk_pct` | Risk already live across open positions (caller-supplied). |
| `max_position_notional` | Reject if `price * qty` exceeds this cash cap. |
| `min_stop_atr_mult` | Every order needs a stop, at least this many ATRs away. |
| `symbol_allowlist` | Only these symbols may trade. Empty = nothing allowed. |

## How live trading is unlocked (and why it's hard on purpose)

Three independent things must all be true before a single share moves:

1. `ALLOW_TRADING=1` is set in the shell environment — a human action, outside
   the agent's reach.
2. The caller passes `live=True`.
3. The caller passes the exact typed confirmation token for *that* order.

Miss the env flag → routes to paper. Miss the token → blocked. This is friction
by design. Paper is the default precisely because the cost of an accidental live
order is asymmetric: a missed paper trade is nothing, an erroneous live trade is
real money. The gate would rather refuse a good order than wave through a bad one.

## Broker adapters (stubs)

The gate is broker-agnostic. It hands a *cleared* order to a `BrokerAdapter`:

- `PaperAdapter` — the default sink; simulates a fill locally, touches nothing.
- `StubLiveAdapter` — stands in for a real broker; proves the gate routes a
  cleared order to the live path, but still simulates, so tests never transmit.

Real adapters wrap `alpaca-py` / `ib_async` / `ccxt` and are imported behind
`try/except`, so this module has zero hard broker dependencies and no keys are
ever required to run or test it. Swap `StubLiveAdapter` for a real adapter to
trade actual capital — the gate logic does not change.

## Worked example

```text
$ python3 execution_safety.py --symbol SPY --side sell --qty 50 --type market \
    --price 548 --stop 540 --atr 4 --profile risk_profile.example.json --live \
    --confirm "CONFIRM SELL 50 SPY @ market"

# ALLOW_TRADING not set -> paper:
paper   - Live requested but ALLOW_TRADING=1 is not set — routed to paper.

# Stop too wide (12.4% risk) with ALLOW_TRADING=1 -> blocked:
blocked - Risk 12.40% of equity exceeds the 1% per-trade cap; Projected open
          risk 12.40% exceeds the 3% daily stop.

# Wrong token with ALLOW_TRADING=1 -> blocked:
blocked - Live order requires exact confirmation 'CONFIRM SELL 50 SPY @ market'. Got 'go'.

# ALLOW_TRADING=1 + valid order + exact token -> live (stub adapter):
live    - Live order routed to stub adapter (simulated — connect a real broker SDK).
```

## Tests

`tests/test_execution_safety.py` proves the four core invariants plus extras:
(a) a live order with no `ALLOW_TRADING` routes to paper, (b) an order breaching
a risk limit is blocked, (c) a live order without the correct typed confirmation
is rejected, (d) a fully-valid confirmed live order passes the gate to the stub
adapter. No live order is ever transmitted — the live adapter is a local stub and
`ALLOW_TRADING` is set via test monkeypatch, never the real shell.

```bash
cd ~/.claude/skills/execution-safety && python3 -m pytest tests/ -q
# 9 passed
```

## Dependencies

Standard library only (`argparse`, `json`, `os`, `dataclasses`, `uuid`). No
credentials, no env vars required to run, no network. Broker SDKs are optional
and live behind adapter stubs. `pytest` only for the test suite.
