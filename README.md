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
uv run btest run strategies/ma_cross.py SPY --start 2016-01-01 --end 2025-01-01 \
    -p fast=30 -p slow=390 --slippage-bps 1
uv run btest report 1                       # rewrite data/reports/run-1.html
```

A strategy is a Python file with one `btest.strategy.Strategy` subclass. Each run is stored in
the Postgres `runs` schema (params, git commit, fills, daily equity, metrics) and gets an HTML
report under `data/reports/`.

## Fast path, parity, sweeps

```sh
uv run btest parity strategies/ma_cross.py SPY --start 2016-01-01 --end 2025-01-01
uv run btest sweep strategies/ma_cross.py SPY --start 2016-01-01 \
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

## Charts

Candlestick charts (TradingView's lightweight-charts) on every run page and in the Chart tab:
1m to 1D candles on New York session time, split- and dividend-adjusted like the backtests,
SMA / EMA / Bollinger overlays, and the run's fills as buy and sell markers. Indicators preset
from a strategy's params are set in minutes, so at 1m they equal what the strategy computed.
On Railway the web service has no bar files; it proxies `/api/candles` to the worker's private
bar service (`BTEST_BARS_URL`, shared `BTEST_INTERNAL_TOKEN`).

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
