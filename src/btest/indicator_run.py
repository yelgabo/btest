"""Parent side of custom indicators: load candles with warm-up, run the child, trim."""

import math
import os
import sys
import threading
from datetime import UTC, date, datetime, timedelta

from btest import bars, db, lab
from btest.worker_proc import run_child

TIMEOUT_S = 20
# A couple at a time: each child is a fresh Python with numpy loaded.
SLOTS = threading.BoundedSemaphore(2)


def warmup_candles(params: dict) -> int:
    ints = [v for v in params.values() if isinstance(v, int) and not isinstance(v, bool)]
    return min(5000, 3 * max(ints, default=0) + 10)


def child_env() -> dict:
    keep = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({"HOME": "/tmp", "POLARS_MAX_THREADS": "2", "NUMBA_NUM_THREADS": "2",
                "OMP_NUM_THREADS": "2"})
    return env


def series(settings, conn_factory, code: str, name: str, params: dict, symbol: str,
           start: date, end: date, tf: str) -> dict:
    info = lab.inspect_code(code, "indicator")
    if info.error:
        return {"error": info.error, "error_line": info.error_line}
    merged = {**info.params, **{k: v for k, v in params.items() if k in info.params}}
    extra = warmup_candles(merged)
    per_day = 1 if bars.TIMEFRAMES[tf] is None else math.ceil(390 / bars.TIMEFRAMES[tf])
    pad_days = math.ceil(extra / per_day * 365 / 252) + 5
    load_from = max(settings.history_start, start - timedelta(days=pad_days))
    with conn_factory() as conn:
        splits, dividends = db.get_splits(conn, symbol), db.get_dividends(conn, symbol)
    candles = bars.candles(settings.data_dir, symbol, load_from, end, tf, splits, dividends)
    with SLOTS:
        result, log = run_child([sys.executable, "-m", "btest.indicator_child"],
                                {"code": code, "name": name, "params": merged, "candles": candles},
                                TIMEOUT_S, child_env(), "indicator")
    if result.get("error"):
        return {"error": result["error"], "error_line": result.get("error_line"), "log": log}
    first = int(datetime.combine(start, datetime.min.time(), UTC).timestamp())
    cut = next((i for i, t in enumerate(candles["t"]) if t >= first), len(candles["t"]))
    return {"t": candles["t"][cut:], "series": {k: v[cut:] for k, v in result["series"].items()},
            "pane": info.pane, "levels": info.levels or [], "params": merged}
