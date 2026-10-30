# C++ Trading Research Engine

An Egyptian Exchange (EGX) research project developed with AI assistance. Research and paper simulation only; no live broker orders.

## Components

- **egx-engine/main.cpp**: C++17 historical weekly stock ranking and data validation.
- **egx-engine/backtest.cpp**: C++17 SMA crossover backtesting with fees, slippage, liquidity constraints, holding delays, trade records, and equity reports.
- **telecom_egypt_sma_strategy.pine**: TradingView Pine strategy source.
- **trading-suite-codex/**: 17 supporting research workflows and reference implementations. The bundled Python engines are reference material; their C++ replacements are not implemented or validated.
- **prepare_trading_suite.cpp**: Utility used to prepare the research workflows.

## Build and test

Requires a C++17 compiler and a POSIX environment (tested locally on macOS).

```sh
cd egx-engine
make test
```

The existing suite contains 9 ranking checks and 10 backtest checks. See [engine documentation](egx-engine/README.md) for collection and simulation commands. Collection requires a separately configured local TradingView MCP bridge; its paths currently reflect the original macOS setup.

Captured market datasets, generated reports, local audit logs, and compiled binaries are not included. Collection is required before running historical ranking or backtests.

## Research status

The strategy uses fixed moving-average rules, not a trained AI prediction model. Historical experiments have selection hindsight and do not establish a validated trading edge. Costs and execution behavior are simulation assumptions. See the engine documentation and [preparation status](trading-suite-codex/PREPARATION.md) for limitations.

Bundled third-party dependency notices are preserved in their respective folders.
