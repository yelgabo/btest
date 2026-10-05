"""Cached incremental CWMR state must equal a full replay at every decision."""
from datetime import date
from pathlib import Path
import numpy as np, polars as pl, psycopg
from btest import config, daily, db
from btest.portfolio import Data, Market, PortfolioConfig, PortfolioEngine
from btest.runner import load_strategy_class

s = config.load(need_alpaca=False)
cls = load_strategy_class(Path("strategies/olps/cwmr.py"))
with psycopg.connect(s.database_url) as conn:
    sess = db.get_sessions(conn, date(2000, 1, 1), date(2100, 1, 1))
    frames = {x: daily.load(s.data_dir, x, sess, daily.Timing(), db.get_splits(conn, x), db.get_dividends(conn, x)).filter(pl.col("date") < date(2016, 12, 31)) for x in cls.universe}
dates = [d for d in sess["date"].to_list() if min(f["date"].min() for f in frames.values()) <= d < date(2016, 12, 31)]
e = PortfolioEngine(Market(dates, frames), sess, PortfolioConfig())
cached, fresh = cls(), cls()
worst = 0.0
for i in range(5, len(dates)):
    a = cached.decide(e.decide_ts[i], Data(e, i))
    fresh.__dict__.pop("_state", None)
    b = fresh.decide(e.decide_ts[i], Data(e, i))
    keys = set(a) | set(b)
    worst = max(worst, max(abs(a.get(k, 0) - b.get(k, 0)) for k in keys))
print(f"{len(dates) - 5} decisions, largest weight difference cached vs full replay: {worst:.2e}")
