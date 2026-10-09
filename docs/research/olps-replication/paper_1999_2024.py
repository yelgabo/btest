"""Table 4 of the working paper recomputed on btest's own engine: the four CWMR schedules, equal
weight and SPY on long history, 1999-2024, deciding on each close and filling at the next open.
The replication repository's etf_tables.py computes the same table with a separate backtest engine."""
from datetime import date
from pathlib import Path

import polars as pl
import psycopg

from btest import config, db, longhist, metrics
from btest.calendar import nyse_sessions
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import benchmark_from_daily, load_strategy_class

START, END = date(1999, 1, 1), date(2025, 1, 1)
monthly = load_strategy_class(Path("strategies/olps/cwmr_monthly.py"))
# The same algorithm and late-joiner rule as cwmr_monthly, trading every session.
daily = type("CWMRDaily", (monthly,), {"rebalance": "daily"})
STRATS = {"Daily": daily,
          "Monthly, daily signal": monthly,
          "Monthly bars": load_strategy_class(Path("strategies/olps/cwmr_monthly_bars.py")),
          "Weekly bars": load_strategy_class(Path("strategies/olps/cwmr_weekly_bars.py")),
          "Equal weight": load_strategy_class(Path("strategies/olps/crp.py"))}

s = config.load(need_alpaca=False)
universe = monthly.universe
with psycopg.connect(s.database_url) as conn:
    frames = longhist.frames(conn, universe, END)
    rates = db.get_rates(conn, "DTB3")
sessions = nyse_sessions(longhist.START, date(2027, 1, 1))
dates = sessions.filter(pl.col("date") < END)["date"].to_list()
market = Market(dates, frames)
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=0.7), data="longhist")

print(f"{START} to {END}, 0.7 bp")
spy = None
for name, cls in STRATS.items():
    r = PortfolioEngine(market, sessions, cfg, rates=rates).run(cls(), START, END)
    eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash), on="date")
    st = metrics.compute(eq, rates) | metrics.trade_stats(r.fills, eq)
    spy = metrics.compute(eq.select("date", pl.col("benchmark").alias("equity")), rates)
    print(f"  {name:24} CAGR {st['cagr']:6.2%}  Sharpe {st['sharpe']:.2f}  "
          f"max DD {st['max_drawdown']:6.1%}  turnover {st['turnover']:6.1f}x")
print(f"  {'SPY':24} CAGR {spy['cagr']:6.2%}  Sharpe {spy['sharpe']:.2f}  "
      f"max DD {spy['max_drawdown']:6.1%}")
