# Replication files for the OLPS paper review

Scripts and inputs behind `../2026-10-04-online-portfolio-selection-paper.md`. Outputs from the
runs quoted there are in `outputs/`.

Setup, from the btest repo root:

```sh
git clone https://github.com/nglahani/Online-Quantitative-Trading-Strategies \
    docs/research/olps-replication/olps-repo
git -C docs/research/olps-replication/olps-repo checkout 7c2e88d
uv run --with scipy --with pandas --with cvxpy python docs/research/olps-replication/paper_data.py
```

| Script | What it does | Needs |
|---|---|---|
| `paper_data.py` | The authors' own 1998-2009 data and functions: reproduce Tables 3-4, then costs, one-day delay, bad prints, full-history tickers, paired Sharpe tests | authors' repo |
| `their_code.py` | Authors' functions on 16/17 ETFs, 2016-2024 (OLMAR and FTRL checks) | btest database and bars |
| `decompose.py` | ETFs: one assumption at a time, measured spreads, input definitions, paired tests, start dates | btest database and bars, `spreads.json` |
| `ndx_test.py` | Authors' functions on current NASDAQ-100 members, 2016-2024, Alpaca daily bars | Alpaca keys, `ndx.txt` |
| `spreads.py` | Half-spreads at 15:45, 45 sessions per ETF | Alpaca keys |
| `cwmr_cache_check.py` | btest CWMR port: cached state equals full replay | btest database and bars |
| `olps_sanity.py` | OLMAR, PAMR, CRP on alternating synthetic prices | none |
| `dry.py` | One btest engine backtest without saving (`SLIP` env var = bp) | btest database and bars |
| `port_vs_authors.py` | btest's CWMR port against the authors' `cwmr()` on the paper's data | authors' repo |
| `monthly.py` | Every OLPS strategy on the 16 ETFs, 2016-2024: daily, daily signal traded at month end, monthly bars | btest database and bars |
| `monthly_robustness.py` | Monthly CWMR and Anticor: 21 trading offsets, yearly restarts, paired Sharpe tests | btest database and bars |
| `weekly.py` | As `monthly.py` with weeks, then the robustness checks for weekly CWMR | btest database and bars |
| `paper_1999_2024.py` | The working paper's Table 4 on btest's engine: four CWMR schedules, equal weight and SPY, 1999-2024 on long history | btest database (`btest longhist`) |
| `bars_1999.py` | Monthly and weekly bars, equal weight and SPY, 1999-2015 on long history; paired tests; higher costs | btest database (`btest longhist`) |
| `weekly_offsets_longhist.py` | Weekly-bars CWMR at each of the 5 week-end offsets, 1999-2024 on long history | btest database (`btest longhist`) |
| `long_history.py`, `long_history_run.py` | Superseded stand-in study: ETFs spliced with older funds from 1995, same-close fills (outputs `long_history_*.out`; `continuous`, `control`, `validate` arguments) | downloads, cached under `data/longhist/` |

Run every script from the repo root; paths such as `strategies/olps/cwmr.py` and `data/` are
relative to it. `engine_cwmr.out` collects three `dry.py` runs of `strategies/olps/cwmr.py`
at 0, 0.43 and 0.7 bp, each under a `==` header.
