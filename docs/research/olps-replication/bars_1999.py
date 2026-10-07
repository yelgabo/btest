"""Checks added after the pre-registered 1999-2015 runs of CWMR on monthly and weekly bars
(website runs 80 and 81): equal weight in the same ETFs, paired Sharpe tests against SPY, and
higher costs. Same data and engine path as a website run with data = longhist."""
import math
from datetime import date
from math import erf
from pathlib import Path

import numpy as np
import polars as pl
import psycopg

from btest import config, db, longhist, metrics
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import load_strategy_class

START, END = date(1999, 1, 1), date(2016, 1, 1)
STRATS = {"Monthly bars": "strategies/olps/cwmr_monthly_bars.py",
          "Weekly bars": "strategies/olps/cwmr_weekly_bars.py",
          "Equal weight, monthly": "strategies/olps/crp.py",
          "SPY": "strategies/baseline/buy_hold.py"}

s = config.load(need_alpaca=False)
universe = load_strategy_class(Path(STRATS["Monthly bars"])).universe
with psycopg.connect(s.database_url) as conn:
    frames = longhist.frames(conn, universe, END)
    rates = db.get_rates(conn, "DTB3")
sessions = nyse_sessions(longhist.START, date(2018, 1, 1))
dates = sessions.filter(pl.col("date") < END)["date"].to_list()
market = Market(dates, frames)


def run(path, bp):
    cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=bp), data="longhist")
    r = PortfolioEngine(market, sessions, cfg, rates=rates).run(
        load_strategy_class(Path(path))(), START, END)
    return r.equity, metrics.compute(r.equity, rates) | metrics.trade_stats(r.fills, r.equity)


def paired(eq1, eq2):
    j = eq1.join(eq2, on="date", suffix="_b").sort("date")
    r1 = np.diff(j["equity"].to_numpy()) / j["equity"].to_numpy()[:-1]
    r2 = np.diff(j["equity_b"].to_numpy()) / j["equity_b"].to_numpy()[:-1]
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2))))


base = {name: run(path, 0.7) for name, path in STRATS.items()}
print(f"{START} to {END}, 0.7 bp")
for name, (eq, st) in base.items():
    vs = ""
    if name != "SPY":
        vs = "  vs SPY {:+.2f}, p {:.2f}".format(*paired(eq, base["SPY"][0]))
    if name in ("Monthly bars", "Weekly bars"):
        vs += "; vs equal weight {:+.2f}, p {:.2f}".format(
            *paired(eq, base["Equal weight, monthly"][0]))
    print(f"  {name:22} CAGR {st['cagr']:6.2%}  Sharpe {st['sharpe']:.2f}  "
          f"max DD {st['max_drawdown']:6.1%}  turnover {st['turnover']:5.1f}x{vs}")
print("CAGR at higher costs per dollar traded:")
for name in ("Monthly bars", "Weekly bars"):
    row = [f"{bp} bp {run(STRATS[name], bp)[1]['cagr']:.2%}" for bp in (5, 10, 20)]
    print(f"  {name:22} " + ", ".join(row))
