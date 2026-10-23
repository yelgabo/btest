"""Every trade of strategies/intraday/vwap_band_fade.py on SPY minute bars, 2016-2024, gross of
costs (entry and exit at the next bar's open), grouped by exit reason, side and year. Extra
arguments override the strategy's params, e.g. entry_sd=2.5."""
import importlib.util
import math
import sys
from datetime import UTC, datetime

import numpy as np
import polars as pl

from btest import config, db, loader
from btest.config import ROOT

spec = importlib.util.spec_from_file_location("vbf", ROOT / "strategies/intraday/vwap_band_fade.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

params = {**mod.VWAPBandFade.params, **dict(a.split("=") for a in sys.argv[1:])}
for k in ("entry_sd", "exit_sd", "stop_sd"):
    params[k] = float(params[k])
settings = config.load(need_alpaca=False)
conn = db.connect(settings.database_url)
sp, dv = db.get_splits(conn, "SPY"), db.get_dividends(conn, "SPY")
bars = loader.load_bars(settings.data_dir, "SPY", datetime(2016, 1, 1, tzinfo=UTC),
                        datetime(2025, 1, 1, tzinfo=UTC), sp, dv)
day = bars["date"].to_numpy().astype("datetime64[D]")
m = mod.ny_minutes(bars["ts"].to_numpy(), day)
h, l, c, v, o = (bars[k].to_numpy() for k in ("high", "low", "close", "volume", "open"))
f = mod.Fader(params)
trades, cur = [], None
for i in range(len(c)):
    w = f.step(m[i], i > 0 and day[i] != day[i - 1], h[i], l[i], c[i], v[i])
    if np.isnan(w) or i + 1 >= len(c):
        continue
    if w != 0:
        cur = (i + 1, int(np.sign(w)))
    elif cur:
        ei, side = cur
        vw = f.pv / f.v
        sd = math.sqrt(max(f.pv2 / f.v - vw * vw, 0))
        z = (c[i] - vw) / sd if sd else 0
        reason = ("time" if m[i] >= f.exit_at or day[i] != day[ei]
                  else "stop" if -side * z >= params["stop_sd"] else "target")
        trades.append((str(day[ei])[:4], "long" if side > 0 else "short", reason, i + 1 - ei,
                       side * (o[i + 1] / o[ei] - 1) * 1e4))
        cur = None
t = pl.DataFrame(trades, schema=["year", "side", "reason", "bars", "bps"], orient="row")
pl.Config.set_tbl_rows(20)
print(params)
print(f"trades {t.height}, mean gross {t['bps'].mean():.2f} bp, median {t['bps'].median():.2f} bp, "
      f"win {(t['bps'] > 0).mean():.1%}")
agg = [pl.len().alias("n"), pl.col("bps").mean().round(2).alias("mean_bp"),
       pl.col("bps").sum().round(0).alias("sum_bp"), pl.col("bars").median().alias("med_bars")]
for key in ("reason", "side", "year"):
    print(t.group_by(key).agg(agg).sort(key))
