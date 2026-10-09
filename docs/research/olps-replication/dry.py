"""Run a portfolio backtest without saving it: prints metrics and timing.

    uv run python dry.py STRATEGY.py START END [param=json ...]

SLIP sets slippage in bp (default 1); UNIV overrides the universe (comma-separated)."""
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import psycopg

from btest import config, daily, db, metrics
from btest.options import OptionBook
from btest.portfolio import Market, PortfolioConfig, PortfolioCosts, PortfolioEngine
from btest.runner import benchmark_from_daily, load_strategy_class

path = Path(sys.argv[1])
start = date.fromisoformat(sys.argv[2])
end = date.fromisoformat(sys.argv[3])
params = {k: json.loads(v) for k, v in (a.split("=", 1) for a in sys.argv[4:])}
s = config.load(need_alpaca=False)
cls = load_strategy_class(path)
if os.environ.get("UNIV"):
    cls.universe = os.environ["UNIV"].split(",")
strat = cls(**params)
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=float(os.environ.get("SLIP", "1"))))
t0 = time.time()
with psycopg.connect(s.database_url) as conn:
    all_sessions = db.get_sessions(conn, date(2000, 1, 1), date.today())
    sessions = all_sessions.filter(pl.col("date") < end)
    need = list(dict.fromkeys(cls.universe + ["SPY"]))
    splits = {x: db.get_splits(conn, x) for x in need}
    dividends = {x: db.get_dividends(conn, x) for x in need}
    frames = {x: daily.load(s.data_dir, x, all_sessions, cfg.timing, splits[x], dividends[x])
              .filter(pl.col("date") < end) for x in need}
    t1 = time.time()
    first = min(frames[x]["date"].min() for x in cls.universe)
    dates = [d for d in sessions["date"].to_list() if d >= first]
    market = Market(dates, {x: frames[x] for x in cls.universe})
    rf = db.get_rates(conn, "DTB3")
    engine = PortfolioEngine(market, all_sessions, cfg, splits, dividends, rf,
                             OptionBook(conn, datetime.combine(end, datetime.min.time(), UTC)))
    r = engine.run(strat, start, end)
    t2 = time.time()
    eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash), on="date")
    st = metrics.compute(eq, rf)
    bm = metrics.compute(eq.select("date", pl.col("benchmark").alias("equity")), rf)
print(f"load {t1-t0:.1f}s run {t2-t1:.1f}s fills {len(r.fills)} exposure {r.exposure:.2f}")
for k in ["cagr", "ann_vol", "sharpe", "max_drawdown", "end_equity"]:
    print(f"{k:14} {st.get(k):>12.4f} {bm.get(k):>12.4f}")
print("notes", r.notes[:5])
print("first fills", [(f.ts.date(), f.symbol, round(f.qty, 3), round(f.price, 2))
                      for f in r.fills[:4]])
