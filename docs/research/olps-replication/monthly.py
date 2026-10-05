"""Every OLPS strategy three ways on the 16 ETFs, 2016-2024, btest timing, 0.7 bp:
daily (as published), A = daily signal but trade only at month end, B = monthly bars."""
import copy
from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from btest import config, daily, db, metrics
from btest import olps
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import benchmark_from_daily, load_strategy_class

UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "EFA", "EEM", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY",
            "XLP", "XLU", "XLB", "XLRE"]
START, END = date(2016, 1, 1), date(2025, 1, 1)
ALGOS = {
    "CWMR (paper)": (olps.CWMRAuthors, {}),
    "PAMR (paper)": (olps.PAMRAuthors, {}),
    "Anticor": (olps.Anticor, {}),
    "RMR": (olps.RMR, {}),
    "Pattern matching": (olps.PatternMatching, {}),
    "Follow the leader": (olps.FollowTheLeader, {}),
    "FTRL": (olps.FollowTheRegularizedLeader, {}),
    "Exponential gradient": (olps.ExponentialGradient, {}),
    "Universal portfolios": (olps.UniversalPortfolios, {}),
    "FTLH": (olps.FollowTheLeadingHistory, {}),
    "Meta, exponential": (olps.MetaExperts, {"method": "exponential"}),
    "Meta, Newton": (olps.MetaExperts, {"method": "newton",
                                        "experts": ["cwmr", "pamr", "rmr", "olmar"]}),
}

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


def run(strategy):
    e = PortfolioEngine(market, sessions, cfg, sp, dv, rates)
    r = e.run(strategy, START, END)
    eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash), on="date")
    st = metrics.compute(eq, rates) | metrics.trade_stats(r.fills, eq)
    return st


def make_class(algo, kw, bars, rebalance):
    class S(olps.OnlineStrategy):
        universe = UNIVERSE
        params = {}

        def make(self, n):
            return algo(n, **copy.deepcopy(kw))

        def decide(self, as_of, data):
            return self.run_online(data)
    S.bars, S.rebalance = bars, rebalance
    return S


print(f"{'strategy':22}{'daily':>22}{'A: trade monthly':>24}{'B: monthly bars':>24}")
print(f"{'':22}{'CAGR  Sh  turn':>22}{'CAGR  Sh  turn':>24}{'CAGR  Sh  turn':>24}")


def cell(st):
    return f"{st['cagr']:6.1%} {st['sharpe']:4.2f} {st['turnover']:5.0f}x"


for name, (algo, kw) in ALGOS.items():
    out = [run(make_class(algo, kw, bars, reb)())
           for bars, reb in (("daily", "daily"), ("daily", "month_end"), ("monthly", "month_end"))]
    print(f"{name:22}{cell(out[0]):>22}{cell(out[1]):>24}{cell(out[2]):>24}", flush=True)
olmar = load_strategy_class(Path("strategies/olps/olmar.py"))
o_daily = run(olmar())
olmar.rebalance = "month_end"
print(f"{'OLMAR (Li-Hoi)':22}{cell(o_daily):>22}{cell(run(olmar())):>24}{'(not run)':>24}")
crp = load_strategy_class(Path("strategies/olps/crp.py"))
print(f"{'CRP monthly':22}{cell(run(crp())):>22}")
spy = load_strategy_class(Path("strategies/baseline/buy_hold.py"))
print(f"{'SPY buy and hold':22}{cell(run(spy())):>22}")
