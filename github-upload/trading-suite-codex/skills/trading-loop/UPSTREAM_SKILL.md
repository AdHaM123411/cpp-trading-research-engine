---
name: trading-loop
description: The self-learning loop that makes a paper-trading strategy get better month over month. Runs one closed cadence — hypothesis -> paper-trade for a window -> measure (win rate, expectancy, profit factor, max consecutive losses, Sharpe) -> loss-autopsy + pattern analysis -> adjust ONE variable -> keep/revert gate -> re-run. It orchestrates skills that already exist (trade-journal for logging/autopsy, autoresearch for the metric-defined loop, risk-manager for sizing) rather than reinventing them. Persists cycle state to a JSON file so the loop has memory: cycle history, what changed, what improved, what got reverted. Takes a supplied trade log so it runs offline with no live broker. numpy + stdlib only.
---

# trading-loop

Install location: `~/.claude/skills/trading-loop/`.

The orchestration layer for a strategy that learns. Most trading agents do one
thing on a trigger. This wraps yours in a loop that measures itself every month,
finds its biggest leak, changes exactly one thing, and only keeps the change if
the evidence says so. Built by Lewis Jackson for the Trading Suite.

It does **not** reinvent journalling, research design, or risk sizing — it calls
the skills that already do those:

- **`trade-journal`** — the per-trade schema (entry reason, rule compliance,
  emotional state), the weekly/monthly Performance Review, the Pattern Analyser
  (needs 20+ trades), and the Loss Autopsy whose whole job is to emit *one
  specific rule change*. trading-loop consumes that schema and reproduces the
  autopsy/pattern categories in code so the loop can run unattended.
- **`autoresearch`** — the plan → act → measure → keep-winners loop and, most
  importantly, its first step: turn a fuzzy goal into a measurable metric. The
  loop's `hypothesis` + `primary_metric` are that step made concrete.
- **`risk-manager` / `capital-allocator`** — sizing and circuit breakers. The
  loop's adjustable config (`risk_per_trade_pct`, `max_loss_R`) is the lever it
  hands back to those skills; on a losing streak it proposes the circuit-breaker
  move (halve risk) rather than inventing its own.

## Invocation

```bash
cd ~/.claude/skills/trading-loop

# 1. Define the falsifiable edge + the metric that proves it (autoresearch step)
python3 -m trading_loop.run init \
    --state cycle_state.json \
    --hypothesis "Disciplined London-session breakouts on BTC have positive expectancy" \
    --metric expectancy_R

# 2. Run one cycle over a paper-trade window (a trade-journal CSV for the period)
python3 -m trading_loop.run run --state cycle_state.json --trades window1.csv

# 3. Next month: run the next window. The gate keeps or reverts last month's change.
python3 -m trading_loop.run run --state cycle_state.json --trades window2.csv

# 4. See the history
python3 -m trading_loop.run show --state cycle_state.json
```

Run `--help` on any subcommand. `--metric` is one of the higher-is-better
metrics: `expectancy_R` (default), `profit_factor`, `sharpe`, `win_rate`.

## The 6-stage loop

One `run` call = one cycle over one window of trades.

1. **Hypothesis** — `init` records a falsifiable edge and the single metric that
   proves it. This is autoresearch's metric-definition step: "make money" is not
   a metric; `expectancy_R > 0` over a month is. The metric is the optimisation
   target the gate reads.
2. **Paper-trade window** — you supply the window: a CSV trade log (default
   cadence ~1 month / 20+ trades) in trade-journal's schema. Every trade carries
   its R multiple (or entry/stop/exit to derive it), session, setup, and rule
   compliance. *Offline by design — no broker keys, no network.*
3. **Measure** — `compute_metrics` produces the period tear-sheet: win rate,
   expectancy (avg R), profit factor, max consecutive losses, and per-trade
   Sharpe.
4. **Loss-autopsy + pattern** — `loss_autopsy` reproduces trade-journal's
   categories (psychology/discipline, timing, setup quality, risk management,
   market context), ranks them by *recoverable R*, and emits a specific rule
   change for the worst leak. The Pattern Analyser stats (expectancy by session
   and setup) feed the ranking; it flags when the window has fewer than the 20
   trades trade-journal wants for a stable read.
5. **Adjust — one variable only** — `propose_change` applies the single
   highest-impact change to the config and records it as an explicit diff
   (`from -> to`). **Hard rule: one variable per cycle.** You cannot attribute an
   improvement if you moved three knobs at once, so the loop refuses to. The
   change is enforced in `run_cycle` (at most one config key differs) and the
   test suite asserts it on every cycle.
6. **Gate + re-run** — next window runs under the proposed change. If the primary
   metric beats the previous accepted benchmark, the change is **kept** (folded
   into the accepted config, benchmark advances). If not, it is **reverted** and
   that variable is **locked** so the loop won't waste another cycle on it. The
   decision is logged and the next cycle begins.

### Decision gates, precisely

- Cycle 1 has no pending change → decision **`baseline`**: it sets the benchmark
  and proposes the first change.
- Every later cycle tests the pending change against the benchmark:
  - metric improved → **`keep`** (accepted config += the change; benchmark moves up)
  - metric did not improve → **`revert`** (accepted config untouched; variable
    added to `reverted_locks`)
- Then exactly one new change is proposed on top of the accepted config, skipping
  any locked variable. When there's no safe single-variable move left, the loop
  reports `none` — the strategy is clean for now.

> Sizing note: pure `risk_per_trade_pct` changes scale mean and volatility
> together, so they don't move ratio metrics like expectancy_R or Sharpe — they
> manage drawdown and ruin, which is correct. The metric-moving changes are the
> *filters* (drop the losing session/setup, enforce discipline) and the loss cap.
> The loop proposes the risk cut only as a circuit-breaker on a loss streak.

## Cycle-state file format

JSON, written/appended every cycle. This is the loop's memory.

```jsonc
{
  "schema": "trading-loop/1",
  "hypothesis": "Disciplined London-session breakouts on BTC have positive expectancy",
  "primary_metric": "expectancy_R",
  "accepted_config": {           // the currently-trusted config
    "risk_per_trade_pct": 1.0,
    "require_rule_compliance": true,
    "allowed_sessions": null,
    "allowed_setups": null,
    "max_loss_R": null
  },
  "active_config": { ... },      // accepted_config + the pending change (runs next window)
  "pending_change": {            // the one change under test
    "variable": "risk_per_trade_pct", "from": 1.0, "to": 0.5,
    "category": "market_context", "rationale": "...", "rule_change": "..."
  },
  "benchmark": { "metric": "expectancy_R", "value": -0.409 },
  "reverted_locks": [],          // variables tried and rejected — never re-proposed
  "cycles": [
    {
      "cycle": 1,
      "window_trades": 22, "taken_trades": 22,
      "config_tested": { ... },
      "metrics": { "expectancy_R": -0.409, "win_rate": 0.455, "profit_factor": 0.62,
                   "max_consecutive_losses": 12, "sharpe": -0.22, "total_R": -9.0 },
      "gate": { "decision": "baseline", "compared": null },
      "autopsy": { "top_findings": [ ... ], "pattern_note": "..." },
      "change_proposed": { "variable": "require_rule_compliance", "from": false, "to": true, ... },
      "accepted_config_after": { ... }
    }
  ]
}
```

## Worked example — one full cycle (real output)

Window 1 = 22 logged trades: disciplined London breakouts that net positive, plus
8 undisciplined "revenge" trades in the NY session that each lost 2.5R.

**Cycle 1 (baseline):**

```
expectancy -0.409R | win 45.5% | PF 0.62 | maxConsecLoss 12 | Sharpe -0.22 | total -9.00R
GATE       : BASELINE  (sets the benchmark)
autopsy    : [psychology] 8 losing trades broke the plan, costing 20.00R (recoverable 20.00R)
NEXT CHANGE: require_rule_compliance: False -> True
  rule      : Only take trades that pass the pre-trade checklist (rule_compliance=True).
```

The autopsy's biggest leak is discipline, so the loop changes exactly one thing —
`require_rule_compliance` False → True — and waits for the next window's evidence.

**Cycle 2 (gate fires)** on window 2 (the next month, same edge), now running the
discipline filter:

```
window     : 23 logged / 16 taken under tested config
expectancy +0.650R | win 68.8% | PF 3.08 | maxConsecLoss 5 | Sharpe 0.57 | total +10.40R
GATE       : KEEP  (expectancy_R +0.650 vs -0.409 -> improved)
NEXT CHANGE: risk_per_trade_pct: 1.0 -> 0.5   (circuit breaker on the 5-loss streak)
```

Expectancy went from **−0.409R to +0.650R**, so the gate **keeps** the discipline
filter, advances the benchmark, and proposes the next single change. Had the
metric not improved, the gate would have printed `REVERT`, restored the accepted
config, and locked `require_rule_compliance` out of future proposals. That keep /
revert decision is the whole point: the strategy only carries changes the data
earned.

## Tests

```bash
cd ~/.claude/skills/trading-loop
python3 -m pytest tests/ -q
```

`tests/test_trading_loop.py` runs full cycles on synthetic windows and asserts:
the cycle-state file is written; cycle 1 is a `baseline` that proposes one change;
a second window produces a `keep`/`revert` gate decision persisted to disk; `keep`
fires when the filter improves expectancy and `revert` locks a variable that
doesn't; and the one-variable-at-a-time rule holds on every cycle. 5 passing.

## Dependencies

Python 3.10+, `numpy`, and the standard library (`csv`, `json`, `copy`,
`argparse`). No credentials, no env vars, no network. License-clean.
