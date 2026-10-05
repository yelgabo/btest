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
