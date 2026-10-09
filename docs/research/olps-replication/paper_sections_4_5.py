"""Numbers for the working paper's Sections 7 and 8 that need btest data: daily and monthly CWMR
against equal weight and SPY on 2016-2024 minute data (the search that chose the holdout
variant), with paired Sharpe tests, and monthly CWMR on long history from 1995 (website runs 84
and 85), also measured from its first fill. The tests match the replication repository's
cwmr_etf.stats."""
import math
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl
import psycopg

from btest import config, daily, db, longhist, metrics
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import benchmark_from_daily, load_strategy_class

S2016, S2025 = date(2016, 1, 1), date(2025, 1, 1)
BLOCKS = (1, 5, 21, 63, 126)
STRATS = {"Daily CWMR": "strategies/olps/cwmr.py",
          "Monthly, daily signal": "strategies/olps/cwmr_monthly.py",
          "Equal weight": "strategies/olps/crp.py"}


def returns(eq: np.ndarray) -> np.ndarray:
    return eq[1:] / eq[:-1] - 1


def jkm(eq1, eq2):
    r1, r2 = returns(eq1), returns(eq2)
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def bootstrap_p(eq1, eq2, block, draws=10_000, seed=0):
    r1, r2 = returns(eq1), returns(eq2)
    diff = (r1.mean() / r1.std() - r2.mean() / r2.std()) * math.sqrt(252)
    rng = np.random.default_rng(seed)
    n, k = len(r1), len(r1) // block
    out = np.empty(draws)
    for j in range(draws):
        idx = (rng.integers(0, n - block + 1, k)[:, None] + np.arange(block)).ravel()
        a, b = r1[idx], r2[idx]
        out[j] = (a.mean() / a.std() - b.mean() / b.std()) * math.sqrt(252)
    return float(np.mean(np.abs(out - out.mean()) >= abs(diff)))


def compare(name, a, b):
    d, p = jkm(a, b)
    boots = ", ".join(f"{bootstrap_p(a, b, k):.2f}" for k in BLOCKS)
    print(f"  {name:38} {d:+.2f}  JKM p {p:.2f}  bootstrap p by block {BLOCKS}: {boots}")


def cagr(dates, eq):
    return (eq[-1] / eq[0]) ** (365.25 / (dates[-1] - dates[0]).days) - 1


def window(df: pl.DataFrame, col: str, lo: date, hi: date):
    """The part of a run between lo and hi, from the equity on the session before lo."""
    d = df["date"].to_list()
    ks = [k for k, x in enumerate(d) if lo <= x < hi]
    if ks[0] > 0:
        ks = [ks[0] - 1] + ks
    return [d[k] for k in ks], df[col].to_numpy()[ks]


s = config.load(need_alpaca=False)
universe = load_strategy_class(Path(STRATS["Daily CWMR"])).universe

print("2016-2024, btest minute data, decide 15:30, fill 15:45")
for bp in (0.0, 0.43, 0.7):
    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=bp))
    with psycopg.connect(s.database_url) as conn:
        sessions = db.get_sessions(conn, date(2000, 1, 1), date(2100, 1, 1))
        sp = {x: db.get_splits(conn, x) for x in universe}
        dv = {x: db.get_dividends(conn, x) for x in universe}
        frames = {x: daily.load(s.data_dir, x, sessions, cfg.timing, sp[x], dv[x])
                  .filter(pl.col("date") < S2025) for x in universe}
        rates = db.get_rates(conn, "DTB3")
    dates = [d for d in sessions.filter(pl.col("date") < S2025)["date"].to_list()
             if d >= min(f["date"].min() for f in frames.values())]
    market = Market(dates, frames)
    eqs = {}
    for name, path in STRATS.items():
        if bp != 0.7 and name != "Daily CWMR":
            continue
        r = PortfolioEngine(market, sessions, cfg, sp, dv, rates).run(
            load_strategy_class(Path(path))(), S2016, S2025)
        eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash),
                           on="date")
        st = metrics.compute(eq, rates) | metrics.trade_stats(r.fills, eq)
        eqs[name] = eq
        print(f"  {bp:4} bp  {name:24} CAGR {st['cagr']:6.2%}  Sharpe {st['sharpe']:.2f}  "
              f"turnover {st['turnover']:5.1f}x")
    spy = next(iter(eqs.values()))
    spy_st = metrics.compute(spy.select("date", pl.col("benchmark").alias("equity")), rates)
    print(f"  {bp:4} bp  {'SPY':24} CAGR {spy_st['cagr']:6.2%}  Sharpe {spy_st['sharpe']:.2f}")
    if bp == 0.7:
        a = {k: v["equity"].to_numpy() for k, v in eqs.items()}
        spy_eq = spy["benchmark"].to_numpy()
        compare("Daily CWMR vs equal weight", a["Daily CWMR"], a["Equal weight"])
        compare("Daily CWMR vs SPY", a["Daily CWMR"], spy_eq)
        compare("Monthly, daily signal vs equal weight", a["Monthly, daily signal"],
                a["Equal weight"])
        compare("Monthly, daily signal vs SPY", a["Monthly, daily signal"], spy_eq)

print("\nLong history, monthly CWMR (daily signal) from 1995, decide on the close, "
      "fill at the next open, 0.7 bp")
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.7), data="longhist")
need = list(dict.fromkeys(universe + ["SPY"]))
with psycopg.connect(s.database_url) as conn:
    frames = longhist.frames(conn, need, S2025)
    rates = db.get_rates(conn, "DTB3")
sessions = nyse_sessions(longhist.START, date(2027, 1, 1))
dates = sessions.filter(pl.col("date") < S2025)["date"].to_list()
market = Market(dates, {x: frames[x] for x in universe})
for end in (S2016, S2025):
    runs = {}
    for name in ("Monthly, daily signal", "Equal weight"):
        r = PortfolioEngine(market, sessions, cfg, rates=rates).run(
            load_strategy_class(Path(STRATS[name]))(), date(1995, 1, 3), end)
        eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash),
                           on="date")
        runs[name] = (r, eq)
    r, eq = runs["Monthly, daily signal"]
    bench = metrics.compute(eq.select("date", pl.col("benchmark").alias("equity")), rates)
    st = metrics.compute(eq, rates)
    print(f"  1995-{end.year - 1}: CAGR {st['cagr']:.2%} vs SPY {bench['cagr']:.2%}; "
          f"first trade {r.fills[0].ts.date() if r.fills else None}")
    if end == S2016 and r.fills:
        first = r.fills[0].ts.date()
        d, v = window(eq, "equity", first, end)
        _, b = window(eq, "benchmark", first, end)
        print(f"  from the first fill to 2015: CAGR {cagr(d, v):.2%} vs SPY {cagr(d, b):.2%}")
    if end == S2025:
        for name, (_, e) in runs.items():
            d, v = window(e, "equity", S2016, S2025)
            print(f"  2016-2024 part of the 1995-2024 run, {name}: {cagr(d, v):.2%}")
        d, v = window(eq, "benchmark", S2016, S2025)
        print(f"  2016-2024 part, SPY: {cagr(d, v):.2%}")
