import hashlib
import itertools
import json
import math
import time
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import psycopg
from psycopg.types.json import Jsonb

from btest import bars, db, loader, metrics
from btest.engine import Config
from btest.fast import FastResult, Prepared, run_fast
from btest.ingest import log
from btest.runner import _git, load_strategy_class, strategy_timeframe


def parse_grid(specs: list[str]) -> dict[str, list]:
    """'fast=5,10,20' lists values; 'slow=100:400:50' is an inclusive start:stop:step range."""
    grid = {}
    for spec in specs:
        key, sep, raw = spec.partition("=")
        if not sep or not raw:
            raise SystemExit(f"bad --grid {spec!r}, expected key=a,b,c or key=start:stop:step")
        if raw.count(":") == 2:
            start, stop, step = (json.loads(x) for x in raw.split(":"))
            n = int(math.floor((stop - start) / step + 1e-9)) + 1
            # Rounding drops float noise from repeated steps: 0.18 + 0.02 is 0.19999999999999998.
            values = [round(start + k * step, 12) for k in range(n)]
            if all(isinstance(v, int) for v in (start, stop, step)):
                values = [int(v) for v in values]
        else:
            values = [_value(v) for v in raw.split(",")]
        grid[key] = values
    return grid


def _value(s: str):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def fast_metrics(r: FastResult, rf: pl.DataFrame) -> dict:
    eq = r.equity
    m = metrics.compute(eq, rf)
    realized = r.fill_realized[~np.isnan(r.fill_realized)]
    years = (eq["date"][-1] - eq["date"][0]).days / 365.25 if eq.height > 1 else 0.0
    avg = eq["equity"].mean() if eq.height else 0.0
    traded = float(np.sum(np.abs(r.fill_qty) * r.fill_price))
    return m | {
        "fills": len(r.fill_qty),
        "win_rate": float(np.mean(realized > 0)) if len(realized) else None,
        "turnover": traded / avg / years if avg and years else None,
        "costs": r.costs,
        "exposure": r.exposure,
    }


def run_sweep(conn: psycopg.Connection, data_dir: Path, strategy_path: Path, symbol: str,
              fixed: dict, grid: dict[str, list], start: datetime, end: datetime,
              holdout_start: date, config: Config, label: str | None = None,
              strategy_version_id: int | None = None) -> tuple[int, pl.DataFrame]:
    holdout_ts = datetime.combine(holdout_start, datetime.min.time(), UTC)
    if end > holdout_ts:
        raise SystemExit(f"sweep end {end:%Y-%m-%d} reaches into the holdout, which starts "
                         f"{holdout_start}. Sweeps must stop at or before it.")
    cls = load_strategy_class(strategy_path)
    splits, dividends = db.get_splits(conn, symbol), db.get_dividends(conn, symbol)
    tf = strategy_timeframe(cls)
    data = bars.aggregate(loader.load_bars(data_dir, symbol, start, end, splits, dividends), tf)
    if data.is_empty():
        raise SystemExit(f"no bars for {symbol} in {start} to {end}")
    prep = Prepared(data, splits, dividends)
    rf = db.get_rates(conn, "DTB3")
    keys = list(grid)
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*grid.values())]
    rows, skipped = [], 0
    t0 = time.perf_counter()
    step = max(1, len(combos) // 20)
    for i, combo in enumerate(combos, 1):
        params = fixed | combo
        try:
            strat = cls(**params)
        except ValueError:
            skipped += 1
            continue
        r = run_fast(prep, strat.signals(prep.arrays), config)
        rows.append({"params": strat.params, "metrics": fast_metrics(r, rf)})
        if i % step == 0 or i == len(combos):
            log(f"sweep [{i}/{len(combos)} {100 * i / len(combos):.0f}%] {skipped} skipped")
    duration = time.perf_counter() - t0
    commit, dirty = _git() if strategy_version_id is None else (None, None)
    sweep_id = conn.execute(
        "INSERT INTO runs.sweep (strategy, strategy_sha256, symbol, start_ts, end_ts, "
        "holdout_start, fixed_params, grid, config, git_commit, git_dirty, combos, skipped, "
        "duration_s, strategy_version_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (f"{label or strategy_path.name}:{cls.__name__}",
         hashlib.sha256(strategy_path.read_bytes()).hexdigest(), symbol, start, end,
         holdout_start, Jsonb(fixed), Jsonb(grid), Jsonb(config.to_dict() | {"timeframe": tf}),
         commit, dirty,
         len(combos), skipped, duration, strategy_version_id),
    ).fetchone()[0]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO runs.sweep_result (sweep_id, seq, params, metrics) "
            "VALUES (%s, %s, %s, %s)",
            [(sweep_id, i, Jsonb(r["params"]), Jsonb(r["metrics"])) for i, r in enumerate(rows)],
        )
    conn.commit()
    table = pl.DataFrame([{**{k: r["params"][k] for k in keys}, **r["metrics"]} for r in rows])
    log(f"sweep {sweep_id}: {len(rows)} runs in {duration:.1f}s ({skipped} skipped)")
    return sweep_id, table
