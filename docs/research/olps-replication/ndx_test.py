"""The authors' unmodified algorithms on current NASDAQ-100 members, 2016-2024, their method
(close-to-close, missing price ratio = 1.0), Alpaca daily bars adjusted for splits and
dividends. Survivorship-biased: today's members only."""
import os

# Folder holding spreads.json, ndx.txt and the authors' repo (olps-repo/); defaults to here.
WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
import sys, math, time
from datetime import date
import httpx, numpy as np, polars as pl
SCR = WORK
sys.path[:0] = [OLPS + "/Scripts", OLPS + "/Scripts/Strategies"]
import follow_the_loser as ftl
from btest import config
s = config.load()
H = {"APCA-API-KEY-ID": s.alpaca_key, "APCA-API-SECRET-KEY": s.alpaca_secret}
# SPCX before 2026 is an unrelated SPAC ETF that used the same ticker.
syms = [x for x in open(SCR + "/ndx.txt").read().split() if x != "SPCX"]
c = httpx.Client(base_url="https://data.alpaca.markets", headers=H, timeout=60)
frames = []
for i, sym in enumerate(syms, 1):
    rows, token = [], None
    while True:
        p = {"timeframe": "1Day", "start": "2016-01-01T00:00:00Z", "end": "2025-01-01T00:00:00Z",
             "adjustment": "all", "feed": "sip", "limit": 10000}
        if token: p["page_token"] = token
        r = c.get(f"/v2/stocks/{sym}/bars", params=p)
        if r.status_code == 429: time.sleep(3); continue
        r.raise_for_status(); d = r.json(); rows += d.get("bars") or []; token = d.get("next_page_token")
        if not token: break
    if rows:
        frames.append(pl.DataFrame({"date": [x["t"][:10] for x in rows], sym: [float(x["c"]) for x in rows]}))
    if i % 25 == 0: print(f"[{i}/{len(syms)}] fetched", flush=True)
m = frames[0]
for f in frames[1:]:
    m = m.join(f, on="date", how="full", coalesce=True)
m = m.sort("date")
full = [x for x in m.columns if x != "date" and m[x].null_count() == 0]
print(f"{len(frames)} tickers with data, {len(full)} with the full 2016-2024 history, {m.height} days")
def matrix(cols):
    prices = m.select(cols).fill_null(strategy="forward").to_numpy()
    rel = prices[1:] / prices[:-1]
    return np.where(np.isnan(rel), 1.0, rel)
def evaluate(b_n, earn, cost_bps=0.0):
    wealth, path, prev = 1.0, [], None
    for t in range(len(earn)):
        if prev is not None:
            drift = prev * earn[t - 1]; drift /= drift.sum()
            wealth *= 1 - np.abs(b_n[t] - drift).sum() * cost_bps / 1e4
        wealth *= float(b_n[t] @ earn[t]); path.append(wealth); prev = b_n[t]
    path = np.array(path); r = path[1:] / path[:-1] - 1
    to = np.abs(np.diff(b_n, axis=0)).sum(axis=1).mean() * 252
    return path[-1] ** (252 / len(earn)) - 1, r.mean() / r.std() * math.sqrt(252), (path / np.maximum.accumulate(path) - 1).min(), to
for label, cols in [("all current members (late listings held at ratio 1.0, as the paper does)", [x for x in m.columns if x != "date"]),
                    ("members with full 2016-2024 history", full)]:
    rel = matrix(cols); n = rel.shape[1]; b0 = np.full(n, 1 / n)
    print(f"\n{label}: {n} stocks")
    crp = np.tile(b0, (len(rel), 1))
    print(f"  {'CRP daily':24}{evaluate(crp, rel)[0]:8.1%}  Sharpe {evaluate(crp, rel)[1]:.2f}")
    for name, f in {"CWMR (their variant)": ftl.cwmr, "PAMR (their settings)": ftl.pamr}.items():
        b = np.asarray(f(b0, rel))
        out = [evaluate(b, rel, k) for k in (0, 1, 3, 5)]
        lag = evaluate(b[:-1], rel[1:])
        print(f"  {name:24}" + "  ".join(f"{k}bp {o[0]:6.1%} (Sh {o[1]:.2f})" for k, o in zip((0, 1, 3, 5), out))
              + f"  | 1-day delay {lag[0]:6.1%}  | maxDD {out[0][2]:.0%}  turnover {out[0][3]:.0f}x")

from math import erf
def jk(r1, r2):
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std(); rho = np.corrcoef(r1, r2)[0, 1]; T = len(r1)
    z = (s1 - s2) / math.sqrt((2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T)
    return (s1 - s2) * math.sqrt(252), z, 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2))))
def dret(b_n, rel, cost=0.0):
    out, prev = [], None
    for t in range(len(rel)):
        c = 0.0
        if prev is not None and cost:
            d = prev * rel[t - 1]; d = d / d.sum(); c = np.abs(b_n[t] - d).sum() * cost / 1e4
        out.append((1 - c) * float(b_n[t] @ rel[t]) - 1); prev = b_n[t]
    return np.array(out)
for label, cols in [("all members", [x for x in m.columns if x != "date"]), ("full history", full)]:
    rel = matrix(cols); k = rel.shape[1]; b0 = np.full(k, 1 / k); r_crp = dret(np.tile(b0, (len(rel), 1)), rel)
    for name, f in {"CWMR": ftl.cwmr, "PAMR": ftl.pamr}.items():
        b = np.asarray(f(b0, rel))
        for cost in (0, 1):
            d, z, pv = jk(dret(b, rel, cost), r_crp)
            print(f"  paired vs CRP, {label:12} {name} {cost}bp: Sharpe diff {d:+.2f}, z {z:+.2f}, p {pv:.2f}")
