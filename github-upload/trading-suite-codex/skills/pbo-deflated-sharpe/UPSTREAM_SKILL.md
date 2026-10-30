---
name: pbo-deflated-sharpe
description: The three overfitting checks that catch backtests that lie. Takes a backtest's trial results and answers one question — is this edge real, or did you curve-fit it? Runs Probability of Backtest Overfitting (PBO, via combinatorially-symmetric cross-validation), the Deflated Sharpe Ratio (DSR, the probability the Sharpe is real after accounting for how many configurations you tried), and the Probabilistic Sharpe Ratio (PSR). Input A is a matrix of per-period returns, one column per parameter/strategy trial, and it returns PBO%. Input B is the chosen strategy's return series plus the array of every trial's Sharpe, and it returns the DSR. Outputs a plain-English pass/fail verdict. numpy + stdlib only, clean-room from the Bailey / Lopez de Prado papers.
---

# pbo-deflated-sharpe

Install location: `~/.claude/skills/pbo-deflated-sharpe/`.

The maths is lifted verbatim from the trading-os validation engine, which is
itself clean-room from the public Bailey / Lopez de Prado papers ("The
Probability of Backtest Overfitting" and "The Deflated Sharpe Ratio"). No
scipy — the normal CDF and its inverse are computed by hand. The skill is
self-contained: it depends only on `numpy` and the standard library.

## What it does

You ran a backtest. You tried a bunch of parameter settings and picked the best
one. The number looks great. The problem: if you try enough settings, one of
them will look great by pure luck — and that luck does not repeat with real
money. These three checks tell you whether your result survives that scrutiny.

- **PBO** — feed it the full grid of trials (every parameter set you tested) and
  it estimates how often the best-in-sample config flips to below-average
  out-of-sample. High = you curve-fit.
- **DSR** — feed it your chosen strategy's returns plus every trial's Sharpe,
  and it gives the probability the true Sharpe is above zero *after* penalising
  you for how many configurations you tried.
- **PSR** — the same probability without the trial penalty. Shown for contrast.

## Invocation

```bash
cd ~/.claude/skills/pbo-deflated-sharpe

# Input A — a matrix of per-period returns, one column per parameter/strategy
# trial, one row per period (CSV, optional header). Runs PBO.
uv run python -m pbo_deflated_sharpe.run --matrix trials.csv

# Input B — the chosen strategy's return series + every trial's Sharpe. Runs DSR.
uv run python -m pbo_deflated_sharpe.run --returns chosen.csv --sharpes sharpes.csv

# Both at once. With only --matrix, the per-column Sharpes become the trial set
# and the best in-sample column is treated as the chosen strategy.
uv run python -m pbo_deflated_sharpe.run --matrix trials.csv

# Built-in demo: one overfit case, one genuine case, no files needed.
uv run python -m pbo_deflated_sharpe.run --demo
```

Or call the functions directly:

```python
import numpy as np
from pbo_deflated_sharpe import cscv_pbo, deflated_sharpe, probabilistic_sharpe, verdict

pbo = cscv_pbo(trial_matrix)            # T periods x N trials -> float in [0,1]
dsr = deflated_sharpe(chosen_returns, all_trial_sharpes)  # -> probability in [0,1]
print(verdict(pbo=pbo, dsr=dsr))        # plain-English pass/fail
```

## Inputs it accepts

- **Trial matrix (for PBO):** a 2-D array, rows = periods, columns = each
  strategy/parameter-config you tested. CSV with or without a header row, or a
  numpy array. Needs at least 2 columns and enough rows for the CSCV split
  (default `--S 8` partitions, so 16+ rows minimum; hundreds is healthier).
- **Chosen return series (for DSR/PSR):** a 1-D array of the selected strategy's
  per-period returns. Needs 8+ observations.
- **Trial Sharpes (for DSR):** a 1-D array holding the Sharpe of every config you
  tried. The more trials, the harder DSR is to pass — that is the point.

## How to read the output

- **PBO < 50% = pass.** The best-looking config still beats the median
  out-of-sample more often than not, so the result is probably not just
  curve-fit. PBO ≥ 50% means the winner reverts out-of-sample — treat the
  headline number as noise.
- **DSR > 0.95 = strong.** There's a 95%+ chance the true Sharpe is above zero
  once you account for the number of trials. Below that, the apparent edge may
  just be the best of many coin-flips.
- The verdict line combines them: it only says `pass` when every check you ran
  passes.

## Glossary (plain explanation first, then the term)

- **How often the best backtest setting stops working once you stop cherry-picking it** — that is the *Probability of Backtest Overfitting (PBO)*. It splits your trial history into blocks, repeatedly picks the best config on one half and checks where it ranks on the other half, and reports the fraction of splits where the in-sample winner lands below the out-of-sample median. The method is *combinatorially-symmetric cross-validation (CSCV)* — it tries every balanced way of splitting the blocks, so a single lucky split can't flatter the result.
- **The chance your Sharpe ratio is real once you've been honest about how many settings you tried** — that is the *Deflated Sharpe Ratio (DSR)*. Try 1,000 random strategies and the best will show a fat Sharpe by luck alone; DSR raises the bar in proportion to the number and spread of trials, then asks how likely the true Sharpe still clears zero.
- **The chance your Sharpe is above zero given the track-record length and the shape of the returns, before any trial penalty** — that is the *Probabilistic Sharpe Ratio (PSR)*. It corrects a raw Sharpe for short samples and for fat tails / skew. DSR is PSR measured against a higher, trials-aware benchmark instead of zero.

## Worked example

```bash
$ uv run python -m pbo_deflated_sharpe.run --demo
```

Demo 1 builds 40 trials where each config gets one big return spike in a single
time block and is pure noise elsewhere — a textbook curve-fit. The best
in-sample config only won because its spike landed in-sample; out-of-sample it
reverts:

```
  PBO (prob. of backtest overfitting) : 100.0%
  DSR (deflated Sharpe, prob. real)   :  0.193  (deflated over 40 trials)
  PBO 100% — FAIL. The best-looking config flips to below-median out-of-sample
             most of the time — this looks overfit. Treat the result as noise.
  DSR 0.19 — WEAK. After deflating for the number of trials, the chance the true
             Sharpe is above zero is only 19%.
  VERDICT: FAIL
```

Demo 2 is a genuine upward drift tested with only five low-variance trials:

```
  PSR (prob. Sharpe > 0, no deflation):  1.000
  DSR (deflated Sharpe, prob. real)   :  0.999  (deflated over 5 trials)
  DSR 1.00 — STRONG. After deflating for the number of trials, there is a 100%
             chance the true Sharpe is above zero.
  VERDICT: PASS
```

Same Sharpe-sized number, opposite verdicts — because one was the best of 40
coin-flips and the other was a real edge tested honestly.

## Tests

```bash
cd ~/.claude/skills/pbo-deflated-sharpe
uv run pytest -q
```

Covers: PBO is high on a structurally-overfit matrix, DSR is high on a genuine
series, deflation never increases the probability versus PSR, and the hand-rolled
normal CDF/PPF match known values.

## Dependencies

`uv`-managed `.venv/`, Python 3.10+: `numpy` only (`pytest` for the test suite).
No credentials, no env vars, no network. License-clean to bundle and ship.
