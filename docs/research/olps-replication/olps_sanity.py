"""Two assets whose prices alternate around a mean: a correct mean-reversion algorithm must
compound strongly; CRP gains a little; buy and hold gains nothing."""
from datetime import date
import numpy as np, polars as pl
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import load_strategy_class
from pathlib import Path

sessions = nyse_sessions(date(2024, 1, 2), date(2024, 12, 31))
dates = sessions["date"].to_list()
n = len(dates)
a = np.array([1.0 if i % 2 == 0 else 2.0 for i in range(n)])
b = np.array([2.0 if i % 2 == 0 else 1.0 for i in range(n)])
def frame(p):
    return pl.DataFrame({"date": dates, **{c: p for c in ("open", "high", "low", "close", "cut_open", "cut_high", "cut_low", "cut_close", "raw_cut_close", "raw_close", "fill")},
                         "volume": [1e6] * n, "cut_volume": [1e6] * n})
cfg = PortfolioConfig(cash=10_000.0, costs=PortfolioCosts(slippage_bps=0.0, sec_fee_rate=0.0), cash_yield=False)
for name in ("olmar", "pamr", "crp"):
    cls = load_strategy_class(Path(f"strategies/olps/{name}.py"))
    cls.universe = ["A", "B"]
    params = {"window": 2} if name == "olmar" else ({"monthly": False} if name == "crp" else {})
    e = PortfolioEngine(Market(dates, {"A": frame(a), "B": frame(b)}), sessions, cfg)
    r = e.run(cls(**params), dates[0], date(2025, 1, 1))
    print(name, f"final equity {r.equity['equity'][-1]:,.0f} after {n} sessions")
