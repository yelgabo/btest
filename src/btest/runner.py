import hashlib
import importlib.util
import inspect
import subprocess
import time
from datetime import datetime
from pathlib import Path

import polars as pl
import psycopg

from btest import db, loader, metrics
from btest.config import ROOT
from btest.engine import Config, Engine, Result
from btest.strategy import Strategy

BENCHMARK = "SPY"


def load_strategy_class(path: Path) -> type[Strategy]:
    spec = importlib.util.spec_from_file_location(f"btest_user_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = [obj for _, obj in inspect.getmembers(module, inspect.isclass)
             if issubclass(obj, Strategy) and obj is not Strategy
             and obj.__module__ == module.__name__]
    if len(found) != 1:
        raise SystemExit(f"{path}: expected exactly one Strategy subclass, found {len(found)}")
    return found[0]


def daily_close(bars: pl.DataFrame) -> pl.DataFrame:
    return bars.group_by("date").agg(pl.col("close").sort_by("ts").last()).sort("date")


def benchmark_equity(bars: pl.DataFrame, dates: pl.Series, cash: float) -> pl.DataFrame:
    """Buy-and-hold on adjusted closes, which include reinvested dividends."""
    closes = daily_close(bars)
    out = pl.DataFrame({"date": dates}).join(closes, on="date", how="left")
    out = out.with_columns(pl.col("close").forward_fill().backward_fill())
    first = out["close"][0]
    return out.select("date", (pl.col("close") / first * cash).alias("benchmark"))


def _git() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "strategies"],
                               cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip() != ""
        return commit, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, None


def run_backtest(conn: psycopg.Connection, data_dir: Path, strategy_path: Path, params: dict,
                 symbols: list[str], start: datetime, end: datetime, config: Config,
                 label: str | None = None,
                 strategy_version_id: int | None = None) -> tuple[int, dict, dict, Result]:
    cls = load_strategy_class(strategy_path)
    strategy = cls(**params)
    splits = {s: db.get_splits(conn, s) for s in symbols}
    dividends = {s: db.get_dividends(conn, s) for s in symbols}
    data = {s: loader.load_bars(data_dir, s, start, end, splits[s], dividends[s])
            for s in symbols}
    for s, df in data.items():
        if df.is_empty():
            raise SystemExit(f"no bars for {s} in {start} to {end}; run `btest ingest {s}`")

    t0 = time.perf_counter()
    result = Engine(data, config, splits, dividends).run(strategy)
    duration = time.perf_counter() - t0

    bench_bars = data.get(BENCHMARK)
    if bench_bars is None:
        bench_bars = loader.load_bars(data_dir, BENCHMARK, start, end,
                                      db.get_splits(conn, BENCHMARK),
                                      db.get_dividends(conn, BENCHMARK))
    equity = result.equity.join(
        benchmark_equity(bench_bars, result.equity["date"], config.cash), on="date", how="left",
    )
    rf = db.get_rates(conn, "DTB3")
    stats = metrics.compute(equity, rf) | metrics.trade_stats(result.fills, equity) | {
        "exposure": result.exposure, "bars": result.bars, "engine_s": duration,
    }
    bench = metrics.compute(equity.select("date", pl.col("benchmark").alias("equity")), rf)
    # Lab strategies are versioned in the database, so the repo commit says nothing about them.
    commit, dirty = _git() if strategy_version_id is None else (None, None)
    run_id = db.save_run(conn, {
        "strategy": f"{label or strategy_path.name}:{cls.__name__}",
        "strategy_sha256": hashlib.sha256(strategy_path.read_bytes()).hexdigest(),
        "params": strategy.params,
        "symbols": symbols,
        "start_ts": start,
        "end_ts": end,
        "config": config.to_dict(),
        "git_commit": commit,
        "git_dirty": dirty,
        "metrics": stats,
        "benchmark_metrics": bench,
        "duration_s": duration,
        "strategy_version_id": strategy_version_id,
    }, result.fills, equity)
    return run_id, stats, bench, result
