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
