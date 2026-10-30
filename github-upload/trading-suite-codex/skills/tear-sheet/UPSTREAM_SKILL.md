---
name: tear-sheet
description: Turns a trade log or equity curve into a professional performance tear-sheet (self-contained HTML + PNG snapshot) — the "how am I actually doing" report for a trading system. Thin wrapper over QuantStats (Apache-2.0). Accepts daily returns, an equity/balance curve, or a trade-by-trade PnL log; auto-detects which shape you gave it and converts to a clean daily returns series. Renders cumulative returns, drawdown, monthly-returns heatmap, and the headline stats (Sharpe, Sortino, CAGR, max drawdown, win rate, volatility). Pass a benchmark (CSV or a ticker like SPY) for relative metrics.
---

# tear-sheet

Install location: `~/.claude/skills/tear-sheet/`.
Built by Lewis Jackson as a Claude Code skill. The heavy lifting is done by
[QuantStats](https://github.com/ranaroussi/quantstats) (Apache-2.0,
license-clean to ship); this skill is the input-shape detection and CLI around
it.

## What it does

Give it a CSV of your track record. It works out whether the numbers are
returns, an equity curve, or trade PnL, turns them into a clean daily returns
series, and writes:

- a **self-contained HTML tear-sheet** — cumulative returns, drawdown periods,
  monthly-returns heatmap, rolling Sharpe, and a full metrics table; and
- a **PNG snapshot** of the key panel (cumulative returns + drawdown + daily
  returns) for pasting into a message or doc.

## Install

Inside the skill directory (uses `uv`, mirrors the other skills here):

```bash
cd ~/.claude/skills/tear-sheet
uv sync                 # creates .venv with quantstats + deps
```

Or with plain pip into any environment:

```bash
pip install quantstats
```

If QuantStats isn't installed the skill stops with a clear message telling you
to run `pip install quantstats` — it does not try to limp on without it.

## Invocation

```bash
cd ~/.claude/skills/tear-sheet

# the common case: point it at a CSV, get report.html + report.png
.venv/bin/python -m tearsheet --input trades.csv --out report.html

# force the input type if auto-detection guesses wrong
.venv/bin/python -m tearsheet --input curve.csv --type equity --out report.html

# trade PnL in dollars, with a starting capital so returns are honest
.venv/bin/python -m tearsheet --input pnl.csv --type pnl --capital 25000 --out report.html

# add a benchmark for relative metrics (a CSV path, or a ticker yfinance knows)
.venv/bin/python -m tearsheet --input trades.csv --benchmark SPY --out report.html
```

Flags: `--input/-i`, `--out/-o`, `--png` (defaults to the HTML path with a
`.png` suffix), `--type {returns,equity,pnl}`, `--date-col`, `--value-col`,
`--capital` (PnL only, default 10000), `--benchmark/-b`, `--title`.

## Accepted input formats

A CSV with a date column and one numeric value column. The value column is read
as one of three shapes:

1. **Daily / per-period returns** — e.g. `0.012`, `-0.004`. If they look like
   percent (typical move > 1.5), they're rescaled by 100.
2. **Equity / balance curve** — account value over time, e.g.
   `10000, 10120, 10080, ...`. Converted to returns via percentage change.
3. **Trade-by-trade PnL** — dollars won/lost per trade, e.g. `+320, -110`.
   Converted to returns against a running equity that starts at `--capital`.
   Multiple trades on the same day are compounded into one daily return.

Detection uses the column name first (`equity`/`balance`/`nav` → equity,
`pnl`/`profit` → PnL, `return`/`ret`/`%` → returns) and falls back to the shape
of the numbers. Override with `--type`, `--date-col`, `--value-col` whenever the
guess is wrong.

## How to read the output

Plain-English first, the textbook term after.

- **How much you made overall, end to end** — *total return* (and **CAGR**, the
  same thing expressed as a smoothed yearly rate so you can compare across
  periods of different length).
- **Return per unit of stomach-churn** — how much return you got for the size of
  the swings you sat through. Higher is better; above 1 is decent, above 2 is
  strong. Term: **Sharpe ratio**.
- **Return per unit of *downside* only** — like Sharpe, but it only counts the
  losing swings against you, not the upside volatility (which you don't mind).
  Usually higher than Sharpe. Term: **Sortino ratio**.
- **The worst peak-to-trough fall** — the biggest drop from a high-water mark to
  the bottom before a new high. This is the pain number; it's what actually
  makes people quit a system. Shown as a negative percent. Term: **maximum
  drawdown**.
- **How often a period was green** — the share of days/trades that made money. A
  high win rate with a small average win can still lose overall, so read it next
  to the returns, not on its own. Term: **win rate**.
- **How jumpy the returns are** — the spread of the return swings, annualised.
  Higher means a wilder ride. Term: **volatility**.

If you pass a benchmark, the report adds relative numbers (alpha, beta, and the
strategy plotted against the benchmark) so you can see whether you actually beat
just holding it.

## Worked example

A 53-row sample trade log ships in `tests/sample_trades.csv` (dates + dollar
PnL):

```bash
cd ~/.claude/skills/tear-sheet
.venv/bin/python -m tearsheet --input tests/sample_trades.csv \
    --out /tmp/report.html --png /tmp/snap.png
```

Output:

```
[tearsheet] detected=pnl; date_col='date'; value_col='pnl'; periods=54; range=2023-01-03..2023-12-27

Tear-sheet written:
  HTML : /tmp/report.html
  PNG  : /tmp/snap.png

Headline metrics
  Period       : 2023-01-03 -> 2023-12-27 (54 periods)
  Total return : 55.51%
  CAGR         : 685.05%
  Sharpe       : 5.93
  Sortino      : 12.48
  Max drawdown : -3.44%
  Volatility   : 35.92%
  Win rate     : 57.41%
```

(The eye-watering CAGR is the usual small-sample artefact — annualising a great
year of sparse trades. The tear-sheet itself shows the honest cumulative curve
and drawdowns; read those, not just the headline rate.)

The HTML is fully self-contained (charts inlined) so it opens anywhere, and the
PNG is the key panel for a quick paste.

## Tests

```bash
cd ~/.claude/skills/tear-sheet
.venv/bin/python -m pytest tests/ -q
```

Nine tests: input-shape detection for all three formats (returns / equity /
PnL), percent-vs-fractional rescaling, capital-based PnL conversion, same-day
compounding, error paths, and one end-to-end render that asserts a real
non-empty HTML and PNG land on disk.

## Dependencies

`uv`-managed `.venv/`, Python 3.10–3.12: `quantstats`, `numpy`, `pandas`,
`matplotlib` (`pytest` optional). No credentials, no env vars. Network is only
touched if you pass a benchmark *ticker* (QuantStats fetches it from Yahoo
Finance via yfinance); a benchmark *CSV* and the core report are fully offline.
