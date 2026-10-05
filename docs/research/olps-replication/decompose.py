"""Where does the paper's edge go? The authors' unmodified algorithms, one assumption at a time.
  A  paper method: signal from day t close, earn close t -> close t+1, no costs
  B  A + costs: 1 bp (and 5 bp) on every dollar traded, with drifted weights
  C  one-day delay: signal from close t, earn close t+1 -> close t+2 (trade the next close)
  D  btest timing: signal from the 15:14 price, earn 15:45 -> next day's 15:45, no costs
  E  D + 1 bp"""
import os

# Folder holding spreads.json, ndx.txt and the authors' repo (olps-repo/); defaults to here.
WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
import sys, math
from datetime import date
import numpy as np, polars as pl, psycopg
REPO = OLPS + "/Scripts"
sys.path[:0] = [REPO, REPO + "/Strategies"]
import follow_the_loser as ftl
from btest import config, daily, db

EQ = ["SPY","QQQ","IWM","DIA","EFA","EEM","XLK","XLF","XLV","XLE","XLI","XLY","XLP","XLU","XLB","XLRE"]
START, END = date(2016, 1, 1), date(2025, 1, 1)
s = config.load(need_alpaca=False)
with psycopg.connect(s.database_url) as conn:
    sess = db.get_sessions(conn, date(2000, 1, 1), date(2100, 1, 1))
    frames = []
    for sym in EQ:
        df = daily.load(s.data_dir, sym, sess, daily.Timing(), db.get_splits(conn, sym), db.get_dividends(conn, sym))
        df = df.filter((pl.col("date") >= START) & (pl.col("date") < END)).with_columns(
            (pl.col("fill") * pl.col("close") / pl.col("raw_close")).alias("fill_adj"))
        frames.append(df.select("date", pl.col("close").alias(f"c_{sym}"), pl.col("cut_close").alias(f"k_{sym}"),
                                pl.col("fill_adj").alias(f"f_{sym}")))
m = frames[0]
for f in frames[1:]:
    m = m.join(f, on="date", how="inner")
m = m.sort("date").fill_nan(None).fill_null(strategy="forward").fill_null(strategy="backward")
close = np.column_stack([m[f"c_{x}"].to_numpy() for x in EQ])
cut = np.column_stack([m[f"k_{x}"].to_numpy() for x in EQ])
fill = np.column_stack([m[f"f_{x}"].to_numpy() for x in EQ])
n = len(EQ); b0 = np.full(n, 1 / n)
rel_close = close[1:] / close[:-1]          # row t: close t -> t+1
rel_cut = cut[1:] / cut[:-1]
rel_fill = fill[1:] / fill[:-1]

def evaluate(b_n, earn, cost_bps=0.0):
    """b_n[t] is held over earn[t]. Costs charged on the trade from drifted weights to b_n[t]."""
    wealth, path, prev = 1.0, [], None
    traded_total = 0.0
    for t in range(len(earn)):
        if prev is not None:
            drift = prev * earn[t - 1]; drift = drift / drift.sum()
            traded = np.abs(b_n[t] - drift).sum()
            traded_total += traded
            wealth *= 1 - traded * cost_bps / 10_000
        wealth *= float(b_n[t] @ earn[t]); path.append(wealth); prev = b_n[t]
    path = np.array(path)
    yrs = len(earn) / 252
    r = path[1:] / path[:-1] - 1
    return path[-1] ** (1 / yrs) - 1, r.mean() / r.std() * math.sqrt(252), (path / np.maximum.accumulate(path) - 1).min(), traded_total / yrs

algos = {"CWMR (their variant)": ftl.cwmr, "PAMR (their settings)": ftl.pamr, "Anticor": ftl.anticor}
print(f"16 ETFs, {m['date'][0]} to {m['date'][-1]}; CAGR / Sharpe (no rf) / max DD / turnover per year")
spy = EQ.index("SPY")
r_spy = rel_close[:, spy] - 1
print(f"SPY buy and hold, close to close: {np.prod(rel_close[:, spy]) ** (252 / len(rel_close)) - 1:.1%}, Sharpe {r_spy.mean() / r_spy.std() * math.sqrt(252):.2f}, maxDD {(np.cumprod(rel_close[:, spy]) / np.maximum.accumulate(np.cumprod(rel_close[:, spy])) - 1).min():.1%}")
bad = [(c, i) for c in m.columns if c != "date" for i in np.where(np.isnan(m[c].to_numpy()))[0]]
print("missing after fill:", [(c, str(m["date"][i])) for c, i in bad])
crp = np.tile(b0, (len(rel_close), 1))
print(f"{'CRP daily':24} A {evaluate(crp, rel_close)[0]:.1%}   B1bp {evaluate(crp, rel_close, 1)[0]:.1%}")
for name, f in algos.items():
    b_paper = np.asarray(f(b0, rel_close))           # signal from closes
    b_cut = np.asarray(f(b0, rel_cut))               # signal from 15:14 prices
    rows = {
        "A paper method": evaluate(b_paper, rel_close),
        "B +1 bp": evaluate(b_paper, rel_close, 1),
        "B +5 bp": evaluate(b_paper, rel_close, 5),
        "C one-day delay": evaluate(b_paper[:-1], rel_close[1:]),
        "D btest timing": evaluate(b_cut, rel_fill),
        "E btest timing +1 bp": evaluate(b_cut, rel_fill, 1),
    }
    print(f"\n{name}")
    for k, (c, sh, dd, to) in rows.items():
        print(f"  {k:22}{c:8.1%}{sh:7.2f}{dd:8.1%}{to:8.0f}x")

# F: btest's lab version keeps only the last 252 sessions of memory (rebuilt each decision).
def windowed(f, rel, w=252):
    out = np.tile(b0, (len(rel), 1))
    for t in range(w + 1, len(rel)):
        out[t] = np.asarray(f(b0, rel[t - w - 1:t]))[-1]
    return out
b_w = windowed(ftl.cwmr, rel_cut)
skip = 253
full_cut = np.asarray(ftl.cwmr(b0, rel_cut))
print("\nCWMR memory length, btest timing, from session 253 on (both invested):")
print(f"  {'full history, 0 bp':24}{evaluate(full_cut[skip:], rel_fill[skip:])[0]:8.1%}")
print(f"  {'full history, 1 bp':24}{evaluate(full_cut[skip:], rel_fill[skip:], 1)[0]:8.1%}")
print(f"  {'last 252 sessions, 0 bp':24}{evaluate(b_w[skip:], rel_fill[skip:])[0]:8.1%}")
print(f"  {'last 252 sessions, 1 bp':24}{evaluate(b_w[skip:], rel_fill[skip:], 1)[0]:8.1%}")
print(f"  {'SPY same span':24}{np.prod(rel_fill[skip:, spy]) ** (252 / len(rel_fill[skip:])) - 1:8.1%}")

# G: measured per-symbol half-spreads (Alpaca SIP quotes at 15:45, 30 sampled sessions).
import json
hs = json.load(open(WORK + "/spreads.json"))
cvec = np.array([hs[x] for x in EQ])

def evaluate_vec(b_n, earn, cost_vec):
    wealth, path, prev = 1.0, [], None
    for t in range(len(earn)):
        if prev is not None:
            drift = prev * earn[t - 1]; drift = drift / drift.sum()
            wealth *= 1 - float(np.abs(b_n[t] - drift) @ cost_vec) / 10_000
        wealth *= float(b_n[t] @ earn[t]); path.append(wealth); prev = b_n[t]
    path = np.array(path); r = path[1:] / path[:-1] - 1
    return path[-1] ** (252 / len(earn)) - 1, r.mean() / r.std() * math.sqrt(252)

print("\nWith measured half-spreads (one half-spread per dollar traded):")
for name, f in algos.items():
    bp, bc = np.asarray(f(b0, rel_close)), np.asarray(f(b0, rel_cut))
    a = evaluate_vec(bp, rel_close, cvec); d = evaluate_vec(bc, rel_fill, cvec)
    print(f"  {name:24} paper method {a[0]:6.1%} (Sharpe {a[1]:.2f})   btest timing {d[0]:6.1%} (Sharpe {d[1]:.2f})")
# Break-even flat cost for CWMR vs SPY, paper method
bp = np.asarray(ftl.cwmr(b0, rel_close)); spy_c = np.prod(rel_close[:, spy]) ** (252 / len(rel_close)) - 1
lo, hi = 0.0, 5.0
for _ in range(30):
    mid = (lo + hi) / 2
    (lo, hi) = (mid, hi) if evaluate(bp, rel_close, mid)[0] > spy_c else (lo, mid)
print(f"  CWMR break-even flat cost vs SPY (paper method): {lo:.2f} bp per dollar traded")
bc = np.asarray(ftl.cwmr(b0, rel_cut)); spy_f = np.prod(rel_fill[:, spy]) ** (252 / len(rel_fill)) - 1
lo, hi = 0.0, 5.0
for _ in range(30):
    mid = (lo + hi) / 2
    (lo, hi) = (mid, hi) if evaluate(bc, rel_fill, mid)[0] > spy_f else (lo, mid)
print(f"  CWMR break-even flat cost vs SPY (btest timing): {lo:.2f} bp per dollar traded")

# H: engine-style input. History rows are close-to-close; the decision day's row is the 15:14
# price over yesterday's close (what btest's port feeds the algorithm). Earn fill to fill.
def cwmr_step(mu, sigma, x, eps=0.89, theta=0.92, eta=0.93):
    k = len(mu); denom = x @ sigma @ x
    lam = eta * max(0.0, (mu @ x - eps) / (denom + 1e-15)) if denom > 0 else 0.0
    mu = mu - lam * (sigma @ x)
    inv = np.linalg.inv(sigma + np.eye(k) * 1e-12) + 2 * lam * theta * np.outer(x, x)
    return ftl.project_to_simplex(mu), np.linalg.inv(inv)
mu, sig = b0.copy(), np.eye(n)
b_engine = np.tile(b0, (len(rel_fill), 1))
for t in range(1, len(rel_fill)):
    # Decision on day t (row t of the earn series starts at day t's fill).
    if t >= 2:
        mu, sig = cwmr_step(mu, sig, close[t - 1] / close[t - 2])   # completed day t-1
    today = cut[t] / close[t - 1]
    b_engine[t], _ = cwmr_step(mu, sig, today)
print("\nCWMR input definition, earning 15:45 fill to fill:")
print(f"  {'15:14 over 15:14 (row D)':34}{evaluate(np.asarray(ftl.cwmr(b0, rel_cut)), rel_fill)[0]:7.1%}")
print(f"  {'closes, today 15:14 over close':34}{evaluate(b_engine, rel_fill)[0]:7.1%}   +1 bp {evaluate(b_engine, rel_fill, 1)[0]:7.1%}")
lo, hi = 0.0, 5.0
spy_f = np.prod(rel_fill[:, spy]) ** (252 / len(rel_fill)) - 1
for _ in range(30):
    mid = (lo + hi) / 2
    (lo, hi) = (mid, hi) if evaluate(b_engine, rel_fill, mid)[0] > spy_f else (lo, mid)
print(f"  engine-style break-even vs SPY (CAGR): {lo:.2f} bp; SPY fill-to-fill {spy_f:.1%}")

# I: paired Sharpe test (Jobson-Korkie with Memmel's correction) and start-date sensitivity.
def returns(b_n, earn, cost_vec=None, cost_bps=0.0):
    out, prev = [], None
    for t in range(len(earn)):
        c = 0.0
        if prev is not None:
            drift = prev * earn[t - 1]; drift = drift / drift.sum()
            d = np.abs(b_n[t] - drift)
            c = float(d @ cost_vec) / 1e4 if cost_vec is not None else d.sum() * cost_bps / 1e4
        out.append((1 - c) * float(b_n[t] @ earn[t]) - 1); prev = b_n[t]
    return np.array(out)

def jk_memmel(r1, r2):
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]; T = len(r1)
    v = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T
    z = (s1 - s2) / math.sqrt(v)
    from math import erf
    p = 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2))))
    return (s1 - s2) * math.sqrt(252), z, p, rho

spy_close = rel_close[:, spy] - 1; spy_fill = rel_fill[:, spy] - 1
crp_close = returns(crp, rel_close)
cw_a = returns(np.asarray(ftl.cwmr(b0, rel_close)), rel_close)
cw_a_cost = returns(np.asarray(ftl.cwmr(b0, rel_close)), rel_close, cvec)
cw_e_cost = returns(b_engine, rel_fill, cvec)
print("\nPaired Sharpe tests (annualized Sharpe difference, z, p, correlation), no risk-free rate:")
for label, a, b in [("CWMR A vs SPY", cw_a, spy_close), ("CWMR A vs CRP", cw_a, crp_close),
                    ("CWMR A measured spreads vs SPY", cw_a_cost, spy_close),
                    ("CWMR A measured spreads vs CRP", cw_a_cost, crp_close),
                    ("CWMR engine-style measured spreads vs SPY", cw_e_cost, spy_fill)]:
    d, z, p, rho = jk_memmel(a, b)
    print(f"  {label:44}{d:+6.2f}  z {z:+5.2f}  p {p:.2f}  rho {rho:.2f}")
diff = cw_a - spy_close
se = diff.std() / math.sqrt(len(diff)) * 252
print(f"  CWMR A minus SPY: mean {diff.mean() * 252:+.1%} a year, SE {se:.1%} (95% CI {diff.mean() * 252 - 1.96 * se:+.1%} to {diff.mean() * 252 + 1.96 * se:+.1%})")

dates_arr = np.array(m["date"].to_list()[1:])
print("\nStart-date sensitivity (CWMR restarted from equal weights each January), method A, no costs:")
print(f"  {'start':6}{'CWMR':>8}{'CRP':>8}{'SPY':>8}{'CWMR, measured spreads':>25}")
for y in range(2016, 2024):
    k = int(np.searchsorted(dates_arr, date(y, 1, 1)))
    sub = rel_close[k:]
    bw = np.asarray(ftl.cwmr(b0, sub))
    yrs = len(sub) / 252
    f = lambda r: (np.prod(1 + r)) ** (1 / yrs) - 1
    print(f"  {y:<6}{f(returns(bw, sub)):8.1%}{f(returns(crp[k:], sub)):8.1%}{f(sub[:, spy] - 1):8.1%}{f(returns(bw, sub, cvec)):25.1%}")
print("\nCalendar-year return differences, CWMR (2016 start, method A, no costs) minus SPY:")
yrs_lab = np.array([d.year for d in dates_arr])
print("  " + "  ".join(f"{y}: {np.prod(1 + cw_a[yrs_lab == y]) - np.prod(1 + spy_close[yrs_lab == y]):+.1%}" for y in range(2016, 2025)))
