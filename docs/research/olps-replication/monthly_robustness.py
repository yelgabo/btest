"""Is the monthly CWMR / Anticor result luck? Trade every 21 sessions at each of 21 offsets
instead of month end; restart in each year; paired Sharpe test against SPY; per-year gaps;
how many ETFs it holds."""
import math
from datetime import date
from math import erf

import numpy as np
import polars as pl
import psycopg

from btest import config, daily, db, metrics, olps
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY",
            "XLP", "XLU", "XLB", "XLRE"]
END = date(2025, 1, 1)
s = config.load(need_alpaca=False)
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.7))
with psycopg.connect(s.database_url) as conn:
    sessions = db.get_sessions(conn, date(2000, 1, 1), date(2100, 1, 1))
    sp = {x: db.get_splits(conn, x) for x in UNIVERSE}
    dv = {x: db.get_dividends(conn, x) for x in UNIVERSE}
    frames = {x: daily.load(s.data_dir, x, sessions, cfg.timing, sp[x], dv[x])
              .filter(pl.col("date") < END) for x in UNIVERSE}
    rates = db.get_rates(conn, "DTB3")
dates = [d for d in sessions.filter(pl.col("date") < END)["date"].to_list()
         if d >= min(f["date"].min() for f in frames.values())]
market = Market(dates, frames)


def strategy(algo, every=None, offset=0, month_end=False):
    class S(olps.OnlineStrategy):
        universe = UNIVERSE
        params = {}
        rebalance = "month_end" if month_end else "daily"

        def make(self, n):
            return algo(n)

        def decide(self, as_of, data):
            if every and (len(data.history("SPY")) - offset) % every:
                return None
            return self.run_online(data)
    return S()


def run(strat, start=date(2016, 1, 1)):
    e = PortfolioEngine(market, sessions, cfg, sp, dv, rates)
    r = e.run(strat, start, END)
    return r.equity, metrics.compute(r.equity, rates), r.fills


def spy_equity(start):
    e = PortfolioEngine(market, sessions, cfg, sp, dv, rates)
    from pathlib import Path
    from btest.runner import load_strategy_class
    return e.run(load_strategy_class(Path("strategies/baseline/buy_hold.py"))(), start, END).equity


def paired(eq1, eq2):
    j = eq1.join(eq2, on="date", suffix="_b").sort("date")
    r1 = np.diff(j["equity"].to_numpy()) / j["equity"].to_numpy()[:-1]
    r2 = np.diff(j["equity_b"].to_numpy()) / j["equity_b"].to_numpy()[:-1]
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2)))), rho


spy16 = spy_equity(date(2016, 1, 1))
spy_cagr = metrics.compute(spy16, rates)["cagr"]
for name, algo in [("CWMR", olps.CWMRAuthors), ("Anticor", olps.Anticor)]:
    print(f"\n== {name}, daily signal, trade monthly, 0.7 bp (SPY {spy_cagr:.1%})")
    eq, st, fills = run(strategy(algo, month_end=True))
    d, p, rho = paired(eq, spy16)
    print(f"month end: CAGR {st['cagr']:.1%}, Sharpe {st['sharpe']:.2f}, "
          f"max DD {st['max_drawdown']:.1%}; paired Sharpe vs SPY {d:+.2f}, p {p:.2f}, "
          f"rho {rho:.2f}")
    buy_days = {}
    for f in fills:
        if f.qty > 0:
            buy_days.setdefault(f.ts.date(), set()).add(f.symbol)
    pos = eq.join(spy16, on="date", suffix="_spy")
    years = sorted({dt.year for dt in pos["date"]})
    gaps = []
    for y in years:
        yr = pos.filter(pl.col("date").dt.year() == y)
        prev = pos.filter(pl.col("date").dt.year() == y - 1)
        a0 = prev["equity"][-1] if prev.height else yr["equity"][0]
        b0 = prev["equity_spy"][-1] if prev.height else yr["equity_spy"][0]
        gaps.append(f"{y}: {yr['equity'][-1] / a0 - yr['equity_spy'][-1] / b0:+.1%}")
    print("year minus SPY:", "  ".join(gaps))
    cagrs = []
    for off in range(21):
        _, st_o, _ = run(strategy(algo, every=21, offset=off))
        cagrs.append(st_o["cagr"])
    c = np.array(cagrs)
    print(f"every 21 sessions, 21 offsets: CAGR min {c.min():.1%}, median {np.median(c):.1%}, "
          f"max {c.max():.1%}; offsets beating SPY: {(c > spy_cagr).sum()} of 21")
    rows = []
    for y in range(2017, 2024):
        start = date(y, 1, 1)
        _, st_y, _ = run(strategy(algo, month_end=True), start)
        sp_y = metrics.compute(spy_equity(start), rates)["cagr"]
        rows.append(f"{y}: {st_y['cagr']:.1%} vs {sp_y:.1%}")
    # The algorithm still learns from 2016 on; only the measured window starts later.
    print("measured from (state still built from 2016):", "  ".join(rows))
