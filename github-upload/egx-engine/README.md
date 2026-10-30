# EGX weekly price ranking

C++17 collector and ranking engine for the completed EGX week of 18–22 October 2026. Ranking is `(close on October 22 / close on October 15 - 1) * 100`. Later candles are explicitly excluded. This is a historical screen, not a trading recommendation or a strategy backtest.

## Run

```sh
make test
./egx_rank collect .
./egx_rank rank .
```

The collector invokes the existing local TradingView MCP CLI as infrastructure. All new collection orchestration, date handling, validation, and ranking logic is C++. `vendor/json.hpp` is nlohmann/json v3.12.0 (MIT license included).

TradingView Desktop must be running with its local debug connection enabled. The collector uses the first chart pane, temporarily switches symbols and timeframe, then restores the starting symbol and timeframe. Do not change the chart or run a second collector while it is collecting. Existing cached captures are reused; raw JSON includes source, retrieval timestamp, symbol, currency, and timeframe. Errors are recorded in `data/collection-errors.jsonl`. Three consecutive capture failures stop the run.

## Sources and limitations

- `data/universe.json`: TradingView Egypt scanner response, filtered to `type=stock`, columns `name,description,currency,type`, range `0..1000`, sorted by name. Downloaded from `https://scanner.tradingview.com/egypt/scan`; the ranking rejects a truncated response or duplicate symbols.
- `data/universe.html`: public all-stocks page retained as supporting evidence; it displays only 100 rows and is not used as the complete universe.
- `data/bars/`: unmodified daily candle values from the desktop chart, wrapped with collection provenance. Data is delayed. This screen uses completed historical candles.
- Only EGP listings with valid OHLCV, a baseline candle, all five session candles, and positive reported volume at both endpoints qualify. Every other listing appears in the exclusions report. Never treat exclusions as zero-return stocks.
- Candle stability and symbol/timeframe are checked before saving. The source bridge does not expose a formally authenticated per-bar instrument identifier; independent provider reconciliation remains necessary before trading research is trusted.
- Prices reflect the chart's adjustment settings. Splits, dividends, rights issues, and historical listing membership have not been independently audited. Results are provisional price returns, not total shareholder returns. The directory reflects currently available listings and may omit securities delisted since the period.
- Volume totals are in shares, not EGP turnover. No liquidity filter, commission, spread, or slippage model is implied by this ranking.
- Selecting last week's winners and testing them on that same week introduces selection bias. Subsequent validation must use a point-in-time universe and periods after selection, or a rolling selection procedure with untouched out-of-sample results.

## Output

`output/ranking.json` includes ordered returns, coverage counts, and explicit exclusion reasons. `output/ranking.csv` is a compact export. Nothing connects to a broker or places orders. The risk, execution, strategy-audit, and backtesting engines are separate later work and are not implemented by this ranking executable.

## C++ hourly backtest (next onboarding step)

The broad ranking scan was stopped at the user's request. See `data/collection-status.json`: results cover an alphabetical subset, not the full market. `experiment.json` fixes the three selected symbols and one SMA 9/21 configuration before running the backtest.

```sh
make test
./egx_backtest capture .
./egx_backtest run .
```

`capture` collects up to 500 currently loaded hourly bars per selected symbol and restores the original chart. `run` excludes candles after October 22, validates timestamp ordering and OHLCV, then exports results to `output/backtest/`. It does not place orders. `backtest.cpp` reuses the C++ bridge and JSON helpers in `main.cpp` via the `EGX_LIBRARY` guard.

Each symbol has its own simulated EGP 100,000 account. SMA crossings use completed bars; market fills occur at the next observed open with 10 bps assumed adverse execution per side. Buy allocation is capped at 10% including fees, with whole shares and a previous-bar volume cap. Exits wait for two subsequent observed trading sessions and enough prior-bar volume; delayed exits remain pending. Current Thndr standard fees (including third-party fees) are applied as an illustrative schedule across the full history, assuming one transaction per fill. Fees may differ for actual accounts, split fills and historical dates.

The return includes the last-close value of any open position; win rate uses closed trades only. No terminal liquidation is invented. The benchmark invests 10% once with entry costs and marks to the same final close. Equity CSVs, trade CSVs, SVG charts, raw result JSON, a readable report and append-only trial records are exported. This is a research simulator, not exact Pine or broker parity: corporate actions, dividends, full holiday/session completeness, tick grids, opening liquidity and trading halts remain unverified. Selecting last week's winners makes this historical experiment selection-biased, not out-of-sample. No validated edge, audit pass or risk approval is claimed.
