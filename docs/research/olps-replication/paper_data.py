"""The authors' own 1998-2009 data and unmodified functions: reproduce Tables 3-4, then change
one assumption at a time (costs, one-day delay, two suspected bad prints, full-history tickers)."""
import os

# Folder holding spreads.json, ndx.txt and the authors' repo (olps-repo/); defaults to here.
WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
import math, sys
import numpy as np, pandas as pd
SCR = WORK
sys.path[:0] = [OLPS + "/Scripts", OLPS + "/Scripts/Strategies"]
import follow_the_loser as ftl, follow_the_winner as ftw
from utilities import calculate_cumulative_wealth_over_time, compute_periodic_returns, compute_sharpe_ratio

df = pd.read_csv(OLPS + "/Data/Price Relative Vectors/price_relative_vectors.csv", index_col=0)
rel_all = df.to_numpy(float)
print(f"{df.shape[1]} tickers, {df.shape[0]} days, {df.index[0]} to {df.index[-1]}")

# Reproduction of Tables 3-4 to four decimals, via the authors' notebook path.
import benchmarks as bm
_n = rel_all.shape[1]; _b0 = np.full(_n, 1 / _n)
def _final(b_n):
    return calculate_cumulative_wealth_over_time(b_n, rel_all)[-1]
print("reproduction (final wealth):", {k: round(float(v), 4) for k, v in {
    "CWMR": _final(ftl.cwmr(_b0, rel_all)), "PAMR": _final(ftl.pamr(_b0, rel_all)),
    "Anticor": _final(ftl.anticor(_b0, rel_all)), "RMR": _final(ftl.rmr(_b0, rel_all)),
    "OLMAR": _final(ftl.olmar(_b0, rel_all)), "FTRL": _final(ftw.follow_the_regularized_leader(_b0, rel_all)),
    "EG": _final(ftw.exponential_gradient(_b0, rel_all)), "CRP": _final(np.tile(_b0, (len(rel_all), 1))),
    "Buy and hold": float(np.mean(np.prod(rel_all, axis=0)))}.items()})
for _name, _f in [("OLMAR", ftl.olmar), ("EG", ftw.exponential_gradient)]:
    _b = np.asarray(_f(_b0, rel_all))
    print(f"{_name}: days the target weights changed: {int((np.abs(np.diff(_b, axis=0)).sum(axis=1) > 1e-12).sum())} of {len(_b) - 1}")
_lead = [c for c in df.columns if (df[c].values == 1.0).cumprod().sum() > 20]
_tail = [c for c in df.columns if (df[c].values[::-1] == 1.0).cumprod().sum() > 20]
print(f"tickers with >20 leading placeholder days: {len(_lead)}; with >20 trailing: {_tail}")

# Spike-and-reverse pairs: a ratio below 0.6 followed the next day by one above 1.6, or vice versa.
pairs = []
for j, t in zip(*np.where(((rel_all[:-1] < 0.6) & (rel_all[1:] > 1.6)) | ((rel_all[:-1] > 1.6) & (rel_all[1:] < 0.6)))[::-1]):
    pairs.append((df.columns[j], df.index[t], rel_all[t, j], rel_all[t + 1, j]))
print("spike-and-reverse pairs:", [(a, b, round(c, 3), round(d, 3)) for a, b, c, d in sorted(pairs)])

def stats(b_n, rel, cost_bps=0.0):
    wealth, path, prev = 1.0, [], None
    for t in range(len(rel)):
        if prev is not None and cost_bps:
            drift = prev * rel[t - 1]; drift = drift / drift.sum()
            wealth *= 1 - np.abs(b_n[t] - drift).sum() * cost_bps / 1e4
        wealth *= float(b_n[t] @ rel[t]); path.append(wealth); prev = b_n[t]
    path = np.array(path); r = path[1:] / path[:-1] - 1
    yrs = len(rel) / 252
    return path[-1], path[-1] ** (1 / yrs) - 1, compute_sharpe_ratio(r, 252, 0.05), r.mean() / r.std() * math.sqrt(252)

def table(rel, label):
    n = rel.shape[1]; b0 = np.full(n, 1 / n)
    print(f"\n{label}: {n} tickers. wealth / CAGR / Sharpe (rf 5%, paper) / Sharpe (no rf)")
    crp = np.tile(b0, (len(rel), 1))
    algos = {"CRP": lambda: crp, "CWMR": lambda: ftl.cwmr(b0, rel), "PAMR": lambda: ftl.pamr(b0, rel),
             "Anticor": lambda: ftl.anticor(b0, rel), "FTRL": lambda: ftw.follow_the_regularized_leader(b0, rel)}
    for name, f in algos.items():
        b = np.asarray(f())
        rows = {"A paper": stats(b, rel), "A +1bp": stats(b, rel, 1), "A +5bp": stats(b, rel, 5),
                "A +10bp": stats(b, rel, 10), "one-day delay": stats(b[:-1], rel[1:]),
                "delay +5bp": stats(b[:-1], rel[1:], 5)}
        print(f"  {name:8}" + "  ".join(f"{k} {w:,.1f} ({c:.1%}, {s1:.2f}/{s2:.2f})" for k, (w, c, s1, s2) in rows.items()))

table(rel_all, "All 93 tickers (paper sample)")
fixed = rel_all.copy()
for name, d, a, b in pairs:
    j, t = df.columns.get_loc(name), df.index.get_loc(d)
    fixed[t, j] = fixed[t + 1, j] = 1.0
table(fixed, f"Same, with the {len(pairs)} spike-and-reverse pairs set to 1.0")
lead = (rel_all == 1.0)
full = [j for j in range(rel_all.shape[1]) if not lead[:20, j].all() and (rel_all[:, j] != 1.0).mean() > 0.97]
table(rel_all[:, full], "Tickers with data over (almost) the whole sample")

def daily_returns(b_n, rel, cost_bps=0.0):
    out, prev = [], None
    for t in range(len(rel)):
        c = 0.0
        if prev is not None and cost_bps:
            drift = prev * rel[t - 1]; drift = drift / drift.sum()
            c = np.abs(b_n[t] - drift).sum() * cost_bps / 1e4
        out.append((1 - c) * float(b_n[t] @ rel[t]) - 1); prev = b_n[t]
    return np.array(out)
def jk(r1, r2):
    from math import erf
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std(); rho = np.corrcoef(r1, r2)[0, 1]; T = len(r1)
    z = (s1 - s2) / math.sqrt((2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / T)
    return (s1 - s2) * math.sqrt(252), z, 2 * (1 - 0.5 * (1 + erf(abs(z) / math.sqrt(2))))
n = rel_all.shape[1]; b0 = np.full(n, 1 / n); crp = np.tile(b0, (len(rel_all), 1))
bc = np.asarray(ftl.cwmr(b0, rel_all)); bp = np.asarray(ftl.pamr(b0, rel_all))
r_crp = daily_returns(crp, rel_all)
print("\nPaired Sharpe tests vs CRP on the paper's data (annualized difference, z, p):")
r_crp_lag = daily_returns(crp[:-1], rel_all[1:])
for label, r, base in [("CWMR A", daily_returns(bc, rel_all), r_crp), ("CWMR A +10bp", daily_returns(bc, rel_all, 10), r_crp),
                       ("CWMR one-day delay", daily_returns(bc[:-1], rel_all[1:]), r_crp_lag),
                       ("CWMR delay +5bp", daily_returns(bc[:-1], rel_all[1:], 5), r_crp_lag),
                       ("PAMR A", daily_returns(bp, rel_all), r_crp), ("PAMR A +10bp", daily_returns(bp, rel_all, 10), r_crp),
                       ("PAMR one-day delay", daily_returns(bp[:-1], rel_all[1:]), r_crp_lag),
                       ("PAMR delay +5bp", daily_returns(bp[:-1], rel_all[1:], 5), r_crp_lag),
                       ("PAMR delay +10bp", daily_returns(bp[:-1], rel_all[1:], 10), r_crp_lag)]:
    d, z, p = jk(r, base); rho = np.corrcoef(r, base)[0, 1]
    print(f"  {label:22}{d:+6.2f}  z {z:+5.2f}  p {p:.4f}  rho {rho:.2f}")
