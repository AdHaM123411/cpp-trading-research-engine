---
name: alpha-combine
description: The 11-step institutional alpha-combination engine from the Quant Maths article. Takes a matrix of per-period signal returns (or implied probabilities), serially demeans, normalises, cross-sectionally demeans, regresses out shared variance, and assigns each signal a mathematically optimal weight proportional to its independent edge and inversely to its noise. Reports the effective number of independent signals, implied information ratio (IR = IC x sqrt(N)), a combined "mega-alpha" series, and an uncertainty-adjusted empirical Kelly fraction. Prediction-market mode included.
---

# alpha-combine

Install location: `~/.claude/skills/alpha-combine/`.
Author of the underlying framework: Roan (@RohOnChain), "The Math Behind
Combining 50 Weak Signals Into One Winning Trade". Built as a Claude Code
skill by Lewis Jackson, ahead of the Quant Maths video, directly from the
article's verbatim 11-step procedure.

## Invocation

```
cd ~/.claude/skills/alpha-combine
# combine an arbitrary signal-return matrix (index=date, columns=signals)
uv run python -m alpha_combine.run --csv signals.csv --ic 0.05

# demo: build the classic BTC signal families and combine them
uv run python -m alpha_combine.run --ticker BTC-USD --years 10 --ic 0.05

# prediction-market mode (article Part 5: probability inputs)
uv run python -m alpha_combine.run --csv probs.csv --prediction-market
```

## What it computes (article Part 3, verbatim)

1. Collect R(i,s) per signal i, period s
2. Serial demean: X = R − mean_s R
3. Sample variance σ(i)²= (1/M)ΣX²
4. Normalise Y = X/σ
5. Drop most recent observation (no look-ahead)
6. Cross-sectional demean Λ = Y − mean_j Y
7. Drop one more period (look-ahead hygiene)
8. Expected forward return E = d-day MA of R; E_norm = E/σ
9. Residual after removing shared variance with Λ (independent edge)
10. w(i) = η·ε(i)/σ(i)
11. Normalise so Σ|w| = 1

Outputs: weight per signal, **effective independent-signal count**
(participation ratio — the N that belongs in IR = IC·√N, not the raw count),
implied IR, combined signal series, and empirical Kelly
`f = f_kelly·(1 − CV_edge)` with CV_edge from a 10,000-path bootstrap.

## Step 9 note

The article states Step 9 in prose and it is dimensionally ambiguous for
small stacks. We implement its stated purpose: project the expected-return
vector off the shared cross-signal variance directions (PCs of the signal
correlation matrix with eigenvalue > 1) and keep the residual. Exact for
independent signals (no shrinkage); shrinks duplicated/redundant signals
toward zero weight. Documented inline in `engine.py`.

## Role in the synthesised BTC strategy

This is Layer 3 (conviction combination). The orchestrator feeds it the LSTM
directional probability + the Markov `signal_from_matrix` scalar + the three
classic families. Steps 6 & 9 measure the LSTM's *marginal independent edge*
over momentum/mean-reversion and auto-down-weight it if redundant — the
series' own anti-double-counting mechanism. See
`~/.claude/plans/alright-if-we-were-jiggly-candle.md`.

## Dependencies

`uv`-managed `.venv/`, Python 3.12: `yfinance`, `numpy`, `pandas`
(`pytest` optional for the test suite). No credentials, no env vars, no
network beyond `yfinance` → Yahoo Finance.
