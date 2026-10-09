"""The working paper's holdout table (Section 7), read from the stored website run 73. Nothing is
run on 2025 onward: this only reads the run's saved equity curve and metrics."""
import math

import numpy as np
import polars as pl
import psycopg

from btest import config, db, metrics

RUN = 73

s = config.load(need_alpaca=False)
with psycopg.connect(s.database_url) as conn:
    rows = conn.execute("SELECT date, equity, benchmark FROM runs.equity WHERE run_id = %s "
                        "ORDER BY date", (RUN,)).fetchall()
    rf = db.get_rates(conn, "DTB3")
eq = pl.DataFrame(rows, schema=["date", "equity", "benchmark"], orient="row")
strat = metrics.compute(eq.select("date", "equity"), rf)
bench = metrics.compute(eq.select("date", pl.col("benchmark").alias("equity")), rf)
a, b = eq["equity"].to_numpy(), eq["benchmark"].to_numpy()
r1, r2 = a[1:] / a[:-1] - 1, b[1:] / b[:-1] - 1
s1, s2 = r1.mean() / r1.std(), r2.mean() / r2.std()
rho = np.corrcoef(r1, r2)[0, 1]
z = (s1 - s2) / math.sqrt((2 - 2 * rho + 0.5 * (s1 ** 2 + s2 ** 2 - 2 * s1 * s2 * rho ** 2))
                          / len(r1))
p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
months = (eq.with_columns(pl.col("date").dt.strftime("%Y-%m").alias("m"))
          .group_by("m", maintain_order=True)
          .agg(pl.col("equity").last(), pl.col("benchmark").last()))
# The run ends on 2026-10-02, so October 2026 is a partial month and is left out.
months = months.slice(0, months.height - 1)
prev_e, prev_b, beat = a[0], b[0], 0
for e, bm in zip(months["equity"], months["benchmark"]):
    beat += (e / prev_e) > (bm / prev_b)
    prev_e, prev_b = e, bm
print(f"run {RUN}: {eq['date'][0]} to {eq['date'][-1]}, {eq.height} sessions, "
      f"{eq.height - 1} daily returns")
for name, m in (("Monthly CWMR", strat), ("SPY", bench)):
    print(f"  {name:13} CAGR {m['cagr']:.2%}  Sharpe {m['sharpe']:.2f}  "
          f"max DD {m['max_drawdown']:.1%}")
print(f"  JKM p {p:.2f}; beat SPY in {beat} of {months.height} full months")
