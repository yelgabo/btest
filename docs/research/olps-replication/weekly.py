"""Every OLPS strategy three ways on the 16 ETFs, 2016-2024, btest timing, 0.7 bp:
daily (as published), A = daily signal but trade only at each week's last session,
B = weekly bars. Then, for CWMR with A and B, the checks monthly_robustness.py ran on monthly."""
import copy
import math
from math import erf
from datetime import date
from pathlib import Path

import numpy as np
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
    return st | {"equity": r.equity}


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


print(f"{'strategy':22}{'daily':>22}{'A: trade weekly':>24}{'B: weekly bars':>24}")
print(f"{'':22}{'CAGR  Sh  turn':>22}{'CAGR  Sh  turn':>24}{'CAGR  Sh  turn':>24}")


def cell(st):
    return f"{st['cagr']:6.1%} {st['sharpe']:4.2f} {st['turnover']:5.0f}x"


for name, (algo, kw) in ALGOS.items():
    out = [run(make_class(algo, kw, bars, reb)())
           for bars, reb in (("daily", "daily"), ("daily", "weekly"), ("weekly", "weekly"))]
    print(f"{name:22}{cell(out[0]):>22}{cell(out[1]):>24}{cell(out[2]):>24}", flush=True)
olmar = load_strategy_class(Path("strategies/olps/olmar.py"))
o_daily = run(olmar())
olmar.rebalance = "weekly"
print(f"{'OLMAR (Li-Hoi)':22}{cell(o_daily):>22}{cell(run(olmar())):>24}{'(not run)':>24}")
crp = load_strategy_class(Path("strategies/olps/crp.py"))
print(f"{'CRP monthly':22}{cell(run(crp())):>22}")
spy = load_strategy_class(Path("strategies/baseline/buy_hold.py"))
spy_st = run(spy())
print(f"{'SPY buy and hold':22}{cell(spy_st):>22}")


def paired(eq1, eq2):
    j = eq1.join(eq2, on="date", suffix="_b").sort("date")
    r1 = np.diff(j["equity"].to_numpy()) / j["equity"].to_numpy()[:-1]
    r2 = np.diff(j["equity_b"].to_numpy()) / j["equity_b"].to_numpy()[:-1]
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2)))), rho


class Every(olps.OnlineStrategy):
    universe = UNIVERSE
    params = {}
    every, offset = 5, 0

    def make(self, n):
        return olps.CWMRAuthors(n)

    def decide(self, as_of, data):
        if (len(data.history("SPY")) - self.offset) % self.every:
            return None
        return self.run_online(data)


class EveryBars(Every):
    """Bars of 5 sessions ending on offset sessions, instead of ISO weeks."""

    def _closes(self, data):
        frame = data.frame("close")
        last = frame.height - 1
        rows = frame[[i for i in range(last % 5, last + 1, 5)]]
        return {s: rows[s].drop_nulls().to_numpy() for s in self.universe}


def report(label, st, cls):
    d, p, rho = paired(st["equity"], spy_st["equity"])
    print(f"\n== CWMR, {label} (SPY {spy_st['cagr']:.1%}, Sharpe {spy_st['sharpe']:.2f})")
    print(f"week end: CAGR {st['cagr']:.1%}, Sharpe {st['sharpe']:.2f}, max DD "
          f"{st['max_drawdown']:.1%}; paired Sharpe vs SPY {d:+.2f}, p {p:.2f}, rho {rho:.2f}")
    pos = st["equity"].join(spy_st["equity"], on="date", suffix="_spy")
    gaps = []
    for y in sorted({dt.year for dt in pos["date"]}):
        yr = pos.filter(pl.col("date").dt.year() == y)
        prev = pos.filter(pl.col("date").dt.year() == y - 1)
        a0 = prev["equity"][-1] if prev.height else yr["equity"][0]
        b0 = prev["equity_spy"][-1] if prev.height else yr["equity_spy"][0]
        gaps.append(f"{y}: {yr['equity'][-1] / a0 - yr['equity_spy'][-1] / b0:+.1%}")
    print("year minus SPY:", "  ".join(gaps))
    out = []
    for off in range(5):
        cls.offset = off
        out.append(run(cls()))
    c = np.array([o["cagr"] for o in out])
    sh = np.array([o["sharpe"] for o in out])
    print("every 5 sessions, 5 offsets: CAGR " + ", ".join(f"{x:.1%}" for x in c)
          + "; Sharpe " + ", ".join(f"{x:.2f}" for x in sh)
          + f"; beating SPY on both: {((c > spy_st['cagr']) & (sh > spy_st['sharpe'])).sum()} of 5")


report("A: daily signal, trade weekly", run(make_class(olps.CWMRAuthors, {}, "daily", "weekly")()),
       Every)
report("B: weekly bars", run(make_class(olps.CWMRAuthors, {}, "weekly", "weekly")()), EveryBars)
