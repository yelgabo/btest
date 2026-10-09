"""Paired tests for the cross-asset strategies of 2026-10-09 (website runs 94-96): trend (GTAA) and
inverse volatility against equal weight in the same 15 ETFs and against SPY, 1999-2024. Reads the
saved daily equity; nothing is rerun. Sharpe differences are tested on daily returns in excess of
the 3-month T-bill rate, because the trend strategy holds T-bills much of the time and raw returns
would count their interest as a reward for risk; the raw-return version (the working paper's
convention, for fully invested strategies) is printed too. Jobson-Korkie with Memmel's correction
and a moving-block bootstrap; return leads use daily log returns. Both
bootstraps are centred, two-sided, 10,000 draws, at five block lengths, with Holm-adjusted p over
the five comparisons at each block length. Same method as the replication's cwmr_etf.stats."""
import math

import numpy as np
import psycopg

from btest import config, db

RUNS = {"Trend (GTAA)": 94, "Inverse volatility": 95, "Equal weight": 96}
PAIRS = [("Trend (GTAA)", "Equal weight"), ("Inverse volatility", "Equal weight"),
         ("Trend (GTAA)", "SPY"), ("Inverse volatility", "SPY"), ("Equal weight", "SPY")]
BLOCKS = (1, 5, 21, 63, 126)


def jkm(r1, r2):
    s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
    rho = np.corrcoef(r1, r2)[0, 1]
    var = (2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2)) / len(r1)
    z = (s1 - s2) / math.sqrt(var)
    return (s1 - s2) * math.sqrt(252), 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def bootstrap(stat, r1, r2, block, draws=10_000, seed=0):
    """Centred two-sided p and 95% interval for stat(r1, r2) under a moving-block bootstrap."""
    observed = stat(r1, r2)
    rng = np.random.default_rng(seed)
    n, k = len(r1), len(r1) // block
    out = np.empty(draws)
    for j in range(draws):
        idx = (rng.integers(0, n - block + 1, k)[:, None] + np.arange(block)).ravel()
        out[j] = stat(r1[idx], r2[idx])
    p = float(np.mean(np.abs(out - out.mean()) >= abs(observed)))
    return observed, p, np.percentile(out, 2.5), np.percentile(out, 97.5)


def sharpe_diff(a, b):
    return (a.mean() / a.std() - b.mean() / b.std()) * math.sqrt(252)


def lead(a, b):
    return (np.log1p(a) - np.log1p(b)).mean() * 252


def holm(p):
    adjusted, running = np.empty(len(p)), 0.0
    for rank, k in enumerate(np.argsort(p)):
        running = max(running, min(1.0, (len(p) - rank) * p[k]))
        adjusted[k] = running
    return adjusted


s = config.load(need_alpaca=False)
series = {}
with psycopg.connect(s.database_url) as conn:
    for name, rid in RUNS.items():
        rows = conn.execute("SELECT date, equity, benchmark FROM runs.equity WHERE run_id = %s "
                            "ORDER BY date", (rid,)).fetchall()
        series[name] = {d: e for d, e, _ in rows}
        series.setdefault("SPY", {d: b for d, _, b in rows})
    rates = db.get_rates(conn, "DTB3")
dates = sorted(set.intersection(*(set(v) for v in series.values())))
returns = {}
for name, v in series.items():
    eq = np.array([v[d] for d in dates])
    returns[name] = eq[1:] / eq[:-1] - 1
# The T-bill rate known on each day, as btest.metrics uses it: annual percent over 252 days.
rate_dates, rate_values = rates["date"].to_list(), rates["rate"].to_list()
rf, k = [], 0
for d in dates[1:]:
    while k + 1 < len(rate_dates) and rate_dates[k + 1] <= d:
        k += 1
    rf.append(rate_values[k] / 100 / 252 if rate_dates[k] <= d else 0.0)
rf = np.array(rf)
excess = {name: r - rf for name, r in returns.items()}
print(f"{dates[0]} to {dates[-1]}, {len(dates) - 1} daily returns")

for title, stat, data in (("Sharpe difference over T-bills", sharpe_diff, excess),
                          ("Sharpe difference on raw returns", sharpe_diff, returns),
                          ("Annual log-return lead", lead, returns)):
    print(f"\n{title}; bootstrap p by block length {BLOCKS}, then Holm over the "
          f"{len(PAIRS)} comparisons at each block length")
    by_block = []
    for k in BLOCKS:
        by_block.append([bootstrap(stat, data[a], data[b], k) for a, b in PAIRS])
    adjusted = [holm(np.array([r[1] for r in rows])) for rows in by_block]
    for j, (a, b) in enumerate(PAIRS):
        observed, _, lo, hi = by_block[2][j]
        extra = f"  JKM p {jkm(data[a], data[b])[1]:.3f}" if stat is sharpe_diff else ""
        unit = "{:+.2f}" if stat is sharpe_diff else "{:+.2%}"
        print(f"  {a + ' vs ' + b:36} {unit.format(observed)} [21-day 95% interval "
              f"{unit.format(lo)}, {unit.format(hi)}]{extra}")
        print(f"      p {', '.join(f'{r[j][1]:.3f}' for r in by_block)}  | Holm "
              f"{', '.join(f'{h[j]:.3f}' for h in adjusted)}")
