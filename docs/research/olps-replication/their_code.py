"""Run the authors' unmodified strategy functions on our daily closes, with their method:
close-to-close price relatives, no costs, their wealth calculation."""
import os

# Folder holding spreads.json, ndx.txt and the authors' repo (olps-repo/); defaults to here.
WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
import sys, math, os
from datetime import date
import numpy as np, polars as pl, psycopg
REPO = OLPS + "/Scripts"
sys.path[:0] = [REPO, REPO + "/Strategies"]
import follow_the_loser as ftl, follow_the_winner as ftw, benchmarks as bm
from btest import config, daily, db

def matrix(symbols, start, end):
    s = config.load(need_alpaca=False)
    with psycopg.connect(s.database_url) as conn:
        sess = db.get_sessions(conn, date(2000, 1, 1), date(2100, 1, 1))
        cols = {}
        for sym in symbols:
            df = daily.load(s.data_dir, sym, sess, daily.Timing(), db.get_splits(conn, sym), db.get_dividends(conn, sym))
            cols[sym] = df.filter((pl.col("date") >= start) & (pl.col("date") < end)).select("date", pl.col("close").alias(sym))
    out = None
    for sym, df in cols.items():
        out = df if out is None else out.join(df, on="date", how="full", coalesce=True)
    out = out.sort("date")
    prices = out.drop("date").fill_null(strategy="forward").to_numpy()
    rel = prices[1:] / prices[:-1]
    rel = np.where(np.isnan(rel), 1.0, rel)   # their rule: no prior close -> 1.0
    return out["date"].to_list()[1:], rel

def stats(b_n, rel):
    r = np.einsum("ij,ij->i", b_n, rel)
    wealth = np.cumprod(r)
    years = len(r) / 252
    cagr = wealth[-1] ** (1 / years) - 1
    daily_rf = 1.05 ** (1 / 252) - 1
    sharpe = (r - 1 - daily_rf).mean() / (r - 1).std() * math.sqrt(252)
    peak = np.maximum.accumulate(wealth)
    mdd = (wealth / peak - 1).min()
    turnover = np.abs(np.diff(b_n, axis=0)).sum(axis=1).mean() * 252
    return wealth[-1], cagr, sharpe, mdd, turnover

def run(symbols, start, end, label):
    dates, rel = matrix(symbols, start, end)
    n = rel.shape[1]
    b0 = np.full(n, 1.0 / n)
    print(f"\n{label}: {len(symbols)} symbols, {dates[0]} to {dates[-1]}, {len(dates)} days")
    print(f"{'strategy':28}{'wealth':>9}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>8}{'turnover/yr':>13}")
    runs = {
        "CWMR (their variant)": lambda: ftl.cwmr(b0, rel),
        "PAMR (their settings)": lambda: ftl.pamr(b0, rel),
        "OLMAR (their code)": lambda: ftl.olmar(b0, rel),
        "Anticor": lambda: ftl.anticor(b0, rel),
        "RMR": lambda: ftl.rmr(b0, rel),
        "FTRL": lambda: ftw.follow_the_regularized_leader(b0, rel),
        "CRP (daily)": lambda: np.tile(b0, (len(rel), 1)),
    }
    for name, f in runs.items():
        try:
            b_n = np.asarray(f())
            w, c, s, m, t = stats(b_n, rel)
            print(f"{name:28}{w:9.2f}{c:8.1%}{s:8.2f}{m:8.1%}{t:13.0f}x")
            if name.startswith("OLMAR"):
                changed = int((np.abs(np.diff(b_n, axis=0)).sum(axis=1) > 1e-9).sum())
                print(f"{'':28}OLMAR days the portfolio changed: {changed} of {len(b_n) - 1}")
        except Exception as e:
            print(f"{name:28} failed: {type(e).__name__}: {e}")
    spy = symbols.index("SPY") if "SPY" in symbols else None
    if spy is not None:
        w = np.cumprod(rel[:, spy])
        print(f"{'SPY buy and hold':28}{w[-1]:9.2f}{w[-1] ** (252 / len(rel)) - 1:8.1%}")

EQ = ["SPY","QQQ","IWM","DIA","EFA","EEM","XLK","XLF","XLV","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]
run(EQ, date(2016, 1, 1), date(2025, 1, 1), "17 equity ETFs (same as btest runs)")
run([s for s in EQ if s != "XLC"], date(2016, 1, 1), date(2025, 1, 1), "16 ETFs without XLC (full history)")
