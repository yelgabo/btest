# btest

Minute-bar backtesting for Python trading strategies. Design:
[docs/superpowers/specs/2026-10-01-btest-design.md](docs/superpowers/specs/2026-10-01-btest-design.md).

## Setup

```sh
cp .env.example .env        # add Alpaca paper keys
createdb btest
uv sync
uv run btest migrate
```

## Data

```sh
uv run btest ingest                         # backfill, then incremental on later runs
uv run btest check-adjust                   # compare adjusted bars with Alpaca's
uv run btest bars NVDA 2024-06-07T19:50 2024-06-10T13:35
uv run pytest
```

Symbols and history start live in `btest.toml`. Bars are stored under `data/bars/` as Parquet,
raw and unadjusted; corporate actions and the NYSE calendar live in Postgres.

## Backtests

```sh
uv run btest run strategies/trend/ma_cross.py SPY --start 2016-01-01 --end 2025-01-01 \
    -p fast=30 -p slow=390 --slippage-bps 1
uv run btest report 1                       # rewrite data/reports/run-1.html
```

A strategy is a Python file with one `btest.strategy.Strategy` subclass. Each run is stored in
the Postgres `runs` schema (params, git commit, fills, daily equity, metrics) and gets an HTML
report under `data/reports/`.

## Fast path, parity, sweeps

```sh
uv run btest parity strategies/trend/ma_cross.py SPY --start 2016-01-01 --end 2025-01-01
uv run btest sweep strategies/trend/ma_cross.py SPY --start 2016-01-01 \
    -g fast=5,10,30,60 -g slow=60:2340:60
```

`signals()` must give the same fills as `on_bar()`; `btest parity` checks that on real data.
Sweeps stop at `holdout_start` in `btest.toml`. Confirm a chosen setting on the holdout once
with `btest run`; it warns how many times that strategy has already looked at the holdout.

## UI

```sh
uv run btest ui                             # http://127.0.0.1:8765
```

Read-only workbench over the runs and sweeps in Postgres: runs table, run detail (equity,
drawdown, monthly returns, fills), compare up to four runs, sweep parameter maps, data status.

## Strategy lab (website)

The Strategies tab is an editor: file tree (folders come from `/` in names), tabs, Cmd/Ctrl+P
to jump, Cmd/Ctrl+S to save (every changed save is a new version), Cmd/Ctrl+Enter to run.
Runs and sweeps are queued in `lab.job` and executed by `btest worker`, each in a child process
that connects as the restricted `btest_runner` role and has a time limit. `btest
import-strategies` copies `strategies/*.py` into the lab.

## Strategies and indicators

| Strategy | Bars | Idea |
|---|---|---|
| `trend/ma_cross` | 1m | Fast / slow moving-average crossover |
| `mean_reversion/zscore` | 1m | Buy stretches below the rolling mean, sell on the snap back |
| `mean_reversion/rsi2` | 1D | Connors RSI(2) pullbacks inside a 200-day uptrend |
| `trend/sma_200` | 1D | Hold above the moving average, cash below |
| `trend/momentum_12m` | 1D | Hold while the 12-month return beats a hurdle, checked monthly |
| `risk/vol_target` | 1D | Always invested, sized to a target volatility |
| `intraday/opening_range` | 5m | Buy a break of the first 30 minutes' high, flat by 15:50 |

Indicators: `rsi`, `zscore`, `vwap`, `atr`, `volatility`, `roc`.

## Portfolio strategies

A strategy with a `decide(as_of, data)` method (start from `strategies/templates/portfolio.py`)
holds several symbols and trades on the live system's schedule: one decision per scheduled
session at 15:30 New York time on data through the 15:14 bar (the free SIP feed is 15 minutes
behind), orders filling at the 15:45 bar's open. Half days shift with the close. It declares
`universe = [...]` and `rebalance = "daily" | "weekly" | "month_end" | "month_start"` and
returns target weights, `Targets(...)` with option contracts, or `None` for no change.

The portfolio engine trades like a cash account: notional orders, sells before buys, no
leverage, fractional shares (on by default), idle cash earning the 3-month T-bill rate (on by
default), written puts fully secured by cash and assigned at expiry. Benchmark: SPY or 60/40.

```sh
uv run btest run strategies/portfolio/trend_gtaa.py --start 2016-01-01 --end 2025-01-01
uv run btest ingest-options XLF EEM          # monthly puts + 30-minute bars, Feb 2024 on
uv run btest run strategies/options/put_write.py --start 2024-02-01 --end 2025-01-01
```

| Strategy | Rebalance | Idea |
|---|---|---|
| `baseline/buy_hold` | once | All in one symbol, held |
| `portfolio/trend_gtaa` | month end | Five asset classes, each held only above its 10-month average |
| `portfolio/dual_momentum` | month end | US or international stocks, whichever is stronger, else bonds |
| `portfolio/sector_momentum` | month end | Top 3 sector ETFs by 6-month return, cash below SPY's 200-day |
| `mean_reversion/rsi2_basket` | daily | RSI(2) pullbacks across SPY, QQQ, IWM, DIA |
| `calendar/turn_of_month` | daily | SPY from the last session of a month to the third of the next |
| `risk/risk_parity` | month end | Stocks, bonds, gold by inverse volatility at a 10% vol target |
| `options/put_write` | daily | Cash-secured monthly puts on XLF |

Sweeps of portfolio strategies wait for a portfolio fast path.

## Live trading (Alpaca paper)

The worker trades enabled deployments on the same timing: 15:30 refresh bars and run
`decide()` in the sandboxed child (no broker keys), 15:45 sell then buy, 16:15 read fills back
and compare each with the backtest's fill price. A kill switch disables a deployment after a
daily loss beyond `max_daily_loss`; orders above `max_order` x capital are refused. Strategies
see cash capped at the deployed capital even when the account holds more.

```sh
uv run btest live configure-account          # no margin, no shorting
uv run btest live deploy gtaa portfolio/trend_gtaa --capital 20000
uv run btest live decide gtaa --session 2026-10-02   # dry run: targets and orders
uv run btest live enable gtaa
uv run btest live list
```

## Timeframes

A strategy sets `timeframe = "1D"` (or `5m`, `15m`, `30m`, `1h`; default `1m`). The runner,
the fast path, sweeps and parity all build those bars from the minute data with the same
session bucketing as the charts, so windows in `params` count bars of that size, decisions
happen at each bar's close and orders fill at the next bar's open. Run pages open their chart
on the strategy's timeframe, where its indicators match exactly. Example:
`strategies/trend/sma_200.py`.

## Charts

Candlestick charts (TradingView's lightweight-charts) on every run page and in the Chart tab:
1m to 1D candles on New York session time, split- and dividend-adjusted like the backtests,
SMA / EMA / Bollinger overlays, and the run's fills as buy and sell markers. The chart loads
about 3,000 candles around the Go to date and fetches more as you scroll toward either edge
(capped at 400,000 loaded candles per chart). Indicators preset
from a strategy's params are set in minutes, so at 1m they equal what the strategy computed.
On Railway the web service has no bar files; it proxies `/api/candles` to the worker's private
bar service (`BTEST_BARS_URL`, shared `BTEST_INTERNAL_TOKEN`).

## Custom indicators

The Indicators section of the lab holds Python indicators (`btest.indicator.Indicator`):
`params`, `pane = "price" | "own"`, optional `levels`, and `compute(self, c)` returning
`{line: array}`. Opening one shows a live preview; any chart can add them from "Add
indicator". The worker computes them in a child process that gets only the candles on stdin
(no database URL, no secrets, 20 s limit). Starters live in `indicators/` and are added by
`btest import-strategies`.

## Deployment (Railway)

Project `btest`: `Postgres`, `web` (UI and API) and `worker` (lab jobs, Parquet bars on the
`/data` volume, nightly ingest at 22:00 UTC on weekdays). One image; `BTEST_ROLE=worker`
selects the worker.

- Live: https://web-production-584c0.up.railway.app (HTTP basic auth, any username, password
  is `BTEST_UI_PASSWORD` in `.env` and on the web service).
- Deploy: `railway up --service web --detach` and `railway up --service worker --detach`.
  Not hooked to GitHub; pushing does not deploy.
- The website signs in with `BTEST_UI_PASSWORD` (login page, 14-day cookie).
- Railway Postgres is the main database. The local CLI writes runs and sweeps to it through
  the public TCP proxy (`DATABASE_URL` in `.env`), so new results appear on the site.
- Parquet bars stay on this machine. `btest ingest` refreshes `market.coverage`, which the
  Data page reads; `btest coverage` refreshes it alone.
