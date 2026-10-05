import os
"""Run a portfolio backtest without saving it: prints metrics and timing."""
import sys, time
from datetime import UTC, date, datetime
from pathlib import Path
import polars as pl
import psycopg
from btest import config, daily, db, metrics
from btest.options import OptionBook
from btest.portfolio import Market, PortfolioConfig, PortfolioEngine
from btest.runner import load_strategy_class, benchmark_from_daily

path = Path(sys.argv[1]); start = date.fromisoformat(sys.argv[2]); end = date.fromisoformat(sys.argv[3])
params = dict(a.split("=", 1) for a in sys.argv[4:])
import json
params = {k: json.loads(v) for k, v in params.items()}
s = config.load(need_alpaca=False)
cls = load_strategy_class(path)
if os.environ.get("UNIV"): cls.universe = os.environ["UNIV"].split(",")
strat = cls(**params)
import os
from btest.portfolio import PortfolioCosts
cfg = PortfolioConfig(costs=PortfolioCosts(slippage_bps=float(os.environ.get("SLIP", "1"))))
t0 = time.time()
with psycopg.connect(s.database_url) as conn:
    allsess = db.get_sessions(conn, date(2000, 1, 1), date.today()); sessions = allsess.filter(pl.col("date") < end)
    need = list(dict.fromkeys(cls.universe + ["SPY"]))
    sp = {x: db.get_splits(conn, x) for x in need}; dv = {x: db.get_dividends(conn, x) for x in need}
    frames = {x: daily.load(s.data_dir, x, allsess, cfg.timing, sp[x], dv[x]).filter(pl.col("date") < end) for x in need}
    t1 = time.time()
    dates = [d for d in sessions["date"].to_list() if d >= min(frames[x]["date"].min() for x in cls.universe)]
    m = Market(dates, {x: frames[x] for x in cls.universe})
    e = PortfolioEngine(m, allsess, cfg, sp, dv, db.get_rates(conn, "DTB3"),
                        OptionBook(conn, datetime.combine(end, datetime.min.time(), UTC)))
    r = e.run(strat, start, end)
    t2 = time.time()
    eq = r.equity.join(benchmark_from_daily(frames, "SPY", r.equity["date"], cfg.cash), on="date")
    rf = db.get_rates(conn, "DTB3")
    st = metrics.compute(eq, rf); bm = metrics.compute(eq.select("date", pl.col("benchmark").alias("equity")), rf)
print(f"load {t1-t0:.1f}s run {t2-t1:.1f}s fills {len(r.fills)} exposure {r.exposure:.2f}")
for k in ["cagr", "ann_vol", "sharpe", "max_drawdown", "end_equity"]:
    print(f"{k:14} {st.get(k):>12.4f} {bm.get(k):>12.4f}")
print("notes", r.notes[:5])
print("first fills", [(f.ts.date(), f.symbol, round(f.qty, 3), round(f.price, 2)) for f in r.fills[:4]])
